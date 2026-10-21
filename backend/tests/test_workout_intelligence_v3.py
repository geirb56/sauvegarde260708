"""C352 — Workout Intelligence V3 Core.

All fixtures below are SYNTHETIC. They exercise the deterministic rules; they
are not a validation against real Garmin data.
"""

from __future__ import annotations

import asyncio
import inspect
import json
from datetime import date
from types import SimpleNamespace

import pytest

import workout_intelligence_v3 as wiv3
import workout_intelligence_v3_service as wiv3_service
from activity_phases import ACTIVITY_PHASE_SCHEMA_VERSION, ActivityPhase
from training_v2.prescription_snapshot import PrescriptionSnapshot, is_snapshot_authoritative
from workout_analysis_v2 import WorkoutAnalysisV2Response, build_workout_analysis_v2
from workout_intelligence_v3 import (
    build_workout_intelligence_v3,
    extract_workout_intelligence_input,
)
from workout_intelligence_v3_models import (
    WIV3PhysiologicalProfile,
    WIV3PrescriptionContext,
    WIV3ThresholdEstimate,
    WorkoutIntelligenceV3,
)

OUTDOOR = "running"
TREADMILL = "treadmill_running"


def _w(wid, day, *, hr=145, pace=6.0, duration=50, distance=None, max_hr=170, continuous=True, **extra):
    doc = {
        "id": wid, "user_id": "user-a", "date": day, "type": "run", "name": wid,
        "distance_km": distance if distance is not None else round(duration / pace, 2),
        "duration_minutes": duration, "avg_heart_rate": hr, "max_heart_rate": max_hr,
        "avg_pace_min_km": pace, "km_splits": [], "split_analysis": {},
    }
    if continuous:
        doc["session_structure"] = "continuous"
    doc.update(extra)
    return doc


def _lt(value, source="lab_test", on="2026-01-01", confidence="high"):
    return WIV3ThresholdEstimate(value_bpm=value, source=source, estimated_on=on, confidence=confidence)


PROFILE = WIV3PhysiologicalProfile(lt1=_lt(150), lt2=_lt(170), lt_source_status="provided")


def _phase(order, kind, duration, distance=None, hr=None):
    return ActivityPhase(
        order=order, native_type=kind.upper(), phase_type=kind, duration_s=duration,
        distance_m=distance, average_speed_mps=(distance / duration) if distance else None,
        average_hr=hr, max_hr=None, min_hr=None, source="synthetic",
    )


def _interval_phases():
    rows = [("warmup", 600, None, 130)]
    for index in range(5):
        rows += [("effort", 180, 800, 172 + index), ("recovery", 120, None, 140)]
    rows.append(("cooldown", 600, None, 130))
    return [_phase(i, *row) for i, row in enumerate(rows)]


def _analyze(current, history, *, types=None, phases=None, profile=PROFILE, prescription=None,
             language="en", historical_phases=None) -> WorkoutIntelligenceV3:
    all_ids = [current["id"]] + [item["id"] for item in history]
    activity_types = {wid: OUTDOOR for wid in all_ids} if types is None else types
    v2 = build_workout_analysis_v2(
        current, history, language, phases,
        historical_phases=historical_phases, activity_types=activity_types,
    )
    data = extract_workout_intelligence_input(
        current, history, v2_analysis=v2, activity_types=activity_types,
        historical_phases=historical_phases, profile=profile, prescription=prescription,
    )
    return build_workout_intelligence_v3(data, language)


def _flat_history(n=4, hr=145, pace=6.0, start_day=1, step=10):
    return [
        _w(f"h{i}", f"2026-03-{start_day + i * step:02d}" if start_day + i * step <= 31 else
           f"2026-04-{start_day + i * step - 31:02d}", hr=hr, pace=pace)
        for i in range(n)
    ]


CURRENT_DAY = "2026-05-10"


