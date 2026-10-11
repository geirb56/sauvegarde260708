"""Two real examples reconstructed into an envelope; no live Garmin or Mongo."""

import asyncio
import copy
import json
import threading
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from garmin import activity_laps as laps
from garmin.providers.gccli_provider import GccliProvider
from garmin.runner import GccliError, GccliRunner
from jobs import queue
from test_activity_details_pr321 import Collection, run


@pytest.fixture
def payload():
    reference = json.loads((Path(__file__).parent / "fixtures/garmin_laps_fixture.json").read_text())
    return {"activityId": reference["envelope"]["activityId"], "eventDTOs": [],
            "lapDTOs": [reference["lap_full_example"], reference["lap_partial_example"]]}


def test_real_examples_preserve_source_and_partial_distance(payload):
    normalized = laps.normalize_activity_laps(payload, "garmin-24346252881")
    assert len(normalized) == 2
    assert normalized[1]["lap_index"] == 22
    assert normalized[1]["order"] == 21
    assert normalized[1]["distance_m"] == 274.53
    assert normalized[1]["max_speed_mps"] == 3.191
    assert normalized[1]["average_speed_mps"] == 3.196
    for raw, lap in zip(payload["lapDTOs"], normalized):
        assert set(lap) == set(laps.FIELDS.values())
        for source, target in laps.FIELDS.items():
            assert lap[target] == raw.get(source)


def test_optional_fields_null_and_sensitive_fields_excluded(payload):
    payload["lapDTOs"] = [{"lapIndex": 1, "messageIndex": 0, "distance": 400,
                          "startLatitude": 1, "endLongitude": 2, "strideLength": 123,
                          "connectIQMeasurement": [{"secret": "excluded"}], "lengthDTOs": [{}]}]
    lap = laps.normalize_activity_laps(payload, payload["activityId"])[0]
    assert lap["distance_m"] == 400
    assert all(lap[key] is None for key in lap if key not in {"distance_m", "lap_index", "order"})
    assert set(lap) == set(laps.FIELDS.values())


@pytest.mark.parametrize("value", [24346252881, "24346252881", "garmin-24346252881", "00024346252881"])
def test_identifiers(value):
    assert laps.validate_activity_id(value) == "24346252881"


@pytest.mark.parametrize("value", [None, True, 1.0, 0, "-1", "garmin-", "1;ls", "--help", "1" * 31])
def test_invalid_identifiers(value):
    with pytest.raises(ValueError):
        laps.validate_activity_id(value)


def test_empty_is_valid_but_documentary_fixture_is_not_input(payload):
    payload["lapDTOs"] = []
    assert laps.normalize_activity_laps(payload, payload["activityId"]) == []
    reference = json.loads((Path(__file__).parent / "fixtures/garmin_laps_fixture.json").read_text())
    with pytest.raises(ValueError):
        laps.normalize_activity_laps(reference, payload["activityId"])


@pytest.mark.parametrize("bad", [None, {}, [], {"activityId": 24346252881},
                               {"activityId": 24346252881, "lapDTOs": None},
                               {"activityId": 24346252881, "lapDTOs": {}},
                               {"activityId": "24346252881", "lapDTOs": []}])
def test_malformed_envelopes(bad):
    with pytest.raises(ValueError):
        laps.normalize_activity_laps(bad, "24346252881")


@pytest.mark.parametrize("field,value", [
    ("distance", "1"), ("duration", True), ("averageHR", float("nan")),
    ("maxSpeed", float("inf")), ("distance", -1), ("elevationGain", -1),
    ("duration", 10 ** 1000), ("lapIndex", None), ("messageIndex", -1),
    ("lapIndex", 1.0), ("intensityType", {}), ("startTimeGMT", "yesterday"),
    ("startTimeGMT", "2026-09-13T08:00:00+02:00"), ("activityId", 1),
])
def test_invalid_lap_values_fail_closed(payload, field, value):
    payload["lapDTOs"][0][field] = value
    with pytest.raises(ValueError):
        laps.normalize_activity_laps(payload, payload["activityId"])


@pytest.mark.parametrize("change", ["duplicate", "reverse", "time", "order", "id", "events", "size", "lap"])
def test_invalid_order_and_identity(payload, change):
    if change == "duplicate":
        payload["lapDTOs"].append(copy.deepcopy(payload["lapDTOs"][-1]))
    elif change == "reverse":
        payload["lapDTOs"].reverse()
    elif change == "time":
        payload["lapDTOs"][-1]["startTimeGMT"] = "2026-09-12T10:00:00"
    elif change == "order":
        payload["lapDTOs"][-1]["messageIndex"] = 0
    elif change == "id":
        payload["activityId"] = 1
    elif change == "events":
        payload["eventDTOs"] = None
    elif change == "size":
        payload["lapDTOs"] *= 501
    else:
        payload["lapDTOs"] = [None]
    with pytest.raises(ValueError):
        laps.normalize_activity_laps(payload, "24346252881")


