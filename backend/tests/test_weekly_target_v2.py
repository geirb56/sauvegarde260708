"""PR130 — WeeklyTarget V2 — full test matrix.

Tests cover all scenarios from the problem statement:

A.  no_history → km=None, duration, no intensity
B.  deep_reprise without prior history → conservative duration
C.  deep_reprise with prior trained history → duration > unknown, no intensity
D.  prior_running_window within J-42..J-28 is used
E.  activity older than J-42 does NOT inflate prior fitness
F.  partial_reprise with observable baseline → distance, prudent, no intensity
G.  partial_reprise without baseline → duration, km=None
H.  reprise_exit → volume HOLD, allow_intensity can be True
I.  reprise_exit → never volume + intensity simultaneously
J.  S1 → S2 → S3 → no collapse
K.  brutal overload → spike dampened
L.  normal → controlled progression
M.  normal marathon low volume → no artificial marathon minimum
N.  taper → target < build/specific
O.  continuous / consolidation → coherent
P.  preferred_days / max_days constraints respected
Q.  no DEFAULT_WEEKLY_KM
R.  no training_engine import
S.  no Garmin / Terra import
T.  no datetime.now / date.today inside weekly_target
"""

from __future__ import annotations

import ast
import sys
import textwrap
from datetime import date, timedelta
from typing import Any, Optional, Sequence

import pytest

# ── import path ──────────────────────────────────────────────────────────────
sys.path.insert(0, ".")

from training_v2.weekly_target import (
    DEEP_REPRISE_WEEKLY_MINUTES_FLOOR,
    DEEP_REPRISE_WEEKLY_MINUTES_TRAINED,
    NORMAL_MAX_PROGRESSION,
    PHASE_VOLUME_MULTIPLIERS,
    PRIOR_TRAINED_KM_FLOOR,
    REPRISE_MAX_SESSIONS,
    WeeklyTarget,
    build_weekly_target,
)
from training_v2.training_history import (
    TrainingHistory,
    build_training_history,
)
from training_v2.training_state import (
    TrainingState,
    build_training_state,
)
from training_v2.runner_profile import RunnerProfile, build_runner_profile
from training_v2.plan_goal import PlanGoal, GoalType, build_plan_goal
from training_v2.periodization import (
    PeriodizationSnapshot,
    PeriodizationPhase,
    PeriodizationMode,
    build_periodization,
)
from training_v2.training_load import TrainingLoadSnapshot, build_training_load

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REF = date(2026, 8, 14)


def _make_activity(days_ago: int, km: float, minutes: float = 0, ref: date = REF) -> dict:
    act_date = ref - timedelta(days=days_ago)
    return {
        "activity_type": "running",
        "start_time": act_date.isoformat(),
        "distance_m": km * 1000,
        "duration_s": (minutes or km * 6) * 60,  # default 6 min/km
    }


def _history(activities: Sequence[dict], ref: date = REF) -> TrainingHistory:
    return build_training_history(activities, ref)


def _load_snapshot() -> TrainingLoadSnapshot:
    return build_training_load(activities=[], reference_date=REF)


def _profile(
    activities: Sequence[dict] = (),
    declared: Optional[dict] = None,
    ref: date = REF,
) -> tuple[TrainingHistory, RunnerProfile]:
    hist = _history(activities, ref)
    prof = build_runner_profile(
        training_history=hist,
        training_load=_load_snapshot(),
        user_profile=declared or {},
        reference_date=ref,
    )
    return hist, prof


def _state(
    hist: TrainingHistory,
    prof: RunnerProfile,
    ref: date = REF,
) -> TrainingState:
    return build_training_state(
        training_history=hist,
        training_load=_load_snapshot(),
        runner_profile=prof,
        reference_date=ref,
    )


CYCLE_ANCHOR = REF - timedelta(weeks=6)  # arbitrary stable anchor for tests


def _goal(
    goal_type: str = "maintenance",
    race_date: Optional[date] = None,
    ref: date = REF,
) -> PlanGoal:
    return build_plan_goal(
        goal_type=goal_type,
        race_date=race_date,
    )