# 1 ─ Easy run under LT1 with coherent history
def test_easy_run_below_lt1_with_coherent_history():
    result = _analyze(_w("cur", CURRENT_DAY, hr=140, pace=6.0), _flat_history(hr=141))
    assert result.intensity_assessment.position == "below_LT1"
    assert result.intensity_assessment.lt1.source == "lab_test"
    assert result.intensity_assessment.confidence == "medium"  # capped: average HR only
    assert "average_hr_is_not_time_in_zone" in result.intensity_assessment.limitations
    assert result.session_classification.type == "easy_run_probable"
    assert result.historical_comparison.comparability == "strong"
    assert result.historical_comparison.pace_at_comparable_hr.reference_count == 4
    assert result.performance_trend.status == "stable"


# 2 ─ Easy run with HR between LT1 and LT2
def test_run_between_lt1_and_lt2_is_steady_with_low_confidence():
    result = _analyze(_w("cur", CURRENT_DAY, hr=160), _flat_history(hr=160))
    assert result.intensity_assessment.position == "between_LT1_LT2"
    assert result.session_classification.type == "steady_run_probable"
    assert result.session_classification.confidence == "low"
    assert "tempo_not_distinguishable_from_average_hr" in result.session_classification.limitations


# 3 ─ No reliable LT1/LT2
@pytest.mark.parametrize("profile", [
    WIV3PhysiologicalProfile(),
    WIV3PhysiologicalProfile(lt1=_lt(150, source="generic_formula"), lt2=_lt(170, source="generic_formula")),
    WIV3PhysiologicalProfile(lt1=_lt(150, confidence="low"), lt2=_lt(170, confidence="low")),
    WIV3PhysiologicalProfile(lt1=_lt(150, source="user_declared"), lt2=_lt(170, on=None)),
    WIV3PhysiologicalProfile(lt1=_lt(175), lt2=_lt(165)),
])
def test_missing_or_unreliable_thresholds_return_unknown(profile):
    result = _analyze(_w("cur", CURRENT_DAY, hr=140), _flat_history(), profile=profile)
    assert result.intensity_assessment.position == "unknown"
    assert result.intensity_assessment.lt1 is None and result.intensity_assessment.lt2 is None
    assert result.session_classification.type == "unknown"
    assert result.coach_assessment.advice.code == "advice.thresholds"


def test_generic_threshold_is_never_reported_as_personal():
    profile = WIV3PhysiologicalProfile(lt1=_lt(150, source="generic_formula"))
    result = _analyze(_w("cur", CURRENT_DAY, hr=140), [], profile=profile)
    assert result.intensity_assessment.rejected_thresholds["lt1"].startswith("source_not_personal")


def test_only_lt1_cannot_place_hr_above_it():
    profile = WIV3PhysiologicalProfile(lt1=_lt(150))
    result = _analyze(_w("cur", CURRENT_DAY, hr=165), [], profile=profile)
    assert result.intensity_assessment.position == "unknown"
    assert "missing_threshold_for_this_hr_range" in result.intensity_assessment.limitations


# 4 ─ Fast session without phases: never invent intervals
def test_fast_session_without_phases_never_becomes_intervals():
    current = _w("cur", CURRENT_DAY, hr=176, max_hr=185, pace=4.2, continuous=False)
    result = _analyze(current, _flat_history())
    assert result.session_classification.type != "intervals"
    assert result.session_classification.type == "tempo_probable"
    assert result.session_classification.confidence == "low"
    assert "intervals_not_identifiable_without_phases" in result.session_classification.limitations
    no_thresholds = _analyze(current, _flat_history(), profile=WIV3PhysiologicalProfile())
    assert no_thresholds.session_classification.type == "unknown"


# 5 ─ Intervals with reliable phases
def test_intervals_identified_from_reliable_garmin_phases():
    current = _w("cur", CURRENT_DAY, hr=160, pace=5.2, duration=45, continuous=False)
    result = _analyze(current, _flat_history(), phases=_interval_phases())
    cls = result.session_classification
    assert cls.type == "intervals"
    assert cls.confidence == "high"
    assert cls.evidence == {"effort_count": 5.0, "recovery_count": 5.0}
    assert result.historical_comparison.status == "not_applicable"
    assert result.performance_trend.status == "insufficient_data"
    assert result.coach_assessment.diagnosis.code == "diagnosis.intervals"


