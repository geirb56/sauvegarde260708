"""C349-B — metric-specific historical comparability.

Synthetic fixtures only: no Mongo data, no real athlete values, no physiology thresholds.
"""

import json
import math

import pytest

from activity_phases import ActivityPhase
from workout_analysis_v2 import (
    SIMILAR_MIN_COMPARABLE_SAMPLE,
    WorkoutAnalysisSimilarReference,
    WorkoutAnalysisV2Response,
    _build_similar_reference,
    build_workout_analysis_v2,
)

LANGUAGES = ("fr", "en", "es")
LEGACY_SIMILAR_KEYS = {
    "available", "comparable", "sample_count", "period_days", "distance_tolerance_pct",
    "min_comparable_sample", "workout_ids", "avg_distance_km", "avg_pace_min_km",
    "avg_heart_rate", "distance_sample_count", "pace_sample_count", "pace_avg_distance_km",
    "hr_sample_count", "pace_difference_min_km", "heart_rate_difference_bpm",
    "limitations", "reason_unavailable",
}
NEW_SIMILAR_KEYS = {
    "pace_comparability", "hr_comparability", "pace_nature_status", "hr_nature_status",
    "pace_limitations", "hr_limitations",
}


def current(**changes):
    base = dict(id="current", name="Run", date="2026-10-12", type="run", distance_km=9.33,
                duration_minutes=68.6, avg_pace_min_km=7.35, avg_heart_rate=127)
    base.update(changes)
    return base


def reference(index, **changes):
    base = dict(id=f"ref-{index}", name="Run", date=f"2026-10-0{index}", type="run",
                distance_km=9.0, duration_minutes=63.0, avg_pace_min_km=7.0, avg_heart_rate=130)
    base.update(changes)
    return base


def refs(count=3, **changes):
    return [reference(index, **changes) for index in range(1, count + 1)]


def similar(workout, history):
    return _build_similar_reference(workout, history, "en")


def history_items(workout, history, language="en", phases=None):
    analysis = build_workout_analysis_v2(workout, history, language, phases)
    return [item for item in analysis.coach_language.conclusions if item.category == "history"]


def intervals():
    phases = [ActivityPhase(order=0, phase_type="warmup", duration_s=600, distance_m=1500,
                            average_hr=110, source="synthetic")]
    for index in range(1, 4):
        phases += [
            ActivityPhase(order=index * 2 - 1, phase_type="effort", duration_s=300,
                          distance_m=1000, average_hr=150, source="synthetic"),
            ActivityPhase(order=index * 2, phase_type="recovery", duration_s=120,
                          distance_m=300, average_hr=120, source="synthetic"),
        ]
    return phases


# 1. Three references with reliable pace but no HR.
def test_pace_references_without_hr_still_admit_pace():
    workout = current(is_race=False)
    ref = similar(workout, refs(avg_heart_rate=None, is_race=False))
    assert ref.pace_sample_count == 3 and ref.hr_sample_count == 0
    assert ref.pace_comparability == "strong"
    assert ref.hr_comparability == "insufficient"
    assert "hr_sample_too_small" in ref.hr_limitations
    assert ref.pace_limitations == []
    # Legacy meaning preserved: any limitation keeps the aggregate flag False.
    assert ref.comparable is False and "hr_sample_too_small" in ref.limitations
    items = history_items(workout, refs(avg_heart_rate=None, is_race=False))
    assert [item.code for item in items] == ["coach.history.pace"]
    assert items[0].kind == "conclusion"
    assert items[0].evidence["pace_sample_count"] == 3
    assert not any("heart" in key for key in items[0].evidence)


# 2. Three references with reliable HR but no pace.
def test_hr_references_without_pace_still_admit_hr():
    workout = current(is_race=False)
    history = refs(avg_pace_min_km=None, is_race=False)
    ref = similar(workout, history)
    assert ref.hr_comparability == "strong"
    assert ref.pace_comparability == "insufficient"
    items = history_items(workout, history)
    assert [item.code for item in items] == ["coach.history.hr"]
    assert items[0].evidence["hr_sample_count"] == 3
    assert items[0].evidence["heart_rate_difference_bpm"] == -3
    assert items[0].metadata["population"] == "hr_only"


