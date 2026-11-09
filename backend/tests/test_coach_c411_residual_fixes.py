"""C411 — pre-beta residual fixes C (HR position), E (same-distance history), D ("celle d'avant").

Deterministic: no model, Garmin or production call. Final texts are asserted, not only helpers.
"""

from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

import coach_evidence_guard as guard
import coach_activity_conversation as cac
import test_coach_c408d_partial_validation as c408d
import test_coach_c409_activity_conversation as c409
import test_coach_c410_guard_fixes as c410g
from test_coach_c393_fallback_quota import _post

pytestmark = pytest.mark.asyncio
TODAY = c409.TODAY


def _runs_around_12_10():
    km = [9.0, 5.0, 9.5, 10.0, 9.2]
    return [c409._run(f"s{i}", f"2026-10-{i + 1:02d}T08:00:00", k, 60, 350, 150) for i, k in enumerate(km)]


# ---------------------------------------------------------------- C: one HR position, exact population

C_RAW = {
    "fr": ("Tu as couru 9,33 km à 7:21/km avec une FC moyenne de 127 bpm. Ta FC se situe dans la partie basse de tes "
           "31 séances de référence. Elle est à un niveau intermédiaire parmi tes séances habituelles similaires."),
    "en": ("You ran 9.33 km at 7:21/km with an average HR of 127 bpm. Your HR is in the lower part of your 31 "
           "reference sessions. It is at an intermediate level among your usual similar sessions."),
    "es": ("Corriste 9,33 km a 7:21/km con una FC media de 127 bpm. Tu FC está en la parte baja de tus 31 sesiones "
           "de referencia. Está en un nivel intermedio entre tus sesiones habituales similares."),
}


@pytest.mark.parametrize("language", ["fr", "en", "es"])
async def test_replay_26_10_second_hr_position_is_removed_and_population_is_exact(language):
    context = c408d._ctx(language)
    reasons = guard.check_contract_claims(C_RAW[language], context)
    assert {"redundant_hr_position"} <= reasons
    out = guard.resolve_chat_reply(C_RAW[language], context, language)
    text = out["text"]
    assert out["response_source"] != "llm_reply_checked"
    assert text.count("31") == 1
    for banned in ("habituelles similaires", "usual similar", "habituales similares", "intermédiaire", "intermediate",
                   "intermedio"):
        assert banned not in text.lower()
    assert "9,33" in text or "9.33" in text and "127" in text
    assert guard.verify_chat_reply(text, context, language)["passed"] is True


async def test_unwanted_population_wording_is_rejected_even_alone():
    context = c408d._ctx("fr")
    text = "Ta FC de 127 bpm est à un niveau intermédiaire parmi tes séances habituelles similaires."
    assert "population_misdescribed" in guard.check_contract_claims(text, context)


async def test_single_correct_position_statement_is_unchanged():
    context = c408d._ctx("fr")
    text = "Ta FC moyenne de 127 bpm se situe dans la partie basse de tes 31 séances de référence."
    assert guard.resolve_chat_reply(text, context, "fr")["response_source"] == "llm_reply_checked"


# ---------------------------------------------------------------- E: history with an explicit reference

@pytest.mark.parametrize("message,language,expected", [
    ("Montre-moi mes 3 dernières sorties de même distance que celle du 12 octobre.", "fr", "3 séances retenues"),
    ("Montre-moi mes 3 sorties précédentes de même distance que celle du 12 octobre.", "fr", "3 séances retenues"),
    ("Montre-moi les 3 sorties de même distance que le 12 octobre.", "fr", "3 séances retenues"),
    ("Show me my last 3 runs of the same distance as October 12.", "en", "3 sessions"),
    ("Show me 3 runs of the same distance as October 12.", "en", "3 sessions"),
    ("Muéstrame mis últimas 3 salidas de la misma distancia que la del 12 de octubre.", "es", "3 sesiones"),
    ("Muéstrame 3 salidas de la misma distancia que la del 12 de octubre.", "es", "3 sesiones"),
])
async def test_replay_12_10_history_returns_up_to_three_earlier_comparable_runs(message, language, expected):
    db = c409._db(c409.A(), c409.B(), *_runs_around_12_10())
    turn = await c409._turn(db, message, language=language)
    assert turn["kind"] == "compare"
    contract = turn["contract"]
    assert contract["reference"]["id"] == "wA"
    assert [f["id"] for f in contract["population"]] == ["s2", "s3", "s4"]
    assert all(f["id"] != "wA" for f in contract["population"])
    assert expected in turn["text"]


async def test_history_explains_when_fewer_than_three_runs_match():
    db = c409._db(c409.A(), c409.B(), *_runs_around_12_10()[:3])
    turn = await c409._turn(db, "Montre-moi mes 3 dernières sorties de même distance que celle du 12 octobre.")
    assert [f["id"] for f in turn["contract"]["population"]] == ["s0", "s2"]
    assert "2 séances retenues sur 3" in turn["text"] or "sur 3" in turn["text"]


async def test_history_never_invents_runs():
    db = c409._db(c409.A(), c409.B())
    turn = await c409._turn(db, "Montre-moi mes 3 sorties de même distance que le 12 octobre.")
    assert turn["contract"]["population"] == [] and "Aucune séance antérieure" in turn["text"]


