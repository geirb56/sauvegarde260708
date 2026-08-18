"""PR#141 — Regression tests for disproportionate long run / weekly target during reprise.

Root cause:  when a runner has duration-only activities in the last 28 days (no
valid distance_m) but a large 90-day historical baseline, ``_classify_continuity``
previously classified them as ``normal`` because ``days_since_last_run < 28``.
This caused ``_target_normal`` to pick up the inflated 90d baseline (~40 km/week)
and produce a ~16 km long run.

Primary fix:  ``training_state._classify_continuity`` now also checks that all
``weekly_distance_buckets_28d`` are non-zero before allowing a non-deep-reprise
state.  A runner with zero km in the last 28 days is always ``deep_reprise``.

Secondary fix:  ``weekly_target._chronic_base_km`` guards the RunnerProfile
90d-fallback so it is only used when ``days_since >= 28``.

Invariant fix:  ``workout_generator.build_weekly_plan`` explicitly caps every
session distance to ``weekly_target.target_km`` as a belt-and-suspenders guard.

All fixtures use the DomainActivity dict format:
    {
        "activity_type": "running",
        "start_time": <ISO date str>,
        "distance_m": <float>,   # 0 or None for duration-only
        "duration_s": <float>,
    }

Cases:
    A  deep_reprise + half_marathon goal  → duration basis, target_km=None
    B  deep_reprise + marathon goal       → duration basis, target_km=None
    C  deep_reprise + ultra goal          → duration basis, target_km=None
    D  partial_reprise                    → bounded distance target, no goal jump
    E  reprise_exit                       → proportional long run, no mandatory intensity
    F  normal athlete                     → goal floors still operative
    G  EXACT BUG CASE — duration-only in 28d + heavy 90d history + half_marathon
         must NOT produce target_km≈40-46 km or long_run≈16 km
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from typing import Optional, Sequence

import pytest

sys.path.insert(0, ".")

from training_v2.training_history import TrainingHistory, build_training_history
from training_v2.runner_profile import RunnerProfile, build_runner_profile
from training_v2.training_state import TrainingState, build_training_state
from training_v2.weekly_target import WeeklyTarget, build_weekly_target
from training_v2.plan_goal import PlanGoal, build_plan_goal
from training_v2.periodization import build_periodization
from training_v2.training_load import build_training_load
from training_v2.workout_generator import build_weekly_plan

# ---------------------------------------------------------------------------
# Reference date (fixed for determinism)
# ---------------------------------------------------------------------------
REF = date(2026, 8, 18)
CYCLE_ANCHOR = REF - timedelta(weeks=8)


# ---------------------------------------------------------------------------
# Fixture helpers (DomainActivity format)
# ---------------------------------------------------------------------------

def _act(days_ago: int, km: float, minutes: Optional[float] = None, ref: date = REF) -> dict:
    """Normal run with valid distance_m."""
    act_date = ref - timedelta(days=days_ago)
    dur_s = (minutes * 60) if minutes is not None else (km * 6 * 60)
    return {
        "activity_type": "running",
        "start_time": act_date.isoformat(),
        "distance_m": km * 1000,
        "duration_s": dur_s,
    }


def _duration_only_act(days_ago: int, minutes: float, ref: date = REF) -> dict:
    """Duration-only run (no valid GPS distance — e.g. indoor treadmill).

    ``distance_m=0`` is not a valid distance per ``_valid_distance``,
    but ``duration_s > 0`` is valid, so ``days_since_last_run`` will count
    this activity (runner did move), while ``weekly_distance_buckets_28d``
    will correctly record 0 km for that week.
    """
    act_date = ref - timedelta(days=days_ago)
    return {
        "activity_type": "running",
        "start_time": act_date.isoformat(),
        "distance_m": 0,
        "duration_s": minutes * 60,
    }


# ---------------------------------------------------------------------------
# Pipeline helpers
# ---------------------------------------------------------------------------

def _build_pipeline(
    activities: Sequence[dict],
    goal_type: str = "maintenance",
    race_days_from_ref: int = 180,
    ref: date = REF,
    target_distance_km: Optional[float] = None,
) -> tuple[TrainingHistory, RunnerProfile, TrainingState, WeeklyTarget]:
    hist = build_training_history(activities, ref)
    load = build_training_load(activities=[], reference_date=ref)
    prof = build_runner_profile(
        training_history=hist,
        training_load=load,
        user_profile={},
        reference_date=ref,
    )
    state = build_training_state(
        training_history=hist,
        training_load=load,
        runner_profile=prof,
        reference_date=ref,
    )
    race_date = ref + timedelta(days=race_days_from_ref)
    goal = build_plan_goal(
        goal_type=goal_type,
        race_date=race_date,
        target_distance_km=target_distance_km,
    )
    # race_plan_start_date required for future-dated races (engine contract).
    # Use ref as start date so the runner is already "in" the plan cycle.
    plan_start = ref - timedelta(weeks=4)
    period = build_periodization(
        goal, ref,
        training_state=state,
        race_plan_start_date=plan_start,
        cycle_anchor_date=CYCLE_ANCHOR,
    )
    wt = build_weekly_target(
        runner_profile=prof,
        training_history=hist,
        training_state=state,
        plan_goal=goal,
        periodization=period,
        reference_date=ref,
    )
    return hist, prof, state, wt


def _max_session_km(wt: WeeklyTarget, activities: Sequence[dict], goal_type: str, ref: date = REF, target_distance_km: Optional[float] = None) -> Optional[float]:
    """Generate the weekly plan and return the maximum session distance km."""
    hist = build_training_history(activities, ref)
    load = build_training_load(activities=[], reference_date=ref)
    prof = build_runner_profile(training_history=hist, training_load=load, user_profile={}, reference_date=ref)
    state = build_training_state(training_history=hist, training_load=load, runner_profile=prof, reference_date=ref)
    goal = build_plan_goal(goal_type=goal_type, race_date=ref + timedelta(days=180), target_distance_km=target_distance_km)
    plan_start = ref - timedelta(weeks=4)
    period = build_periodization(goal, ref, training_state=state, race_plan_start_date=plan_start, cycle_anchor_date=CYCLE_ANCHOR)
    plan = build_weekly_plan(
        weekly_target=wt,
        runner_profile=prof,
        plan_goal=goal,
        periodization=period,
        reference_date=ref,
    )
    running_sessions = [s for s in plan.sessions if s.workout_type != "rest" and s.distance_km is not None]
    if not running_sessions:
        return None
    return max(s.distance_km for s in running_sessions)


# ---------------------------------------------------------------------------
# Heavy historical baseline used across cases A–C and G
# ---------------------------------------------------------------------------

def _heavy_historical_activities(ref: date = REF) -> list[dict]:
    """~40 km/week from J-35 to J-120 (clear prior trained volume)."""
    acts = []
    for week in range(1, 13):
        for day_offset in (0, 2, 4):
            days_ago = 35 + week * 7 + day_offset
            if days_ago <= 120:
                acts.append(_act(days_ago, 13.0, ref=ref))
    return acts


# ---------------------------------------------------------------------------
# A. deep_reprise + half_marathon
# ---------------------------------------------------------------------------

class TestCaseA_DeepRepriseHalfMarathon:
    """Aucun run récent ~28j + historique antérieur réel + goal = half_marathon.

    Attendu:
    - continuity_state = deep_reprise
    - target_basis = duration
    - target_km = None
    - allow_intensity = False
    - aucune long run kilométrique dérivée du floor semi
    """

    @pytest.fixture
    def setup(self):
        # Classic deep_reprise path: last run at 35+ days (days_since >= 28).
        activities = _heavy_historical_activities()
        hist, prof, state, wt = _build_pipeline(activities, "half_marathon")
        return hist, prof, state, wt

    def test_deep_reprise_state(self, setup):
        _, _, state, _ = setup
        assert state.continuity_state == "deep_reprise"

    def test_duration_basis(self, setup):
        _, _, _, wt = setup
        assert wt.target_basis == "duration"

    def test_target_km_none(self, setup):
        _, _, _, wt = setup
        assert wt.target_km is None

    def test_no_intensity(self, setup):
        _, _, _, wt = setup
        assert wt.allow_intensity is False

    def test_no_km_based_long_run(self, setup):
        _, _, _, wt = setup
        max_km = _max_session_km(wt, _heavy_historical_activities(), "half_marathon")
        assert max_km is None, f"Expected no km sessions in deep_reprise but got max_km={max_km}"


# ---------------------------------------------------------------------------
# B. deep_reprise + marathon
# ---------------------------------------------------------------------------

class TestCaseB_DeepRepriseMarathon:
    @pytest.fixture
    def setup(self):
        activities = _heavy_historical_activities()
        return _build_pipeline(activities, "marathon")

    def test_deep_reprise_state(self, setup):
        _, _, state, _ = setup
        assert state.continuity_state == "deep_reprise"

    def test_duration_basis(self, setup):
        _, _, _, wt = setup
        assert wt.target_basis == "duration"

    def test_target_km_none(self, setup):
        _, _, _, wt = setup
        assert wt.target_km is None

    def test_no_intensity(self, setup):
        _, _, _, wt = setup
        assert wt.allow_intensity is False

    def test_no_km_based_long_run(self, setup):
        _, _, _, wt = setup
        max_km = _max_session_km(wt, _heavy_historical_activities(), "marathon")
        assert max_km is None, f"Expected no km sessions in deep_reprise but got max_km={max_km}"


# ---------------------------------------------------------------------------
# C. deep_reprise + ultra
# ---------------------------------------------------------------------------

class TestCaseC_DeepRepriseUltra:
    @pytest.fixture
    def setup(self):
        activities = _heavy_historical_activities()
        return _build_pipeline(activities, "ultra", race_days_from_ref=300, target_distance_km=60.0)

    def test_deep_reprise_state(self, setup):
        _, _, state, _ = setup
        assert state.continuity_state == "deep_reprise"

    def test_duration_basis(self, setup):
        _, _, _, wt = setup
        assert wt.target_basis == "duration"

    def test_target_km_none(self, setup):
        _, _, _, wt = setup
        assert wt.target_km is None

    def test_no_intensity(self, setup):
        _, _, _, wt = setup
        assert wt.allow_intensity is False

    def test_no_km_based_long_run(self, setup):
        _, _, _, wt = setup
        max_km = _max_session_km(wt, _heavy_historical_activities(), "ultra", target_distance_km=60.0)
        assert max_km is None, f"Expected no km sessions in deep_reprise but got max_km={max_km}"


# ---------------------------------------------------------------------------
# D. partial_reprise — bounded target, no goal floor jump
# ---------------------------------------------------------------------------

class TestCaseD_PartialReprise:
    """Volume récent faible + baseline observable.

    For partial_reprise to trigger:
    - ``_recent_weekly_equivalent_km`` = 7d window distance (must be low)
    - ``_observable_baseline_km`` = runner_profile.typical_weekly_km from 30d window (must be HIGH)
    - recent < PARTIAL_REPRISE_VOLUME_RATIO (0.50) × baseline

    Fixture: 3 high-volume runs at 9–27 days ago create a high 30d baseline;
    one small run 3 days ago keeps recent low.

    Attendu:
    - continuity_state = partial_reprise
    - cible progressive et bornée
    - aucun saut vers le floor normal du goal
    - allow_intensity = False
    """

    @pytest.fixture
    def activities(self):
        # Days 9-27: high volume, sits inside the 30d window → drives the baseline up.
        # Each run is 15 km; 6 runs = 90 km in 30d → typical_weekly_km ≈ 90*7/30 = 21 km/week.
        high_volume = [_act(days_ago, 15.0) for days_ago in (9, 13, 17, 21, 25, 28)]
        # Day 3: very small run = 2 km → 7d window only sees 2 km.
        # recent_weekly_km (7d) = 2 km << 0.5 * 21 = 10.5 → partial_reprise triggers.
        recent_low = [_act(3, 2.0)]
        return high_volume + recent_low

    @pytest.fixture
    def setup(self, activities):
        return _build_pipeline(activities, "half_marathon")

    def test_partial_reprise_state(self, setup):
        _, _, state, _ = setup
        assert state.continuity_state == "partial_reprise"

    def test_no_intensity(self, setup):
        _, _, _, wt = setup
        assert wt.allow_intensity is False

    def test_target_bounded(self, setup):
        """Target km must stay well below a typical half_marathon min floor (~35 km).

        A partial_reprise runner doing 2 km/run, 4 runs/week ≈ 8 km/week must
        NOT jump to 35+ km because the half_marathon goal has a weekly floor.
        """
        _, _, _, wt = setup
        if wt.target_basis == "distance":
            assert wt.target_km is not None
            # Should be proportional to recent capacity, not to the half_marathon floor
            assert wt.target_km < 25.0, (
                f"partial_reprise target_km={wt.target_km} is too large "
                f"(likely caused by goal floor override)"
            )

    def test_long_run_proportional_to_target(self, setup, activities):
        _, _, _, wt = setup
        if wt.target_basis != "distance" or wt.target_km is None:
            return  # duration basis — nothing to check
        max_km = _max_session_km(wt, activities, "half_marathon")
        if max_km is not None:
            assert max_km <= wt.target_km, (
                f"long run {max_km} > weekly target {wt.target_km}"
            )


# ---------------------------------------------------------------------------
# E. reprise_exit — proportional long run, no mandatory intensity
# ---------------------------------------------------------------------------

class TestCaseE_RepriseExit:
    """Volume recovering but not yet stable.

    reprise_exit triggers when available_history_days < REPRISE_EXIT_STABLE_WEEKS*7 (28).
    Fixture: 5 runs over 22 days → available_history_days = 22 < 28 → reprise_exit.
    """

    @pytest.fixture
    def activities(self):
        return [_act(days_ago, 7.0) for days_ago in (3, 7, 12, 18, 22)]

    @pytest.fixture
    def setup(self, activities):
        return _build_pipeline(activities, "half_marathon")

    def test_reprise_exit_state(self, setup):
        _, _, state, _ = setup
        assert state.continuity_state == "reprise_exit"

    def test_long_run_proportional(self, setup, activities):
        _, _, _, wt = setup
        if wt.target_basis != "distance" or wt.target_km is None:
            return
        max_km = _max_session_km(wt, activities, "half_marathon")
        if max_km is not None:
            assert max_km <= wt.target_km, (
                f"reprise_exit: long run {max_km} > weekly target {wt.target_km}"
            )

    def test_intensity_not_mandatory(self, setup, activities):
        """allow_intensity may be True in reprise_exit, but intensity is NOT forced."""
        _, _, _, wt = setup
        hist = build_training_history(activities, REF)
        load = build_training_load(activities=[], reference_date=REF)
        prof = build_runner_profile(training_history=hist, training_load=load, user_profile={}, reference_date=REF)
        state = build_training_state(training_history=hist, training_load=load, runner_profile=prof, reference_date=REF)
        goal = build_plan_goal(goal_type="half_marathon", race_date=REF + timedelta(days=180))
        plan_start = REF - timedelta(weeks=4)
        period = build_periodization(goal, REF, training_state=state, race_plan_start_date=plan_start, cycle_anchor_date=CYCLE_ANCHOR)
        plan = build_weekly_plan(
            weekly_target=wt,
            runner_profile=prof,
            plan_goal=goal,
            periodization=period,
            reference_date=REF,
        )
        quality_sessions = [
            s for s in plan.sessions
            if s.workout_type in ("quality", "interval", "tempo")
        ]
        if not wt.allow_intensity:
            assert len(quality_sessions) == 0, (
                f"allow_intensity=False but quality sessions found: {quality_sessions}"
            )


# ---------------------------------------------------------------------------
# F. normal athlete — goal floors still work
# ---------------------------------------------------------------------------

class TestCaseF_Normal:
    """A genuinely normal athlete must not be broken by PR#141.

    Goal floors and normal progression rules should still apply when the
    runner has consistent recent volume.

    For normal state: need available_history_days >= 28 (REPRISE_EXIT_STABLE_WEEKS*7)
    AND w30.activity_count >= REPRISE_EXIT_STABLE_WEEKS*3 = 12.
    Using runs every 2 days over 60 days: 30d window has 15 runs >= 12. ✓
    """

    @pytest.fixture
    def activities(self):
        # Every 2 days for 60 days: 30 activities, 15 in the 30d window
        return [_act(days_ago, 10.0) for days_ago in range(1, 61, 2)]

    @pytest.fixture
    def setup(self, activities):
        return _build_pipeline(activities, "half_marathon")

    def test_normal_state(self, setup):
        _, _, state, _ = setup
        assert state.continuity_state == "normal"

    def test_distance_basis(self, setup):
        _, _, _, wt = setup
        assert wt.target_basis == "distance"

    def test_target_km_not_none(self, setup):
        _, _, _, wt = setup
        assert wt.target_km is not None

    def test_long_run_proportional(self, setup, activities):
        _, _, _, wt = setup
        assert wt.target_km is not None
        max_km = _max_session_km(wt, activities, "half_marathon")
        if max_km is not None:
            assert max_km <= wt.target_km, (
                f"normal: long run {max_km} > weekly target {wt.target_km}"
            )


# ---------------------------------------------------------------------------
# G. EXACT BUG CASE — PR#141
#
# ~4 weeks without real outdoor/GPS running.
# Duration-only activities (treadmill, indoor) in the last 28 days kept
# days_since_last_run < 28, preventing the old code from entering deep_reprise.
# Heavy 90-day historical baseline (~40 km/week) inflated the chronic base.
# Goal = half_marathon.
#
# Before fix:  state=normal, target_km≈40-46 km, long_run≈16 km
# After fix:   state=deep_reprise, target_basis=duration, target_km=None,
#              no km-based long run
# ---------------------------------------------------------------------------

class TestCaseG_ExactBugPR141:
    """Reproduction du cas exact ayant déclenché PR#141."""

    @pytest.fixture
    def activities(self):
        """Duration-only runs in last 28 days + heavy volume 35–120 days ago."""
        # Duration-only (indoor/treadmill, no valid GPS distance)
        recent_duration_only = [
            _duration_only_act(days_ago=5,  minutes=35),
            _duration_only_act(days_ago=12, minutes=40),
            _duration_only_act(days_ago=20, minutes=30),
        ]
        # Historical outdoor running: ~40 km/week from J-35 to J-120
        historical = _heavy_historical_activities()
        return recent_duration_only + historical

    def test_continuity_state_is_deep_reprise(self, activities):
        """After fix: duration-only recent + zero 28d km → deep_reprise."""
        _, _, state, _ = _build_pipeline(activities, "half_marathon")
        assert state.continuity_state == "deep_reprise", (
            f"Expected deep_reprise but got {state.continuity_state!r}. "
            f"The bug may have re-appeared: duration-only runs in 28d are "
            f"inflating the continuity classification."
        )

    def test_target_basis_is_duration(self, activities):
        _, _, _, wt = _build_pipeline(activities, "half_marathon")
        assert wt.target_basis == "duration", (
            f"Expected duration basis but got {wt.target_basis!r}."
        )

    def test_target_km_is_none(self, activities):
        _, _, _, wt = _build_pipeline(activities, "half_marathon")
        assert wt.target_km is None, (
            f"Expected target_km=None for deep_reprise but got {wt.target_km}. "
            f"Goal floor (half_marathon) must NOT inflate reprise target."
        )

    def test_allow_intensity_false(self, activities):
        _, _, _, wt = _build_pipeline(activities, "half_marathon")
        assert wt.allow_intensity is False

    def test_no_km_sessions_in_plan(self, activities):
        """Prouver qu'on ne peut plus obtenir long_run ≈ 16 km."""
        _, _, _, wt = _build_pipeline(activities, "half_marathon")
        max_km = _max_session_km(wt, activities, "half_marathon")
        assert max_km is None, (
            f"Expected no km-based sessions for deep_reprise (duration basis) "
            f"but got max_session_km={max_km}. "
            f"The bug weekly≈2km / long_run≈16km must not be reproducible."
        )

    def test_weekly_distance_buckets_all_zero(self, activities):
        """Verify that the fixture correctly has 0 km in 28d buckets."""
        hist = build_training_history(activities, REF)
        assert all(km == 0 for km in hist.weekly_distance_buckets_28d), (
            f"Expected all-zero 28d buckets but got {hist.weekly_distance_buckets_28d}"
        )

    def test_days_since_less_than_28_without_fix(self, activities):
        """Verify that days_since_last_run < 28 (the old trigger condition).

        This documents WHY the bug existed: duration-only activities count
        toward days_since but not toward distance buckets.
        """
        hist = build_training_history(activities, REF)
        assert hist.days_since_last_run is not None
        assert hist.days_since_last_run < 28, (
            f"Expected days_since_last_run < 28 to prove the duration-only "
            f"activities kept the runner 'active' but got {hist.days_since_last_run}"
        )

    def test_session_invariant_distance_never_exceeds_weekly_target(self, activities):
        """WorkoutGenerator invariant: no session km > weekly target km.

        This test is vacuously true for duration basis (no km sessions),
        but serves as a non-regression marker for the WorkoutGenerator fix.
        """
        _, _, _, wt = _build_pipeline(activities, "half_marathon")
        if wt.target_basis != "distance" or wt.target_km is None:
            return  # invariant doesn't apply to duration-based weeks
        max_km = _max_session_km(wt, activities, "half_marathon")
        if max_km is not None:
            assert max_km <= wt.target_km, (
                f"Invariant violated: session {max_km} km > weekly target {wt.target_km} km"
            )


