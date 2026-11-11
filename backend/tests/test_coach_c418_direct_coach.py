"""C418: computed C409 comparisons are worded by the model; no post-generation check (mocked LLM only)."""

import json
from unittest.mock import AsyncMock, patch

import pytest

from test_coach_contract_unified import _STUB_REPLIES, _free_access, _trial_access  # sets env first
import coach_activity_conversation as cac
import coach_session_comment as csc
import server
from test_coach_c393_fallback_quota import _llm, _post
from test_coach_c409_activity_conversation import A, B, TODAY, _db, _history_runs, _run, _server_env, _turn

pytestmark = pytest.mark.asyncio

PAIR_MESSAGES = {
    "fr": "Compare ma sortie du 12 octobre avec celle du 13 septembre",
    "en": "Compare my run on October 12 with the one on September 13",
    "es": "Compara mi salida del 12 de octubre con la del 13 de septiembre",
}


def _env(db, access=_trial_access):
    return _server_env(db, access)


def _patches():
    return (
        patch("coach_activity_conversation.today_for", return_value=TODAY),
        patch("server.get_training_v2_week", AsyncMock(side_effect=AssertionError("must not persist"))),
        patch("server.get_today_adaptive_session", AsyncMock(side_effect=AssertionError("must not persist"))),
    )


@pytest.mark.parametrize("language", ["fr", "en", "es"])
async def test_pair_comparison_goes_to_llm_with_the_unmodified_c409_contract(language):
    db = _db(A(), B())
    p1, p2, p3 = _patches()
    with _env(db), p1, p2, p3:
        llm = server.llm_coach.enrich_chat_response
        response = await _post({"message": PAIR_MESSAGES[language], "language": language})
        context = llm.await_args.kwargs["context"]
    turn = await _turn(db, PAIR_MESSAGES[language], language=language)
    assert response.status_code == 200 and llm.await_count == 1
    body = response.json()
    assert body["response"] == _STUB_REPLIES.get(language, _STUB_REPLIES["en"]) and body["verification"]["response_source"] == "llm_direct_unverified"
    assert context["comparison_contract"] == json.loads(json.dumps(turn["contract"]))  # no recalculation
    assert context["comparison_request"]["nature"] == "pair" and context["language"] == language
    for current_state in ("today", "current_week_sessions", "readiness", "training_load", "predictions"):
        assert current_state not in context
    stored = [d for d in db.conversations._docs if d["role"] == "assistant"]
    assert len(stored) == 1 and stored[0]["coach_refs"]["kind"] == "pair"
    assert stored[0]["coach_contract"]["kind"] == "pair" and stored[0]["content"] == body["response"]
    assert len([d for d in db.conversations._docs if d["role"] == "user"]) == 1


async def test_history_comparison_keeps_its_nature_focus_and_population():
    db = _db(A(), B(), *_history_runs())
    p1, p2, p3 = _patches()
    with _env(db), p1, p2, p3:
        await _post({"message": "Compare ma sortie du 12 octobre avec mes trois dernières sorties, côté cardio",
                     "language": "fr"})
        context = server.llm_coach.enrich_chat_response.await_args.kwargs["context"]
        follow = await _post({"message": "Et au niveau de l'allure ?", "language": "fr"})
        follow_context = server.llm_coach.enrich_chat_response.await_args.kwargs["context"]
    assert follow.status_code == 200
    assert context["comparison_request"]["nature"] == "history"
    assert follow_context["comparison_contract"]["kind"] == "history"
    assert follow_context["comparison_request"]["focus"] == "pace"
    assert follow_context["comparison_contract"]["reference"]["id"] == "wA"


async def test_clarification_stays_deterministic_and_never_calls_the_model():
    db = _db(A(), B(), _run("wA2", "2026-10-12T18:00:00", 5.0, 30, 360, 140))
    p1, p2, p3 = _patches()
    with _env(db), p1, p2, p3:
        llm = server.llm_coach.enrich_chat_response
        ambiguous = await _post({"message": "Analyse ma sortie du 12 octobre", "language": "fr"})
        missing = await _post({"message": "Analyse ma sortie du 1 janvier 2026", "language": "fr"})
    assert ambiguous.status_code == missing.status_code == 200
    assert llm.await_count == 0
    assert ambiguous.json()["verification"]["response_source"] == "c409_reference_resolution"


async def test_provider_failure_on_comparison_is_503_without_assistant_message_or_refs():
    db = _db(A(), B())
    p1, p2, p3 = _patches()
    with _env(db), p1, p2, p3:
        server.llm_coach.enrich_chat_response.side_effect = _llm((None, False, {}))
        response = await _post({"message": PAIR_MESSAGES["en"], "language": "en"})
        calls = server.llm_coach.enrich_chat_response.await_count
    assert response.status_code == 503 and calls == 1
    assert [d["role"] for d in db.conversations._docs] == ["user"]
    assert not [d for d in db.conversations._docs if d.get("coach_refs")]


async def test_comparison_never_leaks_another_users_activities():
    db = _db(A(), B(), _run("wX", "2026-10-12T07:00:00", 3.0, 20, 400, 120, user="user-b"))
    p1, p2, p3 = _patches()
    with _env(db), p1, p2, p3:
        await _post({"message": PAIR_MESSAGES["en"], "language": "en"})
        context = server.llm_coach.enrich_chat_response.await_args.kwargs["context"]
    assert "wX" not in json.dumps(context)
    assert {a["id"] for a in context["comparison_contract"]["activities"]} == {"wA", "wB"}


async def test_free_user_gets_restriction_and_no_llm_call_for_comparisons():
    db = _db(A(), B())
    p1, p2, p3 = _patches()
    with _env(db, _free_access), p1, p2, p3:
        response = await _post({"message": PAIR_MESSAGES["fr"], "language": "fr"})
        assert server.llm_coach.enrich_chat_response.await_count == 0
    assert "essai actif ou Premium" in response.json()["response"]
    assert db.conversations._docs == []


async def test_changing_subject_after_a_comparison_drops_the_pair():
    db = _db(A(), B())
    p1, _, _ = _patches()
    with _env(db), p1:
        await _post({"message": PAIR_MESSAGES["fr"], "language": "fr"})
        await _post({"message": "Changeons de sujet. Et le cardio ?", "language": "fr"})
        context = server.llm_coach.enrich_chat_response.await_args.kwargs["context"]
    assert "comparison_contract" not in context
    assert [d.get("coach_refs") for d in db.conversations._docs if d["role"] == "assistant"][1] is None


async def test_comparison_context_builder_is_pure():
    turn = await _turn(_db(A(), B()), PAIR_MESSAGES["fr"])
    snapshot = json.dumps(turn["contract"], sort_keys=True)
    context = csc.build_comparison_chat_context(turn, "fr")
    context["comparison_contract"]["deltas"].clear()
    assert json.dumps(turn["contract"], sort_keys=True) == snapshot
    assert cac.build_comparison_contract  # calculation entry point untouched
