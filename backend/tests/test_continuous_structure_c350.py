"""C350 — conservative recognition of continuous sessions.

Synthetic fixtures only: no Mongo data, no real athlete values, no physiological
threshold. Laps never prove continuity; Garmin typed-splits or an explicit
record do, with the same criteria for the session and its history references.
"""

import asyncio
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from activity_phases import ActivityPhase
from garmin_laps_analysis import (
    CHRONOLOGY_TOLERANCE_S,
    LAP_ALTERNATION_UNOBSERVABLE,
    adapt_garmin_laps,
    assess_lap_structure,
)
from workout_analysis_v2 import _build_similar_reference, build_workout_analysis_v2
from workout_analysis_v2_service import (
    _historical_garmin_sources,
    _reliable_activity_type,
    load_scoped_workout_analysis_v2,
)

LANGUAGES = ("fr", "en", "es")


def laps_fixture(distances=(1000,) * 9 + (330,), durations=(441,) * 9 + (147,), **lap_changes):
    """A 12/10-shaped session: 9.33 km, 10 coherent ACTIVE laps, no pause."""
    start = datetime(2026, 10, 12, 8, tzinfo=timezone.utc)
    laps = []
    for index, (distance, duration) in enumerate(zip(distances, durations)):
        lap = {
            "lap_index": index + 1, "order": index,
            "start_time_gmt": start.isoformat(), "distance_m": distance,
            "duration_s": duration, "moving_duration_s": duration,
            "elapsed_duration_s": duration, "average_speed_mps": distance / duration,
            "average_hr": 127, "max_hr": 140, "intensity_type": "ACTIVE",
        }
        lap.update(lap_changes)
        laps.append(lap)
        start += timedelta(seconds=duration)
    workout = {
        "id": "garmin-24701222152", "external_id": "24701222152", "user_id": "synthetic",
        "name": "Course à pied", "type": "run", "date": "2026-10-12",
        "distance_km": round(sum(distances) / 1000, 2),
        "duration_minutes": sum(durations) / 60,
        "avg_pace_min_km": 7.35, "avg_heart_rate": 127, "is_race": False,
    }
    activity = {
        "user_id": "synthetic", "external_id": "24701222152", "source": "garmin",
        "activity_laps": {
            "schema_version": 1, "status": "complete", "source": "garmin",
            "endpoint": "splits", "laps": laps,
        },
    }
    return workout, activity


def single_effort(duration_s, distance_m, source="garmin"):
    return [ActivityPhase(order=0, phase_type="effort", duration_s=duration_s,
                          distance_m=distance_m, source=source)]


def interval_phases(source="garmin"):
    phases = [ActivityPhase(order=0, phase_type="warmup", duration_s=600, distance_m=1500,
                            source=source)]
    for index in range(1, 4):
        phases += [
            ActivityPhase(order=index * 2 - 1, phase_type="effort", duration_s=300,
                          distance_m=1000, source=source),
            ActivityPhase(order=index * 2, phase_type="recovery", duration_s=120,
                          distance_m=300, source=source),
        ]
    return phases


def reference(index, **changes):
    base = dict(id=f"garmin-{100 + index}", external_id=str(100 + index), name="Run",
                date=f"2026-10-0{index}", type="run", distance_km=9.0, duration_minutes=63.0,
                avg_pace_min_km=7.0, avg_heart_rate=130, is_race=False)
    base.update(changes)
    return base


def refs(count=5, **changes):
    return [reference(index, **changes) for index in range(1, count + 1)]


def continuous_reference_phases(history):
    return {ref["id"]: single_effort(ref["duration_minutes"] * 60, ref["distance_km"] * 1000)
            for ref in history}


def history_items(analysis):
    return [item for item in analysis.coach_language.conclusions if item.category == "history"]


# --- Lap evidence: never sufficient, every blocker reported -------------------------------

