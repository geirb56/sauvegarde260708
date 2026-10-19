import asyncio
import copy
import os
import re
import uuid
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from garmin import activity_details, activity_laps
from garmin import service


def run(coro):
    return asyncio.run(coro)


class Cursor:
    def __init__(self, docs):
        self.docs = docs

    async def to_list(self, length=None):
        return self.docs[:length]


def mongo_date(value):
    if isinstance(value, str):
        try:
            value = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    if not isinstance(value, datetime):
        return None
    if value.tzinfo is None:
        value = value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class Activities:
    def __init__(self, docs):
        self.docs = docs
        self.query = None
        self.cursor = None

    def aggregate(self, pipeline):
        self.pipeline = pipeline
        query = pipeline[0]["$match"]
        self.query = query
        docs = [
            {**doc, "_coverage_start": (
                mongo_date((doc.get("garmin_activity") or {}).get("start_time"))
                or mongo_date(doc.get("start_time"))
            ), "_coverage_id": str(doc.get("external_id") or "")}
            for doc in self.docs
            if doc.get("user_id") == query["user_id"]
            and doc.get("source") == query["source"]
            and isinstance(doc.get("activity_type"), str)
            and re.fullmatch(
                query["activity_type"]["$regex"], doc["activity_type"], re.IGNORECASE,
            )
        ]
        docs = sorted(
            (doc for doc in docs if doc["_coverage_start"] is not None),
            key=lambda doc: (doc["_coverage_start"], doc["_coverage_id"]),
            reverse=True,
        )[:pipeline[-1]["$limit"]]
        self.cursor = Cursor(docs)
        return self.cursor

    async def update_one(self, query, update, upsert=False):
        existing = next((
            doc for doc in self.docs
            if doc.get("user_id") == query["user_id"]
            and doc.get("external_id") == query["external_id"]
        ), None)
        if existing is not None:
            existing.update(update["$set"])
            return SimpleNamespace(modified_count=1, upserted_id=None)
        if upsert:
            self.docs.append(dict(update["$set"]))
            return SimpleNamespace(modified_count=0, upserted_id="synthetic-insert")
        return SimpleNamespace(modified_count=0, upserted_id=None)


class Connections:
    def __init__(self, doc):
        self.doc = doc

    async def find_one(self, query, projection=None):
        return copy.deepcopy(self.doc) if self.doc and self.doc.get("user_id") == query["user_id"] else None

    async def update_one(self, query, update):
        assert query == {"user_id": self.doc["user_id"]}
        self.doc.update(update["$set"])


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
    assert "start_time" not in db.garmin_activities.query


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


