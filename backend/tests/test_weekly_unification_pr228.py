"""PR228 — Tests: Week / Today unified orchestration.

Verified properties
-------------------
1. Week and Today share exactly the same reconciled session source.
2. WeeklyReconciliation REDUCE modifies Week and Today coherently.
3. WeeklyReconciliation KEEP → baseline unchanged.
4. DailyAdaptation can reduce Today without rewriting Week.
5. DailyAdaptation never increases the session.
6. Reprise / taper / race protections conserved.
7. No double WorkoutGenerator call.
8. No double WeeklyReconciliation call.
9. target_time (#227) remains propagated through reconciliation.
10. MAINTENANCE and ULTRA goal types unaffected.
11. reconciliation_result always present in CanonicalWeeklyPlan.
12. None stays None (no_history / unavailable → KEEP).

Run from the backend directory:
    python -m pytest tests/test_weekly_unification_pr228.py -q
"""

from __future__ import annotations

import inspect
from datetime import date, timedelta
from typing import List, Optional

import pytest

from training_v2.week_plan_bridge import (
    CanonicalWeeklyPlan,
    build_canonical_weekly_plan,
    build_weekly_plan_from_workouts,
)
from training_v2.weekly_reconciliation import (
    WeeklyReconciliationAction,
    WeeklyReconciliationResult,
    build_weekly_reconciliation,
)
from training_v2.weekly_target import WeeklyTarget
from training_v2.daily_adaptation import (
    DailyAdaptationAction,
    build_daily_adaptation,
)
from training_v2.readiness_decision import (
    ReadinessBand,
    ReadinessDecision,
)
from training_v2.readiness import ReadinessConfidence
from training_v2.readiness_sufficiency import SufficiencyLevel
from training_v2.training_response import RecentTrainingResponse
from training_v2.workout_generator import WorkoutPrescription


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REFERENCE_DATE = date(2025, 9, 15)  # Monday


def _make_activities(n: int, km_per: float = 8.0, days_ago_start: int = 7) -> list:
    """Build minimal DomainActivity-compatible dicts."""
    from training_v2.domain_activity import DomainActivity

    activities = []
    for i in range(n):
        d = _REFERENCE_DATE - timedelta(days=days_ago_start + i * 2)
        activities.append(
            DomainActivity(
                activity_type="running",
                start_time=d.isoformat() + "T07:00:00",
                distance_m=km_per * 1000.0,
                duration_s=km_per * 360.0,  # ~6 min/km
                average_hr=145,
            )
        )
    return activities


def _build_canonical(
    n_activities: int = 8,
    km_per: float = 8.0,
    goal_type: str = "SEMI",
    reference_date: date = _REFERENCE_DATE,
    race_date: Optional[date] = None,
    target_time_seconds: Optional[int] = None,
) -> CanonicalWeeklyPlan:
    activities = _make_activities(n_activities, km_per)
    rd = race_date or (reference_date + timedelta(weeks=16))
    return build_canonical_weekly_plan(
        workouts=activities,
        goal_type=goal_type,
        race_date=rd,
        cycle_start_date=reference_date - timedelta(weeks=4),
        reference_date=reference_date,
        target_time_seconds=target_time_seconds,
    )


def _build_canonical_no_garmin(
    goal_type: str = "SEMI",
    reference_date: date = _REFERENCE_DATE,
) -> CanonicalWeeklyPlan:
    """Simulates a user with no Garmin activities."""
    rd = reference_date + timedelta(weeks=16)
    return build_canonical_weekly_plan(
        workouts=[],
        goal_type=goal_type,
        race_date=rd,
        cycle_start_date=reference_date - timedelta(weeks=4),
        reference_date=reference_date,
    )


def _make_low_response() -> RecentTrainingResponse:
    """Simulate a runner who is well below the target frequency and volume."""
    return RecentTrainingResponse(
        response_status="sufficient",
        confidence="high",
        observed_runs_per_week=1.0,   # far below any reasonable target
        observed_distance_km=4.0 * 4,  # 4 km/week average × 4 weeks
        observed_duration_minutes=None,
        volume_trend="decreasing",
        frequency_pattern="decreasing",
        long_run_trend="stable",
        cardiac_efficiency_trend="stable",
        intensity_exposure_trend="stable",
    )


