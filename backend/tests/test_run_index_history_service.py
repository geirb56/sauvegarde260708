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
        return all(doc.get(key) == value for key, value in query.items())


class FakeDB:
    def __init__(self, workouts: list[dict] | None = None):
        self.workouts = FakeCollection(workouts)
        self.run_index_scores = FakeCollection()


def test_select_snapshot_dates_uses_monthly_then_weekly_granularity():
    workouts = _progressive_workouts()

    snapshot_dates = select_snapshot_dates(workouts, reference_date=date(2026, 7, 9))

    assert snapshot_dates[-1] == date(2026, 7, 9)
    assert len({snapshot_date.isoformat() for snapshot_date in snapshot_dates}) == len(snapshot_dates)
    assert len(snapshot_dates) >= 5


def test_backfill_run_index_history_creates_progressive_snapshots():
    db = FakeDB(_progressive_workouts())

    result = asyncio.run(backfill_run_index_history(db, "runner-1", reference_date=date(2026, 7, 9)))

    history = sorted(db.run_index_scores.docs, key=lambda doc: doc["date"])
    assert result["snapshots_targeted"] == len(history)
    assert len(history) >= 5
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