# 6 ─ Improved pace at comparable HR over several admissible sessions
def _improving_history():
    paces = [6.0, 5.95, 5.70, 5.65]
    days = ["2026-03-01", "2026-03-20", "2026-04-10", "2026-04-30"]
    return [_w(f"h{i}", day, hr=145, pace=pace) for i, (day, pace) in enumerate(zip(days, paces))]


def test_improved_pace_at_comparable_hr_is_probable_improvement():
    result = _analyze(_w("cur", CURRENT_DAY, hr=145, pace=5.6), _improving_history())
    trend = result.performance_trend
    assert trend.status == "probable_improvement"
    assert trend.variation_confirmed is True
    assert trend.observation_count == 5
    assert trend.confidence == "medium"
    assert trend.median_change_sec_per_km < -trend.criteria["pace_margin_sec_per_km"]
    assert {row.status for row in trend.sensitivity} == {"probable_improvement"}
    assert result.historical_comparison.pace_at_comparable_hr.pace_difference_sec_per_km < 0


# 7 ─ Isolated variation, no confirmed trend
def test_isolated_fast_session_is_not_a_trend():
    result = _analyze(_w("cur", CURRENT_DAY, hr=145, pace=5.5), _flat_history(hr=145))
    trend = result.performance_trend
    assert trend.status == "stable"
    assert trend.variation_confirmed is False
    assert trend.observed_variation_sec_per_km == pytest.approx(-30.0)
    assert "isolated_variation_not_confirmed" in trend.limitations
    assert any(item.code == "limit.isolated" for item in result.coach_assessment.limitations)


# 8 ─ Insufficient history
def test_insufficient_history():
    result = _analyze(_w("cur", CURRENT_DAY), _flat_history(n=2))
    assert result.performance_trend.status == "insufficient_data"
    assert result.performance_trend.confidence == "none"
    empty = _analyze(_w("cur", CURRENT_DAY), [])
    assert empty.historical_comparison.status == "insufficient"
    assert empty.historical_comparison.comparability == "insufficient"
    assert empty.performance_trend.status == "insufficient_data"


def test_trend_requires_spread_in_time():
    history = [_w(f"h{i}", f"2026-05-0{i + 2}", pace=6.0 - i * 0.1) for i in range(4)]
    result = _analyze(_w("cur", CURRENT_DAY, pace=5.5), history)
    assert result.performance_trend.status == "insufficient_data"
    assert "observations_not_spread_in_time" in result.performance_trend.limitations


# 9 ─ Treadmill vs outdoor exclusion
def test_treadmill_history_is_excluded_from_outdoor_session():
    history = _improving_history()
    types = {"cur": OUTDOOR, **{item["id"]: TREADMILL for item in history}}
    result = _analyze(_w("cur", CURRENT_DAY, hr=145, pace=5.6), history, types=types)
    assert result.historical_comparison.exclusion_reasons == {"different_environment": 4}
    assert result.historical_comparison.reference_count == 0
    assert result.performance_trend.status == "insufficient_data"


def test_unknown_environment_is_never_mixed():
    history = _improving_history()
    result = _analyze(_w("cur", CURRENT_DAY, hr=145, pace=5.6), history, types={})
    assert result.historical_comparison.exclusion_reasons == {"current_environment_unknown": 4}
    assert result.performance_trend.status == "insufficient_data"


def test_distance_proximity_alone_is_not_comparability():
    # Same distance, very different HR and pace: no physiological match.
    history = [_w(f"h{i}", day, hr=175, pace=4.5, duration=37, distance=8.2)
               for i, day in enumerate(["2026-03-01", "2026-03-20", "2026-04-10", "2026-04-30"])]
    result = _analyze(_w("cur", CURRENT_DAY, hr=140, pace=6.0, duration=49, distance=8.2), history)
    assert result.historical_comparison.pace_at_comparable_hr.reference_count == 0
    assert result.historical_comparison.hr_at_comparable_pace.reference_count == 0
    assert result.historical_comparison.comparability == "insufficient"


# 10 ─ History with unknown structure: no strong conclusion
def test_unknown_reference_structure_prevents_strong_conclusion():
    history = [dict(item) for item in _improving_history()]
    for item in history:
        item.pop("session_structure")
    result = _analyze(_w("cur", CURRENT_DAY, hr=145, pace=5.6), history)
    assert result.historical_comparison.comparability == "moderate"
    assert "reference_structure_unknown" in result.historical_comparison.limitations
    assert result.performance_trend.confidence == "low"
    assert not any(item.code == "evidence.trend" for item in result.coach_assessment.evidence)


