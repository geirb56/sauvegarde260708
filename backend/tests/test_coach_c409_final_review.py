"""C409 final review (PR #399): one adversarial test per open review remark.

Fixtures: "today" is Sunday 2026-11-08; A = 12/10/2026 (9.33 km), B = 13/09/2026 (21.27 km).
"""

from unittest.mock import AsyncMock, patch

import pytest

from test_coach_c409_activity_conversation import (
    A, B, TODAY, _db, _history_runs, _post, _run, _turn,
)
from test_coach_c409_review_fixes import _assistants, _chat, _llm_calls
from test_coach_contract_unified import _free_access
import coach_activity_conversation as cac

pytestmark = pytest.mark.asyncio

LANGS = ("fr", "en", "es")


# ---- A. explicit dates in historical comparisons

@pytest.mark.parametrize("message,language", [
    ("Compare ma sortie du 2026-10-12 avec mes trois dernières sorties similaires.", "fr"),
    ("Compare ma sortie du 12/10/2026 avec mes trois dernières sorties similaires.", "fr"),
    ("Compare ma sortie du 12 octobre avec mes trois dernières sorties similaires.", "fr"),
    ("Compare my run on October 12, 2026 with my last three similar runs.", "en"),
    ("Compare my run on 2026-10-12 with my last three similar runs.", "en"),
    ("Compara mi salida del 12 de octubre con mis últimas tres salidas similares.", "es"),
])
async def test_explicit_date_wins_over_remembered_activity_in_history(message, language):
    parsed = cac.parse_message(message, TODAY)
    assert [s["date"].isoformat() for s in parsed["selectors"]] == ["2026-10-12"]
    assert parsed["history"]["kind"] == "similar"
    db = _db(A(), B(), *_history_runs())
    turn = await _turn(db, message, memory=cac._refs("single", ["wB"], primary="wB"), language=language)
    assert turn["kind"] == "compare" and turn["contract"]["reference"]["id"] == "wA"


# ---- B. distance filter applied in the owner-scoped query, before the limit

@pytest.mark.parametrize("message,language", [
    ("Analyse mon dernier semi-marathon", "fr"),
    ("Analyze my last half marathon", "en"),
    ("Analiza mi último medio maratón", "es"),
])
async def test_old_half_marathon_found_behind_many_recent_short_runs(message, language):
    runs = [_run(f"s{i}", f"2026-10-{1 + i // 10:02d}T06:{i % 10:02d}:00", 5.0, 30, 360, 140) for i in range(220)]
    half = _run("half", "2026-03-15T08:00:00", 21.1, 120, 340, 150)
    db = _db(*runs, half)
    turn = await _turn(db, message, language=language)
    assert turn["kind"] == "single" and turn["workout_id"] == "half"


async def test_distance_query_is_bounded_and_owner_scoped():
    db = _db(_run("half", "2026-03-15T08:00:00", 21.1, 120, 340, 150),
             _run("other", "2026-04-15T08:00:00", 21.1, 120, 340, 150, user="user-b"))
    queries = []
    original = db.workouts.find

    def spy(query=None, projection=None):
        queries.append(query)
        return original(query, projection)

    db.workouts.find = spy
    turn = await _turn(db, "Analyse mon dernier semi-marathon")
    assert turn["workout_id"] == "half"
    query = queries[0]
    assert query["user_id"] == "user-a" and query["type"] == "run" and "distance_km" in query


# ---- C. absent metrics

@pytest.mark.parametrize("language", LANGS)
async def test_hr_question_with_no_hr_on_both_sessions_is_explicitly_impossible(language):
    a, b = A(), B()
    a["avg_heart_rate"] = b["avg_heart_rate"] = None
    memory = cac._refs("pair", ["wB", "wA"], primary="wA")
    message = {"fr": "Et au niveau du cardio ?", "en": "And heart rate?", "es": "¿Y la frecuencia cardíaca?"}[language]
    turn = await _turn(_db(a, b), message, memory=memory, language=language)
    assert turn["kind"] == "compare" and turn["text"].strip()
    assert turn["text"] == cac.t("no_metric", language)
    assert "bpm" not in turn["text"]


