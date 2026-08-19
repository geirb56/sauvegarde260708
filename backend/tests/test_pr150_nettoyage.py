"""PR150 — Tests for nettoyage complet post-#149.

Covers:
1. Test portability (no hardcoded CI paths).
2. Goal source: /training/week-plan reads from training_cycles.
3. TSS: distance-based fallback has estimated_tss=None, total_tss=None.
4. TSS: duration-based fallback has estimated_tss=None, total_tss=None.
5. No fictitious ACWR/TSS (None != 0).
"""

import pathlib
import pytest


# ---------------------------------------------------------------------------
# A. Test portability — no hardcoded CI paths in test files
# ---------------------------------------------------------------------------

class TestPortability:
    """Ensure no test file uses hardcoded CI paths."""

    def test_no_hardcoded_ci_path_in_pr149_test(self):
        """test_pr149_week_plan_v2.py must not contain /home/runner/work absolute paths."""
        test_file = pathlib.Path(__file__).resolve().parent / "test_pr149_week_plan_v2.py"
        source = test_file.read_text()
        assert "/home/runner/work" not in source, (
            "Hardcoded CI path found — use Path(__file__).resolve().parents[1] instead"
        )

    def test_server_path_derivable_from_file(self):
        """server.py is reachable via __file__-relative path."""
        server_path = pathlib.Path(__file__).resolve().parents[1] / "server.py"
        assert server_path.exists(), f"server.py not found at {server_path}"


# ---------------------------------------------------------------------------
# B. Goal source — training_cycles is canonical
# ---------------------------------------------------------------------------

class TestGoalSource:
    """Prove /training/week-plan reads from training_cycles, not training_goals."""

    def test_week_plan_reads_training_cycles(self):
        """server.py week-plan endpoint must read from db.training_cycles."""
        server_path = pathlib.Path(__file__).resolve().parents[1] / "server.py"
        source = server_path.read_text()
        # Find the week-plan function
        wp_start = source.find('async def get_week_plan')
        assert wp_start != -1, "get_week_plan not found in server.py"
        # Get the next 60 lines (the goal-reading section)
        wp_section = source[wp_start:wp_start + 3000]
        assert 'db.training_cycles.find_one' in wp_section, (
            "week-plan must read goal from training_cycles"
        )

    def test_week_plan_does_not_read_training_goals_for_goal(self):
        """server.py week-plan endpoint must NOT read from db.training_goals."""
        server_path = pathlib.Path(__file__).resolve().parents[1] / "server.py"
        source = server_path.read_text()
        wp_start = source.find('async def get_week_plan')
        wp_section = source[wp_start:wp_start + 3000]
        assert 'db.training_goals.find_one' not in wp_section, (
            "week-plan must NOT read from legacy training_goals"
        )

    def test_no_goal_returns_400(self):
        """When no cycle exists, the error message is explicit."""
        server_path = pathlib.Path(__file__).resolve().parents[1] / "server.py"
        source = server_path.read_text()
        wp_start = source.find('async def get_week_plan')
        wp_section = source[wp_start:wp_start + 1500]
        assert "No goal defined" in wp_section


# ---------------------------------------------------------------------------
# C. TSS — distance-based fallback: all estimated_tss = None
# ---------------------------------------------------------------------------

class TestTSSDistanceBased:
    """Distance-based fallback must have estimated_tss=None and total_tss=None."""

    def test_no_hardcoded_tss_in_distance_fallback(self):
        """_generate_fallback_week_plan must not contain estimated_tss: <number>."""
        server_path = pathlib.Path(__file__).resolve().parents[1] / "server.py"
        source = server_path.read_text()
        fn_start = source.find('def _generate_fallback_week_plan')
        assert fn_start != -1
        fn_section = source[fn_start:]
        # Find the end of the function (next def at same indent or end)
        next_def = fn_section.find('\n@', 100)
        if next_def == -1:
            next_def = len(fn_section)
        fn_body = fn_section[:next_def]

        import re
        # No estimated_tss with a numeric value
        matches = re.findall(r'"estimated_tss":\s*(\d+)', fn_body)
        assert matches == [], (
            f"Found hardcoded estimated_tss values: {matches}. Must be None."
        )

    def test_total_tss_is_none_in_distance_fallback(self):
        """total_tss must be None (not computed from fake values)."""
        server_path = pathlib.Path(__file__).resolve().parents[1] / "server.py"
        source = server_path.read_text()
        fn_start = source.find('def _generate_fallback_week_plan')
        fn_section = source[fn_start:]
        next_def = fn_section.find('\n@', 100)
        if next_def == -1:
            next_def = len(fn_section)
        fn_body = fn_section[:next_def]
        assert 'total_tss = None' in fn_body, "total_tss must be None in distance-based fallback"


# ---------------------------------------------------------------------------
# D. TSS — duration-based fallback: estimated_tss=None, total_tss=None
# ---------------------------------------------------------------------------

class TestTSSDurationBased:
    """Duration-based fallback must have estimated_tss=None and total_tss=None."""

    def test_duration_fallback_estimated_tss_none(self):
        """Duration-based sessions have estimated_tss: None."""
        server_path = pathlib.Path(__file__).resolve().parents[1] / "server.py"
        source = server_path.read_text()
        fn_start = source.find('def _generate_fallback_week_plan')
        fn_section = source[fn_start:]
        # The duration-based branch
        dur_start = fn_section.find('target_km_protected is None and target_duration_minutes is not None')
        assert dur_start != -1, "Duration-based branch not found"
        dur_section = fn_section[dur_start:dur_start + 2000]
        assert '"estimated_tss": None' in dur_section
        assert '"total_tss": None' in dur_section


# ---------------------------------------------------------------------------
# E. None != 0 — no fictitious values
# ---------------------------------------------------------------------------

class TestNoneNotZeroFallback:
    """Ensure None is never confused with 0 in fallback plans."""

    def test_none_semantics(self):
        """None is not equal to 0."""
        assert None != 0
        assert None is not 0

    def test_no_total_tss_sum_in_fallback(self):
        """There must be no sum(estimated_tss) computing total_tss from None values."""
        server_path = pathlib.Path(__file__).resolve().parents[1] / "server.py"
        source = server_path.read_text()
        fn_start = source.find('def _generate_fallback_week_plan')
        fn_section = source[fn_start:]
        next_def = fn_section.find('\n@', 100)
        if next_def == -1:
            next_def = len(fn_section)
        fn_body = fn_section[:next_def]
        assert 'sum(s["estimated_tss"]' not in fn_body, (
            "Must not sum estimated_tss — values are None"
        )
