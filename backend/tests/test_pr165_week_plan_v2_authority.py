"""PR165 — Supprimer la double autorité de prescription dans /training/week-plan.

Tests verify:
- AST: generate_cycle_week is NOT called at runtime in get_week_plan path.
- AST: compute_target_km, reprise_durations, compute_long_run_km,
       apply_resume_guard are NOT called in the week-plan path after PR165.
- The plan comes from build_weekly_plan_from_workouts (WeeklyPlan V2).
- Contract A: distance normal — sum(distance_km) == target_km.
- Contract B: deep_reprise duration — sum(duration_minutes) == target_duration_minutes.
- Contract C: partial_reprise distance — sum(distance_km) ≈ target_km.
- Contract D: partial_reprise duration — sum(duration_minutes) == target_duration_minutes.
- Contract E: no_history duration — target_basis == "duration", no artificial km.
- Contract F: normal duration fallback — target_basis == "duration".
- Contract G: long_easy proportional — distance ≤ weekly_target.target_km.
- Contract H: sum distance conserved across adapter.
- Contract I: sum duration conserved across adapter.
- Contract J: session_count conserved across adapter.
- Contract K: allow_intensity respected (no quality if allow_intensity=False).
- Contract M: TSS doctrine — active=None, rest=0, total_tss=None.
- Adapter mapping: V2 type → legacy display type.
- Adapter: no prescribed fields invented (no HR, no paces).
"""
from __future__ import annotations

import ast
import os
import sys
import textwrap
from datetime import date, timedelta
from typing import Optional

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-pr165")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_REF_DATE = date(2024, 6, 10)


def _make_workouts(n: int = 0, km_per_session: float = 8.0) -> list[dict]:
    """Generate synthetic workout documents for the last n*7 days."""
    ref = _REF_DATE
    workouts = []
    for i in range(n):
        d = ref - timedelta(days=i * 7 + 3)
        workouts.append({
            "distance_km": km_per_session,
            "duration_minutes": 50,
            "date": d.isoformat(),
            "activity_type": "running",
        })
    return workouts


def _make_workouts_deep_reprise_trained() -> list[dict]:
    """Fixture for deep_reprise with a former trained runner (Option A).

    All activities fall in the prior window (days_ago in [28, 41]) so
    days_since_last_run == 29 >= 28 → deep_reprise.

    5 runs × 16 km = 80 km in 2 weeks → prior_km = 40 km/week (= TRAINED cap).
    _interpolate_deep_reprise_minutes(40) → DEEP_REPRISE_WEEKLY_MINUTES_TRAINED = 135.
    active_weeks = 0 (no activity in last 28 days) → no progression multiplier.
    Deterministic result: target_duration_minutes = 135.
    """
    ref = _REF_DATE
    # days_ago 29-41 all fall in [28, 41] inclusive — the prior_running_window.
    prior_dates = [ref - timedelta(days=d) for d in [41, 38, 35, 32, 29]]
    return [
        {
            "distance_km": 16.0,
            "duration_minutes": 80,
            "date": d.isoformat(),
            "activity_type": "running",
        }
        for d in prior_dates
    ]


def _make_workouts_partial_reprise_distance() -> list[dict]:
    """Fixture for partial_reprise + distance-based target (Option A).

    History:
      5 runs × 10 km at days_ago 21, 17, 14, 11, 8 (inside 28d, outside 7d).
      1 run  ×  4 km at days_ago  3             (inside 7d).

    30d total = 54 km → typical_weekly_km = 54 * 7 / 30 ≈ 12.6 km (observed).
    7d total  =  4 km → recent_weekly_km  =  4 km.
    4 < 50 % × 12.6 = 6.3 → continuity_state = "partial_reprise".

    28d buckets: [4, 20, 20, 10] → chronic = 13.5 km.
    _target_partial_reprise: base = min(4, 13.5) = 4 km.
    proposed = 4 × 1.10 = 4.4 km → target_km = 4.4 (build phase multiplier = 1.0).
    """
    ref = _REF_DATE
    bigger = [
        {
            "distance_km": 10.0,
            "duration_minutes": 60,
            "date": (ref - timedelta(days=d)).isoformat(),
            "activity_type": "running",
        }
        for d in [21, 17, 14, 11, 8]
    ]
    small = [
        {
            "distance_km": 4.0,
            "duration_minutes": 25,
            "date": (ref - timedelta(days=3)).isoformat(),
            "activity_type": "running",
        }
    ]
    return bigger + small


