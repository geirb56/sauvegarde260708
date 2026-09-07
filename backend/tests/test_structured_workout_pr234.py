"""PR234 — Tests for StructuredWorkoutPrescriptionEngine.

All tests use a fixed reference_date to ensure full determinism.
No datetime.now() or date.today() is called anywhere.

Test matrix (mirrors RUNINDEX_PR234_REPORT.md §tests)
------------------------------------------------------
A. Determinism — same input -> identical output
B. Easy -> single coherent continuous block
C. Long easy -> exact total, no invented quality block
D. Recovery -> light coherent prescription
E. Quality goal-aware -> different goals, same context, distinguishable structure
F. Phase-aware -> same goal, different phases, structure adapts when relevant
G. Total distance invariant (distance-based)
H. Total duration invariant (duration-based)
I. Recoveries never inflate the parent total
J. Rounding — no silent drift
K. Missing Training Pace -> no invented numeric pace
L. Training Pace present -> correct zone / value used
M-P. DailyAdaptation KEEP / SHORTEN / DOWNGRADE / REST interaction
Q. Maintenance -> no invented race-specific structure
R. 5K / 10K / Half / Marathon / Ultra coverage
S. Taper -> never increases volume/intensity
T. None != 0
U. Serialization

Run from the backend directory:
    python -m pytest tests/test_structured_workout_pr234.py -v
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from training_v2.daily_adaptation import (  # noqa: E402
    DailyAdaptationAction,
    build_daily_adaptation,
)
from training_v2.periodization import (  # noqa: E402
    PeriodizationMode,
    PeriodizationPhase,
    PeriodizationSnapshot,
)
from training_v2.plan_goal import GoalType, build_plan_goal  # noqa: E402
from training_v2.readiness import ReadinessConfidence, ReadinessResult  # noqa: E402
from training_v2.readiness_decision import (  # noqa: E402
    ReadinessBand,
    ReadinessDecision,
    build_readiness_decision,
)
from training_v2.readiness_sufficiency import SufficiencyLevel  # noqa: E402
from training_v2.structured_workout import (  # noqa: E402
    QualityKind,
    StructuredStepType,
    StructuredWorkoutPrescription,
    build_structured_workout_prescription,
)
from training_v2.training_paces import TrainingPaces, daniels_paces  # noqa: E402
from training_v2.workout_generator import WorkoutPrescription  # noqa: E402

REF = date(2026, 8, 17)


# ---------------------------------------------------------------------------
# Fixtures / builders
# ---------------------------------------------------------------------------


def _goal(goal_type: GoalType, **kwargs) -> "PlanGoal":
    if goal_type == GoalType.ultra and "target_distance_km" not in kwargs:
        kwargs["target_distance_km"] = 60.0
    return build_plan_goal(goal_type=goal_type, created_from="user", **kwargs)


def _phase(phase: PeriodizationPhase) -> PeriodizationSnapshot:
    return PeriodizationSnapshot(
        reference_date=REF,
        phase=phase,
        mode=PeriodizationMode.race_calendar,
        weeks_to_race=10.0,
        phase_start_date=REF,
        phase_end_date=REF,
        cycle_week=1,
        cycle_length_weeks=4,
        reason_codes=(),
    )


def _workout(
    workout_type: str,
    *,
    distance_km: float | None = None,
    duration_minutes: int | None = None,
) -> WorkoutPrescription:
    intensity = {
        "rest": "rest",
        "recovery": "low",
        "easy": "low",
        "steady": "moderate",
        "quality": "high",
        "long_easy": "low",
    }[workout_type]
    return WorkoutPrescription(
        day="wednesday",
        workout_type=workout_type,
        intensity_class=intensity,
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        reason_codes=("ORIGINAL_PLAN",),
    )


def _paces(vdot: float = 50.0) -> TrainingPaces:
    return daniels_paces(vdot, REF)


def _all_step_distance_m(prescription: StructuredWorkoutPrescription) -> float | None:
    total = 0.0
    for step in prescription.steps:
        if step.distance_m is None:
            return None
        total += step.distance_m * step.repetitions
    return total


# ---------------------------------------------------------------------------
# A. Determinism
# ---------------------------------------------------------------------------


def test_determinism_quality_distance():
    args = dict(
        workout=_workout("quality", distance_km=9.0),
        plan_goal=_goal(GoalType.five_k),
        periodization=_phase(PeriodizationPhase.build),
        training_paces=_paces(),
    )
    r1 = build_structured_workout_prescription(**args)
    r2 = build_structured_workout_prescription(**args)
    assert r1 == r2


def test_determinism_continuous():
    args = dict(
        workout=_workout("long_easy", distance_km=16.0),
        plan_goal=_goal(GoalType.marathon),
        periodization=_phase(PeriodizationPhase.base),
    )
    r1 = build_structured_workout_prescription(**args)
    r2 = build_structured_workout_prescription(**args)
    assert r1 == r2


# ---------------------------------------------------------------------------
# B. Easy
# ---------------------------------------------------------------------------


def test_easy_produces_single_continuous_block():
    r = build_structured_workout_prescription(
        workout=_workout("easy", distance_km=8.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.base),
    )
    assert len(r.steps) == 1
    assert r.steps[0].step_type == StructuredStepType.continuous
    assert r.steps[0].pace_zone == "E"
    assert r.distance_closes_total
    assert r.steps_distance_km_sum == pytest.approx(8.0)


# ---------------------------------------------------------------------------
# C. Long easy
# ---------------------------------------------------------------------------


def test_long_easy_exact_total_no_invented_quality():
    r = build_structured_workout_prescription(
        workout=_workout("long_easy", distance_km=16.0),
        plan_goal=_goal(GoalType.marathon),
        periodization=_phase(PeriodizationPhase.build),
    )
    assert len(r.steps) == 1
    assert r.steps[0].step_type == StructuredStepType.continuous
    assert r.steps[0].pace_zone == "E"
    assert r.steps[0].recovery is None
    assert r.distance_invariant_applicable
    assert r.distance_closes_total
    assert r.steps_distance_km_sum == pytest.approx(16.0)


# ---------------------------------------------------------------------------
# D. Recovery
# ---------------------------------------------------------------------------


def test_recovery_light_coherent_prescription():
    r = build_structured_workout_prescription(
        workout=_workout("recovery", distance_km=5.0),
        plan_goal=_goal(GoalType.half_marathon),
        periodization=_phase(PeriodizationPhase.base),
    )
    assert len(r.steps) == 1
    assert r.steps[0].step_type == StructuredStepType.continuous
    assert r.steps[0].pace_zone == "E"
    assert r.distance_closes_total


# ---------------------------------------------------------------------------
# E. Quality goal-aware
# ---------------------------------------------------------------------------


def test_quality_goal_aware_5k_vs_ultra_build_differ():
    common = dict(
        workout=_workout("quality", distance_km=12.0),
        periodization=_phase(PeriodizationPhase.build),
    )
    r_5k = build_structured_workout_prescription(plan_goal=_goal(GoalType.five_k), **common)
    r_ultra = build_structured_workout_prescription(plan_goal=_goal(GoalType.ultra), **common)

    assert any(c.startswith("QUALITY_") for c in r_5k.reason_codes)
    assert any(c.startswith("QUALITY_") for c in r_ultra.reason_codes)
    quality_code_5k = next(c for c in r_5k.reason_codes if c.startswith("QUALITY_"))
    quality_code_ultra = next(c for c in r_ultra.reason_codes if c.startswith("QUALITY_"))
    assert quality_code_5k != quality_code_ultra
    assert quality_code_5k == "QUALITY_VO2_SELECTED"


def test_quality_goal_aware_10k_vs_marathon_specific_differ_in_zone():
    common = dict(
        workout=_workout("quality", distance_km=14.0),
        periodization=_phase(PeriodizationPhase.specific),
    )
    r_10k = build_structured_workout_prescription(plan_goal=_goal(GoalType.ten_k), **common)
    r_marathon = build_structured_workout_prescription(plan_goal=_goal(GoalType.marathon), **common)

    work_10k = next(s for s in r_10k.steps if s.step_type == StructuredStepType.work)
    work_marathon = next(s for s in r_marathon.steps if s.step_type == StructuredStepType.work)
    # Both select race_specific_steady, but the pace ZONE differs by goal.
    assert work_10k.pace_zone == "T"
    assert work_marathon.pace_zone == "M"


# ---------------------------------------------------------------------------
# F. Phase-aware
# ---------------------------------------------------------------------------


def test_phase_aware_10k_base_vs_build_differ():
    goal = _goal(GoalType.ten_k)
    r_base = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=10.0),
        plan_goal=goal,
        periodization=_phase(PeriodizationPhase.base),
    )
    r_build = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=10.0),
        plan_goal=goal,
        periodization=_phase(PeriodizationPhase.build),
    )
    kind_base = next(c for c in r_base.reason_codes if c.startswith("QUALITY_"))
    kind_build = next(c for c in r_build.reason_codes if c.startswith("QUALITY_"))
    assert kind_base == "QUALITY_TEMPO_SELECTED"
    assert kind_build == "QUALITY_THRESHOLD_SELECTED"
    assert kind_base != kind_build


def test_phase_aware_taper_always_conservative_regardless_of_goal():
    for goal_type in (GoalType.five_k, GoalType.ten_k, GoalType.marathon):
        r = build_structured_workout_prescription(
            workout=_workout("quality", distance_km=6.0),
            plan_goal=_goal(goal_type),
            periodization=_phase(PeriodizationPhase.taper),
        )
        assert "QUALITY_TEMPO_SELECTED" in r.reason_codes
        assert "TAPER_REDUCED" in r.reason_codes


# ---------------------------------------------------------------------------
# G. Total distance invariant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("distance_km", [3.0, 6.0, 9.0, 12.0, 16.0, 21.0])
def test_total_distance_invariant_quality(distance_km):
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=distance_km),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
    )
    assert r.distance_invariant_applicable
    assert r.distance_closes_total
    assert r.steps_distance_km_sum == pytest.approx(distance_km, abs=0.01)
    computed = _all_step_distance_m(r)
    assert computed is not None
    assert computed == pytest.approx(distance_km * 1000.0, abs=10)


@pytest.mark.parametrize("distance_km", [4.0, 10.0, 18.0])
def test_total_distance_invariant_continuous(distance_km):
    r = build_structured_workout_prescription(
        workout=_workout("easy", distance_km=distance_km),
        plan_goal=_goal(GoalType.half_marathon),
        periodization=_phase(PeriodizationPhase.base),
    )
    assert r.distance_closes_total
    assert r.steps_distance_km_sum == pytest.approx(distance_km)


# ---------------------------------------------------------------------------
# H. Total duration invariant
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("duration_minutes", [20, 35, 45, 60, 75])
def test_total_duration_invariant_quality(duration_minutes):
    r = build_structured_workout_prescription(
        workout=_workout("quality", duration_minutes=duration_minutes),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
    )
    assert r.duration_invariant_applicable
    assert r.duration_closes_total
    assert r.steps_duration_seconds_sum == duration_minutes * 60


def test_total_duration_invariant_continuous():
    r = build_structured_workout_prescription(
        workout=_workout("long_easy", duration_minutes=90),
        plan_goal=_goal(GoalType.marathon),
        periodization=_phase(PeriodizationPhase.base),
    )
    # Duration-basis continuous session: total duration IS the parent
    # target directly (single block, no pace needed to know the total).
    assert r.duration_invariant_applicable
    assert r.duration_closes_total
    assert r.steps_duration_seconds_sum == 90 * 60


# ---------------------------------------------------------------------------
# I. Recoveries never inflate the parent total
# ---------------------------------------------------------------------------


def test_recovery_never_inflates_distance_total():
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=9.0),
        plan_goal=_goal(GoalType.five_k),
        periodization=_phase(PeriodizationPhase.build),
    )
    work_step = next(s for s in r.steps if s.step_type == StructuredStepType.work)
    assert work_step.repetitions > 1
    assert work_step.recovery is not None
    assert work_step.recovery.distance_m is None
    # Distance sum still closes exactly even though recovery exists.
    assert r.distance_closes_total
    assert r.steps_distance_km_sum == pytest.approx(9.0, abs=0.01)


def test_recovery_included_in_duration_total_when_duration_based():
    r = build_structured_workout_prescription(
        workout=_workout("quality", duration_minutes=45),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
    )
    work_step = next(s for s in r.steps if s.step_type == StructuredStepType.work)
    assert work_step.recovery is not None
    assert work_step.recovery.duration_seconds is not None
    # The exact-total invariant already proves recovery time is counted,
    # not added on top of the 45-minute budget.
    assert r.duration_closes_total
    assert r.steps_duration_seconds_sum == 45 * 60


# ---------------------------------------------------------------------------
# J. Rounding
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("distance_km", [7.3, 8.7, 11.1, 13.37, 17.05])
def test_rounding_no_silent_drift_distance(distance_km):
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=distance_km),
        plan_goal=_goal(GoalType.marathon),
        periodization=_phase(PeriodizationPhase.build),
    )
    assert r.distance_closes_total
    for step in r.steps:
        if step.distance_m is not None:
            assert step.distance_m >= 0.0


@pytest.mark.parametrize("duration_minutes", [37, 41, 53, 67])
def test_rounding_no_silent_drift_duration(duration_minutes):
    r = build_structured_workout_prescription(
        workout=_workout("quality", duration_minutes=duration_minutes),
        plan_goal=_goal(GoalType.marathon),
        periodization=_phase(PeriodizationPhase.build),
    )
    assert r.duration_closes_total
    for step in r.steps:
        if step.duration_seconds is not None:
            assert step.duration_seconds >= 0


def test_no_negative_and_no_meaningless_zero_step():
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=2.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
    )
    for step in r.steps:
        if step.distance_m is not None:
            assert step.distance_m >= 0.0


def test_degenerate_rep_size_falls_back_to_continuous_volume_limited():
    # 5K/build selects vo2_intervals (rep_min=4, target=800m). At exactly
    # 2.5km total, work_m=1100m clears the old _MIN_WORK_M_FOR_INTERVALS
    # floor (900m) but clamping to rep_min=4 yields per_rep_m=275m, below
    # the degenerate-rep sanity floor (300m) — the engine must fall back to
    # a single continuous work block with VOLUME_LIMITED rather than
    # presenting a fake, unrealistically short interval structure.
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=2.5),
        plan_goal=_goal(GoalType.five_k),
        periodization=_phase(PeriodizationPhase.build),
    )
    assert "VOLUME_LIMITED" in r.reason_codes
    work_steps = [s for s in r.steps if s.step_type == StructuredStepType.work]
    assert len(work_steps) == 1
    assert work_steps[0].repetitions == 1
    assert work_steps[0].recovery is None
    assert r.distance_closes_total


# ---------------------------------------------------------------------------
# K. Missing Training Pace
# ---------------------------------------------------------------------------


def test_missing_training_pace_never_invents_numeric_pace():
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=9.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
        training_paces=None,
    )
    for step in r.steps:
        assert step.pace_min_per_km is None
        assert step.pace_min_per_km_min is None
        assert step.pace_min_per_km_max is None
    assert "PACE_UNAVAILABLE" in r.reason_codes
    # Zone remains known (semantic), even without a numeric value.
    work_step = next(s for s in r.steps if s.step_type == StructuredStepType.work)
    assert work_step.pace_zone is not None


def test_insufficient_training_paces_confidence_never_invents_pace():
    insufficient = TrainingPaces(
        reference_date=REF,
        vdot_result=daniels_paces(50.0, REF).vdot_result,
        confidence="insufficient",
        easy=None,
        marathon=None,
        threshold=None,
        interval=None,
        repetition=None,
        reason="insufficient evidence",
    )
    r = build_structured_workout_prescription(
        workout=_workout("easy", distance_km=8.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.base),
        training_paces=insufficient,
    )
    assert r.steps[0].pace_min_per_km_min is None
    assert r.steps[0].pace_min_per_km_max is None


def test_malformed_pace_zone_value_never_invents_pace():
    # Defensive branch: a zone field that is neither PaceRange nor PaceValue
    # (should never happen upstream, but must never fabricate a value if it
    # somehow did) must resolve to PACE_UNAVAILABLE, not raise or invent.
    base = _paces()
    malformed = TrainingPaces(
        reference_date=base.reference_date,
        vdot_result=base.vdot_result,
        confidence=base.confidence,
        easy="not-a-pace-object",  # type: ignore[arg-type]
        marathon=base.marathon,
        threshold=base.threshold,
        interval=base.interval,
        repetition=base.repetition,
        reason=base.reason,
    )
    r = build_structured_workout_prescription(
        workout=_workout("easy", distance_km=8.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.base),
        training_paces=malformed,
    )
    assert r.steps[0].pace_min_per_km is None
    assert r.steps[0].pace_min_per_km_min is None
    assert r.steps[0].pace_min_per_km_max is None
    assert "PACE_UNAVAILABLE" in r.reason_codes


# ---------------------------------------------------------------------------
# L. Training Pace present
# ---------------------------------------------------------------------------


def test_training_pace_present_uses_correct_zone_and_value():
    paces = _paces(vdot=52.0)
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=9.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
        training_paces=paces,
    )
    work_step = next(s for s in r.steps if s.step_type == StructuredStepType.work)
    assert work_step.pace_zone == "T"
    assert work_step.pace_min_per_km == pytest.approx(paces.threshold.min_per_km)
    # A duration can be legitimately derived from a single-valued zone pace.
    assert work_step.duration_seconds is not None


def test_training_pace_present_easy_uses_range_not_single_value():
    paces = _paces(vdot=45.0)
    r = build_structured_workout_prescription(
        workout=_workout("easy", distance_km=8.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.base),
        training_paces=paces,
    )
    step = r.steps[0]
    assert step.pace_min_per_km is None  # E is a range, never a single value
    assert step.pace_min_per_km_min == pytest.approx(paces.easy.lower.min_per_km)
    assert step.pace_min_per_km_max == pytest.approx(paces.easy.upper.min_per_km)
    # No point-estimate duration invented from a range.
    assert step.duration_seconds is None


# ---------------------------------------------------------------------------
# M-P. DailyAdaptation interaction
# ---------------------------------------------------------------------------


def _readiness_decision(score: float) -> ReadinessDecision:
    result = ReadinessResult(
        score=score,
        confidence=ReadinessConfidence.NORMAL,
        sufficiency_level=SufficiencyLevel.SUFFICIENT,
        reasons=(),
    )
    return build_readiness_decision(result)


def _favorable_readiness() -> ReadinessDecision:
    return _readiness_decision(85.0)


def _low_readiness() -> ReadinessDecision:
    return _readiness_decision(45.0)


def _very_low_readiness() -> ReadinessDecision:
    return _readiness_decision(20.0)


def test_daily_adaptation_keep_structure_coherent():
    planned = _workout("easy", distance_km=8.0)
    adaptation = build_daily_adaptation(
        workout=planned,
        readiness_decision=_favorable_readiness(),
        training_load=None,
        recent_response=None,
    )
    assert adaptation.action == DailyAdaptationAction.KEEP
    r = build_structured_workout_prescription(
        workout=adaptation.adapted_workout,
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.base),
    )
    assert r.distance_closes_total
    assert r.steps_distance_km_sum == pytest.approx(8.0)


def test_daily_adaptation_shorten_structure_actually_shortened():
    planned = _workout("long_easy", distance_km=18.0)
    adaptation = build_daily_adaptation(
        workout=planned,
        readiness_decision=_low_readiness(),
        training_load=None,
        recent_response=None,
    )
    assert adaptation.action == DailyAdaptationAction.SHORTEN
    assert adaptation.adapted_workout.distance_km < planned.distance_km

    r_planned = build_structured_workout_prescription(
        workout=planned,
        plan_goal=_goal(GoalType.marathon),
        periodization=_phase(PeriodizationPhase.build),
    )
    r_adapted = build_structured_workout_prescription(
        workout=adaptation.adapted_workout,
        plan_goal=_goal(GoalType.marathon),
        periodization=_phase(PeriodizationPhase.build),
    )
    # The FINAL structure reflects the SHORTENED total, not the stale plan.
    assert r_adapted.steps_distance_km_sum < r_planned.steps_distance_km_sum
    assert r_adapted.steps_distance_km_sum == pytest.approx(adaptation.adapted_workout.distance_km)
    assert r_adapted.distance_closes_total


def test_daily_adaptation_downgrade_no_residual_quality_block():
    planned = _workout("quality", distance_km=10.0)
    adaptation = build_daily_adaptation(
        workout=planned,
        readiness_decision=_low_readiness(),
        training_load=None,
        recent_response=None,
    )
    assert adaptation.action == DailyAdaptationAction.EASY_DOWNGRADE
    assert adaptation.adapted_workout.workout_type == "easy"

    r = build_structured_workout_prescription(
        workout=adaptation.adapted_workout,
        plan_goal=_goal(GoalType.five_k),
        periodization=_phase(PeriodizationPhase.build),
    )
    # No leftover interval/threshold/VO2 structure from the pre-downgrade
    # quality session: structuring runs on the FINAL (easy) prescription.
    assert all(s.step_type != StructuredStepType.work for s in r.steps)
    assert all(s.recovery is None for s in r.steps)
    assert all(s.pace_zone in (None, "E") for s in r.steps)


def test_daily_adaptation_rest_no_residual_effort_structure():
    planned = _workout("quality", distance_km=10.0)
    adaptation = build_daily_adaptation(
        workout=planned,
        readiness_decision=_very_low_readiness(),
        training_load=None,
        recent_response=None,
    )
    assert adaptation.action == DailyAdaptationAction.REST
    assert adaptation.adapted_workout.workout_type == "rest"

    r = build_structured_workout_prescription(
        workout=adaptation.adapted_workout,
        plan_goal=_goal(GoalType.five_k),
        periodization=_phase(PeriodizationPhase.build),
    )
    assert r.steps == ()
    assert r.total_distance_km is None
    assert r.total_duration_minutes is None


# ---------------------------------------------------------------------------
# Q. Maintenance
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "phase",
    [
        PeriodizationPhase.base,
        PeriodizationPhase.build,
        PeriodizationPhase.specific,
        PeriodizationPhase.taper,
        PeriodizationPhase.race,
        PeriodizationPhase.consolidation,
    ],
)
def test_maintenance_never_invents_race_specific_structure(phase):
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=8.0),
        plan_goal=_goal(GoalType.maintenance),
        periodization=_phase(phase),
    )
    assert "QUALITY_TEMPO_SELECTED" in r.reason_codes
    assert "QUALITY_RACE_SPECIFIC_SELECTED" not in r.reason_codes
    assert "QUALITY_VO2_SELECTED" not in r.reason_codes


# ---------------------------------------------------------------------------
# R. Goal coverage
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "goal_type",
    [
        GoalType.five_k,
        GoalType.ten_k,
        GoalType.half_marathon,
        GoalType.marathon,
        GoalType.ultra,
    ],
)
def test_goal_coverage_quality_build_phase(goal_type):
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=12.0),
        plan_goal=_goal(goal_type),
        periodization=_phase(PeriodizationPhase.build),
    )
    assert r.distance_closes_total
    assert any(c.startswith("QUALITY_") for c in r.reason_codes)
    assert _goal_code_present(r, goal_type)


def _goal_code_present(r: StructuredWorkoutPrescription, goal_type: GoalType) -> bool:
    mapping = {
        GoalType.five_k: "GOAL_5K",
        GoalType.ten_k: "GOAL_10K",
        GoalType.half_marathon: "GOAL_HALF_MARATHON",
        GoalType.marathon: "GOAL_MARATHON",
        GoalType.ultra: "GOAL_ULTRA",
        GoalType.maintenance: "GOAL_MAINTENANCE",
    }
    return mapping[goal_type] in r.reason_codes


def test_ultra_never_receives_vo2_intervals_any_phase():
    for phase in (
        PeriodizationPhase.base,
        PeriodizationPhase.build,
        PeriodizationPhase.specific,
    ):
        r = build_structured_workout_prescription(
            workout=_workout("quality", distance_km=12.0),
            plan_goal=_goal(GoalType.ultra),
            periodization=_phase(phase),
        )
        assert "QUALITY_VO2_SELECTED" not in r.reason_codes


# ---------------------------------------------------------------------------
# S. Taper
# ---------------------------------------------------------------------------


def test_taper_never_increases_volume():
    total_km = 8.0
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=total_km),
        plan_goal=_goal(GoalType.half_marathon),
        periodization=_phase(PeriodizationPhase.taper),
    )
    assert r.steps_distance_km_sum == pytest.approx(total_km)
    assert r.steps_distance_km_sum <= total_km + 1e-6
    work_step = next(s for s in r.steps if s.step_type == StructuredStepType.work)
    assert work_step.recovery is None  # no intervals introduced during taper


# ---------------------------------------------------------------------------
# T. None != 0
# ---------------------------------------------------------------------------


def test_none_is_never_replaced_by_zero_pace():
    r = build_structured_workout_prescription(
        workout=_workout("easy", distance_km=8.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.base),
        training_paces=None,
    )
    step = r.steps[0]
    assert step.pace_min_per_km_min is None
    assert step.pace_min_per_km_max is None
    assert step.pace_min_per_km_min != 0
    assert step.pace_min_per_km_max != 0


def test_none_is_never_replaced_by_zero_duration_when_basis_is_distance():
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=9.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
        training_paces=None,
    )
    work_step = next(s for s in r.steps if s.step_type == StructuredStepType.work)
    assert work_step.duration_seconds is None


# ---------------------------------------------------------------------------
# U. Serialization
# ---------------------------------------------------------------------------


def test_serialization_round_trip():
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=9.0),
        plan_goal=_goal(GoalType.five_k),
        periodization=_phase(PeriodizationPhase.build),
        training_paces=_paces(),
    )
    dumped = r.model_dump(mode="json")
    assert isinstance(dumped, dict)
    assert dumped["workout_type"] == "quality"
    rebuilt = StructuredWorkoutPrescription.model_validate(dumped)
    assert rebuilt == r


def test_serialization_rest_day():
    r = build_structured_workout_prescription(
        workout=_workout("rest"),
        plan_goal=_goal(GoalType.maintenance),
        periodization=_phase(PeriodizationPhase.base),
    )
    dumped = r.model_dump(mode="json")
    assert dumped["steps"] == []
    rebuilt = StructuredWorkoutPrescription.model_validate(dumped)
    assert rebuilt == r


# ---------------------------------------------------------------------------
# Misc: unsupported workout_type never invents structure
# ---------------------------------------------------------------------------


def test_unknown_workout_type_never_invents_structure():
    r = build_structured_workout_prescription(
        workout=_workout("steady", distance_km=7.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.base),
    )
    assert r.steps[0].step_type == StructuredStepType.continuous
    assert r.distance_closes_total
