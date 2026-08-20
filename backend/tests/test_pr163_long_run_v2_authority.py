"""PR163 — WorkoutGenerator V2 as long_easy authority.

Tests verify:
- compute_long_run_km is no longer called in the generate_cycle_week path.
- llm_coach.py does NOT import compute_long_run_km or _compute_long_run_km.
- No V2 constants (LONG_RUN_FRACTION etc.) are duplicated in llm_coach.py.
- Long-easy distance is proportional for low volumes (no artificial minima).
- Cap absolus V2 are respected.
- Invariant: long_easy.distance_km <= weekly_target.target_km.
- Weekly sum conserved.
- Duration-based path doesn't inject artificial km.
"""
from __future__ import annotations

import ast
import inspect
import textwrap
from datetime import date, timedelta
from pathlib import Path

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_BACKEND = Path(__file__).resolve().parent.parent


def _make_workouts(*, km_per_week: float, weeks: int = 12, ref: date) -> list[dict]:
    """Generate synthetic distance-based workouts (4 runs/week)."""
    runs = 4
    per_run = km_per_week / runs
    workouts = []
    for i in range(weeks):
        for j in range(runs):
            d = ref - timedelta(days=(i * 7 + j * 2))
            workouts.append(
                {
                    "date": d.isoformat(),
                    "activity_type": "running",
                    "distance_km": per_run,
                    "duration_minutes": per_run * 6.0,
                }
            )
    return workouts


def _get_long_easy(sessions) -> "WorkoutPrescription | None":
    return next((s for s in sessions if s.workout_type == "long_easy"), None)


# ---------------------------------------------------------------------------
# H — Non-duplication / import audit
# ---------------------------------------------------------------------------


class TestNoDuplication:
    """llm_coach must NOT import compute_long_run_km (public or private)
    and must NOT duplicate V2 long-run constants."""

    def _llm_coach_source(self) -> str:
        return (_BACKEND / "llm_coach.py").read_text()

    def test_no_import_compute_long_run_km_anywhere(self):
        """compute_long_run_km must not be imported or called in llm_coach.py."""
        tree = ast.parse(self._llm_coach_source())
        for node in ast.walk(tree):
            # Check imports (any level: module-level or inside functions)
            if isinstance(node, ast.ImportFrom):
                for alias in node.names:
                    assert alias.name != "compute_long_run_km", (
                        f"llm_coach.py imports compute_long_run_km from {node.module}"
                    )
            # Check direct calls: compute_long_run_km(...)
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    assert func.id != "compute_long_run_km", (
                        "llm_coach.py calls compute_long_run_km directly"
                    )

    def test_no_import_private_compute_long_run_km(self):
        """llm_coach must never import _compute_long_run_km from training_v2."""
        src = self._llm_coach_source()
        # The private V2 function must never be imported from training_v2
        assert "_compute_long_run_km" not in src, (
            "llm_coach.py must not reference _compute_long_run_km"
        )

    def test_no_long_run_fraction_constant(self):
        """V2 LONG_RUN_FRACTION must not be duplicated in llm_coach.py."""
        src = self._llm_coach_source()
        assert "LONG_RUN_FRACTION" not in src, (
            "llm_coach.py must not duplicate V2 constant LONG_RUN_FRACTION"
        )

    def test_no_long_run_goal_adjust_constant(self):
        src = self._llm_coach_source()
        assert "_LONG_RUN_GOAL_ADJUST" not in src, (
            "llm_coach.py must not duplicate V2 constant _LONG_RUN_GOAL_ADJUST"
        )

    def test_no_long_run_abs_cap_constant(self):
        src = self._llm_coach_source()
        assert "_LONG_RUN_ABS_CAP" not in src, (
            "llm_coach.py must not duplicate V2 constant _LONG_RUN_ABS_CAP"
        )

    def test_generate_cycle_week_uses_context_long_run_km_v2(self):
        """generate_cycle_week must read long_run_km_v2 from context."""
        import llm_coach

        code = inspect.getsource(llm_coach.generate_cycle_week)
        # Must not directly call compute_long_run_km (AST check)
        tree = ast.parse(textwrap.dedent(code))
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                if isinstance(func, ast.Name):
                    assert func.id != "compute_long_run_km", (
                        "generate_cycle_week calls compute_long_run_km directly"
                    )
        # Must read long_run_km_v2 from context
        assert "long_run_km_v2" in code, (
            "generate_cycle_week does not use context['long_run_km_v2']"
        )


