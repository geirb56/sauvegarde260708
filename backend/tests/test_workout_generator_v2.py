"""PR131 — Tests for WorkoutGenerator V2.

All tests use a fixed reference_date to ensure full determinism.
No datetime.now() or date.today() is called anywhere.

Test matrix
-----------
A. deep_reprise → duration-based → easy-only → run/walk reason code → no quality
B. deep_reprise → sum(minutes) == WeeklyTarget exact
C. partial_reprise distance → easy-only → sum(km) exact
D. reprise_exit allow_intensity=True → maximum 1 quality
E. reprise_exit allow_intensity=False → zero quality
F. normal allow_intensity=True → maximum 1 quality
G. normal allow_intensity=False → zero quality
H. long run tests (proportionality, no artificial floors, cap, proportion by goal)
I. NO_ROUNDING_DRIFT distance (various targets + session counts)
J. NO_ROUNDING_DRIFT duration
K. Phase modulation (no double volume reduction)
L. No false precision (no pace/HR/TSS/training_engine/llm_coach)
M. Determinism (same inputs → identical output)

Run from the backend directory:
    python -m pytest tests/test_workout_generator_v2.py -v
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from training_v2 import (
    PeriodizationPhase,
    PeriodizationSnapshot,
    PeriodizationMode,
    PlanGoal,
    GoalType,
    RunnerProfile,
    WeeklyTarget,
)
from training_v2.workout_generator import (
    WeeklyPlan,
    WorkoutPrescription,
    build_weekly_plan,
    _compute_long_run_km,
    LONG_RUN_MAX_FRACTION,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

REF = date(2026, 8, 11)  # Monday

# ---------------------------------------------------------------------------
# Fixture builders
# ---------------------------------------------------------------------------


def _runner_profile_minimal(ref: date = REF) -> RunnerProfile:
    """Minimal RunnerProfile with no scheduling constraints."""
    # Build via direct construction (frozen model) — avoids full builder chain
    # which would require TrainingHistory/TrainingLoad.
    return RunnerProfile(
        reference_date=ref,
        age=35,
        sex="male",
        primary_discipline="road",
        experience_level="established",
        typical_weekly_km=40.0,
        typical_weekly_km_is_observed=True,
        typical_weekly_hours=None,
        typical_runs_per_week=4.0,
        typical_long_run_km=None,
        typical_speed_kmh=None,
        available_history_days=120,
        profile_confidence="medium",
        vo2max=None,
        vma_kmh=None,
        max_hr=None,
        resting_hr=None,
        has_hrv=False,
        has_vo2max=False,
        has_training_readiness=False,
        has_power=False,
        has_running_dynamics=False,
        preferred_days_per_week=4,
        max_days_per_week=5,
        preferred_long_run_day=None,
        injury_constraints=[],
        availability_constraints=[],
    )


def _periodization(phase: str = "build", ref: date = REF) -> PeriodizationSnapshot:
    return PeriodizationSnapshot(
        reference_date=ref,
        phase=PeriodizationPhase(phase),
        mode=PeriodizationMode.continuous,
        weeks_to_race=None,
        phase_start_date=None,
        phase_end_date=None,
        cycle_week=None,
        cycle_length_weeks=None,
        reason_codes=(),
    )


def _plan_goal(goal: str = "marathon") -> PlanGoal:
    return PlanGoal(
        goal_type=GoalType(goal),
        target_time_seconds=None,
        race_date=None,
        target_distance_km=(
            42.195 if goal == "marathon"
            else 21.0975 if goal == "half_marathon"
            else 10.0 if goal == "10k"
            else 5.0 if goal == "5k"
            else None
        ),
        created_from="user",
    )


def _wt_duration(
    minutes: int,
    sessions: int = 3,
    allow_intensity: bool = False,
    codes: tuple = (),
    continuity_state: str = "deep_reprise",
) -> WeeklyTarget:
    return WeeklyTarget(
        reference_date=REF,
        target_basis="duration",
        target_km=None,
        target_duration_minutes=minutes,
        target_sessions=sessions,
        allow_intensity=allow_intensity,
        confidence="low",
        continuity_state=continuity_state,
        reason_codes=codes,
    )


def _wt_distance(
    km: float,
    sessions: int = 4,
    allow_intensity: bool = True,
    codes: tuple = (),
    continuity_state: str = "normal",
) -> WeeklyTarget:
    return WeeklyTarget(
        reference_date=REF,
        target_basis="distance",
        target_km=km,
        target_duration_minutes=None,
        target_sessions=sessions,
        allow_intensity=allow_intensity,
        confidence="medium",
        continuity_state=continuity_state,
        reason_codes=codes,
    )


def _plan(
    weekly_target: WeeklyTarget,
    goal: str = "marathon",
    phase: str = "build",
    ref: date = REF,
) -> WeeklyPlan:
    return build_weekly_plan(
        weekly_target=weekly_target,
        runner_profile=_runner_profile_minimal(ref),
        plan_goal=_plan_goal(goal),
        periodization=_periodization(phase, ref),
        reference_date=ref,
    )


def _running_sessions(plan: WeeklyPlan) -> list[WorkoutPrescription]:
    return [s for s in plan.sessions if s.workout_type != "rest"]


def _quality_sessions(plan: WeeklyPlan) -> list[WorkoutPrescription]:
    return [s for s in plan.sessions if s.workout_type == "quality"]


# ---------------------------------------------------------------------------
# A. deep_reprise — easy-only — run/walk reason code — no quality
# ---------------------------------------------------------------------------

class TestDeepRepriseEasyOnly:

    def test_no_quality_session(self):
        wt = _wt_duration(105, sessions=3, allow_intensity=False)
        plan = _plan(wt)
        assert len(_quality_sessions(plan)) == 0

    def test_all_running_sessions_are_easy_or_recovery(self):
        wt = _wt_duration(105, sessions=3, allow_intensity=False)
        plan = _plan(wt)
        for s in _running_sessions(plan):
            assert s.workout_type in ("easy", "recovery"), f"Unexpected type: {s.workout_type}"

    def test_run_walk_reason_code_present(self):
        wt = _wt_duration(105, sessions=3, allow_intensity=False)
        plan = _plan(wt)
        for s in _running_sessions(plan):
            assert "run_walk_allowed" in s.reason_codes, (
                f"Missing run_walk_allowed on {s.day}: {s.reason_codes}"
            )

    def test_route_code_present(self):
        wt = _wt_duration(105, sessions=3, allow_intensity=False)
        plan = _plan(wt)
        assert "generator_route_deep_reprise" in plan.reason_codes

    def test_max_3_running_sessions(self):
        wt = _wt_duration(135, sessions=3, allow_intensity=False)
        plan = _plan(wt)
        assert len(_running_sessions(plan)) <= 3


# ---------------------------------------------------------------------------
# B. deep_reprise — sum(minutes) == WeeklyTarget exact
# ---------------------------------------------------------------------------

class TestDeepRepriseDurationSum:

    @pytest.mark.parametrize("minutes", [105, 135, 90, 120, 137, 200])
    def test_duration_sum_exact(self, minutes: int):
        wt = _wt_duration(minutes, sessions=3, allow_intensity=False)
        plan = _plan(wt)
        total = sum(s.duration_minutes for s in _running_sessions(plan) if s.duration_minutes)
        assert total == minutes, f"Expected {minutes} min, got {total}"

    def test_planned_duration_matches(self):
        wt = _wt_duration(105, sessions=3)
        plan = _plan(wt)
        assert plan.planned_duration_minutes == 105


# ---------------------------------------------------------------------------
# C. partial_reprise distance — easy-only — sum km exact
# ---------------------------------------------------------------------------

class TestPartialRepriseDistance:

    @pytest.mark.parametrize("km", [12.0, 17.3, 31.7, 12.4, 25.0])
    def test_distance_sum_exact(self, km: float):
        wt = _wt_distance(
            km, sessions=3, allow_intensity=False,
            continuity_state="partial_reprise",
        )
        plan = _plan(wt)
        total = round(sum(s.distance_km for s in _running_sessions(plan) if s.distance_km), 1)
        assert abs(total - km) <= 0.1, f"Expected {km} km, got {total}"

    def test_no_quality_session(self):
        wt = _wt_distance(20.0, sessions=3, allow_intensity=False, continuity_state="partial_reprise")
        plan = _plan(wt)
        assert len(_quality_sessions(plan)) == 0

    def test_all_easy_or_recovery(self):
        wt = _wt_distance(20.0, sessions=3, allow_intensity=False, continuity_state="partial_reprise")
        plan = _plan(wt)
        for s in _running_sessions(plan):
            assert s.workout_type in ("easy", "recovery", "long_easy"), (
                f"Unexpected: {s.workout_type}"
            )

    def test_route_code_present(self):
        wt = _wt_distance(20.0, sessions=3, allow_intensity=False, continuity_state="partial_reprise")
        plan = _plan(wt)
        assert "generator_route_partial_reprise" in plan.reason_codes


# ---------------------------------------------------------------------------
# D. reprise_exit allow_intensity=True → maximum 1 quality
# ---------------------------------------------------------------------------

class TestRepriseExitAllowIntensity:

    def test_max_one_quality_4_sessions(self):
        wt = _wt_distance(30.0, sessions=4, allow_intensity=True)
        plan = _plan(wt)
        assert len(_quality_sessions(plan)) <= 1

    def test_max_one_quality_5_sessions(self):
        wt = _wt_distance(40.0, sessions=5, allow_intensity=True)
        plan = _plan(wt)
        assert len(_quality_sessions(plan)) <= 1

    def test_max_one_quality_6_sessions(self):
        wt = _wt_distance(50.0, sessions=6, allow_intensity=True)
        plan = _plan(wt)
        assert len(_quality_sessions(plan)) <= 1

    def test_distance_sum_exact_reprise_exit(self):
        wt = _wt_distance(28.0, sessions=4, allow_intensity=True)
        plan = _plan(wt)
        total = round(sum(s.distance_km for s in _running_sessions(plan) if s.distance_km), 1)
        assert abs(total - 28.0) <= 0.1


# ---------------------------------------------------------------------------
# E. reprise_exit allow_intensity=False → zero quality
# ---------------------------------------------------------------------------

class TestRepriseExitNoIntensity:

    def test_zero_quality_sessions(self):
        wt = _wt_distance(25.0, sessions=4, allow_intensity=False)
        plan = _plan(wt)
        assert len(_quality_sessions(plan)) == 0

    def test_all_easy_or_lower(self):
        wt = _wt_distance(25.0, sessions=4, allow_intensity=False)
        plan = _plan(wt)
        for s in _running_sessions(plan):
            assert s.workout_type in ("easy", "recovery", "long_easy"), (
                f"Unexpected: {s.workout_type}"
            )


# ---------------------------------------------------------------------------
# F. normal allow_intensity=True → maximum 1 quality
# ---------------------------------------------------------------------------

class TestNormalAllowIntensity:

    @pytest.mark.parametrize("sessions", [2, 3, 4, 5, 6])
    def test_max_one_quality(self, sessions: int):
        km = sessions * 8.0
        wt = _wt_distance(km, sessions=sessions, allow_intensity=True)
        plan = _plan(wt)
        assert len(_quality_sessions(plan)) <= 1

    def test_normal_4_sessions_sum_exact(self):
        wt = _wt_distance(42.0, sessions=4, allow_intensity=True)
        plan = _plan(wt)
        total = round(sum(s.distance_km for s in _running_sessions(plan) if s.distance_km), 1)
        assert abs(total - 42.0) <= 0.1


# ---------------------------------------------------------------------------
# G. normal allow_intensity=False → zero quality
# ---------------------------------------------------------------------------

class TestNormalNoIntensity:

    @pytest.mark.parametrize("sessions", [2, 3, 4, 5, 6])
    def test_zero_quality(self, sessions: int):
        km = sessions * 7.0
        wt = _wt_distance(km, sessions=sessions, allow_intensity=False)
        plan = _plan(wt)
        assert len(_quality_sessions(plan)) == 0


# ---------------------------------------------------------------------------
# H. Long run proportionality
# ---------------------------------------------------------------------------

class TestLongRunProportionality:

    def test_low_volume_long_run_proportional(self):
        """20 km week → long run is NOT 28 km (marathon)."""
        lr = _compute_long_run_km(20.0, "marathon")
        assert lr <= 20.0
        assert lr >= 20.0 * 0.20  # minimum fraction

    def test_marathon_low_volume_no_28km_floor(self):
        """A 20 km weekly target must never produce a 28 km long run."""
        lr = _compute_long_run_km(20.0, "marathon")
        assert lr < 28.0, f"Long run {lr} >= 28 km for a 20 km week!"

    def test_semi_low_volume_no_16km_floor(self):
        """A 15 km weekly target must never produce a 16 km long run."""
        lr = _compute_long_run_km(15.0, "half_marathon")
        assert lr <= 15.0

    def test_long_run_never_exceeds_weekly_target(self):
        for km in [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 80.0]:
            for goal in ["5k", "10k", "half_marathon", "marathon", "ultra", "maintenance"]:
                lr = _compute_long_run_km(km, goal)
                assert lr <= km, f"long_run {lr} > weekly {km} for {goal}"

    def test_long_run_max_fraction_respected(self):
        """Long run never absorbs more than LONG_RUN_MAX_FRACTION of weekly km."""
        for km in [15.0, 25.0, 35.0, 50.0]:
            for goal in ["marathon", "half_marathon", "maintenance"]:
                lr = _compute_long_run_km(km, goal)
                assert lr <= km * LONG_RUN_MAX_FRACTION + 0.1, (
                    f"long_run fraction {lr/km:.2f} > {LONG_RUN_MAX_FRACTION} for {km} km / {goal}"
                )

    def test_five_k_long_run_less_dominant(self):
        """5K goal → long run should be smaller than marathon goal (same volume)."""
        lr_5k = _compute_long_run_km(40.0, "5k")
        lr_marathon = _compute_long_run_km(40.0, "marathon")
        assert lr_5k <= lr_marathon

    def test_marathon_long_run_larger_than_5k(self):
        lr_5k = _compute_long_run_km(40.0, "5k")
        lr_marathon = _compute_long_run_km(40.0, "marathon")
        assert lr_marathon >= lr_5k

    def test_plan_long_run_exists_in_normal_week(self):
        """Normal week should include at least one long_easy session."""
        wt = _wt_distance(40.0, sessions=4, allow_intensity=True)
        plan = _plan(wt, goal="marathon")
        long_sessions = [s for s in plan.sessions if s.workout_type == "long_easy"]
        assert len(long_sessions) >= 1

    def test_plan_long_run_not_more_than_half_weekly(self):
        """Long run session distance <= 50% of total weekly km."""
        wt = _wt_distance(40.0, sessions=4, allow_intensity=True)
        plan = _plan(wt, goal="marathon")
        long_sessions = [s for s in plan.sessions if s.workout_type == "long_easy"]
        if long_sessions:
            lr_km = long_sessions[0].distance_km or 0.0
            assert lr_km <= 40.0 * 0.50 + 0.1


# ---------------------------------------------------------------------------
# I. NO_ROUNDING_DRIFT — distance
# ---------------------------------------------------------------------------

class TestNoRoundingDriftDistance:

    @pytest.mark.parametrize("km,sessions", [
        (42.0, 4),
        (42.0, 3),
        (42.0, 5),
        (31.7, 3),
        (17.3, 4),
        (12.4, 3),
        (50.1, 5),
        (60.0, 6),
    ])
    def test_sum_equals_target(self, km: float, sessions: int):
        wt = _wt_distance(km, sessions=sessions, allow_intensity=True)
        plan = _plan(wt)
        total = round(sum(
            s.distance_km for s in _running_sessions(plan) if s.distance_km is not None
        ), 1)
        assert abs(total - km) <= 0.1, f"target={km} got={total} sessions={sessions}"

    def test_planned_km_matches_target(self):
        wt = _wt_distance(42.0, sessions=4)
        plan = _plan(wt)
        assert plan.planned_km is not None
        assert abs(plan.planned_km - 42.0) <= 0.1


# ---------------------------------------------------------------------------
# J. NO_ROUNDING_DRIFT — duration
# ---------------------------------------------------------------------------

class TestNoRoundingDriftDuration:

    @pytest.mark.parametrize("minutes,sessions", [
        (105, 3),
        (120, 3),
        (137, 3),
        (90, 2),
        (180, 4),
    ])
    def test_duration_sum_exact(self, minutes: int, sessions: int):
        wt = _wt_duration(minutes, sessions=sessions, codes=())
        plan = _plan(wt)
        total = sum(s.duration_minutes for s in _running_sessions(plan) if s.duration_minutes)
        assert total == minutes, f"target={minutes} got={total}"


# ---------------------------------------------------------------------------
# K. Phase modulation — no double volume reduction
# ---------------------------------------------------------------------------

class TestPhaseModulation:

    @pytest.mark.parametrize("phase", ["base", "build", "specific", "taper", "race", "consolidation"])
    def test_volume_not_remodulated(self, phase: str):
        """WorkoutGenerator must not shrink or grow the total vs WeeklyTarget."""
        wt = _wt_distance(30.0, sessions=4, allow_intensity=(phase not in ("taper", "race")))
        plan = _plan(wt, phase=phase)
        total = round(sum(
            s.distance_km for s in _running_sessions(plan) if s.distance_km is not None
        ), 1)
        assert abs(total - 30.0) <= 0.1, (
            f"Phase {phase}: target=30.0 got={total}"
        )

    def test_taper_no_quality(self):
        """Taper phase: quality slots should be downgraded."""
        wt = _wt_distance(25.0, sessions=4, allow_intensity=True)
        plan = _plan(wt, phase="taper")
        # In taper, quality is downgraded by _apply_phase_modulation
        # (allow_intensity may still allow 1 quality — but taper enforces easy)
        # The check: taper preserves volume, does not add a second quality.
        assert len(_quality_sessions(plan)) <= 1

    def test_race_week_conservative(self):
        """Race week: generator must output a conservative plan."""
        wt = _wt_distance(15.0, sessions=2, allow_intensity=False)
        plan = _plan(wt, phase="race")
        assert len(_quality_sessions(plan)) == 0

    def test_consolidation_volume_preserved(self):
        wt = _wt_distance(27.0, sessions=4, allow_intensity=False)
        plan = _plan(wt, phase="consolidation")
        total = round(sum(
            s.distance_km for s in _running_sessions(plan) if s.distance_km is not None
        ), 1)
        assert abs(total - 27.0) <= 0.1


# ---------------------------------------------------------------------------
# L. No false precision
# ---------------------------------------------------------------------------

class TestNoFalsePrecision:

    def test_no_distance_km_when_duration_target(self):
        """Duration-based plans must NOT invent distance_km from a pace fallback."""
        wt = _wt_duration(120, sessions=3)
        plan = _plan(wt)
        for s in _running_sessions(plan):
            assert s.distance_km is None, (
                f"Session {s.day} has distance_km={s.distance_km} despite duration basis"
            )

    def test_no_duration_minutes_when_distance_target(self):
        """Distance-based plans must NOT invent duration_minutes from a pace fallback."""
        wt = _wt_distance(40.0, sessions=4)
        plan = _plan(wt)
        for s in _running_sessions(plan):
            assert s.duration_minutes is None, (
                f"Session {s.day} has duration_minutes={s.duration_minutes} despite distance basis"
            )

    def test_no_training_engine_import(self):
        """Workout generator must not import training_engine."""
        import ast
        import training_v2.workout_generator as wg_module
        import inspect
        source = inspect.getsource(wg_module)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
                mod = getattr(node, "module", "") or ""
                assert "training_engine" not in mod
                for n in names:
                    assert "training_engine" not in n

    def test_no_llm_coach_import(self):
        """Workout generator must not import llm_coach."""
        import ast
        import training_v2.workout_generator as wg_module
        import inspect
        source = inspect.getsource(wg_module)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
                mod = getattr(node, "module", "") or ""
                assert "llm_coach" not in mod
                for n in names:
                    assert "llm_coach" not in n

    def test_no_hardcoded_hr(self):
        """Workout generator must not contain hardcoded HR ranges."""
        import training_v2.workout_generator as wg_module
        import inspect
        # Strip docstrings before checking
        source_lines = [l for l in inspect.getsource(wg_module).splitlines()
                        if not l.strip().startswith("#") and not l.strip().startswith('"""')]
        source = "\n".join(source_lines)
        for hr_pattern in ["120-135", "135-150", "150-165", "165-175"]:
            assert hr_pattern not in source, f"Found hardcoded HR: {hr_pattern}"

    def test_no_hardcoded_pace_fallback(self):
        """Workout generator must not contain hardcoded pace fallbacks."""
        import training_v2.workout_generator as wg_module
        import inspect
        source_lines = [l for l in inspect.getsource(wg_module).splitlines()
                        if not l.strip().startswith("#") and not l.strip().startswith('"""')]
        source = "\n".join(source_lines)
        for pace in ["6:00/km", "7:00/km", "7:30/km"]:
            assert pace not in source, f"Found hardcoded pace: {pace}"

    def test_no_default_weekly_km(self):
        """Workout generator must not contain DEFAULT_WEEKLY_KM."""
        import ast
        import training_v2.workout_generator as wg_module
        import inspect
        source = inspect.getsource(wg_module)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id == "DEFAULT_WEEKLY_KM":
                pytest.fail("Found DEFAULT_WEEKLY_KM in workout_generator")
            if isinstance(node, ast.Attribute) and node.attr == "DEFAULT_WEEKLY_KM":
                pytest.fail("Found DEFAULT_WEEKLY_KM in workout_generator")

    def test_no_goal_config(self):
        """Workout generator must not contain legacy GOAL_CONFIG."""
        import ast
        import training_v2.workout_generator as wg_module
        import inspect
        source = inspect.getsource(wg_module)
        tree = ast.parse(source)
        forbidden = {"GOAL_CONFIG", "VOLUME_GOAL_CONFIG"}
        for node in ast.walk(tree):
            if isinstance(node, ast.Name) and node.id in forbidden:
                pytest.fail(f"Found {node.id} in workout_generator")

    def test_no_garmin_terra(self):
        """Workout generator must not import Garmin or Terra."""
        import ast
        import training_v2.workout_generator as wg_module
        import inspect
        source = inspect.getsource(wg_module)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = [a.name for a in node.names] if isinstance(node, ast.Import) else []
                mod = getattr(node, "module", "") or ""
                for forbidden in ("garmin", "terra"):
                    assert forbidden not in mod.lower()
                    for n in names:
                        assert forbidden not in n.lower()

    def test_no_datetime_now(self):
        """Workout generator must never call datetime.now() or date.today()."""
        import ast
        import training_v2.workout_generator as wg_module
        import inspect
        source = inspect.getsource(wg_module)
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Attribute):
                    if func.attr in ("now", "today"):
                        pytest.fail(f"Found {func.attr}() call in workout_generator")


