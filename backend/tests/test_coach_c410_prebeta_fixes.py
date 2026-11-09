"""C410 — pre-beta Coach fixes D/E/F (deterministic, no model call, no Garmin call)."""

from datetime import date

import pytest

from test_coach_contract_unified import _FakeDB  # sets env first
import coach_activity_conversation as cac

pytestmark = pytest.mark.asyncio

TODAY = date(2026, 11, 8)


def _run(wid, start, km, minutes, pace_s, hr, user="user-a", **extra):
    doc = {
        "id": wid, "user_id": user, "type": "run", "name": "Course", "date": start, "distance_km": km,
        "duration_minutes": minutes, "avg_pace_min_km": pace_s / 60.0, "avg_heart_rate": hr,
        "data_source": "manual",
    }
    doc.update(extra)
    return doc


def _db(*workouts, activities=()):
    db = _FakeDB()
    db.workouts._docs.extend(dict(w) for w in workouts)
    db.garmin_activities._docs.extend(dict(a) for a in activities)
    return db


async def _turn(db, message, language="fr", memory=None, user="user-a"):
    return await cac.resolve_turn(
        db=db, user_id=user, message=message, language=language, today=TODAY, memory=memory)


LAST = _run("w3", "2026-11-05T08:00:00", 10.0, 55, 330, 150)
PREV = _run("w2", "2026-11-01T08:00:00", 10.2, 58, 341, 148)
OLDER = _run("w1", "2026-10-20T08:00:00", 10.1, 57, 338, 147)


# ---------------------------------------------------------------- D: last vs previous

@pytest.mark.parametrize("message,language", [
    ("Compare ma dernière sortie avec la précédente", "fr"),
    ("Compare my last run with the previous one", "en"),
    ("Compara mi última salida con la anterior", "es"),
])
async def test_last_vs_previous_resolves_both_without_clarification(message, language):
    turn = await _turn(_db(OLDER, PREV, LAST), message, language)
    assert turn["kind"] == "compare"
    assert turn["refs"]["workout_ids"] == ["w2", "w3"]


async def test_last_vs_previous_needs_two_runs():
    turn = await _turn(_db(LAST), "Compare ma dernière sortie avec la précédente")
    assert turn["kind"] == "reply"


async def test_last_vs_previous_is_owner_scoped():
    other = _run("x1", "2026-11-06T08:00:00", 10.0, 55, 330, 150, user="user-b")
    turn = await _turn(_db(LAST, other), "Compare ma dernière sortie avec la précédente")
    assert turn["kind"] == "reply"


async def test_plural_previous_runs_still_a_history_request():
    parsed = cac.parse_message("compare my last run with my previous runs", TODAY)
    assert parsed["history"] is not None and not parsed["selectors"]


# ---------------------------------------------------------------- E: similar-distance history

@pytest.mark.parametrize("message", [
    "Montre-moi mes 3 dernières sorties de même distance",
    "Show me my last 3 runs of the same distance",
    "Muéstrame mis 3 últimas salidas de la misma distancia",
])
async def test_same_distance_history_is_deterministic(message):
    parsed = cac.parse_message(message, TODAY)
    assert parsed["history"] == {"kind": "similar", "count": 3}


async def test_same_distance_history_with_reference():
    runs = [_run(f"h{i}", f"2026-10-{i + 1:02d}T08:00:00", 10.0, 55, 330, 150) for i in range(4)]
    reference = _run("ref", "2026-11-05T08:00:00", 10.0, 55, 330, 150)
    memory = {"v": 1, "kind": "single", "workout_ids": ["ref"]}
    turn = await _turn(_db(*runs, reference), "Montre-moi mes 3 dernières sorties de même distance", memory=memory)
    assert turn["kind"] == "compare"
    assert [f["id"] for f in turn["contract"]["population"]] == ["h1", "h2", "h3"]
    assert turn["contract"]["criterion"]["kind"] == "similar"


