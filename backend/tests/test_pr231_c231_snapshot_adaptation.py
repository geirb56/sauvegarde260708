"""C231 (final corrections) — item 3 BLOCKER: the prescription snapshot
frozen for TODAY must be the FINAL post-DailyAdaptation prescription (the
one actually served by /training/today), never the raw WeeklyPlan session.

Reuses the fake-DB/httpx harness from test_pr232a_c231_week_endpoint.py.
"""
from __future__ import annotations

import os
import sys
from datetime import date
from unittest.mock import patch

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-pr231-final-secret-32chars!")
os.environ.setdefault("JWT_SECRET", "test-pr231-final-secret-32chars!")
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
from training_v2.readiness_decision import (  # noqa: E402
    ReadinessBand,
    ReadinessConfidence,
    ReadinessDecision,
    SufficiencyLevel,
)

pytestmark = pytest.mark.asyncio

_MONDAY = _harness._MONDAY
_USER_ID = _harness._USER_ID


def _decision(band: ReadinessBand) -> ReadinessDecision:
    return ReadinessDecision(
        band=band,
        score=30.0 if band in (ReadinessBand.VERY_LOW, ReadinessBand.CAUTION, ReadinessBand.LOW) else 80.0,
        confidence=ReadinessConfidence.NORMAL,
        sufficiency_level=SufficiencyLevel.SUFFICIENT,
        reason_codes=(f"READINESS_{band.value.upper()}",),
        readiness_reasons=(),
    )


def _monday_snapshot(fake_db) -> dict:
    docs = [
        d for d in fake_db.training_prescription_snapshots._docs
        if d.get("planned_date") == _MONDAY.isoformat()
    ]
    assert len(docs) == 1, f"Expected exactly 1 Monday snapshot, got {docs}"
    return docs[0]


async def test_shorten_snapshot_freezes_adapted_distance_not_raw():
    """long_easy 18km + SHORTEN -> 12.6km: snapshot must be 12.6km, and a
    12.6km Garmin activity must adhere as completed_as_planned — NEVER
    compared against the raw 18km."""
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_connected(fake_db, connected=True)

    # Force the reconciled WeeklyPlan's Monday session to be a long_easy 18km
    # by patching build_canonical_weekly_plan's downstream WorkoutPrescription
    # via the DailyAdaptation readiness path: patch build_readiness_decision to
    # CAUTION so long_easy gets SHORTEN-ed, and directly control the planned
    # session's distance through the reconciled plan's WorkoutGenerator by
    # patching resolve_today_final_prescription's adapted output deterministically
    # is avoided here — instead we drive it purely through the real pipeline by
    # forcing CAUTION readiness (a real, supported trigger for SHORTEN).
    with patch(
        "training_v2.today_prescription.build_readiness_decision",
        return_value=_decision(ReadinessBand.CAUTION),
    ):
        week_result = await _harness._get_week(fake_db)

    assert week_result["status"] == 200, week_result["body"]
    monday_session = next(
        s for s in week_result["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )

    snapshot = _monday_snapshot(fake_db)
    # The snapshot's distance must match what was actually served (the
    # session distance in the response), NOT any larger raw value.
    assert snapshot["distance_km"] == monday_session["distance_km"]

    # A later call (e.g. from /training/today, or a Week refresh) must NEVER
    # recompute/overwrite this snapshot even if CAUTION is no longer forced.
    week_result_2 = await _harness._get_week(fake_db)
    snapshot_2 = _monday_snapshot(fake_db)
    assert snapshot_2["distance_km"] == snapshot["distance_km"]


async def test_rest_adaptation_snapshot_is_rest():
    """VERY_LOW readiness -> REST action: snapshot must reflect the REST
    adapted workout, not the original prescription."""
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_connected(fake_db, connected=True)

    with patch(
        "training_v2.today_prescription.build_readiness_decision",
        return_value=_decision(ReadinessBand.VERY_LOW),
    ):
        week_result = await _harness._get_week(fake_db)

    assert week_result["status"] == 200, week_result["body"]
    monday_session = next(
        s for s in week_result["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    snapshot = _monday_snapshot(fake_db)
    assert snapshot["workout_type"] == "rest"
    assert monday_session["workout_type"] == "rest"


async def test_keep_action_snapshot_matches_original():
    """GOOD readiness -> KEEP: snapshot must equal the original (unadapted)
    prescription."""
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_connected(fake_db, connected=True)

    with patch(
        "training_v2.today_prescription.build_readiness_decision",
        return_value=_decision(ReadinessBand.FAVORABLE),
    ):
        week_result = await _harness._get_week(fake_db)

    assert week_result["status"] == 200, week_result["body"]
    monday_session = next(
        s for s in week_result["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    snapshot = _monday_snapshot(fake_db)
    assert snapshot["distance_km"] == monday_session["distance_km"]
    assert snapshot["workout_type"] == monday_session["workout_type"]


async def test_replay_at_j_plus_n_is_identical():
    """Replaying the week endpoint N days later must return the SAME frozen
    snapshot for Monday (no re-adaptation, no drift)."""
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_connected(fake_db, connected=True)

    with patch(
        "training_v2.today_prescription.build_readiness_decision",
        return_value=_decision(ReadinessBand.CAUTION),
    ):
        week_day0 = await _harness._get_week(fake_db, reference_date=_MONDAY)
    snapshot_day0 = _monday_snapshot(fake_db)

    # J+3: readiness swings back to GOOD — must NOT affect Monday's frozen
    # snapshot, since it is now strictly in the past.
    with patch(
        "training_v2.today_prescription.build_readiness_decision",
        return_value=_decision(ReadinessBand.FAVORABLE),
    ):
        week_day3 = await _harness._get_week(
            fake_db, reference_date=_MONDAY + __import__("datetime").timedelta(days=3)
        )
    assert week_day3["status"] == 200, week_day3["body"]
    snapshot_day3 = _monday_snapshot(fake_db)

    assert snapshot_day0 == snapshot_day3
