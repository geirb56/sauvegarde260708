from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from typing import Any, Optional
from unittest.mock import AsyncMock

import pytest

from services.paddle_event_index import ensure_paddle_events_unique_index
from subscription_manager import SubscriptionStatus, cancel_subscription

pytestmark = pytest.mark.asyncio


class _Cursor:
    def __init__(self, groups: list[dict[str, Any]]) -> None:
        self._groups = groups

    async def to_list(self, length=None) -> list[dict[str, Any]]:
        return [dict(group) for group in self._groups]


class _PaddleEventsCollection:
    def __init__(self, docs: Optional[list[dict[str, Any]]] = None, indexes: Optional[list[dict[str, Any]]] = None) -> None:
        self.docs = [dict(doc) for doc in (docs or [])]
        self.indexes = [dict(idx) for idx in (indexes or [{"name": "_id_", "key": {"_id": 1}}])]
        self.create_calls: list[dict[str, Any]] = []
        self.drop_calls: list[str] = []

    async def list_indexes(self):
        for idx in self.indexes:
            yield dict(idx)

    async def drop_index(self, name: str) -> None:
        self.drop_calls.append(name)
        self.indexes = [idx for idx in self.indexes if idx.get("name") != name]

    async def create_index(self, key, **kwargs):
        index_name = kwargs.get("name") or f"{key}_1"
        key_dict = {key: 1} if isinstance(key, str) else dict(key)
        self.indexes = [idx for idx in self.indexes if idx.get("name") != index_name]
        self.indexes.append({"name": index_name, "key": key_dict, **kwargs})
        self.create_calls.append({"key": key, **kwargs})
        return index_name

    def aggregate(self, _pipeline: list[dict[str, Any]]) -> _Cursor:
        grouped: dict[str, list[dict[str, Any]]] = defaultdict(list)
        for doc in self.docs:
            event_id = doc.get("event_id")
            if isinstance(event_id, str) and event_id != "":
                grouped[str(event_id)].append(doc)
        groups = []
        for event_id, docs in grouped.items():
            if len(docs) > 1:
                groups.append({"_id": event_id, "count": len(docs), "docs": [dict(doc) for doc in docs]})
        return _Cursor(groups)

    async def delete_many(self, query: dict[str, Any]):
        ids = set((query.get("_id") or {}).get("$in", []))
        before = len(self.docs)
        self.docs = [doc for doc in self.docs if doc.get("_id") not in ids]
        return SimpleNamespace(deleted_count=before - len(self.docs))