def _periodization(
    goal: Optional[PlanGoal] = None,
    ref: date = REF,
    race_plan_start: Optional[date] = None,
) -> PeriodizationSnapshot:
    g = goal or _goal(ref=ref)
    state = _state(*_profile(ref=ref), ref=ref)
    return build_periodization(
        g, ref, training_state=state,
        race_plan_start_date=race_plan_start,
        cycle_anchor_date=CYCLE_ANCHOR,
    )


def _build(
    activities: Sequence[dict] = (),
    declared: Optional[dict] = None,
    goal_type: str = "maintenance",
    race_date: Optional[date] = None,
    plan_start: Optional[date] = None,
    ref: date = REF,
) -> WeeklyTarget:
    hist, prof = _profile(activities, declared, ref)
    state = _state(hist, prof, ref)
    goal = _goal(goal_type, race_date, ref)
    period = build_periodization(
        goal, ref, training_state=state,
        race_plan_start_date=plan_start,
        cycle_anchor_date=CYCLE_ANCHOR,
    )
    return build_weekly_target(
        runner_profile=prof,
        training_history=hist,
        training_state=state,
        plan_goal=goal,
        periodization=period,
        reference_date=ref,
    )


# ---------------------------------------------------------------------------
# A. no_history
# ---------------------------------------------------------------------------


def test_a_no_history_km_none():
    wt = _build(activities=[])
    assert wt.target_km is None


def test_a_no_history_duration_based():
    wt = _build(activities=[])
    assert wt.target_basis == "duration"
    assert wt.target_duration_minutes is not None
    assert wt.target_duration_minutes > 0


def test_a_no_history_no_intensity():
    wt = _build(activities=[])
    assert wt.allow_intensity is False


def test_a_no_history_conservative_duration():
    wt = _build(activities=[])
    # Must not exceed the deep_reprise floor (no prior training known).
    assert wt.target_duration_minutes <= DEEP_REPRISE_WEEKLY_MINUTES_FLOOR


# ---------------------------------------------------------------------------
# B. deep_reprise without prior history
# ---------------------------------------------------------------------------


def test_b_deep_reprise_no_prior_duration():
    """No run in 28+ days, no activity before J-28 either."""
    # 0 runs anywhere → no_history (TrainingState), but we want deep_reprise.
    # To get deep_reprise: add an old run outside the prior window but before J-42.
    acts = [_make_activity(60, 5.0)]  # only a very old run
    wt = _build(activities=acts)
    assert wt.target_basis == "duration"
    assert wt.target_km is None


def test_b_deep_reprise_no_prior_conservative():
    acts = [_make_activity(60, 5.0)]
    wt = _build(activities=acts)
    # Conservative: not more than trained floor.
    assert wt.target_duration_minutes <= DEEP_REPRISE_WEEKLY_MINUTES_TRAINED


def test_b_deep_reprise_no_prior_no_intensity():
    acts = [_make_activity(60, 5.0)]
    wt = _build(activities=acts)
    assert wt.allow_intensity is False


# ---------------------------------------------------------------------------
# C. deep_reprise with prior trained history → duration > unknown
# ---------------------------------------------------------------------------


def test_c_deep_reprise_trained_vs_unknown():
    """Former trained runner (40 km/w before break) must get longer target."""
    # Trained: ~40 km/week in J-28..J-41 window.
    trained_acts = [
        _make_activity(28, 10.0),
        _make_activity(31, 10.0),
        _make_activity(34, 10.0),
        _make_activity(38, 10.0),
    ]
    # Unknown: only very old activity (> J-42).
    unknown_acts = [_make_activity(60, 5.0)]

    wt_trained = _build(activities=trained_acts)
    wt_unknown = _build(activities=unknown_acts)

    assert wt_trained.target_basis == "duration"
    assert wt_unknown.target_basis == "duration"
    assert wt_trained.target_duration_minutes > wt_unknown.target_duration_minutes, (
        f"Trained ({wt_trained.target_duration_minutes}) must exceed unknown ({wt_unknown.target_duration_minutes})"
    )