@pytest.mark.parametrize("language", LANGS)
async def test_metric_present_for_one_session_only_is_reported_not_invented(language):
    a = A()
    a["avg_heart_rate"] = None
    memory = cac._refs("pair", ["wB", "wA"], primary="wA")
    message = {"fr": "Et le cardio ?", "en": "And heart rate?", "es": "¿Y el cardio?"}[language]
    turn = await _turn(_db(a, B()), message, memory=memory, language=language)
    assert turn["kind"] == "compare" and "12/10/2026" in turn["text"]
    assert "33" not in turn["text"] and "127" not in turn["text"]  # no invented gap, no fabricated value


# ---- D. historical enrichment and per-metric counts

async def test_history_population_is_enriched_from_stored_garmin_documents():
    runs = _history_runs()
    for run in runs:
        run["avg_heart_rate"] = None
        run["data_source"] = "garmin"
        run["external_id"] = f"ext-{run['id']}"
    db = _db(A(), *runs)
    db.garmin_activities._docs.extend(
        {"user_id": "user-a", "external_id": f"ext-{r['id']}", "averageHR": 150 + i} for i, r in enumerate(runs))
    contract = (await _turn(db, "Compare ma sortie du 12 octobre avec mes trois dernières sorties récentes"))["contract"]
    assert len(contract["population"]) == 3
    assert all(f["avg_hr"] is not None for f in contract["population"])
    assert contract["population_stats"]["avg_hr"]["n"] == 3


@pytest.mark.parametrize("language", LANGS)
async def test_history_shows_the_sample_size_of_each_metric(language):
    runs = _history_runs()
    runs[6]["avg_heart_rate"] = None
    db = _db(A(), *runs)
    message = {"fr": "Compare ma sortie du 12 octobre avec mes trois dernières sorties",
               "en": "Compare my run on October 12 with my last three runs",
               "es": "Compara mi salida del 12 de octubre con mis últimas tres salidas"}[language]
    turn = await _turn(db, message, language=language)
    stats = turn["contract"]["population_stats"]
    assert stats["avg_hr"]["n"] == 2 and stats["distance_km"]["n"] == 3
    assert "2/3" in turn["text"]


# ---- E. planning is not an activity lookup

@pytest.mark.parametrize("message", [
    "Que dois-je faire aujourd'hui ?", "Que dois-je faire demain ?", "Quelle allure cible pour 10 km demain ?",
    "What should I do today?", "What target pace for 10 km tomorrow?", "What should I run next week?",
    "¿Qué debo hacer hoy?", "¿Qué ritmo objetivo para 10 km mañana?",
])
async def test_planning_questions_are_not_activity_selectors(message):
    parsed = cac.parse_message(message, TODAY)
    assert parsed["selectors"] == [] and parsed["history"] is None and parsed["plan_related"]
    turn = await _turn(_db(A(), B()), message, memory=cac._refs("single", ["wA"], primary="wA"))
    assert turn["kind"] == "passthrough"


@pytest.mark.parametrize("message,expected", [
    ("Analyse ma sortie d'aujourd'hui", "2026-11-08"),
    ("Analyze my run today", "2026-11-08"),
    ("Analiza mi salida de hoy", "2026-11-08"),
    ("Analyse ma sortie d'hier", "2026-11-07"),
])
async def test_completed_activity_requests_today_still_resolve(message, expected):
    parsed = cac.parse_message(message, TODAY)
    assert [s["date"].isoformat() for s in parsed["selectors"]] == [expected]


async def test_planning_question_reaches_the_existing_coach_and_free_tier_is_not_restricted():
    db = _db(A(), B())
    with _chat(db):
        response = await _post({"message": "Que dois-je faire demain ?", "language": "fr"})
        assert response.status_code == 200 and _llm_calls() == 1
    db = _db(A(), B())
    with _chat(db, _free_access):
        response = await _post({"message": "Que dois-je faire aujourd'hui ?", "language": "fr"})
    assert response.status_code == 200 and "essai actif" not in response.json()["response"]


# ---- F. continuity of historical comparisons

