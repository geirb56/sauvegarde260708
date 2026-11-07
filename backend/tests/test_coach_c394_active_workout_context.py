"""C394 — validated V3 observations in the chat context, single load, isolation, prompt contract.

All MongoDB access and the LLM are mocked; fixtures are synthetic (not Garmin activities).
No provider, Garmin or network call is made. These tests do not assess LLM answer quality.
"""

from unittest.mock import AsyncMock, patch

import pytest

from narrative_coach_v3_models import NarrativeCoachV3
from test_coach_c393_fallback_quota import _llm, _owned_workout, _post
from test_coach_contract_unified import _FakeDB, _analyze_environment, _premium_access, _trial_access
import llm_coach
import server

pytestmark = pytest.mark.asyncio


def _narrative():
    return NarrativeCoachV3(
        headline="Synthetic headline", analysis="Synthetic: 3 efforts recorded.", interpretation="",
        recommendation="SHOULD NOT APPEAR", limitations=["Synthetic: no HR."],
        language="en", generation_mode="deterministic_fallback",
    )


async def test_validated_observations_reach_llm_context_once_without_recommendation():
    fake_db = _FakeDB()
    with (
        _analyze_environment(fake_db, _trial_access),
        _owned_workout(fake_db),
        patch("server.load_scoped_workout_coach_evidence",
              AsyncMock(return_value=(_narrative(), None))) as loader,
    ):
        llm = server.llm_coach.enrich_chat_response
        response = await _post({"message": "and the HR?", "workout_id": "w1", "language": "en"})
        context = llm.await_args.kwargs["context"]
    assert response.status_code == 200
    loader.assert_awaited_once()
    obs = context["validated_workout_observations"]
    assert obs["source"] == "workout_intelligence_v3_deterministic"
    assert obs["analysis"] == "Synthetic: 3 efforts recorded."
    assert obs["limitations"] == ["Synthetic: no HR."]
    assert "SHOULD NOT APPEAR" not in str(obs) and "recommendation" not in obs


async def test_degraded_reply_reuses_loaded_narrative():
    fake_db = _FakeDB()
    with (
        _analyze_environment(fake_db, _premium_access),
        _owned_workout(fake_db),
        patch("server.load_scoped_workout_coach_evidence",
              AsyncMock(return_value=(_narrative(), None))) as loader,
    ):
        server.llm_coach.enrich_chat_response.side_effect = _llm((None, False, {}))
        response = await _post({"message": "x", "workout_id": "w1", "language": "en"})
    assert response.json()["degraded"] is True
    loader.assert_awaited_once()


@pytest.mark.parametrize("outcome", [None, RuntimeError("boom")])
async def test_unavailable_narrative_is_not_reloaded_for_fallback(outcome):
    fake_db = _FakeDB()
    mock = AsyncMock(side_effect=outcome) if isinstance(outcome, Exception) else AsyncMock(return_value=outcome)
    with (
        _analyze_environment(fake_db, _premium_access),
        _owned_workout(fake_db),
        patch("server.load_scoped_workout_coach_evidence", mock),
    ):
        server.llm_coach.enrich_chat_response.side_effect = _llm((None, False, {}))
        response = await _post({"message": "x", "workout_id": "w1", "language": "en"})
    assert response.status_code == 503  # C393: no usable fallback -> explicit unavailable
    mock.assert_awaited_once()
    assert fake_db.coach_quota_counters._docs == [] or fake_db.coach_quota_counters._docs[0]["count"] == 0


async def test_prompt_allows_recent_workouts_but_keeps_roles_and_limits():
    p = llm_coach.SYSTEM_PROMPT_COACH
    assert "Only the selected workout and comparison.similar sessions are available" not in p
    for fragment in (
        "recent_workouts are factual context you may cite",
        "selected (active) workout is the subject",
        "comparison.similar sessions are the only supported basis",
        "Never invent a session",
        "A comparison never replaces the selected workout",
    ):
        assert fragment in p


async def test_general_chat_loads_no_workout_observations():
    fake_db = _FakeDB()
    with (
        _analyze_environment(fake_db, _trial_access),
        patch("server.load_scoped_workout_coach_evidence", AsyncMock()) as loader,
    ):
        llm = server.llm_coach.enrich_chat_response
        await _post({"message": "combien de séances cette semaine ?", "language": "fr"})
        assert "validated_workout_observations" not in llm.await_args.kwargs["context"]
    loader.assert_not_awaited()


async def test_loader_failure_or_missing_data_omits_observations():
    for outcome in (RuntimeError("boom"), None):
        fake_db = _FakeDB()
        with (
            _analyze_environment(fake_db, _trial_access),
            _owned_workout(fake_db),
            patch("server.load_scoped_workout_coach_evidence",
                  AsyncMock(side_effect=outcome) if isinstance(outcome, Exception)
                  else AsyncMock(return_value=outcome)),
        ):
            llm = server.llm_coach.enrich_chat_response
            response = await _post({"message": "x", "workout_id": "w1", "language": "en"})
            assert response.status_code == 200
            assert "validated_workout_observations" not in llm.await_args.kwargs["context"]


async def test_history_window_is_wider_than_c393_baseline():
    assert server.COACH_HISTORY_LIMIT >= 8


async def test_prompt_contract_covers_reasoning_followups_and_limits():
    p = llm_coach.SYSTEM_PROMPT_COACH
    for fragment in (
        "validated_workout_observations", "Follow-ups",
        "never invent LT1/LT2", "Never create a new prescription",
        # C392-B general-hypothesis contract replaces the former "hypotheses" keyword.
        "C. Hypothesis: you may explain a general physiological mechanism",
        "labeled as general knowledge",
        "never present a hypothesis as an established cause",
        "never present a general explanation as proof of this athlete's progress",
        # C394 continuity: follow-ups stay attached to the selected workout.
        "refer to the selected workout and the previous answer's subject",
        "ask one short clarification question",
    ):
        assert fragment in p


async def test_conversation_history_window_in_prompt():
    captured = {}

    async def fake_call(system, prompt, user_id, kind, **kw):
        captured["prompt"] = prompt
        return "ok", True, {}

    history = [{"role": "user", "content": f"m{i} " + "x" * 300} for i in range(8)]
    with patch.object(llm_coach, "_call_gpt", fake_call):
        await llm_coach.enrich_chat_response("pourquoi ?", {"language": "fr"}, history, "u")
    assert "m7" in captured["prompt"] and "m2" in captured["prompt"] and "m1 " not in captured["prompt"]
    assert "x" * 300 in captured["prompt"]
