"""C338 — Mongo identity, concurrent PATCH and projected local-clock regressions."""

import asyncio
import os
from contextlib import ExitStack
from copy import deepcopy
from datetime import datetime, timezone
from unittest.mock import patch
from uuid import uuid4

import httpx
import pytest
import pytest_asyncio
from bson import ObjectId
from motor.motor_asyncio import AsyncIOMotorClient

from test_training_v2_preferences_endpoint import (
    _FakeDB,
    _MONDAY,
    _USER_A,
    _USER_B,
    _bearer,
    _patches,
    _request,
    _seed_cycle,
    server,
)


@pytest.mark.asyncio
@pytest.mark.parametrize("path,method", [
    ("/api/training/v2/preferences", "GET"),
    ("/api/training/v2/preferences", "PATCH"),
    ("/api/training/today", "GET"),
    ("/api/training/v2/week", "GET"),
])
async def test_ambiguous_legacy_preferences_fail_explicitly_without_writes(path, method):
    db = _FakeDB()
    _seed_cycle(db, _USER_A)
    db.training_prefs._docs.extend([
        {"_id": ObjectId(), "user_id": _USER_A, "sessions_per_week": 4},
        {"_id": _USER_A, "user_id": _USER_A, "sessions_per_week": 3},
    ])
    original = deepcopy(db.training_prefs._docs)
    response = await _request(
        method, path, fake_db=db, user_id=_USER_A,
        json={"sessions_per_week": 2} if method == "PATCH" else None,
    )
    assert response.status_code == 409, response.text
    assert "Duplicate training preferences" in response.json()["detail"]
    assert db.training_prefs._docs == original
    assert not db.training_prescription_snapshots._docs


@pytest.mark.asyncio
async def test_legacy_object_id_and_missing_revision_are_preserved():
    db = _FakeDB()
    legacy_id = ObjectId()
    db.training_prefs._docs.append({
        "_id": legacy_id, "user_id": _USER_A, "sessions_per_week": 4,
        "unrelated_preference": "preserved",
    })
    original_update = db.training_prefs.update_one

    async def check_filter(query, update, upsert=False):
        assert query == {"_id": legacy_id, "user_id": _USER_A, "preferences_revision": None}
        assert not upsert
        return await original_update(query, update, upsert)

    db.training_prefs.update_one = check_filter
    response = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=db, user_id=_USER_A,
        json={"preferred_training_days": ["tuesday", "sunday"]},
    )
    assert response.status_code == 200, response.text
    assert len(db.training_prefs._docs) == 1
    stored = db.training_prefs._docs[0]
    assert stored["_id"] == legacy_id
    assert stored["preferences_revision"] == 1
    assert stored["unrelated_preference"] == "preserved"
    assert response.json()["training_prefs"]["active_preferences"]["sessions_per_week"] == 4


@pytest.mark.asyncio
async def test_duplicate_preferences_of_another_user_do_not_block_update():
    db = _FakeDB()
    db.training_prefs._docs.extend([
        {"_id": ObjectId(), "user_id": _USER_B, "sessions_per_week": 3},
        {"_id": ObjectId(), "user_id": _USER_B, "sessions_per_week": 4},
    ])
    response = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=db, user_id=_USER_A,
        json={"sessions_per_week": 3},
    )
    assert response.status_code == 200, response.text
    assert len([doc for doc in db.training_prefs._docs if doc["user_id"] == _USER_A]) == 1


@pytest.mark.asyncio
async def test_document_replacement_during_readback_is_not_reported_as_success():
    db = _FakeDB()
    original_insert = db.training_prefs.insert_one

    async def replaced_after_insert(document):
        await original_insert({**document, "_id": ObjectId()})

    db.training_prefs.insert_one = replaced_after_insert
    response = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=db, user_id=_USER_A,
        json={"sessions_per_week": 3},
    )
    assert response.status_code == 409, response.text
    assert "document changed" in response.json()["detail"]


@pytest_asyncio.fixture
async def mongo_db():
    url = os.environ.get("C338_TEST_MONGO_URL")
    if not url:
        pytest.skip("Set C338_TEST_MONGO_URL to run real MongoDB concurrency/clock tests.")
    client = AsyncIOMotorClient(url, serverSelectionTimeoutMS=5000)
    db = client["runindex_c338_test_" + uuid4().hex]
    await client.admin.command("ping")
    await db.users.insert_one({
        "id": _USER_A, "email": _USER_A + "@example.com",
        "is_active": True, "is_email_verified": True,
    })
    try:
        yield db
    finally:
        await client.drop_database(db.name)
        client.close()


