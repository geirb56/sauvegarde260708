from __future__ import annotations

from typing import Any, Optional

from workout_analysis_v2 import (
    SIMILAR_HISTORY_WINDOW_DAYS,
    WorkoutAnalysisV2Response,
    build_workout_analysis_v2,
    workout_analysis_candidate_date_bounds,
)


async def load_scoped_workout_analysis_v2(
    *,
    db: Any,
    user_id: str,
    workout_id: str,
    language: str,
) -> Optional[tuple[dict[str, Any], Optional[WorkoutAnalysisV2Response]]]:
    workout = await db.workouts.find_one(
        {"id": workout_id, "user_id": user_id},
        {"_id": 0},
    )
    if workout is None:
        return None

    try:
        lower_bound, upper_bound = workout_analysis_candidate_date_bounds(
            workout.get("date", ""),
            days=SIMILAR_HISTORY_WINDOW_DAYS,
        )
        historical_workouts = await (
            db.workouts.find(
                {
                    "user_id": user_id,
                    "type": workout.get("type"),
                    "date": {"$gte": lower_bound, "$lt": upper_bound},
                },
                {"_id": 0},
            )
            .sort("date", -1)
            .to_list(length=200)
        )
        analysis = build_workout_analysis_v2(
            workout=workout,
            historical_workouts=historical_workouts,
            language=language,
        )
    except Exception:
        analysis = None
    return workout, analysis
