"""C409 review corrections: memory policy, selected-workout routing, FR/EN/ES, population, quotas.

Dates in these fixtures: "today" is Sunday 2026-11-08.
"""

import re
from contextlib import contextmanager
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock, patch

import pytest

from test_coach_contract_unified import _trial_access, _free_access
from test_coach_c393_fallback_quota import _count
from test_coach_c409_activity_conversation import (
    A, B, TODAY, _db, _history_runs, _post, _run, _server_env, _turn,
)
import server
import coach_activity_conversation as cac

pytestmark = pytest.mark.asyncio


class _Detail:
    def model_dump(self, mode="json"):
        return {"workout_detail": {"id": "x", "date": "2026-10-12", "type": "run", "avg_hr": 127.0}}


@contextmanager
def _chat(db, access=_trial_access):
    async def scoped(**kw):
        return {"id": kw["workout_id"], "user_id": kw["user_id"]}, object()

    with (
        _server_env(db, access),
        patch("coach_activity_conversation.today_for", return_value=TODAY),
        patch("server.build_coach_context_v2", AsyncMock(return_value=_Detail())),
        patch("server.load_scoped_workout_analysis_v2", AsyncMock(side_effect=scoped)) as loader,
        patch("server.load_scoped_workout_coach_evidence", AsyncMock(return_value=(None, None))),
    ):
        yield loader


def _assistants(db, user="user-a"):
    return [d for d in db.conversations._docs if d["role"] == "assistant" and d["user_id"] == user]


def _llm_calls():
    return server.llm_coach.enrich_chat_response.await_count


# ================================================================ 1. conversational continuity

async def test_intermediate_acknowledgement_keeps_the_same_two_activities():
    db = _db(A(), B())
    with _chat(db):
        r1 = await _post({"message": "Analyse ma sortie du 12 octobre.", "language": "fr"})
        r2 = await _post({"message": "Compare-la avec celle du 13 septembre.", "language": "fr"})
        calls = _llm_calls()
        r3 = await _post({"message": "D'accord, je vois.", "language": "fr"})
        r4 = await _post({"message": "Et au niveau du cardio ?", "language": "fr"})
        total = _llm_calls()
    assert [r.status_code for r in (r1, r2, r3, r4)] == [200] * 4
    assert total == calls + 1  # only the acknowledgement reaches the model
    refs = [d.get("coach_refs") for d in _assistants(db)]
    assert refs[0]["workout_ids"] == ["wA"]
    assert refs[1]["workout_ids"] == ["wB", "wA"] and refs[1]["kind"] == "pair"
    assert refs[2]["workout_ids"] == ["wB", "wA"] and refs[2]["carried"] == 1
    assert refs[3]["workout_ids"] == ["wB", "wA"] and "carried" not in refs[3]
    text = r4.json()["response"]
    assert "160 bpm" in text and "127 bpm" in text and "33 bpm" in text


async def test_explicit_change_of_subject_abandons_the_previous_context():
    db = _db(A(), B())
    with _chat(db):
        await _post({"message": "Compare ma sortie du 12 octobre avec celle du 13 septembre", "language": "fr"})
        r2 = await _post({"message": "Changeons de sujet.", "language": "fr"})
        calls = _llm_calls()
        r3 = await _post({"message": "Et le cardio ?", "language": "fr"})
        total = _llm_calls()
    refs = [d.get("coach_refs") for d in _assistants(db)]
    assert refs[0]["kind"] == "pair" and refs[1] is None and refs[2] is None
    assert total == calls + 1  # not answered from the old sessions
    assert "160 bpm" not in r3.json()["response"] and r2.status_code == r3.status_code == 200


async def test_new_explicit_session_becomes_the_current_reference():
    db = _db(A(), B())
    with _chat(db) as loader:
        await _post({"message": "Compare ma sortie du 12 octobre avec celle du 13 septembre", "language": "fr"})
        await _post({"message": "Analyse ma sortie du 13 septembre", "language": "fr"})
        assert loader.await_args.kwargs["workout_id"] == "wB"
        await _post({"message": "Et au niveau du cardio ?", "language": "fr"})
        assert loader.await_args.kwargs["workout_id"] == "wB"
    refs = [d.get("coach_refs") for d in _assistants(db)]
    assert [r["workout_ids"] for r in refs] == [["wB", "wA"], ["wB"], ["wB"]]


