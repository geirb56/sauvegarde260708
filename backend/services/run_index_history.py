from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from typing import Optional

try:
    from pymongo import UpdateOne
except ImportError:  # pragma: no cover - lightweight fallback for unit tests
    class UpdateOne:  # type: ignore[no-redef]
        def __init__(self, filter_doc, update_doc, upsert=False):
            self._filter = filter_doc
            self._doc = update_doc
            self._upsert = upsert

from engine.run_index_engine import calculate_run_index

logger = logging.getLogger(__name__)

WEEKLY_WINDOW_DAYS = 183


def _reference_day(reference_date: Optional[date] = None) -> date:
    return reference_date or datetime.now(timezone.utc).date()


def _parse_workout_day(workout: dict) -> Optional[date]:
    raw_value = workout.get("date") or workout.get("start_time")
    if not raw_value:
        return None
    if isinstance(raw_value, date):
        return raw_value
    if isinstance(raw_value, datetime):
        return raw_value.date()
    try:
        return datetime.fromisoformat(str(raw_value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.fromisoformat(str(raw_value).split("T")[0]).date()
        except ValueError:
            return None


def select_snapshot_dates(workouts: list[dict], reference_date: Optional[date] = None) -> list[date]:
    today = _reference_day(reference_date)
    weekly_cutoff = today - timedelta(days=WEEKLY_WINDOW_DAYS)
    monthly_buckets: dict[tuple[int, int], date] = {}
    weekly_buckets: dict[tuple[int, int], date] = {}

    for workout in workouts:
        workout_day = _parse_workout_day(workout)
        if workout_day is None or workout_day > today:
            continue
        if workout_day < weekly_cutoff:
            key = (workout_day.year, workout_day.month)
            monthly_buckets[key] = max(monthly_buckets.get(key, workout_day), workout_day)
            continue
        iso = workout_day.isocalendar()
        key = (iso.year, iso.week)
        weekly_buckets[key] = max(weekly_buckets.get(key, workout_day), workout_day)

    snapshot_dates = sorted(monthly_buckets.values()) + sorted(weekly_buckets.values())
    if workouts and (not snapshot_dates or snapshot_dates[-1] != today):
        snapshot_dates.append(today)
    return snapshot_dates


def build_snapshot_document(
    user_id: str,
    workouts: list[dict],
    snapshot_date: date,
    computed_at: Optional[str] = None,
) -> dict:
    snapshot = calculate_run_index(workouts, reference_date=snapshot_date)
    return {
        "user_id": user_id,
        "date": snapshot_date.isoformat(),
        "computed_at": computed_at or datetime.now(timezone.utc).isoformat(),
        **snapshot,
    }


async def load_user_workouts(db, user_id: str) -> list[dict]:
    cursor = db.workouts.find({"user_id": user_id}, {"_id": 0}).sort("date", 1)
    return await cursor.to_list(None)


async def upsert_run_index_snapshot(
    db,
    user_id: str,
    workouts: list[dict],
    snapshot_date: Optional[date] = None,
) -> dict:
    target_day = _reference_day(snapshot_date)
    doc = build_snapshot_document(user_id, workouts, target_day)
    await db.run_index_scores.update_one(
        {"user_id": user_id, "date": doc["date"]},
        {"$set": doc},
        upsert=True,
    )
    logger.info("[run-index-history] upserted daily snapshot user=%s date=%s run_index=%s confidence=%s",
                user_id, doc["date"], doc["run_index"], doc["confidence_score"])
    return doc


@dataclass
class BackfillSummary:
    user_id: str
    snapshots_targeted: int
    snapshots_created: int
    snapshots_updated: int
    period_start: Optional[str]
    period_end: Optional[str]

    def as_dict(self) -> dict:
        return {
            "user_id": self.user_id,
            "snapshots_targeted": self.snapshots_targeted,
            "snapshots_created": self.snapshots_created,
            "snapshots_updated": self.snapshots_updated,
            "period_start": self.period_start,
            "period_end": self.period_end,
        }


async def backfill_run_index_history(
    db,
    user_id: str,
    workouts: Optional[list[dict]] = None,
    reference_date: Optional[date] = None,
) -> dict:
    today = _reference_day(reference_date)
    workouts = workouts if workouts is not None else await load_user_workouts(db, user_id)
    snapshot_dates = select_snapshot_dates(workouts, today)

    if not snapshot_dates:
        summary = BackfillSummary(
            user_id=user_id,
            snapshots_targeted=0,
            snapshots_created=0,
            snapshots_updated=0,
            period_start=None,
            period_end=None,
        )
        logger.info("[run-index-history] no snapshots created user=%s covered=%s->%s",
                    user_id, summary.period_start, summary.period_end)
        return summary.as_dict()

    computed_at = datetime.now(timezone.utc).isoformat()
    operations = [
        UpdateOne(
            {"user_id": user_id, "date": snapshot_day.isoformat()},
            {"$set": build_snapshot_document(user_id, workouts, snapshot_day, computed_at)},
            upsert=True,
        )
        for snapshot_day in snapshot_dates
    ]
    result = await db.run_index_scores.bulk_write(operations, ordered=False)
    summary = BackfillSummary(
        user_id=user_id,
        snapshots_targeted=len(snapshot_dates),
        snapshots_created=result.upserted_count,
        snapshots_updated=result.modified_count,
        period_start=snapshot_dates[0].isoformat(),
        period_end=snapshot_dates[-1].isoformat(),
    )
    logger.info(
        "[run-index-history] backfill user=%s snapshots=%s created=%s updated=%s covered=%s->%s",
        user_id,
        summary.snapshots_targeted,
        summary.snapshots_created,
        summary.snapshots_updated,
        summary.period_start,
        summary.period_end,
    )
    return summary.as_dict()


async def refresh_run_index_after_garmin_sync(db, user_id: str) -> dict:
    from garmin.backfill import backfill_user as backfill_garmin_workouts

    await backfill_garmin_workouts(db, user_id, prune=False)
    workouts = await load_user_workouts(db, user_id)
    today_snapshot = await upsert_run_index_snapshot(db, user_id, workouts)

    conn = await db.garmin_connections.find_one({"user_id": user_id}, {"_id": 0})
    if conn and not conn.get("run_index_history_backfilled_at"):
        history = await backfill_run_index_history(db, user_id, workouts=workouts)
        await db.garmin_connections.update_one(
            {"user_id": user_id},
            {"$set": {"run_index_history_backfilled_at": datetime.now(timezone.utc).isoformat()}},
        )
        return {"today_snapshot": today_snapshot, "history_backfill": history}

    return {"today_snapshot": today_snapshot, "history_backfill": None}


async def backfill_connected_users_run_index_history(db) -> dict:
    from garmin.backfill import backfill_user as backfill_garmin_workouts

    cursor = db.garmin_connections.find({"connected": True}, {"_id": 0, "user_id": 1})
    users = 0
    snapshots_created = 0
    snapshots_updated = 0
    errors = []

    async for conn in cursor:
        user_id = conn.get("user_id")
        if not user_id:
            continue
        try:
            await backfill_garmin_workouts(db, user_id, prune=False)
            workouts = await load_user_workouts(db, user_id)
            summary = await backfill_run_index_history(db, user_id, workouts=workouts)
            await db.garmin_connections.update_one(
                {"user_id": user_id},
                {"$set": {"run_index_history_backfilled_at": datetime.now(timezone.utc).isoformat()}},
            )
            users += 1
            snapshots_created += summary["snapshots_created"]
            snapshots_updated += summary["snapshots_updated"]
        except Exception as exc:
            logger.exception("[run-index-history] backfill failed user=%s", user_id)
            errors.append({"user_id": user_id, "error": str(exc)})

    result = {
        "users": users,
        "snapshots_created": snapshots_created,
        "snapshots_updated": snapshots_updated,
        "errors": errors,
    }
    logger.info("[run-index-history] backfill-all users=%s created=%s updated=%s errors=%s",
                users, snapshots_created, snapshots_updated, len(errors))
    return result
