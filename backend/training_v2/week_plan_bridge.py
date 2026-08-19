"""PR149 — Bridge: build WeeklyTarget V2 from raw workout documents.

This module provides a thin orchestration entry-point for endpoints that
need a V2 WeeklyTarget without owning the full V2 rendering pipeline.

Design rules:
- PURE orchestration: no MongoDB, no HTTP, no LLM.
- Delegates all domain logic to existing V2 modules.
- Uses the canonical DomainActivity adapter (to_domain_activity) from domain_activity.py.
- Does NOT duplicate formulas — only wires existing builders.
- reference_date is MANDATORY — no implicit datetime.now().
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from .domain_activity import to_domain_activity
from .plan_goal import GoalType, build_plan_goal
from .periodization import build_periodization
from .runner_profile import build_runner_profile
from .training_history import build_training_history
from .training_load import build_training_load
from .training_state import build_training_state
from .weekly_target import WeeklyTarget, build_weekly_target


# Closed mapping: legacy goal strings → GoalType V2.
# Unknown goals are NOT silently mapped to a default.
_GOAL_MAP: dict[str, GoalType] = {
    "10K": GoalType.ten_k,
    "SEMI": GoalType.half_marathon,
    "HALF_MARATHON": GoalType.half_marathon,
    "MARATHON": GoalType.marathon,
    "5K": GoalType.five_k,
    "ULTRA": GoalType.ultra,
    "MAINTENANCE": GoalType.maintenance,
}


class UnknownGoalTypeError(ValueError):
    """Raised when a goal string cannot be mapped to a known GoalType."""
    pass


def _normalize_workout_to_domain_fields(workout: dict) -> dict:
    """Normalize a raw db.workouts document to DomainActivity-compatible field names.

    This is the provider adapter layer: Mongo/Garmin → DomainActivity field contract.
    It does NOT duplicate domain logic — only maps field names/units.

    Mapping:
      distance_km → distance_m (km * 1000)
      duration_minutes → duration_s (min * 60)
      duration_seconds / elapsed_time → duration_s
      avg_heart_rate → average_hr
      max_heart_rate → max_hr
      start_date_local / date → start_time (if start_time absent)
    """
    out = dict(workout)  # shallow copy

    # Distance: distance_km → distance_m
    if "distance_m" not in out:
        dist_km = out.get("distance_km")
        if isinstance(dist_km, (int, float)) and not isinstance(dist_km, bool) and dist_km > 0:
            out["distance_m"] = float(dist_km) * 1000.0

    # Duration: duration_minutes → duration_s
    if "duration_s" not in out:
        for key in ("duration_seconds", "elapsed_time"):
            v = out.get(key)
            if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
                out["duration_s"] = float(v)
                break
        if "duration_s" not in out:
            dur_min = out.get("duration_minutes")
            if isinstance(dur_min, (int, float)) and not isinstance(dur_min, bool) and dur_min > 0:
                out["duration_s"] = float(dur_min) * 60.0

    # Heart rate aliases
    if "average_hr" not in out and "avg_heart_rate" in out:
        out["average_hr"] = out["avg_heart_rate"]
    if "max_hr" not in out and "max_heart_rate" in out:
        out["max_hr"] = out["max_heart_rate"]

    # Start time: ensure start_time is present
    if "start_time" not in out or out["start_time"] is None:
        out["start_time"] = out.get("start_date_local") or out.get("date")

    return out


def build_weekly_target_from_workouts(
    *,
    workouts: List[dict],
    goal_type: str,
    race_date: Optional[date] = None,
    cycle_start_date: Optional[date] = None,
    reference_date: date,
    user_profile: Optional[dict] = None,
) -> WeeklyTarget:
    """Build a WeeklyTarget V2 from raw workout documents and goal info.

    Parameters
    ----------
    workouts : list of raw db.workouts documents (up to 90 days).
    goal_type : legacy goal string (e.g. "SEMI", "MARATHON", "10K").
    race_date : target race date, if known.
    cycle_start_date : start of the training cycle.
    reference_date : anchor date — MANDATORY, no implicit today.
    user_profile : optional user_profiles document for RunnerProfile enrichment.

    Raises
    ------
    UnknownGoalTypeError
        If goal_type does not map to a known GoalType.
    """
    # BLOCKER 3: Unknown goal → explicit error, never silent half_marathon.
    mapped_goal = _GOAL_MAP.get(goal_type.upper() if goal_type else "")
    if mapped_goal is None:
        raise UnknownGoalTypeError(
            f"Unknown goal_type '{goal_type}' — cannot map to V2 GoalType. "
            f"Valid values: {sorted(_GOAL_MAP.keys())}"
        )

    # BLOCKER 4: Use canonical DomainActivity adapter (to_domain_activity).
    # Pre-normalize db.workouts fields to match DomainActivity's expected keys.
    # This is the provider-neutral adapter layer: Mongo/Garmin → DomainActivity.
    activities = [to_domain_activity(_normalize_workout_to_domain_fields(w)) for w in workouts]

    # Build V2 chain
    training_history = build_training_history(activities, reference_date)
    training_load = build_training_load(activities, reference_date)
    runner_profile = build_runner_profile(
        training_history=training_history,
        training_load=training_load,
        user_profile=user_profile,
        capabilities=None,
        physiological_metrics=None,
        reference_date=reference_date,
    )
    training_state = build_training_state(
        training_history=training_history,
        training_load=training_load,
        runner_profile=runner_profile,
        reference_date=reference_date,
    )

    plan_goal = build_plan_goal(
        goal_type=mapped_goal,
        race_date=race_date,
        created_from="user",
    )

    # Periodization
    if race_date and race_date > reference_date:
        periodization = build_periodization(
            plan_goal=plan_goal,
            reference_date=reference_date,
            race_plan_start_date=cycle_start_date,
        )
    else:
        periodization = build_periodization(
            plan_goal=plan_goal,
            reference_date=reference_date,
            cycle_anchor_date=cycle_start_date or reference_date,
        )

    # Build target
    weekly_target = build_weekly_target(
        runner_profile=runner_profile,
        training_history=training_history,
        training_state=training_state,
        plan_goal=plan_goal,
        periodization=periodization,
        reference_date=reference_date,
    )

    return weekly_target