def test_historical_interval_sessions_are_excluded():
    history = _improving_history()
    phases = {item["id"]: _interval_phases() for item in history}
    result = _analyze(_w("cur", CURRENT_DAY, hr=145, pace=5.6), history, historical_phases=phases)
    assert result.historical_comparison.exclusion_reasons.get("different_structure") == 4


# 11 ─ Historical prescription absent or non-authoritative
def _snapshot(planned, served=None, workout_type="easy", intensity="low"):
    return PrescriptionSnapshot(
        user_id="user-a", prescription_id=f"user-a:{planned}:sunday", planned_date=date.fromisoformat(planned),
        served_reference_date=date.fromisoformat(served) if served else None, day="sunday",
        workout_type=workout_type, intensity_class=intensity, distance_km=8.0, duration_minutes=48,
    )


def test_prescription_absent_or_not_authoritative():
    current = _w("cur", CURRENT_DAY, hr=140)
    absent = _analyze(current, [], prescription=WIV3PrescriptionContext(local_date=CURRENT_DAY))
    assert absent.prescription_assessment.status == "unavailable"
    stale = _snapshot(CURRENT_DAY, served="2026-05-08")
    assert is_snapshot_authoritative(snapshot=stale, reference_date=date(2026, 5, 10)) is False
    non_auth = _analyze(current, [], prescription=WIV3PrescriptionContext(local_date=CURRENT_DAY, snapshots=[stale]))
    assert non_auth.prescription_assessment.status == "unavailable"
    assert non_auth.prescription_assessment.reasons == ["snapshot_not_authoritative_for_date"]
    no_local_date = _analyze(current, [], prescription=WIV3PrescriptionContext(snapshots=[_snapshot(CURRENT_DAY)]))
    assert no_local_date.prescription_assessment.status == "indeterminate"


def test_prescription_consistent_deviation_and_ambiguous():
    easy = WIV3PrescriptionContext(local_date=CURRENT_DAY, snapshots=[_snapshot(CURRENT_DAY, served=CURRENT_DAY)])
    consistent = _analyze(_w("cur", CURRENT_DAY, hr=140), [], prescription=easy)
    assert consistent.prescription_assessment.status == "consistent"
    deviation = _analyze(_w("cur", CURRENT_DAY, hr=160, continuous=False), [], prescription=easy,
                         phases=_interval_phases())
    assert deviation.prescription_assessment.status == "deviation"
    assert deviation.coach_assessment.advice.code == "advice.deviation"
    ambiguous = _analyze(_w("cur", CURRENT_DAY, hr=140), [], prescription=easy.model_copy(
        update={"same_day_session_count": 2}))
    assert ambiguous.prescription_assessment.status == "indeterminate"
    low_conf = _analyze(_w("cur", CURRENT_DAY, hr=176, max_hr=185), [], prescription=easy)
    assert low_conf.prescription_assessment.status == "indeterminate"  # tempo_probable low confidence


# 12 ─ Session without splits
def test_session_without_splits_is_fully_analyzed():
    current = _w("cur", CURRENT_DAY, hr=140)
    assert current["km_splits"] == []
    result = _analyze(current, _flat_history(hr=141))
    assert "session.splits" not in result.data_used
    assert result.session_classification.type == "easy_run_probable"
    assert result.historical_comparison.status == "available"


# 13 ─ Missing or aberrant HR
@pytest.mark.parametrize("hr,max_hr,code", [
    (None, None, "hr_missing"),
    (180, 170, "hr_aberrant_average_above_max"),
    (260, None, "hr_aberrant_above_credible_ceiling"),
    (float("nan"), None, "hr_missing"),
])
def test_missing_or_aberrant_hr(hr, max_hr, code):
    result = _analyze(_w("cur", CURRENT_DAY, hr=hr, max_hr=max_hr), _flat_history())
    assert result.intensity_assessment.position == "unknown"
    assert result.intensity_assessment.hr_used_bpm is None
    assert code in result.intensity_assessment.limitations
    assert result.performance_trend.status == "insufficient_data"
    assert result.coach_assessment.limitations[0].code == "limit.hr_unusable"
    assert result.coach_assessment.advice is None


