"""PR149 — Bridge: build WeeklyTarget V2 from raw workout documents.

This module provides a thin orchestration entry-point for endpoints that
need a V2 WeeklyTarget without owning the full V2 rendering pipeline.

Design rules:
- PURE orchestration: no MongoDB, no HTTP, no LLM.
- Delegates all domain logic to existing V2 modules.
- Reuses _to_domain_activity_from_workout pattern from coach_service.
- Does NOT duplicate formulas — only wires existing builders.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import List, Optional

from .plan_goal import GoalType, build_plan_goal
from .periodization import build_periodization
from .runner_profile import build_runner_profile
from .training_history import build_training_history
from .training_load import build_training_load
from .training_state import build_training_state
from .weekly_target import WeeklyTarget, build_weekly_target


def _to_domain_activity(workout: dict) -> dict:
    """Convert a raw db.workouts document to a DomainActivity-compatible dict.

    Mirrors coach_service._to_domain_activity_from_workout exactly.
    """
    # Distance
    dist_km = 0.0
    for key in ("distance_km", "distance"):
        v = workout.get(key)
        if isinstance(v, (int, float)) and v > 0:
            dist_km = float(v)
            break

    # Duration
    duration_s = 0.0
    for key in ("duration_seconds", "duration_s", "elapsed_time"):
        v = workout.get(key)
        if isinstance(v, (int, float)) and v > 0:
            duration_s = float(v)
            break
    if duration_s == 0:
        dur_min = workout.get("duration_minutes")
        if isinstance(dur_min, (int, float)) and dur_min > 0:
            duration_s = float(dur_min) * 60.0

    # Start time
    raw_start = workout.get("start_time") or workout.get("start_date_local") or workout.get("date")
    if isinstance(raw_start, datetime):
        start_time = raw_start.strftime("%Y-%m-%dT%H:%M:%S")
    elif isinstance(raw_start, str):
        start_time = raw_start.split(".")[0]
    else:
        start_time = raw_start

    # Activity type
    activity_type_raw = (workout.get("activity_type") or workout.get("type") or "").lower()
    is_running = activity_type_raw in ("running", "run", "trail_running", "treadmill_running")

    def _pos_float(v):
        if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0:
            return float(v)
        return None

    return {
        "activity_type": "running" if is_running else "other",
        "start_time": start_time,
        "distance_m": dist_km * 1000.0 if dist_km > 0 else None,
        "duration_s": duration_s if duration_s > 0 else None,
        "moderate_intensity_minutes": _pos_float(workout.get("moderate_intensity_minutes")),
        "vigorous_intensity_minutes": _pos_float(workout.get("vigorous_intensity_minutes")),
        "average_hr": _pos_float(workout.get("average_hr") or workout.get("avg_heart_rate")),
        "max_hr": _pos_float(workout.get("max_hr") or workout.get("max_heart_rate")),
        "elevation_gain_m": _pos_float(workout.get("elevation_gain_m")),
    }


def build_weekly_target_from_workouts(
    *,
    workouts: List[dict],
    goal_type: str,
    race_date: Optional[date] = None,
    cycle_start_date: Optional[date] = None,
    reference_date: Optional[date] = None,
    user_profile: Optional[dict] = None,
) -> WeeklyTarget:
    """Build a WeeklyTarget V2 from raw workout documents and goal info.

    Parameters
    ----------
    workouts : list of raw db.workouts documents (up to 90 days).
    goal_type : legacy goal string (e.g. "SEMI", "MARATHON", "10K").
    race_date : target race date, if known.
    cycle_start_date : start of the training cycle.
    reference_date : anchor date (defaults to today UTC).
    user_profile : optional user_profiles document for RunnerProfile enrichment.
    """
    if reference_date is None:
        reference_date = datetime.now(timezone.utc).date()

    # Convert to domain activities
    activities = [_to_domain_activity(w) for w in workouts]

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

    # Map legacy goal string to GoalType
    goal_map = {
        "10K": GoalType.ten_k,
        "SEMI": GoalType.half_marathon,
        "HALF_MARATHON": GoalType.half_marathon,
        "MARATHON": GoalType.marathon,
        "5K": GoalType.five_k,
        "ULTRA": GoalType.ultra,
        "MAINTENANCE": GoalType.maintenance,
    }
    mapped_goal = goal_map.get(goal_type.upper(), GoalType.half_marathon)

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
