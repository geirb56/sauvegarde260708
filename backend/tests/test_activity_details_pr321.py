"""PR321 contract tests. ALL typed-splits data below is SYNTHETIC.

No fixture represents the real activity 24671804067 or a Garmin connection.
Mongo and Redis are in-memory test doubles; subprocess calls are mocked.
"""

import asyncio
import copy
import json
import subprocess
import threading
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from garmin import activity_details as details
from garmin.data_layer import normalize_typed_splits
from garmin.domain_adapter import mongo_garmin_to_domain, mongo_garmin_to_observed_activity
from garmin.providers.gccli_provider import GccliProvider
from garmin.runner import GccliError, GccliRunner
from jobs import queue

SYNTHETIC_SPLITS = [
    {"splitType": "WARMUP", "duration": 600},
    {"splitType": "INTERVAL_ACTIVE", "duration": 240, "distance": 1000,
     "averageSpeed": 4.1, "averageHR": 165, "maxHR": 175},
    {"splitType": "INTERVAL_RECOVERY", "duration": 180, "distance": 0},
    {"splitType": "COOLDOWN"},
    {"splitType": "UNRECOGNIZED"},
]


def run(coro):
    return asyncio.run(coro)


def test_synthetic_parsing_preserves_order_native_types_and_available_metrics():
    phases = normalize_typed_splits({"splitDTOs": SYNTHETIC_SPLITS})
    assert [p["phase_type"] for p in phases] == [
        "warmup", "effort", "recovery", "cooldown", "unknown",
    ]
    assert [p["order"] for p in phases] == list(range(5))
    assert phases[1]["native_type"] == "INTERVAL_ACTIVE"
    assert phases[1]["duration_s"] == 240
    assert phases[1]["distance_m"] == 1000
    assert phases[1]["average_speed_mps"] == 4.1
    assert phases[1]["average_hr"] == 165
    assert phases[1]["max_hr"] == 175
    assert phases[2]["distance_m"] == 0
    assert phases[3]["duration_s"] is None
    assert all(p["source"] == "garmin" for p in phases)


@pytest.mark.parametrize("value", [None, True, "240", -1, float("inf"), float("nan")])
def test_missing_or_invalid_measurements_are_not_fabricated(value):
    phase = normalize_typed_splits([{"splitType": "INTERVAL_ACTIVE", "duration": value}])[0]
    assert phase["duration_s"] is None
    assert phase["average_speed_mps"] is None
    assert phase["average_hr"] is None


@pytest.mark.parametrize("raw", [None, {}, {"splits": []}, [None], [{}],
                                     [{"splitType": ""}], [SYNTHETIC_SPLITS[0]] * 1001])
def test_unverified_shapes_fail_closed(raw):
    with pytest.raises(ValueError):
        normalize_typed_splits(raw)


@pytest.mark.parametrize("raw", [[], {"splitDTOs": []}])
def test_recognized_empty_data(raw):
    assert normalize_typed_splits(raw) == []


def test_runner_uses_existing_command_auth_and_json_boundary(tmp_path):
    runner = GccliRunner(home=str(tmp_path))
    runner._run_json = Mock(return_value=SYNTHETIC_SPLITS)
    assert runner.fetch_activity_typed_splits("123", "synthetic-account") == SYNTHETIC_SPLITS
    runner._run_json.assert_called_once_with(
        ["activity", "typed-splits", "123"], account="synthetic-account", single_attempt=True,
    )


@pytest.mark.parametrize("activity_id", ["--help", "1;ls", "../123", "", None, "1" * 31])
def test_runner_rejects_non_activity_arguments(tmp_path, activity_id):
    runner = GccliRunner(home=str(tmp_path))
    runner._run_json = Mock()
    with pytest.raises(ValueError):
        runner.fetch_activity_typed_splits(activity_id, "synthetic-account")
    runner._run_json.assert_not_called()


def test_provider_requires_per_user_account_even_for_global_provider():
    runner = Mock()
    with pytest.raises(GccliError):
        GccliProvider(runner, allow_global_account=True).get_activity_phases("u", "123")
    runner.fetch_activity_typed_splits.assert_not_called()