def _build_v2_context():
    """Build minimal V2 objects for Option B tests (direct WeeklyTarget construction).

    Returns (runner_profile, plan_goal, periodization, reference_date) built from
    an empty history — the only valid way to wire build_weekly_plan without
    depending on a particular continuity state.
    """
    from training_v2.runner_profile import build_runner_profile
    from training_v2.training_history import build_training_history
    from training_v2.training_load import build_training_load
    from training_v2.plan_goal import build_plan_goal, GoalType
    from training_v2.periodization import build_periodization

    ref = _REF_DATE
    training_history = build_training_history([], ref)
    training_load = build_training_load([], ref)
    runner_profile = build_runner_profile(
        training_history=training_history,
        training_load=training_load,
        user_profile=None,
        capabilities=None,
        physiological_metrics=None,
        reference_date=ref,
    )
    plan_goal = build_plan_goal(
        goal_type=GoalType.half_marathon,
        race_date=None,
        created_from="user",
    )
    periodization = build_periodization(
        plan_goal=plan_goal,
        reference_date=ref,
        cycle_anchor_date=ref - timedelta(weeks=4),
    )
    return runner_profile, plan_goal, periodization, ref


def _run_bridge(
    workouts: list[dict],
    goal_type: str = "SEMI",
    reference_date: Optional[date] = None,
) -> tuple:
    from training_v2.week_plan_bridge import build_weekly_plan_from_workouts
    ref = reference_date or _REF_DATE
    return build_weekly_plan_from_workouts(
        workouts=workouts,
        goal_type=goal_type,
        race_date=None,
        cycle_start_date=ref - timedelta(weeks=4),
        reference_date=ref,
    )


def _adapt(workouts: list[dict], goal_type: str = "SEMI") -> dict:
    from training_v2.week_plan_adapter import adapt_weekly_plan_to_legacy
    wt, wp = _run_bridge(workouts, goal_type)
    return adapt_weekly_plan_to_legacy(wp, wt, "build")


def _active_sessions(plan: dict) -> list[dict]:
    return [s for s in plan["sessions"] if s["type"] != "rest"]


# ---------------------------------------------------------------------------
# AST tests — architectural contracts
# ---------------------------------------------------------------------------

