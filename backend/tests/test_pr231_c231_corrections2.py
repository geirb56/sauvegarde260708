"""C231 (corrections round 2) — tests for:

- item 3: no retroactively-invented prescription snapshot for a day that was
  never opened/served while it was current (Monday never opened, Wednesday
  endpoint call, plan recomputed differently on Wednesday => no snapshot,
  execution_status="prescription_unavailable" as a bridge-level fact (never
  a PR230 MatchingStatus/AdherenceStatus value), deterministic replay).
- item 4: the prescription-snapshot unique index must be a CRITICAL
  (fail-fast) startup prerequisite, exactly like Paddle's — creation failure
  must propagate and stop startup.
"""
from __future__ import annotations

import os
import sys
import types
from datetime import date
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-pr231-bis2-secret-32chars!!")
os.environ.setdefault("JWT_SECRET", "test-pr231-bis2-secret-32chars!!")
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

pytestmark = pytest.mark.asyncio

_USER_ID = "user-pr231-bis2"
_MONDAY = date(2024, 6, 10)
_WEEK_START = _MONDAY


def _session(day: str, workout_type: str = "easy", distance_km=8.0):
    from training_v2.workout_generator import WorkoutPrescription

    return WorkoutPrescription(
        day=day, workout_type=workout_type,
        intensity_class="rest" if workout_type == "rest" else "low",
        distance_km=distance_km, duration_minutes=None, reason_codes=(),
    )


# ---------------------------------------------------------------------------
# Item 3 — no retroactive snapshot fabrication
# ---------------------------------------------------------------------------


def test_monday_never_opened_wednesday_call_no_snapshot_created():
    from training_v2.week_execution import (
        EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE,
        build_week_execution,
    )

    # Monday's plan when it was current would have been 8.0km, but the plan
    # is recomputed differently by the time Wednesday's call happens (10.0km)
    # — Monday was NEVER opened/served while current, so NO snapshot exists.
    monday_session_as_recomputed_on_wednesday = _session("monday", distance_km=10.0)
    sessions = [monday_session_as_recomputed_on_wednesday, _session("tuesday", distance_km=8.0)]

    result = build_week_execution(
        user_id=_USER_ID,
        reference_date=date(2024, 6, 12),  # Wednesday
        week_start=_WEEK_START,
        sessions=sessions,
        garmin_docs=[],
        frozen_snapshots={},  # Monday was never opened -> no snapshot
    )

    # No snapshot must ever be proposed for Monday (planned_date < reference_date,
    # no existing snapshot): only "today" (== reference_date) may freeze one,
    # and Wednesday is not in this week's sessions.
    monday_pids = [
        s.session.day for s in result.sessions if s.session.day == "monday"
    ]
    assert monday_pids == ["monday"]
    assert list(result.snapshots_to_persist) == []

    monday_se = next(s for s in result.sessions if s.session.day == "monday")
    # C231 (round 2, item 2) — this is a BRIDGE-level fact, never a PR230
    # matching_status/adherence_status value: no fabricated PR230 row at all.
    assert monday_se.row is None
    assert monday_se.execution_status == EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE
    assert monday_se.execution_status == "prescription_unavailable"


def test_monday_never_opened_replay_is_deterministic():
    """Calling the endpoint again later (plan recomputed yet again) must
    still show prescription_unavailable for Monday — never anything else."""
    from training_v2.week_execution import (
        EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE,
        build_week_execution,
    )

    sessions_first_call = [_session("monday", distance_km=10.0)]
    sessions_second_call = [_session("monday", distance_km=13.5)]  # plan changed again

    first = build_week_execution(
        user_id=_USER_ID, reference_date=date(2024, 6, 12),
        week_start=_WEEK_START, sessions=sessions_first_call,
        garmin_docs=[], frozen_snapshots={},
    )
    second = build_week_execution(
        user_id=_USER_ID, reference_date=date(2024, 6, 20),
        week_start=_WEEK_START, sessions=sessions_second_call,
        garmin_docs=[], frozen_snapshots={},
    )
    se1 = next(s for s in first.sessions if s.session.day == "monday")
    se2 = next(s for s in second.sessions if s.session.day == "monday")
    assert se1.execution_status == EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE
    assert se2.execution_status == EXECUTION_STATUS_PRESCRIPTION_UNAVAILABLE
    assert se1.row is None
    assert se2.row is None