async def test_a_freshly_designated_activity_does_not_inherit_the_previous_history():
    db = _db(A(), B())
    with _chat(db):
        await _post({"message": "Analyse ma sortie du 12 octobre.", "language": "fr"})
        await _post({"message": "Analyse ma sortie du 13 septembre", "language": "fr"})
        history_new = server.llm_coach.enrich_chat_response.await_args.kwargs["conversation_history"]
        await _post({"message": "Et au niveau du cardio ?", "language": "fr"})
        history_followup = server.llm_coach.enrich_chat_response.await_args.kwargs["conversation_history"]
    assert history_new == []
    assert any(m["content"] == "Analyse ma sortie du 13 septembre" for m in history_followup)
    assert all(m["content"] != "Analyse ma sortie du 12 octobre." for m in history_followup[-1:])


async def test_pending_clarification_survives_an_invalid_answer_then_resolves():
    morning = _run("m1", "2026-10-12T07:30:00", 9.33, 68, 441, 127)
    evening = _run("m2", "2026-10-12T18:00:00", 5.0, 30, 360, 140)
    db = _db(morning, evening, B())
    first = await _turn(db, "Analyse ma sortie du 12 octobre")
    memory = first["refs"]
    again = await _turn(db, "la 9", memory=memory)
    assert again["kind"] == "reply" and "pas pu" not in again["text"]
    assert first["text"] in again["text"] and again["refs"]["pending"]["choices"] == memory["pending"]["choices"]
    done = await _turn(db, "la deuxième", memory=again["refs"])
    assert done["kind"] == "single" and done["workout_id"] == "m2"


async def test_invalid_answers_do_not_loop_forever():
    morning = _run("m1", "2026-10-12T07:30:00", 9.33, 68, 441, 127)
    evening = _run("m2", "2026-10-12T18:00:00", 5.0, 30, 360, 140)
    db = _db(morning, evening)
    memory = (await _turn(db, "Analyse ma sortie du 12 octobre"))["refs"]
    for _ in range(cac.MAX_CARRY):
        turn = await _turn(db, "la 9", memory=memory)
        memory = turn["refs"]
        assert memory is not None and memory["pending"]
    last = await _turn(db, "la 9", memory=memory)
    assert last["kind"] == "reply" and last["refs"] is None and "De quelle séance" in last["text"]


async def test_carried_references_lapse_after_the_hop_limit_a_plan_question_or_a_long_digression():
    pair = cac._refs("pair", ["wB", "wA"], primary="wA")
    parsed = lambda text: cac.parse_message(text, TODAY)  # noqa: E731
    one = cac.carried_refs(pair, parsed("D'accord"))
    two = cac.carried_refs(one, parsed("ok merci"))
    assert one["carried"] == 1 and two["carried"] == 2
    assert cac.carried_refs(two, parsed("super")) is None
    assert cac.carried_refs(pair, parsed("Quelle allure cible demain ?")) is None
    assert cac.carried_refs(pair, parsed("Changeons de sujet")) is None
    assert cac.carried_refs(pair, parsed("Peux-tu m'expliquer en détail comment organiser mon alimentation "
                                         "avant une compétition importante de la saison ?")) is None


async def test_stale_or_malformed_references_are_ignored():
    now = datetime(2026, 11, 8, 12, 0, tzinfo=timezone.utc)
    refs = cac._refs("pair", ["wB", "wA"], primary="wA")
    fresh = {"coach_refs": refs, "timestamp": (now - timedelta(minutes=5)).isoformat()}
    assert cac.usable_memory(fresh, now) == refs
    assert cac.usable_memory({**fresh, "timestamp": (now - timedelta(hours=7)).isoformat()}, now) is None
    assert cac.usable_memory({**fresh, "timestamp": "n/a"}, now) is None
    assert cac.usable_memory({"coach_refs": {**refs, "v": 99}, "timestamp": fresh["timestamp"]}, now) is None
    assert cac.usable_memory({"coach_refs": "x", "timestamp": fresh["timestamp"]}, now) is None
    assert cac.usable_memory(None, now) is None


