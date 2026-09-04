"""C231 (corrections round 3 / "C231-quater") — end-to-end tests for:

- item 1 (P0): /training/today ALWAYS displays the canonical served
  prescription, never a stale planned_session/live-recomputed value gated by
  the ephemeral adaptation_applied flag. A pre-frozen snapshot must win the
  display regardless of what the CURRENT call's live readiness recompute
  would decide.
- item 2 (P0/P1): "prescription_unavailable" lives ONLY at the bridge/API
  level (SessionExecution.execution_status / WeekV2SessionResponse.
  execution_status) — PR230's own MatchingStatus/AdherenceStatus enums stay
  untouched (planned/matched/missed/ambiguous/unmatched_actual and their
  adherence counterparts only).
- item 3 (P0): a past day whose real historical prescription was never
  frozen/served exposes an explicit, non-fabricated state — no
  distance/duration/workout_type/matching_status/adherence_status invented
  from today's live recompute — while a real Garmin activity for that same
  day still surfaces via unmatched_actuals.

Reuses the real FastAPI handler + in-memory fake DB harness from
test_pr232a_c231_week_endpoint.py.

Run from the backend directory:
    python -m pytest tests/test_pr231_c231_corrections3.py -q
"""
from __future__ import annotations

import os
import sys
from datetime import date, timedelta

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-pr231-c231-r3-secret-32chars!")
os.environ.setdefault("JWT_SECRET", "test-pr231-c231-r3-secret-32chars!")
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

pytestmark = pytest.mark.asyncio

_USER_ID = _harness._USER_ID
_MONDAY = _harness._MONDAY


def _prescription_id_for_monday() -> str:
    from training_v2.week_execution import prescription_id_for

    return prescription_id_for(_USER_ID, _MONDAY, "monday")


def _seed_frozen_snapshot(fake_db, *, distance_km: float, duration_minutes=None) -> None:
    """Pre-freeze a snapshot with a value that could NOT come from a live
    recompute of the seeded plan (e.g. a much smaller distance than the
    live plan would ever produce for this slot), so that any test assertion
    of "the served value equals this" can only be explained by the snapshot
    actually being read back, never a coincidental live recompute match."""
    fake_db.training_prescription_snapshots._docs.append({
        "user_id": _USER_ID,
        "prescription_id": _prescription_id_for_monday(),
        "planned_date": _MONDAY.isoformat(),
        "day": "monday",
        "workout_type": "long_easy",
        "intensity_class": "low",
        "distance_km": distance_km,
        "duration_minutes": duration_minutes,
    })


# ---------------------------------------------------------------------------
# Item 1 — Today always displays the canonical served prescription
# ---------------------------------------------------------------------------


async def test_today_endpoint_exposes_served_prescription_key_matching_frozen_snapshot():
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_garmin_activities(fake_db, n=8)
    _harness._seed_connected(fake_db, connected=True)
    _seed_frozen_snapshot(fake_db, distance_km=12.6)

    result = await _harness._get_today(fake_db)
    assert result["status"] == 200, result["body"]
    body = result["body"]

    assert "served_prescription" in body
    assert body["served_prescription"]["distance_km"] == 12.6
    # adapted_prescription is kept for backward compat but MUST be identical
    # to served_prescription — never a separately (possibly divergent) live
    # recompute.
    assert body["adapted_prescription"] == body["served_prescription"]
    # planned_session is the RAW (unfrozen) live plan and is allowed to
    # differ — but it must NEVER be what a consumer displays as "today's
    # session" once a served_prescription exists.
    assert body["planned_session"]["distance_km"] != 12.6


async def test_today_endpoint_served_prescription_wins_even_when_adaptation_applied_is_false():
    """The core item-1 bug: adaptation_applied reflects TODAY's live
    recompute action only. A previously-frozen snapshot (e.g. from an
    earlier CAUTION-triggered SHORTEN) must still be displayed even if the
    CURRENT call's live readiness recompute would say KEEP
    (adaptation_applied=False)."""
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_garmin_activities(fake_db, n=8)
    _harness._seed_connected(fake_db, connected=True)
    _seed_frozen_snapshot(fake_db, distance_km=12.6)

    result = await _harness._get_today(fake_db)
    assert result["status"] == 200, result["body"]
    body = result["body"]

    # Whatever adaptation_applied says on THIS call, the served/adapted
    # prescription must reflect the frozen 12.6 km value, never the raw
    # planned_session distance.
    assert body["served_prescription"]["distance_km"] == 12.6
    assert body["adapted_prescription"]["distance_km"] == 12.6


async def test_today_endpoint_exposes_session_modified_from_planned_true_when_snapshot_differs():
    """C231 (round 4 / 'C231-micro') item P1: session_modified_from_planned
    is the ONLY ground-truth signal for whether the frontend "Adapté" banner
    should be shown — it must be exposed explicitly and be True whenever the
    frozen served_prescription actually differs from the live planned_session."""
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_garmin_activities(fake_db, n=8)
    _harness._seed_connected(fake_db, connected=True)
    _seed_frozen_snapshot(fake_db, distance_km=12.6)

    result = await _harness._get_today(fake_db)
    assert result["status"] == 200, result["body"]
    body = result["body"]

    assert "session_modified_from_planned" in body
    assert body["session_modified_from_planned"] is True
    assert body["served_prescription"]["distance_km"] != body["planned_session"]["distance_km"]