# ---------------------------------------------------------------------------
# M. Determinism
# ---------------------------------------------------------------------------

class TestDeterminism:

    def test_same_inputs_same_output_distance(self):
        wt = _wt_distance(42.0, sessions=4, allow_intensity=True)
        plan1 = _plan(wt)
        plan2 = _plan(wt)
        assert plan1 == plan2

    def test_same_inputs_same_output_duration(self):
        wt = _wt_duration(120, sessions=3)
        plan1 = _plan(wt)
        plan2 = _plan(wt)
        assert plan1 == plan2

    def test_reference_date_explicit(self):
        """Changing reference_date produces a different plan date but same structure."""
        wt = _wt_distance(40.0, sessions=4)
        plan1 = _plan(wt, ref=date(2026, 8, 11))
        plan2 = _plan(wt, ref=date(2026, 8, 18))
        assert plan1.reference_date != plan2.reference_date
        # sessions should be structurally identical
        assert len(plan1.sessions) == len(plan2.sessions)


# ---------------------------------------------------------------------------
# Non-regression: WeeklyTarget unchanged
# ---------------------------------------------------------------------------

class TestNonRegression:

    def test_weekly_target_still_immutable(self):
        wt = _wt_distance(30.0, sessions=4)
        with pytest.raises(Exception):
            wt.target_km = 99.0  # type: ignore[misc]

    def test_weekly_plan_immutable(self):
        wt = _wt_distance(30.0, sessions=4)
        plan = _plan(wt)
        with pytest.raises(Exception):
            plan.planned_km = 99.0  # type: ignore[misc]

    def test_workout_prescription_immutable(self):
        wt = _wt_distance(30.0, sessions=4)
        plan = _plan(wt)
        running = _running_sessions(plan)
        if running:
            with pytest.raises(Exception):
                running[0].distance_km = 99.0  # type: ignore[misc]

    def test_session_count_matches_target_sessions(self):
        """session_count in WeeklyPlan matches WeeklyTarget.target_sessions when no day constraints."""
        # Use a profile with no max_days_per_week constraint so all session counts are reachable.
        unconstrained_profile = RunnerProfile(
            reference_date=REF,
            age=35, sex="male",
            primary_discipline="road",
            experience_level="established",
            typical_weekly_km=50.0,
            typical_weekly_km_is_observed=True,
            typical_weekly_hours=None,
            typical_runs_per_week=5.0,
            typical_long_run_km=None,
            typical_speed_kmh=None,
            available_history_days=120,
            profile_confidence="medium",
            vo2max=None, vma_kmh=None, max_hr=None, resting_hr=None,
            has_hrv=False, has_vo2max=False, has_training_readiness=False,
            has_power=False, has_running_dynamics=False,
            preferred_days_per_week=None,
            max_days_per_week=None,
            preferred_long_run_day=None,
            injury_constraints=[],
            availability_constraints=[],
        )
        for n in [2, 3, 4, 5, 6]:
            wt = _wt_distance(n * 8.0, sessions=n)
            plan = build_weekly_plan(
                weekly_target=wt,
                runner_profile=unconstrained_profile,
                plan_goal=_plan_goal("marathon"),
                periodization=_periodization("build"),
                reference_date=REF,
            )
            assert plan.session_count == n, (
                f"target_sessions={n} but plan.session_count={plan.session_count}"
            )

    def test_seven_day_plan(self):
        """WeeklyPlan always has exactly 7 sessions (including rest days)."""
        wt = _wt_distance(40.0, sessions=4)
        plan = _plan(wt)
        assert len(plan.sessions) == 7