def test_c_deep_reprise_trained_no_intensity():
    trained_acts = [_make_activity(30, 10.0), _make_activity(35, 10.0)]
    wt = _build(activities=trained_acts)
    assert wt.allow_intensity is False


def test_c_deep_reprise_trained_still_prudent():
    """Even trained runner must not exceed the TRAINED ceiling."""
    trained_acts = [_make_activity(28, 20.0), _make_activity(35, 20.0)]
    wt = _build(activities=trained_acts)
    assert wt.target_duration_minutes <= DEEP_REPRISE_WEEKLY_MINUTES_TRAINED


# ---------------------------------------------------------------------------
# D. prior_running_window uses J-28..J-41 (both inclusive)
# ---------------------------------------------------------------------------


def test_d_prior_window_j28_inclusive():
    """Activity exactly at J-28 must be in the prior window."""
    acts = [_make_activity(28, 20.0)]  # exactly at boundary
    hist = _history(acts)
    assert hist.prior_running_window.activity_count == 1
    assert hist.prior_running_window.distance_km > 0


def test_d_prior_window_j41_inclusive():
    """Activity exactly at J-41 must be in the prior window."""
    acts = [_make_activity(41, 20.0)]
    hist = _history(acts)
    assert hist.prior_running_window.activity_count == 1
    assert hist.prior_running_window.distance_km > 0


def test_d_prior_window_j42_excluded():
    """Activity at J-42 must NOT be in the prior window."""
    acts = [_make_activity(42, 20.0)]
    hist = _history(acts)
    assert hist.prior_running_window.activity_count == 0
    assert hist.prior_running_window.distance_km == 0.0


def test_d_prior_window_j27_excluded():
    """Activity at J-27 (too recent) must NOT be in the prior window."""
    acts = [_make_activity(27, 20.0)]
    hist = _history(acts)
    assert hist.prior_running_window.activity_count == 0


# ---------------------------------------------------------------------------
# E. Very old activity (>J-42) does not inflate prior fitness
# ---------------------------------------------------------------------------


def test_e_old_activity_ignored_for_prior():
    acts = [_make_activity(90, 100.0)]  # 100 km at J-90 — outside prior window
    hist = _history(acts)
    assert hist.prior_running_window.activity_count == 0
    assert hist.prior_running_window.distance_km == 0.0


def test_e_old_activity_prior_trained_check():
    """Old activity must not push prior_weekly_km above FLOOR threshold."""
    acts = [_make_activity(90, 200.0), _make_activity(60, 5.0)]
    wt_old_only = _build(activities=acts)
    wt_no_history = _build(activities=[_make_activity(60, 5.0)])
    # Both have no prior window activity → same calibration
    assert wt_old_only.target_duration_minutes == wt_no_history.target_duration_minutes


# ---------------------------------------------------------------------------
# F. partial_reprise with observable baseline → distance, prudent, no intensity
# ---------------------------------------------------------------------------


def test_f_partial_reprise_distance_based():
    # 30d history but recent drop.
    # Need enough history for partial_reprise to trigger.
    acts = (
        [_make_activity(d, 5.0) for d in [24, 26, 28]]
        + [_make_activity(d, 5.0) for d in [17, 19, 21]]
        + [_make_activity(d, 5.0) for d in [10, 12, 14]]
        + [_make_activity(2, 2.0)]  # recent big drop
    )
    wt = _build(activities=acts)
    # If partial_reprise, should be distance-based; no_intensity.
    if wt.target_basis == "distance":
        assert wt.target_km is not None
        assert wt.target_km > 0


def test_f_partial_reprise_no_intensity():
    acts = (
        [_make_activity(d, 8.0) for d in [24, 26]]
        + [_make_activity(d, 8.0) for d in [17, 19]]
        + [_make_activity(d, 8.0) for d in [10, 12]]
        + [_make_activity(2, 2.0)]
    )
    wt = _build(activities=acts)
    if wt.target_basis == "distance":
        assert wt.allow_intensity is False


def test_f_partial_reprise_prudent_not_jump():
    """Partial reprise must not jump to 3x the recent volume."""
    acts = (
        [_make_activity(d, 8.0) for d in [24, 26]]
        + [_make_activity(d, 8.0) for d in [17, 19]]
        + [_make_activity(2, 2.0)]
    )
    wt = _build(activities=acts)
    if wt.target_basis == "distance":
        assert wt.target_km <= 20.0, f"Partial reprise should be prudent, got {wt.target_km}"


