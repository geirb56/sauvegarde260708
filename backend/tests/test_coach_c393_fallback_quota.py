"""C393 — LLM failure fallback (H1) and Free quota refund (H2).

All MongoDB access and the LLM are mocked; no provider or network is reached.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from access_control import Tier, UserAccess
from narrative_coach_v3_models import NarrativeCoachV3
from test_coach_contract_unified import (
    _FakeDB, _STUB_REPLIES, _analyze_environment, _free_access, _premium_access, _send_analyze_request,
    _trial_access, _current_month_key, _month_ts,
)
import server

pytestmark = pytest.mark.asyncio


def _llm(result):
    async def call(**_kwargs):
        if isinstance(result, Exception):
            raise result
        return result
    return AsyncMock(side_effect=call)


def _narrative():
    return NarrativeCoachV3(
        headline="Session headline", analysis="Observed 10 km.", interpretation="",
        recommendation="SHOULD NOT APPEAR", limitations=["Limited data."],
        language="en", generation_mode="deterministic_fallback",
    )


async def _post(payload, user_id="user-a"):
    server.rate_limiter.requests.clear()
    import httpx
    from test_coach_contract_unified import _bearer
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://test",
    ) as client:
        return await client.post(
            "/api/coach/analyze", headers=_bearer(user_id, f"{user_id}@test.com"), json=payload,
        )


def _count(fake_db, user_id="user-a"):
    docs = [d for d in fake_db.coach_quota_counters._docs if d["user_id"] == user_id]
    return docs[0]["count"] if docs else None


def _owned_workout(fake_db):
    fake_db.workouts._docs.append({"id": "w1", "user_id": "user-a"})
    return patch("server.load_scoped_workout_analysis_v2",
                 AsyncMock(return_value=({"id": "w1", "user_id": "user-a"}, object())))


FAILURES = [
    ("timeout", (None, False, {"success": False})),
    ("provider_error", (None, False, {})),
    ("empty", ("", True, {})),
    ("none_text", (None, True, {})),
]


# ---------------------------------------------------------------- H1


async def test_llm_success_consumes_quota_and_persists_both_messages():
    fake_db = _FakeDB()
    with _analyze_environment(fake_db, _free_access):
        response = await _post({"message": "hi", "language": "en"})
    assert response.status_code == 200
    assert response.json()["response"] == _STUB_REPLIES["en"]
    assert response.json()["degraded"] is False
    assert _count(fake_db) == 1
    assert [d["role"] for d in fake_db.conversations._docs] == ["user", "assistant"]


@pytest.mark.parametrize("language,fragment", [
    ("fr", "n'est pas disponible"), ("es", "no está disponible"), ("en", "currently unavailable"),
])
@pytest.mark.parametrize("name,result", FAILURES)
async def test_general_chat_failure_is_explicit_503_localized(name, result, language, fragment):
    fake_db = _FakeDB()
    with _analyze_environment(fake_db, _free_access):
        server.llm_coach.enrich_chat_response.side_effect = _llm(result)
        response = await _post({"message": "hi", "language": language})
    assert response.status_code == 503
    assert fragment in response.json()["detail"]
    assert _count(fake_db) == 0
    assert [d["role"] for d in fake_db.conversations._docs] == ["user"]


@pytest.mark.parametrize("name,result", FAILURES)
@pytest.mark.parametrize("access", [_trial_access, _premium_access])
async def test_selected_workout_failure_returns_degraded_factual_reply(name, result, access):
    fake_db = _FakeDB()
    with (
        _analyze_environment(fake_db, access),
        _owned_workout(fake_db),
        patch("server.load_scoped_workout_coach_evidence",
              AsyncMock(return_value=(_narrative(), None))) as fallback,
    ):
        llm = server.llm_coach.enrich_chat_response
        llm.side_effect = _llm(result)
        response = await _post({"message": "analyse", "workout_id": "w1", "language": "en"})
    body = response.json()
    assert response.status_code == 200
    assert body["degraded"] is True and body["message_id"] == ""
    assert "temporarily unavailable" in body["response"]
    assert "Observed 10 km." in body["response"] and "Limited data." in body["response"]
    assert "SHOULD NOT APPEAR" not in body["response"]  # no competing prescription
    assert llm.await_count == 1  # no second LLM call
    fallback.assert_awaited_once_with(db=fake_db, user_id="user-a", workout_id="w1", language="en")
    assert [d["role"] for d in fake_db.conversations._docs] == ["user"]


@pytest.mark.parametrize("language,fragment", [
    ("fr", "temporairement indisponible"), ("es", "no está disponible temporalmente"),
    ("en", "temporarily unavailable"),
])
async def test_degraded_notice_is_localized(language, fragment):
    fake_db = _FakeDB()
    with (
        _analyze_environment(fake_db, _trial_access),
        _owned_workout(fake_db),
        patch("server.load_scoped_workout_coach_evidence",
              AsyncMock(return_value=(_narrative(), None))),
    ):
        server.llm_coach.enrich_chat_response.side_effect = _llm((None, False, {}))
        response = await _post({"message": "x", "workout_id": "w1", "language": language})
    assert fragment in response.json()["response"]


@pytest.mark.parametrize("narrative", [
    None,
    NarrativeCoachV3(generation_mode="none"),
    NarrativeCoachV3(generation_mode="deterministic_fallback"),
])
async def test_selected_workout_without_usable_synthesis_is_503(narrative):
    fake_db = _FakeDB()
    with (
        _analyze_environment(fake_db, _trial_access),
        _owned_workout(fake_db),
        patch("server.load_scoped_workout_coach_evidence", AsyncMock(return_value=(narrative, None))),
    ):
        server.llm_coach.enrich_chat_response.side_effect = _llm((None, False, {}))
        response = await _post({"message": "x", "workout_id": "w1"})
    assert response.status_code == 503


async def test_fallback_loader_exception_is_503_not_fake_success():
    fake_db = _FakeDB()
    with (
        _analyze_environment(fake_db, _trial_access),
        _owned_workout(fake_db),
        patch("server.load_scoped_workout_coach_evidence",
              AsyncMock(side_effect=RuntimeError("boom"))),
    ):
        server.llm_coach.enrich_chat_response.side_effect = _llm((None, False, {}))
        response = await _post({"message": "x", "workout_id": "w1"})
    assert response.status_code == 503


async def test_access_denied_has_no_fallback_no_llm_no_quota():
    fake_db = _FakeDB()
    with (
        _analyze_environment(fake_db, _free_access),
        patch("server.load_scoped_workout_coach_evidence", AsyncMock()) as fallback,
    ):
        response = await _post({"message": "x", "workout_id": "w1", "language": "en"})
        assert response.status_code == 200 and response.json()["degraded"] is False
        fallback.assert_not_awaited()
        server.llm_coach.enrich_chat_response.assert_not_awaited()
    assert fake_db.coach_quota_counters._docs == [] and fake_db.conversations._docs == []


async def test_foreign_workout_never_reaches_fallback():
    fake_db = _FakeDB()
    with (
        _analyze_environment(fake_db, _trial_access),
        patch("server.load_scoped_workout_coach_evidence", AsyncMock()) as fallback,
    ):
        response = await _post({"message": "x", "workout_id": "foreign"})
    assert response.status_code == 404
    fallback.assert_not_awaited()


async def test_internal_context_error_is_not_masked_and_refunds():
    fake_db = _FakeDB()
    with _analyze_environment(fake_db, _free_access):
        server.build_coach_context_v2.side_effect = RuntimeError("context broke")
        server.rate_limiter.requests.clear()
        import httpx
        from test_coach_contract_unified import _bearer
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/coach/analyze", headers=_bearer("user-a", "a@test.com"),
                json={"message": "x"},
            )
    assert response.status_code == 500
    assert _count(fake_db) == 0
    assert fake_db.conversations._docs == []


async def test_deterministic_loader_never_calls_provider():
    from workout_intelligence_v3_service import load_scoped_workout_deterministic_narrative

    intelligence = object()
    v2 = SimpleNamespace(phase_analysis=None, coach_language=None)
    with (
        patch("workout_intelligence_v3_service._load_scoped_workout_intelligence_v3",
              AsyncMock(return_value=({}, intelligence, None, v2))),
        patch("narrative_coach_v3.deterministic_fallback", return_value=_narrative()) as det,
        patch("narrative_coach_v3.generate_narrative_coach_v3", AsyncMock()) as gen,
        patch("llm_coach._call_gpt", AsyncMock()) as gpt,
    ):
        result = await load_scoped_workout_deterministic_narrative(
            db=object(), user_id="u", workout_id="w", language="en",
        )
    assert result.generation_mode == "deterministic_fallback"
    det.assert_called_once()
    gen.assert_not_awaited()
    gpt.assert_not_awaited()


async def test_deterministic_loader_none_when_not_owned_or_no_intelligence():
    from workout_intelligence_v3_service import load_scoped_workout_deterministic_narrative

    for loaded in (None, ({}, None, None, None)):
        with patch("workout_intelligence_v3_service._load_scoped_workout_intelligence_v3",
                   AsyncMock(return_value=loaded)):
            assert await load_scoped_workout_deterministic_narrative(
                db=object(), user_id="u", workout_id="w", language="en") is None


# ---------------------------------------------------------------- H2


@pytest.mark.parametrize("name,result", FAILURES)
async def test_refund_after_failure_even_with_persisted_user_message(name, result):
    fake_db = _FakeDB()
    with _analyze_environment(fake_db, _free_access):
        server.llm_coach.enrich_chat_response.side_effect = _llm(result)
        response = await _post({"message": "x"})
    assert response.status_code == 503
    assert _count(fake_db) == 0
    user = fake_db.conversations._docs[0]
    assert user["role"] == "user" and user["quota_refunded"] is True


async def test_failure_before_user_message_persistence_refunds():
    fake_db = _FakeDB()
    fake_db.conversations.insert_one = AsyncMock(side_effect=RuntimeError("insert failed"))
    with _analyze_environment(fake_db, _free_access):
        import httpx
        from test_coach_contract_unified import _bearer
        server.rate_limiter.requests.clear()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/coach/analyze", headers=_bearer("user-a", "a@test.com"), json={"message": "x"},
            )
    assert response.status_code == 500
    assert _count(fake_db) == 0


async def test_assistant_persistence_failure_refunds_once():
    fake_db = _FakeDB()
    original = fake_db.conversations.insert_one

    async def insert(doc):
        if doc["role"] == "assistant":
            raise RuntimeError("assistant insert failed")
        return await original(doc)

    fake_db.conversations.insert_one = insert
    with (
        _analyze_environment(fake_db, _free_access),
        patch("server._release_free_coach_quota_slot", wraps=server._release_free_coach_quota_slot) as release,
    ):
        import httpx
        from test_coach_contract_unified import _bearer
        server.rate_limiter.requests.clear()
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/api/coach/analyze", headers=_bearer("user-a", "a@test.com"), json={"message": "x"},
            )
        assert release.await_count == 1
    assert response.status_code == 500
    assert _count(fake_db) == 0


async def test_llm_failure_releases_exactly_once():
    fake_db = _FakeDB()
    with (
        _analyze_environment(fake_db, _free_access),
        patch("server._release_free_coach_quota_slot", wraps=server._release_free_coach_quota_slot) as release,
    ):
        server.llm_coach.enrich_chat_response.side_effect = _llm((None, False, {}))
        await _post({"message": "x"})
        assert release.await_count == 1


async def test_refund_failure_does_not_mask_original_error():
    fake_db = _FakeDB()
    with (
        _analyze_environment(fake_db, _free_access),
        patch("server._release_free_coach_quota_slot", AsyncMock(side_effect=RuntimeError("db down"))),
    ):
        server.llm_coach.enrich_chat_response.side_effect = _llm((None, False, {}))
        response = await _post({"message": "x"})
    assert response.status_code == 503


async def test_repeat_after_error_keeps_cap_and_never_goes_negative():
    fake_db = _FakeDB()
    with _analyze_environment(fake_db, _free_access):
        llm = server.llm_coach.enrich_chat_response
        llm.side_effect = _llm((None, False, {}))
        for _ in range(15):
            assert (await _post({"message": "x"})).status_code == 503
            assert _count(fake_db) == 0
        llm.side_effect = _llm(("ok", True, {}))
        for _ in range(10):
            assert (await _post({"message": "x"})).status_code == 200
        assert _count(fake_db) == 10
        assert (await _post({"message": "x"})).status_code == 429
        assert _count(fake_db) == 10


async def test_failure_near_cap_restores_last_slot_then_success_consumes_it():
    fake_db = _FakeDB()
    with _analyze_environment(fake_db, _free_access):
        llm = server.llm_coach.enrich_chat_response
        for _ in range(9):
            assert (await _post({"message": "x"})).status_code == 200
        llm.side_effect = _llm((None, False, {}))
        assert (await _post({"message": "x"})).status_code == 503
        assert _count(fake_db) == 9
        llm.side_effect = _llm(("ok", True, {}))
        assert (await _post({"message": "x"})).status_code == 200
        assert _count(fake_db) == 10
        assert (await _post({"message": "x"})).status_code == 429


async def test_release_is_floored_at_baseline():
    fake_db = _FakeDB()
    fake_db.coach_quota_counters._docs.append({
        "user_id": "user-a", "month_key": _current_month_key(), "count": 3, "baseline": 3,
    })
    with patch.object(server, "db", fake_db):
        await server._release_free_coach_quota_slot(
            {"user_id": "user-a", "month_key": _current_month_key(), "baseline": 3},
        )
    assert fake_db.coach_quota_counters._docs[0]["count"] == 3


async def test_concurrent_failures_do_not_double_refund_or_go_negative():
    fake_db = _FakeDB()
    with _analyze_environment(fake_db, _free_access):
        async def slow_fail(**_kwargs):
            await asyncio.sleep(0)
            return None, False, {}

        server.llm_coach.enrich_chat_response.side_effect = slow_fail
        server.rate_limiter.requests.clear()
        results = await asyncio.gather(*[_send_analyze_request() for _ in range(4)])
    assert all(r.status_code == 503 for r in results)
    assert _count(fake_db) == 0


async def test_concurrent_success_and_failure_at_8_of_10_ends_at_9_then_fills_cap():
    fake_db = _FakeDB()
    fake_db.coach_quota_counters._docs.append({
        "user_id": "user-a", "month_key": _current_month_key(), "count": 8, "baseline": 0,
    })
    arrived = 0
    both_admitted = asyncio.Event()

    async def llm(**_kwargs):
        nonlocal arrived
        arrived += 1
        mine = arrived
        if arrived == 2:
            both_admitted.set()
        await both_admitted.wait()
        return ("ok", True, {}) if mine == 1 else (None, False, {})

    with _analyze_environment(fake_db, _free_access):
        server.llm_coach.enrich_chat_response.side_effect = llm
        server.rate_limiter.requests.clear()
        results = await asyncio.gather(*[_send_analyze_request() for _ in range(2)])
        assert sorted(r.status_code for r in results) == [200, 503]
        assert _count(fake_db) == 9
        server.llm_coach.enrich_chat_response.side_effect = _llm(("ok", True, {}))
        assert (await _post({"message": "x"})).status_code == 200
        assert _count(fake_db) == 10
        assert (await _post({"message": "x"})).status_code == 429
        assert _count(fake_db) == 10


async def test_history_clear_does_not_reset_quota_after_failures():
    fake_db = _FakeDB()
    with _analyze_environment(fake_db, _free_access):
        for _ in range(3):
            await _post({"message": "x"})
        server.llm_coach.enrich_chat_response.side_effect = _llm((None, False, {}))
        await _post({"message": "x"})
        assert _count(fake_db) == 3
        with patch("server.get_user_access", AsyncMock(side_effect=_free_access)):
            result = await server.clear_conversation_history(user={"id": "user-a"})
        assert result["deleted_count"] > 0
        assert _count(fake_db) == 3


async def test_refunded_messages_are_excluded_from_bootstrap_baseline():
    fake_db = _FakeDB()
    fake_db.conversations._docs += [
        {"id": "1", "user_id": "user-a", "role": "user", "timestamp": _month_ts(1)},
        {"id": "2", "user_id": "user-a", "role": "user", "timestamp": _month_ts(2), "quota_refunded": True},
    ]
    with _analyze_environment(fake_db, _free_access):
        count = await server._get_or_bootstrap_free_coach_quota_count(
            user_id="user-a", now_utc=server.datetime.now(server.timezone.utc),
        )
    assert count == 1


# ------------------------------------------------- non-regression


@pytest.mark.parametrize("access", [_trial_access, _premium_access])
async def test_unlimited_users_have_no_counter_and_normal_success(access):
    fake_db = _FakeDB()
    with _analyze_environment(fake_db, access):
        response = await _post({"message": "hi"})
    assert response.status_code == 200 and response.json()["degraded"] is False
    assert fake_db.coach_quota_counters._docs == []


async def test_failure_of_one_user_does_not_affect_another():
    fake_db = _FakeDB()
    with _analyze_environment(fake_db, _free_access):
        llm = server.llm_coach.enrich_chat_response
        assert (await _post({"message": "x"}, "user-b")).status_code == 200
        llm.side_effect = _llm((None, False, {}))
        assert (await _post({"message": "x"}, "user-a")).status_code == 503
    assert _count(fake_db, "user-a") == 0
    assert _count(fake_db, "user-b") == 1
    assert all(d["user_id"] == "user-b" for d in fake_db.conversations._docs if d["role"] == "assistant")


# ------------------------------------------- refund robustness (review)


def _request():
    return server.CoachRequest(message="x", language="en")


async def test_history_update_error_still_releases_quota():
    fake_db = _FakeDB()
    original = fake_db.conversations.update_one

    async def update(query, update_doc):
        if "quota_refunded" in update_doc.get("$set", {}):
            raise RuntimeError("history update failed")
        return await original(query, update_doc)

    fake_db.conversations.update_one = update
    with _analyze_environment(fake_db, _free_access):
        server.llm_coach.enrich_chat_response.side_effect = _llm((None, False, {}))
        response = await _post({"message": "x"})
    assert response.status_code == 503
    assert _count(fake_db) == 0
    assert "quota_refunded" not in fake_db.conversations._docs[0]


async def test_cancel_during_release_applies_exactly_one_decrement_and_flags_after():
    fake_db = _FakeDB()
    events = []
    release_started, release_gate = asyncio.Event(), asyncio.Event()
    real_release = server._release_free_coach_quota_slot
    real_update = fake_db.conversations.update_one

    async def slow_release(reservation):
        events.append("release_start")
        release_started.set()
        await release_gate.wait()
        await real_release(reservation)
        events.append("release_done")

    async def update(query, update_doc):
        if "quota_refunded" in update_doc.get("$set", {}):
            events.append("flag")
        return await real_update(query, update_doc)

    fake_db.conversations.update_one = update
    with (
        _analyze_environment(fake_db, _free_access),
        patch("server._release_free_coach_quota_slot", side_effect=slow_release) as release,
    ):
        server.llm_coach.enrich_chat_response.side_effect = _llm((None, False, {}))
        task = asyncio.ensure_future(server.process_coach_message(request=_request(), user={"id": "user-a"}))
        await release_started.wait()
        assert "flag" not in events  # not flagged before cleanup completes
        task.cancel()
        await asyncio.sleep(0)
        release_gate.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.gather(*list(server._COACH_REFUND_TASKS))
        assert release.call_count == 1
    assert events == ["release_start", "release_done", "flag"]
    assert _count(fake_db) == 0


async def test_cancel_during_llm_call_refunds_once():
    fake_db = _FakeDB()
    started = asyncio.Event()

    async def hang(**_kwargs):
        started.set()
        await asyncio.sleep(3600)

    with (
        _analyze_environment(fake_db, _free_access),
        patch("server._release_free_coach_quota_slot", wraps=server._release_free_coach_quota_slot) as release,
    ):
        server.llm_coach.enrich_chat_response.side_effect = hang
        task = asyncio.ensure_future(server.process_coach_message(request=_request(), user={"id": "user-a"}))
        await started.wait()
        assert _count(fake_db) == 1
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.gather(*list(server._COACH_REFUND_TASKS))
        assert release.call_count == 1
    assert _count(fake_db) == 0
    assert fake_db.conversations._docs[0]["quota_refunded"] is True


async def test_repeated_cancellation_during_cleanup_does_not_double_refund():
    fake_db = _FakeDB()
    release_started, release_gate = asyncio.Event(), asyncio.Event()
    real_release = server._release_free_coach_quota_slot

    async def slow_release(reservation):
        release_started.set()
        await release_gate.wait()
        await real_release(reservation)

    with (
        _analyze_environment(fake_db, _free_access),
        patch("server._release_free_coach_quota_slot", side_effect=slow_release) as release,
    ):
        server.llm_coach.enrich_chat_response.side_effect = _llm((None, False, {}))
        task = asyncio.ensure_future(server.process_coach_message(request=_request(), user={"id": "user-a"}))
        await release_started.wait()
        for _ in range(3):
            task.cancel()
            await asyncio.sleep(0)
        release_gate.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.gather(*list(server._COACH_REFUND_TASKS))
        assert release.call_count == 1
    assert _count(fake_db) == 0


async def test_cancel_while_flagging_message_does_not_redecrement():
    fake_db = _FakeDB()
    fake_db.coach_quota_counters._docs.append({
        "user_id": "user-a", "month_key": _current_month_key(), "count": 5, "baseline": 0,
    })
    flag_started, flag_gate = asyncio.Event(), asyncio.Event()
    real_update = fake_db.conversations.update_one

    async def update(query, update_doc):
        if "quota_refunded" in update_doc.get("$set", {}):
            flag_started.set()
            await flag_gate.wait()
        return await real_update(query, update_doc)

    fake_db.conversations.update_one = update
    with (
        _analyze_environment(fake_db, _free_access),
        patch("server._release_free_coach_quota_slot", wraps=server._release_free_coach_quota_slot) as release,
    ):
        server.llm_coach.enrich_chat_response.side_effect = _llm((None, False, {}))
        task = asyncio.ensure_future(server.process_coach_message(request=_request(), user={"id": "user-a"}))
        await flag_started.wait()
        task.cancel()
        await asyncio.sleep(0)
        flag_gate.set()
        with pytest.raises(asyncio.CancelledError):
            await task
        await asyncio.gather(*list(server._COACH_REFUND_TASKS))
        assert release.call_count == 1
    assert _count(fake_db) == 5