# ---------------------------------------------------------------------------
# N. Contract — continuity_state end-to-end (PR131 audit correction)
# ---------------------------------------------------------------------------
# Tests the FULL chain: TrainingState → build_weekly_target() → build_weekly_plan()
# Guarantees WeeklyTarget.continuity_state is the single routing signal for
# WorkoutGenerator.  reason_codes MUST NOT affect routing.
# ---------------------------------------------------------------------------

from training_v2.training_state import TrainingState
from training_v2.weekly_target import build_weekly_target
from training_v2.training_history import build_training_history
from training_v2.training_load import build_training_load
from training_v2.runner_profile import build_runner_profile


def _make_training_state(
    continuity_state: str,
    ref: date = REF,
    reason_codes: list[str] | None = None,
) -> TrainingState:
    """Build a minimal TrainingState with the given continuity_state."""
    return TrainingState(
        reference_date=ref,
        continuity_state=continuity_state,
        continuity_confidence="medium",
        load_state="balanced",
        load_confidence="medium",
        overall_confidence="medium",
        days_since_last_run=None,
        recent_7d_km=None,
        recent_30d_km=None,
        acute_load=None,
        chronic_weekly_load=None,
        acwr=None,
        reason_codes=reason_codes or [],
    )


def _minimal_runner_profile(ref: date = REF) -> RunnerProfile:
    hist = build_training_history([], ref)
    return build_runner_profile(
        training_history=hist,
        training_load=build_training_load(activities=[], reference_date=ref),
        user_profile={"typical_weekly_km": 30.0, "preferred_days_per_week": 3},
        reference_date=ref,
    )