# 3. Insufficient pace sample.
def test_insufficient_pace_sample_never_backs_pace():
    workout = current(is_race=False)
    history = refs(is_race=False)
    history[0]["avg_pace_min_km"] = None
    history[1]["avg_pace_min_km"] = 0
    ref = similar(workout, history)
    assert ref.pace_sample_count == 1 < SIMILAR_MIN_COMPARABLE_SAMPLE
    assert ref.pace_comparability == "insufficient"
    assert "pace_sample_too_small" in ref.pace_limitations
    items = history_items(workout, history)
    assert [item.code for item in items] == ["coach.history.hr"]


# 4. Insufficient HR sample.
def test_insufficient_hr_sample_never_backs_hr():
    workout = current(is_race=False, avg_pace_min_km=None)
    history = refs(is_race=False)
    history[0]["avg_heart_rate"] = None
    history[1]["avg_heart_rate"] = None
    ref = similar(workout, history)
    assert ref.hr_sample_count == 1
    assert ref.hr_comparability == "insufficient"
    assert history_items(workout, history) == []


# 5. Distinct pace and HR populations.
def test_pace_and_hr_populations_stay_distinct():
    workout = current(is_race=False)
    history = [reference(1, avg_heart_rate=None, avg_pace_min_km=7.0, is_race=False),
               reference(2, avg_heart_rate=None, avg_pace_min_km=7.2, is_race=False),
               reference(3, avg_pace_min_km=None, avg_heart_rate=120, is_race=None),
               reference(4, avg_pace_min_km=None, avg_heart_rate=124, is_race=None)]
    ref = similar(workout, history)
    assert (ref.pace_sample_count, ref.hr_sample_count, ref.sample_count) == (2, 2, 4)
    assert ref.avg_pace_min_km == pytest.approx(7.1)
    assert ref.avg_heart_rate == pytest.approx(122)
    # Unknown nature on HR-only references does not degrade the pace population.
    assert (ref.pace_nature_status, ref.hr_nature_status) == ("same_known", "unknown")
    assert (ref.pace_comparability, ref.hr_comparability) == ("strong", "distance_only")
    items = history_items(workout, history)
    assert [item.code for item in items] == ["coach.history.pace"]
    assert items[0].evidence["pace_sample_count"] == 2


# 6. Known and identical training nature.
@pytest.mark.parametrize("flag", [False, True])
def test_known_identical_nature_is_strong(flag):
    workout = current(is_race=flag)
    ref = similar(workout, refs(is_race=flag))
    assert ref.comparable is True and ref.limitations == []
    assert (ref.pace_comparability, ref.hr_comparability) == ("strong", "strong")
    assert ref.pace_nature_status == "same_known"


# 7. Explicitly different nature is excluded, never compared.
def test_explicitly_different_nature_is_excluded():
    workout = current(is_race=False)
    ref = similar(workout, refs(is_race=True))
    assert ref.available is False and ref.sample_count == 0
    assert ref.pace_comparability == ref.hr_comparability == "insufficient"
    assert history_items(workout, refs(is_race=True)) == []


# 8. Unknown nature: explicit limitation, at most a limited descriptive scope.
@pytest.mark.parametrize("language,scope_words", [
    ("fr", "sans garantie de même nature"),
    ("en", "without any guarantee of the same nature"),
    ("es", "sin garantía de que sean de la misma naturaleza"),
])
def test_unknown_nature_is_limited_and_announced(language, scope_words):
    workout = current()
    history = refs()
    ref = similar(workout, history)
    assert ref.comparable is False
    assert "session_nature_unknown" in ref.limitations
    assert ref.pace_comparability == "distance_only"
    assert "session_nature_unknown" in ref.pace_limitations
    analysis = build_workout_analysis_v2(workout, history, language)
    assert "limitations.session_nature_unknown" in {item.code for item in analysis.limitations}
    items = [item for item in analysis.coach_language.conclusions if item.category == "history"]
    assert [item.code for item in items] == ["coach.history.pace"]
    item = items[0]
    assert item.kind == "descriptive"
    assert item.metadata["comparability"] == "distance_only"
    assert scope_words in item.text
    assert "3" in item.text
    assert item.evidence["pace_difference_sec_per_km"] == pytest.approx(21)
    # Strong-only factual history stays gated on the legacy aggregate contract.
    assert not any(fact.code.startswith("fact.similar") for fact in analysis.meaning.factual_observations)


