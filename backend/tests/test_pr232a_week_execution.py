"""PR232A — Tests for training_v2.week_execution (Training execution bridge).

Verifies that GET /training/v2/week's factual execution layer is built
EXCLUSIVELY from the PR230 Garmin boundary, with no calendar fallback and
no fabricated DONE/MISSED, and that the manual '/training/feedback'
endpoint has been fully removed.
"""
from __future__ import annotations

import ast
import os
import sys
from datetime import date

import pytest

os.environ.setdefault("JWT_SECRET", "test-secret-pr232a")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from training_v2.week_execution import build_week_execution  # noqa: E402
from training_v2.workout_generator import WorkoutPrescription  # noqa: E402
from training_v2.performed_workout import MatchingStatus, AdherenceStatus  # noqa: E402

# Monday anchor
WEEK_START = date(2024, 6, 10)
USER = "u1"


def _session(day: str, workout_type: str = "easy", distance_km=8.0, duration_minutes=None):
    return WorkoutPrescription(
        day=day,
        workout_type=workout_type,
        intensity_class="rest" if workout_type == "rest" else "low",
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        reason_codes=(),
    )


def _garmin_doc(
    *,
    activity_id: str,
    user_id: str = USER,
    local_date: str,
    distance_km: float = 8.0,
    duration_min: float = 48.0,
    activity_type: str = "running",
    source: str = "garmin",
):
    return {
        "user_id": user_id,
        "source": source,
        "activity_id": activity_id,
        "activity_type": activity_type,
        "distance_m": distance_km * 1000.0,
        "duration_s": duration_min * 60.0,
        "garmin_activity": {"start_time_local": f"{local_date} 07:00:00"},
        "start_time": f"{local_date} 07:00:00",
    }


def _row_for(rows, planned_date: date):
    for row in rows:
        if row.planned_date == planned_date:
            return row
    raise AssertionError(f"No row for {planned_date}")


# ---------------------------------------------------------------------------
# 1. Past session without Garmin evidence != done
# ---------------------------------------------------------------------------

def test_past_without_garmin_is_never_done():
    sessions = [_session("monday")]
    rows = build_week_execution(
        user_id=USER,
        reference_date=date(2024, 6, 12),  # window (monday) is closed
        week_start=WEEK_START,
        sessions=sessions,
        garmin_docs=[],
    )
    row = _row_for(rows, date(2024, 6, 10))
    assert row.matching_status == MatchingStatus.MISSED
    assert row.adherence_status == AdherenceStatus.MISSED
    # Never fabricated as "done"/"completed_as_planned".
    assert row.adherence_status != AdherenceStatus.COMPLETED_AS_PLANNED


# ---------------------------------------------------------------------------
# 2. Compatible Garmin activity -> matched
# ---------------------------------------------------------------------------

def test_compatible_garmin_activity_is_matched():
    sessions = [_session("monday", distance_km=8.0)]
    docs = [_garmin_doc(activity_id="a1", local_date="2024-06-10", distance_km=8.05, duration_min=48)]
    rows = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 10),
        week_start=WEEK_START, sessions=sessions, garmin_docs=docs,
    )
    row = _row_for(rows, date(2024, 6, 10))
    assert row.matching_status == MatchingStatus.MATCHED
    assert row.adherence_status == AdherenceStatus.COMPLETED_AS_PLANNED
    assert row.actual_distance_km == pytest.approx(8.05)


# ---------------------------------------------------------------------------
# 3. Modified Garmin activity -> completed_modified
# ---------------------------------------------------------------------------

def test_modified_garmin_activity_is_completed_modified():
    sessions = [_session("monday", distance_km=8.0)]
    # +30% distance deviation: within MATCH_MAX_DEVIATION_RATIO(0.5) but
    # outside ADHERENCE_TOLERANCE_RATIO(0.10).
    docs = [_garmin_doc(activity_id="a1", local_date="2024-06-10", distance_km=10.4, duration_min=48)]
    rows = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 10),
        week_start=WEEK_START, sessions=sessions, garmin_docs=docs,
    )
    row = _row_for(rows, date(2024, 6, 10))
    assert row.matching_status == MatchingStatus.MATCHED
    assert row.adherence_status == AdherenceStatus.COMPLETED_MODIFIED