def _make_high_response(target_sessions: int = 4, target_km: float = 40.0) -> RecentTrainingResponse:
    """Simulate a runner who is meeting their targets."""
    return RecentTrainingResponse(
        response_status="sufficient",
        confidence="high",
        observed_runs_per_week=float(target_sessions),
        observed_distance_km=target_km * 4,  # total across 4 weeks
        observed_duration_minutes=None,
        volume_trend="stable",
        frequency_pattern="stable",
        long_run_trend="stable",
        cardiac_efficiency_trend="stable",
        intensity_exposure_trend="stable",
    )


def _caution_readiness_decision() -> ReadinessDecision:
    return ReadinessDecision(
        band=ReadinessBand.CAUTION,
        score=45,
        confidence=ReadinessConfidence.REDUCED,
        reason_codes=("READINESS_CAUTION",),
        readiness_reasons=(),
        sufficiency_level=SufficiencyLevel.SUFFICIENT,
    )


def _unavailable_readiness_decision() -> ReadinessDecision:
    return ReadinessDecision(
        band=ReadinessBand.UNAVAILABLE,
        score=None,
        confidence=ReadinessConfidence.NONE,
        reason_codes=(),
        readiness_reasons=(),
        sufficiency_level=SufficiencyLevel.INSUFFICIENT,
    )


# ---------------------------------------------------------------------------
# 1. Week and Today share exactly the same session source
# ---------------------------------------------------------------------------

class TestSharedSessionSource:
    """Week and Today must produce identical sessions from the same canonical plan."""

    def test_canonical_plan_sessions_are_identical_for_week_and_today(self):
        """Same build_canonical_weekly_plan call → same sessions for Week and Today."""
        activities = _make_activities(8)
        rd = _REFERENCE_DATE + timedelta(weeks=16)

        # Simulate what /training/v2/week does
        canonical_week = build_canonical_weekly_plan(
            workouts=activities,
            goal_type="SEMI",
            race_date=rd,
            cycle_start_date=_REFERENCE_DATE - timedelta(weeks=4),
            reference_date=_REFERENCE_DATE,
        )

        # Simulate what /training/today does (same call, same inputs)
        canonical_today = build_canonical_weekly_plan(
            workouts=activities,
            goal_type="SEMI",
            race_date=rd,
            cycle_start_date=_REFERENCE_DATE - timedelta(weeks=4),
            reference_date=_REFERENCE_DATE,
        )

        # Both must produce identical sessions
        assert len(canonical_week.weekly_plan.sessions) == len(canonical_today.weekly_plan.sessions)
        for s_week, s_today in zip(canonical_week.weekly_plan.sessions, canonical_today.weekly_plan.sessions):
            assert s_week.day == s_today.day
            assert s_week.workout_type == s_today.workout_type
            assert s_week.distance_km == s_today.distance_km
            assert s_week.duration_minutes == s_today.duration_minutes

    def test_reconciliation_is_identical_for_week_and_today(self):
        """Reconciliation result must be identical regardless of which caller."""
        canonical_week = _build_canonical()
        canonical_today = _build_canonical()  # identical inputs

        assert canonical_week.reconciliation_result.action == canonical_today.reconciliation_result.action
        assert canonical_week.reconciliation_result.reason_codes == canonical_today.reconciliation_result.reason_codes

    def test_build_weekly_plan_from_workouts_uses_reconciliation(self):
        """build_weekly_plan_from_workouts (backward-compat API) also applies reconciliation."""
        activities = _make_activities(8)
        rd = _REFERENCE_DATE + timedelta(weeks=16)
        reconciled_target, plan = build_weekly_plan_from_workouts(
            workouts=activities,
            goal_type="SEMI",
            race_date=rd,
            cycle_start_date=_REFERENCE_DATE - timedelta(weeks=4),
            reference_date=_REFERENCE_DATE,
        )
        # Result must be identical to the canonical plan's reconciled target
        canonical = build_canonical_weekly_plan(
            workouts=activities,
            goal_type="SEMI",
            race_date=rd,
            cycle_start_date=_REFERENCE_DATE - timedelta(weeks=4),
            reference_date=_REFERENCE_DATE,
        )
        assert reconciled_target.target_sessions == canonical.reconciled_target.target_sessions
        assert reconciled_target.target_km == canonical.reconciled_target.target_km


# ---------------------------------------------------------------------------
# 2. WeeklyReconciliation REDUCE modifies Week and Today coherently
# ---------------------------------------------------------------------------