async def test_history_followup_keeps_reference_population_and_criterion():
    db = _db(A(), B(), *_history_runs())
    first = await _turn(db, "Compare ma sortie du 12 octobre avec mes trois dernières sorties récentes")
    refs = first["refs"]
    assert refs["kind"] == "history" and refs["workout_ids"] == ["wA"] and refs["history"]["count"] == 3
    followup = await _turn(db, "Et au niveau du cardio ?", memory=refs)
    assert followup["kind"] == "compare" and followup["contract"]["kind"] == "history"
    assert followup["contract"]["reference"]["id"] == "wA"
    assert [f["id"] for f in followup["contract"]["population"]] == [f["id"] for f in first["contract"]["population"]]
    assert followup["contract"]["criterion"] == first["contract"]["criterion"]
    assert "127 bpm" in followup["text"] and "FC" in followup["text"]


@pytest.mark.parametrize("language", LANGS)
async def test_history_followup_in_every_language(language):
    db = _db(A(), B(), *_history_runs())
    refs = cac._refs("history", ["wA"], primary="wA") | {"history": {"kind": "recent", "count": 3}}
    message = {"fr": "Et leur cardio ?", "en": "And their heart rate?", "es": "¿Y su frecuencia cardíaca?"}[language]
    turn = await _turn(db, message, memory=refs, language=language)
    assert turn["kind"] == "compare" and turn["contract"]["kind"] == "history"
    assert "127" in turn["text"]


async def test_history_followup_dropped_after_topic_change_and_for_other_users():
    db = _db(A(), B(), *_history_runs())
    refs = cac._refs("history", ["wA"], primary="wA") | {"history": {"kind": "recent", "count": 3}}
    changed = await _turn(db, "Changeons de sujet. Et le cardio ?", memory=refs)
    assert changed["kind"] != "compare"
    foreign = await _turn(db, "Et le cardio ?", memory=refs, user="user-b")
    assert foreign["kind"] != "compare"


async def test_history_followup_through_the_server_and_stored_refs():
    db = _db(A(), B(), *_history_runs())
    with _chat(db):
        r1 = await _post({"message": "Compare ma sortie du 12 octobre avec mes trois dernières sorties récentes",
                          "language": "fr"})
        calls = _llm_calls()
        r2 = await _post({"message": "Et au niveau du cardio ?", "language": "fr"})
        assert _llm_calls() == calls
    assert r1.status_code == r2.status_code == 200
    refs = [d["coach_refs"] for d in _assistants(db)]
    assert refs[0]["kind"] == refs[1]["kind"] == "history" and refs[1]["workout_ids"] == ["wA"]
    assert "127 bpm" in r2.json()["response"]


# ---- G. continuity without seeded references

async def test_real_three_turn_continuity_without_injected_refs():
    db = _db(A(), B())
    with _chat(db):
        r1 = await _post({"message": "Analyse ma sortie du 12 octobre.", "language": "fr"})
        persisted = _assistants(db)[0]["coach_refs"]
        r2 = await _post({"message": "Compare-la avec celle du 13 septembre.", "language": "fr"})
        r3 = await _post({"message": "Et au niveau du cardio ?", "language": "fr"})
    assert r1.status_code == r2.status_code == r3.status_code == 200
    assert persisted["workout_ids"] == ["wA"]
    assert [d["coach_refs"]["workout_ids"] for d in _assistants(db)[1:]] == [["wB", "wA"]] * 2
    assert "160 bpm" in r3.json()["response"] and "33 bpm" in r3.json()["response"]


# ---- obsolete remarks: regression tests

@pytest.mark.parametrize("message", ["Analyze my last half marathon", "my last half marathon", "Analyse mon dernier semi",
                                     "Analyse mon dernier semi-marathon", "Analiza mi última media maratón"])
async def test_last_half_marathon_is_recognised_and_beats_the_marathon(message):
    selectors = cac.parse_message(message, TODAY)["selectors"]
    assert selectors and selectors[0]["type"] in ("last", "distance") and selectors[0]["km"] == (20.5, 22.0)


async def test_marathon_is_still_a_marathon():
    assert cac.parse_message("Analyse mon dernier marathon", TODAY)["selectors"][0]["km"] == (41.5, 43.5)


@pytest.mark.parametrize("language", LANGS)
async def test_progress_answer_does_not_assert_different_distances_or_purposes(language):
    same = [_run("p1", "2026-10-12T07:00:00", 10.0, 55, 330, 150), _run("p2", "2026-09-12T07:00:00", 10.0, 56, 336, 152)]
    message = {"fr": "Est-ce que je progresse ?", "en": "Am I improving?", "es": "¿Estoy progresando?"}[language]
    turn = await _turn(_db(*same), message, memory=cac._refs("pair", ["p2", "p1"], primary="p1"), language=language)
    text = turn["text"].lower()
    for forbidden in ("distances et d'objectifs différents", "different distances", "distancias y objetivos distintos"):
        assert forbidden not in text
    assert turn["contract"]["undemonstrated_conclusions"]


