"""C231 (final corrections round) — tests for:

- item 2: /training/today and /training/v2/week share ONE canonical
  reference_date resolver (``server._resolve_canonical_reference_date``),
  never a raw ``now_utc.date()``.
- item 4: the Mongo UNIQUE index on
  ``training_prescription_snapshots.(user_id, prescription_id)`` is created
  via the repo's existing startup index-init mechanism
  (services/prescription_snapshot_index.py), not ad-hoc in a handler.
- item 5: ``build_week_execution`` fail-fasts (raises) when a prescription
  has no matching PR230 ledger row, instead of silently dropping the
  session.
- item 6: ``WeekV2ActualResponse``/``WeekV2PlanResponse.unmatched_actuals``
  cleanup (docstring + ``Field(default_factory=list)``).
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone
from unittest.mock import AsyncMock, MagicMock

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-pr231-final")
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-pr231-final-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)


# ---------------------------------------------------------------------------
# Item 2 — canonical reference_date resolver, shared by both endpoints
# ---------------------------------------------------------------------------


def test_resolve_canonical_reference_date_matches_pure_resolver():
    """server._resolve_canonical_reference_date delegates to the SAME
    training_v2.local_reference_date.resolve_local_reference_date used
    everywhere else — no divergent logic."""
    import server
    from training_v2.local_reference_date import resolve_local_reference_date

    now_utc = datetime(2024, 6, 12, 1, 30, tzinfo=timezone.utc)  # near UTC midnight
    activities = [
        {
            "start_time": "2024-06-11T22:00:00",
            "garmin_activity": {
                "start_time": "2024-06-12T02:00:00",
                "start_time_local": "2024-06-11T22:00:00",
            },
        }
    ]
    expected = resolve_local_reference_date(now_utc=now_utc, garmin_activities=activities)
    actual = server._resolve_canonical_reference_date(now_utc, activities)
    assert actual == expected


def test_today_and_week_use_same_reference_date_helper_source():
    """AST-level guard: both /training/today and /training/v2/week bodies
    must call the SAME shared resolver, never a raw now_utc.date()."""
    import ast

    with open(os.path.join(_BACKEND_DIR, "server.py")) as f:
        source = f.read()
    tree = ast.parse(source)

    found = {"get_today_adaptive_session": False, "get_training_v2_week": False}
    for node in ast.walk(tree):
        if isinstance(node, ast.AsyncFunctionDef) and node.name in found:
            lines = source.splitlines()
            body_lines = lines[node.lineno - 1: node.end_lineno]
            # Strip comment-only content so a mention inside a docstring/comment
            # doesn't produce a false positive/negative.
            code_lines = [
                line.split("#", 1)[0] for line in body_lines
            ]
            body = "\n".join(code_lines)
            assert "_resolve_canonical_reference_date(" in body, (
                f"{node.name} must call _resolve_canonical_reference_date()"
            )
            assert "now_utc.date()" not in body, (
                f"{node.name} must never call now_utc.date() directly"
            )
            found[node.name] = True
    assert all(found.values()), f"Missing handlers: {found}"


def test_same_instant_same_user_same_reference_date():
    """Calling the resolver twice with the identical (now_utc, activities)
    input must be fully deterministic — same reference_date both times."""
    import server

    now_utc = datetime(2024, 6, 12, 3, 0, tzinfo=timezone.utc)
    activities = [
        {
            "start_time": "2024-06-11T20:00:00",
            "garmin_activity": {
                "start_time": "2024-06-12T03:30:00",
                "start_time_local": "2024-06-11T20:00:00",
            },
        }
    ]
    r1 = server._resolve_canonical_reference_date(now_utc, activities)
    r2 = server._resolve_canonical_reference_date(now_utc, activities)
    assert r1 == r2


def test_boundary_utc_plus_and_minus_around_midnight():
    """UTC+ and UTC- boundary cases around midnight must resolve to the
    athlete's LOCAL calendar day, not the raw UTC day."""
    import server

    # UTC 23:30 on June 11 -> local (UTC+2) is June 12 01:30.
    now_utc_plus = datetime(2024, 6, 11, 23, 30, tzinfo=timezone.utc)
    activities_plus = [
        {
            "start_time": "2024-06-12T01:00:00",
            "garmin_activity": {
                "start_time": "2024-06-11T23:00:00",
                "start_time_local": "2024-06-12T01:00:00",
            },
        }
    ]
    result_plus = server._resolve_canonical_reference_date(now_utc_plus, activities_plus)
    assert result_plus == date(2024, 6, 12)

    # UTC 02:30 on June 12 -> local (UTC-5) is June 11 21:30.
    now_utc_minus = datetime(2024, 6, 12, 2, 30, tzinfo=timezone.utc)
    activities_minus = [
        {
            "start_time": "2024-06-11T21:00:00",
            "garmin_activity": {
                "start_time": "2024-06-12T02:00:00",
                "start_time_local": "2024-06-11T21:00:00",
            },
        }
    ]
    result_minus = server._resolve_canonical_reference_date(now_utc_minus, activities_minus)
    assert result_minus == date(2024, 6, 11)


# ---------------------------------------------------------------------------
# Item 4 — Mongo UNIQUE index via the startup init mechanism
# ---------------------------------------------------------------------------


class _FakeIndexCollection:
    def __init__(self):
        self.create_index_calls = []

    async def create_index(self, keys, **kwargs):
        self.create_index_calls.append((keys, kwargs))
        return "uniq_user_prescription"