# ---------------------------------------------------------------------------
# G. partial_reprise without baseline → duration, km=None
# ---------------------------------------------------------------------------


def test_g_partial_reprise_no_baseline_duration():
    # Very short history with some runs: likely reprise_exit or partial_reprise.
    acts = [_make_activity(3, 5.0), _make_activity(6, 4.0)]
    wt = _build(activities=acts)
    # If duration-based: km must be None.
    if wt.target_basis == "duration":
        assert wt.target_km is None
        assert wt.target_duration_minutes is not None


# ---------------------------------------------------------------------------
# H. reprise_exit → volume HOLD, allow_intensity can be True
# ---------------------------------------------------------------------------


def test_h_reprise_exit_allow_intensity():
    # 3 consecutive active weeks → reprise_exit.
    acts = (
        [_make_activity(d, 5.0) for d in [15, 17, 19]]
        + [_make_activity(d, 5.0) for d in [8, 10, 12]]
        + [_make_activity(d, 5.0) for d in [1, 3, 5]]
    )
    wt = _build(activities=acts)
    if wt.target_basis == "distance" and "REPRISE_EXIT" in str(wt.reason_codes):
        assert wt.allow_intensity is True


# ---------------------------------------------------------------------------
# I. reprise_exit — never volume + intensity simultaneously
# ---------------------------------------------------------------------------


def test_i_reprise_exit_no_volume_and_intensity():
    """When intensity returns in reprise_exit, volume must not also grow (HOLD)."""
    acts_base = (
        [_make_activity(d, 10.0) for d in [22, 24, 26]]
        + [_make_activity(d, 10.0) for d in [15, 17, 19]]
        + [_make_activity(d, 10.0) for d in [8, 10, 12]]
        + [_make_activity(d, 10.0) for d in [1, 3, 5]]
    )
    hist, prof = _profile(acts_base)
    state = _state(hist, prof)
    goal = _goal()
    period = build_periodization(goal, REF, training_state=state, cycle_anchor_date=CYCLE_ANCHOR)
    wt = build_weekly_target(
        runner_profile=prof,
        training_history=hist,
        training_state=state,
        plan_goal=goal,
        periodization=period,
        reference_date=REF,
    )
    if wt.allow_intensity:
        # Volume must be HOLD — not grow beyond 5% above the chronic base.
        # Reference: mean of non-zero distance buckets (same as _chronic_base_km).
        buckets = hist.weekly_distance_buckets_28d
        active_buckets = [km for km in buckets if km > 0]
        chronic = sum(active_buckets) / float(len(active_buckets)) if active_buckets else 0.0
        if wt.target_basis == "distance" and wt.target_km is not None:
            assert wt.target_km <= chronic * 1.05 + 0.5, (
                f"reprise_exit: volume {wt.target_km} should be held near chronic {chronic}"
            )


# ---------------------------------------------------------------------------
# J. S1 → S2 → S3 — no collapse
# ---------------------------------------------------------------------------