@pytest.mark.parametrize("failure", [
    subprocess.TimeoutExpired("gccli", 15),
    SimpleNamespace(returncode=1, stdout=b"", stderr=b"synthetic failure"),
    SimpleNamespace(returncode=0, stdout=b"invalid JSON", stderr=b""),
])
def test_runner_simulated_errors(tmp_path, monkeypatch, failure):
    runner = GccliRunner(home=str(tmp_path), max_retries=1)
    monkeypatch.setattr(runner, "is_available", lambda: True)
    call = Mock(side_effect=failure) if isinstance(failure, Exception) else Mock(return_value=failure)
    monkeypatch.setattr(subprocess, "run", call)
    with pytest.raises(GccliError):
        runner.fetch_activity_typed_splits("123", "synthetic-account")


def _value(doc, path):
    for key in path.split("."):
        if not isinstance(doc, dict) or key not in doc:
            return None
        doc = doc[key]
    return doc


def _matches(doc, query):
    for key, expected in query.items():
        if key == "$or":
            if not any(_matches(doc, sub) for sub in expected):
                return False
        elif key == "$nor":
            if any(_matches(doc, sub) for sub in expected):
                return False
        elif isinstance(expected, dict):
            value = _value(doc, key)
            if "$exists" in expected and (value is not None) != expected["$exists"]:
                return False
            if "$lte" in expected and (value is None or value > expected["$lte"]):
                return False
            if "$in" in expected and value not in expected["$in"]:
                return False
        elif _value(doc, key) != expected:
            return False
    return True


class Collection:
    def __init__(self, docs):
        self.docs = copy.deepcopy(docs)
        self.writes = []

    async def find_one(self, query, projection=None):
        return next((copy.deepcopy(d) for d in self.docs if _matches(d, query)), None)

    async def update_one(self, query, update, upsert=False):
        self.writes.append((copy.deepcopy(query), copy.deepcopy(update), upsert))
        for doc in self.docs:
            if _matches(doc, query):
                before = copy.deepcopy(doc)
                doc.update(copy.deepcopy(update["$set"]))
                return SimpleNamespace(modified_count=int(before != doc), upserted_id=None)
        if upsert:
            self.docs.append(copy.deepcopy(update["$set"]))
            return SimpleNamespace(modified_count=0, upserted_id="synthetic-insert")
        return SimpleNamespace(modified_count=0, upserted_id=None)

    async def count_documents(self, query):
        return sum(_matches(d, query) for d in self.docs)


@pytest.fixture
def db():
    return SimpleNamespace(
        garmin_activities=Collection([
            {"user_id": "a", "external_id": "123", "source": "garmin",
             "start_time": "2026-10-01T10:00:00", "duration": 3000, "distance": 9000},
            {"user_id": "b", "external_id": "123", "source": "garmin"},
            {"user_id": "a", "external_id": "456", "source": "other"},
        ]),
        garmin_connections=Collection([
            {"user_id": "a", "connected": True, "garmin_username": "synthetic-a"},
            {"user_id": "b", "connected": True, "garmin_username": "synthetic-b"},
        ]),
    )


@pytest.fixture
def provider(monkeypatch):
    provider = Mock()
    provider.get_activity_phases.return_value = normalize_typed_splits(SYNTHETIC_SPLITS)
    factory = Mock(return_value=provider)
    monkeypatch.setattr(details, "get_provider_for_user", factory)
    return provider, factory


def test_targeted_persistence_idempotence_and_user_isolation(db, provider):
    assert run(details.fetch_activity_details(db, "a", "123"))["success"]
    assert run(details.fetch_activity_details(db, "a", "123"))["status"] == "cached"
    provider[0].get_activity_phases.assert_called_once_with("a", "123")
    provider[1].assert_called_once_with("a", garmin_account="synthetic-a")
    assert "activity_details" not in db.garmin_activities.docs[1]
    assert db.garmin_activities.docs[0]["duration"] == 3000
    assert all(not write[2] for write in db.garmin_activities.writes)