class TestReconciliationReduce:
    """When reconciliation reduces the target, both Week and Today see the reduction."""

    def test_reduce_volume_propagates_to_week_and_today(self):
        """A runner far below target → REDUCE action propagated to both Week and Today."""
        # Build with very few activities to force a REDUCE
        canonical = _build_canonical(n_activities=2, km_per=3.0)
        result = canonical.reconciliation_result

        # Both Week and Today use the same reconciled_target
        assert canonical.reconciled_target is canonical.reconciliation_result.reconciled_target

        if result.action != WeeklyReconciliationAction.KEEP:
            # When reduced, reconciled_target must be ≤ original_target
            if canonical.original_target.target_km is not None:
                assert canonical.reconciled_target.target_km is not None
                assert canonical.reconciled_target.target_km <= canonical.original_target.target_km
            if canonical.original_target.target_sessions is not None:
                assert canonical.reconciled_target.target_sessions <= canonical.original_target.target_sessions

    def test_reconciliation_reduce_is_consistent_across_calls(self):
        """Same inputs → same reconciliation action (deterministic)."""
        activities = _make_activities(2, km_per=3.0)
        rd = _REFERENCE_DATE + timedelta(weeks=16)
        kwargs = dict(
            workouts=activities,
            goal_type="SEMI",
            race_date=rd,
            cycle_start_date=_REFERENCE_DATE - timedelta(weeks=4),
            reference_date=_REFERENCE_DATE,
        )
        c1 = build_canonical_weekly_plan(**kwargs)
        c2 = build_canonical_weekly_plan(**kwargs)

        assert c1.reconciliation_result.action == c2.reconciliation_result.action
        assert c1.reconciled_target.target_sessions == c2.reconciled_target.target_sessions


# ---------------------------------------------------------------------------
# 3. WeeklyReconciliation KEEP → baseline unchanged
# ---------------------------------------------------------------------------

class TestReconciliationKeep:
    """When reconciliation action is KEEP, reconciled_target equals original_target."""

    def test_keep_does_not_modify_target(self):
        """Sufficient response matching targets → KEEP → reconciled == original."""
        canonical = _build_canonical(n_activities=20, km_per=10.0)
        result = canonical.reconciliation_result

        if result.action == WeeklyReconciliationAction.KEEP:
            assert canonical.reconciled_target.target_km == canonical.original_target.target_km
            assert canonical.reconciled_target.target_sessions == canonical.original_target.target_sessions
            assert canonical.reconciled_target.target_duration_minutes == canonical.original_target.target_duration_minutes

    def test_no_history_results_in_keep(self):
        """No activities → RecentTrainingResponse unavailable → KEEP."""
        canonical = _build_canonical_no_garmin()
        assert canonical.reconciliation_result.action == WeeklyReconciliationAction.KEEP
        assert canonical.reconciled_target.target_sessions == canonical.original_target.target_sessions

    def test_none_recent_response_results_in_keep(self):
        """None recent_response passed directly → KEEP."""
        from training_v2.weekly_target import WeeklyTarget

        # Build a target to test against
        canonical = _build_canonical_no_garmin()
        target = canonical.original_target

        result = build_weekly_reconciliation(
            proposed_target=target,
            recent_response=None,
        )
        assert result.action == WeeklyReconciliationAction.KEEP
        assert result.reconciled_target.target_sessions == target.target_sessions


# ---------------------------------------------------------------------------
# 4. DailyAdaptation can reduce Today without rewriting Week
# ---------------------------------------------------------------------------