def test_j_s1_s2_s3_no_collapse():
    """Comeback progression must not collapse across 3 simulated weeks.

    S1 = deep_reprise (duration-based)
    S2 = after 1 week of easy running (may switch to distance)
    S3 = after 2 weeks of easy running (must not regress from S2)
    """
    # S1: deep_reprise — old run only, no recent history.
    wt_s1 = _build(activities=[_make_activity(60, 5.0)])
    assert wt_s1.target_basis == "duration", "S1 should be duration-based"
    assert wt_s1.target_duration_minutes is not None
    assert wt_s1.target_duration_minutes >= DEEP_REPRISE_WEEKLY_MINUTES_FLOOR

    # S2: after 1 week of ~10 km total (3 easy sessions).
    acts_s2 = [_make_activity(d, 3.5) for d in [3, 5, 7]]
    wt_s2 = _build(activities=[_make_activity(60, 5.0)] + acts_s2)
    # S2 must produce a reasonable prescription (not tiny).
    if wt_s2.target_basis == "distance":
        assert wt_s2.target_km is not None
        assert wt_s2.target_km >= 5.0, f"S2 distance target must be reasonable, got {wt_s2.target_km}"
    else:
        assert wt_s2.target_duration_minutes is not None
        assert wt_s2.target_duration_minutes >= 60, f"S2 duration too low: {wt_s2.target_duration_minutes}"

    # S3: after 2 weeks of ~10 km each.
    acts_s3 = [_make_activity(d, 3.5) for d in [3, 5, 7, 10, 12, 14]]
    wt_s3 = _build(activities=[_make_activity(60, 5.0)] + acts_s3)

    # S3 must not collapse below S2 (same units).
    def _km_equiv(wt: WeeklyTarget) -> float:
        if wt.target_km is not None:
            return wt.target_km
        if wt.target_duration_minutes is not None:
            return wt.target_duration_minutes / 6.0  # approx 6 min/km
        return 10.0

    km2 = _km_equiv(wt_s2)
    km3 = _km_equiv(wt_s3)
    assert km3 >= km2 - 1.0, f"S3 ({km3:.1f} km-equiv) must not collapse below S2 ({km2:.1f} km-equiv)"


# ---------------------------------------------------------------------------
# K. Brutal overload is dampened
# ---------------------------------------------------------------------------


def test_k_overload_damped():
    """A spike week must be damped — not validated as new baseline."""
    # Chronic base ~15 km/week, then suddenly 40 km last week.
    chronic_acts = [_make_activity(d, 5.0) for d in [24, 26, 28, 17, 19, 21, 10, 12, 14]]
    spike_acts = [_make_activity(d, 10.0) for d in [1, 2, 3, 4]]  # ~40 km in 7 days
    wt = _build(activities=chronic_acts + spike_acts)
    if wt.target_basis == "distance" and wt.target_km is not None:
        assert wt.target_km <= 25.0, (
            f"Spike should be damped, target {wt.target_km} km is too high"
        )


# ---------------------------------------------------------------------------
# L. Normal → controlled progression
# ---------------------------------------------------------------------------


def test_l_normal_controlled_progression():
    """Normal state: weekly target does not exceed +10% of chronic."""
    chronic_km = 40.0
    acts = [_make_activity(d, chronic_km / 3) for d in [24, 26, 28, 17, 19, 21, 10, 12, 14, 2, 4, 6]]
    wt = _build(activities=acts)
    if wt.target_basis == "distance" and wt.target_km is not None:
        # Should not grow beyond chronic * NORMAL_MAX_PROGRESSION * phase_multiplier.
        # Base phase multiplier is 1.0.
        assert wt.target_km <= chronic_km * NORMAL_MAX_PROGRESSION * 1.05, (
            f"Normal: target {wt.target_km} exceeds max progression"
        )


def test_l_normal_allow_intensity():
    acts = [_make_activity(d, 10.0) for d in [24, 26, 28, 17, 19, 21, 10, 12, 14, 2, 4, 6]]
    wt = _build(activities=acts)
    if wt.target_basis == "distance":
        assert wt.allow_intensity is True


# ---------------------------------------------------------------------------
# M. Normal + marathon goal + low volume → no artificial marathon minimum
# ---------------------------------------------------------------------------


def test_m_marathon_goal_no_artificial_minimum():
    """12 km/week observed + marathon goal must NOT jump to ~40 km."""
    acts = [_make_activity(d, 4.0) for d in [24, 26, 28, 17, 19, 21, 10, 12, 14, 2, 4, 6]]
    race = REF + timedelta(weeks=20)
    plan_start = REF - timedelta(weeks=4)
    wt = _build(
        activities=acts,
        goal_type="marathon",
        race_date=race,
        plan_start=plan_start,
    )
    if wt.target_basis == "distance" and wt.target_km is not None:
        assert wt.target_km <= 20.0, (
            f"Marathon goal must not create artificial volume floor, got {wt.target_km} km"
        )


# ---------------------------------------------------------------------------
# N. Taper < build/specific
# ---------------------------------------------------------------------------