# ---------------------------------------------------------------------------
# H. Pure deep_reprise: no distance activity AND days_since >= 28
#    (classic path — ensure the primary 28d check still works)
# ---------------------------------------------------------------------------

class TestCaseH_ClassicDeepReprise:
    """Regression: the original days_since >= 28 path must still work."""

    def test_classic_deep_reprise_still_works(self):
        activities = _heavy_historical_activities()
        # Last activity is at 35 days — well above the 28d threshold
        _, _, state, wt = _build_pipeline(activities, "half_marathon")
        assert state.continuity_state == "deep_reprise"
        assert wt.target_basis == "duration"
        assert wt.target_km is None
        assert wt.allow_intensity is False


# ---------------------------------------------------------------------------
# I. goal floor invariant: reprise states are always priority over goal floors
# ---------------------------------------------------------------------------

class TestCaseI_GoalFloorCannotOverrideReprise:
    """Goal floors for every goal type must not override reprise protections."""

    @pytest.mark.parametrize("goal_type,target_km", [
        ("5k", None), ("10k", None), ("half_marathon", None), ("marathon", None), ("ultra", 60.0)
    ])
    def test_goal_floor_does_not_override_deep_reprise(self, goal_type: str, target_km: Optional[float]):
        activities = _heavy_historical_activities()
        _, _, state, wt = _build_pipeline(
            activities, goal_type,
            race_days_from_ref=300 if goal_type == "ultra" else 180,
            target_distance_km=target_km,
        )
        assert state.continuity_state == "deep_reprise", (
            f"goal={goal_type}: expected deep_reprise but got {state.continuity_state}"
        )
        assert wt.target_basis == "duration", (
            f"goal={goal_type}: expected duration basis but got {wt.target_basis}"
        )
        assert wt.target_km is None, (
            f"goal={goal_type}: goal floor produced target_km={wt.target_km} during deep_reprise"
        )

    @pytest.mark.parametrize("goal_type,target_km", [
        ("5k", None), ("10k", None), ("half_marathon", None), ("marathon", None), ("ultra", 60.0)
    ])
    def test_goal_floor_does_not_override_no_distance_in_28d(self, goal_type: str, target_km: Optional[float]):
        """Duration-only runs + heavy history: goal floor must not override deep_reprise."""
        recent_duration_only = [
            _duration_only_act(5, 35),
            _duration_only_act(12, 40),
        ]
        historical = _heavy_historical_activities()
        activities = recent_duration_only + historical
        _, _, state, wt = _build_pipeline(
            activities, goal_type,
            race_days_from_ref=300 if goal_type == "ultra" else 180,
            target_distance_km=target_km,
        )
        assert state.continuity_state == "deep_reprise", (
            f"goal={goal_type}: no_distance_in_28d + goal={goal_type} "
            f"produced state={state.continuity_state} instead of deep_reprise"
        )
        assert wt.target_km is None, (
            f"goal={goal_type}: goal floor produced target_km={wt.target_km} "
            f"during deep_reprise (expected None)"
        )