def test_fully_coherent_laps_still_cannot_prove_continuity():
    workout, activity = laps_fixture()
    original = deepcopy((workout, activity))
    result = assess_lap_structure(workout, activity)
    assert result.status == "unknown"
    assert result.reasons == (LAP_ALTERNATION_UNOBSERVABLE,)
    assert result.lap_count == 10
    assert (workout, activity) == original


def test_homogeneous_laps_and_absent_phases_do_not_classify_the_12_10_session():
    workout, activity = laps_fixture()
    assert adapt_garmin_laps(workout, activity).status == "eligible"
    history = refs()
    for language in LANGUAGES:
        analysis = build_workout_analysis_v2(workout, history, language, None)
        assert analysis.signals.session_structure.available is False
        assert analysis.comparison.similar.sample_count == 5
        assert history_items(analysis) == []
        # Even references proven continuous do not unlock an unknown current session.
        analysis = build_workout_analysis_v2(
            workout, history, language, None,
            historical_phases=continuous_reference_phases(history),
        )
        assert analysis.comparison.similar.pace_structure_status == "continuous_recorded"
        assert analysis.signals.session_structure.available is False
        assert history_items(analysis) == []


@pytest.mark.parametrize("intensities", [
    ["ACTIVE", "INTERVAL", "RECOVERY", "INTERVAL", "RECOVERY", "ACTIVE",
     "ACTIVE", "ACTIVE", "ACTIVE", "ACTIVE"],
    ["ACTIVE"] * 5 + ["REST"] + ["ACTIVE"] * 4,
])
def test_explicit_intensity_variation_is_a_hint_never_a_classification(intensities):
    workout, activity = laps_fixture()
    for lap, value in zip(activity["activity_laps"]["laps"], intensities):
        lap["intensity_type"] = value
    result = assess_lap_structure(workout, activity)
    assert result.status == "unknown"
    assert "intensity_variation_recorded" in result.reasons
    analysis = build_workout_analysis_v2(workout, [], "en", None)
    assert analysis.signals.session_structure.available is False


def test_missing_intensity_is_reported():
    workout, activity = laps_fixture(intensity_type=None)
    assert assess_lap_structure(workout, activity).reasons == (
        "intensity_missing", LAP_ALTERNATION_UNOBSERVABLE,
    )


# --- Fractionné ---------------------------------------------------------------------------

@pytest.mark.parametrize("language", LANGUAGES)
def test_interval_session_stays_intervals_without_history(language):
    workout = dict(laps_fixture()[0], distance_km=6.0, duration_minutes=40.0)
    history = refs(distance_km=6.0)
    analysis = build_workout_analysis_v2(
        workout, history, language, interval_phases(),
        historical_phases=continuous_reference_phases(history),
    )
    assert analysis.signals.session_structure.code == "intervals"
    assert history_items(analysis) == []


# --- Incomplete laps / pauses / chronology / insufficient data ----------------------------

def test_incomplete_laps_coverage_is_reported():
    workout, activity = laps_fixture()
    activity["activity_laps"]["laps"].pop()
    assert assess_lap_structure(workout, activity).reasons == (
        "coverage_incomplete", LAP_ALTERNATION_UNOBSERVABLE,
    )


def test_partial_timestamps_are_reported():
    workout, activity = laps_fixture()
    activity["activity_laps"]["laps"][3]["start_time_gmt"] = None
    assert "chronology_incomplete" in assess_lap_structure(workout, activity).reasons


def test_absent_timestamps_are_reported():
    workout, activity = laps_fixture(start_time_gmt=None)
    assert "chronology_missing" in assess_lap_structure(workout, activity).reasons


def shift_lap_starts(activity, first_index, seconds):
    for lap in activity["activity_laps"]["laps"][first_index:]:
        start = datetime.fromisoformat(lap["start_time_gmt"]) + timedelta(seconds=seconds)
        lap["start_time_gmt"] = start.isoformat()


