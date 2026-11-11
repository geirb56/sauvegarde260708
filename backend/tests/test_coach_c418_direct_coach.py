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


# ---------------------------------------------------------------- correctif: focus/why, écarts, isolation

HIST = "Compare ma sortie du 12 octobre avec mes trois dernières sorties côté cardio, et explique-moi la différence"


def _last():
    return server.llm_coach.enrich_chat_response.await_args.kwargs


async def _chat_turns(db, messages, language="fr", access=_trial_access):
    p1, p2, p3 = _patches()
    out = []
    with _env(db, access), p1, p2, p3:
        for m in messages:
            r = await _post({"message": m, "language": language})
            out.append((r, dict(_last()) if server.llm_coach.enrich_chat_response.await_count else None))
        count = server.llm_coach.enrich_chat_response.await_count
    return out, count


async def test_history_focus_and_why_reach_the_llm():
    out, _ = await _chat_turns(_db(A(), B(), *_history_runs()), [HIST])
    req = out[0][1]["context"]["comparison_request"]
    assert req["nature"] == "history" and req["focus"] == "hr" and req["explanation_requested"] is True


async def test_history_turn_returns_focus_and_why():
    turn = await _turn(_db(A(), B(), *_history_runs()), HIST)
    assert turn["kind"] == "compare" and turn["focus"] == "hr" and turn["why"] is True


async def test_history_focus_survives_date_clarification_and_choice():
    other = _run("wA2", "2026-10-12T18:00:00", 5.0, 30, 360, 140)
    db = _db(A(), B(), other, *_history_runs())
    out, _ = await _chat_turns(db, [HIST, "la première"])
    assert out[0][1] is None  # clarification: no model call
    pending = [d for d in db.conversations._docs if d["role"] == "assistant"][0]["coach_refs"]["pending"]
    assert pending["intent"]["focus"] == "hr" and pending["intent"]["why"] is True
    req = out[1][1]["context"]["comparison_request"]
    assert req["focus"] == "hr" and req["explanation_requested"] is True


async def test_history_followup_changes_focus_and_keeps_reference():
    db = _db(A(), B(), *_history_runs())
    out, _ = await _chat_turns(db, [HIST, "Et au niveau de l'allure ?", "Et la distance ?"])
    contexts = [o[1]["context"] for o in out]
    assert [c["comparison_request"]["focus"] for c in contexts] == ["hr", "pace", "distance"]
    assert all(c["comparison_contract"]["reference"]["id"] == "wA" for c in contexts)
    assert all(c["comparison_contract"]["kind"] == "history" for c in contexts)


@pytest.mark.parametrize("language,message", [
    ("fr", HIST),
    ("en", "Compare my run on October 12 with my last three runs, heart rate, and explain why"),
    ("es", "Compara mi salida del 12 de octubre con mis últimas tres salidas, frecuencia cardiaca, y explica por qué"),
])
async def test_computed_summary_is_the_exact_c409_rendering_and_contract_is_unchanged(language, message):
    db = _db(A(), B(), *_history_runs())
    out, _ = await _chat_turns(db, [message], language)
    context = out[0][1]["context"]
    turn = await _turn(db, message, language=language)
    assert turn["kind"] == "compare"
    assert context["comparison_computed_summary"] == turn["text"]
    assert context["comparison_contract"] == json.loads(json.dumps(turn["contract"]))
    assert out[0][0].json()["response"] != turn["text"]  # the LLM wording, not the report


async def test_pair_context_also_carries_the_computed_summary():
    db = _db(A(), B())
    out, _ = await _chat_turns(db, [PAIR_MESSAGES["fr"]])
    turn = await _turn(db, PAIR_MESSAGES["fr"])
    assert out[0][1]["context"]["comparison_computed_summary"] == turn["text"]


async def test_no_comparable_history_and_missing_values_keep_contract_and_summary():
    lone = _run("wL", "2026-10-12T07:00:00", 10.0, None, None, None)
    db = _db(lone)
    out, _ = await _chat_turns(db, ["Compare ma sortie du 12 octobre avec mes trois dernières sorties"])
    context = out[0][1]["context"]
    turn = await _turn(db, "Compare ma sortie du 12 octobre avec mes trois dernières sorties")
    assert context["comparison_contract"]["population"] == [] == turn["contract"]["population"]
    assert context["comparison_computed_summary"] == turn["text"]