async def test_history_without_reference_still_offers_a_choice():
    db = c409._db(c409.A(), c409.B(), *_runs_around_12_10())
    turn = await c409._turn(db, "Montre-moi mes 3 dernières sorties de même distance")
    assert turn["kind"] == "reply" and "1)" in turn["text"] and turn["refs"]["pending"]["choices"]


@pytest.mark.parametrize("message", ["Analyse mes 3 sorties", "Montre-moi mes 3 sorties", "Analyse ma sortie du 12 octobre"])
async def test_count_alone_does_not_turn_a_message_into_a_history(message):
    assert cac.parse_message(message, TODAY)["history"] is None


async def test_e2e_history_text_returned_by_the_endpoint_without_model_call():
    db = c409._db(c409.A(), c409.B(), *_runs_around_12_10())
    with c409._server_env(db), patch("coach_activity_conversation.today_for", return_value=TODAY):
        llm = c409.server.llm_coach.enrich_chat_response
        before = llm.await_count
        response = await _post({"message": "Montre-moi mes 3 sorties précédentes de même distance que celle du 12 octobre.",
                                "language": "fr"})
        assert llm.await_count == before
    body = response.json()["response"]
    assert response.status_code == 200 and "3 séances retenues" in body
    assert "3 octobre" in body and "4 octobre" in body and "5 octobre" in body and "7:21/km" in body


# ---------------------------------------------------------------- D: "celle d'avant" and equivalents

D_MESSAGES = [
    ("Compare ma dernière sortie avec la précédente.", "fr"),
    ("Compare ma dernière sortie avec celle d'avant.", "fr"),
    ("Compare ma dernière sortie avec celle d’avant.", "fr"),
    ("Compare my last run with the previous one.", "en"),
    ("Compare my last run with the one before.", "en"),
    ("Compare my last run with the one prior.", "en"),
    ("Compara mi última salida con la anterior.", "es"),
    ("Compara mi última salida con la de antes.", "es"),
]


@pytest.mark.parametrize("message,language", D_MESSAGES)
async def test_last_vs_previous_variants_compare_the_two_latest_activities(message, language):
    db = c409._db(c409.A(), c409.B(), c409._run("wOld", "2026-08-01T08:00:00", 5.0, 30, 360, 140))
    turn = await c409._turn(db, message, language=language)
    assert turn["kind"] == "compare"
    assert turn["contract"]["kind"] != "history" and turn["refs"]["workout_ids"] == ["wB", "wA"]
    assert "21,27" in turn["text"] or "21.27" in turn["text"]


async def test_e2e_celle_d_avant_returns_the_same_text_as_la_precedente():
    texts = []
    for message in ("Compare ma dernière sortie avec la précédente.", "Compare ma dernière sortie avec celle d'avant."):
        db = c409._db(c409.A(), c409.B())
        with c409._server_env(db), patch("coach_activity_conversation.today_for", return_value=TODAY):
            response = await _post({"message": message, "language": "fr"})
        assert response.status_code == 200
        texts.append(response.json()["response"])
    assert texts[0] == texts[1] and "De quelle séance" not in texts[0]


# ---------------------------------------------------------------- non-regression of validated behaviours

@pytest.mark.parametrize("language", ["fr", "en", "es"])
async def test_replay_10_10_interval_structure_is_preserved(language):
    context = c410g._interval_context([240] * 4)
    out = guard.resolve_chat_reply(c410g.A_TEXTS[language], context, language)
    assert ("4 ×" in out["text"] or "4 x" in out["text"]) and "3:56" in out["text"]


async def test_replay_13_09_type_stays_probabilistic():
    context = c410g._long_run_context("fr")
    out = guard.resolve_chat_reply("C'était clairement une sortie longue.", context, "fr")
    assert "clairement" not in out["text"].lower() and "probablement" in out["text"].lower()


async def test_replay_19_10_vs_12_10_keeps_the_treadmill_reserve():
    import test_coach_c410_prebeta_fixes as c410p
    _garmin = c410p._garmin
    t_w, t_a = _garmin("gt", "1", "2026-10-19T08:00:00", 10.0, 55, 330, 150, "treadmill_running")
    o_w, o_a = _garmin("go", "2", "2026-10-12T08:00:00", 10.0, 58, 348, 148, "running")
    turn = await c410p._turn(c410p._db(t_w, o_w, activities=(t_a, o_a)), "Compare 12/10 et 19/10", "fr")
    assert turn["contract"]["environments_differ"] is True and "tapis" in turn["text"]


async def test_free_account_quota_and_access_control_unchanged():
    db = c409._db(c409.A(), c409.B(), *_runs_around_12_10())
    with c409._server_env(db, c409._free_access), patch("coach_activity_conversation.today_for", return_value=TODAY):
        history = await _post({"message": "Montre-moi mes 3 sorties de même distance que le 12 octobre.", "language": "fr"})
        previous = await _post({"message": "Compare ma dernière sortie avec celle d'avant.", "language": "fr"})
        general = await _post({"message": "Bonjour", "language": "fr"})
    assert "essai actif ou Premium" in history.json()["response"]
    assert "essai actif ou Premium" in previous.json()["response"]
    assert "essai actif" not in general.json()["response"]
