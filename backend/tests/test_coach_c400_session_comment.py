"""C400 — automatic session comment (C396 voice on C388 facts).

MongoDB and the LLM are mocked: these tests do NOT validate real model output.
"""

import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx
import pytest

import coach_session_comment as csc
import llm_coach
from narrative_coach_v3_models import NarrativeCoachV3
from test_coach_contract_unified import (  # sets up the environment before server is imported
    _FakeDB, _analyze_environment, _bearer, _free_access, _premium_access, _trial_access,
)
import server

pytestmark = pytest.mark.asyncio

TEXTS = {
    "en": "This was a steady 10 km at 5:32 per km, and the pace stayed consistent from start to finish, which is a good sign.",
    "fr": "C'est une sortie régulière de 10 km à 5:32 par km, et le rythme est resté constant du début à la fin, ce qui est une bonne chose.",
    "es": "Fue una salida regular de 10 km a 5:32 por km, y el ritmo se mantuvo constante de principio a fin, lo que es una buena señal.",
}


class _Payload:
    def model_dump(self, mode="json"):
        return {
            "language": "en", "reference_date": "2026-01-15",
            "workout_detail": {"date": "2026-01-10", "distance_km": 10.04, "pace_display": "5:32",
                               "analysis": {"signals": {"intensity": {"available": False}}}},
        }


def _narrative(language="en"):
    return NarrativeCoachV3(
        headline="You ran 10.04 km at 5:32 per km.", analysis="Pace was consistent.",
        interpretation="Descriptive only.", limitations=["Limited history."],
        language=language, generation_mode="deterministic_fallback",
    )


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setenv("C400_SESSION_COMMENT_ENABLED", "true")
    csc.reset_state()
    yield
    csc.reset_state()


def _llm(text=TEXTS["en"], success=True):
    async def call(context, user_id="x"):
        return text, success, {}
    return AsyncMock(side_effect=call)


def _env(fake_db, access=_premium_access, owned=("user-a",), llm=None, narrative=None):
    from contextlib import ExitStack
    stack = ExitStack()
    stack.enter_context(_analyze_environment(fake_db, access))
    stack.enter_context(patch("server.build_coach_context_v2", AsyncMock(return_value=_Payload())))

    async def load(*, db, user_id, workout_id, language):
        if user_id not in owned or workout_id != "w1":
            return None
        return {"id": "w1", "user_id": user_id}, SimpleNamespace(
            model_dump=lambda mode="json": {"summary": "x", "language": language})
    stack.enter_context(patch("server.load_scoped_workout_analysis_v2", AsyncMock(side_effect=load)))
    stack.enter_context(patch(
        "server._load_coach_narrative",
        AsyncMock(side_effect=lambda **kw: narrative(kw["language"]) if callable(narrative)
                  else _narrative(kw["language"]))))
    llm_mock = llm or _llm()
    stack.enter_context(patch.object(llm_coach, "generate_session_comment", llm_mock))
    return stack, llm_mock


async def _get(user_id="user-a", workout="w1", language="en"):
    server.rate_limiter.requests.clear()
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as c:
        return await c.get(f"/api/coach/workout-comment/{workout}?language={language}",
                           headers=_bearer(user_id, f"{user_id}@test.com"))


# 1. identical facts between automatic comment and chat
async def test_comment_and_chat_receive_identical_context():
    fake_db = _FakeDB()
    stack, llm = _env(fake_db)
    with stack:
        chat_llm = server.llm_coach.enrich_chat_response
        server.rate_limiter.requests.clear()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as c:
            chat = await c.post("/api/coach/analyze", headers=_bearer("user-a", "user-a@test.com"),
                                json={"message": "analyse", "workout_id": "w1", "language": "en"})
        resp = await _get()
    assert chat.status_code == 200 and resp.status_code == 200
    assert resp.json()["status"] == "generated"
    chat_context = chat_llm.await_args.kwargs["context"]
    comment_context = llm.await_args.args[0]
    assert comment_context == chat_context
    assert "validated_workout_observations" in comment_context


