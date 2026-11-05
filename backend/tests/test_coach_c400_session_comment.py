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
        if user_id not in owned or workout_id not in ("w1", "w2"):
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
    key = csc.cache_key(user_id="a", workout_id="w", language="en", context={})
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


# validation guard — realistic selected-session context plus unrelated context
def _ctx(**perm):
    permissions = {"progress_regression_allowed": False, "physiological_efficiency_allowed": False,
                   "causal_explanation_allowed": False, "intensity_interpretation_allowed": False,
                   "similar_comparison_available": False, "similar_comparable": False}
    permissions.update(perm)
    return {
        "language": "en",
        "workout_detail": {
            "id": "w1", "date": "2026-01-10", "start_time": "2026-01-10T07:30:00",
            "distance_km": 10.04, "duration_minutes": 55.5, "avg_hr": 148.0, "avg_pace_display": "5:32",
            "elevation_gain_m": 120.0,
            "analysis": {
                "phase_analysis": {"effort_count": 4, "recovery_count": 3},
                "comparison": {"similar": {"available": True, "reference_count": 6,
                                           "baseline_pace_display": "5:50", "pace_difference_sec_per_km": -18,
                                           "baseline_avg_hr": 152}},
            },
        },
        "validated_workout_observations": {"analysis": "Pace was steady.", "limitations": []},
        "selected_workout_permissions": permissions,
        # present in the prompt but NOT facts about the selected session
        "recent_workouts": [{"distance_km": 21.1, "avg_pace_display": "4:58", "avg_hr": 171.0}],
        "today": {"distance_km": 14.0, "pace_display": "6:10"},
        "readiness": {"score": 77},
    }


def _ok(text, ctx=None, lang="en"):
    return csc.validate_session_comment(text, ctx or _ctx(), lang)


@pytest.mark.parametrize("text", [
    "The 21.1 km run was steady and the pace stayed even from the first kilometre to the last one.",
    "You ran 10 km at 4:58 per km, which is a steady and even pace for the whole of this run.",
    "Your average heart rate was 171 bpm over 10 km, which is a steady value for this run today.",
    "You ran 10 km at 6:10 per km, and the pace was steady for the whole of this run at that rate.",
    "Today's readiness of 77 and a 10 km run at 5:32 per km make for a steady and even session.",
])
def test_number_from_history_or_context_is_rejected(text):
    ok, reasons = _ok(text)
    assert not ok and any(r.startswith("ungrounded") for r in reasons), reasons


@pytest.mark.parametrize("text", [
    "You covered 10 km at 5:32 per km with an average heart rate of 148 bpm, and the pace was steady.",
    "A steady 10.0 km in 55 minutes, with 120 m of climbing and 4 efforts, was the pattern of this run.",
    "The run was 10.04 km at 5:32 per km, with a heart rate of about 148 bpm and a steady pace overall.",
    "On 10 January you ran 10 km at 5:32 per km, and the pace was steady for the whole of this run.",
])
def test_formatted_session_numbers_are_accepted(text):
    ok, reasons = _ok(text)
    assert ok, reasons


def test_wrong_unit_category_is_rejected():
    ok, reasons = _ok("This run lasted 148 minutes with a steady pace, and it was 10 km in total here.")
    assert not ok and "ungrounded_number" in reasons
    ok, reasons = _ok("You ran 10 km on 12 January at 5:32 per km, and the pace was steady all along.")
    assert not ok and "ungrounded_date" in reasons


def test_authorised_comparison_accepted_and_value_not_mistaken_for_session():
    ctx = _ctx(similar_comparison_available=True)
    ok, reasons = _ok("Compared with similar sessions, your 5:32 per km pace was faster than the 5:50 baseline.", ctx)
    assert ok, reasons
    ok, reasons = _ok("You ran 10 km at 5:50 per km, and the pace was steady for the whole of this run.", ctx)
    assert not ok and "comparison_value_as_session" in reasons


def test_unauthorised_comparison_rejected():
    ok, reasons = _ok("Compared with your earlier runs, this 10 km at 5:32 per km was a steady one overall.")
    assert not ok and "comparison_not_available" in reasons
    # the comparison figure is not usable either when comparison is not available
    ok, reasons = _ok("You ran 10 km at 5:32 per km and your usual 5:50 pace was clearly beaten today.")
    assert not ok


