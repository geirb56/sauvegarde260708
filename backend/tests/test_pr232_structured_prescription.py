"""C232 (correction, "Structured Workout Prescription V1") — tests for
training_v2.structured_prescription.

Mandatory scenarios (see problem statement section 8):
  - sum of steps' distance == parent distance_km (and duration, mutatis
    mutandis) — recovery is time-only and excluded from the distance sum.
  - quality produces a REAL warmup/work/recovery/cooldown structure.
  - easy / long_easy => one continuous Easy step, no invented progression.
  - steady => continuous, no fabricated pace zone.
  - rest => steps=().
  - INSUFFICIENT paces => structure is still an engine decision, but no
    numeric pace is ever fabricated (every pace_range stays None).
  - idempotent: calling twice with identical inputs is byte-identical.
  - imperial-safety: the module itself never renders a unit string (no
    "/km" anywhere) — it only produces numeric min_per_km values, agnostic
    of the caller's display unit system.
"""

from __future__ import annotations

from datetime import date

import pytest

from training_v2.structured_prescription import (
    build_structured_prescription,
    resolve_primary_step,
)
from training_v2.training_paces import PaceRange, PaceValue, TrainingPaces, VdotResult
from training_v2.workout_generator import WorkoutPrescription


def _prescription(
    *,
    workout_type: str,
    distance_km: float | None,
    duration_minutes: int | None = None,
    day: str = "tuesday",
) -> WorkoutPrescription:
    intensity = "rest" if workout_type == "rest" else (
        "high" if workout_type == "quality" else "low"
    )
    return WorkoutPrescription(
        day=day,
        workout_type=workout_type,
        intensity_class=intensity,
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        reason_codes=("TEST_FIXTURE",),
    )


def _paces(*, easy=True, threshold=True) -> TrainingPaces:
    easy_range = (
        PaceRange(
            lower=PaceValue(min_per_km=5.5, km_per_hour=10.9),
            upper=PaceValue(min_per_km=6.2, km_per_hour=9.7),
        )
        if easy
        else None
    )
    threshold_value = PaceValue(min_per_km=4.6, km_per_hour=13.0) if threshold else None
    return TrainingPaces(
        reference_date=date(2026, 8, 25),
        vdot_result=VdotResult(
            reference_vdot=50.0,
            paces_confidence="high",
            evidence_count=1,
            high_count=1,
            medium_count=0,
            concordant=True,
            reason="test fixture",
        ),
        confidence="HIGH",
        easy=easy_range,
        marathon=None,
        threshold=threshold_value,
        interval=None,
        repetition=None,
        reason="test fixture",
    )


def _insufficient_paces() -> TrainingPaces:
    return TrainingPaces(
        reference_date=date(2026, 8, 25),
        vdot_result=VdotResult(
            reference_vdot=None,
            paces_confidence="insufficient",
            evidence_count=0,
            high_count=0,
            medium_count=0,
            concordant=False,
            reason="test fixture",
        ),
        confidence="INSUFFICIENT",
        easy=None,
        marathon=None,
        threshold=None,
        interval=None,
        repetition=None,
        reason="test fixture",
    )


# ---------------------------------------------------------------------------
# REST
# ---------------------------------------------------------------------------


def test_rest_has_no_steps():
    prescription = _prescription(workout_type="rest", distance_km=None)
    result = build_structured_prescription(prescription=prescription, paces=_paces())
    assert result.steps == ()


# ---------------------------------------------------------------------------
# EASY / RECOVERY / LONG_EASY — continuous, no invented progression
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("workout_type", ["easy", "recovery", "long_easy"])
def test_easy_family_is_one_continuous_easy_step(workout_type):
    prescription = _prescription(workout_type=workout_type, distance_km=12.0)
    result = build_structured_prescription(prescription=prescription, paces=_paces())
    assert len(result.steps) == 1
    step = result.steps[0]
    assert step.kind == "continuous"
    assert step.pace_zone == "easy"
    assert step.distance_km == 12.0
    assert step.pace_range is not None
    assert step.pace_range.lower_min_per_km == 5.5
    assert step.pace_range.upper_min_per_km == 6.2


def test_long_easy_never_gets_a_fabricated_progression_or_marathon_segment():
    prescription = _prescription(workout_type="long_easy", distance_km=18.0)
    result = build_structured_prescription(prescription=prescription, paces=_paces())
    kinds = [s.kind for s in result.steps]
    assert kinds == ["continuous"], "no 65/20/15 progression, no marathon segment invented"
    assert result.steps[0].pace_zone == "easy"