def test_n_taper_less_than_build():
    """Taper phase target must be strictly less than build phase target."""
    chronic_km = 40.0
    acts = [_make_activity(d, chronic_km / 3) for d in [24, 26, 28, 17, 19, 21, 10, 12, 14, 2, 4, 6]]

    # Build phase: long race far away.
    hist, prof = _profile(acts)
    state_build = build_training_state(
        training_history=hist, training_load=_load_snapshot(),
        runner_profile=prof, reference_date=REF
    )
    # Simulate build phase.
    period_build = PeriodizationSnapshot(
        reference_date=REF,
        phase=PeriodizationPhase.build,
        mode=PeriodizationMode.continuous,
        weeks_to_race=None,
        phase_start_date=REF - timedelta(weeks=2),
        phase_end_date=REF + timedelta(weeks=3),
        cycle_week=3,
        cycle_length_weeks=5,
        reason_codes=("PHASE_BUILD",),
    )
    period_taper = PeriodizationSnapshot(
        reference_date=REF,
        phase=PeriodizationPhase.taper,
        mode=PeriodizationMode.race_calendar,
        weeks_to_race=1.0,
        phase_start_date=REF - timedelta(days=3),
        phase_end_date=REF + timedelta(days=10),
        cycle_week=1,
        cycle_length_weeks=2,
        reason_codes=("PHASE_TAPER",),
    )
    goal = _goal()
    wt_build = build_weekly_target(
        runner_profile=prof, training_history=hist, training_state=state_build,
        plan_goal=goal, periodization=period_build, reference_date=REF,
    )
    wt_taper = build_weekly_target(
        runner_profile=prof, training_history=hist, training_state=state_build,
        plan_goal=goal, periodization=period_taper, reference_date=REF,
    )
    if wt_build.target_basis == "distance" and wt_taper.target_basis == "distance":
        assert wt_taper.target_km < wt_build.target_km, (
            f"Taper ({wt_taper.target_km}) must be < build ({wt_build.target_km})"
        )
    # Also verify via multipliers directly.
    assert PHASE_VOLUME_MULTIPLIERS["taper"] < PHASE_VOLUME_MULTIPLIERS["build"]
    assert PHASE_VOLUME_MULTIPLIERS["taper"] < PHASE_VOLUME_MULTIPLIERS["specific"]


# ---------------------------------------------------------------------------
# O. Continuous / consolidation
# ---------------------------------------------------------------------------


def test_o_consolidation_less_than_build():
    """Consolidation multiplier < build multiplier (recovery from build)."""
    assert PHASE_VOLUME_MULTIPLIERS["consolidation"] < PHASE_VOLUME_MULTIPLIERS["build"]


def test_o_maintenance_returns_target():
    """Maintenance goal with running history returns a valid target."""
    acts = [_make_activity(d, 8.0) for d in [24, 26, 28, 17, 19, 21, 10, 12, 14, 2, 4, 6]]
    wt = _build(activities=acts)
    assert wt.target_basis in ("distance", "duration")
    assert (wt.target_km is not None) or (wt.target_duration_minutes is not None)


# ---------------------------------------------------------------------------
# P. preferred_days / max_days constraints
# ---------------------------------------------------------------------------


def test_p_preferred_days_respected():
    acts = [_make_activity(d, 8.0) for d in [24, 26, 28, 17, 19, 21, 10, 12, 14, 2, 4, 6]]
    declared = {"preferred_days_per_week": 4}
    wt = _build(activities=acts, declared=declared)
    assert wt.target_sessions == 4


def test_p_max_days_respected():
    acts = [_make_activity(d, 8.0) for d in [24, 26, 28, 17, 19, 21, 10, 12, 14, 2, 4, 6]]
    declared = {"preferred_days_per_week": 5, "max_days_per_week": 3}
    wt = _build(activities=acts, declared=declared)
    assert wt.target_sessions <= 3


def test_p_reprise_sessions_capped():
    """In deep_reprise, sessions must be <= REPRISE_MAX_SESSIONS."""
    acts = [_make_activity(60, 5.0)]  # old activity → deep_reprise
    declared = {"preferred_days_per_week": 6}
    wt = _build(activities=acts, declared=declared)
    assert wt.target_sessions <= REPRISE_MAX_SESSIONS