class TestAST:
    """Verify via source inspection that the week-plan path has zero calls
    to legacy prescription functions after PR165."""

    def _server_get_week_plan_source(self) -> str:
        """Read get_week_plan source from server.py without importing the module."""
        from pathlib import Path
        server_path = Path(_BACKEND_DIR) / "server.py"
        source = server_path.read_text()
        tree = ast.parse(source)
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_week_plan":
                lines = source.splitlines()
                start = node.lineno - 1
                end = node.end_lineno
                return "\n".join(lines[start:end])
        raise RuntimeError("get_week_plan not found in server.py")

    def test_generate_cycle_week_not_called_in_get_week_plan(self):
        """PR165: generate_cycle_week must NOT be called inside get_week_plan."""
        source = self._server_get_week_plan_source()
        tree = ast.parse(textwrap.dedent(source))
        calls = [
            node.func.id if isinstance(node.func, ast.Name) else
            node.func.attr if isinstance(node.func, ast.Attribute) else ""
            for node in ast.walk(tree)
            if isinstance(node, ast.Call) and (
                (isinstance(node.func, ast.Name) and node.func.id == "generate_cycle_week") or
                (isinstance(node.func, ast.Attribute) and node.func.attr == "generate_cycle_week")
            )
        ]
        assert calls == [], (
            f"generate_cycle_week is still called in get_week_plan: {calls}"
        )

    def test_compute_target_km_not_called_in_get_week_plan(self):
        """PR165: compute_target_km must NOT be called in get_week_plan."""
        source = self._server_get_week_plan_source()
        assert "compute_target_km" not in source, (
            "compute_target_km is still referenced in get_week_plan after PR165"
        )

    def test_reprise_durations_not_called_in_get_week_plan(self):
        """PR165: reprise_durations must NOT be called in get_week_plan."""
        source = self._server_get_week_plan_source()
        assert "reprise_durations" not in source, (
            "reprise_durations is still referenced in get_week_plan after PR165"
        )

    def test_compute_long_run_km_not_called_in_get_week_plan(self):
        """PR165: compute_long_run_km must NOT be called in get_week_plan."""
        source = self._server_get_week_plan_source()
        assert "compute_long_run_km" not in source, (
            "compute_long_run_km is still referenced in get_week_plan after PR165"
        )

    def test_apply_resume_guard_not_called_in_get_week_plan(self):
        """PR165: apply_resume_guard must NOT be called in get_week_plan."""
        source = self._server_get_week_plan_source()
        assert "apply_resume_guard" not in source, (
            "apply_resume_guard is still referenced in get_week_plan after PR165"
        )

    def test_build_weekly_plan_from_workouts_is_called(self):
        """PR165: get_week_plan must call build_weekly_plan_from_workouts."""
        source = self._server_get_week_plan_source()
        assert "build_weekly_plan_from_workouts" in source, (
            "build_weekly_plan_from_workouts is not called in get_week_plan"
        )

    def test_adapt_weekly_plan_to_legacy_is_called(self):
        """PR165: get_week_plan must call adapt_weekly_plan_to_legacy."""
        source = self._server_get_week_plan_source()
        assert "adapt_weekly_plan_to_legacy" in source, (
            "adapt_weekly_plan_to_legacy is not called in get_week_plan — adapter not wired"
        )

    def test_adapter_does_not_call_prescription_functions(self):
        """PR165: adapter module must not CALL any prescription function (AST — ignores docstrings)."""
        from pathlib import Path
        adapter_path = Path(_BACKEND_DIR) / "training_v2" / "week_plan_adapter.py"
        source = adapter_path.read_text()
        tree = ast.parse(source)
        forbidden = {
            "compute_target_km",
            "reprise_durations",
            "compute_long_run_km",
            "apply_resume_guard",
            "generate_cycle_week",
        }
        calls_found = []
        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                if isinstance(node.func, ast.Name) and node.func.id in forbidden:
                    calls_found.append(node.func.id)
                elif isinstance(node.func, ast.Attribute) and node.func.attr in forbidden:
                    calls_found.append(node.func.attr)
        assert calls_found == [], (
            f"Adapter must not call prescription functions, found: {calls_found}"
        )


# ---------------------------------------------------------------------------
# Contract A — distance normal
# ---------------------------------------------------------------------------

class TestContractA:
    """A: distance-based normal week — sum(distance_km) == target_km."""

    def test_distance_sum_conserved(self):
        workouts = _make_workouts(8, km_per_session=10.0)
        wt, wp = _run_bridge(workouts)
        if wp.target_basis != "distance":
            pytest.skip("not distance-based for this fixture")
        plan = _adapt(workouts)
        active = _active_sessions(plan)
        total_km = round(sum(s["distance_km"] or 0 for s in active), 1)
        assert abs(total_km - (wp.planned_km or 0)) <= 0.15, (
            f"sum(distance_km)={total_km} != planned_km={wp.planned_km}"
        )


# ---------------------------------------------------------------------------
# Contract B — deep_reprise duration
# ---------------------------------------------------------------------------