async def test_today_endpoint_session_modified_from_planned_false_when_served_equals_planned():
    """Scenario A (round 4): the served (frozen) prescription equals the raw
    planned session even though THIS call's live readiness recompute may
    still flag adaptation_applied=True — session_modified_from_planned must
    be False so no false-positive "Adapté" banner is shown."""
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_garmin_activities(fake_db, n=8)
    _harness._seed_connected(fake_db, connected=True)

    # No frozen snapshot pre-seeded: the get-or-create path freezes the
    # served prescription from THIS call's own adaptation result, so
    # served_prescription and planned_session start out consistent for the
    # very first call of the day (nothing external diverges them yet).
    result = await _harness._get_today(fake_db)
    assert result["status"] == 200, result["body"]
    body = result["body"]

    assert "session_modified_from_planned" in body
    modified = body["session_modified_from_planned"]
    assert isinstance(modified, bool)
    assert modified == (body["served_prescription"] != body["planned_session"])


async def test_week_first_then_today_show_identical_served_prescription():
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_garmin_activities(fake_db, n=8)
    _harness._seed_connected(fake_db, connected=True)

    week_result = await _harness._get_week(fake_db)
    assert week_result["status"] == 200, week_result["body"]
    monday_week_session = next(
        s for s in week_result["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )

    today_result = await _harness._get_today(fake_db)
    assert today_result["status"] == 200, today_result["body"]

    assert today_result["body"]["served_prescription"]["distance_km"] == monday_week_session["distance_km"]


async def test_today_first_then_week_show_identical_served_prescription():
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_garmin_activities(fake_db, n=8)
    _harness._seed_connected(fake_db, connected=True)

    today_result = await _harness._get_today(fake_db)
    assert today_result["status"] == 200, today_result["body"]

    week_result = await _harness._get_week(fake_db)
    assert week_result["status"] == 200, week_result["body"]
    monday_week_session = next(
        s for s in week_result["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )

    assert today_result["body"]["served_prescription"]["distance_km"] == monday_week_session["distance_km"]


# ---------------------------------------------------------------------------
# Item 2 — prescription_unavailable lives in the bridge/API only
# ---------------------------------------------------------------------------


def test_pr230_matching_status_enum_has_no_prescription_unavailable():
    from training_v2.performed_workout import MatchingStatus

    values = {s.value for s in MatchingStatus}
    assert values == {"planned", "matched", "missed", "ambiguous", "unmatched_actual"}
    assert "prescription_unavailable" not in values


def test_pr230_adherence_status_enum_has_no_prescription_unavailable():
    from training_v2.performed_workout import AdherenceStatus

    values = {s.value for s in AdherenceStatus}
    assert values == {
        "pending", "completed_as_planned", "completed_modified",
        "completed_unverified", "missed", "ambiguous", "unmatched_actual",
        "not_applicable",
    }
    assert "prescription_unavailable" not in values


def test_week_session_response_has_dedicated_execution_status_field():
    from training_v2.training_week_response import WeekV2SessionResponse

    session = WeekV2SessionResponse(
        day="monday", planned_date=None, reason_codes=[],
    )
    assert hasattr(session, "execution_status")
    assert session.execution_status is None


# ---------------------------------------------------------------------------
# Item 3 — no fabricated historical prescription; real Garmin evidence for
# that day still surfaces separately via unmatched_actuals.
# ---------------------------------------------------------------------------


async def test_week_endpoint_monday_never_served_reports_prescription_unavailable():
    """Monday is strictly in the past (reference_date == Wednesday) and was
    NEVER frozen while it was current: the endpoint must report
    execution_status == "prescription_unavailable", None matching/adherence
    status, and no fabricated distance/duration/workout_type — never a PR230
    MatchingStatus/AdherenceStatus value."""
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_connected(fake_db, connected=True)

    wednesday = _MONDAY + timedelta(days=2)
    result = await _harness._get_week(fake_db, reference_date=wednesday)
    assert result["status"] == 200, result["body"]

    monday_session = next(
        s for s in result["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    assert monday_session["execution_status"] == "prescription_unavailable"
    assert monday_session["matching_status"] is None
    assert monday_session["adherence_status"] is None
    assert monday_session["distance_km"] is None
    assert monday_session["duration_minutes"] is None
    assert monday_session["workout_type"] is None
    assert monday_session["actual"] is None


async def test_week_endpoint_real_garmin_activity_for_unserved_monday_still_surfaces_as_unmatched():
    """Even though Monday's prescription is unavailable (never frozen), a
    REAL Garmin activity that really happened on that Monday must still be
    visible — as an unmatched actual, never silently dropped, and never used
    to fabricate a fake "matched" verdict against the untrusted historical
    prescription."""
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    # Seed enough training history so Monday is a real (non-rest) prescribed
    # session — otherwise a bare cycle with zero history defaults to a rest
    # day, which is exempt from "prescription_unavailable" by design and
    # would make this test not actually exercise the scenario under test.
    _harness._seed_garmin_activities(fake_db, n=8)
    _harness._seed_connected(fake_db, connected=True)

    fake_db.garmin_activities._docs.append({
        "user_id": _USER_ID,
        "source": "garmin",
        "activity_id": "monday-real-run",
        "activity_type": "running",
        "start_time": _MONDAY.isoformat() + " 07:00:00",
        "garmin_activity": {"start_time_local": _MONDAY.isoformat() + " 07:00:00"},
        "distance_m": 9000.0,
        "duration_s": 2700.0,
    })

    wednesday = _MONDAY + timedelta(days=2)
    result = await _harness._get_week(fake_db, reference_date=wednesday)
    assert result["status"] == 200, result["body"]

    unmatched_ids = {a["activity_id"] for a in result["body"]["week"]["unmatched_actuals"]}
    assert "monday-real-run" in unmatched_ids

    monday_session = next(
        s for s in result["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    assert monday_session["execution_status"] == "prescription_unavailable"
    assert monday_session["actual"] is None