@pytest.mark.parametrize("memory", [
    {"v": 1, "kind": "pair", "workout_ids": "wB"},
    {"v": 1, "kind": "pair", "workout_ids": [1, None]},
    {"v": 1, "kind": "single", "workout_ids": ["a", "b", "c"]},
    {"v": 1, "pending": {"choices": 5, "intent": []}},
    {"v": 1, "pending": {"choices": [None, 3, {"id": 4}], "intent": {"action": "history"}}},
    {"v": 1, "kind": "pair", "workout_ids": ["wB", "wA"], "pending": {"choices": [{"id": "wA"}], "intent": 7}},
    {"v": 1, "kind": "pair", "workout_ids": ["wB", "wA"], "carried": "x", "pending": {"choices": [{"id": "wA"}],
     "intent": {"action": "history", "history": {"kind": "weird", "count": "x"}}}},
    "garbage", 12, [],
])
async def test_malformed_stored_memory_never_raises(memory):
    db = _db(A(), B())
    for message in ("la première", "1", "la dernière", "Et le cardio ?", "Compare-la à celle du 13 septembre",
                    "Compare avec mes dernières sorties similaires", "celle du 12 octobre"):
        turn = await _turn(db, message, memory=memory)
        assert turn["kind"] in ("passthrough", "single", "compare", "reply")


async def test_references_are_isolated_between_users_and_conversation_scopes():
    db = _db(A(), B(), _run("wX", "2026-10-12T07:00:00", 12.0, 80, 400, 150, user="user-b"))
    stamp = datetime.now(timezone.utc).isoformat()
    db.conversations._docs.append({
        "id": "other-user", "user_id": "user-b", "role": "assistant", "content": "x", "workout_id": None,
        "timestamp": stamp, "coach_refs": cac._refs("pair", ["wB", "wA"], primary="wA")})
    db.conversations._docs.append({
        "id": "other-scope", "user_id": "user-a", "role": "assistant", "content": "x", "workout_id": "wA",
        "timestamp": stamp, "coach_refs": cac._refs("pair", ["wB", "wA"], primary="wA")})
    with _chat(db):
        calls = _llm_calls()
        response = await _post({"message": "Et au niveau du cardio ?", "language": "fr"})
        total = _llm_calls()
    assert response.status_code == 200 and total == calls + 1
    assert "160 bpm" not in response.json()["response"]
    assert _assistants(db)[-1].get("coach_refs") is None


async def test_comparison_never_loads_another_users_activity_even_with_forged_ids():
    db = _db(A(), _run("wX", "2026-09-13T07:00:00", 12.0, 80, 400, 150, user="user-b"))
    forged = cac._refs("pair", ["wX", "wA"], primary="wA")
    turn = await _turn(db, "Et le cardio ?", memory=forged)
    assert turn["kind"] == "reply" and "De quelle séance" in turn["text"]
    assert "150" not in turn["text"]


# ================================================================ 2. selected-workout routing

async def test_comparison_from_a_selected_activity_uses_it_as_first_reference():
    db = _db(A(), B())
    with _chat(db) as loader:
        calls = _llm_calls()
        response = await _post({"message": "Compare-la avec celle du 13 septembre", "workout_id": "wA",
                                "language": "fr"})
        followup = await _post({"message": "Et au niveau du cardio ?", "workout_id": "wA", "language": "fr"})
        general = await _post({"message": "Et au niveau du cardio ?", "language": "fr"})
        total = _llm_calls()
    assert response.status_code == followup.status_code == 200
    assert total == calls + 1  # only the general-chat message, with no references, reaches the model
    body = response.json()
    assert "21,27 km" in body["response"] and "9,33 km" in body["response"]
    assert body["verification"]["response_source"] == "c409_comparison_contract"
    assert "160 bpm" in followup.json()["response"] and "127 bpm" in followup.json()["response"]
    assert "160 bpm" not in general.json()["response"]
    assert loader.await_args_list[0].kwargs["workout_id"] == "wA" and loader.await_count == 2
    stored = [d for d in db.conversations._docs if d["role"] == "assistant"]
    assert [d["workout_id"] for d in stored] == ["wA", "wA", None]
    assert stored[0]["coach_refs"]["workout_ids"] == ["wB", "wA"]
    assert {d["workout_id"] for d in db.conversations._docs if d["role"] == "user"} == {"wA", None}


async def test_selected_activity_wins_over_stale_references_of_another_pair():
    other = _run("wC", "2026-08-02T08:00:00", 21.1, 125, 355, 158)
    db = _db(A(), B(), other)
    stale = cac._refs("pair", ["wB", "wC"], primary="wC")
    turn = await cac.resolve_turn(db=db, user_id="user-a", message="Compare-la avec celle du 13 septembre",
                                  language="fr", today=TODAY, memory=stale, selected_id="wA")
    assert turn["kind"] == "compare" and [a["id"] for a in turn["contract"]["activities"]] == ["wB", "wA"]


