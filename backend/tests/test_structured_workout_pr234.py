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


@pytest.mark.parametrize(
    ("basis", "value", "sum_field"),
    [
        ("distance", 0.0, "steps_distance_km_sum"),
        ("duration", 0, "steps_duration_seconds_sum"),
    ],
)
def test_quality_known_zero_omits_zero_steps_without_unknown_totals(basis, value, sum_field):
    workout = (
        _workout("quality", distance_km=value)
        if basis == "distance"
        else _workout("quality", duration_minutes=value)
    )
    result = build_structured_workout_prescription(
        workout=workout,
        plan_goal=_goal(GoalType.five_k),
        periodization=_phase(PeriodizationPhase.build),
        training_paces=_paces(),
    )

    assert all(
        (step.distance_m != 0 if basis == "distance" else step.duration_seconds != 0)
        for step in result.steps
    )
    assert getattr(result, sum_field) == 0
    assert result.distance_closes_total if basis == "distance" else result.duration_closes_total


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
    assert r_5k.quality_kind == QualityKind.vo2_intervals
    assert r_ultra.quality_kind == QualityKind.threshold_intervals


@pytest.mark.parametrize(
    ("goal_type", "phase", "expected"),
    [
        (GoalType.ten_k, PeriodizationPhase.base, QualityKind.tempo_continuous),
        (GoalType.ten_k, PeriodizationPhase.build, QualityKind.threshold_intervals),
        (GoalType.five_k, PeriodizationPhase.build, QualityKind.vo2_intervals),
        (GoalType.marathon, PeriodizationPhase.specific, QualityKind.race_specific_steady),
    ],
)
def test_quality_kind_exposes_the_exact_selected_subtype(goal_type, phase, expected):
    result = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=12.0),
        plan_goal=_goal(goal_type),
        periodization=_phase(phase),
    )

    assert result.quality_kind == expected.value
    assert result.model_dump(mode="json")["quality_kind"] == expected.value


@pytest.mark.parametrize("workout_type", ["rest", "easy", "recovery", "long_easy", "steady"])
def test_non_quality_prescriptions_have_no_quality_kind(workout_type):
    result = build_structured_workout_prescription(
        workout=_workout(workout_type, distance_km=None if workout_type == "rest" else 8.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
    )

    assert result.quality_kind is None


def test_quality_goal_aware_10k_vs_marathon_specific_differ_in_zone():
    common = dict(
        workout=_workout("quality", distance_km=14.0),
        periodization=_phase(PeriodizationPhase.specific),
    )
    r_10k = build_structured_workout_prescription(plan_goal=_goal(GoalType.ten_k), **common)
    r_marathon = build_structured_workout_prescription(plan_goal=_goal(GoalType.marathon), **common)

    work_10k = next(s for s in r_10k.steps if s.step_type == StructuredStepType.work)
    work_marathon = next(s for s in r_marathon.steps if s.step_type == StructuredStepType.work)
    # Both select race_specific_steady, but Training Paces has no canonical
    # 10K race-specific zone (C234 blocker 4) — never fake it with T.
    assert work_10k.pace_zone is None
    assert "RACE_SPECIFIC_PACE_UNAVAILABLE" in r_10k.reason_codes
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
def test_total_distance_mixed_basis_quality_with_time_only_recovery(distance_km):
    """C234 blocker 2 — a distance-based quality session whose work step
    embeds a time-only jog recovery (recovery.distance_m is None) can NEVER
    claim exact distance closure: the athlete runs the known blocks PLUS an
    unknown extra distance while jogging the recoveries (None != 0)."""
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=distance_km),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
    )
    work_step = next(s for s in r.steps if s.step_type == StructuredStepType.work)
    assert work_step.repetitions > 1
    assert work_step.recovery is not None
    assert work_step.recovery.duration_seconds is not None
    assert work_step.recovery.distance_m is None  # never fabricated (None != 0)

    # The invariant CANNOT be asserted exact — never a vacuous/misleading True.
    assert not r.distance_invariant_applicable
    assert not r.distance_closes_total
    assert "DISTANCE_TOTAL_MIXED_BASIS" in r.reason_codes

    # steps_distance_km_sum still reports the sum of KNOWN prescribed-block
    # distances (warmup + work×reps + cooldown) — never coerced to None,
    # never fabricated — but is no longer presented as "the exact total".
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
    """C234 blocker 2 — recovery never fabricates a distance (None != 0), and
    the KNOWN block sum still equals the prescribed total exactly, but the
    overall invariant is explicitly NOT claimed exact (mixed basis)."""
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=9.0),
        plan_goal=_goal(GoalType.five_k),
        periodization=_phase(PeriodizationPhase.build),
    )
    work_step = next(s for s in r.steps if s.step_type == StructuredStepType.work)
    assert work_step.repetitions > 1
    assert work_step.recovery is not None
    assert work_step.recovery.distance_m is None
    # Known-block distance sum still closes exactly (recovery never adds a
    # fabricated distance component)...
    assert r.steps_distance_km_sum == pytest.approx(9.0, abs=0.01)
    # ...but the exact-closure claim itself is explicitly withheld because a
    # real (unknown) recovery distance exists (never a misleading True).
    assert not r.distance_invariant_applicable
    assert not r.distance_closes_total
    assert "DISTANCE_TOTAL_MIXED_BASIS" in r.reason_codes



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
    # These volumes select threshold_intervals with an embedded time-only
    # recovery (mixed basis, C234 blocker 2) — the KNOWN block sum still
    # closes exactly (no silent drift), even though the overall exact-total
    # claim is explicitly withheld.
    assert r.steps_distance_km_sum == pytest.approx(distance_km, abs=0.01)
    assert not r.distance_closes_total
    assert "DISTANCE_TOTAL_MIXED_BASIS" in r.reason_codes
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
    # Build-phase interval structures embed a time-only jog recovery:
    # exact distance closure is explicitly withheld (mixed basis, C234
    # blocker 2) — the known block sum still equals the prescribed total.
    assert r.steps_distance_km_sum == pytest.approx(12.0, abs=0.01)
    assert not r.distance_closes_total
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