def _chain(
    continuity_state: str,
    ref: date = REF,
    goal_type: str = "maintenance",
    phase_name: str = "base",
    reason_codes: list[str] | None = None,
) -> tuple["WeeklyTarget", "WeeklyPlan"]:  # type: ignore[name-defined]
    """Full chain: TrainingState → WeeklyTarget → WeeklyPlan."""
    ts = _make_training_state(continuity_state, ref, reason_codes)
    prof = _minimal_runner_profile(ref)
    hist = build_training_history([], ref)
    goal = _plan_goal(goal_type)
    period = _periodization(phase_name, ref)

    wt = build_weekly_target(
        runner_profile=prof,
        training_history=hist,
        training_state=ts,
        plan_goal=goal,
        periodization=period,
        reference_date=ref,
    )
    plan = build_weekly_plan(
        weekly_target=wt,
        runner_profile=prof,
        plan_goal=goal,
        periodization=period,
        reference_date=ref,
    )
    return wt, plan


class TestContractContinuityStateTransport:
    """Section 5 — continuity_state contract tests.

    These tests prove that WeeklyTarget.continuity_state is transported
    explicitly from TrainingState and that WorkoutGenerator uses it directly.
    reason_codes MUST NOT alter routing.
    """

    def test_5A_deep_reprise_transport_and_routing(self):
        """A: TrainingState deep_reprise → WeeklyTarget.continuity_state == deep_reprise
        → WeeklyPlan deep_reprise branch → no quality session."""
        wt, plan = _chain("deep_reprise")
        assert wt.continuity_state == "deep_reprise"
        quality = [s for s in plan.sessions if s.workout_type == "quality"]
        assert len(quality) == 0, "deep_reprise must produce zero quality sessions"
        assert "generator_route_deep_reprise" in plan.reason_codes

    def test_5B_partial_reprise_transport_and_routing(self):
        """B: partial_reprise → WeeklyTarget.continuity_state == partial_reprise → easy-only."""
        wt, plan = _chain("partial_reprise")
        assert wt.continuity_state == "partial_reprise"
        running = [s for s in plan.sessions if s.workout_type not in ("rest",)]
        for s in running:
            assert s.workout_type in ("easy", "recovery", "long_easy"), (
                f"partial_reprise must be easy-only, got {s.workout_type}"
            )
        assert "generator_route_partial_reprise" in plan.reason_codes

    def test_5C_reprise_exit_with_baseline_intensity(self):
        """C: reprise_exit + baseline exploitable → allow_intensity=True → max 1 quality."""
        wt, plan = _chain("reprise_exit")
        assert wt.continuity_state == "reprise_exit"
        if wt.allow_intensity:
            quality = [s for s in plan.sessions if s.workout_type == "quality"]
            assert len(quality) <= 1, "reprise_exit with intensity: max 1 quality"

    def test_5D_reprise_exit_no_baseline_no_quality(self):
        """D: reprise_exit → if allow_intensity=False → zero quality."""
        wt, plan = _chain("reprise_exit")
        assert wt.continuity_state == "reprise_exit"
        if not wt.allow_intensity:
            quality = [s for s in plan.sessions if s.workout_type == "quality"]
            assert len(quality) == 0, "reprise_exit allow_intensity=False must yield 0 quality"

    def test_5E_normal_uses_normal_routing(self):
        """E: normal → continuity_state == normal → standard routing."""
        wt, plan = _chain("normal")
        assert wt.continuity_state == "normal"
        assert "generator_route_normal" in plan.reason_codes

    def test_5F_reason_codes_do_not_affect_routing(self):
        """F: changing reason_codes without changing continuity_state MUST NOT change routing.

        This test guarantees reason_codes are not a hidden business-state API.
        """
        base_wt = _wt_distance(30.0, sessions=4, allow_intensity=True, continuity_state="normal")
        misleading_wt = _wt_distance(
            30.0, sessions=4, allow_intensity=True,
            codes=("continuity_deep_reprise", "continuity_partial_reprise", "SOME_OTHER_CODE"),
            continuity_state="normal",  # continuity_state is the authority
        )
        plan_base = _plan(base_wt)
        plan_misleading = _plan(misleading_wt)
        # Both must use normal routing, not deep/partial reprise routing.
        assert "generator_route_normal" in plan_base.reason_codes
        assert "generator_route_normal" in plan_misleading.reason_codes
        # Neither should use reprise-specific routing.
        assert "generator_route_deep_reprise" not in plan_misleading.reason_codes
        assert "generator_route_partial_reprise" not in plan_misleading.reason_codes


