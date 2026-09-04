"""C231 (P0 #2) — tests for training_v2.served_prescription.

Reuses the fake-DB harness from test_pr232a_c231_week_endpoint.py.
"""
from __future__ import annotations

import os
import sys
from datetime import date

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-pr231-served-secret-32chars!")
os.environ.setdefault("JWT_SECRET", "test-pr231-served-secret-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
_TESTS_DIR = os.path.dirname(os.path.abspath(__file__))
for _p in (_BACKEND_DIR, _TESTS_DIR):
    if _p not in sys.path:
        sys.path.insert(0, _p)

import test_pr232a_c231_week_endpoint as _harness  # noqa: E402
from training_v2.served_prescription import get_or_create_served_prescription  # noqa: E402
from training_v2.workout_generator import WorkoutPrescription  # noqa: E402

pytestmark = pytest.mark.asyncio

_USER_ID = _harness._USER_ID
_MONDAY = date(2024, 6, 10)
_PID = f"{_USER_ID}:{_MONDAY.isoformat()}:monday"


def _prescription(distance_km: float) -> WorkoutPrescription:
    return WorkoutPrescription(
        day="monday",
        workout_type="long_easy",
        intensity_class="low",
        distance_km=distance_km,
        duration_minutes=None,
        reason_codes=(),
    )


async def test_first_call_creates_snapshot_and_returns_its_own_candidate():
    fake_db = _harness._FakeDB()
    candidate = _prescription(18.0)
    result = await get_or_create_served_prescription(
        fake_db, user_id=_USER_ID, prescription_id=_PID,
        planned_date=_MONDAY, served_candidate=candidate,
    )
    assert result.distance_km == 18.0
    docs = [d for d in fake_db.training_prescription_snapshots._docs if d.get("prescription_id") == _PID]
    assert len(docs) == 1
    assert docs[0]["distance_km"] == 18.0


async def test_existing_snapshot_is_authoritative_never_overwritten():
    fake_db = _harness._FakeDB()
    first = await get_or_create_served_prescription(
        fake_db, user_id=_USER_ID, prescription_id=_PID,
        planned_date=_MONDAY, served_candidate=_prescription(18.0),
    )
    assert first.distance_km == 18.0

    # A second caller computes a DIFFERENT candidate (e.g. readiness changed
    # -> SHORTEN to 12.6km) — the already-frozen 18.0km value must win.
    second = await get_or_create_served_prescription(
        fake_db, user_id=_USER_ID, prescription_id=_PID,
        planned_date=_MONDAY, served_candidate=_prescription(12.6),
    )
    assert second.distance_km == 18.0

    docs = [d for d in fake_db.training_prescription_snapshots._docs if d.get("prescription_id") == _PID]
    assert len(docs) == 1, "Exactly one snapshot document must ever exist for this prescription_id."


async def test_week_first_then_today_returns_identical_value():
    """Week calls first with an 18km live candidate; Today calls afterwards
    with a differently-adapted 12.6km candidate. Both must converge on the
    SAME (Week's) 18km value, because Week's call won the race."""
    fake_db = _harness._FakeDB()
    week_result = await get_or_create_served_prescription(
        fake_db, user_id=_USER_ID, prescription_id=_PID,
        planned_date=_MONDAY, served_candidate=_prescription(18.0),
    )
    today_result = await get_or_create_served_prescription(
        fake_db, user_id=_USER_ID, prescription_id=_PID,
        planned_date=_MONDAY, served_candidate=_prescription(12.6),
    )
    assert week_result.distance_km == today_result.distance_km == 18.0


async def test_today_first_then_week_returns_identical_value():
    fake_db = _harness._FakeDB()
    today_result = await get_or_create_served_prescription(
        fake_db, user_id=_USER_ID, prescription_id=_PID,
        planned_date=_MONDAY, served_candidate=_prescription(12.6),
    )
    week_result = await get_or_create_served_prescription(
        fake_db, user_id=_USER_ID, prescription_id=_PID,
        planned_date=_MONDAY, served_candidate=_prescription(18.0),
    )
    assert today_result.distance_km == week_result.distance_km == 12.6


async def test_concurrent_calls_result_in_single_snapshot_and_same_value():
    import asyncio

    fake_db = _harness._FakeDB()
    results = await asyncio.gather(
        get_or_create_served_prescription(
            fake_db, user_id=_USER_ID, prescription_id=_PID,
            planned_date=_MONDAY, served_candidate=_prescription(18.0),
        ),
        get_or_create_served_prescription(
            fake_db, user_id=_USER_ID, prescription_id=_PID,
            planned_date=_MONDAY, served_candidate=_prescription(12.6),
        ),
    )
    docs = [d for d in fake_db.training_prescription_snapshots._docs if d.get("prescription_id") == _PID]
    assert len(docs) == 1
    assert results[0].distance_km == results[1].distance_km
    assert results[0].distance_km == docs[0]["distance_km"]


async def test_rest_day_candidate_is_preserved_identically():
    fake_db = _harness._FakeDB()
    rest_candidate = WorkoutPrescription(
        day="monday", workout_type="rest", intensity_class="rest",
        distance_km=None, duration_minutes=None, reason_codes=(),
    )
    result = await get_or_create_served_prescription(
        fake_db, user_id=_USER_ID, prescription_id=_PID,
        planned_date=_MONDAY, served_candidate=rest_candidate,
    )
    assert result.workout_type == "rest"
    assert result.distance_km is None