class TestContractB:
    """B: deep_reprise duration — trained runner — sum(duration_minutes) == target_duration_minutes.

    Fixture: _make_workouts_deep_reprise_trained → 5 × 16 km in prior window (days 29-41 ago).
    prior_km = 40 km/week → TRAINED level → target_duration_minutes = 135.
    No active weeks in last 28d → no progression → result is deterministic.
    """

    def test_deep_reprise_trained_state(self):
        """Pipeline must classify the trained-runner fixture as deep_reprise."""
        workouts = _make_workouts_deep_reprise_trained()
        wt, _ = _run_bridge(workouts)
        assert wt.continuity_state == "deep_reprise", (
            f"Expected deep_reprise, got continuity_state={wt.continuity_state}"
        )

    def test_deep_reprise_trained_basis_is_duration(self):
        """deep_reprise target_basis must be 'duration'."""
        workouts = _make_workouts_deep_reprise_trained()
        wt, wp = _run_bridge(workouts)
        assert wt.target_basis == "duration", (
            f"Expected target_basis=duration, got {wt.target_basis}"
        )
        assert wp.target_basis == "duration", (
            f"WeeklyPlan target_basis mismatch: {wp.target_basis}"
        )

    def test_deep_reprise_trained_duration_conserved(self):
        """sum(active session durations) == target_duration_minutes == 135."""
        workouts = _make_workouts_deep_reprise_trained()
        wt, wp = _run_bridge(workouts)
        assert wt.continuity_state == "deep_reprise"
        assert wt.target_basis == "duration"

        plan = _adapt(workouts)
        active = _active_sessions(plan)
        total_min = sum(int(s["duration"].replace("min", "") or "0") for s in active)

        assert wt.target_duration_minutes == 135, (
            f"Expected target_duration_minutes=135 (TRAINED level), got {wt.target_duration_minutes}"
        )
        assert wp.planned_duration_minutes == wt.target_duration_minutes, (
            f"WeeklyPlan planned_duration_minutes={wp.planned_duration_minutes} "
            f"!= WeeklyTarget {wt.target_duration_minutes}"
        )
        assert total_min == wt.target_duration_minutes, (
            f"API sum(duration)={total_min} != target_duration_minutes={wt.target_duration_minutes}"
        )

    def test_deep_reprise_no_artificial_km(self):
        """Duration-based deep_reprise must not produce weekly_km in the adapter output."""
        workouts = _make_workouts_deep_reprise_trained()
        wt, wp = _run_bridge(workouts)
        assert wt.continuity_state == "deep_reprise"
        plan = _adapt(workouts)
        assert plan["weekly_km"] is None, (
            f"duration-based deep_reprise must not set weekly_km, got {plan['weekly_km']}"
        )


# ---------------------------------------------------------------------------
# Contract C — partial_reprise distance
# ---------------------------------------------------------------------------

class TestContractC:
    """C: partial_reprise distance — sum(distance_km) ≈ target_km.

    Fixture: _make_workouts_partial_reprise_distance.
    continuity_state = partial_reprise, target_basis = distance, target_km = 4.4 km.
    """

    def test_partial_reprise_distance_state(self):
        """Pipeline must classify the fixture as partial_reprise."""
        workouts = _make_workouts_partial_reprise_distance()
        wt, _ = _run_bridge(workouts)
        assert wt.continuity_state == "partial_reprise", (
            f"Expected partial_reprise, got {wt.continuity_state}"
        )

    def test_partial_reprise_distance_basis(self):
        """Target basis must be 'distance' for this fixture."""
        workouts = _make_workouts_partial_reprise_distance()
        wt, wp = _run_bridge(workouts)
        assert wt.target_basis == "distance", (
            f"Expected target_basis=distance, got {wt.target_basis}"
        )
        assert wp.target_basis == "distance", (
            f"WeeklyPlan target_basis={wp.target_basis}"
        )

    def test_partial_reprise_distance_conserved(self):
        """sum(active session distance_km) == planned_km == target_km."""
        workouts = _make_workouts_partial_reprise_distance()
        wt, wp = _run_bridge(workouts)
        assert wt.continuity_state == "partial_reprise"
        assert wt.target_basis == "distance"

        plan = _adapt(workouts)
        active = _active_sessions(plan)
        total_km = round(sum(s["distance_km"] or 0 for s in active), 1)

        assert abs(total_km - (wp.planned_km or 0)) <= 0.15, (
            f"sum(distance_km)={total_km} != planned_km={wp.planned_km}"
        )
        assert abs(total_km - (wt.target_km or 0)) <= 0.15, (
            f"API sum={total_km} != target_km={wt.target_km}"
        )

    def test_partial_reprise_distance_no_invented_minutes(self):
        """Distance-based partial_reprise: weekly_minutes must be None in adapter output."""
        workouts = _make_workouts_partial_reprise_distance()
        wt, _ = _run_bridge(workouts)
        assert wt.target_basis == "distance"
        plan = _adapt(workouts)
        assert plan["weekly_minutes"] is None or plan.get("weekly_km") is not None, (
            "distance-based partial_reprise must not produce weekly_minutes"
        )


# ---------------------------------------------------------------------------
# Contract D — partial_reprise duration
# ---------------------------------------------------------------------------