@pytest.mark.parametrize("text,reason", [
    ("Your LT2 was clearly crossed during this run, and the effort felt very demanding overall.", "unsupported_physiology"),
    ("With 148 bpm on average, this was an easy run and the effort stayed low for the whole session.", "intensity_not_allowed"),
    ("This steady run was done thanks to good aerobic efficiency, with an even pace all along the way.", "efficiency_not_allowed"),
    ("The pace was steady because your fitness is at a good level, and it shows over the 10 km run.", "causal_not_allowed"),
    ("You are progressing nicely and this session shows that your fitness is better than before.", "progress_claim"),
    ("You felt strong during the 10 km at 5:32 per km, and the pace was steady for the whole run.", "invented_sensation"),
    ("The 10 km at 5:32 per km was steady, and the next session should be a bit faster than this.", "prescription"),
    ("This 10 km run fits your marathon goal well, and the pace of 5:32 per km was steady all along.", "context_as_session_fact"),
    ("- 10 km at 5:32 per km, and the pace was steady for the whole run that you did today.", "format"),
    ("You did four efforts of one kilometre at a steady pace, which is what this run was all about.", "unverifiable_number_word"),
])
def test_guard_rejects_unsupported_claims(text, reason):
    ok, reasons = _ok(text)
    assert not ok and reason in reasons, reasons


def test_permissions_unlock_only_what_they_allow():
    ctx = _ctx(intensity_interpretation_allowed=True)
    ok, reasons = _ok("With 148 bpm on average, this looked like an easy run, and the pace was steady for 10 km.", ctx)
    assert "intensity_not_allowed" not in reasons
    ok, reasons = _ok("This 10 km run at 5:32 per km does not show progress on its own, and the pace was steady.")
    assert ok, reasons


@pytest.mark.parametrize("lang", ["fr", "en", "es"])
def test_language_check_accepts_natural_text_and_rejects_other_language(lang):
    ok, reasons = _ok(TEXTS[lang], lang=lang)
    assert ok, reasons
    other = "en" if lang != "en" else "fr"
    assert "language" in _ok(TEXTS[other], lang=lang)[1]


@pytest.mark.parametrize("text,lang", [
    ("Belle sortie de 10 km à 5:32 par km, avec un rythme très régulier du début à la fin de la séance.", "fr"),
    ("Una salida de 10 km a 5:32 por km, con un ritmo muy regular de principio a fin en la sesión.", "es"),
    ("A clean 10 km at 5:32 per km, with a very even pace from the start to the end of the session.", "en"),
])
def test_short_natural_formulations_not_falsely_rejected(text, lang):
    ok, reasons = _ok(text, lang=lang)
    assert ok, reasons


def test_scope_excludes_context_sections():
    session, compared = csc.split_session_facts(_ctx())
    values = {v for _, v in session}
    assert 21.1 not in values and 171.0 not in values and 77 not in values
    assert 10.04 in values and not any(p[0] == "comparison" for p, _ in session)
    assert any(v == "5:50" for _, v in compared)


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


# cache: the key covers the exact context sent to C396
async def test_context_change_between_calls_invalidates_cache():
    class Varying(_Payload):
        reference = "2026-01-15"

        def model_dump(self, mode="json"):
            data = super().model_dump(mode)
            data["reference_date"] = Varying.reference
            data["stats_7d"] = {"km": 30.0 if Varying.reference == "2026-01-15" else 42.0}
            return data

    stack, llm = _env(_FakeDB())
    with stack:
        with patch("server.build_coach_context_v2", AsyncMock(side_effect=lambda **kw: Varying())):
            first = await _get()
            again = await _get()
            Varying.reference = "2026-01-16"
            changed = await _get()
    assert (first.json()["cached"], again.json()["cached"], changed.json()["cached"]) == (False, True, False)
    assert llm.await_count == 2


async def test_two_sessions_do_not_collide():
    stack, llm = _env(_FakeDB())
    with stack:
        a, b = await _get(workout="w1"), await _get(workout="w2")
    assert a.json()["cached"] is False and b.json()["cached"] is False
    assert a.json()["workout_id"] == "w1" and b.json()["workout_id"] == "w2"
    assert llm.await_count == 2


async def test_cache_key_covers_user_workout_language_and_model(monkeypatch):
    base = dict(user_id="a", workout_id="w", language="en", context={"x": 1})
    keys = {csc.cache_key(**base)}
    for change in ({"user_id": "b"}, {"workout_id": "v"}, {"language": "fr"}, {"context": {"x": 2}}):
        keys.add(csc.cache_key(**{**base, **change}))
    monkeypatch.setattr(llm_coach, "LLM_MODEL", "other-model")
    keys.add(csc.cache_key(**base))
    assert len(keys) == 6


async def test_comment_route_builds_context_and_narrative_once():
    stack, llm = _env(_FakeDB())
    with stack, patch("server._load_coach_narrative", AsyncMock(return_value=_narrative())) as narrative:
        await _get()
    assert narrative.await_count == 1


async def test_comment_route_writes_nothing():
    fake_db = _FakeDB()
    stack, _ = _env(fake_db)
    with stack:
        await _get()
    assert fake_db.conversations._docs == []