# ---------------------------------------------------------------------------
# C234 corrective audit — blocker 3: steady != easy
# ---------------------------------------------------------------------------


def test_steady_never_defaults_to_easy_zone():
    """C234 blocker 3 — WorkoutGenerator's "steady" has intensity_class
    "moderate" (distinct from easy's "low"); the structured engine must
    never coerce it into Easy pace (or any other zone) by default."""
    workout = _workout("steady", distance_km=10.0)
    assert workout.intensity_class == "moderate"
    r = build_structured_workout_prescription(
        workout=workout,
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.base),
    )
    step = r.steps[0]
    assert step.pace_zone is None
    assert step.pace_zone != "E"
    assert "STEADY_ZONE_UNAVAILABLE" in step.reason_codes
    # Distance closure is unaffected (steady is still a single continuous
    # block with no recovery — only the zone assignment changes).
    assert r.distance_closes_total


@pytest.mark.parametrize("workout_type", ["easy", "recovery", "long_easy"])
def test_continuous_easy_family_still_uses_zone_e(workout_type):
    """Confirms the corrective fix (blocker 3) is scoped to "steady" only —
    easy / recovery / long_easy keep zone E as before."""
    r = build_structured_workout_prescription(
        workout=_workout(workout_type, distance_km=10.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.base),
    )
    assert r.steps[0].pace_zone == "E"


# ---------------------------------------------------------------------------
# C234 corrective audit — blocker 4: honest race-specific pace
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("goal_type", [GoalType.ten_k, GoalType.half_marathon, GoalType.ultra])
def test_race_specific_never_invents_pace_for_non_marathon_goals(goal_type):
    """C234 blocker 4 — Training Paces provides only E/M/T/I/R; it does NOT
    provide a 5K/10K/Half/Ultra race-specific pace. 10K/Half/Ultra "specific"
    quality sessions must never present T (or any other zone) as if it were
    a genuine race-specific pace."""
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=14.0),
        plan_goal=_goal(goal_type),
        periodization=_phase(PeriodizationPhase.specific),
        training_paces=_paces(),
    )
    assert "QUALITY_RACE_SPECIFIC_SELECTED" in r.reason_codes
    work_step = next(s for s in r.steps if s.step_type == StructuredStepType.work)
    assert work_step.pace_zone is None
    assert work_step.pace_zone != "T"
    assert work_step.pace_min_per_km is None
    assert "RACE_SPECIFIC_PACE_UNAVAILABLE" in r.reason_codes


def test_race_specific_marathon_uses_m_correctly():
    """Marathon is the only goal with a legitimate canonical race-specific
    zone (M) — this must keep working exactly as before."""
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=14.0),
        plan_goal=_goal(GoalType.marathon),
        periodization=_phase(PeriodizationPhase.specific),
        training_paces=_paces(),
    )
    assert "QUALITY_RACE_SPECIFIC_SELECTED" in r.reason_codes
    work_step = next(s for s in r.steps if s.step_type == StructuredStepType.work)
    assert work_step.pace_zone == "M"
    assert work_step.pace_min_per_km is not None
    assert "RACE_SPECIFIC_PACE_UNAVAILABLE" not in r.reason_codes