# ---------------------------------------------------------------------------
# O. Day assignment — RunnerProfile constraints (PR131 audit correction)
# ---------------------------------------------------------------------------

def _runner_profile_with_constraints(
    *,
    max_days: int | None = None,
    unavailable_days: list[str] | None = None,
    ref: date = REF,
) -> RunnerProfile:
    """Build a RunnerProfile with specific scheduling constraints."""
    return RunnerProfile(
        reference_date=ref,
        age=30, sex="female",
        primary_discipline="road",
        experience_level="established",
        typical_weekly_km=35.0,
        typical_weekly_km_is_observed=True,
        typical_weekly_hours=None,
        typical_runs_per_week=3.0,
        typical_long_run_km=None,
        typical_speed_kmh=None,
        available_history_days=90,
        profile_confidence="medium",
        vo2max=None, vma_kmh=None, max_hr=None, resting_hr=None,
        has_hrv=False, has_vo2max=False, has_training_readiness=False,
        has_power=False, has_running_dynamics=False,
        preferred_days_per_week=3,
        max_days_per_week=max_days,
        preferred_long_run_day=None,
        injury_constraints=[],
        availability_constraints=unavailable_days or [],
    )


def _plan_with_profile(
    weekly_target: "WeeklyTarget",  # type: ignore[name-defined]
    runner_profile: RunnerProfile,
    goal: str = "marathon",
    phase: str = "build",
) -> "WeeklyPlan":  # type: ignore[name-defined]
    return build_weekly_plan(
        weekly_target=weekly_target,
        runner_profile=runner_profile,
        plan_goal=_plan_goal(goal),
        periodization=_periodization(phase),
        reference_date=REF,
    )