# ---------------------------------------------------------------------------
# 4. No compatible Garmin after window -> missed
# ---------------------------------------------------------------------------

def test_no_compatible_activity_after_window_is_missed():
    sessions = [_session("monday", distance_km=8.0)]
    # Deviation way beyond guard ratio -> rejected as incompatible.
    docs = [_garmin_doc(activity_id="a1", local_date="2024-06-10", distance_km=1.0, duration_min=6)]
    rows = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 12),
        week_start=WEEK_START, sessions=sessions, garmin_docs=docs,
    )
    row = _row_for(rows, date(2024, 6, 10))
    assert row.matching_status == MatchingStatus.MISSED
    assert row.adherence_status == AdherenceStatus.MISSED


# ---------------------------------------------------------------------------
# 5. Ambiguous -> ambiguous
# ---------------------------------------------------------------------------

def test_two_equivalent_candidates_are_ambiguous():
    sessions = [_session("monday", distance_km=8.0)]
    docs = [
        _garmin_doc(activity_id="a1", local_date="2024-06-10", distance_km=8.05, duration_min=48),
        _garmin_doc(activity_id="a2", local_date="2024-06-10", distance_km=8.05, duration_min=48),
    ]
    rows = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 10),
        week_start=WEEK_START, sessions=sessions, garmin_docs=docs,
    )
    row = _row_for(rows, date(2024, 6, 10))
    assert row.matching_status == MatchingStatus.AMBIGUOUS
    assert row.adherence_status == AdherenceStatus.AMBIGUOUS
    assert row.actual_distance_km is None
    # Even after the window closes, ambiguity is never resolved into missed.
    rows_later = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 15),
        week_start=WEEK_START, sessions=sessions, garmin_docs=docs,
    )
    row_later = _row_for(rows_later, date(2024, 6, 10))
    assert row_later.matching_status == MatchingStatus.AMBIGUOUS


# ---------------------------------------------------------------------------
# 6. Extra run without prescription -> unmatched_actual, never dropped
# ---------------------------------------------------------------------------

def test_extra_run_is_unmatched_actual_and_stays_visible():
    sessions = [_session("monday", distance_km=8.0)]
    docs = [
        _garmin_doc(activity_id="a1", local_date="2024-06-10", distance_km=8.05, duration_min=48),
        _garmin_doc(activity_id="extra", local_date="2024-06-11", distance_km=5.0, duration_min=30),
    ]
    rows = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 11),
        week_start=WEEK_START, sessions=sessions, garmin_docs=docs,
    )
    # session rows (len == len(sessions)) followed by extra unmatched actuals.
    session_rows, extra_rows = rows[: len(sessions)], rows[len(sessions):]
    assert session_rows[0].matching_status == MatchingStatus.MATCHED
    assert len(extra_rows) == 1
    assert extra_rows[0].matching_status == MatchingStatus.UNMATCHED_ACTUAL
    assert extra_rows[0].activity_id == "extra"


# ---------------------------------------------------------------------------
# 7. Multi-user isolation
# ---------------------------------------------------------------------------

def test_multi_user_isolation():
    sessions = [_session("monday", distance_km=8.0)]
    docs = [
        _garmin_doc(activity_id="a1", user_id="other-user", local_date="2024-06-10", distance_km=8.05),
    ]
    rows = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 12),
        week_start=WEEK_START, sessions=sessions, garmin_docs=docs,
    )
    row = _row_for(rows, date(2024, 6, 10))
    # Another user's activity can never be attributed — session stays missed.
    assert row.matching_status == MatchingStatus.MISSED
    assert all(r.activity_id != "a1" for r in rows)


# ---------------------------------------------------------------------------
# 8. No-lookahead: a future prescription is always planned, future activities
#    cannot retroactively change a historical prescription's state.
# ---------------------------------------------------------------------------

