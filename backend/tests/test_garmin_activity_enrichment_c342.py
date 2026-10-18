import asyncio
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from garmin import activity_details, activity_laps
from garmin import service


def run(coro):
    return asyncio.run(coro)


@pytest.fixture(autouse=True)
def allow_enrichment_pass(monkeypatch):
    monkeypatch.setattr("sync.rate_limiter.cooldown_ok", AsyncMock(return_value=True))


class Cursor:
    def __init__(self, docs):
        self.docs = docs
        self.sort_key = None
        self.limit_count = None

    def sort(self, key, direction):
        self.sort_key = key
        self.direction = direction
        return self

    def limit(self, count):
        self.limit_count = count
        return self

    async def to_list(self, length=None):
        docs = sorted(
            self.docs,
            key=lambda doc: doc.get(self.sort_key) or "",
            reverse=self.direction < 0,
        )
        return docs[:min(length or self.limit_count, self.limit_count)]


class Activities:
    def __init__(self, docs):
        self.docs = docs
        self.query = None
        self.cursor = None

    def find(self, query, projection=None):
        self.query = query
        cutoff = query["start_time"]["$gte"]
        docs = [
            doc for doc in self.docs
            if doc.get("user_id") == query["user_id"]
            and doc.get("source") == query["source"]
            and doc.get("start_time", "") >= cutoff
        ]
        self.cursor = Cursor(docs)
        return self.cursor


class Connections:
    def __init__(self, doc):
        self.doc = doc

    async def find_one(self, query, projection=None):
        return self.doc if self.doc and self.doc.get("user_id") == query["user_id"] else None