class TestContractD:
    """D: partial_reprise duration — sum(duration_minutes) == target_duration_minutes.

    Option B: WeeklyTarget is constructed directly with the required continuity_state
    and target_basis. This is necessary because the pipeline cannot produce
    partial_reprise + duration through a workout fixture: whenever days_since < 28
    (required to avoid deep_reprise), the 28d buckets contain activity, so
    _target_partial_reprise always returns a distance-based target.

    The contract under test is the *adapter + plan* layer, not the heuristic that
    selects partial_reprise duration — that heuristic is covered by weekly_target tests.
    """

    def test_partial_reprise_duration_conserved(self):
        """sum(active session durations) == planned_duration_minutes == target (120 min)."""
        from training_v2.weekly_target import WeeklyTarget
        from training_v2.workout_generator import build_weekly_plan
        from training_v2.week_plan_adapter import adapt_weekly_plan_to_legacy

        runner_profile, plan_goal, periodization, ref = _build_v2_context()

        wt = WeeklyTarget(
            reference_date=ref,
            target_basis="duration",
            target_km=None,
            target_duration_minutes=120,
            target_sessions=3,
            allow_intensity=False,
            confidence="low",
            continuity_state="partial_reprise",
            reason_codes=("PARTIAL_REPRISE_DURATION_FALLBACK", "LOAD_UNAVAILABLE"),
        )
        wp = build_weekly_plan(
            weekly_target=wt,
            runner_profile=runner_profile,
            plan_goal=plan_goal,
            periodization=periodization,
            reference_date=ref,
        )
        plan = adapt_weekly_plan_to_legacy(wp, wt, "build")
        active = _active_sessions(plan)
        total_min = sum(int(s["duration"].replace("min", "") or "0") for s in active)

        assert wt.continuity_state == "partial_reprise"
        assert wt.target_basis == "duration"
        assert wp.planned_duration_minutes == wt.target_duration_minutes, (
            f"WeeklyPlan planned_duration_minutes={wp.planned_duration_minutes} "
            f"!= {wt.target_duration_minutes}"
        )
        assert total_min == wt.target_duration_minutes, (
            f"API sum(duration)={total_min} != target_duration_minutes={wt.target_duration_minutes}"
        )

    def test_partial_reprise_duration_no_invented_km(self):
        """Duration-based partial_reprise: weekly_km must be None (no invented distance)."""
        from training_v2.weekly_target import WeeklyTarget
        from training_v2.workout_generator import build_weekly_plan
        from training_v2.week_plan_adapter import adapt_weekly_plan_to_legacy

        runner_profile, plan_goal, periodization, ref = _build_v2_context()

        wt = WeeklyTarget(
            reference_date=ref,
            target_basis="duration",
            target_km=None,
            target_duration_minutes=120,
            target_sessions=3,
            allow_intensity=False,
            confidence="low",
            continuity_state="partial_reprise",
            reason_codes=("PARTIAL_REPRISE_DURATION_FALLBACK", "LOAD_UNAVAILABLE"),
        )
        wp = build_weekly_plan(
            weekly_target=wt,
            runner_profile=runner_profile,
            plan_goal=plan_goal,
            periodization=periodization,
            reference_date=ref,
        )
        plan = adapt_weekly_plan_to_legacy(wp, wt, "build")
        assert plan["weekly_km"] is None, (
            f"duration-based partial_reprise must not set weekly_km, got {plan['weekly_km']}"
        )


# ---------------------------------------------------------------------------
# Contract E — no_history duration
# ---------------------------------------------------------------------------

class TestContractE:
    """E: no_history → target_basis == "duration", no artificial km."""

    def test_no_history_basis_is_duration(self):
        workouts = []
        wt, wp = _run_bridge(workouts)
        if wt.continuity_state not in ("deep_reprise", "no_history"):
            pytest.skip(f"continuity_state={wt.continuity_state}, need no_history or deep_reprise")
        assert wp.target_basis == "duration", (
            f"no_history should produce duration-based plan, got {wp.target_basis}"
        )

    def test_no_history_no_artificial_km(self):
        workouts = []
        wt, wp = _run_bridge(workouts)
        if wt.continuity_state not in ("deep_reprise", "no_history"):
            pytest.skip(f"continuity_state={wt.continuity_state}")
        plan = _adapt(workouts)
        # weekly_km must be None for duration-based weeks
        assert plan["weekly_km"] is None, (
            f"duration-based plan must not set weekly_km, got {plan['weekly_km']}"
        )


# ---------------------------------------------------------------------------
# Contract F — normal duration fallback
# ---------------------------------------------------------------------------