def test_no_lookahead_future_session_stays_planned():
    sessions = [_session("monday", distance_km=8.0)]
    rows = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 5),  # before the session
        week_start=WEEK_START, sessions=sessions, garmin_docs=[],
    )
    row = _row_for(rows, date(2024, 6, 10))
    assert row.matching_status == MatchingStatus.PLANNED
    assert row.adherence_status == AdherenceStatus.PENDING


def test_no_lookahead_future_activity_is_dropped():
    sessions = [_session("monday", distance_km=8.0)]
    # Activity dated after reference_date must never be considered.
    docs = [_garmin_doc(activity_id="a1", local_date="2024-06-10", distance_km=8.05)]
    rows = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 9),  # before the activity date
        week_start=WEEK_START, sessions=sessions, garmin_docs=docs,
    )
    row = _row_for(rows, date(2024, 6, 10))
    assert row.matching_status == MatchingStatus.PLANNED
    assert row.actual_distance_km is None


# ---------------------------------------------------------------------------
# Rest days: never matchable, never missed.
# ---------------------------------------------------------------------------

def test_rest_day_is_not_applicable():
    sessions = [_session("tuesday", workout_type="rest", distance_km=None)]
    rows = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 20),
        week_start=WEEK_START, sessions=sessions, garmin_docs=[],
    )
    row = _row_for(rows, date(2024, 6, 11))
    assert row.matching_status == MatchingStatus.PLANNED
    assert row.adherence_status == AdherenceStatus.NOT_APPLICABLE


# ---------------------------------------------------------------------------
# Architecture: no None -> 0 coercion, no fabricated "done"/"completed" state.
# ---------------------------------------------------------------------------

def test_engine_never_fabricates_a_completed_state_outside_pr230_vocabulary():
    valid_adherence = {a.value for a in AdherenceStatus}
    assert "done" not in valid_adherence
    assert "completed" not in valid_adherence


def test_missing_actual_stays_none_never_zero():
    sessions = [_session("monday", distance_km=8.0)]
    rows = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 12),
        week_start=WEEK_START, sessions=sessions, garmin_docs=[],
    )
    row = _row_for(rows, date(2024, 6, 10))
    assert row.actual_distance_km is None
    assert row.actual_duration_min is None


# ---------------------------------------------------------------------------
# Manual feedback endpoint removal
# ---------------------------------------------------------------------------

def test_training_feedback_endpoint_removed_from_server():
    server_path = os.path.join(_BACKEND_DIR, "server.py")
    with open(server_path, "r", encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source, filename=server_path)

    def _decorator_calls(node):
        for dec in getattr(node, "decorator_list", []):
            call = dec if isinstance(dec, ast.Call) else None
            if call is not None:
                for arg in call.args:
                    if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                        yield arg.value

    routes = []
    for node in ast.walk(tree):
        if isinstance(node, (ast.AsyncFunctionDef, ast.FunctionDef)):
            routes.extend(_decorator_calls(node))

    assert "/training/feedback" not in routes
    assert "submit_training_feedback" not in source


def test_training_feedback_removed_from_access_control():
    access_control_path = os.path.join(_BACKEND_DIR, "access_control.py")
    with open(access_control_path, "r", encoding="utf-8") as fh:
        source = fh.read()
    assert "/api/training/feedback" not in source


def test_week_execution_module_has_no_io_dependencies():
    module_path = os.path.join(_BACKEND_DIR, "training_v2", "week_execution.py")
    with open(module_path, "r", encoding="utf-8") as fh:
        source = fh.read()
    tree = ast.parse(source, filename=module_path)
    forbidden = {"pymongo", "motor", "requests", "httpx", "fastapi"}
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                assert alias.name.split(".")[0] not in forbidden
        elif isinstance(node, ast.ImportFrom) and node.module:
            assert node.module.split(".")[0] not in forbidden
    assert "datetime.now(" not in source
    assert "date.today(" not in source