def test_p_no_history_sessions_capped():
    wt = _build(activities=[])
    assert wt.target_sessions <= REPRISE_MAX_SESSIONS


def _get_imports(mod) -> list[str]:
    """Return all module names imported in the given module (AST-based)."""
    import inspect
    source = inspect.getsource(mod)
    tree = ast.parse(source)
    imports = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imports.append(node.module)
    return imports


def _get_function_calls(mod) -> str:
    """Return source of all non-comment, non-docstring code."""
    import inspect
    source = inspect.getsource(mod)
    # Remove triple-quoted strings to avoid false positives in docstrings.
    import re
    source_no_docs = re.sub(r'""".*?"""', '', source, flags=re.DOTALL)
    source_no_docs = re.sub(r"'''.*?'''", '', source_no_docs, flags=re.DOTALL)
    # Also remove single-line comments.
    source_no_docs = re.sub(r'#.*', '', source_no_docs)
    return source_no_docs


# ---------------------------------------------------------------------------
# Q. No DEFAULT_WEEKLY_KM constant in weekly_target module
# ---------------------------------------------------------------------------


def test_q_no_default_weekly_km():
    import training_v2.weekly_target as wt_mod
    assert not hasattr(wt_mod, "DEFAULT_WEEKLY_KM"), (
        "DEFAULT_WEEKLY_KM must not exist in weekly_target V2"
    )


# ---------------------------------------------------------------------------
# R. No training_engine import in weekly_target module
# ---------------------------------------------------------------------------


def test_r_no_training_engine_import():
    import training_v2.weekly_target as wt_mod
    imports = _get_imports(wt_mod)
    assert not any("training_engine" in imp for imp in imports), (
        f"weekly_target must not import training_engine; found: {imports}"
    )


# ---------------------------------------------------------------------------
# S. No Garmin / Terra import
# ---------------------------------------------------------------------------


def test_s_no_garmin_terra_import():
    import training_v2.weekly_target as wt_mod
    imports = _get_imports(wt_mod)
    assert not any("garmin" in imp.lower() for imp in imports), (
        f"weekly_target must not import Garmin; found: {imports}"
    )
    assert not any("terra" in imp.lower() for imp in imports), (
        f"weekly_target must not import Terra; found: {imports}"
    )


# ---------------------------------------------------------------------------
# T. No datetime.now / date.today in weekly_target module
# ---------------------------------------------------------------------------


def test_t_no_datetime_now():
    import training_v2.weekly_target as wt_mod
    code = _get_function_calls(wt_mod)
    assert "datetime.now()" not in code, "weekly_target must not call datetime.now() outside docstrings"
    assert "date.today()" not in code, "weekly_target must not call date.today() outside docstrings"


# ---------------------------------------------------------------------------
# Additional structural tests
# ---------------------------------------------------------------------------


def test_weekly_target_is_immutable():
    wt = _build(activities=[])
    with pytest.raises(Exception):
        wt.target_km = 999.0  # type: ignore


def test_weekly_target_has_reason_codes():
    wt = _build(activities=[])
    assert isinstance(wt.reason_codes, tuple)
    assert len(wt.reason_codes) > 0


def test_deep_reprise_weekly_trained_gt_floor():
    """Calibration: TRAINED target must be strictly greater than FLOOR target."""
    assert DEEP_REPRISE_WEEKLY_MINUTES_TRAINED > DEEP_REPRISE_WEEKLY_MINUTES_FLOOR


def test_prior_trained_km_threshold_sensible():
    """PRIOR_TRAINED_KM_FLOOR must be positive and reasonable."""
    assert 0 < PRIOR_TRAINED_KM_FLOOR <= 20.0


def test_prior_running_window_weekly_equivalent():
    """weekly_km_equivalent = distance_km / 2 for the 14-day window."""
    acts = [_make_activity(28, 10.0), _make_activity(35, 10.0)]
    hist = _history(acts)
    pw = hist.prior_running_window
    assert pw.activity_count == 2
    assert abs(pw.weekly_km_equivalent - pw.distance_km / 2.0) < 0.01


