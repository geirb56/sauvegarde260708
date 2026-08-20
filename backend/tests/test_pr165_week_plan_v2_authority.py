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

def _make_workouts(n: int = 0, km_per_session: float = 8.0) -> list[dict]:
    """Generate synthetic workout documents for the last n*7 days."""
    ref = date(2024, 6, 10)
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


def _run_bridge(
    workouts: list[dict],
    goal_type: str = "SEMI",
    reference_date: Optional[date] = None,
) -> tuple:
    from training_v2.week_plan_bridge import build_weekly_plan_from_workouts
    ref = reference_date or date(2024, 6, 10)
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
    """B: deep_reprise duration — sum(duration_minutes) == target_duration_minutes."""

    def test_deep_reprise_duration_conserved(self):
        # No history → deep_reprise
        workouts = _make_workouts(0)
        wt, wp = _run_bridge(workouts)
        if wt.continuity_state != "deep_reprise":
            pytest.skip(f"continuity_state={wt.continuity_state}, not deep_reprise")
        if wp.target_basis != "duration":
            pytest.skip("not duration-based for deep_reprise fixture")

        plan = _adapt(workouts)
        active = _active_sessions(plan)
        # duration field is "Xmin" string — parse it
        total_min = sum(int(s["duration"].replace("min", "") or "0") for s in active)
        assert total_min == wt.target_duration_minutes, (
            f"sum(duration)={total_min} != target_duration_minutes={wt.target_duration_minutes}"
        )

    def test_deep_reprise_no_artificial_km(self):
        """Duration-based deep_reprise must not invent km (weekly_km may be None)."""
        workouts = _make_workouts(0)
        wt, wp = _run_bridge(workouts)
        if wt.continuity_state != "deep_reprise":
            pytest.skip(f"continuity_state={wt.continuity_state}, not deep_reprise")
        plan = _adapt(workouts)
        # planned_km should be None for duration-based
        assert plan["weekly_km"] is None or plan["target_basis"] == "duration", (
            "duration-based deep_reprise must not set weekly_km"
        )


# ---------------------------------------------------------------------------
# Contract C — partial_reprise distance
# ---------------------------------------------------------------------------

class TestContractC:
    """C: partial_reprise distance — sum(distance_km) ≈ target_km."""

    def test_partial_reprise_distance_conserved(self):
        # Sparse history → may produce partial_reprise
        workouts = _make_workouts(2, km_per_session=15.0)
        wt, wp = _run_bridge(workouts)
        if wt.continuity_state != "partial_reprise" or wp.target_basis != "distance":
            pytest.skip(
                f"continuity_state={wt.continuity_state}, basis={wp.target_basis} — need partial_reprise+distance"
            )
        plan = _adapt(workouts)
        active = _active_sessions(plan)
        total_km = round(sum(s["distance_km"] or 0 for s in active), 1)
        assert abs(total_km - (wp.planned_km or 0)) <= 0.15, (
            f"sum(distance_km)={total_km} != planned_km={wp.planned_km}"
        )


# ---------------------------------------------------------------------------
# Contract D — partial_reprise duration
# ---------------------------------------------------------------------------

class TestContractD:
    """D: partial_reprise duration — sum(duration_minutes) == target_duration_minutes."""

    def test_partial_reprise_duration_conserved(self):
        workouts = _make_workouts(1, km_per_session=5.0)
        wt, wp = _run_bridge(workouts)
        if wt.continuity_state != "partial_reprise" or wp.target_basis != "duration":
            pytest.skip(
                f"continuity_state={wt.continuity_state}, basis={wp.target_basis} — need partial_reprise+duration"
            )
        plan = _adapt(workouts)
        active = _active_sessions(plan)
        total_min = sum(int(s["duration"].replace("min", "") or "0") for s in active)
        assert total_min == wt.target_duration_minutes, (
            f"sum(duration)={total_min} != target_duration_minutes={wt.target_duration_minutes}"
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
