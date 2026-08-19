"""PR151 — Tests for resolve_training_goal_context helper.

Tests the REAL helper, does NOT reimplement its logic.
"""
import sys
import os
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

# Ensure backend is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from training_v2.goal_context import resolve_training_goal_context, GoalContextError
from config.training_goals import GOAL_CONFIG


class TestResolveTrainingGoalContext:
    """Tests for resolve_training_goal_context pure helper."""

    def _cycle(self, **overrides):
        base = {
            "user_id": "u1",
            "goal": "SEMI",
            "start_date": datetime(2026, 1, 6, tzinfo=timezone.utc),
        }
        base.update(overrides)
        return base

    def _user_goal(self, **overrides):
        base = {
            "user_id": "u1",
            "event_name": "Paris Semi",
            "event_date": datetime(2026, 4, 5, tzinfo=timezone.utc),
        }
        base.update(overrides)
        return base

    # 1. goal valide
    def test_valid_goal(self):
        result = resolve_training_goal_context(
            training_cycle=self._cycle(),
            user_goal=self._user_goal(),
            goal_config=GOAL_CONFIG,
        )
        assert result["goal_type"] == "SEMI"
        assert result["cycle_weeks"] == 12

    # 2. start_date valide
    def test_start_date_valid(self):
        result = resolve_training_goal_context(
            training_cycle=self._cycle(start_date=date(2026, 2, 1)),
            user_goal=None,
            goal_config=GOAL_CONFIG,
        )
        assert result["start_date"] == date(2026, 2, 1)

    # 3. race_date valide
    def test_race_date_valid(self):
        result = resolve_training_goal_context(
            training_cycle=self._cycle(),
            user_goal=self._user_goal(),
            goal_config=GOAL_CONFIG,
        )
        assert result["race_date"] == date(2026, 4, 5)

    # 4. race_date absente
    def test_race_date_absent(self):
        result = resolve_training_goal_context(
            training_cycle=self._cycle(),
            user_goal=None,
            goal_config=GOAL_CONFIG,
        )
        assert result["race_date"] is None

    # 5. goal inconnu
    def test_unknown_goal_raises(self):
        with pytest.raises(GoalContextError, match="Unknown goal type"):
            resolve_training_goal_context(
                training_cycle=self._cycle(goal="TRIATHLON"),
                user_goal=None,
                goal_config=GOAL_CONFIG,
            )

    # 6. start_date absente
    def test_start_date_absent_raises(self):
        with pytest.raises(GoalContextError, match="no start_date"):
            resolve_training_goal_context(
                training_cycle=self._cycle(start_date=None),
                user_goal=None,
                goal_config=GOAL_CONFIG,
            )

    # 7. cycle_weeks valide (from config)
    def test_cycle_weeks_from_config(self):
        result = resolve_training_goal_context(
            training_cycle=self._cycle(goal="MARATHON"),
            user_goal=None,
            goal_config=GOAL_CONFIG,
        )
        assert result["cycle_weeks"] == 16

    # 8. cycle_weeks impossible (no cycle)
    def test_no_training_cycle_raises(self):
        with pytest.raises(GoalContextError, match="No training cycle"):
            resolve_training_goal_context(
                training_cycle=None,
                user_goal=self._user_goal(),
                goal_config=GOAL_CONFIG,
            )

    # 9. adjusted_weeks overrides config
    def test_adjusted_weeks_overrides_config(self):
        result = resolve_training_goal_context(
            training_cycle=self._cycle(adjusted_weeks=10),
            user_goal=None,
            goal_config=GOAL_CONFIG,
        )
        assert result["cycle_weeks"] == 10

    def test_adjusted_weeks_invalid_raises(self):
        with pytest.raises(GoalContextError, match="adjusted_weeks"):
            resolve_training_goal_context(
                training_cycle=self._cycle(adjusted_weeks=-1),
                user_goal=None,
                goal_config=GOAL_CONFIG,
            )

    # Ensure start_date as ISO string works
    def test_start_date_as_string(self):
        result = resolve_training_goal_context(
            training_cycle=self._cycle(start_date="2026-03-01T00:00:00Z"),
            user_goal=None,
            goal_config=GOAL_CONFIG,
        )
        assert result["start_date"] == date(2026, 3, 1)