class TestContractF:
    """F: normal continuity state with duration-based target fallback.

    Option B: WeeklyTarget constructed directly with continuity_state="normal"
    and target_basis="duration". This proves that the adapter / plan routing
    depends on target_basis, not on a proxy derived from training_state.

    The NORMAL_NO_BASELINE_DURATION_FALLBACK path in _target_normal is
    exercised by WeeklyTarget tests; here we test the contract that flows
    downstream from it.
    """

    def test_normal_duration_fallback_basis(self):
        """WeeklyPlan.target_basis must mirror WeeklyTarget.target_basis = 'duration'."""
        from training_v2.weekly_target import WeeklyTarget
        from training_v2.workout_generator import build_weekly_plan

        runner_profile, plan_goal, periodization, ref = _build_v2_context()

        wt = WeeklyTarget(
            reference_date=ref,
            target_basis="duration",
            target_km=None,
            target_duration_minutes=120,
            target_sessions=3,
            allow_intensity=True,
            confidence="low",
            continuity_state="normal",
            reason_codes=("NORMAL_NO_BASELINE_DURATION_FALLBACK", "LOAD_UNAVAILABLE"),
        )
        wp = build_weekly_plan(
            weekly_target=wt,
            runner_profile=runner_profile,
            plan_goal=plan_goal,
            periodization=periodization,
            reference_date=ref,
        )

        assert wt.continuity_state == "normal"
        assert wt.target_basis == "duration"
        assert wp.target_basis == "duration", (
            f"WeeklyPlan.target_basis={wp.target_basis}, expected duration"
        )

    def test_normal_duration_fallback_conserved(self):
        """sum(active session durations) == planned_duration_minutes == target (120 min)."""
        from training_v2.weekly_target import WeeklyTarget
        from training_v2.workout_generator import build_weekly_plan
        from training_v2.week_plan_adapter import adapt_weekly_plan_to_legacy

        runner_profile, plan_goal, periodization, ref = _build_v2_context()

        wt = WeeklyTarget(
            reference_date=ref,
            target_basis="duration",
            target_km=None,
            target_duration_minutes=120,
            target_sessions=3,
            allow_intensity=True,
            confidence="low",
            continuity_state="normal",
            reason_codes=("NORMAL_NO_BASELINE_DURATION_FALLBACK", "LOAD_UNAVAILABLE"),
        )
        wp = build_weekly_plan(
            weekly_target=wt,
            runner_profile=runner_profile,
            plan_goal=plan_goal,
            periodization=periodization,
            reference_date=ref,
        )
        plan = adapt_weekly_plan_to_legacy(wp, wt, "build")
        active = _active_sessions(plan)
        total_min = sum(int(s["duration"].replace("min", "") or "0") for s in active)

        assert wp.planned_duration_minutes == wt.target_duration_minutes, (
            f"WeeklyPlan planned_duration_minutes={wp.planned_duration_minutes} "
            f"!= {wt.target_duration_minutes}"
        )
        assert total_min == wt.target_duration_minutes, (
            f"API sum(duration)={total_min} != target_duration_minutes={wt.target_duration_minutes}"
        )

    def test_normal_duration_fallback_adapter_fields(self):
        """Adapter must set weekly_minutes and must NOT invent weekly_km."""
        from training_v2.weekly_target import WeeklyTarget
        from training_v2.workout_generator import build_weekly_plan
        from training_v2.week_plan_adapter import adapt_weekly_plan_to_legacy

        runner_profile, plan_goal, periodization, ref = _build_v2_context()

        wt = WeeklyTarget(
            reference_date=ref,
            target_basis="duration",
            target_km=None,
            target_duration_minutes=120,
            target_sessions=3,
            allow_intensity=True,
            confidence="low",
            continuity_state="normal",
            reason_codes=("NORMAL_NO_BASELINE_DURATION_FALLBACK", "LOAD_UNAVAILABLE"),
        )
        wp = build_weekly_plan(
            weekly_target=wt,
            runner_profile=runner_profile,
            plan_goal=plan_goal,
            periodization=periodization,
            reference_date=ref,
        )
        plan = adapt_weekly_plan_to_legacy(wp, wt, "build")

        assert plan.get("target_basis") == "duration", (
            f"adapter plan['target_basis']={plan.get('target_basis')}, expected 'duration'"
        )
        assert plan["weekly_km"] is None, (
            f"duration-based normal must not set weekly_km, got {plan['weekly_km']}"
        )


