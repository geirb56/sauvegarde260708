from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from services.run_index_history import (  # noqa: E402
    backfill_run_index_history,
    build_snapshot_document,
    get_run_index_history_payload,
    select_snapshot_dates,
)


def _run(days_ago: int, distance_km: float, pace_min_km: float, avg_hr: int | None = None) -> dict:
    duration_minutes = distance_km * pace_min_km
    return {
        "type": "run",
        "date": (date(2026, 7, 9) - timedelta(days=days_ago)).isoformat(),
        "distance_km": distance_km,
        "duration_minutes": round(duration_minutes, 1),
        "avg_pace_min_km": pace_min_km,
        "avg_speed_kmh": round(60.0 / pace_min_km, 2),
        "avg_heart_rate": avg_hr,
        "user_id": "runner-1",
    }


def _progressive_workouts() -> list[dict]:
    return [
        _run(240, 5.0, 6.4),
        _run(210, 6.0, 6.2),
        _run(182, 7.0, 6.0),
        _run(154, 8.0, 5.7),
        _run(126, 10.0, 5.4, 160),
        _run(98, 12.0, 5.1, 158),
        _run(70, 14.0, 4.9, 156),
        _run(49, 16.0, 4.7, 154),
        _run(28, 10.0, 4.4, 166),
        _run(14, 18.0, 4.3, 160),
        _run(7, 12.0, 4.1, 168),
        _run(2, 21.1, 4.0, 162),
    ]


def _progressive_span_workouts(total_days: int, step_days: int) -> list[dict]:
    workouts = []
    scheduled_days = list(range(total_days, -1, -step_days))
    for index, days_ago in enumerate(scheduled_days):
        progress = index / max(len(scheduled_days) - 1, 1)
        distance_km = round(6.0 + (10.0 * progress), 1)
        pace_min_km = round(6.4 - (2.0 * progress), 2)
        avg_hr = int(166 - (10 * progress))
        workouts.append(_run(days_ago, distance_km, pace_min_km, avg_hr))
    return workouts


class FakeCursor:
    def __init__(self, docs: list[dict]):
        self.docs = list(docs)

    def sort(self, field: str, direction: int):
        self.docs.sort(key=lambda doc: doc.get(field), reverse=direction < 0)
        return self

    async def to_list(self, length=None):
        if length is None:
            return list(self.docs)
        return list(self.docs[:length])

    def __aiter__(self):
        self._index = 0
        return self

    async def __anext__(self):
        if self._index >= len(self.docs):
            raise StopAsyncIteration
        doc = self.docs[self._index]
        self._index += 1
        return doc


class FakeCollection:
    def __init__(self, docs: list[dict] | None = None):
        self.docs = list(docs or [])

    def find(self, query: dict, projection=None):
        return FakeCursor([doc for doc in self.docs if self._matches(doc, query)])

    async def find_one(self, query: dict, projection=None):
        for doc in self.docs:
            if self._matches(doc, query):
                return dict(doc)
        return None

    async def update_one(self, filter_doc: dict, update_doc: dict, upsert: bool = False):
        for index, doc in enumerate(self.docs):
            if self._matches(doc, filter_doc):
                self.docs[index] = {**doc, **update_doc.get("$set", {})}
                return SimpleNamespace(upserted_id=None, modified_count=1)
        if upsert:
            self.docs.append(dict(update_doc.get("$set", {})))
            return SimpleNamespace(upserted_id=len(self.docs), modified_count=0)
        return SimpleNamespace(upserted_id=None, modified_count=0)

    async def bulk_write(self, operations, ordered: bool = False):
        upserted = 0
        modified = 0
        for operation in operations:
            existing = next((doc for doc in self.docs if self._matches(doc, operation._filter)), None)
            if existing is None:
                self.docs.append(dict(operation._doc["$set"]))
                upserted += 1
                continue
            updated = {**existing, **operation._doc["$set"]}
            if updated != existing:
                self.docs[self.docs.index(existing)] = updated
                modified += 1
        return SimpleNamespace(upserted_count=upserted, modified_count=modified)

    @staticmethod
    def _matches(doc: dict, query: dict) -> bool:
        for key, value in query.items():
            doc_value = doc.get(key)
            if isinstance(value, dict):
                # Test helper only needs the range operators used by the history service queries.
                if "$gte" in value and (doc_value is None or doc_value < value["$gte"]):
                    return False
                if "$lte" in value and (doc_value is None or doc_value > value["$lte"]):
                    return False
                continue
            if doc_value != value:
                return False
        return True


def _workout_to_garmin_activity_doc(workout: dict) -> dict:
    """Convert a test workout dict to a garmin_activities-compatible document.

    Used to migrate FakeDB to the PR179 canonical source (garmin_activities).
    """
    user_id = workout.get("user_id", "runner-1")
    # Use date as start_time (append T00:00:00+00:00 so it parses as a datetime)
    raw_date = workout.get("date") or workout.get("start_time") or ""
    start_time = raw_date if "T" in raw_date else f"{raw_date}T00:00:00+00:00"
    distance_m = (workout.get("distance_km") or 0.0) * 1000.0
    duration_s = (workout.get("duration_minutes") or 0.0) * 60.0
    avg_hr = workout.get("avg_heart_rate") or workout.get("average_hr")
    return {
        "user_id": user_id,
        "activity_type": "running",
        "start_time": start_time,
        "distance_m": distance_m,
        "duration_s": duration_s,
        "average_hr": float(avg_hr) if avg_hr is not None else None,
        "source": "garmin",
    }