async def test_selected_activity_compared_with_itself_is_refused_clearly():
    db = _db(A(), B())
    turn = await cac.resolve_turn(db=db, user_id="user-a", message="Compare-la avec celle du 12 octobre",
                                  language="fr", today=TODAY, memory=None, selected_id="wA")
    assert turn["kind"] == "reply" and "ne peut pas être comparée à elle-même" in turn["text"]


async def test_selected_scope_never_starts_the_analysis_of_another_activity():
    db = _db(A(), B())
    turn = await cac.resolve_turn(db=db, user_id="user-a", message="Analyse ma sortie du 13 septembre",
                                  language="fr", today=TODAY, memory=None, selected_id="wA")
    assert turn["kind"] == "compare" and turn["contract"]["kind"] == "pair"
    plain = await cac.resolve_turn(db=db, user_id="user-a", message="Et ma FC ?", language="fr", today=TODAY,
                                   memory=None, selected_id="wA")
    assert plain["kind"] == "passthrough"  # answered by the existing selected-workout path


async def test_selected_activity_history_comparison_uses_it_as_reference():
    db = _db(A(), B(), *_history_runs())
    turn = await cac.resolve_turn(db=db, user_id="user-a", message="Compare avec mes trois dernières sorties",
                                  language="fr", today=TODAY, memory=None, selected_id="wA")
    assert turn["kind"] == "compare" and turn["contract"]["reference"]["id"] == "wA"


async def test_selected_scope_free_tier_is_still_restricted_without_quota_use():
    db = _db(A(), B())
    with _chat(db, _free_access):
        response = await _post({"message": "Compare-la avec celle du 13 septembre", "workout_id": "wA",
                                "language": "fr"})
    assert "essai actif ou Premium" in response.json()["response"]
    assert _count(db) is None and not db.conversations._docs


# ================================================================ 3. FR / EN / ES

_LANG_CASES = {
    "fr": {"date": "Analyse ma sortie du 12 octobre", "compare": "Compare ma sortie du 12 octobre avec celle du 13 septembre",
           "hr": "Et au niveau du cardio ?", "none": "Analyse ma sortie du 3 octobre", "progress": "Est-ce que je progresse ?",
           "multiple": "Analyse ma sortie du 12 octobre", "history": "Compare avec mes trois dernières sorties longues"},
    "en": {"date": "Analyze my run on October 12", "compare": "Compare my run on October 12 with the one on September 13",
           "hr": "What about heart rate?", "none": "Analyze my run on October 3", "progress": "Am I improving?",
           "multiple": "Analyze my run on October 12", "history": "Compare with my last three long runs"},
    "es": {"date": "Analiza mi salida del 12 de octubre", "compare": "Compara mi salida del 12 de octubre con la del 13 de septiembre",
           "hr": "¿Y a nivel de frecuencia cardíaca?", "none": "Analiza mi salida del 3 de octubre",
           "progress": "¿Significa que estoy progresando?", "multiple": "Analiza mi salida del 12 de octubre",
           "history": "Compara con mis tres últimas salidas largas"},
}
_ENGLISH_WORDS = re.compile(
    r"\b(?:the|and|with|average|compared|higher|lower|faster|slower|longer|shorter|gaps|identical|criterion|"
    r"reference|kept|requested|your|you|fitness|recovery|threshold|climbing|heart|session|sessions|run|"
    r"available|found|which|please|median|oldest)\b", re.I)
_FRENCH_WORDS = re.compile(r"\b(?:les|des|une|avec|séances?|écarts|différence)\b", re.I)


def _assert_language(text, lang):
    if lang == "es":
        assert not _ENGLISH_WORDS.search(text), text
        assert not _FRENCH_WORDS.search(text), text
    if lang == "en":
        assert not _FRENCH_WORDS.search(text), text


@pytest.mark.parametrize("lang", ["fr", "en", "es"])
async def test_language_activity_found_by_date(lang):
    turn = await _turn(_db(A(), B()), _LANG_CASES[lang]["date"], language=lang)
    assert turn["kind"] == "single" and turn["workout_id"] == "wA"


