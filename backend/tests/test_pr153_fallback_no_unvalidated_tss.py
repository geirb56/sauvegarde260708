"""PR #153 — Verify that _generate_fallback_week_plan produces no estimated TSS
values not derived from a validated calculation.

Strategy: extract the function from server.py source via AST to avoid importing
the full server module (which has heavy dependencies).
"""
import ast
import re
import textwrap
from pathlib import Path

import pytest

SERVER_PATH = Path(__file__).resolve().parents[1] / "server.py"


def _get_function_source(func_name: str) -> str:
    """Extract a function's source from server.py using AST."""
    source = SERVER_PATH.read_text()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == func_name:
            return ast.get_source_segment(source, node)
    raise ValueError(f"Function {func_name} not found")


def _build_callable():
    """Build a callable _generate_fallback_week_plan with minimal stubs."""
    source = SERVER_PATH.read_text()

    # Extract get_phase_description if it exists, else stub it
    stub = textwrap.dedent("""
    DEFAULT_WEEKLY_KM = 30

    def get_phase_description(phase):
        return {"advice": "Keep it up!"}

    """)

    func_src = _get_function_source("_generate_fallback_week_plan")
    exec_globals = {}
    exec(stub + func_src, exec_globals)
    return exec_globals["_generate_fallback_week_plan"]


_generate_fallback_week_plan = _build_callable()


def _make_context(**overrides):
    base = {"weekly_km": 40}
    base.update(overrides)
    return base


class TestDistanceBasedFallbackNoUnvalidatedTSS:
    """Distance-based (km/pace) fallback must have estimated_tss=None and total_tss=None."""

    @pytest.mark.parametrize("phase", ["build", "deload", "taper", "intensification"])
    def test_all_estimated_tss_none(self, phase):
        plan = _generate_fallback_week_plan(_make_context(), phase, 100, "10k", 40.0)
        for s in plan["sessions"]:
            assert s["estimated_tss"] is None, f"{s['day']}: estimated_tss should be None, got {s['estimated_tss']}"

    @pytest.mark.parametrize("phase", ["build", "deload", "taper", "intensification"])
    def test_total_tss_none(self, phase):
        plan = _generate_fallback_week_plan(_make_context(), phase, 100, "10k", 40.0)
        assert plan["total_tss"] is None

    def test_none_is_not_zero(self):
        plan = _generate_fallback_week_plan(_make_context(), "build", 100, "10k", 40.0)
        assert plan["total_tss"] is not 0  # noqa: E711
        for s in plan["sessions"]:
            assert s["estimated_tss"] is not 0  # noqa: E711


class TestDurationBasedFallbackUnchanged:
    """Duration-based path must still produce estimated_tss=None, total_tss=None, target_km=None."""

    def test_duration_based_tss_none(self):
        ctx = {"target_duration_minutes": 120}
        plan = _generate_fallback_week_plan(ctx, "build", 100, "10k", None)
        assert plan["total_tss"] is None
        for s in plan["sessions"]:
            assert s["estimated_tss"] is None
            assert s.get("distance_km") is None


class TestNoNumericTSSHardcodesInSource:
    """Source code audit: no estimated_tss not derived from a validated calculation."""

    def test_no_numeric_estimated_tss_in_function(self):
        func_src = _get_function_source("_generate_fallback_week_plan")
        matches = re.findall(r'"estimated_tss"\s*:\s*(\d+)', func_src)
        assert matches == [], f"Found numeric estimated_tss hardcodes: {matches}"

    def test_no_sum_of_estimated_tss(self):
        func_src = _get_function_source("_generate_fallback_week_plan")
        assert 'sum(s["estimated_tss"]' not in func_src