@pytest.mark.parametrize("gap, incoherent", [
    (CHRONOLOGY_TOLERANCE_S, False), (1.058, True), (2, True), (-2, True),
])
def test_chronology_keeps_the_one_second_tolerance(gap, incoherent):
    workout, activity = laps_fixture()
    shift_lap_starts(activity, 4, gap)
    reasons = assess_lap_structure(workout, activity).reasons
    assert ("chronology_incoherent" in reasons) is incoherent
    assert reasons[-1] == LAP_ALTERNATION_UNOBSERVABLE


def test_recorded_pause_is_reported():
    workout, activity = laps_fixture()
    lap = activity["activity_laps"]["laps"][4]
    lap["elapsed_duration_s"] = lap["duration_s"] + 60
    shift_lap_starts(activity, 5, 60)
    reasons = assess_lap_structure(workout, activity).reasons
    assert reasons == ("pause_recorded", LAP_ALTERNATION_UNOBSERVABLE)


def test_stationary_time_is_reported():
    workout, activity = laps_fixture()
    lap = activity["activity_laps"]["laps"][2]
    lap["moving_duration_s"] = lap["duration_s"] - 20
    assert "stationary_time_recorded" in assess_lap_structure(workout, activity).reasons


def test_unverifiable_pauses_are_reported():
    workout, activity = laps_fixture(moving_duration_s=None)
    assert "pause_unverifiable" in assess_lap_structure(workout, activity).reasons


def test_incoherent_lap_times_are_reported():
    workout, activity = laps_fixture()
    lap = activity["activity_laps"]["laps"][1]
    lap["moving_duration_s"] = lap["duration_s"] + 5
    assert "time_incoherent" in assess_lap_structure(workout, activity).reasons


@pytest.mark.parametrize("mutate, reason", [
    (lambda w, a: w.update(id="manual-1", data_source="manual"), "not_garmin"),
    (lambda w, a: a.pop("activity_laps"), "laps_missing"),
    (lambda w, a: a["activity_laps"].update(status="empty", laps=[]), "laps_empty"),
    (lambda w, a: a["activity_laps"].update(schema_version=2), "laps_invalid"),
    (lambda w, a: a["activity_laps"].update(status="partial"), "laps_invalid"),
    (lambda w, a: a["activity_laps"]["laps"][2].update(order=0), "laps_invalid"),
    (lambda w, a: a["activity_laps"]["laps"][2].update(distance_m=0), "laps_invalid"),
    (lambda w, a: a["activity_laps"]["laps"][2].update(average_speed_mps=9.9), "laps_invalid"),
    (lambda w, a: a["activity_laps"]["laps"][2].update(
        start_time_gmt="2026-10-12T10:00:00+02:00"), "laps_invalid"),
    (lambda w, a: w.update(duration_minutes=None), "summary_missing"),
])
def test_insufficient_data_is_reported_alone(mutate, reason):
    workout, activity = laps_fixture()
    mutate(workout, activity)
    result = assess_lap_structure(workout, activity)
    assert result.status == "unknown" and result.reasons == (reason,)


def test_missing_activity_document_is_reported():
    workout, _ = laps_fixture()
    assert assess_lap_structure(workout, None).reasons == ("activity_missing",)


# --- Demonstrable continuous session ------------------------------------------------------

@pytest.mark.parametrize("language", LANGUAGES)
def test_demonstrable_continuous_session_receives_strong_history(language):
    workout, _ = laps_fixture()
    phases = single_effort(workout["duration_minutes"] * 60, workout["distance_km"] * 1000)
    history = refs()
    analysis = build_workout_analysis_v2(
        workout, history, language, phases,
        historical_phases=continuous_reference_phases(history),
    )
    assert analysis.signals.session_structure.code == "continuous"
    similar = analysis.comparison.similar
    assert similar.pace_structure_status == similar.hr_structure_status == "continuous_recorded"
    items = history_items(analysis)
    assert [item.metadata["comparability"] for item in items] == ["strong"]