@pytest.mark.asyncio
@pytest.mark.parametrize("legacy", [False, True])
async def test_real_mongo_two_overlapping_patches_preserve_both_updates(mongo_db, legacy):
    db = mongo_db
    legacy_id = None
    if legacy:
        legacy_id = (await db.training_prefs.insert_one({
            "user_id": _USER_A, "sessions_per_week": 4,
        })).inserted_id
        assert isinstance(legacy_id, ObjectId)
    await db.training_prescription_snapshots.insert_one({
        "user_id": _USER_A, "prescription_id": "historical", "planned_date": "2026-09-10",
        "workout_type": "easy", "distance_km": 5,
    })
    snapshot = await db.training_prescription_snapshots.find_one({"user_id": _USER_A})
    original_load = server._load_training_preferences
    barrier = asyncio.Event()
    initial_reads = 0

    async def overlapping_reads(user_id):
        nonlocal initial_reads
        doc = await original_load(user_id)
        if initial_reads < 2:
            initial_reads += 1
            if initial_reads == 2:
                barrier.set()
            await asyncio.wait_for(barrier.wait(), timeout=5)
        return doc

    with ExitStack() as stack:
        for patcher in _patches(db, _MONDAY):
            stack.enter_context(patcher)
        stack.enter_context(patch.object(server, "_load_training_preferences", overlapping_reads))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
        ) as client:
            responses = await asyncio.gather(
                client.patch("/api/training/v2/preferences", headers=_bearer(_USER_A),
                             json={"sessions_per_week": 3}),
                client.patch("/api/training/v2/preferences", headers=_bearer(_USER_A),
                             json={"preferred_training_days": ["tuesday", "sunday"],
                                   "preferred_long_run_day": "sunday"}),
            )
    assert all(response.status_code == 200 for response in responses), [
        response.text for response in responses
    ]
    assert await db.training_prefs.count_documents({"user_id": _USER_A}) == 1
    stored = await db.training_prefs.find_one({"user_id": _USER_A})
    assert stored["_id"] == (legacy_id if legacy else _USER_A)
    assert stored["preferences_revision"] == 2
    assert stored["sessions_per_week"] == 3
    assert stored["preferred_training_days"] == ["tuesday", "sunday"]
    assert stored["preferred_long_run_day"] == "sunday"
    assert stored["effective_from"] == "2026-09-21"
    assert stored["active_preferences"]["sessions_per_week"] == (4 if legacy else None)
    assert await db.training_prescription_snapshots.find_one({"user_id": _USER_A}) == snapshot
    assert list((await db.training_prefs.index_information())) == ["_id_"]


@pytest.mark.asyncio
async def test_real_mongo_duplicates_are_not_merged_or_indexed(mongo_db):
    db = mongo_db
    await db.training_prefs.insert_many([
        {"user_id": _USER_A, "sessions_per_week": 4},
        {"_id": _USER_A, "user_id": _USER_A, "sessions_per_week": 3},
    ])
    before = await db.training_prefs.find({}).to_list(2)
    response = await _request(
        "PATCH", "/api/training/v2/preferences", fake_db=db, user_id=_USER_A,
        json={"sessions_per_week": 2},
    )
    assert response.status_code == 409
    assert await db.training_prefs.find({}).to_list(2) == before
    assert list((await db.training_prefs.index_information())) == ["_id_"]


@pytest.mark.asyncio
async def test_overlapping_legacy_writer_is_detected_without_silent_success(mongo_db):
    db = mongo_db
    original_load = server._load_training_preferences
    first_read = True

    async def legacy_insert_after_empty_read(user_id):
        nonlocal first_read
        document = await original_load(user_id)
        if first_read:
            first_read = False
            assert document is None
            await db.training_prefs.insert_one({"user_id": user_id, "sessions_per_week": 4})
        return document

    with patch.object(server, "_load_training_preferences", legacy_insert_after_empty_read):
        response = await _request(
            "PATCH", "/api/training/v2/preferences", fake_db=db, user_id=_USER_A,
            json={"sessions_per_week": 3},
        )
    assert response.status_code == 409, response.text
    assert "Duplicate training preferences" in response.json()["detail"]
    # No automatic deletion or guess at which pre-deployment writer was authoritative.
    assert await db.training_prefs.count_documents({"user_id": _USER_A}) == 2


@pytest.mark.asyncio
@pytest.mark.parametrize("offset_hours", [-5, 2, None])
@pytest.mark.parametrize("legacy_clock", [False, True])
async def test_real_clock_projection_keeps_local_sunday_monday_boundary(mongo_db, offset_hours, legacy_clock):
    from datetime import timedelta

    db = mongo_db
    now = datetime(2026, 9, 14, 0, 30, tzinfo=timezone.utc)
    if offset_hours is not None:
        gmt = datetime(2026, 9, 13, 20)
        local = (gmt + timedelta(hours=offset_hours)).isoformat()
        clock = (
            {"startTimeGMT": gmt.isoformat(), "startTimeLocal": local}
            if legacy_clock else {
                "garmin_activity": {
                    "start_time": gmt.isoformat(), "start_time_local": local,
                    "unneeded_large_payload": "not part of the clock",
                },
            }
        )
        await db.garmin_activities.insert_many([
            {
                "user_id": _USER_A, "start_time": gmt.isoformat(),
                **clock,
            },
            {"user_id": _USER_A, "start_time": "2026-09-13T23:00:00",
             "startTimeGMT": "invalid", "startTimeLocal": "invalid"},
        ])
    evidence = await db.garmin_activities.find({"user_id": _USER_A}).to_list(1000)
    expected = server._resolve_canonical_reference_date(now, evidence)
    from test_training_v2_preferences_endpoint import _make_fixed_datetime_class

    with patch.object(server, "db", db), patch.object(server, "datetime", _make_fixed_datetime_class(now)):
        assert await server._preferences_reference_date(_USER_A) == expected
    with ExitStack() as stack:
        for patcher in _patches(db, _MONDAY):
            stack.enter_context(patcher)
        stack.enter_context(patch.object(server, "datetime", _make_fixed_datetime_class(now)))
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
        ) as client:
            response = await client.patch(
                "/api/training/v2/preferences", headers=_bearer(_USER_A),
                json={"sessions_per_week": 3},
            )
    assert response.status_code == 200, response.text
    assert response.json()["training_prefs"]["effective_from"] == (
        "2026-09-14" if offset_hours == -5 else "2026-09-21"
    )