@pytest.mark.parametrize("lang,fragments", [
    ("fr", ["21,27 km", "5:43/km", "11,94 km", "1 min 38 s/km", "33 bpm", "54 min", "plus rapide", "supérieure"]),
    ("en", ["21.27 km", "5:43/km", "11.94 km", "1 min 38 s/km", "33 bpm", "54 min", "faster", "longer"]),
    ("es", ["21,27 km", "5:43/km", "11,94 km", "1 min 38 s/km", "33 bpm", "54 min", "más rápido", "superior",
            "13 de septiembre", "12 de octubre", "FC media"]),
])
async def test_language_comparison_of_two_sessions(lang, fragments):
    turn = await _turn(_db(A(), B()), _LANG_CASES[lang]["compare"], language=lang)
    assert turn["kind"] == "compare"
    for fragment in fragments:
        assert fragment in turn["text"], (lang, fragment, turn["text"])
    _assert_language(turn["text"], lang)


@pytest.mark.parametrize("lang,fragment", [("fr", "FC moyenne était de 160 bpm"), ("en", "average was 160 bpm"),
                                           ("es", "FC media fue de 160 bpm")])
async def test_language_hr_follow_up(lang, fragment):
    memory = cac._refs("pair", ["wB", "wA"], primary="wA")
    turn = await _turn(_db(A(), B()), _LANG_CASES[lang]["hr"], memory=memory, language=lang)
    assert turn["kind"] == "compare" and fragment in turn["text"] and "33 bpm" in turn["text"]
    assert "21,27" not in turn["text"] and "21.27" not in turn["text"]  # limited to the heart rate
    _assert_language(turn["text"], lang)


@pytest.mark.parametrize("lang,fragment", [("fr", "plusieurs séances"), ("en", "several sessions"),
                                           ("es", "varias sesiones")])
async def test_language_clarification_with_several_activities(lang, fragment):
    morning = _run("m1", "2026-10-12T07:30:00", 9.33, 68, 441, 127)
    evening = _run("m2", "2026-10-12T18:00:00", 5.0, 30, 360, 140)
    turn = await _turn(_db(morning, evening), _LANG_CASES[lang]["multiple"], language=lang)
    assert turn["kind"] == "reply" and fragment in turn["text"]
    assert "07:30" in turn["text"] and "18:00" in turn["text"]
    assert ("12 de octubre" if lang == "es" else "12 octobre" if lang == "fr" else "12 October") in turn["text"]
    _assert_language(turn["text"], lang)


@pytest.mark.parametrize("lang,fragment", [("fr", "Je ne trouve aucune course le 3 octobre"),
                                           ("en", "I can't find any run on 3 October"),
                                           ("es", "No encuentro ninguna carrera el 3 de octubre")])
async def test_language_no_activity(lang, fragment):
    turn = await _turn(_db(A(), B()), _LANG_CASES[lang]["none"], language=lang)
    assert turn["kind"] == "reply" and fragment in turn["text"] and turn["refs"] is None
    _assert_language(turn["text"], lang)


@pytest.mark.parametrize("lang,fragment", [("fr", "Je ne peux pas conclure que tu progresses"),
                                           ("en", "I can't conclude that you are improving"),
                                           ("es", "No puedo concluir que estés progresando")])
async def test_language_physiological_conclusion_refused(lang, fragment):
    memory = cac._refs("pair", ["wB", "wA"], primary="wA")
    turn = await _turn(_db(A(), B()), _LANG_CASES[lang]["progress"], memory=memory, language=lang)
    assert turn["kind"] == "compare" and fragment in turn["text"]
    _assert_language(turn["text"], lang)
    assert turn["contract"]["undemonstrated_conclusions"]


@pytest.mark.parametrize("lang", ["fr", "en", "es"])
async def test_language_all_pair_focuses_and_history(lang):
    db = _db(A(), B(), *_history_runs())
    memory = cac._refs("pair", ["wB", "wA"], primary="wA")
    messages = {
        "fr": ["Sur laquelle ai-je couru le plus vite ?", "Laquelle était la plus exigeante ?",
               "Pourquoi ma FC était-elle plus élevée ?", "Et la distance ?", "Et la durée ?"],
        "en": ["Which one was faster?", "Which one was harder?", "Why was my heart rate higher?",
               "And the distance?", "And the duration?"],
        "es": ["¿En cuál corrí más rápido?", "¿Cuál fue más exigente?", "¿Por qué mi frecuencia cardíaca fue más alta?",
               "¿Y la distancia?", "¿Y la duración?"],
    }[lang]
    for message in messages:
        turn = await _turn(db, message, memory=memory, language=lang)
        assert turn["kind"] == "compare" and turn["text"], message
        _assert_language(turn["text"], lang)
    history = await _turn(db, _LANG_CASES[lang]["history"], memory=cac._refs("single", ["wB"]), language=lang)
    assert history["kind"] == "compare" and history["contract"]["kind"] == "history"
    _assert_language(history["text"], lang)


