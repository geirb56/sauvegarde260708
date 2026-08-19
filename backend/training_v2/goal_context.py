"""PR151 — Pure helper: resolve training goal context for /training/week-plan.

This module resolves the canonical goal context from already-read documents.
It performs NO I/O, has no implicit datetime.now(), and produces an explicit
dict suitable for the week-plan endpoint.

Canonical sources:
- db.training_cycles → goal (goal_type), start_date, adjusted_weeks
- db.user_goals → event_name, event_date
- GOAL_CONFIG → cycle_weeks (default if adjusted_weeks absent)
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Optional


class GoalContextError(ValueError):
    """Raised when goal context cannot be resolved due to missing/invalid data."""
    pass


def resolve_training_goal_context(
    *,
    training_cycle: Optional[dict],
    user_goal: Optional[dict],
    goal_config: dict,
) -> dict:
    """Resolve canonical training goal context from pre-read documents.

    Args:
        training_cycle: Document from db.training_cycles (or None).
        user_goal: Document from db.user_goals (or None).
        goal_config: The GOAL_CONFIG dict (keyed by goal type string).

    Returns:
        Dict with keys: goal_type, start_date, race_date, event_name, cycle_weeks.

    Raises:
        GoalContextError: If required data is missing or invalid.
    """
    if not training_cycle:
        raise GoalContextError("No training cycle found. Use /api/training/set-goal first.")

    # --- goal_type ---
    goal_type = training_cycle.get("goal")
    if not goal_type:
        raise GoalContextError("Training cycle has no goal defined.")
    goal_type = goal_type.upper()

    if goal_type not in goal_config:
        raise GoalContextError(
            f"Unknown goal type: {goal_type!r}. "
            f"Valid types: {list(goal_config.keys())}"
        )

    # --- start_date ---
    raw_start = training_cycle.get("start_date")
    if raw_start is None:
        raise GoalContextError(
            "Training cycle has no start_date. Cannot determine cycle position."
        )
    start_date = _normalize_date(raw_start, "start_date")

    # --- cycle_weeks ---
    # adjusted_weeks (from readiness engine) takes priority if present.
    adjusted_weeks = training_cycle.get("adjusted_weeks")
    config_weeks = goal_config[goal_type]["cycle_weeks"]

    if adjusted_weeks is not None:
        try:
            cycle_weeks = int(adjusted_weeks)
            if cycle_weeks <= 0:
                raise GoalContextError(
                    f"adjusted_weeks must be positive, got {adjusted_weeks}"
                )
        except (TypeError, ValueError):
            raise GoalContextError(
                f"adjusted_weeks is not a valid integer: {adjusted_weeks!r}"
            )
    else:
        cycle_weeks = config_weeks

    # --- race_date (optional) ---
    race_date: Optional[date] = None
    event_name: Optional[str] = None

    if user_goal:
        raw_event = user_goal.get("event_date")
        if raw_event is not None:
            race_date = _normalize_date(raw_event, "event_date")
        event_name = user_goal.get("event_name")

    return {
        "goal_type": goal_type,
        "start_date": start_date,
        "race_date": race_date,
        "event_name": event_name,
        "cycle_weeks": cycle_weeks,
    }


def _normalize_date(value: Any, field_name: str) -> date:
    """Convert various date representations to a date object."""
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(
                value.replace("Z", "+00:00").split("T")[0]
            ).date()
        except (ValueError, TypeError):
            pass
    raise GoalContextError(
        f"Cannot parse {field_name}: {value!r}"
    )