async def test_new_pair_after_other_subject_gets_no_old_history_but_followup_keeps_it():
    c = _run("wC", "2026-10-20T08:00:00", 8.0, 50, 375, 150)
    d = _run("wD", "2026-10-26T08:00:00", 6.0, 40, 400, 145)
    e = _run("wE", "2026-11-02T08:00:00", 7.0, 42, 360, 148)
    db = _db(A(), B(), c, d, e)
    msgs = ["Analyse ma sortie du 13 septembre.",
            "Compare ma sortie du 12 octobre avec celle du 20 octobre",
            "Et au niveau du cardio ?",
            "Compare maintenant ma sortie du 26 octobre avec celle du 2 novembre"]
    out, count = await _chat_turns(db, msgs)
    assert count == 4
    hist = [[m["content"] for m in o[1]["conversation_history"]] for o in out]
    assert hist[1] == []  # new comparison: nothing about B
    assert msgs[1] in hist[2] and msgs[0] not in hist[2]  # follow-up keeps the comparison exchange
    assert {a["id"] for a in out[2][1]["context"]["comparison_contract"]["activities"]} == {"wA", "wC"}
    assert out[2][1]["context"]["comparison_request"]["focus"] == "hr"
    assert hist[3] == []
    assert {a["id"] for a in out[3][1]["context"]["comparison_contract"]["activities"]} == {"wD", "wE"}
    assert one_call_per_answer(db, 4)


def one_call_per_answer(db, n):
    return len([d for d in db.conversations._docs if d["role"] == "assistant"]) == n


async def test_opened_workout_differs_from_explicit_pair_and_history_is_isolated():
    c = _run("wC", "2026-10-20T08:00:00", 8.0, 50, 375, 150)
    db = _db(A(), B(), c)
    p1, p2, p3 = _patches()
    with _env(db), p1, p2, p3, patch("server.load_scoped_workout_analysis_v2",
                                      AsyncMock(side_effect=lambda **kw: ({"id": kw["workout_id"], "user_id": kw["user_id"]}, object()))), \
            patch("server.load_scoped_workout_coach_evidence", AsyncMock(return_value=(None, None))), \
            patch("server.build_coach_context_v2", AsyncMock(return_value=type("D", (), {"model_dump": lambda self, mode="json": {"workout_detail": {"id": "x"}}})())):
        await _post({"message": "Et le cardio ?", "workout_id": "wB", "language": "fr"})
        await _post({"message": "Compare ma sortie du 12 octobre avec celle du 20 octobre", "workout_id": "wB", "language": "fr"})
        kw = _last()
        await _post({"message": "Et au niveau du cardio ?", "workout_id": "wB", "language": "fr"})
        kw2 = _last()
    assert {a["id"] for a in kw["context"]["comparison_contract"]["activities"]} == {"wA", "wC"}
    assert kw["conversation_history"] == [] or all("cardio" not in m["content"] or "Compare" in m["content"] for m in kw["conversation_history"])
    assert {a["id"] for a in kw2["context"]["comparison_contract"]["activities"]} == {"wA", "wC"}
    assert any("Compare ma sortie" in m["content"] for m in kw2["conversation_history"])


async def test_history_of_another_user_is_never_sent():
    db = _db(A(), B())
    db.conversations._docs.append({"id": "x", "user_id": "user-b", "role": "user", "content": "SECRET-B",
                                   "workout_id": None, "timestamp": "2026-11-08T10:00:00+00:00"})
    out, _ = await _chat_turns(db, [PAIR_MESSAGES["en"], "What about heart rate?"], "en")
    for o in out:
        assert "SECRET-B" not in json.dumps(o[1]["conversation_history"])


async def test_plan_question_after_comparison_has_no_comparison_context():
    db = _db(A(), B())
    with patch("server._build_coach_llm_context", AsyncMock(return_value=({"plan": True}, None))):
        out, _ = await _chat_turns(db, [PAIR_MESSAGES["fr"], "Quelle est ma séance de demain ?"])
    assert out[1][1]["context"] == {"plan": True}


async def test_continues_flag_is_computed_by_c409():
    db = _db(A(), B())
    first = await _turn(db, PAIR_MESSAGES["fr"])
    assert first["continues"] is False
    memory = first["refs"]
    again = await _turn(db, "Et au niveau du cardio ?", memory=memory)
    assert again["continues"] is True and again["focus"] == "hr"