def test_no_access_to_foreign_or_other_provider_activities(db, provider):
    assert run(details.fetch_activity_details(db, "unknown", "123"))["status"] == "not_found"
    assert run(details.fetch_activity_details(db, "a", "456"))["status"] == "not_found"
    provider[1].assert_not_called()


def test_errors_do_not_cache_empty_or_erase_details_and_have_cooldown(db, provider):
    old_details = {"schema_version": 0, "phases": [{"native_type": "historical"}]}
    db.garmin_activities.docs[0]["activity_details"] = old_details
    provider[0].get_activity_phases.side_effect = GccliError("synthetic failure")
    assert not run(details.fetch_activity_details(db, "a", "123"))["success"]
    assert db.garmin_activities.docs[0]["activity_details"] == old_details
    assert run(details.fetch_activity_details(db, "a", "123"))["status"] == "deferred"
    assert provider[0].get_activity_phases.call_count == 1


def test_empty_result_is_negatively_cached(db, provider):
    provider[0].get_activity_phases.return_value = []
    run(details.fetch_activity_details(db, "a", "123"))
    assert db.garmin_activities.docs[0]["activity_details"]["status"] == "no_data"
    assert run(details.fetch_activity_details(db, "a", "123"))["status"] == "cached"


def test_disconnected_account_never_calls_provider(db, provider):
    db.garmin_connections.docs[0]["connected"] = False
    assert not run(details.fetch_activity_details(db, "a", "123"))["success"]
    provider[1].assert_not_called()


def test_concurrent_fetches_share_atomic_activity_lease(db, provider):
    entered = threading.Event()
    release = threading.Event()

    def blocked(*args):
        entered.set()
        assert release.wait(timeout=5)
        return normalize_typed_splits(SYNTHETIC_SPLITS)

    provider[0].get_activity_phases.side_effect = blocked

    async def scenario():
        first = asyncio.create_task(details.fetch_activity_details(db, "a", "123"))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            assert (await details.fetch_activity_details(db, "a", "123"))["status"] == "deferred"
        finally:
            release.set()
        assert (await first)["success"]

    run(scenario())
    assert provider[0].get_activity_phases.call_count == 1


def test_stale_completion_cannot_overwrite_new_claim(db, provider):
    def superseded(*args):
        db.garmin_activities.docs[0]["activity_details_fetch"]["token"] = "new-claim"
        return normalize_typed_splits(SYNTHETIC_SPLITS)

    provider[0].get_activity_phases.side_effect = superseded
    assert run(details.fetch_activity_details(db, "a", "123"))["status"] == "superseded"
    assert "activity_details" not in db.garmin_activities.docs[0]


def test_summary_sync_cannot_overwrite_enrichment_or_reemit_created(db, provider, monkeypatch):
    from garmin import service

    run(details.fetch_activity_details(db, "a", "123"))
    original = copy.deepcopy(db.garmin_activities.docs[0]["activity_details"])
    emit = AsyncMock()
    monkeypatch.setattr(service, "emit_activity_created", emit)
    summary = {
        "external_id": "123", "source": "garmin", "duration": 3100,
        "activity_details": None, "activity_details_fetch": None,
    }
    assert run(service._ingest_activities(db, "a", [summary]))["new"] == 0
    assert db.garmin_activities.docs[0]["activity_details"] == original
    emit.assert_not_awaited()


def test_historical_domain_and_performed_contracts_unchanged(db, provider):
    doc = db.garmin_activities.docs[0]
    before_domain = mongo_garmin_to_domain(doc)
    before_observed = mongo_garmin_to_observed_activity(doc, user_id="a")
    run(details.fetch_activity_details(db, "a", "123"))
    assert mongo_garmin_to_domain(doc) == before_domain
    assert mongo_garmin_to_observed_activity(doc, user_id="a") == before_observed
    assert "km_splits" not in doc