def test_single_effort_not_covering_the_session_is_not_continuous():
    workout, _ = laps_fixture()
    phases = single_effort(workout["duration_minutes"] * 60 * 0.9, workout["distance_km"] * 900)
    analysis = build_workout_analysis_v2(workout, refs(), "en", phases)
    assert analysis.signals.session_structure.code == "other"
    assert history_items(analysis) == []


# --- Historical references: same criteria, no inference ----------------------------------

def similar(workout, history, historical_phases=None):
    return _build_similar_reference(workout, history, "en", historical_phases)


def current_continuous():
    workout, _ = laps_fixture()
    return dict(workout, session_structure="continuous")


def test_references_without_evidence_stay_unknown_and_limited():
    workout = current_continuous()
    history = refs()
    ref = similar(workout, history)
    assert ref.pace_structure_status == ref.hr_structure_status == "unknown"
    items = history_items(build_workout_analysis_v2(workout, history, "en"))
    assert [item.metadata["comparability"] for item in items] == ["distance_only"]
    assert items[0].kind == "descriptive"


def test_reference_typed_splits_use_the_session_criteria():
    workout = current_continuous()
    history = refs()
    assert similar(workout, history, continuous_reference_phases(history)) \
        .pace_structure_status == "continuous_recorded"


@pytest.mark.parametrize("phases_for", [
    lambda ref: interval_phases(),
    lambda ref: single_effort(ref["duration_minutes"] * 60 * 0.8, ref["distance_km"] * 800),
    lambda ref: [ActivityPhase(order=0, phase_type="unknown",
                               duration_s=ref["duration_minutes"] * 60, source="garmin")],
])
def test_one_non_continuous_reference_blocks_recorded_status(phases_for):
    workout = current_continuous()
    history = refs()
    historical_phases = continuous_reference_phases(history)
    historical_phases[history[2]["id"]] = phases_for(history[2])
    ref = similar(workout, history, historical_phases)
    assert ref.pace_structure_status == "unknown"


def test_reference_phases_override_a_contradicting_record():
    workout = current_continuous()
    history = refs(session_structure="continuous")
    assert similar(workout, history).pace_structure_status == "continuous_recorded"
    phases = {history[0]["id"]: interval_phases()}
    assert similar(workout, history, phases).pace_structure_status == "unknown"


def test_reference_names_never_promote_structure():
    workout = current_continuous()
    history = refs(name="Footing continu easy")
    assert similar(workout, history).pace_structure_status == "unknown"


# --- 19/10 treadmill: no artificial conclusion -------------------------------------------

@pytest.mark.parametrize("language", LANGUAGES)
def test_treadmill_without_structure_or_reference_stays_silent(language):
    workout = {
        "id": "garmin-24781607161", "name": "Tapis de course", "type": "run",
        "date": "2026-10-19", "distance_km": 5.0, "duration_minutes": 35.0,
        "avg_pace_min_km": 7.0, "avg_heart_rate": 125,
    }
    analysis = build_workout_analysis_v2(workout, [], language, None, historical_phases={})
    assert analysis.signals.session_structure.available is False
    assert analysis.comparison.similar.available is False
    assert analysis.coach_language.conclusions == []


# --- Service: read-only reference phases --------------------------------------------------

class Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *_):
        return self

    async def to_list(self, **_):
        return self.docs


def details(phases):
    return {"schema_version": 2, "status": "complete", "source": "garmin",
            "endpoint": "typed-splits",
            "phases": [phase.model_dump(exclude={"pace_sec_per_km"}) for phase in phases]}