# 2. permissions / subscription
async def test_free_user_forbidden_and_no_llm():
    stack, llm = _env(_FakeDB(), access=_free_access)
    with stack:
        resp = await _get()
    assert resp.status_code == 403
    llm.assert_not_awaited()


@pytest.mark.parametrize("access", [_trial_access, _premium_access])
async def test_trial_and_premium_allowed(access):
    stack, llm = _env(_FakeDB(), access=access)
    with stack:
        resp = await _get()
    assert resp.status_code == 200 and resp.json()["text"] == TEXTS["en"]
    assert resp.json()["source"] == "coach_c396"
    assert resp.json()["validation"]["level"] == "heuristic_guard"


async def test_disabled_by_default(monkeypatch):
    monkeypatch.delenv("C400_SESSION_COMMENT_ENABLED")
    stack, llm = _env(_FakeDB())
    with stack:
        resp = await _get()
    assert resp.json()["status"] == "disabled" and resp.json()["text"] is None
    llm.assert_not_awaited()


# 3. user isolation
async def test_other_users_workout_is_404_and_cache_not_shared():
    stack, llm = _env(_FakeDB(), owned=("user-a", "user-b"))
    with stack:
        assert (await _get("user-a")).status_code == 200
        assert (await _get("user-b")).status_code == 200  # same workout id, own scope
        assert llm.await_count == 2
    csc.reset_state()
    stack, llm = _env(_FakeDB(), owned=("user-a",))
    with stack:
        assert (await _get("user-a")).status_code == 200
        assert (await _get("user-b")).status_code == 404
        assert llm.await_count == 1


async def test_cache_entry_bound_to_owner():
    key = csc.cache_key(user_id="a", workout_id="w", language="en", facts={})
    csc._cache_put(key, "a", {"status": "generated"}, 60)
    assert csc._cache_get(key, "b") is None


# 4. fallback
@pytest.mark.parametrize("llm", [
    AsyncMock(side_effect=asyncio.TimeoutError()),
    AsyncMock(side_effect=RuntimeError("provider")),
    AsyncMock(return_value=(None, False, {})),
    AsyncMock(return_value=("", True, {})),
    _llm("The athlete ran 12 km at 4:10 per km and the pace is perfect and the effort was good."),
], ids=["timeout", "error", "failed", "empty", "ungrounded"])
async def test_fallback_keeps_response_usable(llm):
    stack, _ = _env(_FakeDB(), llm=llm)
    with stack:
        resp = await _get()
    body = resp.json()
    assert resp.status_code == 200
    assert body["status"] == "fallback" and body["text"] is None
    assert body["fallback"] == "deterministic_c388" and body["validation"]["passed"] is False


async def test_real_timeout_is_enforced(monkeypatch):
    monkeypatch.setattr(csc, "COMMENT_TIMEOUT_SEC", 0.05)

    async def slow(context, user_id="x"):
        await asyncio.sleep(1)
        return TEXTS["en"], True, {}
    stack, _ = _env(_FakeDB(), llm=AsyncMock(side_effect=slow))
    with stack:
        resp = await _get()
    assert resp.json()["status"] == "fallback"


async def test_no_c388_facts_means_unavailable_without_llm():
    stack, llm = _env(_FakeDB(), narrative=lambda _l: None)
    with stack:
        resp = await _get()
    assert resp.json()["status"] == "unavailable"
    llm.assert_not_awaited()


# 5. cache, invalidation, concurrency
async def test_cache_hit_and_invalidation_when_facts_change():
    stack, llm = _env(_FakeDB())
    with stack:
        first, second = await _get(), await _get()
        assert (first.json()["cached"], second.json()["cached"]) == (False, True)
        assert llm.await_count == 1
    changed = lambda lang: NarrativeCoachV3(  # noqa: E731
        headline="You ran 10.04 km at 5:32 per km.", analysis="Different fact.", interpretation="x",
        limitations=[], language=lang, generation_mode="deterministic_fallback")
    stack, llm2 = _env(_FakeDB(), narrative=changed)
    with stack:
        await _get()
        assert llm2.await_count == 1  # new facts -> new key