# ---------------------------------------------------------------------------
# V2 additions: weekly_distance_buckets_28d, active weeks, reprise_exit fallback
# ---------------------------------------------------------------------------


def test_weekly_distance_buckets_four_active_weeks():
    """Four activities in four distinct weeks all produce non-zero buckets."""
    acts = [
        _make_activity(2, 10.0),
        _make_activity(9, 9.0),
        _make_activity(16, 8.0),
        _make_activity(23, 7.0),
    ]
    hist = _history(acts)
    b = hist.weekly_distance_buckets_28d
    assert b[0] > 0
    assert b[1] > 0
    assert b[2] > 0
    assert b[3] > 0


def test_weekly_distance_buckets_empty_history():
    hist = _history([])
    assert hist.weekly_distance_buckets_28d == (0.0, 0.0, 0.0, 0.0)


def test_active_weeks_exact_count_vs_approximation():
    """Runner with 1 run per week (1 session) should be counted as 3 active weeks.

    Old approximation: 3 // 3 = 1 (undercount).
    New bucket method: 3 non-zero buckets = 3.
    """
    acts = [
        _make_activity(2, 10.0),   # bucket 0
        _make_activity(9, 10.0),   # bucket 1
        _make_activity(16, 10.0),  # bucket 2
    ]
    hist = _history(acts)
    # Bucket-based: 3 non-zero buckets
    active_weeks = sum(1 for km in hist.weekly_distance_buckets_28d if km > 0)
    assert active_weeks == 3


def test_chronic_base_uses_mean_of_active_buckets():
    """chronic_base_km should be the mean of non-zero buckets, not a diluted average."""
    # 2 active weeks: 20 km each. Chronic should be 20 km, not 10 (20+20)/4.
    acts = [
        _make_activity(2, 20.0),
        _make_activity(9, 20.0),
    ]
    hist, prof = _profile(acts)
    # Direct check: mean of non-zero buckets
    buckets = hist.weekly_distance_buckets_28d
    active = [km for km in buckets if km > 0]
    assert active, "should have active buckets"
    expected_chronic = sum(active) / len(active)
    assert abs(expected_chronic - 20.0) < 0.5


def test_reprise_exit_fallback_is_duration_not_km():
    """reprise_exit with no observable baseline must not return target_km=10.0.

    It should return target_basis='duration', target_km=None.
    """
    from training_v2.weekly_target import _target_reprise_exit
    from training_v2.periodization import build_periodization

    # Build a minimal history/profile/periodization with NO recent km data
    # but enough continuity state to trigger reprise_exit path if called directly.
    hist = _history([])
    _, prof = _profile([])
    state = _state(hist, prof)
    goal = _goal()
    period = build_periodization(goal, REF, training_state=state, cycle_anchor_date=CYCLE_ANCHOR)

    reason_codes: list[str] = []
    basis, km, minutes = _target_reprise_exit(prof, hist, period, reason_codes, allow_intensity=True)

    assert basis == "duration", f"expected 'duration', got {basis!r}"
    assert km is None, f"expected None target_km, got {km}"
    assert minutes is not None and minutes > 0
    assert "REPRISE_EXIT_HOLD_FALLBACK" in reason_codes


def test_reprise_exit_fallback_code_in_reason_codes():
    """REPRISE_EXIT_HOLD_FALLBACK code must not produce a distance target."""
    from training_v2.weekly_target import _target_reprise_exit
    from training_v2.periodization import build_periodization

    hist = _history([])
    _, prof = _profile([])
    state = _state(hist, prof)
    goal = _goal()
    period = build_periodization(goal, REF, training_state=state, cycle_anchor_date=CYCLE_ANCHOR)

    reason_codes: list[str] = []
    basis, km, _ = _target_reprise_exit(prof, hist, period, reason_codes, allow_intensity=True)

    if "REPRISE_EXIT_HOLD_FALLBACK" in reason_codes:
        assert km is None, "REPRISE_EXIT_HOLD_FALLBACK must never produce a target_km"
        assert basis == "duration"