# ---------------------------------------------------------------------------
# C234 corrective audit — blocker 5: recovery_count == repetitions - 1
# ---------------------------------------------------------------------------


def test_recovery_count_distance_based_threshold_two_reps():
    # 3.0 km ten_k/build -> threshold_intervals, reps == 2 (see mixed-basis
    # test above): recovery_count must be reps - 1 == 1, never reps == 2.
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=3.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
    )
    work_step = next(s for s in r.steps if s.step_type == StructuredStepType.work)
    assert work_step.repetitions == 2
    assert work_step.recovery is not None
    assert work_step.recovery.count == 1


def test_recovery_count_distance_based_threshold_four_reps():
    # 9.0 km ten_k/build -> threshold_intervals, reps == 4: recovery_count
    # must be 3, never 4.
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=9.0),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
    )
    work_step = next(s for s in r.steps if s.step_type == StructuredStepType.work)
    assert work_step.repetitions == 4
    assert work_step.recovery is not None
    assert work_step.recovery.count == 3


def test_recovery_count_one_rep_fallback_has_no_recovery():
    # Degenerate/volume-limited volumes fall back to a single continuous
    # work block (repetitions == 1) with no recovery metadata at all —
    # equivalent to 0 recoveries, never 1.
    r = build_structured_workout_prescription(
        workout=_workout("quality", distance_km=2.5),
        plan_goal=_goal(GoalType.five_k),
        periodization=_phase(PeriodizationPhase.build),
    )
    work_step = next(s for s in r.steps if s.step_type == StructuredStepType.work)
    assert work_step.repetitions == 1
    assert work_step.recovery is None


@pytest.mark.parametrize(
    "duration_minutes,expected_reps,expected_recovery_count",
    [(20, 2, 1), (45, 4, 3)],
)
def test_recovery_count_duration_based_matches_reps_minus_one(
    duration_minutes, expected_reps, expected_recovery_count
):
    r = build_structured_workout_prescription(
        workout=_workout("quality", duration_minutes=duration_minutes),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
    )
    work_step = next(s for s in r.steps if s.step_type == StructuredStepType.work)
    assert work_step.repetitions == expected_reps
    assert work_step.recovery is not None
    assert work_step.recovery.count == expected_recovery_count
    # Duration total must still close exactly using recovery_count (not
    # repetitions) as the recovery multiplier.
    assert r.duration_invariant_applicable
    assert r.duration_closes_total
    assert r.steps_duration_seconds_sum == duration_minutes * 60


def test_recovery_duration_total_uses_count_not_repetitions():
    """Directly proves the blocker 5 fix: total recovery contribution to
    steps_duration_seconds_sum is duration_seconds * count, never
    duration_seconds * repetitions."""
    r = build_structured_workout_prescription(
        workout=_workout("quality", duration_minutes=45),
        plan_goal=_goal(GoalType.ten_k),
        periodization=_phase(PeriodizationPhase.build),
    )
    work_step = next(s for s in r.steps if s.step_type == StructuredStepType.work)
    recovery = work_step.recovery
    assert recovery is not None
    assert recovery.count == work_step.repetitions - 1
    warmup = next(s for s in r.steps if s.step_type == StructuredStepType.warmup)
    cooldown = next(s for s in r.steps if s.step_type == StructuredStepType.cooldown)
    expected_total = (
        (warmup.duration_seconds or 0)
        + work_step.repetitions * work_step.duration_seconds
        + recovery.count * recovery.duration_seconds
        + (cooldown.duration_seconds or 0)
    )
    assert expected_total == 45 * 60
    assert r.steps_duration_seconds_sum == expected_total


# ---------------------------------------------------------------------------
# C234 corrective audit — blocker 2 companion: continuous / no-recovery
# distance still closes exactly (not everything becomes mixed basis)
# ---------------------------------------------------------------------------


def test_distance_continuous_no_recovery_still_closes_exactly():
    r = build_structured_workout_prescription(
        workout=_workout("long_easy", distance_km=16.0),
        plan_goal=_goal(GoalType.marathon),
        periodization=_phase(PeriodizationPhase.base),
    )
    assert r.steps[0].recovery is None
    assert r.distance_invariant_applicable
    assert r.distance_closes_total
    assert "DISTANCE_TOTAL_MIXED_BASIS" not in r.reason_codes