@pytest.mark.parametrize("message,expected", [
    ("mi salida del 12 de octubre", "2026-10-12"),
    ("el 13/09", "2026-09-13"),
    ("la salida del 13 de septiembre de 2026", "2026-09-13"),
    ("mi salida del domingo", "2026-11-08"),
    ("mi salida de ayer", "2026-11-07"),
])
async def test_spanish_dates(message, expected):
    selectors = cac.parse_message(message, TODAY)["selectors"]
    assert selectors and selectors[0]["date"].isoformat() == expected


async def test_spanish_last_distance_and_history_requests():
    short = _run("s1", "2026-11-01T08:00:00", 5.0, 30, 360, 140)
    db = _db(short, A(), B())
    assert (await _turn(db, "Analiza mi última salida", language="es"))["workout_id"] == "s1"
    assert (await _turn(db, "Analiza mi última media maratón", language="es"))["workout_id"] == "wB"
    assert (await _turn(db, "Analiza mi salida de 21 km", language="es"))["workout_id"] == "wB"
    parsed = cac.parse_message("Compara con mis tres últimas salidas similares", TODAY)
    assert parsed["history"] == {"kind": "similar", "count": 3}


async def test_spanish_references_and_topic_change():
    pair = cac._refs("pair", ["wB", "wA"], primary="wA")
    db = _db(A(), B())
    assert (await _turn(db, "Compáralas", memory=pair, language="es"))["kind"] == "compare"
    assert (await _turn(db, "¿Y las dos en ritmo?", memory=pair, language="es"))["text"].startswith("Corriste más rápido")
    assert (await _turn(db, "Cambiemos de tema", memory=pair, language="es"))["kind"] == "passthrough"
    assert (await _turn(db, "Y el cardio", language="es"))["kind"] == "passthrough"


async def test_semi_marathon_is_not_taken_for_a_marathon():
    parsed = cac.parse_message("Analyse mon dernier semi-marathon", TODAY)
    assert parsed["selectors"] == [{"type": "last", "km": (20.5, 22.0)}]
    full = cac.parse_message("Analyse mon dernier marathon", TODAY)
    assert full["selectors"] == [{"type": "last", "km": (41.5, 43.5)}]


# ================================================================ 4. clarification answers

def _three_runs_same_day():
    return [_run("m1", "2026-10-12T07:30:00", 9.33, 68, 441, 127), _run("m2", "2026-10-12T12:00:00", 6.0, 40, 400, 135),
            _run("m3", "2026-10-12T18:00:00", 5.0, 30, 360, 140)]


@pytest.mark.parametrize("answer,expected", [
    ("la première", "m1"), ("la deuxième", "m2"), ("la dernière", "m3"), ("1", "m1"), ("2", "m2"), ("la 3", "m3"),
    ("celle de 12h", None), ("la 9", None), ("la 0", None),
])
async def test_selection_after_clarification(answer, expected):
    db = _db(*_three_runs_same_day())
    memory = (await _turn(db, "Analyse ma sortie du 12 octobre"))["refs"]
    turn = await _turn(db, answer, memory=memory)
    if expected:
        assert turn["kind"] == "single" and turn["workout_id"] == expected
    else:
        assert turn["kind"] != "single"


async def test_selection_by_precise_date_and_ambiguous_date():
    runs = [*_three_runs_same_day()[:2], _run("w9", "2026-10-10T08:00:00", 10.0, 60, 360, 140)]
    db = _db(*runs)
    two = (await _turn(db, "Analyse ma sortie du 12 octobre"))["refs"]
    ambiguous = await _turn(db, "celle du 12 octobre", memory=two)
    assert ambiguous["kind"] == "reply" and ambiguous["refs"]["pending"]  # same day still ambiguous
    other_day = await _turn(db, "celle du 10 octobre", memory=two)
    assert other_day["kind"] == "single" and other_day["workout_id"] == "w9"


async def test_clarification_for_a_comparison_keeps_the_intent_across_the_answer():
    db = _db(*_three_runs_same_day(), B())
    first = await _turn(db, "Compare ma sortie du 13 septembre avec celle du 12 octobre")
    assert first["kind"] == "reply" and first["refs"]["pending"]["intent"]["others"] == ["wB"]
    done = await _turn(db, "la 2", memory=first["refs"])
    assert done["kind"] == "compare" and [a["id"] for a in done["contract"]["activities"]] == ["wB", "m2"]