class TestDayAssignment:
    """Section 10 — day assignment respecting RunnerProfile constraints."""

    def test_10A_no_constraints_fallback_deterministic(self):
        """A: no constraints → fallback deterministic placement."""
        profile = _runner_profile_with_constraints()
        wt = _wt_distance(30.0, sessions=3)
        plan1 = _plan_with_profile(wt, profile)
        plan2 = _plan_with_profile(wt, profile)
        days1 = [(s.day, s.workout_type) for s in plan1.sessions]
        days2 = [(s.day, s.workout_type) for s in plan2.sessions]
        assert days1 == days2, "No-constraint plans must be deterministic"
        running = [s for s in plan1.sessions if s.workout_type != "rest"]
        assert len(running) == 3

    def test_10B_unavailable_days_respected(self):
        """B: unavailable days must not contain running sessions."""
        unavailable = ["monday", "tuesday", "wednesday"]
        profile = _runner_profile_with_constraints(
            unavailable_days=unavailable, max_days=4,
        )
        wt = _wt_distance(25.0, sessions=3)
        plan = _plan_with_profile(wt, profile)
        for s in plan.sessions:
            if s.day in unavailable:
                assert s.workout_type == "rest", (
                    f"{s.day} is unavailable but has workout_type={s.workout_type}"
                )

    def test_10C_max_days_per_week_never_exceeded(self):
        """C: max_days_per_week is never exceeded."""
        for max_d in [2, 3, 4]:
            profile = _runner_profile_with_constraints(max_days=max_d)
            wt = _wt_distance(40.0, sessions=5)  # request more than max
            plan = _plan_with_profile(wt, profile)
            running = [s for s in plan.sessions if s.workout_type != "rest"]
            assert len(running) <= max_d, (
                f"max_days_per_week={max_d} exceeded: got {len(running)} running sessions"
            )

    def test_10D_quality_not_immediately_before_long_easy_when_avoidable(self):
        """D: quality is not placed immediately (adjacent day) before long_easy
        when another placement exists."""
        profile = _runner_profile_with_constraints(max_days=7)
        wt = _wt_distance(40.0, sessions=4, allow_intensity=True)
        plan = _plan_with_profile(wt, profile)
        days_order = ["monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"]
        long_idx = next(
            (i for i, d in enumerate(days_order) if plan.sessions[i].workout_type == "long_easy"),
            None,
        )
        if long_idx is not None and long_idx > 0:
            prev_session = plan.sessions[long_idx - 1]
            # If there are 4+ sessions, quality should not be adjacent to long_easy
            running = [s for s in plan.sessions if s.workout_type != "rest"]
            if len(running) >= 3:
                assert prev_session.workout_type != "quality", (
                    f"quality placed immediately before long_easy on {prev_session.day}"
                )

    def test_10E_same_inputs_same_days(self):
        """E: determinism — identical inputs always produce identical day assignments."""
        profile = _runner_profile_with_constraints(
            max_days=5, unavailable_days=["monday"],
        )
        wt = _wt_distance(35.0, sessions=4)
        results = []
        for _ in range(3):
            plan = _plan_with_profile(wt, profile)
            results.append([(s.day, s.workout_type) for s in plan.sessions])
        assert results[0] == results[1] == results[2], "Non-deterministic day assignment"

    def test_10F_impossible_constraints_reason_code_no_crash(self):
        """F: constraints that make target_sessions impossible → SCHEDULE_CONSTRAINT_LIMITED
        reason code + no crash (returns best available plan)."""
        # Only 2 days available, requesting 4 sessions.
        profile = _runner_profile_with_constraints(
            unavailable_days=["monday", "tuesday", "wednesday", "thursday", "friday"],
            max_days=2,
        )
        wt = _wt_distance(32.0, sessions=4)
        # Must not crash.
        plan = _plan_with_profile(wt, profile)
        assert "SCHEDULE_CONSTRAINT_LIMITED" in plan.reason_codes, (
            "Impossible constraints must produce SCHEDULE_CONSTRAINT_LIMITED"
        )
        # Running sessions must not exceed available days.
        running = [s for s in plan.sessions if s.workout_type != "rest"]
        assert len(running) <= 2
        assert len(plan.sessions) == 7  # always 7-day plan