# ---------------------------------------------------------------------------
# Core business tests (A–G)
# ---------------------------------------------------------------------------


REF_DATE = date(2025, 6, 9)  # a Monday


class TestLongEasyV2Authority:

    @pytest.fixture(autouse=True)
    def _bridge(self):
        from training_v2.week_plan_bridge import build_weekly_plan_from_workouts
        self._build = build_weekly_plan_from_workouts

    # A — Faible volume marathon
    def test_A_marathon_low_volume_proportional(self):
        """Low-volume marathon: long_easy stays proportional (no 28 km minimum)."""
        wt, wp = self._build(
            workouts=_make_workouts(km_per_week=20, ref=REF_DATE),
            goal_type="MARATHON",
            reference_date=REF_DATE,
        )
        assert wt.target_basis == "distance", "Expected distance-based target"
        le = _get_long_easy(wp.sessions)
        assert le is not None
        assert le.distance_km is not None
        # Must be proportional, NOT 28 km
        assert le.distance_km < 28, (
            f"long_easy {le.distance_km} km should not reach the 28 km marathon cap on low volume"
        )
        # Must be proportional: roughly 0.35–0.45 fraction of target_km
        ratio = le.distance_km / wt.target_km
        assert 0.18 <= ratio <= 0.50, f"long_easy ratio {ratio:.2f} is out of V2 bounds"

    # B — Faible volume semi
    def test_B_semi_low_volume_no_artificial_minimum(self):
        """Low-volume half-marathon: no 16 km artificial minimum."""
        wt, wp = self._build(
            workouts=_make_workouts(km_per_week=20, ref=REF_DATE),
            goal_type="SEMI",
            reference_date=REF_DATE,
        )
        assert wt.target_basis == "distance"
        le = _get_long_easy(wp.sessions)
        assert le is not None
        assert le.distance_km is not None
        assert le.distance_km < 16, (
            f"long_easy {le.distance_km} km imposes artificial 16 km minimum on low volume"
        )
        ratio = le.distance_km / wt.target_km
        assert 0.18 <= ratio <= 0.50

    # C — Volume normal marathon
    def test_C_marathon_normal_volume_fraction_respected(self):
        """Normal volume: long_easy respects V2 fraction/cap."""
        wt, wp = self._build(
            workouts=_make_workouts(km_per_week=50, ref=REF_DATE),
            goal_type="MARATHON",
            reference_date=REF_DATE,
        )
        assert wt.target_basis == "distance"
        le = _get_long_easy(wp.sessions)
        assert le is not None
        assert le.distance_km is not None
        ratio = le.distance_km / wt.target_km
        assert 0.18 <= ratio <= 0.50, f"long_easy ratio {ratio:.2f} out of V2 bounds"

    # D — Volume élevé marathon
    def test_D_marathon_high_volume_cap_respected(self):
        """High volume: 28 km cap for marathon respected."""
        wt, wp = self._build(
            workouts=_make_workouts(km_per_week=80, ref=REF_DATE),
            goal_type="MARATHON",
            reference_date=REF_DATE,
        )
        assert wt.target_basis == "distance"
        le = _get_long_easy(wp.sessions)
        assert le is not None
        assert le.distance_km is not None
        assert le.distance_km <= 28, (
            f"long_easy {le.distance_km} km exceeds the 28 km marathon cap"
        )

    # E — Invariant: long_easy <= weekly target
    def test_E_long_easy_never_exceeds_weekly_target(self):
        """long_easy.distance_km is always <= weekly_target.target_km."""
        for goal, km in [("MARATHON", 20), ("SEMI", 20), ("MARATHON", 60), ("MARATHON", 90)]:
            wt, wp = self._build(
                workouts=_make_workouts(km_per_week=km, ref=REF_DATE),
                goal_type=goal,
                reference_date=REF_DATE,
            )
            if wt.target_basis != "distance" or wt.target_km is None:
                continue
            le = _get_long_easy(wp.sessions)
            if le is None or le.distance_km is None:
                continue
            assert le.distance_km <= wt.target_km, (
                f"{goal} {km}km/week: long_easy {le.distance_km} > target {wt.target_km}"
            )

    # F — Conservation somme hebdomadaire (distance-based)
    def test_F_weekly_sum_conserved(self):
        """Sum of distance_km across sessions ≈ weekly_target.target_km (tolerance ±0.2)."""
        wt, wp = self._build(
            workouts=_make_workouts(km_per_week=40, ref=REF_DATE),
            goal_type="MARATHON",
            reference_date=REF_DATE,
        )
        assert wt.target_basis == "distance"
        total = sum(
            s.distance_km for s in wp.sessions if s.distance_km is not None
        )
        assert abs(total - wt.target_km) <= 0.2, (
            f"Sum {total:.1f} deviates more than 0.2 from target {wt.target_km}"
        )

    # G — Duration-based: no artificial km
    def test_G_duration_based_no_artificial_distance(self):
        """Duration-based week (no_history): long_easy distance_km is None."""
        wt, wp = self._build(
            workouts=[],  # no history → duration-based
            goal_type="MARATHON",
            reference_date=REF_DATE,
        )
        assert wt.target_basis == "duration", "Expected duration-based for no_history"
        le = _get_long_easy(wp.sessions)
        if le is not None:
            assert le.distance_km is None, (
                f"Duration-based week must not inject artificial distance: got {le.distance_km}"
            )

    # V2 values match _compute_long_run_km exactly
    def test_V2_long_easy_matches_compute_long_run_km_v2(self):
        """long_easy.distance_km == _compute_long_run_km(target_km, goal_type)."""
        from training_v2.workout_generator import _compute_long_run_km

        wt, wp = self._build(
            workouts=_make_workouts(km_per_week=20, ref=REF_DATE),
            goal_type="MARATHON",
            reference_date=REF_DATE,
        )
        assert wt.target_basis == "distance"
        le = _get_long_easy(wp.sessions)
        assert le is not None and le.distance_km is not None
        expected = round(_compute_long_run_km(wt.target_km, "marathon"), 1)
        assert le.distance_km == expected, (
            f"long_easy {le.distance_km} != _compute_long_run_km({wt.target_km}, 'marathon') = {expected}"
        )