async def test_pending_choice_is_re_checked_against_the_owner():
    db = _db(*_three_runs_same_day(), _run("wX", "2026-10-12T09:00:00", 8.0, 50, 380, 150, user="user-b"))
    forged = cac._refs("single", [], pending={
        "choices": [{"id": "wX", "date": "2026-10-12"}], "intent": {"action": "single", "others": []}, "prompt": "p"})
    turn = await _turn(db, "la 1", memory=forged)
    assert turn["kind"] == "single"  # the identifier is only a candidate: the Coach path loads it owner-scoped
    loaded = await cac.load_activity_facts(db, "user-a", "wX")
    assert loaded is None


# ================================================================ 5. historical population

async def test_history_population_count_window_and_self_exclusion():
    ref = _run("ref", "2026-10-12T08:00:00", 10.0, 60, 360, 150)
    old = _run("old", "2026-01-01T08:00:00", 10.0, 60, 360, 150)  # outside the 180-day window
    same = [_run(f"s{i}", f"2026-10-0{i + 1}T08:00:00", 10.0 + i * 0.2, 60, 360, 140 + i) for i in range(4)]
    db = _db(ref, old, *same)
    turn = await _turn(db, "Compare avec mes trois dernières sorties similaires",
                       memory=cac._refs("single", ["ref"], primary="ref"))
    contract = turn["contract"]
    ids = [f["id"] for f in contract["population"]]
    assert ids == ["s1", "s2", "s3"] and "ref" not in ids and "old" not in ids
    assert contract["window_size"] == 4 and "3 séances retenues" in turn["text"]
    assert contract["criterion"]["established"] and "±30 %" in turn["text"]


async def test_history_fewer_than_requested_is_reported_with_the_real_number():
    ref = _run("ref", "2026-10-12T08:00:00", 10.0, 60, 360, 150)
    db = _db(ref, _run("s1", "2026-10-01T08:00:00", 10.5, 62, 355, 148))
    turn = await _turn(db, "Compare avec mes trois dernières sorties similaires",
                       memory=cac._refs("single", ["ref"], primary="ref"))
    assert "1 séance retenue sur 3 demandées" in turn["text"]


async def test_history_median_uses_only_present_measures():
    ref = _run("ref", "2026-10-12T08:00:00", 10.0, 60, 360, 160)
    runs = [_run("s1", "2026-10-01T08:00:00", 10.0, 60, 360, None),
            _run("s2", "2026-10-02T08:00:00", 10.2, 60, 360, 140),
            _run("s3", "2026-10-03T08:00:00", 10.4, 60, 360, 150)]
    db = _db(ref, *runs)
    turn = await _turn(db, "Compare avec mes trois dernières sorties similaires",
                       memory=cac._refs("single", ["ref"], primary="ref"))
    stats = turn["contract"]["population_stats"]
    assert stats["avg_hr"] == {"n": 2, "median": 145} and stats["distance_km"]["n"] == 3
    assert "FC moyenne +15 bpm" in turn["text"] and "certaines mesures manquent" in turn["text"]


async def test_history_with_no_hr_at_all_omits_the_hr_gap():
    ref = _run("ref", "2026-10-12T08:00:00", 10.0, 60, 360, 160)
    db = _db(ref, _run("s1", "2026-10-01T08:00:00", 10.0, 60, 360, None))
    turn = await _turn(db, "Compare avec mes dernières sorties similaires",
                       memory=cac._refs("single", ["ref"], primary="ref"))
    assert turn["contract"]["population_stats"]["avg_hr"]["median"] is None
    assert "FC moyenne +" not in turn["text"] and "FC moyenne −" not in turn["text"]


async def test_history_never_compares_an_activity_with_itself_and_ignores_later_runs():
    ref = _run("ref", "2026-10-12T08:00:00", 10.0, 60, 360, 150)
    later = _run("later", "2026-10-20T08:00:00", 10.0, 60, 360, 150)
    db = _db(ref, later)
    turn = await _turn(db, "Compare avec mes dernières sorties similaires",
                       memory=cac._refs("single", ["ref"], primary="ref"))
    assert turn["contract"]["population"] == []
    assert "Aucune séance antérieure" in turn["text"]


# ================================================================ 6. isolation, quotas, measures