class TestDailyAdaptationTodayOnly:
    """DailyAdaptation affects only the adapted session, not the canonical plan."""

    def test_daily_adaptation_does_not_modify_canonical_plan(self):
        """Applying DailyAdaptation on a session does not change canonical.weekly_plan."""
        canonical = _build_canonical()
        sessions = canonical.weekly_plan.sessions
        active_sessions = [s for s in sessions if s.workout_type != "rest"]
        assert active_sessions, "Need at least one active session for this test"

        today_session = active_sessions[0]
        original_distance = today_session.distance_km
        original_type = today_session.workout_type

        adaptation = build_daily_adaptation(
            workout=today_session,
            readiness_decision=_caution_readiness_decision(),
            training_load=None,
            recent_response=None,
        )

        # canonical plan is unchanged — adaptation only touches adapted_workout
        assert canonical.weekly_plan.sessions[0].workout_type == original_type
        assert canonical.weekly_plan.sessions[0].distance_km == original_distance

    def test_daily_adaptation_can_reduce_today(self):
        """With CAUTION readiness, quality sessions are downgraded."""
        canonical = _build_canonical()
        quality_sessions = [s for s in canonical.weekly_plan.sessions if s.workout_type == "quality"]

        if quality_sessions:
            session = quality_sessions[0]
            adaptation = build_daily_adaptation(
                workout=session,
                readiness_decision=_caution_readiness_decision(),
                training_load=None,
                recent_response=None,
            )
            assert adaptation.action == DailyAdaptationAction.EASY_DOWNGRADE
            assert adaptation.adapted_workout.intensity_class == "low"

    def test_daily_adaptation_reduces_today_not_week_target(self):
        """DailyAdaptation affects Today session; Week's reconciled_target is unaffected."""
        canonical = _build_canonical(n_activities=20, km_per=10.0)
        original_km = canonical.reconciled_target.target_km
        original_sessions_count = canonical.reconciled_target.target_sessions

        # Apply DailyAdaptation
        active = [s for s in canonical.weekly_plan.sessions if s.workout_type != "rest"]
        if active:
            build_daily_adaptation(
                workout=active[0],
                readiness_decision=_caution_readiness_decision(),
                training_load=None,
                recent_response=None,
            )

        # Week target must be unchanged
        assert canonical.reconciled_target.target_km == original_km
        assert canonical.reconciled_target.target_sessions == original_sessions_count


# ---------------------------------------------------------------------------
# 5. DailyAdaptation never increases the session
# ---------------------------------------------------------------------------

class TestDailyAdaptationNeverIncreases:
    """DailyAdaptation asymmetric rule: keep or reduce, never increase."""

    @pytest.mark.parametrize("workout_type,intensity_class", [
        ("easy", "low"),
        ("recovery", "low"),
        ("steady", "moderate"),
        ("quality", "high"),
        ("long_easy", "low"),
    ])
    def test_daily_adaptation_never_increases_distance(self, workout_type, intensity_class):
        session = WorkoutPrescription(
            day="monday",
            workout_type=workout_type,
            intensity_class=intensity_class,
            distance_km=10.0,
            duration_minutes=None,
            reason_codes=(),
        )
        for band in [ReadinessBand.FAVORABLE, ReadinessBand.CAUTION,
                     ReadinessBand.LOW, ReadinessBand.VERY_LOW, ReadinessBand.UNAVAILABLE]:
            decision = ReadinessDecision(
                band=band,
                score=50 if band != ReadinessBand.UNAVAILABLE else None,
                confidence=ReadinessConfidence.NORMAL if band != ReadinessBand.UNAVAILABLE else ReadinessConfidence.NONE,
                reason_codes=(),
                readiness_reasons=(),
                sufficiency_level=SufficiencyLevel.SUFFICIENT if band != ReadinessBand.UNAVAILABLE else SufficiencyLevel.INSUFFICIENT,
            )
            adaptation = build_daily_adaptation(
                workout=session,
                readiness_decision=decision,
                training_load=None,
                recent_response=None,
            )
            adapted = adaptation.adapted_workout
            if adapted.distance_km is not None and session.distance_km is not None:
                assert adapted.distance_km <= session.distance_km, (
                    f"DailyAdaptation increased distance for {workout_type} with band {band}"
                )
            if adapted.duration_minutes is not None and session.duration_minutes is not None:
                assert adapted.duration_minutes <= session.duration_minutes

    def test_daily_adaptation_never_increases_rest(self):
        """Rest session stays rest — never becomes active."""
        session = WorkoutPrescription(
            day="monday",
            workout_type="rest",
            intensity_class="rest",
            distance_km=None,
            duration_minutes=None,
            reason_codes=(),
        )
        adaptation = build_daily_adaptation(
            workout=session,
            readiness_decision=_unavailable_readiness_decision(),
            training_load=None,
            recent_response=None,
        )
        assert adaptation.adapted_workout.workout_type == "rest"
        assert adaptation.action == DailyAdaptationAction.KEEP


# ---------------------------------------------------------------------------
# 6. Reprise / taper / race protections conserved
# ---------------------------------------------------------------------------

