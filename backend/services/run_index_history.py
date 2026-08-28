from __future__ import annotations

import calendar
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

from engine.run_index_engine import calculate_run_index, calculate_run_index_from_domain
from training_v2.domain_activity import DomainActivity

logger = logging.getLogger(__name__)

HISTORY_WINDOW_DAYS = 365
WEEKLY_WINDOW_DAYS = 183
MAX_HISTORY_DOCS = 500


@dataclass(frozen=True)
class HistoryPeriod:
    key: str
    months: int
    granularity: str


SUPPORTED_HISTORY_PERIODS = {
    "3m": HistoryPeriod(key="3m", months=3, granularity="week"),
    "6m": HistoryPeriod(key="6m", months=6, granularity="week"),
    "12m": HistoryPeriod(key="12m", months=12, granularity="month"),
}


def _reference_day(reference_date: Optional[date] = None) -> date:
    return reference_date or datetime.now(timezone.utc).date()


def _subtract_months(target_day: date, months: int) -> date:
    year = target_day.year
    month = target_day.month - months
    while month <= 0:
        month += 12
        year -= 1
    day = min(target_day.day, calendar.monthrange(year, month)[1])
    return date(year, month, day)


def normalize_history_period(period: Optional[str] = None, months: Optional[int] = None) -> HistoryPeriod:
    normalized = (period or "").strip().lower()
    if normalized in SUPPORTED_HISTORY_PERIODS:
        return SUPPORTED_HISTORY_PERIODS[normalized]

    if months in {3, 6, 12}:
        return SUPPORTED_HISTORY_PERIODS[f"{months}m"]

    return SUPPORTED_HISTORY_PERIODS["6m"]


def _parse_workout_day(workout: dict) -> Optional[date]:
    raw_value = workout.get("date") or workout.get("start_time")
    if not raw_value:
        return None
    if isinstance(raw_value, datetime):
        return raw_value.date()
    if isinstance(raw_value, date):
        return raw_value
    try:
        return datetime.fromisoformat(str(raw_value).replace("Z", "+00:00")).date()
    except ValueError:
        try:
            return datetime.fromisoformat(str(raw_value).split("T")[0]).date()
        except ValueError:
            return None


def _first_workout_day(workouts: list[dict], reference_date: Optional[date] = None) -> Optional[date]:
    today = _reference_day(reference_date)
    workout_days = [
        workout_day
        for workout_day in (_parse_workout_day(workout) for workout in workouts)
        if workout_day is not None and workout_day <= today
    ]
    if not workout_days:
        return None
    return min(workout_days)


def _history_projection() -> dict:
    return {
        "_id": 0,
        "date": 1,
        "run_index": 1,
        "speed_score": 1,
        "endurance_score": 1,
        "consistency_score": 1,
        "efficiency_score": 1,
    }


def _history_entry(document: dict) -> dict:
    return {
        "date": document["date"],
        "run_index": document.get("run_index"),
        "speed": document.get("speed_score"),
        "endurance": document.get("endurance_score"),
        "consistency": document.get("consistency_score"),
        "efficiency": document.get("efficiency_score"),
        "speed_score": document.get("speed_score"),
        "endurance_score": document.get("endurance_score"),
        "consistency_score": document.get("consistency_score"),
        "efficiency_score": document.get("efficiency_score"),
    }


def _history_bucket_key(date_str: str, granularity: str) -> tuple[int, int]:
    snapshot_day = datetime.fromisoformat(date_str).date()
    if granularity == "month":
        return snapshot_day.year, snapshot_day.month
    iso = snapshot_day.isocalendar()
    return iso.year, iso.week


def _select_period_history(documents: list[dict], granularity: str) -> list[dict]:
    buckets: dict[tuple[int, int], dict] = {}
    for document in documents:
        buckets[_history_bucket_key(document["date"], granularity)] = _history_entry(document)
    return sorted(buckets.values(), key=lambda item: item["date"])


def _expected_period_points(period_config: HistoryPeriod, reference_date: Optional[date] = None) -> list[date]:
    today = _reference_day(reference_date)
    if period_config.granularity == "month":
        return [_subtract_months(today, months_ago) for months_ago in range(period_config.months, -1, -1)]

    start_day = _subtract_months(today, period_config.months)
    points = []
    candidate = today
    while candidate >= start_day:
        points.append(candidate)
        candidate -= timedelta(days=7)
    return list(reversed(points))