def fake_db(workout, activity, history, history_docs, fail=False):
    calls = []

    def find_activities(query, projection):
        calls.append((query, projection))
        if fail:
            raise RuntimeError("unavailable")
        return Cursor(history_docs)

    db = SimpleNamespace(
        workouts=SimpleNamespace(find_one=AsyncMock(return_value=workout),
                                 find=lambda *_: Cursor(history)),
        garmin_activities=SimpleNamespace(find_one=AsyncMock(return_value=activity),
                                          find=find_activities),
    )
    return db, calls


def history_docs(history, phases_for):
    return [{"external_id": ref["external_id"], "activity_details": details(phases_for(ref))}
            for ref in history]


def run_service(db, workout):
    return asyncio.run(load_scoped_workout_analysis_v2(
        db=db, user_id="synthetic", workout_id=workout["id"], language="fr",
    ))


def test_service_reads_reference_phases_once_and_never_writes():
    workout, activity = laps_fixture()
    activity["activity_details"] = details(single_effort(
        workout["duration_minutes"] * 60, workout["distance_km"] * 1000))
    history = refs()
    docs = history_docs(history, lambda ref: single_effort(
        ref["duration_minutes"] * 60, ref["distance_km"] * 1000))
    db, calls = fake_db(workout, activity, history, docs)
    _, analysis = run_service(db, workout)
    assert analysis.signals.session_structure.code == "continuous"
    assert analysis.comparison.similar.pace_structure_status == "continuous_recorded"
    assert [item.metadata["comparability"] for item in history_items(analysis)] == ["strong"]
    assert len(calls) == 1
    query, projection = calls[0]
    assert query["user_id"] == "synthetic"
    assert set(query["external_id"]["$in"]) >= {ref["external_id"] for ref in history}
    assert projection == {"_id": 0, "external_id": 1, "activity_details": 1,
                          "activity_type": 1, "garmin_activity.activity_type": 1}
    assert not any(hasattr(collection, name) for collection in (db.workouts, db.garmin_activities)
                   for name in ("update_one", "update_many", "insert_one", "replace_one"))


def test_service_12_10_without_reliable_types_stays_silent():
    workout, activity = laps_fixture()
    history = refs()
    docs = history_docs(history, lambda ref: single_effort(
        ref["duration_minutes"] * 60, ref["distance_km"] * 1000))
    db, _ = fake_db(workout, activity, history, docs)
    _, analysis = run_service(db, workout)
    assert analysis.comparison.similar.sample_count == 5
    assert analysis.signals.session_structure.available is False
    assert history_items(analysis) == []


def test_service_reference_lookup_failure_keeps_unknown_structure():
    workout, activity = laps_fixture()
    activity["activity_details"] = details(single_effort(
        workout["duration_minutes"] * 60, workout["distance_km"] * 1000))
    history = refs()
    db, _ = fake_db(workout, activity, history, [], fail=True)
    _, analysis = run_service(db, workout)
    assert analysis.comparison.similar.pace_structure_status == "unknown"
    assert [item.metadata["comparability"] for item in history_items(analysis)] == ["distance_only"]


def test_ambiguous_or_invalid_reference_documents_are_ignored():
    history = refs(count=3)
    good = details(single_effort(3780, 9000))
    invalid = dict(good, schema_version=1)
    docs = [
        {"external_id": history[0]["external_id"], "activity_details": good},
        {"external_id": int(history[0]["external_id"]), "activity_details": good},
        {"external_id": history[1]["external_id"], "activity_details": invalid},
        {"external_id": history[2]["external_id"], "activity_details": good},
    ]
    db, _ = fake_db(None, None, history, docs)
    phases, types = asyncio.run(_historical_garmin_sources(db, "synthetic", history))
    assert set(phases) == {history[2]["id"]}
    assert types == {}


def test_non_garmin_references_trigger_no_lookup():
    history = refs(count=2)
    for ref in history:
        ref.update(id=f"manual-{ref['id']}", external_id=None)
    db, calls = fake_db(None, None, history, [])
    assert asyncio.run(_historical_garmin_sources(db, "synthetic", history)) == ({}, {})
    assert calls == []