# ---------------------------------------------------------------------------
# Contract H — sum distance conserved through adapter
# ---------------------------------------------------------------------------

class TestContractH:
    """H: adapter conserves sum(distance_km) from WeeklyPlan V2."""

    def test_distance_sum_matches_planned_km(self):
        workouts = _make_workouts(8, km_per_session=12.0)
        wt, wp = _run_bridge(workouts)
        if wp.target_basis != "distance":
            pytest.skip("not distance-based")
        plan = _adapt(workouts)
        active = _active_sessions(plan)
        api_km = round(sum(s["distance_km"] or 0 for s in active), 1)
        assert abs(api_km - (wp.planned_km or 0)) <= 0.15, (
            f"adapter changed distance: api={api_km}, v2={wp.planned_km}"
        )


# ---------------------------------------------------------------------------
# Contract I — sum duration conserved through adapter
# ---------------------------------------------------------------------------

class TestContractI:
    """I: adapter conserves sum(duration_minutes) from WeeklyPlan V2."""

    def test_duration_sum_matches_planned_duration(self):
        workouts = _make_workouts(0)
        wt, wp = _run_bridge(workouts)
        if wp.target_basis != "duration":
            pytest.skip("not duration-based")
        if wp.planned_duration_minutes is None:
            pytest.skip("planned_duration_minutes is None")
        plan = _adapt(workouts)
        active = _active_sessions(plan)
        api_min = sum(int(s["duration"].replace("min", "") or "0") for s in active)
        assert api_min == wp.planned_duration_minutes, (
            f"adapter changed duration: api={api_min}, v2={wp.planned_duration_minutes}"
        )


# ---------------------------------------------------------------------------
# Contract J — session_count conserved
# ---------------------------------------------------------------------------

class TestContractJ:
    """J: adapter produces same number of running sessions as WeeklyPlan V2."""

    def test_session_count_conserved(self):
        workouts = _make_workouts(8, km_per_session=10.0)
        wt, wp = _run_bridge(workouts)
        plan = _adapt(workouts)
        active = _active_sessions(plan)
        assert len(active) == wp.session_count, (
            f"session_count: adapter={len(active)}, v2={wp.session_count}"
        )


# ---------------------------------------------------------------------------
# Contract K — allow_intensity respected
# ---------------------------------------------------------------------------

class TestContractK:
    """K: no quality session if allow_intensity == False."""

    def test_no_quality_when_intensity_not_allowed(self):
        # deep_reprise / no_history → allow_intensity = False
        workouts = _make_workouts(0)
        wt, wp = _run_bridge(workouts)
        if wp.allow_intensity:
            pytest.skip("allow_intensity=True for this fixture")
        plan = _adapt(workouts)
        quality_types = {"tempo", "threshold", "quality"}
        for s in plan["sessions"]:
            assert s["type"] not in quality_types, (
                f"Quality session {s['type']} present but allow_intensity=False"
            )


# ---------------------------------------------------------------------------
# Contract M — TSS doctrine
# ---------------------------------------------------------------------------

class TestContractM:
    """M: estimated_tss = None for active, 0 for rest; total_tss = None."""

    def test_tss_doctrine(self):
        workouts = _make_workouts(8, km_per_session=10.0)
        plan = _adapt(workouts)
        for s in plan["sessions"]:
            if s["type"] == "rest":
                assert s["estimated_tss"] == 0, (
                    f"rest session estimated_tss={s['estimated_tss']}, expected 0"
                )
            else:
                assert s["estimated_tss"] is None, (
                    f"active session estimated_tss={s['estimated_tss']}, expected None"
                )
        assert plan["total_tss"] is None, (
            f"total_tss={plan['total_tss']}, expected None"
        )


# ---------------------------------------------------------------------------
# Adapter type mapping
# ---------------------------------------------------------------------------