def test_unknown_nature_never_supports_a_race():
    workout = current(is_race=True)
    ref = similar(workout, refs())
    assert ref.pace_comparability == ref.hr_comparability == "insufficient"
    assert history_items(workout, refs()) == []


def test_unknown_nature_on_one_reference_degrades_only_its_population():
    workout = current(is_race=False)
    history = refs(is_race=False)
    history[2]["is_race"] = None
    ref = similar(workout, history)
    assert ref.pace_nature_status == ref.hr_nature_status == "unknown"
    assert ref.pace_comparability == "distance_only"


# 9. Interval session against continuous history.
def test_intervals_never_use_limited_distance_scope():
    workout = current(duration_minutes=40.0, distance_km=6.0)
    history = refs(distance_km=6.0)
    analysis = build_workout_analysis_v2(workout, history, "en", intervals())
    assert analysis.signals.session_structure.code == "intervals"
    assert analysis.comparison.similar.pace_comparability == "distance_only"
    assert [item for item in analysis.coach_language.conclusions if item.category == "history"] == []


# 10. Distance out of tolerance.
def test_distance_out_of_tolerance_is_excluded():
    workout = current(is_race=False)
    history = refs(distance_km=20.0, is_race=False)
    assert similar(workout, history).available is False
    assert history_items(workout, history) == []


# 11. Later sessions are never used.
def test_future_sessions_are_never_used():
    workout = current(is_race=False)
    history = [reference(i, date=f"2026-10-{12 + i}", is_race=False) for i in range(1, 4)]
    history.append(reference(9, date="2026-10-12", is_race=False))
    assert similar(workout, history).available is False
    assert history_items(workout, history) == []


# 12. No reference at all.
def test_no_reference_at_all():
    ref = similar(current(), [])
    assert ref.available is False
    assert ref.limitations == ["no_comparable_reference"]
    assert ref.pace_comparability == ref.hr_comparability == "insufficient"
    assert ref.pace_nature_status is None
    assert history_items(current(), []) == []


# 13. Null, non-finite or incoherent values.
@pytest.mark.parametrize("bad", [None, True, "7", float("nan"), float("inf"), -7.0, 0])
def test_invalid_reference_values_are_not_counted(bad):
    workout = current(is_race=False)
    history = refs(is_race=False, avg_pace_min_km=bad, avg_heart_rate=bad)
    ref = similar(workout, history)
    assert ref.pace_sample_count == ref.hr_sample_count == 0
    assert ref.pace_comparability == ref.hr_comparability == "insufficient"
    assert history_items(workout, history) == []


@pytest.mark.parametrize("bad", [None, float("nan"), float("-inf"), 0, False])
def test_invalid_current_metric_does_not_block_the_other(bad):
    workout = current(is_race=False, avg_heart_rate=bad)
    ref = similar(workout, refs(is_race=False))
    assert ref.hr_comparability == "insufficient"
    assert "current_hr_missing" in ref.hr_limitations
    assert ref.pace_comparability == "strong"
    items = history_items(workout, refs(is_race=False))
    assert [item.code for item in items] == ["coach.history.pace"]


# 14. Deterministic selection: strong before distance-only, pace before HR.
def test_selection_is_deterministic_and_single():
    workout = current(is_race=False)
    history = [reference(1, avg_heart_rate=None, is_race=None),
               reference(2, avg_heart_rate=None, is_race=None),
               reference(3, avg_pace_min_km=None, is_race=False),
               reference(4, avg_pace_min_km=None, is_race=False)]
    ref = similar(workout, history)
    assert (ref.pace_comparability, ref.hr_comparability) == ("distance_only", "strong")
    runs = [[(item.code, item.text, item.priority) for item in history_items(workout, list(order))]
            for order in (history, history[::-1], history[1:] + history[:1])]
    assert runs[0] == runs[1] == runs[2]
    assert [code for code, _, _ in runs[0]] == ["coach.history.hr"]