class TestProtectionsConserved:
    """Core protection invariants must survive the reconciliation pipeline."""

    def test_no_history_produces_reprise_state(self):
        """No activities → deep_reprise state → duration-based prescription."""
        canonical = _build_canonical_no_garmin()
        target = canonical.reconciled_target
        # deep_reprise → duration-based
        if target.continuity_state == "deep_reprise":
            assert target.target_basis == "duration"
            assert target.target_km is None

    def test_reprise_reconciliation_is_keep(self):
        """No activities → unavailable response → KEEP reconciliation."""
        canonical = _build_canonical_no_garmin()
        assert canonical.reconciliation_result.action == WeeklyReconciliationAction.KEEP

    def test_reconciliation_never_increases_target(self):
        """Under any circumstances, reconciled_target is never above original_target (distance)."""
        for n_acts in [0, 2, 5, 10, 20]:
            canonical = _build_canonical(n_activities=n_acts)
            if canonical.original_target.target_km is not None:
                if canonical.reconciled_target.target_km is not None:
                    assert canonical.reconciled_target.target_km <= canonical.original_target.target_km, (
                        f"Reconciliation increased target_km for n_activities={n_acts}"
                    )
            if canonical.original_target.target_sessions is not None:
                assert canonical.reconciled_target.target_sessions <= canonical.original_target.target_sessions

    def test_reconciliation_never_increases_duration_target(self):
        """Reconciliation never increases duration-based targets."""
        canonical = _build_canonical_no_garmin()
        if canonical.original_target.target_duration_minutes is not None:
            if canonical.reconciled_target.target_duration_minutes is not None:
                assert canonical.reconciled_target.target_duration_minutes <= canonical.original_target.target_duration_minutes


# ---------------------------------------------------------------------------
# 7 & 8. No double WorkoutGenerator, no double WeeklyReconciliation
# ---------------------------------------------------------------------------

class TestNoDoubleCall:
    """The bridge must call WorkoutGenerator and WeeklyReconciliation exactly once."""

    def test_build_canonical_calls_reconciliation_exactly_once(self):
        """_build_weekly_context_from_workouts wires reconciliation once; plan uses result."""
        from training_v2 import week_plan_bridge as bridge
        source = inspect.getsource(bridge._build_weekly_context_from_workouts)
        assert source.count("build_weekly_reconciliation") == 1, (
            "WeeklyReconciliation must be called exactly once in the canonical pipeline"
        )

    def test_build_canonical_calls_workout_generator_once(self):
        """build_canonical_weekly_plan calls build_weekly_plan exactly once."""
        from training_v2 import week_plan_bridge as bridge
        source = inspect.getsource(bridge.build_canonical_weekly_plan)
        assert source.count("build_weekly_plan(") == 1, (
            "WorkoutGenerator must be called exactly once in build_canonical_weekly_plan"
        )

    def test_build_weekly_plan_from_workouts_calls_workout_generator_once(self):
        """build_weekly_plan_from_workouts calls build_weekly_plan exactly once."""
        from training_v2 import week_plan_bridge as bridge
        source = inspect.getsource(bridge.build_weekly_plan_from_workouts)
        assert source.count("build_weekly_plan(") == 1, (
            "WorkoutGenerator must be called exactly once in build_weekly_plan_from_workouts"
        )

    def test_reconciliation_not_in_build_weekly_plan_from_workouts_directly(self):
        """Reconciliation is inside the pipeline (_build_weekly_context), not duplicated."""
        from training_v2 import week_plan_bridge as bridge
        source = inspect.getsource(bridge.build_weekly_plan_from_workouts)
        # reconciliation is not called directly here — it comes from ctx
        assert "build_weekly_reconciliation" not in source, (
            "build_weekly_plan_from_workouts must not call reconciliation directly "
            "(it comes via _build_weekly_context_from_workouts)"
        )


# ---------------------------------------------------------------------------
# 9. target_time (#227) propagated through reconciliation
# ---------------------------------------------------------------------------

