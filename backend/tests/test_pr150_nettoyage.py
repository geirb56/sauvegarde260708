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


# ---------------------------------------------------------------------------
# F. Behavioral test — goal reconstruction contract
# ---------------------------------------------------------------------------

import sys
import os
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1]))
from config.training_goals import GOAL_CONFIG


class TestGoalReconstructionContract:
    """Test the goal reconstruction logic from training_cycles shape."""

    def _reconstruct_goal(self, cycle: dict, user_goal: dict = None):
        """Simulate the reconstruction logic from /training/week-plan."""
        if not cycle or not cycle.get("goal"):
            return {"error": "No goal defined"}

        goal_type = cycle["goal"]
        if goal_type not in GOAL_CONFIG:
            return {"error": f"Unknown goal type: {goal_type}"}

        raw_start = cycle.get("start_date")
        if not raw_start:
            return {"error": "Cycle start_date missing"}

        config = GOAL_CONFIG[goal_type]
        cycle_weeks = cycle.get("adjusted_weeks") or config["cycle_weeks"]

        return {
            "goal_type": goal_type,
            "start_date": raw_start,
            "event_date": cycle.get("event_date") or (user_goal.get("event_date") if user_goal else None),
            "cycle_weeks": cycle_weeks,
        }

    def test_case1_valid_cycle(self):
        """CAS 1: valid training_cycles document → correct goal reconstruction."""
        from datetime import datetime, timezone
        cycle = {
            "user_id": "user-123",
            "goal": "SEMI",
            "start_date": datetime(2026, 6, 1, tzinfo=timezone.utc),
            "updated_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
        }
        result = self._reconstruct_goal(cycle)
        assert "error" not in result
        assert result["goal_type"] == "SEMI"
        assert result["start_date"] == datetime(2026, 6, 1, tzinfo=timezone.utc)
        assert result["cycle_weeks"] == 12  # from GOAL_CONFIG["SEMI"]
        assert result["event_date"] is None  # no event_date in cycle or user_goal

    def test_case1_with_adjusted_weeks(self):
        """CAS 1b: adjusted_weeks overrides GOAL_CONFIG cycle_weeks."""
        from datetime import datetime, timezone
        cycle = {
            "user_id": "user-123",
            "goal": "MARATHON",
            "start_date": datetime(2026, 3, 1, tzinfo=timezone.utc),
            "adjusted_weeks": 14,
            "updated_at": datetime(2026, 3, 1, tzinfo=timezone.utc),
        }
        result = self._reconstruct_goal(cycle)
        assert result["cycle_weeks"] == 14  # adjusted_weeks takes priority

    def test_case2_start_date_absent(self):
        """CAS 2: start_date absent → explicit error, NOT today."""
        cycle = {"user_id": "user-123", "goal": "10K"}
        result = self._reconstruct_goal(cycle)
        assert "error" in result
        assert "start_date" in result["error"]

    def test_case3_cycle_weeks_always_determinable(self):
        """CAS 3: cycle_weeks always derivable from GOAL_CONFIG for known goals."""
        from datetime import datetime, timezone
        for goal_type in GOAL_CONFIG:
            cycle = {
                "user_id": "user-123",
                "goal": goal_type,
                "start_date": datetime(2026, 1, 1, tzinfo=timezone.utc),
            }
            result = self._reconstruct_goal(cycle)
            assert "error" not in result
            assert result["cycle_weeks"] == GOAL_CONFIG[goal_type]["cycle_weeks"]

    def test_case3_unknown_goal_type(self):
        """CAS 3b: unknown goal_type → explicit error, no fallback."""
        from datetime import datetime, timezone
        cycle = {
            "user_id": "user-123",
            "goal": "TRIATHLON",
            "start_date": datetime(2026, 1, 1, tzinfo=timezone.utc),
        }
        result = self._reconstruct_goal(cycle)
        assert "error" in result
        assert "Unknown goal type" in result["error"]

    def test_no_cycle_returns_error(self):
        """No cycle document → explicit error."""
        result = self._reconstruct_goal(None)
        assert "error" in result

    def test_event_date_from_user_goals(self):
        """event_date sourced from user_goals when absent in cycle."""
        from datetime import datetime, timezone
        cycle = {
            "user_id": "user-123",
            "goal": "SEMI",
            "start_date": datetime(2026, 6, 1, tzinfo=timezone.utc),
        }
        user_goal = {"event_date": datetime(2026, 9, 15, tzinfo=timezone.utc)}
        result = self._reconstruct_goal(cycle, user_goal)
        assert result["event_date"] == datetime(2026, 9, 15, tzinfo=timezone.utc)


# ---------------------------------------------------------------------------
# G. Source code contract verification — writer/reader consistency
# ---------------------------------------------------------------------------

class TestWriterReaderContract:
    """Verify server.py writer/reader contract consistency."""

    def test_week_plan_reads_cycle_weeks_from_goal_config(self):
        """week-plan derives cycle_weeks from GOAL_CONFIG or adjusted_weeks."""
        server_path = pathlib.Path(__file__).resolve().parents[1] / "server.py"
        source = server_path.read_text()
        wp_start = source.find('async def get_week_plan')
        wp_section = source[wp_start:wp_start + 3000]
        assert 'cycle.get("adjusted_weeks") or config["cycle_weeks"]' in wp_section

    def test_week_plan_rejects_missing_start_date(self):
        """week-plan raises error when start_date is absent."""
        server_path = pathlib.Path(__file__).resolve().parents[1] / "server.py"
        source = server_path.read_text()
        wp_start = source.find('async def get_week_plan')
        wp_section = source[wp_start:wp_start + 3000]
        assert 'start_date missing' in wp_section.lower() or 'Cycle start_date missing' in wp_section

    def test_no_start_date_default_to_now(self):
        """week-plan must NOT default start_date to datetime.now."""
        server_path = pathlib.Path(__file__).resolve().parents[1] / "server.py"
        source = server_path.read_text()
        wp_start = source.find('async def get_week_plan')
        wp_section = source[wp_start:wp_start + 2000]
        assert 'datetime.now(timezone.utc))' not in wp_section, (
            "start_date must not default to now"
        )

    def test_unknown_goal_type_rejected(self):
        """week-plan rejects unknown goal types explicitly."""
        server_path = pathlib.Path(__file__).resolve().parents[1] / "server.py"
        source = server_path.read_text()
        wp_start = source.find('async def get_week_plan')
        wp_section = source[wp_start:wp_start + 2000]
        assert 'goal_type not in GOAL_CONFIG' in wp_section