# ---------------------------------------------------------------------------
# STEADY — continuous, but no canonical Daniels zone
# ---------------------------------------------------------------------------


def test_steady_is_continuous_with_no_fabricated_pace_zone():
    prescription = _prescription(workout_type="steady", distance_km=10.0)
    result = build_structured_prescription(prescription=prescription, paces=_paces())
    assert len(result.steps) == 1
    step = result.steps[0]
    assert step.kind == "continuous"
    assert step.pace_zone is None
    assert step.pace_range is None


# ---------------------------------------------------------------------------
# QUALITY — real warmup/work/recovery/cooldown structure, exact accounting
# ---------------------------------------------------------------------------


def test_quality_produces_real_warmup_work_recovery_cooldown_structure():
    prescription = _prescription(workout_type="quality", distance_km=9.0)
    result = build_structured_prescription(prescription=prescription, paces=_paces())
    kinds = [s.kind for s in result.steps]
    assert kinds == ["warmup", "work", "recovery", "cooldown"]

    warmup, work, recovery, cooldown = result.steps
    assert warmup.pace_zone == "easy"
    assert work.pace_zone == "threshold"
    assert work.repetitions == 3
    assert work.pace_range is not None
    assert work.pace_range.lower_min_per_km == 4.6
    assert work.pace_range.upper_min_per_km == 4.6
    assert recovery.pace_zone is None
    assert recovery.distance_km is None
    assert recovery.duration_minutes == pytest.approx(2.0)
    assert cooldown.pace_zone == "easy"

    # Every km is accounted for exactly (recovery is time-only, excluded).
    distance_sum = warmup.distance_km + work.repetitions * work.distance_km + cooldown.distance_km
    assert distance_sum == pytest.approx(9.0)


def test_quality_duration_basis_sums_exactly():
    prescription = _prescription(workout_type="quality", distance_km=None, duration_minutes=45)
    result = build_structured_prescription(prescription=prescription, paces=_paces())
    kinds = [s.kind for s in result.steps]
    assert kinds == ["warmup", "work", "recovery", "cooldown"]
    warmup, work, recovery, cooldown = result.steps
    duration_sum = warmup.duration_minutes + work.repetitions * work.duration_minutes + cooldown.duration_minutes
    assert duration_sum == pytest.approx(45.0)


def test_quality_too_short_falls_back_to_honest_continuous_no_pace_zone():
    prescription = _prescription(workout_type="quality", distance_km=2.0)
    result = build_structured_prescription(prescription=prescription, paces=_paces())
    assert len(result.steps) == 1
    step = result.steps[0]
    assert step.kind == "continuous"
    assert step.pace_zone is None
    assert step.pace_range is None


# ---------------------------------------------------------------------------
# INSUFFICIENT paces — structure yes, numeric pace NEVER fabricated
# ---------------------------------------------------------------------------


def test_insufficient_paces_still_structures_but_never_invents_a_numeric_pace():
    quality = _prescription(workout_type="quality", distance_km=9.0)
    result = build_structured_prescription(prescription=quality, paces=_insufficient_paces())
    kinds = [s.kind for s in result.steps]
    assert kinds == ["warmup", "work", "recovery", "cooldown"]
    for step in result.steps:
        assert step.pace_range is None

    easy_session = _prescription(workout_type="easy", distance_km=8.0)
    easy_result = build_structured_prescription(prescription=easy_session, paces=_insufficient_paces())
    assert easy_result.steps[0].pace_range is None

    none_paces_result = build_structured_prescription(prescription=easy_session, paces=None)
    assert none_paces_result.steps[0].pace_range is None


# ---------------------------------------------------------------------------
# Idempotency — required so the server can call this once, safely, without
# any special-casing around DailyAdaptation ordering.
# ---------------------------------------------------------------------------


def test_idempotent_on_already_structured_prescription():
    prescription = _prescription(workout_type="quality", distance_km=9.0)
    once = build_structured_prescription(prescription=prescription, paces=_paces())
    twice = build_structured_prescription(prescription=once, paces=_paces())
    assert twice.steps == once.steps


def test_idempotent_never_overwrites_an_already_decided_structure():
    # Simulates a hypothetical future engine that already decided a
    # DIFFERENT structure upstream — V1 must never clobber it.
    from training_v2.workout_generator import WorkoutStep

    injected = (WorkoutStep(kind="continuous", distance_km=9.0, pace_zone="marathon"),)
    prescription = _prescription(workout_type="quality", distance_km=9.0).model_copy(
        update={"steps": injected}
    )
    result = build_structured_prescription(prescription=prescription, paces=_paces())
    assert result.steps == injected