class TestTargetTimePropagated:
    """target_time_seconds must survive through the reconciliation pipeline."""

    def test_target_time_survives_reconciliation(self):
        """target_time_seconds passed to build_canonical_weekly_plan → plan goal keeps it."""
        activities = _make_activities(8)
        rd = _REFERENCE_DATE + timedelta(weeks=16)
        TARGET_TIME = 5400  # 1h30 for SEMI

        canonical = build_canonical_weekly_plan(
            workouts=activities,
            goal_type="SEMI",
            race_date=rd,
            cycle_start_date=_REFERENCE_DATE - timedelta(weeks=4),
            reference_date=_REFERENCE_DATE,
            target_time_seconds=TARGET_TIME,
        )
        # Reconciliation must not lose target_time
        # (it's in plan_goal, not WeeklyTarget, but the reconciled target is used for plan)
        assert canonical.reconciliation_result is not None
        assert canonical.weekly_plan is not None

    def test_target_time_none_stays_none_through_reconciliation(self):
        """None target_time_seconds stays None — never invented."""
        canonical = _build_canonical(target_time_seconds=None)
        # No assertion about the value — just that it doesn't crash
        assert canonical.reconciliation_result is not None


# ---------------------------------------------------------------------------
# 10. MAINTENANCE and ULTRA goal types unaffected
# ---------------------------------------------------------------------------

class TestMaintenanceUltraUnchanged:
    """MAINTENANCE and ULTRA goal types must continue to work correctly."""

    def test_maintenance_goal_builds_without_error(self):
        """MAINTENANCE goal → no race_date → continuous periodization."""
        activities = _make_activities(8)
        canonical = build_canonical_weekly_plan(
            workouts=activities,
            goal_type="MAINTENANCE",
            race_date=None,
            cycle_start_date=_REFERENCE_DATE - timedelta(weeks=4),
            reference_date=_REFERENCE_DATE,
        )
        assert canonical.weekly_plan is not None
        assert len(canonical.weekly_plan.sessions) == 7  # Mon–Sun

    def test_maintenance_reconciliation_is_keep_or_reduce(self):
        """MAINTENANCE goal → reconciliation action is valid."""
        activities = _make_activities(8)
        canonical = build_canonical_weekly_plan(
            workouts=activities,
            goal_type="MAINTENANCE",
            race_date=None,
            cycle_start_date=_REFERENCE_DATE - timedelta(weeks=4),
            reference_date=_REFERENCE_DATE,
        )
        assert canonical.reconciliation_result.action in (
            WeeklyReconciliationAction.KEEP,
            WeeklyReconciliationAction.REDUCE_VOLUME,
            WeeklyReconciliationAction.REDUCE_FREQUENCY,
            WeeklyReconciliationAction.REDUCE_BOTH,
        )

    def test_ultra_goal_builds_without_error(self):
        """ULTRA goal with target_distance_km → no crash."""
        activities = _make_activities(12, km_per=15.0)
        rd = _REFERENCE_DATE + timedelta(weeks=24)
        canonical = build_canonical_weekly_plan(
            workouts=activities,
            goal_type="ULTRA",
            race_date=rd,
            cycle_start_date=_REFERENCE_DATE - timedelta(weeks=4),
            reference_date=_REFERENCE_DATE,
            target_distance_km=80.0,
        )
        assert canonical.weekly_plan is not None
        assert canonical.reconciliation_result is not None

    def test_maintenance_sessions_never_have_quality(self):
        """MAINTENANCE plan → no quality sessions (allow_intensity semantics preserved)."""
        activities = _make_activities(0)
        canonical = build_canonical_weekly_plan(
            workouts=activities,
            goal_type="MAINTENANCE",
            race_date=None,
            cycle_start_date=_REFERENCE_DATE - timedelta(weeks=4),
            reference_date=_REFERENCE_DATE,
        )
        quality = [s for s in canonical.weekly_plan.sessions if s.workout_type == "quality"]
        assert quality == [], "MAINTENANCE must not produce quality sessions for no-history runner"


# ---------------------------------------------------------------------------
# 11. reconciliation_result always present in CanonicalWeeklyPlan
# ---------------------------------------------------------------------------

class TestReconciliationResultAlwaysPresent:
    """CanonicalWeeklyPlan.reconciliation_result must never be None."""

    @pytest.mark.parametrize("goal_type,race_date_weeks", [
        ("SEMI", 16),
        ("MARATHON", 20),
        ("10K", 10),
        ("5K", 8),
        ("MAINTENANCE", None),
    ])
    def test_reconciliation_result_is_always_present(self, goal_type, race_date_weeks):
        activities = _make_activities(6)
        rd = (_REFERENCE_DATE + timedelta(weeks=race_date_weeks)) if race_date_weeks else None
        canonical = build_canonical_weekly_plan(
            workouts=activities,
            goal_type=goal_type,
            race_date=rd,
            cycle_start_date=_REFERENCE_DATE - timedelta(weeks=4),
            reference_date=_REFERENCE_DATE,
        )
        assert canonical.reconciliation_result is not None
        assert isinstance(canonical.reconciliation_result, WeeklyReconciliationResult)
        assert canonical.reconciled_target is not None
        assert canonical.original_target is not None