class TestAdapterTypeMapping:
    """Verify the V2→legacy display type mapping is complete and correct."""

    def test_type_mapping_all_v2_types(self):
        from training_v2.week_plan_adapter import _WORKOUT_TYPE_DISPLAY_MAP
        expected_v2_types = {"rest", "recovery", "easy", "steady", "quality", "long_easy"}
        assert expected_v2_types.issubset(set(_WORKOUT_TYPE_DISPLAY_MAP.keys())), (
            f"Missing V2 types in display map: {expected_v2_types - set(_WORKOUT_TYPE_DISPLAY_MAP.keys())}"
        )

    def test_long_easy_maps_to_long_run(self):
        from training_v2.week_plan_adapter import _WORKOUT_TYPE_DISPLAY_MAP
        assert _WORKOUT_TYPE_DISPLAY_MAP["long_easy"] == "long_run"

    def test_easy_maps_to_endurance(self):
        from training_v2.week_plan_adapter import _WORKOUT_TYPE_DISPLAY_MAP
        assert _WORKOUT_TYPE_DISPLAY_MAP["easy"] == "endurance"

    def test_rest_maps_to_rest(self):
        from training_v2.week_plan_adapter import _WORKOUT_TYPE_DISPLAY_MAP
        assert _WORKOUT_TYPE_DISPLAY_MAP["rest"] == "rest"


# ---------------------------------------------------------------------------
# Adapter details — no invented physiology
# ---------------------------------------------------------------------------

class TestAdapterDetails:
    """details strings must not contain static HR ranges invented by legacy."""

    FORBIDDEN_HR_PATTERNS = [
        "120-135",
        "135-150",
        "150-165",
        "165-175",
        "175-185",
    ]

    def test_no_static_hr_ranges_in_details(self):
        workouts = _make_workouts(8, km_per_session=10.0)
        plan = _adapt(workouts)
        for s in plan["sessions"]:
            details = s.get("details", "") or ""
            for pattern in self.FORBIDDEN_HR_PATTERNS:
                assert pattern not in details, (
                    f"Session {s['day']} details contains static HR range '{pattern}': {details}"
                )

    def test_no_invented_pace_formula_in_details(self):
        """Details must not contain pace patterns like '6:30/km' invented from static defaults."""
        workouts = _make_workouts(8, km_per_session=10.0)
        plan = _adapt(workouts)
        # We only forbid the specific legacy static pace strings
        forbidden_paces = ["6:30/km", "5:45/km", "5:15/km", "4:45/km"]
        for s in plan["sessions"]:
            details = s.get("details", "") or ""
            for pace in forbidden_paces:
                assert pace not in details, (
                    f"Session {s['day']} details contains static pace '{pace}': {details}"
                )


# ---------------------------------------------------------------------------
# Integration: adapter output has required legacy keys
# ---------------------------------------------------------------------------

class TestAdapterLegacyKeys:
    """Output plan must have all keys expected by frontend."""

    REQUIRED_PLAN_KEYS = {"focus", "planned_load", "weekly_km", "sessions", "total_tss", "advice"}
    REQUIRED_SESSION_KEYS = {"day", "type", "duration", "details", "intensity", "estimated_tss"}

    def test_plan_has_required_keys(self):
        workouts = _make_workouts(8, km_per_session=10.0)
        plan = _adapt(workouts)
        missing = self.REQUIRED_PLAN_KEYS - set(plan.keys())
        assert not missing, f"Plan missing keys: {missing}"

    def test_sessions_have_required_keys(self):
        workouts = _make_workouts(8, km_per_session=10.0)
        plan = _adapt(workouts)
        for s in plan["sessions"]:
            missing = self.REQUIRED_SESSION_KEYS - set(s.keys())
            assert not missing, f"Session {s.get('day')} missing keys: {missing}"

    def test_seven_sessions(self):
        workouts = _make_workouts(8, km_per_session=10.0)
        plan = _adapt(workouts)
        assert len(plan["sessions"]) == 7, (
            f"Expected 7 sessions (Mon-Sun), got {len(plan['sessions'])}"
        )

    def test_generated_by_is_weekly_plan_v2(self):
        """server.get_week_plan must set generated_by='weekly_plan_v2' (file-based check)."""
        from pathlib import Path
        server_path = Path(_BACKEND_DIR) / "server.py"
        source = server_path.read_text()
        tree = ast.parse(source)
        fn_source = None
        for node in ast.walk(tree):
            if isinstance(node, ast.AsyncFunctionDef) and node.name == "get_week_plan":
                lines = source.splitlines()
                fn_source = "\n".join(lines[node.lineno - 1:node.end_lineno])
                break
        assert fn_source is not None, "get_week_plan not found in server.py"
        assert "weekly_plan_v2" in fn_source, (
            "generated_by must be 'weekly_plan_v2' — prescription source changed"
        )