def _build_history_response(
    history: list[dict],
    period_config: HistoryPeriod,
    reference_date: Optional[date] = None,
    current_snapshot: Optional[dict] = None,
) -> dict:
    if not history:
        return {
            "has_data": False,
            "has_full_period_data": False,
            "current_run_index": None,
            "trend": 0,
            "period": period_config.key,
            "period_months": period_config.months,
            "granularity": period_config.granularity,
            "history": [],
            "pillars": {},
            "available_from": None,
            "available_until": None,
        }

    current = history[-1]
    current_source = current_snapshot or current
    first = next((entry for entry in history if entry.get("run_index") is not None), None)
    last = next((entry for entry in reversed(history) if entry.get("run_index") is not None), None)

    trend = 0
    if first and last and first["run_index"] is not None and last["run_index"] is not None:
        trend = last["run_index"] - first["run_index"]

    pillars = {}
    for pillar in ("speed", "endurance", "consistency", "efficiency"):
        current_val = current_source.get(pillar)
        first_val = first.get(pillar) if first else None
        pillars[pillar] = {
            "current": current_val,
            "evolution": None if current_val is None or first_val is None else current_val - first_val,
        }

    expected_points = _expected_period_points(period_config, reference_date)
    expected_bucket_count = len({_history_bucket_key(point.isoformat(), period_config.granularity) for point in expected_points})

    return {
        "has_data": True,
        "has_full_period_data": len(history) >= expected_bucket_count,
        "current_run_index": current_source.get("run_index"),
        "trend": trend,
        "period": period_config.key,
        "period_months": period_config.months,
        "granularity": period_config.granularity,
        "history": history,
        "pillars": pillars,
        "available_from": history[0]["date"],
        "available_until": history[-1]["date"],
    }