class _FakeIndexDB:
    def __init__(self):
        self.training_prescription_snapshots = _FakeIndexCollection()


@pytest.mark.asyncio
async def test_ensure_prescription_snapshot_unique_index_creates_expected_index():
    from services.prescription_snapshot_index import ensure_prescription_snapshot_unique_index

    fake_db = _FakeIndexDB()
    await ensure_prescription_snapshot_unique_index(fake_db)

    calls = fake_db.training_prescription_snapshots.create_index_calls
    assert len(calls) == 1
    keys, kwargs = calls[0]
    assert keys == [("user_id", 1), ("prescription_id", 1)]
    assert kwargs.get("unique") is True


def test_create_db_indexes_wires_prescription_snapshot_index():
    """server.py's startup index-init function must call the shared
    wrapper — the index must NOT be created ad-hoc inside the week handler."""
    import inspect
    import server

    source = inspect.getsource(server.create_db_indexes)
    assert "_ensure_prescription_snapshot_unique_index(db)" in source

    # Ad-hoc creation inside the request handler is forbidden.
    week_source = inspect.getsource(server.get_training_v2_week)
    assert "training_prescription_snapshots.create_index" not in week_source


# ---------------------------------------------------------------------------
# Item 5 — fail-fast invariant in build_week_execution
# ---------------------------------------------------------------------------


def _rx_session(day: str, workout_type: str = "easy", distance_km=8.0):
    from training_v2.workout_generator import WorkoutPrescription

    return WorkoutPrescription(
        day=day,
        workout_type=workout_type,
        intensity_class="rest" if workout_type == "rest" else "low",
        distance_km=distance_km,
        duration_minutes=None,
        reason_codes=(),
    )


def test_build_week_execution_raises_when_ledger_row_missing():
    """If build_performed_workouts ever returns fewer rows than prescriptions
    (a broken invariant), build_week_execution must raise explicitly instead
    of silently truncating the week."""
    from unittest.mock import patch
    import training_v2.week_execution as week_execution_mod
    from training_v2.performed_workout import PerformedWorkoutLedger
    from training_v2.prescription_snapshot import PrescriptionSnapshot
    from training_v2.week_execution import prescription_id_for

    week_start = date(2024, 6, 10)  # Monday
    sessions = [_rx_session("monday"), _rx_session("tuesday")]

    # Both days are already frozen (served in the past), so they remain in
    # PR230's matching path rather than being diverted to the item-3
    # "historical prescription unavailable" branch — keeping this test's
    # broken-ledger-invariant scenario meaningful.
    frozen_snapshots = {
        prescription_id_for("u1", date(2024, 6, 10), "monday"): PrescriptionSnapshot(
            user_id="u1", prescription_id=prescription_id_for("u1", date(2024, 6, 10), "monday"),
            planned_date=date(2024, 6, 10), day="monday",
            workout_type="easy", intensity_class="low", distance_km=8.0,
        ),
        prescription_id_for("u1", date(2024, 6, 11), "tuesday"): PrescriptionSnapshot(
            user_id="u1", prescription_id=prescription_id_for("u1", date(2024, 6, 11), "tuesday"),
            planned_date=date(2024, 6, 11), day="tuesday",
            workout_type="easy", intensity_class="low", distance_km=8.0,
        ),
    }

    # Force build_performed_workouts to return an EMPTY ledger (simulating a
    # broken invariant where a prescription silently has no ledger row).
    with patch.object(
        week_execution_mod,
        "build_performed_workouts",
        return_value=PerformedWorkoutLedger(
            user_id="u1",
            reference_date=date(2024, 6, 15),
            entries=(),
            matched_count=0,
            missed_count=0,
            planned_count=0,
            ambiguous_count=0,
            unmatched_actual_count=0,
        ),
    ):
        with pytest.raises(ValueError, match="invariant violated"):
            week_execution_mod.build_week_execution(
                user_id="u1",
                reference_date=date(2024, 6, 15),
                week_start=week_start,
                sessions=sessions,
                garmin_docs=[],
                frozen_snapshots=frozen_snapshots,
            )


@pytest.mark.asyncio
async def test_week_endpoint_returns_500_on_execution_invariant_violation():
    """/training/v2/week must surface a fail-fast 500, never a silently
    truncated week, when build_week_execution raises."""
    import server
    from fastapi import HTTPException

    # We only assert on the source-level wiring here (endpoint-level unit
    # testing of the full handler is covered by test_pr232a_c231_week_endpoint.py);
    # this test verifies the try/except + HTTPException(500) contract exists.
    import inspect

    source = inspect.getsource(server.get_training_v2_week)
    assert "except ValueError as exc:" in source
    assert "status_code=500" in source
    assert "len(execution.sessions) != len(weekly_plan.sessions)" in source


# ---------------------------------------------------------------------------
# Item 6 — WeekV2ActualResponse / unmatched_actuals cleanup
# ---------------------------------------------------------------------------


def test_week_v2_actual_response_docstring_mentions_both_usages():
    from training_v2.training_week_response import WeekV2ActualResponse

    doc = WeekV2ActualResponse.__doc__ or ""
    assert "session.actual" in doc or "actual" in doc
    assert "unmatched_actuals" in doc


def test_unmatched_actuals_uses_default_factory_list():
    from training_v2.training_week_response import WeekV2PlanResponse

    field = WeekV2PlanResponse.model_fields["unmatched_actuals"]
    # Pydantic v2: default_factory should be `list`, not a shared mutable default.
    assert field.default_factory is list
