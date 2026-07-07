"""
Dashboard Service — orchestration layer.

Fetches data from MongoDB and coordinates the physiological engine modules
to build the dashboard payload.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from engine.readiness_engine import compute_readiness
from engine.training_load_engine import compute_training_load
from engine.workout_selector import select_workout


def _readiness_status(score: float) -> str:
    if score >= 80:
        return "excellent"
    if score >= 65:
        return "ready"
    if score >= 50:
        return "moderate"
    return "recovery"


async def get_dashboard(
    db: AsyncIOMotorDatabase,
    user_id: str | None = None,
) -> dict:
    """Build and return the dashboard payload.

    Parameters
    ----------
    db:
        Motor async database instance.
    user_id:
        Optional user identifier to scope the workout query.

    Returns
    -------
    dict:
        {
            "readiness": float,
            "status": str,
            "acwr": float,
            "today_workout": {"type": str, "duration": int, "intensity": str},
            "last_runs": list[dict],
        }
    """
    query: dict = {}
    if user_id:
        query["user_id"] = user_id

    # Fetch all workouts (used for ACWR over the last 28 days)
    cursor = db.workouts.find(query, {"_id": 0})
    workouts: list[dict] = await cursor.to_list(length=None)

    # Compute training load
    load_result = compute_training_load(workouts)
    acwr = load_result["acwr"]
    training_load_score = load_result["training_load_score"]

    # Fetch user data for HRV / RHR
    hrv_score: float | None = None
    rhr_today: float | None = None
    baseline_rhr: float | None = None

    if user_id:
        user_doc = await db.users.find_one({"user_id": user_id}, {"_id": 0})
        if user_doc:
            hrv_score = user_doc.get("hrv_score")
            rhr_today = user_doc.get("rhr_today")
            baseline_rhr = user_doc.get("baseline_rhr")

    # Compute readiness
    readiness = compute_readiness(
        training_load_score=training_load_score,
        hrv_score=hrv_score,
        rhr_today=rhr_today,
        baseline_rhr=baseline_rhr,
    )

    # Select today's workout
    today_workout = select_workout(readiness, acwr)

    # Last 3 workouts (most recent first)
    last_runs_cursor = db.workouts.find(
        query,
        {"_id": 0},
    ).sort("date", -1).limit(3)
    last_runs: list[dict] = await last_runs_cursor.to_list(length=3)

    return {
        "readiness": readiness,
        "status": _readiness_status(readiness),
        "acwr": acwr,
        "today_workout": today_workout,
        "last_runs": last_runs,
    }