# ---------------------------------------------------------------------------
# Context transport: server passes long_run_km_v2 to generate_cycle_week
# ---------------------------------------------------------------------------


class TestContextTransport:
    """Ensure generate_cycle_week uses long_run_km_v2 from context."""

    def test_context_key_consumed_as_target_long_run(self):
        """When context contains long_run_km_v2=7.5, build_session uses that value."""
        import asyncio
        import llm_coach

        async def _run():
            ctx = {
                "weekly_km": 25.0,
                "training_state": "normal",
                "target_km_protected": 25.0,
                "long_run_km_v2": 7.5,
            }
            plan, ok, _ = await llm_coach.generate_cycle_week(
                context=ctx,
                phase="build",
                goal="MARATHON",
                user_id="test",
            )
            return plan, ok

        plan, ok = asyncio.run(_run())
        assert ok
        long_run_sessions = [s for s in plan["sessions"] if s.get("type") == "long_run"]
        assert long_run_sessions, "No long_run session found"
        lr = long_run_sessions[0]
        assert lr["distance_km"] == 7.5, (
            f"Expected 7.5 km from context, got {lr['distance_km']}"
        )

    def test_without_long_run_km_v2_no_artificial_large_distance(self):
        """Without long_run_km_v2 in context, no artificial large distance is injected
        (target_long_run defaults to 0)."""
        import asyncio
        import llm_coach

        async def _run():
            ctx = {
                "weekly_km": 25.0,
                "training_state": "normal",
                "target_km_protected": 25.0,
                # no long_run_km_v2
            }
            plan, ok, _ = await llm_coach.generate_cycle_week(
                context=ctx,
                phase="build",
                goal="MARATHON",
                user_id="test",
            )
            return plan, ok

        plan, ok = asyncio.run(_run())
        assert ok
        # long_run session should have distance_km == 0 (no artificial value)
        lr = next((s for s in plan["sessions"] if s.get("type") == "long_run"), None)
        if lr:
            assert lr["distance_km"] == 0, (
                f"Without long_run_km_v2, long_run distance should be 0, got {lr['distance_km']}"
            )