def test_zero_and_negative_absolute_altitude_are_real(payload):
    payload["lapDTOs"][0].update(distance=0, minElevation=-10, maxElevation=-5)
    normalized = laps.normalize_activity_laps(payload, payload["activityId"])
    assert normalized[0]["distance_m"] == 0
    assert normalized[0]["min_elevation_m"] == -10


def test_runner_provider_account_and_command(payload, tmp_path):
    runner = GccliRunner(home=str(tmp_path))
    runner._run_json = Mock(return_value=payload)
    provider = GccliProvider(runner, account="synthetic-a")
    assert len(provider.get_activity_laps("a", "garmin-24346252881")) == 2
    runner._run_json.assert_called_once_with(
        ["activity", "splits", "24346252881"], account="synthetic-a", single_attempt=True,
    )
    runner._run_json.reset_mock()
    with pytest.raises(GccliError):
        GccliProvider(runner, allow_global_account=True).get_activity_laps("a", "123")
    runner._run_json.assert_not_called()


@pytest.fixture
def db():
    return SimpleNamespace(
        garmin_activities=Collection([
            {"user_id": "a", "external_id": "24346252881", "source": "garmin",
             "activity_day": "2026-09-13", "activity_details": {"phases": []}},
            {"user_id": "b", "external_id": "24346252881", "source": "garmin"},
        ]),
        garmin_connections=Collection([
            {"user_id": "a", "connected": True, "garmin_username": "synthetic-a"},
        ]),
    )


@pytest.fixture
def provider(payload, monkeypatch):
    provider = Mock()
    provider.get_activity_laps.return_value = laps.normalize_activity_laps(payload, payload["activityId"])
    monkeypatch.setattr(laps, "get_provider_for_user", Mock(return_value=provider))
    return provider


def test_persistence_cache_isolation_redelivery(db, provider):
    assert run(laps.fetch_activity_laps(db, "a", "24346252881"))["success"]
    assert run(laps.fetch_activity_laps(db, "a", "garmin-24346252881"))["status"] == "cached"
    provider.get_activity_laps.assert_called_once_with("a", "24346252881")
    doc = db.garmin_activities.docs[0]
    assert doc["activity_day"] == "2026-09-13"
    assert doc["activity_details"] == {"phases": []}
    assert "activity_laps" not in db.garmin_activities.docs[1]
    assert run(laps.get_activity_laps(db, "c", "24346252881")) == {"status": "not_found"}
    assert run(laps.fetch_activity_laps(db, "c", "24346252881"))["status"] == "not_found"


def test_negative_cache_and_version(db, provider):
    provider.get_activity_laps.return_value = []
    run(laps.fetch_activity_laps(db, "a", "24346252881"))
    assert db.garmin_activities.docs[0]["activity_laps"]["status"] == "empty"
    assert run(laps.fetch_activity_laps(db, "a", "24346252881"))["status"] == "cached"
    db.garmin_activities.docs[0]["activity_laps"]["schema_version"] = 0
    run(laps.fetch_activity_laps(db, "a", "24346252881"))
    assert provider.get_activity_laps.call_count == 2


def test_retry_preserves_old_cache(db, provider):
    old = {"schema_version": 0, "status": "complete", "laps": [{"historical": True}]}
    db.garmin_activities.docs[0]["activity_laps"] = copy.deepcopy(old)
    provider.get_activity_laps.side_effect = ValueError("malformed")
    assert not run(laps.fetch_activity_laps(db, "a", "24346252881"))["success"]
    assert db.garmin_activities.docs[0]["activity_laps"] == old
    assert run(laps.fetch_activity_laps(db, "a", "24346252881"))["status"] == "deferred"
    state = db.garmin_activities.docs[0]["activity_laps_fetch"]
    state["next_attempt_at"] = "2000-01-01T00:00:00+00:00"
    provider.get_activity_laps.side_effect = None
    assert run(laps.fetch_activity_laps(db, "a", "24346252881"))["success"]


def test_post_writes_status_before_queue_and_repeated_request(db, monkeypatch):
    async def enqueue(*args):
        assert run_status(db) == "queued"
        return {"status": "queued"}

    def run_status(db):
        return db.garmin_activities.docs[0]["activity_laps_fetch"]["status"]

    call = AsyncMock(side_effect=enqueue)
    monkeypatch.setattr(queue, "enqueue_activity_laps", call)
    assert run(laps.request_activity_laps(db, "a", "24346252881"))["status"] == "queued"
    assert run(laps.get_activity_laps(db, "a", "24346252881"))["fetch_status"] == "queued"
    assert run(laps.request_activity_laps(db, "a", "24346252881"))["status"] == "queued"
    assert call.call_count == 1
    assert run(laps.request_activity_laps(db, "c", "24346252881"))["status"] == "not_found"