def test_limited_scope_ranks_after_strong_scope_priorities():
    strong = history_items(current(is_race=False), refs(is_race=False))[0]
    limited = history_items(current(), refs())[0]
    assert strong.priority == 40 and limited.priority == 50


# 15. FR / EN / ES, numbers coherent with sources.
@pytest.mark.parametrize("language", LANGUAGES)
def test_localized_hr_limited_numbers_match_sources(language):
    workout = current(avg_pace_min_km=None)
    items = history_items(workout, refs(), language)
    assert [item.code for item in items] == ["coach.history.hr"]
    item = items[0]
    assert item.kind == "descriptive"
    assert "127" in item.text and "130" in item.text and "3" in item.text
    assert item.evidence["current_heart_rate_bpm"] == 127
    assert item.evidence["baseline_heart_rate_bpm"] == 130
    lowered = item.text.lower()
    for forbidden in ("drift", "dérive", "deriva", "fatigue", "fatiga", "vo2", "lt1", "lt2",
                      "progress", "progrès", "progreso", "efficac", "eficien"):
        assert forbidden not in lowered


# 16. Repetitions are not changed.
def test_repetition_analysis_unchanged_by_history():
    phases = intervals()
    without = build_workout_analysis_v2(current(), [], "en", phases).coach_language
    with_history = build_workout_analysis_v2(current(), refs(), "en", phases).coach_language
    assert [item for item in with_history.conclusions if item.category != "history"] == [
        item for item in without.conclusions if item.category != "history"
    ]
    assert with_history.limitations == without.limitations


# 17. Split observations are not changed.
def test_split_observations_unchanged_by_history():
    rows = [{"km": i, "pace_min_km": pace} for i, pace in enumerate((7.0, 7.1, 7.4, 7.6), 1)]
    workout = current(distance_km=4, duration_minutes=29.1, session_structure="continuous",
                      km_splits=rows)
    without = build_workout_analysis_v2(workout, [], "en").coach_language.conclusions
    with_history = build_workout_analysis_v2(
        workout, refs(distance_km=4.0), "en",
    ).coach_language.conclusions
    assert [item for item in with_history if item.category != "history"] == without
    assert len(with_history) <= 3
    assert len({item.category for item in with_history}) == len(with_history)


# 18. Existing limitations and diagnostics are preserved; API contract is additive.
def test_legacy_limitations_and_contract_are_preserved():
    analysis = build_workout_analysis_v2(current(), refs(count=1), "en")
    ref = analysis.comparison.similar
    assert ref.limitations == ["sample_too_small", "pace_sample_too_small",
                               "hr_sample_too_small", "session_nature_unknown"]
    assert ref.comparable is False
    codes = {item.code for item in analysis.limitations}
    assert {"limitations.comparability", "limitations.sample_too_small",
            "limitations.session_nature_unknown"} <= codes
    payload = json.loads(analysis.model_dump_json())
    assert set(payload["comparison"]["similar"]) == LEGACY_SIMILAR_KEYS | NEW_SIMILAR_KEYS
    assert WorkoutAnalysisV2Response.model_validate(payload) == analysis


def test_new_fields_have_safe_defaults_for_legacy_payloads():
    legacy = WorkoutAnalysisSimilarReference(available=True, comparable=True, pace_sample_count=3)
    assert legacy.pace_comparability == legacy.hr_comparability == "insufficient"
    assert legacy.pace_limitations == [] and legacy.pace_nature_status is None


def test_runtime_like_footings_without_metadata_have_explicit_scope():
    """Representative fixture shaped like the 5/12 Oct footings — not Mongo data."""
    workout = current()
    history = [reference(5, date="2026-10-05", distance_km=8.44, avg_pace_min_km=7 + 11 / 60,
                         avg_heart_rate=129)]
    ref = similar(workout, history)
    # A single earlier footing never supports a conclusion: abstention is kept.
    assert ref.pace_comparability == ref.hr_comparability == "insufficient"
    assert history_items(workout, history) == []
    assert math.isfinite(ref.pace_difference_min_km)