@pytest.mark.parametrize("language", LANGS)
async def test_pace_gap_is_described_as_faster_not_higher(language):
    turn = await _turn(_db(A(), B()), {"fr": "Compare ma sortie du 12 octobre avec celle du 13 septembre",
                                       "en": "Compare my run on October 12 with the one on September 13",
                                       "es": "Compara mi salida del 12 de octubre con la del 13 de septiembre"}[language],
                       language=language)
    sentence = turn["text"]
    word = {"fr": "plus rapide", "en": "faster", "es": "más rápid"}[language]
    assert word in sentence and "1 min 38 s/km" in sentence


@pytest.mark.parametrize("language", LANGS)
async def test_long_criterion_displays_the_count_of_timed_sessions(language):
    runs = [_run(f"h{i}", f"2026-08-{i + 1:02d}T08:00:00", 8.0, 50 if i < 4 else None, 360, 140) for i in range(5)]
    message = {"fr": "Compare ma sortie du 12 octobre avec mes trois dernières sorties longues",
               "en": "Compare my run on October 12 with my last three long runs",
               "es": "Compara mi salida del 12 de octubre con mis últimas tres salidas largas"}[language]
    turn = await _turn(_db(A(), *runs), message, language=language)
    contract = turn["contract"]
    assert contract["criterion"]["established"] is False and contract["window_size"] == 5
    assert contract["timed_sessions"] == 4
    expected = cac.t("h_long_unset", language, n=cac.LONG_RUN_MIN_HISTORY, w=contract["window_days"], have=4)
    assert expected in turn["text"]


async def test_ambiguous_first_selector_keeps_the_second_activity_of_the_comparison():
    other = _run("wA2", "2026-10-12T18:00:00", 5.0, 30, 360, 140)
    db = _db(A(), other, B())
    first = await _turn(db, "Compare ma sortie du 12 octobre avec celle du 13 septembre")
    pending = first["refs"]["pending"]
    assert first["kind"] == "reply" and pending["intent"]["action"] == "pair"
    assert pending["intent"]["others"] == ["wB"]
    second = await _turn(db, "la 2", memory=first["refs"])
    assert second["kind"] == "compare"
    assert {a["id"] for a in second["contract"]["activities"]} == {"wB", "wA2"}


async def test_clarification_keeps_the_pair_when_the_remembered_counterpart_is_used():
    other = _run("wA2", "2026-10-12T18:00:00", 5.0, 30, 360, 140)
    db = _db(A(), other, B())
    memory = cac._refs("single", ["wB"], primary="wB")
    first = await _turn(db, "Compare-la avec celle du 12 octobre", memory=memory)
    assert first["kind"] == "reply"
    second = await _turn(db, "la première", memory=first["refs"])
    assert second["kind"] == "compare"
    assert {a["id"] for a in second["contract"]["activities"]} == {"wB", "wA"}


# ---- finalisation: exact routing set

@pytest.mark.parametrize("message,kind", [
    ("Que dois-je faire aujourd'hui ?", "passthrough"),
    ("Quelle séance demain ?", "passthrough"),
    ("Quelle allure cible pour mon 10 km ?", "passthrough"),
    ("Analyse ma sortie d'aujourd'hui.", "single"),
])
async def test_planning_vs_analysis_routing_exact_set(message, kind):
    for memory in (None, cac._refs("single", ["wA"], primary="wA")):
        turn = await _turn(_db(A(), B()), message, memory=memory)
        if kind == "passthrough":
            assert turn["kind"] == "passthrough"
        else:
            assert turn["kind"] != "passthrough"
        if kind == "passthrough":
            assert not turn.get("workout_ids")


def test_compare_yesterday_with_monday_is_a_two_date_comparison():
    parsed = cac.parse_message("Compare ma séance d'hier avec celle de lundi.", TODAY)
    assert parsed["compare"] and len(parsed["selectors"]) == 2 and not parsed["plan_related"]