@pytest.mark.parametrize("failure", [False, True])
def test_queue_busy_or_unavailable_is_not_false_queued(db, monkeypatch, failure):
    call = AsyncMock(side_effect=RuntimeError() if failure else None,
                     return_value={"status": "busy"})
    monkeypatch.setattr(queue, "enqueue_activity_laps", call)
    if failure:
        with pytest.raises(RuntimeError):
            run(laps.request_activity_laps(db, "a", "24346252881"))
    else:
        run(laps.request_activity_laps(db, "a", "24346252881"))
    assert run(laps.get_activity_laps(db, "a", "24346252881"))["fetch_status"] == "retryable_error"


def test_already_pending_job_keeps_mongo_queued(db, monkeypatch):
    monkeypatch.setattr(queue, "enqueue_activity_laps", AsyncMock(
        return_value={"status": "already_queued"},
    ))
    assert run(laps.request_activity_laps(db, "a", "24346252881"))["status"] == "already_queued"
    assert run(laps.get_activity_laps(db, "a", "24346252881"))["fetch_status"] == "queued"


def test_concurrent_claim_expired_lease_and_stale_write(db, provider):
    entered, release = threading.Event(), threading.Event()
    expected = provider.get_activity_laps.return_value

    def blocked(*args):
        entered.set()
        release.wait(5)
        return expected

    provider.get_activity_laps.side_effect = blocked

    async def scenario():
        first = asyncio.create_task(laps.fetch_activity_laps(db, "a", "24346252881"))
        try:
            assert await asyncio.to_thread(entered.wait, 5)
            assert (await laps.fetch_activity_laps(db, "a", "24346252881"))["status"] == "deferred"
            state = db.garmin_activities.docs[0]["activity_laps_fetch"]
            state["next_attempt_at"] = "2000-01-01T00:00:00+00:00"
            assert (await laps.get_activity_laps(db, "a", "24346252881"))["error_code"] == "lease_expired"
            provider.get_activity_laps.side_effect = None
            assert (await laps.fetch_activity_laps(db, "a", "24346252881"))["success"]
        finally:
            release.set()
        assert (await first)["status"] == "superseded"

    run(scenario())


def test_interrupted_worker_lease_recovery(db, provider):
    db.garmin_activities.docs[0]["activity_laps_fetch"] = {
        "status": "running", "token": "interrupted",
        "next_attempt_at": (datetime.now(timezone.utc) - timedelta(seconds=1)).isoformat(),
    }
    assert run(laps.fetch_activity_laps(db, "a", "24346252881"))["success"]


def test_session_unavailable_persists_recoverable_error(db, provider):
    db.garmin_connections.docs.clear()
    assert not run(laps.fetch_activity_laps(db, "a", "24346252881"))["success"]
    assert run(laps.get_activity_laps(db, "a", "24346252881"))["fetch_status"] == "retryable_error"
    provider.get_activity_laps.assert_not_called()


def test_authenticated_routes_and_cache_only(db, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    from api.garmin import garmin_router
    from auth.dependencies import get_current_user

    app = FastAPI()
    app.state.db = db
    app.include_router(garmin_router, prefix="/api")
    client = TestClient(app)
    path = "/api/garmin/activities/garmin-24346252881/laps"
    assert client.get(path).status_code in {401, 403}
    assert client.post(path).status_code in {401, 403}
    app.dependency_overrides[get_current_user] = lambda: {"id": "a"}
    factory = Mock(side_effect=AssertionError("GET cannot fetch"))
    monkeypatch.setattr(laps, "get_provider_for_user", factory)
    assert client.get(path).json()["fetch_status"] == "not_requested"
    assert not db.garmin_activities.writes
    monkeypatch.setattr(queue, "enqueue_activity_laps", AsyncMock(return_value={"status": "queued"}))
    assert client.post(path).status_code == 202
    assert client.get(path).json()["fetch_status"] == "queued"
    assert client.get("/api/garmin/activities/--help/laps").status_code == 422
    app.dependency_overrides[get_current_user] = lambda: {"id": "c"}
    assert client.get(path).status_code == 404
    assert client.post(path).status_code == 404
    factory.assert_not_called()


def test_later_sync_preserves_laps_even_if_provider_supplies_cache_fields(db, monkeypatch):
    from garmin import service

    cached = {"schema_version": 1, "status": "complete", "laps": [{"distance_m": 400}]}
    db.garmin_activities.docs[0]["activity_laps"] = copy.deepcopy(cached)
    db.garmin_activities.docs[0]["activity_laps_fetch"] = {"status": "complete"}
    monkeypatch.setattr(service, "emit_activity_created", AsyncMock())
    run(service._ingest_activities(db, "a", [{
        "external_id": "24346252881", "source": "garmin",
        "activity_laps": None, "activity_laps_fetch": None,
    }]))
    assert db.garmin_activities.docs[0]["activity_laps"] == cached
    assert db.garmin_activities.docs[0]["activity_laps_fetch"] == {"status": "complete"}