async def test_same_distance_history_without_reference_offers_runs():
    turn = await _turn(_db(OLDER, PREV, LAST), "Montre-moi mes 3 dernières sorties de même distance")
    assert turn["kind"] == "reply" and "1)" in turn["text"]
    assert [c["id"] for c in turn["refs"]["pending"]["choices"]] == ["w3", "w2", "w1"]
    answer = await _turn(_db(OLDER, PREV, LAST), "la 1", memory=turn["refs"])
    assert answer["kind"] == "compare" and answer["contract"]["reference"]["id"] == "w3"


async def test_same_distance_history_reference_without_distance():
    no_distance = _run("nd", "2026-11-05T08:00:00", 10.0, 55, 330, 150)
    no_distance["distance_km"] = None
    memory = {"v": 1, "kind": "single", "workout_ids": ["nd"]}
    turn = await _turn(_db(no_distance, OLDER), "Show me my last 3 runs of the same distance", "en", memory)
    assert turn["kind"] == "compare" and "no distance" in turn["text"]


# ---------------------------------------------------------------- F: treadmill / outdoor

def _garmin(wid, ext, start, km, minutes, pace_s, hr, activity_type):
    workout = _run(wid, start, km, minutes, pace_s, hr, data_source="garmin", external_id=ext)
    return workout, {"user_id": "user-a", "external_id": ext, "activity_type": activity_type}


@pytest.mark.parametrize("language,fragment", [
    ("fr", "tapis"), ("en", "treadmill"), ("es", "cinta"),
])
async def test_treadmill_vs_outdoor_adds_reserve(language, fragment):
    t_w, t_a = _garmin("gt", "1", "2026-10-19T08:00:00", 10.0, 55, 330, 150, "treadmill_running")
    o_w, o_a = _garmin("go", "2", "2026-10-12T08:00:00", 10.0, 58, 348, 148, "running")
    turn = await _turn(_db(t_w, o_w, activities=(t_a, o_a)), "Compare 12/10 et 19/10", language)
    assert turn["kind"] == "compare"
    assert turn["contract"]["environments_differ"] is True
    assert fragment in turn["text"]


async def test_same_environment_has_no_reserve():
    a_w, a_a = _garmin("ga", "1", "2026-10-19T08:00:00", 10.0, 55, 330, 150, "running")
    b_w, b_a = _garmin("gb", "2", "2026-10-12T08:00:00", 10.0, 58, 348, 148, "running")
    turn = await _turn(_db(a_w, b_w, activities=(a_a, b_a)), "Compare 12/10 et 19/10", "en")
    assert turn["contract"]["environments_differ"] is False
    assert "treadmill" not in turn["text"]


async def test_unknown_environment_is_not_guessed_from_name():
    a_w, _ = _garmin("ga", "1", "2026-10-19T08:00:00", 10.0, 55, 330, 150, "running")
    a_w["name"] = "Tapis du matin"
    b_w = _run("gb", "2026-10-12T08:00:00", 10.0, 58, 348, 148)
    turn = await _turn(_db(a_w, b_w), "Compare 12/10 et 19/10", "fr")
    assert turn["contract"]["environments_differ"] is False


async def test_history_flags_environment_mismatch():
    ref_w, ref_a = _garmin("ref", "9", "2026-11-05T08:00:00", 10.0, 55, 330, 150, "treadmill_running")
    o_w, o_a = _garmin("h1", "8", "2026-10-12T08:00:00", 10.0, 58, 348, 148, "running")
    t_w, t_a = _garmin("h2", "7", "2026-10-19T08:00:00", 10.0, 56, 336, 149, "treadmill_running")
    memory = {"v": 1, "kind": "single", "workout_ids": ["ref"]}
    turn = await _turn(_db(ref_w, o_w, t_w, activities=(ref_a, o_a, t_a)),
                       "Show me my last 3 runs of the same distance", "en", memory)
    assert turn["contract"]["environment_differs"] == {"count": 1, "of": 2}
    assert "not in the same environment" in turn["text"]