async def test_failures_cached_briefly_and_concurrency_deduplicated():
    async def slow(context, user_id="x"):
        await asyncio.sleep(0.05)
        return TEXTS["en"], True, {}
    stack, llm = _env(_FakeDB(), llm=AsyncMock(side_effect=slow))
    with stack:
        results = await asyncio.gather(*[_get() for _ in range(5)])
    assert llm.await_count == 1
    assert all(r.json()["text"] == TEXTS["en"] for r in results)
    csc.reset_state()
    stack, llm = _env(_FakeDB(), llm=AsyncMock(return_value=(None, False, {})))
    with stack:
        await _get()
        await _get()
    assert llm.await_count == 1


# 6. FR / EN / ES
@pytest.mark.parametrize("lang", ["fr", "en", "es"])
async def test_languages(lang):
    stack, _ = _env(_FakeDB(), llm=_llm(TEXTS[lang]))
    with stack:
        resp = await _get(language=lang)
    assert resp.json()["status"] == "generated" and resp.json()["language"] == lang


async def test_wrong_language_rejected():
    stack, _ = _env(_FakeDB(), llm=_llm(TEXTS["en"]))
    with stack:
        resp = await _get(language="fr")
    assert resp.json()["status"] == "fallback"
    assert "language" in resp.json()["validation"]["rejected_checks"]


# validation guard
CTX = {"workout_detail": {"distance_km": 10.04, "pace_display": "5:32"},
       "validated_workout_observations": {"analysis": "Steady pace."},
       "selected_workout_permissions": {"progress_regression_allowed": False}}


@pytest.mark.parametrize("text,reason", [
    ("Your LT2 was clearly crossed during this run, and the effort was really hard for you.", "unsupported_physiology"),
    ("You are progressing nicely and this session shows that your fitness is better than before.", "progress_claim"),
    ("You ran 10 km at 4:58 per km, and this is the pace that you have to hold on the run.", "ungrounded_number"),
    ("The 10 km at 5:32 per km was steady, and the next session should be a bit faster than this.", "prescription"),
    ("You felt strong during the 10 km at 5:32 per km, and the pace was steady for the whole run.", "invented_sensation"),
    ("- 10 km at 5:32 per km, and the pace was steady for the whole run that you did today.", "format"),
])
def test_guard_rejects_unsupported_claims(text, reason):
    ok, reasons = csc.validate_session_comment(text, CTX, "en")
    assert not ok and reason in reasons


def test_guard_accepts_grounded_text_and_negated_progress():
    ok, reasons = csc.validate_session_comment(TEXTS["en"], CTX, "en")
    assert ok, reasons
    text = "This 10.0 km run at 5:32 per km does not show progress on its own, and the pace was steady."
    assert csc.validate_session_comment(text, CTX, "en")[0]


# prompt unchanged / same prompt as chat
async def test_session_comment_uses_chat_prompt_without_fake_question():
    with patch.object(llm_coach, "_call_gpt", AsyncMock(return_value=("x", True, {}))) as call:
        await llm_coach.generate_session_comment(
            {"language": "en", "workout_detail": {"distance_km": 1}}, user_id="u")
    system, prompt = call.await_args.args[0], call.await_args.args[1]
    assert system.startswith(llm_coach.SYSTEM_PROMPT_COACH)
    assert "ATHLETE'S QUESTION" not in prompt and "MODE: selected_workout_initial" in prompt
    assert "AUTOMATIC SESSION COMMENT" in prompt
    assert llm_coach.LLM_MODEL == "gpt-4.1-mini"


async def test_general_chat_never_triggers_session_comment():
    stack, llm = _env(_FakeDB())
    with stack:
        server.rate_limiter.requests.clear()
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=server.app), base_url="http://test") as c:
            r = await c.post("/api/coach/analyze", headers=_bearer("user-a", "user-a@test.com"),
                             json={"message": "hello", "language": "en"})
    assert r.status_code == 200
    llm.assert_not_awaited()