class FakeDB:
    def __init__(self, workouts: list[dict] | None = None):
        raw_workouts = list(workouts or [])
        self.workouts = FakeCollection(raw_workouts)
        # PR179: garmin_activities is the canonical RunIndex source.
        # Convert test workout dicts so that load_garmin_domain_activities works.
        garmin_docs = [_workout_to_garmin_activity_doc(w) for w in raw_workouts]
        self.garmin_activities = FakeCollection(garmin_docs)
        self.run_index_scores = FakeCollection()


def test_select_snapshot_dates_uses_monthly_then_weekly_granularity():
    workouts = _progressive_span_workouts(total_days=365, step_days=14)

    snapshot_dates = select_snapshot_dates(workouts, reference_date=date(2026, 7, 9))

    assert snapshot_dates[-1] == date(2026, 7, 9)
    assert len({snapshot_date.isoformat() for snapshot_date in snapshot_dates}) == len(snapshot_dates)
    assert date(2025, 7, 9) in snapshot_dates
    assert date(2025, 12, 9) in snapshot_dates
    assert date(2026, 1, 8) in snapshot_dates
    assert len(snapshot_dates) >= 30


def test_backfill_run_index_history_creates_progressive_snapshots():
    db = FakeDB(_progressive_span_workouts(total_days=365, step_days=14))

    result = asyncio.run(backfill_run_index_history(db, "runner-1", reference_date=date(2026, 7, 9)))

    history = sorted(db.run_index_scores.docs, key=lambda doc: doc["date"])
    assert result["snapshots_targeted"] == len(history)
    assert len(history) >= 30
    assert len({doc["date"] for doc in history}) == len(history)
    assert len({doc["run_index"] for doc in history}) > 1
    assert history[0]["run_index"] < history[-1]["run_index"]


def test_backfill_run_index_history_is_idempotent():
    db = FakeDB(_progressive_workouts())

    first = asyncio.run(backfill_run_index_history(db, "runner-1", reference_date=date(2026, 7, 9)))
    second = asyncio.run(backfill_run_index_history(db, "runner-1", reference_date=date(2026, 7, 9)))

    assert first["snapshots_created"] == first["snapshots_targeted"]
    assert second["snapshots_created"] == 0
    assert len(db.run_index_scores.docs) == first["snapshots_targeted"]


def test_empty_history_snapshot_has_low_confidence():
    snapshot = build_snapshot_document("runner-1", [], date(2026, 7, 9))

    assert snapshot["run_index"] == 0
    assert snapshot["confidence_score"] == 0


def test_history_payload_returns_complete_12_month_view():
    db = FakeDB(_progressive_span_workouts(total_days=365, step_days=14))
    asyncio.run(backfill_run_index_history(db, "runner-1", reference_date=date(2026, 7, 9)))

    payload = asyncio.run(
        get_run_index_history_payload(
            db,
            "runner-1",
            period="12m",
            reference_date=date(2026, 7, 9),
        )
    )

    assert payload["has_data"] is True
    assert payload["has_full_period_data"] is True
    assert payload["granularity"] == "month"
    assert len(payload["history"]) == 13
    assert payload["history"][0]["date"].startswith("2025-07")
    assert payload["history"][-1]["date"] == "2026-07-09"
    assert payload["history"][0]["run_index"] < payload["history"][-1]["run_index"]
    assert {"speed", "endurance", "consistency", "efficiency"} <= set(payload["history"][0].keys())


def test_history_payload_marks_partial_12_month_view_for_recent_user():
    db = FakeDB(_progressive_span_workouts(total_days=84, step_days=7))
    asyncio.run(backfill_run_index_history(db, "runner-1", reference_date=date(2026, 7, 9)))

    payload = asyncio.run(
        get_run_index_history_payload(
            db,
            "runner-1",
            period="12m",
            reference_date=date(2026, 7, 9),
        )
    )

    assert payload["has_data"] is True
    assert payload["has_full_period_data"] is False
    assert payload["granularity"] == "month"
    assert 1 < len(payload["history"]) < 13
    assert payload["available_from"] >= "2026-04-01"


def test_historical_snapshot_changes_with_progression():
    workouts = _progressive_span_workouts(total_days=180, step_days=14)

    past_snapshot = build_snapshot_document("runner-1", workouts, date(2026, 4, 9))
    current_snapshot = build_snapshot_document("runner-1", workouts, date(2026, 7, 9))

    assert past_snapshot["date"] == "2026-04-09"
    assert current_snapshot["date"] == "2026-07-09"
    assert past_snapshot["run_index"] != current_snapshot["run_index"]
    assert past_snapshot["run_index"] < current_snapshot["run_index"]