# 14 ─ Old session: no access to future data
def test_old_session_never_reads_future_data():
    old = _w("cur", "2026-03-15", hr=145, pace=5.6)
    future = [_w(f"f{i}", f"2026-04-{10 + i * 5:02d}", hr=145, pace=5.0, max_hr=205) for i in range(4)]
    future_threshold = WIV3PhysiologicalProfile(lt1=_lt(150, on="2026-04-01"), lt2=_lt(170))
    result = _analyze(old, _flat_history(n=2) + future, profile=future_threshold)
    data_ids = set(result.historical_comparison.pace_at_comparable_hr.workout_ids)
    assert not data_ids & {f"f{i}" for i in range(4)}
    assert result.intensity_assessment.lt1 is None
    assert result.intensity_assessment.rejected_thresholds["lt1"] == "estimate_after_session"
    assert result.intensity_assessment.fcmax_bpm == 170  # future 205 bpm max is ignored
    future_snapshot = WIV3PrescriptionContext(local_date="2026-03-15", snapshots=[_snapshot("2026-04-10")])
    assert _analyze(old, [], prescription=future_snapshot).prescription_assessment.status == "unavailable"


def test_engine_rejects_future_history_even_when_input_is_built_directly():
    current = _w("cur", CURRENT_DAY)
    v2 = build_workout_analysis_v2(current, [], "en")
    data = extract_workout_intelligence_input(current, [], v2_analysis=v2, activity_types={"cur": OUTDOOR})
    leaked = data.model_copy(update={"history": [
        wiv3.WIV3HistoricalSession(id="x", date="2026-06-01", sport="run", activity_type=OUTDOOR,
                                   duration_minutes=50, avg_pace_min_km=5.0, avg_hr=145,
                                   structure="continuous_recorded"),
    ]})
    result = build_workout_intelligence_v3(leaked)
    assert result.historical_comparison.exclusion_reasons == {"not_strictly_prior": 1}


# 15 ─ FR/EN/ES translations and provenance
@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_translations_and_provenance(language):
    result = _analyze(_w("cur", CURRENT_DAY, hr=145, pace=5.6), _improving_history(), language=language)
    coach = result.coach_assessment
    assert coach.language == language
    items = [coach.diagnosis, *coach.evidence, *coach.limitations] + ([coach.advice] if coach.advice else [])
    assert 1 <= len(coach.evidence) <= 3
    for item in items:
        assert item.text and "{" not in item.text
        assert item.source_paths
    assert set(wiv3._TEXT[language]) == set(wiv3._TEXT["en"])


def test_translation_texts_differ_between_languages():
    texts = {
        lang: _analyze(_w("cur", CURRENT_DAY, hr=140), _flat_history(hr=141), language=lang)
        .coach_assessment.diagnosis.text
        for lang in ("fr", "en", "es")
    }
    assert len(set(texts.values())) == 3


def test_coach_never_repeats_raw_totals_or_claims_fatigue():
    result = _analyze(_w("cur", CURRENT_DAY, hr=140), _flat_history(hr=141), language="fr")
    blob = json.dumps(result.coach_assessment.model_dump(), ensure_ascii=False).lower()
    for forbidden in ("fatigue", "surentra", "récupération incomplète", "overtrain", " km ", "6:00"):
        assert forbidden not in blob


def test_long_run_is_relative_to_habitual_duration():
    history = [_w(f"h{i}", f"2026-04-{1 + i * 4:02d}", duration=45) for i in range(6)]
    result = _analyze(_w("cur", CURRENT_DAY, hr=140, duration=100), history)
    assert result.session_classification.type == "long_run_probable"
    assert result.session_classification.evidence["duration_ratio"] == pytest.approx(2.22)
    unknown_intensity = _analyze(_w("cur", CURRENT_DAY, hr=140, duration=100), history,
                                 profile=WIV3PhysiologicalProfile())
    assert unknown_intensity.session_classification.confidence == "low"


# ── Loader: read-only, additive API, no Garmin call ─────────────────────────