def test_pending_newest_activity_is_skipped_for_next_ready_run(monkeypatch):
    db = make_db([
        activity("123", details_fetch={"status": "running", "next_attempt_at": (
            datetime.now(timezone.utc) + timedelta(minutes=5)
        ).isoformat()}, laps_fetch={"status": "running", "next_attempt_at": (
            datetime.now(timezone.utc) + timedelta(minutes=5)
        ).isoformat()}),
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


def test_complete_phases_request_laps_only(monkeypatch):
    db = make_db([activity(
        "123",
        details={"schema_version": activity_details.SCHEMA_VERSION, "status": "complete"},
    )])
    details = AsyncMock(return_value={"status": "cooldown"})
    laps = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    result = run(service._enqueue_recent_activity_details(db, "user-1"))

    assert result["activity_id"] == "123"
    assert "details" not in result
    details.assert_not_awaited()
    laps.assert_awaited_once_with(db, "user-1", "123")


def test_complete_laps_request_phases_only(monkeypatch):
    db = make_db([activity(
        "123",
        laps={"schema_version": activity_laps.SCHEMA_VERSION, "status": "complete"},
    )])
    details = AsyncMock(return_value={"status": "queued"})
    laps = AsyncMock(return_value={"status": "cached"})
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    result = run(service._enqueue_recent_activity_details(db, "user-1"))

    assert result["activity_id"] == "123"
    assert "laps" not in result
    details.assert_awaited_once_with(db, "user-1", "123")
    laps.assert_not_awaited()


def test_cooldown_newest_activity_is_skipped_for_next_ready_run(monkeypatch):
    future = (datetime.now(timezone.utc) + timedelta(minutes=5)).isoformat()
    db = make_db([
        activity("123", details_fetch={"status": "failed", "next_attempt_at": future},
                 laps_fetch={"status": "failed", "next_attempt_at": future}),
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


def test_pending_phases_with_ready_laps_requests_laps_only(monkeypatch):
    future = (datetime.now(timezone.utc) + timedelta(minutes=10)).isoformat()
    db = make_db([activity(
        "123",
        details_fetch={"status": "running", "next_attempt_at": future},
    )])
    details = AsyncMock(return_value={"status": "queued"})
    laps = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    result = run(service._enqueue_recent_activity_details(db, "user-1"))

    assert result["activity_id"] == "123"
    assert "details" not in result
    details.assert_not_awaited()
    laps.assert_awaited_once_with(db, "user-1", "123")


def test_two_terminal_acquisitions_are_ignored(monkeypatch):
    db = make_db([activity(
        "123",
        details={"schema_version": activity_details.SCHEMA_VERSION, "status": "no_data"},
        laps={"schema_version": activity_laps.SCHEMA_VERSION, "status": "empty"},
    )])
    details = AsyncMock()
    laps = AsyncMock()
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    assert run(service._enqueue_recent_activity_details(db, "user-1")) == {
        "status": "no_candidate",
    }
    details.assert_not_awaited()
    laps.assert_not_awaited()


def test_expired_running_lease_is_ready_for_existing_requester(monkeypatch):
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    db = make_db([activity(
        "123",
        details_fetch={"status": "running", "next_attempt_at": expired},
        laps={"schema_version": activity_laps.SCHEMA_VERSION, "status": "empty"},
    )])
    details = AsyncMock(return_value={"status": "already_queued"})
    laps = AsyncMock()
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    result = run(service._enqueue_recent_activity_details(db, "user-1"))

    assert result["activity_id"] == "123"
    assert result["details"]["status"] == "already_queued"
    details.assert_awaited_once_with(db, "user-1", "123")
    laps.assert_not_awaited()


def test_expired_laps_lease_is_ready_for_existing_requester(monkeypatch):
    expired = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    db = make_db([activity(
        "123",
        details={"schema_version": activity_details.SCHEMA_VERSION, "status": "complete"},
        laps_fetch={"status": "queued", "next_attempt_at": expired},
    )])
    details = AsyncMock()
    laps = AsyncMock(return_value={"status": "already_queued"})
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    result = run(service._enqueue_recent_activity_details(db, "user-1"))

    assert result["activity_id"] == "123"
    assert result["laps"]["status"] == "already_queued"
    details.assert_not_awaited()
    laps.assert_awaited_once_with(db, "user-1", "123")


def test_redis_errors_do_not_fail_the_sync_or_report_false_success(monkeypatch):
    db = make_db([])
    details = AsyncMock(side_effect=RuntimeError("synthetic Redis outage"))
    laps = AsyncMock(side_effect=RuntimeError("synthetic Redis outage"))
    monkeypatch.setattr(service, "emit_activity_created", AsyncMock())
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    async def import_and_schedule():
        summary = {
            "external_id": "123",
            "source": "garmin",
            "activity_type": "running",
            "start_time": datetime.now(timezone.utc).isoformat(),
        }
        ingestion = await service._ingest_activities(db, "user-1", [summary])
        result = await service._schedule_recent_activity_details(db, "user-1")
        return ingestion, result

    ingestion, result = run(import_and_schedule())

    assert ingestion["new"] == 1
    assert db.garmin_activities.docs[0]["external_id"] == "123"
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

    assert db.garmin_activities.pipeline[-1] == {"$limit": 10}
    assert len(db.garmin_activities.cursor.docs) == 10
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


def test_old_runs_remain_eligible_without_an_age_cutoff(monkeypatch):
    db = make_db([activity("123", days_ago=45), activity("456", days_ago=90)])
    details = AsyncMock(return_value={"status": "queued"})
    laps = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr("garmin.activity_details.request_activity_details", details)
    monkeypatch.setattr("garmin.activity_laps.request_activity_laps", laps)

    assert run(service._enqueue_recent_activity_details(db, "user-1"))["activity_id"] == "123"
    assert "start_time" not in db.garmin_activities.query
    details.assert_awaited_once_with(db, "user-1", "123")
    laps.assert_awaited_once_with(db, "user-1", "123")


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


@pytest.fixture
def requesters(monkeypatch):
    details = AsyncMock(return_value={"status": "queued"})
    laps = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr(activity_details, "request_activity_details", details)
    monkeypatch.setattr(activity_laps, "request_activity_laps", laps)
    return details, laps


def large_history():
    """150 summaries, including >50 newer non-runs ahead of the first run."""
    now = datetime(2026, 1, 1, tzinfo=timezone.utc)
    docs = []
    for index in range(150):
        sport = "running" if index >= 60 and index % 3 == 0 else (
            "cycling", "walking", "swimming",
        )[index % 3]
        doc = activity(str(index + 1), activity_type=sport)
        doc["start_time"] = (now - timedelta(days=index)).isoformat()
        docs.append(doc)
    return docs


def test_150_activities_consider_only_latest_ten_runs(requesters):
    db = make_db(large_history())
    expected = [str(index + 1) for index in range(60, 90, 3)]

    async def scenario():
        selected = []
        for _ in range(11):
            before = [request.await_count for request in requesters]
            selected.append((await service._enqueue_recent_activity_details(db, "user-1"))["activity_id"])
            assert [request.await_count - count for request, count in zip(requesters, before)] == [1, 1]
            assert [doc["external_id"] for doc in db.garmin_activities.cursor.docs] == expected
        return selected

    assert run(scenario()) == expected + expected[:1]
    assert len(db.garmin_activities.docs) == 150


def test_three_runs_progress_to_completion_then_stop(requesters):
    db = make_db([activity(str(i), days_ago=i * 30) for i in range(1, 4)])

    async def complete(_db, _user_id, activity_id):
        doc = next(doc for doc in db.garmin_activities.docs if doc["external_id"] == activity_id)
        doc["activity_details"] = {"schema_version": activity_details.SCHEMA_VERSION, "status": "complete"}
        doc["activity_laps"] = {"schema_version": activity_laps.SCHEMA_VERSION, "status": "complete"}
        return {"status": "queued"}

    requesters[0].side_effect = complete

    async def scenario():
        results = [await service._enqueue_recent_activity_details(db, "user-1") for _ in range(5)]
        assert [result["activity_id"] for result in results[:3]] == ["1", "2", "3"]
        assert results[3:] == [{"status": "no_candidate"}] * 2

    run(scenario())
    assert requesters[0].await_count == requesters[1].await_count == 3


def test_completed_top_ten_do_not_expand_coverage_to_eleventh_run(requesters):
    docs = [activity(str(i), days_ago=i) for i in range(1, 12)]
    for doc in docs[:10]:
        doc["activity_details"] = {
            "schema_version": activity_details.SCHEMA_VERSION, "status": "complete",
        }
        doc["activity_laps"] = {
            "schema_version": activity_laps.SCHEMA_VERSION, "status": "complete",
        }
    db = make_db(docs)
    assert run(service._enqueue_recent_activity_details(db, "user-1")) == {"status": "no_candidate"}
    for request in requesters:
        request.assert_not_awaited()


@pytest.mark.parametrize("details_status,laps_status", [
    ("complete", "complete"), ("complete", "empty"),
    ("no_data", "complete"), ("no_data", "empty"),
])
def test_current_terminal_caches_never_repeat(details_status, laps_status, requesters):
    db = make_db([activity(
        "123",
        details={"schema_version": activity_details.SCHEMA_VERSION, "status": details_status},
        laps={"schema_version": activity_laps.SCHEMA_VERSION, "status": laps_status},
    )])
    for _ in range(3):
        assert run(service._enqueue_recent_activity_details(db, "user-1")) == {"status": "no_candidate"}
    for request in requesters:
        request.assert_not_awaited()


def test_stale_terminal_schema_remains_retryable(requesters):
    db = make_db([activity(
        "123", details={"schema_version": -1, "status": "complete"},
        laps={"schema_version": -1, "status": "empty"},
    )])
    assert run(service._enqueue_recent_activity_details(db, "user-1"))["activity_id"] == "123"
    for request in requesters:
        request.assert_awaited_once()


@pytest.mark.parametrize("status", ["failed", "running", "queued"])
def test_cooldown_or_pending_waits_then_retries_after_expiry(status, requesters):
    future = (datetime.now(timezone.utc) + timedelta(minutes=15)).isoformat()
    past = (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat()
    doc = activity(
        "123", details_fetch={"status": status, "next_attempt_at": future},
        laps_fetch={"status": status, "next_attempt_at": future},
    )
    db = make_db([doc])
    assert run(service._enqueue_recent_activity_details(db, "user-1")) == {"status": "no_candidate"}
    for request in requesters:
        request.assert_not_awaited()
    doc["activity_details_fetch"]["next_attempt_at"] = past
    doc["activity_laps_fetch"]["next_attempt_at"] = past
    assert run(service._enqueue_recent_activity_details(db, "user-1"))["activity_id"] == "123"
    for request in requesters:
        request.assert_awaited_once_with(db, "user-1", "123")


def test_rotation_prevents_new_runs_and_retryable_failures_starving_remaining_runs(requesters):
    db = make_db([activity(str(i), days_ago=i) for i in range(1, 11)])
    # A newest-first selector would choose the newly inserted run on every sync,
    # leaving 2..9 unselected. Even repeated failures must advance the cursor.
    requesters[0].side_effect = RuntimeError("synthetic temporary failure")
    requesters[1].return_value = {"status": "busy"}

    async def scenario():
        first = await service._enqueue_recent_activity_details(db, "user-1")
        assert first["activity_id"] == "1"
        selected = []
        for i in range(5):
            new_run = activity(str(100 + i))
            new_run["start_time"] = (datetime.now(timezone.utc) + timedelta(seconds=i)).isoformat()
            db.garmin_activities.docs.append(new_run)
            result = await service._enqueue_recent_activity_details(db, "user-1")
            selected.append(result["activity_id"])
        return selected

    assert run(scenario()) == ["2", "3", "4", "5", "104"]
    # At this point 6..10 have left the top ten: no promise for evicted runs.
    assert requesters[0].await_count == requesters[1].await_count == 6


def test_cursor_boundary_survives_previous_target_leaving_top_ten(requesters):
    db = make_db([activity(str(i), days_ago=i) for i in range(1, 11)])
    db.garmin_connections.doc["activity_details_coverage_cursor"] = {
        "start_time": db.garmin_activities.docs[-1]["start_time"], "external_id": "10",
    }
    db.garmin_activities.docs.append(activity("100"))
    assert run(service._enqueue_recent_activity_details(db, "user-1"))["activity_id"] == "100"
    assert "10" not in [doc["external_id"] for doc in db.garmin_activities.cursor.docs]


def test_persistent_cursor_is_scoped_to_user_and_survives_scheduler_restart(requesters):
    db = make_db([activity("1"), activity("2", days_ago=1)])
    assert run(service._enqueue_recent_activity_details(db, "user-1"))["activity_id"] == "1"
    # A new orchestration invocation has no process-local rotation state.
    restarted = make_db(copy.deepcopy(db.garmin_activities.docs))
    restarted.garmin_connections.doc = copy.deepcopy(db.garmin_connections.doc)
    assert run(service._enqueue_recent_activity_details(restarted, "user-1"))["activity_id"] == "2"
    other = make_db([activity("3")])
    other.garmin_connections.doc["user_id"] = "user-2"
    other.garmin_activities.docs[0]["user_id"] = "user-2"
    other.garmin_activities.docs.extend(copy.deepcopy(db.garmin_activities.docs))
    assert run(service._enqueue_recent_activity_details(other, "user-2"))["activity_id"] == "3"
    for request in requesters:
        assert [call.args[1:] for call in request.await_args_list] == [
            ("user-1", "1"), ("user-1", "2"), ("user-2", "3"),
        ]


def dated_history():
    docs = []
    for activity_id, start in [
        ("1", "2026-01-01T10:00:00Z"),
        ("2", datetime(2026, 1, 1, 10)),  # BSON datetime, naive UTC
        ("3", "2026-01-01T11:00:00+02:00"),  # actually 09:00 UTC
        ("4", "2026-01-01 08:00:00"),  # Garmin's naive, space-separated format
        ("5", "2026-01-01T07:00:00+00:00"),
        ("6", "2026-01-01T15:00:00+00:00"),  # local summary must not override GMT
        ("7", "not-a-date"),
        ("8", None),
        ("9", 123456),
        ("10", "2026-01-01"),  # legacy date-only string
        ("11", "2026-01-01T05:00:00Z"),
    ]:
        doc = activity(activity_id)
        doc["start_time"] = start
        docs.append(doc)
    docs[5]["garmin_activity"] = {"start_time": "2026-01-01T06:00:00Z"}
    docs[10]["garmin_activity"] = {"start_time": "invalid"}
    return docs


def test_actual_dates_and_deterministic_ties_not_lexical_or_bson_type_order(requesters):
    db = make_db(list(reversed(dated_history())))
    expected = ["2", "1", "3", "4", "5", "6", "11", "10"]

    async def scenario():
        selected = [
            (await service._enqueue_recent_activity_details(db, "user-1"))["activity_id"]
            for _ in expected
        ]
        assert selected == expected

    run(scenario())


def test_pipeline_limits_after_sport_and_date_sort_and_projects_no_detail_payloads(requesters):
    db = make_db([activity("123")])
    run(service._enqueue_recent_activity_details(db, "user-1"))
    match, project, valid_date, sort, limit = db.garmin_activities.pipeline
    assert match["$match"]["user_id"] == "user-1"
    assert match["$match"]["source"] == "garmin"
    assert sort == {"$sort": {"_coverage_start": -1, "_coverage_id": -1}}
    assert limit == {"$limit": 10}
    assert valid_date == {"$match": {"_coverage_start": {"$ne": None}}}
    fields = project["$project"]
    assert not {"activity_details", "activity_laps", "raw_payload"} & fields.keys()
    for expression, field in zip(fields["_coverage_start"]["$ifNull"], [
        "$garmin_activity.start_time", "$start_time",
    ]):
        assert expression == {"$convert": {
            "input": {"$cond": [
                {"$in": [{"$type": field}, ["string", "date"]]}, field, None,
            ]},
            "to": "date", "onError": None, "onNull": None,
        }}


@pytest.mark.parametrize("sport", [
    "run", "running", "trail_running", "trail_run", "treadmill_running", " RUNNING ",
])
def test_existing_running_aliases_are_retained(sport, requesters):
    db = make_db([activity("123", activity_type=sport)])
    assert run(service._enqueue_recent_activity_details(db, "user-1"))["activity_id"] == "123"


def test_training_other_sports_and_other_users_never_enter_top_ten(requesters):
    docs = [
        activity(str(i), activity_type=sport)
        for i, sport in enumerate(["cycling", "walking", "swimming", "hiking", None], 1)
    ]
    docs.extend([
        {**activity("6"), "source": "training_v2"},
        {**activity("7"), "user_id": "user-2"},
        activity("8", days_ago=90),
    ])
    db = make_db(docs)
    assert run(service._enqueue_recent_activity_details(db, "user-1"))["activity_id"] == "8"
    assert [doc["external_id"] for doc in db.garmin_activities.cursor.docs] == ["8"]


def test_initial_import_preserves_persisted_details_and_does_not_burst(requesters, monkeypatch):
    docs = large_history()
    first_run = docs[60]
    first_run.update({
        "activity_details": {
            "schema_version": activity_details.SCHEMA_VERSION, "status": "complete",
            "phases": [{"synthetic": "existing"}],
        },
        "activity_laps": {
            "schema_version": activity_laps.SCHEMA_VERSION, "status": "complete",
            "laps": [{"synthetic": "existing"}],
        },
    })
    original = copy.deepcopy(first_run)
    db = make_db([copy.deepcopy(first_run)])
    monkeypatch.setattr(service, "emit_activity_created", AsyncMock())

    async def scenario():
        summaries = copy.deepcopy(docs)
        summaries[60]["activity_details"] = None
        summaries[60]["activity_laps"] = None
        ingest = await service._ingest_activities(db, "user-1", summaries)
        assert ingest["new"] == 149
        result = await service._schedule_recent_activity_details(db, "user-1")
        assert result["activity_id"] == "64"

    run(scenario())
    persisted = next(doc for doc in db.garmin_activities.docs if doc["external_id"] == "61")
    assert persisted["activity_details"] == original["activity_details"]
    assert persisted["activity_laps"] == original["activity_laps"]
    for request in requesters:
        request.assert_awaited_once_with(db, "user-1", "64")


@pytest.mark.parametrize("history,expected", [
    (large_history, [str(index + 1) for index in range(60, 90, 3)]),
    (dated_history, ["2", "1", "3", "4", "5", "6", "11", "10"]),
])
def test_selector_on_local_mongodb_with_synthetic_history(history, expected, requesters):
    """Opt-in real Mongo date conversion/projection/sort, never production or Garmin."""
    uri = os.environ.get("C345_TEST_MONGO_URI")
    if not uri:
        pytest.skip("Set C345_TEST_MONGO_URI to an isolated local MongoDB")
    assert uri.startswith(("mongodb://127.0.0.1:", "mongodb://localhost:"))
    from motor.motor_asyncio import AsyncIOMotorClient

    async def scenario():
        client = AsyncIOMotorClient(uri, serverSelectionTimeoutMS=3000)
        db = client["c345_synthetic_" + uuid.uuid4().hex]
        try:
            await db.garmin_activities.insert_many(history())
            await db.garmin_activities.insert_many([
                {**activity("999"), "user_id": "user-2"},
                activity("998", activity_type=["running"]),
                activity("997", activity_type="cycling"),
                {**activity("996"), "source": "training_v2"},
            ])
            original = await db.garmin_activities.find({}).to_list(length=None)
            await db.garmin_connections.insert_one({
                "user_id": "user-1", "connected": True,
                "garmin_username": "synthetic-account",
            })
            selected = [
                (await service._enqueue_recent_activity_details(db, "user-1"))["activity_id"]
                for _ in range(len(expected) + 1)
            ]
            assert selected == expected + expected[:1]
            for request in requesters:
                assert request.await_count == len(expected) + 1
            assert await db.garmin_activities.find({}).to_list(length=None) == original

            # Verify that projecting only cache metadata retains independent states.
            for activity_id in expected:
                await db.garmin_activities.update_one(
                    {"user_id": "user-1", "external_id": activity_id},
                    {"$set": {
                        "activity_details": {
                            "schema_version": activity_details.SCHEMA_VERSION,
                            "status": "no_data", "phases": [],
                        },
                        "activity_laps": {
                            "schema_version": activity_laps.SCHEMA_VERSION,
                            "status": "empty", "laps": [],
                        },
                    }},
                )
            for request in requesters:
                request.reset_mock()
            assert await service._enqueue_recent_activity_details(db, "user-1") == {"status": "no_candidate"}
            for request in requesters:
                request.assert_not_awaited()
            await db.garmin_activities.update_one(
                {"user_id": "user-1", "external_id": expected[-1]},
                {"$unset": {"activity_laps": ""}},
            )
            result = await service._enqueue_recent_activity_details(db, "user-1")
            assert result["activity_id"] == expected[-1]
            requesters[0].assert_not_awaited()
            requesters[1].assert_awaited_once_with(db, "user-1", expected[-1])
        finally:
            await client.drop_database(db.name)
            client.close()

    run(scenario())