async def test_deterministic_turns_use_no_commercial_quota_and_free_users_are_stopped_first():
    db = _db(A(), B())
    with _chat(db), patch("server._reserve_free_coach_quota_slot", AsyncMock(return_value=None)) as reserve:
        response = await _post({"message": "Compare ma sortie du 12 octobre avec celle du 13 septembre",
                                "language": "fr"})
    assert response.status_code == 200 and reserve.await_count == 0
    assert sum(1 for d in db.conversations._docs if d["role"] == "user") == 1  # one user message, one answer
    assert len(_assistants(db)) == 1
    free_db = _db(A(), B())
    with _chat(free_db, _free_access):
        restricted = await _post({"message": "Analyse ma sortie du 12 octobre", "language": "fr"})
    assert "essai actif ou Premium" in restricted.json()["response"]
    assert _count(free_db) is None and not free_db.conversations._docs


async def test_resolution_failure_is_rejected_before_any_write_or_quota():
    db = _db(A(), B())
    with _chat(db), patch("coach_activity_conversation.resolve_turn", AsyncMock(side_effect=RuntimeError("boom"))):
        response = await _post({"message": "Analyse ma sortie du 12 octobre", "language": "fr"})
    assert response.status_code == 503 and not db.conversations._docs


async def test_unknown_selected_workout_is_rejected_before_resolution():
    db = _db(A(), B())
    with _chat(db) as loader, patch("coach_activity_conversation.resolve_turn", AsyncMock()) as resolver:
        loader.side_effect = AsyncMock(return_value=None)
        response = await _post({"message": "Compare-la avec celle du 13 septembre", "workout_id": "nope",
                                "language": "fr"})
    assert response.status_code == 404
    resolver.assert_not_awaited()


async def test_no_garmin_sync_and_no_write_outside_the_conversation_store():
    db = _db(A(), B())
    sync = AsyncMock(side_effect=AssertionError("sync"))
    with _chat(db), patch("garmin.service._ingest_activities", sync):
        for message in ("Compare ma sortie du 12 octobre avec celle du 13 septembre", "Et le cardio ?"):
            assert (await _post({"message": message, "language": "fr"})).status_code == 200
    sync.assert_not_awaited()
    assert [d["id"] for d in db.workouts._docs] == ["wA", "wB"]
    assert not db.garmin_activities._docs


async def test_gaps_are_computed_from_the_values_that_are_displayed():
    noisy_a = _run("a", "2026-10-12T07:30:00", 9.334, 68.4, 441.4, 127.4)
    noisy_b = _run("b", "2026-09-13T08:00:00", 21.266, 121.6, 342.6, 160.4)
    turn = await _turn(_db(noisy_a, noisy_b), "Compare ma sortie du 12 octobre avec celle du 13 septembre")
    first, second = turn["contract"]["activities"]
    assert (first["distance_km"], second["distance_km"]) == (21.27, 9.33)
    assert turn["contract"]["deltas"]["distance_km"]["gap"] == round(21.27 - 9.33, 2) == 11.94
    assert turn["contract"]["deltas"]["duration_min"]["gap"] == 122 - 68
    assert turn["contract"]["deltas"]["pace_s_per_km"]["gap"] == 441 - 343
    assert turn["contract"]["deltas"]["avg_hr"]["gap"] == 160 - 127
    for fragment in ("21,27 km", "9,33 km", "2h02", "1h08", "11,94 km", "54 min", "1 min 38 s/km", "33 bpm"):
        assert fragment in turn["text"]


@pytest.mark.parametrize("lang", ["fr", "en", "es"])
async def test_no_physiological_conclusion_is_drawn_from_two_sessions(lang):
    memory = cac._refs("pair", ["wB", "wA"], primary="wA")
    contract = (await _turn(_db(A(), B()), "compare", memory=memory, language=lang))
    for conclusion in ("fitness_progress", "vo2max_change", "lactate_threshold_change", "better_recovery",
                       "higher_physiological_difficulty"):
        assert conclusion in contract["contract"]["undemonstrated_conclusions"]
    assert contract["contract"]["allowed_interpretations"] == [
        "measured_values", "computed_gaps", "which_session_is_higher_per_metric"]


@pytest.mark.parametrize("message", ["Est-ce cohérent avec mon objectif 10 km ?", "Is it consistent with my 10 km goal?",
                                     "¿Es coherente con mi objetivo de 10 km?"])
def test_goal_distance_is_not_an_activity_selector(message):
    assert cac.parse_message(message, TODAY)["selectors"] == []