class Redis:
    def __init__(self):
        self.values = {}
        self.payloads = []

    async def set(self, key, value, nx=False, ex=None):
        if nx and key in self.values:
            return False
        self.values[key] = value
        return True

    async def lpush(self, key, payload):
        self.payloads.append(json.loads(payload))

    async def delete(self, key):
        self.values.pop(key, None)

    async def eval(self, script, numkeys, key, job_id, action, ttl):
        if self.values.get(key) != job_id:
            return 0
        if action == "release":
            self.values.pop(key)
        return 1


def test_queue_bounds_one_target_per_user_and_isolates_users(monkeypatch):
    redis = Redis()
    monkeypatch.setattr(queue, "get_redis", lambda: redis)
    assert run(queue.enqueue_activity_details("a", "123"))["status"] == "queued"
    assert run(queue.enqueue_activity_details("a", "789"))["status"] == "already_queued"
    assert run(queue.enqueue_activity_details("b", "123"))["status"] == "queued"
    assert len(redis.payloads) == 2
    assert redis.payloads[0]["activity_id"] == "123"
    assert redis.payloads[0]["type"] == queue.JOB_ACTIVITY_DETAILS
    assert not queue._should_update_sync_progress(queue.JOB_ACTIVITY_DETAILS)


def test_enqueue_outage_releases_pending_flag(monkeypatch):
    redis = Redis()
    redis.lpush = AsyncMock(side_effect=RuntimeError("synthetic redis outage"))
    monkeypatch.setattr(queue, "get_redis", lambda: redis)
    with pytest.raises(RuntimeError):
        run(queue.enqueue_activity_details("a", "123"))
    assert not redis.values


def test_explicit_request_cached_and_unknown_do_not_enqueue(db, provider, monkeypatch):
    enqueue = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr(queue, "enqueue_activity_details", enqueue)
    assert run(details.request_activity_details(db, "a", "123"))["status"] == "queued"
    run(details.fetch_activity_details(db, "a", "123"))
    assert run(details.request_activity_details(db, "a", "123"))["status"] == "cached"
    assert run(details.request_activity_details(db, "other", "123"))["status"] == "not_found"
    enqueue.assert_awaited_once_with("a", "123")


def test_worker_dispatches_only_explicit_target(db, monkeypatch):
    from workers import sync_worker

    fetch = AsyncMock(return_value={"success": True})
    monkeypatch.setattr(details, "fetch_activity_details", fetch)
    assert run(sync_worker._run_job(db, queue.JOB_ACTIVITY_DETAILS, "a", "123"))["success"]
    fetch.assert_awaited_once_with(db, "a", "123")


def test_optional_provider_contract_is_backward_compatible():
    from garmin.providers.base import Provider

    assert Provider.get_activity_phases(object(), "a", "123") is None


def test_unsupported_provider_does_not_cache_no_data(db, provider):
    provider[0].get_activity_phases.return_value = None
    assert not run(details.fetch_activity_details(db, "a", "123"))["success"]
    assert "activity_details" not in db.garmin_activities.docs[0]


def test_cached_state_is_rechecked_in_atomic_claim(db, provider, monkeypatch):
    original_update = db.garmin_activities.update_one

    async def race(query, update, upsert=False):
        db.garmin_activities.docs[0]["activity_details"] = {
            "schema_version": 1, "status": "complete", "phases": [],
        }
        return await original_update(query, update, upsert=upsert)

    monkeypatch.setattr(db.garmin_activities, "update_one", race)
    assert run(details.fetch_activity_details(db, "a", "123"))["status"] == "cached"
    provider[0].get_activity_phases.assert_not_called()