# ---------------------------------------------------------------------------
# PR163 deduplication tests (A–F pipeline invariant suite)
# ---------------------------------------------------------------------------


class TestPipelineUnique:
    """A — Prove that the runtime bridge has exactly ONE construction site for
    each core builder.  AST scan on the source of week_plan_bridge, excluding
    helper / test code outside the module.
    """

    def _bridge_source(self) -> str:
        return (_BACKEND / "training_v2" / "week_plan_bridge.py").read_text()

    def _runtime_call_count(self, source: str, func_name: str) -> int:
        """Count Call nodes whose function is ``func_name`` in the AST."""
        tree = ast.parse(source)
        count = 0
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                func = node.func
                name = func.id if isinstance(func, ast.Name) else (
                    func.attr if isinstance(func, ast.Attribute) else None
                )
                if name == func_name:
                    count += 1
        return count

    def test_single_build_training_history(self):
        src = self._bridge_source()
        assert self._runtime_call_count(src, "build_training_history") == 1

    def test_single_build_training_load(self):
        src = self._bridge_source()
        assert self._runtime_call_count(src, "build_training_load") == 1

    def test_single_build_runner_profile(self):
        src = self._bridge_source()
        assert self._runtime_call_count(src, "build_runner_profile") == 1

    def test_single_build_training_state(self):
        src = self._bridge_source()
        assert self._runtime_call_count(src, "build_training_state") == 1

    def test_single_build_plan_goal(self):
        src = self._bridge_source()
        assert self._runtime_call_count(src, "build_plan_goal") == 1

    def test_single_build_periodization(self):
        src = self._bridge_source()
        assert self._runtime_call_count(src, "build_periodization") == 2, (
            "build_periodization is called inside a single if/else — 2 calls expected (one branch each)"
        )

    def test_single_build_weekly_target(self):
        src = self._bridge_source()
        assert self._runtime_call_count(src, "build_weekly_target") == 1


class TestWeeklyTargetIdentical:
    """B — build_weekly_target_from_workouts and build_weekly_plan_from_workouts[0]
    must return the SAME WeeklyTarget for identical inputs.
    """

    def _call_both(self, **kwargs):
        from training_v2.week_plan_bridge import (
            build_weekly_plan_from_workouts,
            build_weekly_target_from_workouts,
        )
        target_only = build_weekly_target_from_workouts(**kwargs)
        target_from_plan, _ = build_weekly_plan_from_workouts(**kwargs)
        return target_only, target_from_plan

    def test_identity_marathon_normal(self):
        a, b = self._call_both(
            workouts=_make_workouts(km_per_week=50, ref=REF_DATE),
            goal_type="MARATHON",
            reference_date=REF_DATE,
        )
        assert a == b

    def test_identity_semi_low_volume(self):
        a, b = self._call_both(
            workouts=_make_workouts(km_per_week=20, ref=REF_DATE),
            goal_type="SEMI",
            reference_date=REF_DATE,
        )
        assert a == b

    def test_identity_duration_based(self):
        """Duration-based path (empty workouts) must still be identical."""
        a, b = self._call_both(
            workouts=[],
            goal_type="MARATHON",
            reference_date=REF_DATE,
        )
        assert a == b


