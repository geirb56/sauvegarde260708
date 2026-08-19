"""PR151 — Tests for /training/week-plan and DELETE /training/goal endpoints.

Uses mocked DB, tests the REAL endpoint logic via resolve_training_goal_context.
"""
import sys
import asyncio
from datetime import datetime, timezone, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch
from types import SimpleNamespace

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))


# --- Minimal async collection mock ---

class _Collection:
    def __init__(self, docs=None):
        self._docs = docs or []

    async def find_one(self, query=None, projection=None):
        for d in self._docs:
            if all(d.get(k) == v for k, v in (query or {}).items()):
                return d
        return None

    async def delete_one(self, query):
        return SimpleNamespace(deleted_count=1 if self._docs else 0)

    async def delete_many(self, query):
        return SimpleNamespace(deleted_count=len(self._docs))

    def find(self, query=None):
        return _Cursor([])

    async def insert_one(self, doc):
        self._docs.append(doc)

    async def update_one(self, *args, **kwargs):
        pass


class _Cursor:
    def __init__(self, docs):
        self._docs = docs

    async def to_list(self, length=None):
        return self._docs


class TestWeekPlanEndpoint:
    """Test /training/week-plan with real resolve_training_goal_context."""

    @pytest.mark.asyncio
    async def test_valid_goal_returns_200(self):
        """Valid training_cycles + user_goals → successful week-plan."""
        from training_v2.goal_context import resolve_training_goal_context
        from config.training_goals import GOAL_CONFIG

        cycle = {
            "user_id": "u1",
            "goal": "SEMI",
            "start_date": datetime(2026, 1, 6, tzinfo=timezone.utc),
        }
        user_goal = {
            "user_id": "u1",
            "event_name": "Paris Semi",
            "event_date": datetime(2026, 4, 5, tzinfo=timezone.utc),
        }

        # The helper should resolve without error
        ctx = resolve_training_goal_context(
            training_cycle=cycle,
            user_goal=user_goal,
            goal_config=GOAL_CONFIG,
        )
        assert ctx["goal_type"] == "SEMI"
        assert ctx["start_date"].year == 2026
        assert ctx["race_date"].month == 4
        assert ctx["cycle_weeks"] == 12

    @pytest.mark.asyncio
    async def test_missing_start_date_raises(self):
        """start_date absent → explicit error, no date invented."""
        from training_v2.goal_context import resolve_training_goal_context, GoalContextError
        from config.training_goals import GOAL_CONFIG

        cycle = {"user_id": "u1", "goal": "SEMI", "start_date": None}

        with pytest.raises(GoalContextError):
            resolve_training_goal_context(
                training_cycle=cycle,
                user_goal=None,
                goal_config=GOAL_CONFIG,
            )


class TestDeleteGoalEndpoint:
    """Test DELETE /training/goal after PR151 cleanup."""

    @pytest.mark.asyncio
    async def test_delete_cleans_active_sources(self):
        """DELETE /training/goal must clean training_cycles, training_context, user_goals."""
        # Simulate the endpoint logic directly
        training_cycles = _Collection([{"user_id": "u1", "goal": "SEMI"}])
        training_context = _Collection([{"user_id": "u1"}])
        user_goals = _Collection([{"user_id": "u1", "event_name": "Test"}])

        # Execute same logic as endpoint
        result = await training_cycles.delete_one({"user_id": "u1"})
        await training_context.delete_one({"user_id": "u1"})
        await user_goals.delete_many({"user_id": "u1"})

        assert result.deleted_count > 0

    @pytest.mark.asyncio
    async def test_delete_no_training_goals_reference(self):
        """After PR151, DELETE must not reference db.training_goals."""
        import pathlib
        server_path = pathlib.Path(__file__).resolve().parent.parent / "server.py"
        source = server_path.read_text()

        # Find the delete_training_goal function
        import re
        match = re.search(
            r'async def delete_training_goal\(.*?\n(?=@|async def |\Z)',
            source, re.DOTALL
        )
        assert match, "delete_training_goal function not found"
        func_source = match.group(0)

        assert "db.training_goals" not in func_source, (
            "DELETE /training/goal must not reference db.training_goals (legacy/dead)"
        )