def test_worker_reuses_user_lock_and_ack_without_sync_progress(db, monkeypatch):
    from workers import sync_worker

    redis = Redis()
    redis.incr = AsyncMock()
    monkeypatch.setattr(sync_worker.rate_limiter, "acquire_global_slot",
                        AsyncMock(return_value=True))
    monkeypatch.setattr(sync_worker.rate_limiter, "release_global_slot", AsyncMock())
    cooldown = AsyncMock()
    monkeypatch.setattr(sync_worker.rate_limiter, "set_cooldown", cooldown)
    ack = AsyncMock()
    monkeypatch.setattr(sync_worker, "ack_job", ack)
    fetch = AsyncMock(return_value={"success": True, "status": "cached"})
    monkeypatch.setattr(details, "fetch_activity_details", fetch)
    job = {"id": "synthetic-job", "type": queue.JOB_ACTIVITY_DETAILS,
           "user_id": "a", "activity_id": "123", "attempts": 0}
    run(sync_worker.process_job(db, redis, "synthetic-raw", job))
    fetch.assert_awaited_once_with(db, "a", "123")
    ack.assert_awaited_once_with("synthetic-raw", "synthetic-job")
    cooldown.assert_not_awaited()
    assert not redis.values


def test_http_phases_are_authenticated_scoped_and_cache_only(db, provider, monkeypatch):
    import httpx
    from fastapi import FastAPI
    from api.garmin import garmin_router, get_current_user

    app = FastAPI()
    app.state.db = db
    app.include_router(garmin_router, prefix="/api")
    app.dependency_overrides[get_current_user] = lambda: {"id": "a"}
    enqueue = AsyncMock(return_value={"status": "queued"})
    monkeypatch.setattr(queue, "enqueue_activity_details", enqueue)

    async def scenario():
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test",
        ) as client:
            path = "/api/garmin/activities/123/phases"
            response = await client.get(path)
            assert response.status_code == 200
            assert response.json()["activity_details"] is None
            provider[1].assert_not_called()
            enqueue.assert_not_awaited()
            assert (await client.post(path)).status_code == 202
            assert (await client.get("/api/garmin/activities/456/phases")).status_code == 404
            assert (await client.post("/api/garmin/activities/456/phases")).status_code == 404
            assert (await client.get("/api/garmin/activities/invalid/phases")).status_code == 422
            enqueue.side_effect = RuntimeError("synthetic outage")
            assert (await client.post(path)).status_code == 503
            app.dependency_overrides.clear()
            assert (await client.get(path)).status_code == 401

    run(scenario())


def test_worker_defers_lease_contention_without_ack_or_consuming_retry(db, monkeypatch):
    from workers import sync_worker
    from datetime import datetime, timedelta, timezone

    redis = Redis()
    monkeypatch.setattr(sync_worker.rate_limiter, "acquire_global_slot",
                        AsyncMock(return_value=True))
    monkeypatch.setattr(sync_worker.rate_limiter, "release_global_slot", AsyncMock())
    retry_at = (datetime.now(timezone.utc) + timedelta(seconds=900)).isoformat()
    monkeypatch.setattr(details, "fetch_activity_details", AsyncMock(return_value={
        "success": False, "status": "deferred", "retry_at": retry_at,
    }))
    ack = AsyncMock()
    requeue = AsyncMock()
    monkeypatch.setattr(sync_worker, "ack_job", ack)
    monkeypatch.setattr(sync_worker, "requeue_job", requeue)
    job = {"id": "synthetic-job", "type": queue.JOB_ACTIVITY_DETAILS,
           "user_id": "a", "activity_id": "123", "attempts": 1}
    run(sync_worker.process_job(db, redis, "synthetic-raw", job))
    ack.assert_not_awaited()
    requeue.assert_awaited_once()
    payload = json.loads(requeue.call_args.args[2])
    assert payload["attempts"] == 1
    assert payload["not_before"] == datetime.fromisoformat(retry_at).timestamp()


def test_pending_ownership_does_not_delete_a_newer_job():
    redis = Redis()
    key = queue._pending_key(queue.JOB_ACTIVITY_DETAILS, "a")
    redis.values[key] = "new-job"
    assert run(queue.maintain_details_pending(redis, "a", "old-job", release=True)) == 0
    assert redis.values[key] == "new-job"
    assert run(queue.maintain_details_pending(redis, "a", "new-job")) == 1
    assert run(queue.maintain_details_pending(redis, "a", "new-job", release=True)) == 1
    assert key not in redis.values