class TestReferenceDateDeterminism:
    """C — Same inputs + same reference_date → same target + same plan."""

    def test_deterministic_same_ref(self):
        from training_v2.week_plan_bridge import build_weekly_plan_from_workouts
        kwargs = dict(
            workouts=_make_workouts(km_per_week=40, ref=REF_DATE),
            goal_type="MARATHON",
            reference_date=REF_DATE,
        )
        wt1, wp1 = build_weekly_plan_from_workouts(**kwargs)
        wt2, wp2 = build_weekly_plan_from_workouts(**kwargs)
        assert wt1 == wt2
        # Plans should also be equal (same sessions list)
        assert len(wp1.sessions) == len(wp2.sessions)
        for s1, s2 in zip(wp1.sessions, wp2.sessions):
            assert s1.workout_type == s2.workout_type
            assert s1.distance_km == s2.distance_km

    def test_different_ref_may_differ(self):
        """Different reference_date with same workouts: targets are allowed to differ
        (just ensuring no crash and that the pipeline runs cleanly)."""
        from training_v2.week_plan_bridge import build_weekly_target_from_workouts
        other_ref = date(2025, 6, 16)
        wts = []
        for ref in (REF_DATE, other_ref):
            wts.append(build_weekly_target_from_workouts(
                workouts=_make_workouts(km_per_week=40, ref=ref),
                goal_type="MARATHON",
                reference_date=ref,
            ))
        # Both must be valid WeeklyTarget objects (no exception)
        from training_v2.weekly_target import WeeklyTarget
        for wt in wts:
            assert isinstance(wt, WeeklyTarget)


class TestRaceGoalBothAPIs:
    """D — Race goal with future race_date: both APIs produce the SAME WeeklyTarget."""

    def test_race_goal_targets_equal(self):
        from training_v2.week_plan_bridge import (
            build_weekly_plan_from_workouts,
            build_weekly_target_from_workouts,
        )
        race = date(2025, 11, 2)
        cycle_start = date(2025, 6, 2)
        kwargs = dict(
            workouts=_make_workouts(km_per_week=50, ref=REF_DATE),
            goal_type="MARATHON",
            race_date=race,
            cycle_start_date=cycle_start,
            reference_date=REF_DATE,
        )
        a = build_weekly_target_from_workouts(**kwargs)
        b, _ = build_weekly_plan_from_workouts(**kwargs)
        assert a == b


class TestMaintenanceGoalBothAPIs:
    """E — Maintenance/no-race goal: both APIs produce the SAME WeeklyTarget."""

    def test_maintenance_targets_equal(self):
        from training_v2.week_plan_bridge import (
            build_weekly_plan_from_workouts,
            build_weekly_target_from_workouts,
        )
        kwargs = dict(
            workouts=_make_workouts(km_per_week=30, ref=REF_DATE),
            goal_type="MAINTENANCE",
            reference_date=REF_DATE,
        )
        a = build_weekly_target_from_workouts(**kwargs)
        b, _ = build_weekly_plan_from_workouts(**kwargs)
        assert a == b


class TestUnknownGoalBothAPIs:
    """F — Both APIs must raise the SAME UnknownGoalTypeError for an unknown goal."""

    def test_target_raises_unknown_goal(self):
        from training_v2.week_plan_bridge import (
            UnknownGoalTypeError,
            build_weekly_target_from_workouts,
        )
        with pytest.raises(UnknownGoalTypeError):
            build_weekly_target_from_workouts(
                workouts=[],
                goal_type="TRIATHLON",
                reference_date=REF_DATE,
            )

    def test_plan_raises_unknown_goal(self):
        from training_v2.week_plan_bridge import (
            UnknownGoalTypeError,
            build_weekly_plan_from_workouts,
        )
        with pytest.raises(UnknownGoalTypeError):
            build_weekly_plan_from_workouts(
                workouts=[],
                goal_type="TRIATHLON",
                reference_date=REF_DATE,
            )

    def test_same_error_type(self):
        """Both APIs must raise exactly UnknownGoalTypeError — not two different types."""
        from training_v2.week_plan_bridge import (
            UnknownGoalTypeError,
            build_weekly_plan_from_workouts,
            build_weekly_target_from_workouts,
        )
        exc_target = exc_plan = None
        try:
            build_weekly_target_from_workouts(
                workouts=[], goal_type="BAD_GOAL", reference_date=REF_DATE
            )
        except UnknownGoalTypeError as e:
            exc_target = e
        try:
            build_weekly_plan_from_workouts(
                workouts=[], goal_type="BAD_GOAL", reference_date=REF_DATE
            )
        except UnknownGoalTypeError as e:
            exc_plan = e
        assert exc_target is not None, "build_weekly_target_from_workouts did not raise"
        assert exc_plan is not None, "build_weekly_plan_from_workouts did not raise"
        assert type(exc_target) is type(exc_plan)
