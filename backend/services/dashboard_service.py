"""
Dashboard Service — orchestration layer.

Fetches data from MongoDB and coordinates the RunIndex V2 modules
to build the dashboard payload.
"""

from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from engine.workout_selector import select_workout
from garmin.insights import compute_run_index


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
            "readiness": float | None,
            "status": str,
            "acwr": float | None,
            "today_workout": {"type": str, "duration": int, "intensity": str} | None,
            "last_runs": list[dict],
        }
    """
    query: dict = {}
    if user_id:
        query["user_id"] = user_id

    # Last 3 workouts (most recent first)
    last_runs_cursor = db.workouts.find(
        query,
        {"_id": 0},
    ).sort("date", -1).limit(3)
    last_runs: list[dict] = await last_runs_cursor.to_list(length=3)

    run_index_payload = await compute_run_index(db, user_id, language="en") if user_id else None
    metrics = (run_index_payload or {}).get("metrics") or {}
    readiness = metrics.get("run_readiness")
    # `/run-index` exposes ACWR under `metrics.training_load`; `/api/dashboard`
    # mirrors that exact V2 field and renames it to `acwr` for its own contract.
    acwr = metrics.get("training_load")
    today_workout = select_workout(readiness, acwr) if readiness is not None else None

    return {
        "readiness": readiness,
        "status": _readiness_status(readiness) if readiness is not None else "unavailable",
        "acwr": acwr,
        "today_workout": today_workout,
        "last_runs": last_runs,
    }