def activity(activity_id, *, days_ago=0, activity_type="running", details=None,
             details_fetch=None, laps=None, laps_fetch=None):
    start_time = (datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat()
    return {
        "user_id": "user-1",
        "source": "garmin",
        "external_id": activity_id,
        "activity_type": activity_type,
        "start_time": start_time,
        **({"activity_details": details} if details is not None else {}),
        **({"activity_details_fetch": details_fetch} if details_fetch is not None else {}),
        **({"activity_laps": laps} if laps is not None else {}),
        **({"activity_laps_fetch": laps_fetch} if laps_fetch is not None else {}),
    }


def make_db(activities, *, connected=True):
    connection = {
        "user_id": "user-1",
        "connected": connected,
        "garmin_username": "synthetic-account",
    }
    return SimpleNamespace(
        garmin_activities=Activities(activities),
        garmin_connections=Connections(connection),
    )


def test_new_running_activity_is_enqueued_after_summary_availability(monkeypatch):
    db = make_db([activity("123")])
    details = AsyncMock(return_value={"status": "queued"})
    laps = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    result = run(service._enqueue_recent_activity_details(db, "user-1"))

    assert result == {
        "status": "requested",
        "activity_id": "123",
        "details": {"status": "queued"},
        "laps": {"status": "queued"},
    }
    details.assert_awaited_once_with(db, "user-1", "123")
    laps.assert_awaited_once_with(db, "user-1", "123")
    assert db.garmin_activities.query["start_time"]["$gte"]


def test_non_running_and_invalid_activity_ids_are_skipped(monkeypatch):
    db = make_db([
        activity("--help"),
        activity("123", activity_type="cycling"),
        activity("456", activity_type="trail_running"),
    ])
    details = AsyncMock(return_value={"status": "queued"})
    laps = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    result = run(service._enqueue_recent_activity_details(db, "user-1"))

    assert result["activity_id"] == "456"
    details.assert_awaited_once_with(db, "user-1", "456")
    laps.assert_awaited_once_with(db, "user-1", "456")


def test_enriched_newest_activity_is_skipped_for_next_incomplete_run(monkeypatch):
    db = make_db([
        activity(
            "123",
            details={
                "schema_version": activity_details.SCHEMA_VERSION,
                "status": "no_data",
            },
            laps={"schema_version": activity_laps.SCHEMA_VERSION, "status": "empty"},
        ),
        activity("456", days_ago=1),
    ])
    details = AsyncMock(return_value={"status": "queued"})
    laps = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    result = run(service._enqueue_recent_activity_details(db, "user-1"))

    assert result["activity_id"] == "456"
    details.assert_awaited_once_with(db, "user-1", "456")
    laps.assert_awaited_once_with(db, "user-1", "456")


def test_in_progress_activity_is_not_replaced_by_another_target(monkeypatch):
    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    db = make_db([
        activity("123", details_fetch={"status": "running", "next_attempt_at": future}),
        activity("456", days_ago=1),
    ])
    details = AsyncMock(return_value={"status": "cooldown"})
    laps = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    result = run(service._enqueue_recent_activity_details(db, "user-1"))

    assert result["activity_id"] == "123"
    details.assert_awaited_once_with(db, "user-1", "123")
    laps.assert_awaited_once_with(db, "user-1", "123")


def test_failed_activity_respects_cooldown(monkeypatch):
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    db = make_db([
        activity("123", details_fetch={"status": "failed", "next_attempt_at": future},
                 laps_fetch={"status": "failed", "next_attempt_at": future}),
    ])
    details = AsyncMock()
    laps = AsyncMock()
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    assert run(service._enqueue_recent_activity_details(db, "user-1")) == {
        "status": "no_candidate",
    }
    details.assert_not_awaited()
    laps.assert_not_awaited()


def test_per_user_sync_cooldown_bounds_enrichment_passes(monkeypatch):
    db = make_db([activity("123")])
    monkeypatch.setattr(
        "sync.rate_limiter.cooldown_ok", AsyncMock(return_value=False),
    )
    details = AsyncMock()
    laps = AsyncMock()
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    assert run(service._enqueue_recent_activity_details(db, "user-1")) == {
        "status": "cooldown",
    }
    details.assert_not_awaited()
    laps.assert_not_awaited()


def test_redis_errors_do_not_fail_the_sync_or_report_false_success(monkeypatch):
    db = make_db([activity("123")])
    details = AsyncMock(side_effect=RuntimeError("synthetic Redis outage"))
    laps = AsyncMock(side_effect=RuntimeError("synthetic Redis outage"))
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    result = run(service._schedule_recent_activity_details(db, "user-1"))

    assert result["details"]["status"] == "queue_unavailable"
    assert result["laps"]["status"] == "queue_unavailable"
    details.assert_awaited_once()
    laps.assert_awaited_once()


def test_disconnected_account_never_enqueues(monkeypatch):
    db = make_db([activity("123")], connected=False)
    details = AsyncMock()
    laps = AsyncMock()
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    assert run(service._enqueue_recent_activity_details(db, "user-1")) == {
        "status": "disconnected",
    }
    details.assert_not_awaited()
    laps.assert_not_awaited()


def test_large_import_scans_bounded_recent_summaries_and_queues_one_activity(monkeypatch):
    now = datetime.now(timezone.utc)
    docs = [activity(str(index + 1)) for index in range(100)]
    for index, doc in enumerate(docs):
        doc["start_time"] = (now - timedelta(seconds=index)).isoformat()
    db = make_db(docs)
    details = AsyncMock(return_value={"status": "queued"})
    laps = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    result = run(service._enqueue_recent_activity_details(db, "user-1"))

    assert db.garmin_activities.cursor.limit_count == 50
    assert result["activity_id"] == "1"
    details.assert_awaited_once()
    laps.assert_awaited_once()


def test_concurrent_sync_orchestration_is_confined_to_one_target(monkeypatch):
    db = make_db([activity("123")])
    lock = asyncio.Lock()
    accepted = set()

    async def details_request(_db, _user_id, activity_id):
        async with lock:
            key = ("details", activity_id)
            if key in accepted:
                return {"status": "already_queued"}
            accepted.add(key)
            return {"status": "queued"}

    async def laps_request(_db, _user_id, activity_id):
        async with lock:
            key = ("laps", activity_id)
            if key in accepted:
                return {"status": "already_queued"}
            accepted.add(key)
            return {"status": "queued"}

    details = AsyncMock(side_effect=details_request)
    laps = AsyncMock(side_effect=laps_request)
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    async def scenario():
        return await asyncio.gather(
            service._enqueue_recent_activity_details(db, "user-1"),
            service._enqueue_recent_activity_details(db, "user-1"),
        )

    first, second = run(scenario())

    assert accepted == {("details", "123"), ("laps", "123")}
    assert first["activity_id"] == second["activity_id"] == "123"


def test_old_summaries_are_not_reconciled_as_a_historical_backfill(monkeypatch):
    db = make_db([activity("123", days_ago=45), activity("456", days_ago=90)])
    details = AsyncMock()
    laps = AsyncMock()
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    assert run(service._enqueue_recent_activity_details(db, "user-1")) == {
        "status": "no_candidate",
    }
    assert db.garmin_activities.query["start_time"]["$gte"]
    details.assert_not_awaited()
    laps.assert_not_awaited()


def test_targeted_worker_redelivery_after_restart_is_idempotent(monkeypatch):
    from garmin import activity_details
    from jobs import queue
    from workers import sync_worker

    fetch = AsyncMock(side_effect=[
        {"success": True, "status": "complete"},
        {"success": True, "status": "cached"},
    ])
    monkeypatch.setattr(activity_details, "fetch_activity_details", fetch)

    async def replay():
        await sync_worker._run_job(
            object(), queue.JOB_ACTIVITY_DETAILS, "user-1", "123",
        )
        await sync_worker._run_job(
            object(), queue.JOB_ACTIVITY_DETAILS, "user-1", "123",
        )

    run(replay())
    assert fetch.await_count == 2
    assert [call.args[2] for call in fetch.await_args_list] == ["123", "123"]