def test_rest_day_never_opened_is_exempt_from_unavailable():
    """Rest days carry no distance/duration to fabricate; PR230 already
    handles them deterministically (PLANNED/NOT_APPLICABLE) regardless of
    reference_date, so they are exempt from the historical-unavailable
    diversion."""
    from training_v2.week_execution import build_week_execution

    sessions = [_session("monday", workout_type="rest", distance_km=None)]
    result = build_week_execution(
        user_id=_USER_ID, reference_date=date(2024, 6, 20),
        week_start=_WEEK_START, sessions=sessions,
        garmin_docs=[], frozen_snapshots={},
    )
    se = next(s for s in result.sessions if s.session.day == "monday")
    assert se.execution_status is None
    assert se.row is not None


def test_today_session_can_still_be_frozen_normally():
    """The item-3 restriction only concerns the PAST; today's session must
    still be freezable as before."""
    from training_v2.week_execution import build_week_execution

    sessions = [_session("monday", distance_km=8.0)]
    result = build_week_execution(
        user_id=_USER_ID, reference_date=date(2024, 6, 10),  # today == Monday
        week_start=_WEEK_START, sessions=sessions,
        garmin_docs=[], frozen_snapshots={},
    )
    assert len(result.snapshots_to_persist) == 1
    assert result.snapshots_to_persist[0].planned_date == date(2024, 6, 10)


# ---------------------------------------------------------------------------
# Item 4 — startup fail-fast prescription snapshot index
# ---------------------------------------------------------------------------


class _NoopCollection:
    async def create_index(self, *_a, **_kw):
        return None

    async def find_one(self, *_a, **_kw):
        return None


class _FakeIndexStartupDB:
    def __getattr__(self, name):
        col = _NoopCollection()
        object.__setattr__(self, name, col)
        return col


async def test_startup_uses_prescription_snapshot_index_helper():
    import server

    fake_db = _FakeIndexStartupDB()
    fake_bootstrap = types.SimpleNamespace(bootstrap=lambda: None)
    ensure_prescription_index = AsyncMock()

    with patch.object(server, "db", fake_db), \
         patch.object(server, "_ensure_subscriptions_unique_index", AsyncMock()), \
         patch.object(server, "_ensure_paddle_events_unique_index", AsyncMock()), \
         patch.object(server, "_ensure_prescription_snapshot_unique_index", ensure_prescription_index), \
         patch.object(server, "validate_environment_configuration"), \
         patch.object(server, "validate_demo_mode_safety"), \
         patch.object(server, "log_demo_mode_status"), \
         patch.dict(sys.modules, {"garmin.bootstrap": fake_bootstrap}):
        await server.create_db_indexes()

    ensure_prescription_index.assert_awaited_once_with(fake_db)


async def test_startup_fails_fast_when_prescription_snapshot_index_helper_fails():
    """A create_index failure for the prescription snapshot index must
    propagate and stop startup, exactly like Paddle's — never silently
    continue while pretending immutability is guaranteed."""
    import server

    fake_db = _FakeIndexStartupDB()
    fake_bootstrap = types.SimpleNamespace(bootstrap=lambda: None)
    ensure_error = RuntimeError("prescription snapshot index creation failed")
    ensure_prescription_index = AsyncMock(side_effect=ensure_error)
    other_index = AsyncMock()
    fake_db.workouts.create_index = other_index

    with patch.object(server, "db", fake_db), \
         patch.object(server, "_ensure_subscriptions_unique_index", AsyncMock()), \
         patch.object(server, "_ensure_paddle_events_unique_index", AsyncMock()), \
         patch.object(server, "_ensure_prescription_snapshot_unique_index", ensure_prescription_index), \
         patch.object(server, "validate_environment_configuration"), \
         patch.object(server, "validate_demo_mode_safety"), \
         patch.object(server, "log_demo_mode_status"), \
         patch.dict(sys.modules, {"garmin.bootstrap": fake_bootstrap}):
        with pytest.raises(RuntimeError, match="prescription snapshot index creation failed"):
            await server.create_db_indexes()

    # The fail-open block (containing db.workouts.create_index and everything
    # after it) must NEVER run once the critical index creation has failed.
    other_index.assert_not_called()


async def test_prescription_snapshot_index_is_created_before_fail_open_block():
    """Ordering guarantee: the prescription snapshot index call must appear
    BEFORE the fail-open try block in source, mirroring Paddle's pattern."""
    import inspect
    import server

    source = inspect.getsource(server.create_db_indexes)
    paddle_pos = source.index("_ensure_paddle_events_unique_index(db)")
    prescription_pos = source.index("_ensure_prescription_snapshot_unique_index(db)")
    # The fail-open try block is the one immediately following the critical
    # prescription-snapshot index call (there may be an earlier, unrelated
    # try/except for the gccli bootstrap step).
    try_pos = source.index("try:", prescription_pos)
    assert paddle_pos < try_pos
    assert prescription_pos < try_pos