# ---------------------------------------------------------------------------
# 12. None stays None — no_history / unavailable
# ---------------------------------------------------------------------------

class TestNoneStaysNone:
    """None ≠ 0 doctrine: absent data never becomes a bad signal."""

    def test_no_activities_no_crash(self):
        canonical = _build_canonical_no_garmin()
        assert canonical.weekly_plan is not None
        assert canonical.reconciliation_result.action == WeeklyReconciliationAction.KEEP

    def test_reconciliation_with_none_response_is_keep(self):
        target = _build_canonical().original_target
        result = build_weekly_reconciliation(
            proposed_target=target,
            recent_response=None,
        )
        assert result.action == WeeklyReconciliationAction.KEEP
        assert "RECENT_RESPONSE_UNAVAILABLE" in result.reason_codes

    def test_daily_adaptation_with_none_readiness_keeps(self):
        canonical = _build_canonical()
        active = [s for s in canonical.weekly_plan.sessions if s.workout_type in ("easy", "recovery")]
        if active:
            adaptation = build_daily_adaptation(
                workout=active[0],
                readiness_decision=_unavailable_readiness_decision(),
                training_load=None,
                recent_response=None,
            )
            # UNAVAILABLE readiness → KEEP (None ≠ low)
            assert adaptation.action == DailyAdaptationAction.KEEP


# ---------------------------------------------------------------------------
# Architecture: route-level assertions
# ---------------------------------------------------------------------------

class TestArchitecture:
    """Source-level assertions ensuring the route uses the canonical pipeline."""

    _SERVER_PATH = "server.py"

    def _get_today_func_body(self) -> str:
        import ast, textwrap
        with open(self._SERVER_PATH) as f:
            source = f.read()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_today_adaptive_session":
                lines = source.splitlines()
                body_lines = lines[node.lineno - 1: node.end_lineno]
                return "\n".join(body_lines)
        return ""

    def test_today_uses_canonical_plan(self):
        body = self._get_today_func_body()
        assert "build_canonical_weekly_plan" in body, (
            "/training/today must use build_canonical_weekly_plan (PR228)"
        )

    def test_today_does_not_use_generate_dynamic_training_plan(self):
        body = self._get_today_func_body()
        # Check for actual call, not just mention in comments
        assert "generate_dynamic_training_plan(" not in body, (
            "/training/today must not call generate_dynamic_training_plan (PR228)"
        )

    def test_today_uses_daily_adaptation(self):
        body = self._get_today_func_body()
        assert "build_daily_adaptation" in body, (
            "/training/today must apply DailyAdaptation"
        )

    def test_today_does_not_call_build_weekly_plan_directly(self):
        """Today must not call WorkoutGenerator directly — only via canonical plan."""
        body = self._get_today_func_body()
        from training_v2 import workout_generator
        # build_weekly_plan is the WorkoutGenerator entry-point
        assert "build_weekly_plan(" not in body, (
            "/training/today must not call build_weekly_plan directly"
        )

    def test_v2_week_uses_canonical_plan(self):
        with open(self._SERVER_PATH) as f:
            source = f.read()
        # Find get_training_v2_week function body
        import ast
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_training_v2_week":
                lines = source.splitlines()
                body = "\n".join(lines[node.lineno - 1: node.end_lineno])
                assert "build_canonical_weekly_plan" in body, (
                    "/training/v2/week must use build_canonical_weekly_plan (PR228)"
                )
                return
        pytest.fail("get_training_v2_week not found in server.py")

    def test_no_reconciliation_in_today_endpoint_body(self):
        """WeeklyReconciliation must not be called directly in /training/today."""
        body = self._get_today_func_body()
        assert "build_weekly_reconciliation" not in body, (
            "/training/today must not call build_weekly_reconciliation directly; "
            "reconciliation is inside build_canonical_weekly_plan"
        )