def select_snapshot_dates(workouts: list[dict], reference_date: Optional[date] = None) -> list[date]:
    today = _reference_day(reference_date)
    first_workout_day = _first_workout_day(workouts, today)
    if first_workout_day is None:
        return []

    oldest_supported_day = today - timedelta(days=HISTORY_WINDOW_DAYS)
    first_workout_day = max(first_workout_day, oldest_supported_day)

    monthly_dates = [_subtract_months(today, months_ago) for months_ago in range(12, 6, -1)]
    weekly_points = list(range(WEEKLY_WINDOW_DAYS // 7, -1, -1))
    weekly_dates = [today - timedelta(days=7 * weeks_ago) for weeks_ago in weekly_points]

    snapshot_dates = sorted(
        {
            candidate
            for candidate in monthly_dates + weekly_dates
            if first_workout_day <= candidate <= today
        }
    )
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


async def load_garmin_domain_activities(db, user_id: str) -> list[DomainActivity]:
    """Load garmin_activities for a user and convert to DomainActivity.

    PR179 canonical source for RunIndex Garmin. Does NOT touch db.workouts.
    Activities are returned newest-first so callers can filter by reference_date
    without needing a re-sort.
    """
    from garmin.domain_adapter import mongo_garmin_activities_to_domain

    docs = await (
        db.garmin_activities.find({"user_id": user_id}, {"_id": 0})
        .sort("start_time", -1)
        .to_list(None)
    )
    return mongo_garmin_activities_to_domain(docs)


def _domain_activity_day(activity: DomainActivity) -> Optional[date]:
    """Extract the calendar date from a DomainActivity's start_time field."""
    start = activity.start_time
    if start is None:
        return None
    if isinstance(start, datetime):
        return start.date()
    if isinstance(start, date) and not isinstance(start, datetime):
        return start
    if isinstance(start, str):
        try:
            return datetime.fromisoformat(start.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return datetime.fromisoformat(start.split("T")[0]).date()
            except ValueError:
                return None
    return None


def _first_domain_activity_day(
    activities: list[DomainActivity], reference_date: Optional[date] = None
) -> Optional[date]:
    today = _reference_day(reference_date)
    days = [
        d
        for d in (_domain_activity_day(a) for a in activities)
        if d is not None and d <= today
    ]
    return min(days) if days else None


def select_snapshot_dates_from_domain(
    activities: list[DomainActivity],
    reference_date: Optional[date] = None,
) -> list[date]:
    """Compute snapshot date grid from DomainActivity list (PR179 canonical)."""
    today = _reference_day(reference_date)
    first_day = _first_domain_activity_day(activities, today)
    if first_day is None:
        return []

    oldest_supported_day = today - timedelta(days=HISTORY_WINDOW_DAYS)
    first_day = max(first_day, oldest_supported_day)

    monthly_dates = [_subtract_months(today, months_ago) for months_ago in range(12, 6, -1)]
    weekly_points = list(range(WEEKLY_WINDOW_DAYS // 7, -1, -1))
    weekly_dates = [today - timedelta(days=7 * weeks_ago) for weeks_ago in weekly_points]

    return sorted(
        {
            candidate
            for candidate in monthly_dates + weekly_dates
            if first_day <= candidate <= today
        }
    )


def build_snapshot_document_from_domain(
    user_id: str,
    activities: list[DomainActivity],
    snapshot_date: date,
    computed_at: Optional[str] = None,
) -> dict:
    """Build a run_index_scores document from DomainActivity (PR179 canonical).

    reference_date=snapshot_date ensures no future activity influences the score:
    activities with start_time > snapshot_date are filtered by the engine.
    """
    snapshot = calculate_run_index_from_domain(activities, reference_date=snapshot_date)
    return {
        "user_id": user_id,
        "date": snapshot_date.isoformat(),
        "computed_at": computed_at or datetime.now(timezone.utc).isoformat(),
        **snapshot,
    }


async def get_run_index_history_payload(
    db,
    user_id: str,
    period: Optional[str] = None,
    months: Optional[int] = None,
    reference_date: Optional[date] = None,
) -> dict:
    period_config = normalize_history_period(period=period, months=months)
    today = _reference_day(reference_date)
    period_start = _subtract_months(today, period_config.months).isoformat()

    # PR216: refresh today's snapshot from the canonical Garmin DomainActivity
    # path before reading historical snapshots so Progress and Dashboard share
    # the same current RunIndex authority independently of navigation order.
    activities = await load_garmin_domain_activities(db, user_id)
    current_snapshot = await upsert_run_index_snapshot(
        db,
        user_id,
        activities=activities,
        snapshot_date=today,
    )

    documents = await db.run_index_scores.find(
        {"user_id": user_id, "date": {"$gte": period_start, "$lte": today.isoformat()}},
        _history_projection(),
    ).sort("date", 1).to_list(MAX_HISTORY_DOCS)

    history = _select_period_history(documents, period_config.granularity)
    return _build_history_response(
        history,
        period_config,
        reference_date=today,
        current_snapshot=current_snapshot,
    )


async def upsert_run_index_snapshot(
    db,
    user_id: str,
    activities: Optional[list[DomainActivity]] = None,
    snapshot_date: Optional[date] = None,
) -> dict:
    """Upsert today's RunIndex snapshot from DomainActivity (PR179 canonical).

    Source: garmin_activities → DomainActivity (loaded when activities is None).
    Does NOT use db.workouts.
    """
    target_day = _reference_day(snapshot_date)
    if activities is None:
        activities = await load_garmin_domain_activities(db, user_id)
    doc = build_snapshot_document_from_domain(user_id, activities, target_day)
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
    activities: Optional[list[DomainActivity]] = None,
    reference_date: Optional[date] = None,
) -> dict:
    """Backfill RunIndex snapshots from DomainActivity (PR179 canonical).

    Source: garmin_activities → DomainActivity (loaded when activities is None).
    Does NOT use db.workouts. reference_date is propagated to every snapshot
    so no future activity leaks into historical scores.
    """
    today = _reference_day(reference_date)
    if activities is None:
        activities = await load_garmin_domain_activities(db, user_id)
    snapshot_dates = select_snapshot_dates_from_domain(activities, today)

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
            {"$set": build_snapshot_document_from_domain(user_id, activities, snapshot_day, computed_at)},
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


async def refresh_today_run_index_after_garmin_activities(
    db,
    user_id: str,
    activities: Optional[list[DomainActivity]] = None,
) -> dict:
    """Refresh today's RunIndex directly from garmin_activities (PR179).

    No longer waits for the workouts fan-out. Reads garmin_activities →
    DomainActivity immediately after Garmin sync writes, then upserts the
    snapshot. db.workouts is NOT consulted.

    Pass ``activities`` to reuse an already-loaded list and avoid a second
    database round-trip (e.g. when called from refresh_run_index_after_garmin_sync).
    """
    if activities is None:
        activities = await load_garmin_domain_activities(db, user_id)
    today_snapshot = await upsert_run_index_snapshot(db, user_id, activities=activities)
    return {"today_snapshot": today_snapshot, "activities_count": len(activities)}


async def backfill_run_index_history_after_garmin_sync(
    db,
    user_id: str,
    activities: Optional[list[DomainActivity]] = None,
) -> dict:
    """Backfill RunIndex history after a Garmin sync (PR179 canonical).

    Source: garmin_activities → DomainActivity. db.workouts NOT used.
    """
    if activities is None:
        activities = await load_garmin_domain_activities(db, user_id)
    history = await backfill_run_index_history(db, user_id, activities=activities)

    conn = await db.garmin_connections.find_one({"user_id": user_id}, {"_id": 0})
    if conn:
        await db.garmin_connections.update_one(
            {"user_id": user_id},
            {"$set": {"run_index_history_backfilled_at": datetime.now(timezone.utc).isoformat()}},
        )

    return history


async def refresh_run_index_after_garmin_sync(db, user_id: str) -> dict:
    # Load activities once; share across today-snapshot and history backfill.
    activities = await load_garmin_domain_activities(db, user_id)
    refreshed = await refresh_today_run_index_after_garmin_activities(db, user_id, activities=activities)
    history = await backfill_run_index_history_after_garmin_sync(
        db,
        user_id,
        activities=activities,
    )
    return {"today_snapshot": refreshed["today_snapshot"], "history_backfill": history}


async def backfill_connected_users_run_index_history(db) -> dict:
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
            activities = await load_garmin_domain_activities(db, user_id)
            summary = await backfill_run_index_history(db, user_id, activities=activities)
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