# ---------------------------------------------------------------------------
# resolve_primary_step — compact-card headline pace
# ---------------------------------------------------------------------------


def test_resolve_primary_step_prefers_work_over_continuous():
    prescription = _prescription(workout_type="quality", distance_km=9.0)
    result = build_structured_prescription(prescription=prescription, paces=_paces())
    primary = resolve_primary_step(result.steps)
    assert primary is not None
    assert primary.kind == "work"


def test_resolve_primary_step_falls_back_to_continuous():
    prescription = _prescription(workout_type="easy", distance_km=8.0)
    result = build_structured_prescription(prescription=prescription, paces=_paces())
    primary = resolve_primary_step(result.steps)
    assert primary is not None
    assert primary.kind == "continuous"


def test_resolve_primary_step_none_for_empty_steps():
    assert resolve_primary_step(()) is None


# ---------------------------------------------------------------------------
# Composition with DailyAdaptation — "structure once, AFTER adaptation"
# (see server.py: build_structured_prescription() is applied to the FINAL
# adapted_workout, never the broad pre-adaptation one). daily_adaptation.py
# itself is untouched by this round; these tests only verify the pure
# composition produces coherent results for every action.
# ---------------------------------------------------------------------------


def test_daily_adaptation_keep_preserves_structure_when_restructured_again():
    # KEEP => adapted_workout IS original_workout (same object/values) =>
    # re-running build_structured_prescription() on it must reproduce the
    # EXACT SAME structure (idempotency across the KEEP boundary).
    from tests.test_daily_adaptation_pr133 import (
        _decision,
        _load,
        _response,
        _workout,
    )
    from training_v2.daily_adaptation import DailyAdaptationAction, build_daily_adaptation

    workout = _workout("quality", distance_km=9.0)
    result = build_daily_adaptation(
        workout=workout,
        readiness_decision=_decision(85.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.KEEP

    before = build_structured_prescription(prescription=workout, paces=_paces())
    after = build_structured_prescription(prescription=result.adapted_workout, paces=_paces())
    assert after.steps == before.steps
    kinds = [s.kind for s in after.steps]
    assert kinds == ["warmup", "work", "recovery", "cooldown"]


def test_daily_adaptation_easy_downgrade_drops_quality_structure_for_easy():
    from tests.test_daily_adaptation_pr133 import (
        _decision,
        _load,
        _response,
        _workout,
    )
    from training_v2.daily_adaptation import DailyAdaptationAction, build_daily_adaptation

    workout = _workout("quality", distance_km=8.0)
    result = build_daily_adaptation(
        workout=workout,
        readiness_decision=_decision(50.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.EASY_DOWNGRADE
    assert result.adapted_workout.workout_type == "easy"

    structured = build_structured_prescription(prescription=result.adapted_workout, paces=_paces())
    kinds = [s.kind for s in structured.steps]
    # No warmup/work/recovery/cooldown (the old quality shape) — a single
    # coherent continuous Easy step instead.
    assert kinds == ["continuous"]
    assert structured.steps[0].pace_zone == "easy"


def test_daily_adaptation_shorten_keeps_steps_sum_coherent_with_new_total():
    from tests.test_daily_adaptation_pr133 import (
        _decision,
        _load,
        _response,
        _workout,
    )
    from training_v2.daily_adaptation import DailyAdaptationAction, build_daily_adaptation

    workout = _workout("easy", distance_km=10.0)
    result = build_daily_adaptation(
        workout=workout,
        readiness_decision=_decision(65.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.SHORTEN
    shortened_distance = result.adapted_workout.distance_km
    assert shortened_distance < 10.0

    structured = build_structured_prescription(prescription=result.adapted_workout, paces=_paces())
    assert len(structured.steps) == 1
    assert structured.steps[0].distance_km == pytest.approx(shortened_distance)


def test_daily_adaptation_rest_has_no_steps():
    from tests.test_daily_adaptation_pr133 import (
        _decision,
        _load,
        _response,
        _workout,
    )
    from training_v2.daily_adaptation import DailyAdaptationAction, build_daily_adaptation

    workout = _workout("easy", distance_km=8.0)
    result = build_daily_adaptation(
        workout=workout,
        readiness_decision=_decision(35.0),
        training_load=_load("balanced", acwr=1.0),
        recent_response=_response(),
    )
    assert result.action == DailyAdaptationAction.REST
    assert result.adapted_workout.workout_type == "rest"
    structured = build_structured_prescription(prescription=result.adapted_workout, paces=_paces())
    assert structured.steps == ()