class _Cursor:
    def __init__(self, docs):
        self.docs = docs

    def sort(self, *_args):
        return self

    async def to_list(self, length=None):
        return list(self.docs if length is None else self.docs[:length])


class _ReadOnlyCollection:
    """Exposes only read methods: any write attempt raises AttributeError."""

    def __init__(self, docs):
        self.docs = docs
        self.queries = []

    @staticmethod
    def _match(doc, query):
        for key, expected in query.items():
            actual = doc.get(key)
            if isinstance(expected, dict):
                if "$in" in expected and actual not in expected["$in"]:
                    return False
                if "$gte" in expected and (actual is None or actual < expected["$gte"]):
                    return False
                if "$lt" in expected and (actual is None or actual >= expected["$lt"]):
                    return False
            elif actual != expected:
                return False
        return True

    def find(self, query, *_args, **_kwargs):
        self.queries.append(query)
        return _Cursor([dict(doc) for doc in self.docs if self._match(doc, query)])

    async def find_one(self, query, *_args, **_kwargs):
        self.queries.append(query)
        return next((dict(doc) for doc in self.docs if self._match(doc, query)), None)


def _garmin(wid, day, **kwargs):
    doc = _w(wid, day, **kwargs)
    doc.update({"data_source": "garmin", "external_id": wid})
    return doc


def _activity(wid, local_start, activity_type=OUTDOOR):
    return {
        "user_id": "user-a", "external_id": wid, "activity_type": activity_type,
        "garmin_activity": {"activity_type": activity_type, "start_time_local": local_start},
    }


def _loader_db(snapshots=()):
    history = [_garmin(f"h{i}", day, hr=145, pace=pace)
               for i, (day, pace) in enumerate(zip(
                   ["2026-03-01", "2026-03-20", "2026-04-10", "2026-04-30"], [6.0, 5.95, 5.7, 5.65]))]
    current = _garmin("cur", CURRENT_DAY, hr=145, pace=5.6)
    future = _garmin("future", "2026-05-20", hr=145, pace=4.0)
    other_user = dict(_garmin("other", "2026-05-01", hr=145, pace=4.0), user_id="user-b")
    workouts = history + [current, future, other_user]
    activities = [_activity(item["id"], f"{item['date']}T07:00:00") for item in history + [current, future]]
    return SimpleNamespace(
        workouts=_ReadOnlyCollection(workouts),
        garmin_activities=_ReadOnlyCollection(activities),
        training_prescription_snapshots=_ReadOnlyCollection(
            [snap.model_dump(mode="json") for snap in snapshots]),
    )


def test_loader_is_read_only_scoped_and_strictly_prior():
    db = _loader_db([_snapshot(CURRENT_DAY, served=CURRENT_DAY)])
    workout, result = asyncio.run(wiv3_service.load_scoped_workout_intelligence_v3(
        db=db, user_id="user-a", workout_id="cur", language="fr"))
    assert workout["id"] == "cur" and result is not None
    assert all(q.get("user_id") == "user-a" for coll in vars(db).values() for q in coll.queries)
    used = set(result.historical_comparison.pace_at_comparable_hr.workout_ids)
    assert used == {"h0", "h1", "h2", "h3"}
    assert result.performance_trend.status == "probable_improvement"
    assert result.intensity_assessment.position == "unknown"
    assert "personal_thresholds_not_persisted" in result.intensity_assessment.limitations
    assert result.prescription_assessment.status == "indeterminate"  # unknown type → no forced match
    assert result.coach_assessment.language == "fr"


def test_loader_returns_none_for_other_user():
    db = _loader_db()
    assert asyncio.run(wiv3_service.load_scoped_workout_intelligence_v3(
        db=db, user_id="user-b", workout_id="cur", language="en")) is None


def test_v3_sources_have_no_writes_garmin_calls_or_rag():
    for module in (wiv3, wiv3_service):
        source = inspect.getsource(module)
        for forbidden in ("insert_one", "update_one", "update_many", "replace_one", "delete_",
                          "find_one_and_update", "bulk_write", "get_provider_for_user",
                          "fetch_activity_details", "request_activity_details", "gccli",
                          "rag_engine", "datetime.now", "date.today"):
            assert forbidden not in source, (module.__name__, forbidden)


