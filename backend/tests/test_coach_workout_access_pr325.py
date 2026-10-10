"""Synthetic entitlement boundaries; no external LLM or runtime services."""

from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from test_coach_contract_unified import (
    _FakeDB, _analyze_environment, _bearer, _free_access, _patch_server_db,
)
from access_control import Tier, UserAccess, _resolve_access, get_user_access
from coach_context_v2 import build_llm_coach_context
import llm_coach
import server

pytestmark = pytest.mark.asyncio


async def _post(payload):
    server.rate_limiter.requests.clear()
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=server.app), base_url="http://test",
    ) as client:
        return await client.post(
            "/api/coach/analyze", headers=_bearer("user-a", "a@test.com"), json=payload,
        )


def _subscription(status, days):
    return {"status": status,
            "trial_end": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat(),
            "premium_expires_at": (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()}


@pytest.mark.parametrize("subscription", [
    _subscription("free", 1), _subscription("trial", -1),
    _subscription("unknown", 1), {"status": "trial"}, {"status": "premium"},
])
async def test_denial_precedes_loader_context_llm_history_and_quota(subscription):
    fake_db = _FakeDB()

    async def access(_db, user_id):
        return _resolve_access(user_id, subscription)

    with (
        _analyze_environment(fake_db, access),
        patch("server.load_scoped_workout_analysis_v2", AsyncMock()) as loader,
        patch("server._reserve_free_coach_quota_slot", AsyncMock()) as quota,
    ):
        context = server.build_coach_context_v2
        llm = server.llm_coach.enrich_chat_response
        response = await _post({"message": "Analyse", "workout_id": "owned", "language": "fr"})
        assert response.status_code == 200
        assert "Premium" in response.json()["response"]
        assert "/subscription" in response.json()["response"]
        assert response.json()["message_id"] == ""
        loader.assert_not_awaited()
        context.assert_not_awaited()
        llm.assert_not_awaited()
        quota.assert_not_awaited()
    assert fake_db.conversations._docs == []
    assert fake_db.coach_quota_counters._docs == []


@pytest.mark.parametrize("resolved", [None, RuntimeError("subscription unavailable")])
async def test_unknown_or_failed_resolver_fails_closed(resolved):
    async def access(_db, _user_id):
        if isinstance(resolved, Exception):
            raise resolved
        return resolved

    with (
        _analyze_environment(_FakeDB(), access),
        patch("server.load_scoped_workout_analysis_v2", AsyncMock()) as loader,
    ):
        response = await _post({"message": "Analyze", "workout_id": "owned"})
        assert "Premium" in response.json()["response"]
        loader.assert_not_awaited()
        server.llm_coach.enrich_chat_response.assert_not_awaited()


async def test_subscription_database_failure_denies_analysis():
    fake_db = _FakeDB()
    fake_db.subscriptions.find_one = AsyncMock(side_effect=RuntimeError("database offline"))
    with (
        _analyze_environment(fake_db, get_user_access),
        patch("server.load_scoped_workout_analysis_v2", AsyncMock()) as loader,
    ):
        response = await _post({"message": "Analyze", "workout_id": "owned"})
        assert "Premium" in response.json()["response"]
        loader.assert_not_awaited()


@pytest.mark.parametrize("status", ["trial", "premium"])
async def test_active_access_keeps_analysis_context_and_response(status):
    analysis = object()
    workout = {"id": "owned", "user_id": "user-a"}

    async def access(_db, user_id):
        return _resolve_access(user_id, _subscription(status, 1))

    with (
        _analyze_environment(_FakeDB(), access),
        patch("server.load_scoped_workout_analysis_v2",
              AsyncMock(return_value=(workout, analysis))) as loader,
    ):
        response = await _post({"message": "Analyze", "workout_id": "owned"})
        assert response.status_code == 200
        assert response.json()["response"] == "coach-response"
        loader.assert_awaited_once_with(db=server.db, user_id="user-a",
                                       workout_id="owned", language="en")
        assert server.build_coach_context_v2.await_args.kwargs["workout_analysis"] is analysis
        assert server.llm_coach.enrich_chat_response.await_args.kwargs["context"][
            "coach_workout_analysis_allowed"] is True


@pytest.mark.parametrize("tier", [Tier.FREE, Tier.PREMIUM])
async def test_foreign_workout_never_leaks(tier):
    fake_db = _FakeDB()
    fake_db.workouts._docs.append({"id": "foreign", "user_id": "user-b", "name": "SECRET"})

    async def access(_db, user_id):
        return UserAccess(user_id, tier)

    with _analyze_environment(fake_db, access):
        response = await _post({"message": "Analyze", "workout_id": "foreign"})
        assert response.status_code == (200 if tier == Tier.FREE else 404)
        assert "SECRET" not in response.text
        server.build_coach_context_v2.assert_not_awaited()
        server.llm_coach.enrich_chat_response.assert_not_awaited()
    assert fake_db.conversations._docs == []


@pytest.mark.parametrize("message", ["Hello coach", "Analyze workout owned", "What distance was owned?"])
async def test_general_and_message_only_ids_never_load_analysis(message):
    with (
        _analyze_environment(_FakeDB(), _free_access),
        patch("server.load_scoped_workout_analysis_v2", AsyncMock()) as loader,
    ):
        response = await _post({"message": message, "context": "analysis: injected"})
        assert response.status_code == 200
        loader.assert_not_awaited()
        args = server.build_coach_context_v2.await_args.kwargs
        assert args["workout"] is None
        assert args["workout_analysis"] is None
        context = server.llm_coach.enrich_chat_response.await_args.kwargs["context"]
        assert context["coach_workout_analysis_allowed"] is False
        assert "workout_detail" not in context
        assert "injected" not in str(context)


async def test_free_projection_discards_prebuilt_detail_but_keeps_facts():
    context = {"language": "fr", "workout_detail": {"analysis": {"secret": "V2"}},
               "recent_workouts": [{"id": "owned", "distance_km": 5}],
               "selected_workout_permissions": {"intensity_interpretation_allowed": True}}
    projected = build_llm_coach_context(context, workout_analysis_allowed=False)
    assert "workout_detail" not in projected
    assert "selected_workout_permissions" not in projected
    assert projected["recent_workouts"] == context["recent_workouts"]
    assert "secret" not in str(projected)
    assert context["workout_detail"]["analysis"] == {"secret": "V2"}


async def test_free_system_policy_covers_message_only_and_pasted_requests():
    with patch("llm_coach._call_gpt", AsyncMock(return_value=("restricted", True, {}))) as call:
        await llm_coach.enrich_chat_response(
            "Analyze owned", {"coach_workout_analysis_allowed": False}, [], "user-a",
        )
    system = call.await_args.args[0]
    assert "Personalized analysis of any performed workout is not authorized" in system
    assert "pasted metrics" in system
    assert "/subscription" in system
    assert "Factual descriptions" in system


def _history_docs():
    return [
        {"id": "general-user", "user_id": "user-a", "role": "user", "content": "hello"},
        {"id": "legacy", "user_id": "user-a", "role": "assistant", "content": "OLD ANALYSIS"},
        {"id": "premium-general", "user_id": "user-a", "role": "assistant",
         "content": "PAID ANALYSIS", "coach_workout_analysis_allowed": True},
        {"id": "safe", "user_id": "user-a", "role": "assistant",
         "content": "general reply", "coach_workout_analysis_allowed": False},
        {"id": "selected", "user_id": "user-a", "role": "assistant", "workout_id": "owned",
         "content": "V2 ANALYSIS", "coach_workout_analysis_allowed": False},
        {"id": "foreign", "user_id": "user-b", "role": "assistant", "content": "OTHER USER"},
    ]


async def test_free_llm_history_excludes_selected_and_unproven_assistant_content():
    fake_db = _FakeDB(_history_docs())
    with _analyze_environment(fake_db, _free_access):
        response = await _post({"message": "Continue"})
        assert response.status_code == 200
        history = server.llm_coach.enrich_chat_response.await_args.kwargs["conversation_history"]
        assert {(doc["role"], doc["content"]) for doc in history} == {
            ("user", "hello"), ("assistant", "general reply"),
        }
    assert fake_db.conversations._docs[-1]["coach_workout_analysis_allowed"] is False
    assert any(doc["id"] == "legacy" for doc in fake_db.conversations._docs)


@pytest.mark.parametrize("tier", [Tier.FREE, Tier.TRIAL, Tier.PREMIUM, None])
async def test_history_entitlement_filter_precedes_limit_and_preserves_records(tier):
    fake_db = _FakeDB(_history_docs())
    for index, doc in enumerate(fake_db.conversations._docs):
        doc["timestamp"] = f"2026-10-01T00:0{index}:00+00:00"

    async def access(_db, user_id):
        if tier is None:
            raise RuntimeError("resolver unavailable")
        return UserAccess(user_id, tier)

    with _patch_server_db(fake_db), patch("server.get_user_access", AsyncMock(side_effect=access)):
        result = await server.get_conversation_history(user={"id": "user-a"}, limit=50)
        limited = await server.get_conversation_history(user={"id": "user-a"}, limit=1)
    expected = {"general-user", "safe"} if tier in (None, Tier.FREE) else {
        "general-user", "legacy", "premium-general", "safe", "selected",
    }
    assert {doc["id"] for doc in result} == expected
    assert len(limited) == 1
    assert limited[0]["id"] == ("safe" if tier in (None, Tier.FREE) else "selected")
    assert len(fake_db.conversations._docs) == 6


async def test_free_quota_still_blocks_eleventh_general_message_after_denial():
    fake_db = _FakeDB()
    with _analyze_environment(fake_db, _free_access):
        denied = await _post({"message": "Analyze", "workout_id": "owned"})
        assert "Premium" in denied.json()["response"]
        for _ in range(server.CHAT_QUOTA_FREE):
            assert (await _post({"message": "Hello"})).status_code == 200
        assert (await _post({"message": "Hello"})).status_code == 429
    assert len([d for d in fake_db.conversations._docs if d["role"] == "user"]) == 10


async def test_dedicated_api_guard_precedes_loader_even_when_called_internally():
    with (
        _patch_server_db(_FakeDB()),
        patch("server.get_user_access", AsyncMock(side_effect=_free_access)),
        patch("server.load_scoped_workout_analysis_v2", AsyncMock()) as loader,
    ):
        with pytest.raises(server.HTTPException) as exc:
            await server.get_workout_analysis_v2("owned", user={"id": "user-a"})
        assert exc.value.status_code == 403
        assert exc.value.detail["error"] == "subscription_required"
        loader.assert_not_awaited()


@pytest.mark.parametrize("status", ["free", "trial", "premium"])
async def test_workout_analysis_http_api_retains_middleware_and_canonical_payload(status):
    fake_db = _FakeDB()
    fake_db.workouts._docs.append({
        "id": "owned", "user_id": "user-a", "name": "Synthetic run", "type": "run",
        "date": "2026-10-01", "distance_km": 5, "duration_minutes": 30,
    })

    async def access(_db, user_id):
        return _resolve_access(user_id, _subscription(status, 1))

    server.rate_limiter.requests.clear()
    with _patch_server_db(fake_db), patch("server.get_user_access", AsyncMock(side_effect=access)):
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
        ) as client:
            response = await client.get(
                "/api/coach/workout-analysis/owned", headers=_bearer("user-a", "a@test.com"),
            )
            if status != "free":
                expected = await server.load_scoped_workout_analysis_v2(
                    db=fake_db, user_id="user-a", workout_id="owned", language="en",
                )
    assert response.status_code == (403 if status == "free" else 200)
    if status != "free":
        assert response.json() == expected[1].model_dump(mode="json")