class _ArchiveCollection:
    def __init__(self) -> None:
        self.docs: dict[str, dict[str, Any]] = {}

    async def update_one(self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> None:
        key = query["_id"]
        if key not in self.docs and upsert:
            self.docs[key] = dict(update.get("$setOnInsert") or {})


class _SubCollection:
    def __init__(self, docs: Optional[list[dict[str, Any]]] = None) -> None:
        self._docs = [dict(doc) for doc in (docs or [])]

    async def find_one(self, query: dict[str, Any]) -> Optional[dict[str, Any]]:
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                return dict(doc)
        return None

    async def update_one(self, query: dict[str, Any], update: dict[str, Any], upsert: bool = False) -> None:
        for doc in self._docs:
            if all(doc.get(k) == v for k, v in query.items()):
                doc.update(update.get("$set", {}))
                return
        if upsert:
            new_doc = dict(query)
            new_doc.update(update.get("$set", {}))
            self._docs.append(new_doc)


class _DB:
    def __init__(
        self,
        *,
        paddle_docs: Optional[list[dict[str, Any]]] = None,
        paddle_indexes: Optional[list[dict[str, Any]]] = None,
        subscriptions: Optional[list[dict[str, Any]]] = None,
    ) -> None:
        self.paddle_events = _PaddleEventsCollection(paddle_docs, paddle_indexes)
        self.paddle_events_dedup_archive = _ArchiveCollection()
        self.subscriptions = _SubCollection(subscriptions)


async def test_index_migration_creates_unique_index_on_clean_collection():
    db = _DB()
    await ensure_paddle_events_unique_index(db)
    assert len(db.paddle_events.create_calls) == 1
    assert db.paddle_events.create_calls[0]["unique"] is True
    assert db.paddle_events.create_calls[0]["partialFilterExpression"] == {"event_id": {"$type": "string", "$ne": ""}}


async def test_index_migration_replaces_non_unique_event_id_index():
    db = _DB(
        paddle_indexes=[
            {"name": "_id_", "key": {"_id": 1}},
            {"name": "event_id_1", "key": {"event_id": 1}, "unique": False},
        ]
    )
    await ensure_paddle_events_unique_index(db)
    assert "event_id_1" in db.paddle_events.drop_calls
    assert len(db.paddle_events.create_calls) == 1


async def test_index_migration_deduplicates_then_creates_unique_index():
    now = datetime.now(timezone.utc)
    db = _DB(
        paddle_docs=[
            {"_id": "a", "event_id": "evt_dup", "status": "failed", "failed_at": now.isoformat()},
            {"_id": "b", "event_id": "evt_dup", "status": "processed", "processed_at": now.isoformat()},
            {"_id": "c", "event_id": "evt_ok", "status": "processed", "processed_at": now.isoformat()},
        ]
    )
    await ensure_paddle_events_unique_index(db)

    dup_docs = [doc for doc in db.paddle_events.docs if doc.get("event_id") == "evt_dup"]
    assert len(dup_docs) == 1
    assert dup_docs[0]["_id"] == "b"
    assert len(db.paddle_events_dedup_archive.docs) == 1
    assert len(db.paddle_events.create_calls) == 1


async def test_index_migration_keeps_documents_without_event_id():
    db = _DB(
        paddle_docs=[
            {"_id": "legacy1", "event_type": "legacy"},
            {"_id": "legacy2", "event_type": "legacy"},
            {"_id": "event", "event_id": "evt_unique", "status": "processed"},
        ]
    )
    await ensure_paddle_events_unique_index(db)
    assert len([doc for doc in db.paddle_events.docs if doc.get("event_id") is None]) == 2
    assert len(db.paddle_events.create_calls) == 1


async def test_index_migration_second_run_is_idempotent():
    db = _DB()
    await ensure_paddle_events_unique_index(db)
    await ensure_paddle_events_unique_index(db)
    assert len(db.paddle_events.create_calls) == 1


async def test_index_migration_noop_when_target_unique_index_exists():
    db = _DB(
        paddle_indexes=[
            {"name": "_id_", "key": {"_id": 1}},
            {
                "name": "event_id_unique_partial",
                "key": {"event_id": 1},
                "unique": True,
                "partialFilterExpression": {"event_id": {"$type": "string", "$ne": ""}},
            },
        ]
    )
    await ensure_paddle_events_unique_index(db)
    assert db.paddle_events.create_calls == []
    assert db.paddle_events.drop_calls == []


async def test_index_migration_create_index_failure_raises():
    db = _DB()
    db.paddle_events.create_index = AsyncMock(side_effect=RuntimeError("create failed"))
    with pytest.raises(RuntimeError, match="create failed"):
        await ensure_paddle_events_unique_index(db)


async def test_index_migration_drop_index_failure_raises():
    db = _DB(
        paddle_indexes=[
            {"name": "_id_", "key": {"_id": 1}},
            {"name": "event_id_1", "key": {"event_id": 1}, "unique": False},
        ]
    )
    db.paddle_events.drop_index = AsyncMock(side_effect=RuntimeError("drop failed"))
    with pytest.raises(RuntimeError, match="drop failed"):
        await ensure_paddle_events_unique_index(db)


async def test_index_migration_archive_failure_raises():
    now = datetime.now(timezone.utc)
    db = _DB(
        paddle_docs=[
            {"_id": "a", "event_id": "evt_dup", "status": "failed", "failed_at": now.isoformat()},
            {"_id": "b", "event_id": "evt_dup", "status": "processed", "processed_at": now.isoformat()},
        ]
    )
    db.paddle_events_dedup_archive.update_one = AsyncMock(side_effect=RuntimeError("archive failed"))
    with pytest.raises(RuntimeError, match="archive failed"):
        await ensure_paddle_events_unique_index(db)


async def test_index_migration_raises_when_target_index_absent_after_creation():
    db = _DB()
    db.paddle_events.create_index = AsyncMock(return_value="event_id_unique_partial")
    with pytest.raises(RuntimeError, match="index missing/incompatible"):
        await ensure_paddle_events_unique_index(db)


async def test_index_migration_raises_when_created_index_not_unique():
    db = _DB()

    async def _create_non_unique(_key, **_kwargs):
        db.paddle_events.indexes.append(
            {
                "name": "event_id_unique_partial",
                "key": {"event_id": 1},
                "unique": False,
                "partialFilterExpression": {"event_id": {"$type": "string", "$ne": ""}},
            }
        )
        return "event_id_unique_partial"

    db.paddle_events.create_index = AsyncMock(side_effect=_create_non_unique)
    with pytest.raises(RuntimeError, match="index missing/incompatible"):
        await ensure_paddle_events_unique_index(db)


async def test_index_migration_raises_when_created_index_has_wrong_partial_filter():
    db = _DB()

    async def _create_wrong_partial(_key, **_kwargs):
        db.paddle_events.indexes.append(
            {
                "name": "event_id_unique_partial",
                "key": {"event_id": 1},
                "unique": True,
                "partialFilterExpression": {"event_id": {"$exists": True}},
            }
        )
        return "event_id_unique_partial"

    db.paddle_events.create_index = AsyncMock(side_effect=_create_wrong_partial)
    with pytest.raises(RuntimeError, match="index missing/incompatible"):
        await ensure_paddle_events_unique_index(db)


async def test_index_migration_keeps_multiple_null_event_ids():
    db = _DB(
        paddle_docs=[
            {"_id": "n1", "event_id": None, "status": "processed"},
            {"_id": "n2", "event_id": None, "status": "failed"},
            {"_id": "ok", "event_id": "evt_unique", "status": "processed"},
        ]
    )
    await ensure_paddle_events_unique_index(db)
    assert len([doc for doc in db.paddle_events.docs if doc.get("event_id") is None]) == 2


async def test_index_migration_keeps_mixed_missing_null_and_real_event_ids():
    db = _DB(
        paddle_docs=[
            {"_id": "m1", "event_type": "legacy"},
            {"_id": "m2", "event_id": None},
            {"_id": "m3", "event_id": "evt_one"},
            {"_id": "m4", "event_id": "evt_two"},
        ]
    )
    await ensure_paddle_events_unique_index(db)
    assert len([doc for doc in db.paddle_events.docs if doc.get("event_id") in (None, "evt_one", "evt_two")]) == 4


async def test_cancel_subscription_accepts_iso_z_expiry():
    future = (datetime.now(timezone.utc) + timedelta(days=3)).isoformat().replace("+00:00", "Z")
    db = _DB(subscriptions=[{"user_id": "u_z", "status": "premium", "premium_expires_at": future}])
    sub = await cancel_subscription(db, "u_z")
    assert sub["status"] == SubscriptionStatus.PREMIUM


async def test_cancel_subscription_accepts_offset_expiry():
    future_offset = (datetime.now(timezone.utc) + timedelta(days=3)).astimezone(
        timezone(timedelta(hours=2))
    ).isoformat()
    db = _DB(subscriptions=[{"user_id": "u_offset", "status": "premium", "premium_expires_at": future_offset}])
    sub = await cancel_subscription(db, "u_offset")
    assert sub["status"] == SubscriptionStatus.PREMIUM


async def test_cancel_subscription_normalizes_legacy_naive_expiry():
    naive_future = (datetime.now(timezone.utc) + timedelta(days=2)).replace(tzinfo=None).isoformat()
    db = _DB(subscriptions=[{"user_id": "u_naive", "status": "premium", "premium_expires_at": naive_future}])
    sub = await cancel_subscription(db, "u_naive")
    assert sub["status"] == SubscriptionStatus.PREMIUM
    assert sub["premium_expires_at"].endswith("+00:00")


async def test_cancel_subscription_invalid_expiry_falls_back_to_free():
    db = _DB(subscriptions=[{"user_id": "u_bad", "status": "premium", "premium_expires_at": "not-a-date"}])
    sub = await cancel_subscription(db, "u_bad")
    assert sub["status"] == SubscriptionStatus.FREE


async def test_cancel_subscription_naive_datetime_parameter_treated_as_utc():
    naive_future = (datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None)
    db = _DB(subscriptions=[{"user_id": "u_dt_obj", "status": "premium"}])
    sub = await cancel_subscription(db, "u_dt_obj", premium_expires_at=naive_future)
    assert sub["status"] == SubscriptionStatus.PREMIUM


async def test_cancel_subscription_naive_datetime_stored_in_db_is_normalized():
    naive_future = (datetime.now(timezone.utc) + timedelta(days=1)).replace(tzinfo=None)
    db = _DB(subscriptions=[{"user_id": "u_db_naive", "status": "premium", "premium_expires_at": naive_future}])
    sub = await cancel_subscription(db, "u_db_naive")
    assert sub["status"] == SubscriptionStatus.PREMIUM
    assert sub["premium_expires_at"].endswith("+00:00")