# ── Non-regression: Workout Analysis V2 and Training V2 ─────────────────────


def test_v2_response_contract_is_unchanged():
    analysis = build_workout_analysis_v2(_w("cur", CURRENT_DAY), _flat_history(), "en")
    assert set(analysis.model_dump()) == {
        "version", "workout", "summary", "signals", "physiology", "pacing", "comparison",
        "meaning", "advice", "evidence", "limitations", "phase_analysis", "coach_language",
        "session_synthesis",
    }
    assert "workout_intelligence_v3" not in WorkoutAnalysisV2Response.model_fields


def test_v2_result_is_identical_with_superset_history_sources():
    current = _w("cur", CURRENT_DAY, hr=145, pace=5.6)
    history = _improving_history()
    subset = build_workout_analysis_v2(current, history, "en", activity_types={"cur": OUTDOOR, "h3": OUTDOOR})
    extra = {"cur": OUTDOOR, "h3": OUTDOOR, "unrelated": TREADMILL}
    superset = build_workout_analysis_v2(current, history, "en", activity_types=extra,
                                         historical_phases={"unrelated": _interval_phases()})
    assert subset.model_dump() == superset.model_dump()


def test_training_v2_snapshot_authority_rule_is_unchanged():
    assert is_snapshot_authoritative(snapshot=_snapshot(CURRENT_DAY), reference_date=date(2026, 5, 10))
    assert is_snapshot_authoritative(snapshot=_snapshot(CURRENT_DAY, served=CURRENT_DAY),
                                     reference_date=date(2026, 5, 10))
    assert not is_snapshot_authoritative(snapshot=_snapshot("2026-05-11"), reference_date=date(2026, 5, 10))


def _server():
    import os

    for key, value in {
        "JWT_SECRET_KEY": "workout-intelligence-v3-test-secret-32chars!", "JWT_ALGORITHM": "HS256",
        "JWT_ACCESS_TOKEN_EXPIRE_MINUTES": "60", "ENVIRONMENT": "test",
        "MONGO_URL": "mongodb://localhost:27017", "DB_NAME": "test_db",
    }.items():
        os.environ.setdefault(key, value)
    import server

    return server


def test_v3_api_endpoint_is_additive():
    from unittest.mock import AsyncMock, patch

    from fastapi import HTTPException

    from workout_intelligence_v3_models import WorkoutIntelligenceV3Response

    server = _server()
    paths = {route.path for route in server.app.routes}
    assert "/api/coach/workout-intelligence/{workout_id}" in paths
    assert "/api/coach/workout-analysis/{workout_id}" in paths
    db = _loader_db()
    intelligence = asyncio.run(wiv3_service.load_scoped_workout_intelligence_v3(
        db=db, user_id="user-a", workout_id="cur", language="en"))
    with patch.object(server, "_coach_access", AsyncMock(return_value=(None, True))), \
            patch.object(server, "load_scoped_workout_intelligence_v3", AsyncMock(return_value=intelligence)):
        payload = asyncio.run(server.get_workout_intelligence_v3("cur", "en", {"id": "user-a"}))
    assert isinstance(payload, WorkoutIntelligenceV3Response)
    assert set(payload.model_dump()) == {"workout_id", "workout_intelligence_v3"}
    assert set(payload.workout_intelligence_v3.model_dump()) >= {
        "intensity_assessment", "session_classification", "historical_comparison",
        "performance_trend", "prescription_assessment", "coach_assessment",
    }
    with patch.object(server, "_coach_access", AsyncMock(return_value=(None, False))):
        with pytest.raises(HTTPException) as denied:
            asyncio.run(server.get_workout_intelligence_v3("cur", "en", {"id": "user-a"}))
    assert denied.value.status_code == 403
    with patch.object(server, "_coach_access", AsyncMock(return_value=(None, True))), \
            patch.object(server, "load_scoped_workout_intelligence_v3", AsyncMock(return_value=None)):
        with pytest.raises(HTTPException) as missing:
            asyncio.run(server.get_workout_intelligence_v3("nope", "en", {"id": "user-a"}))
    assert missing.value.status_code == 404
