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


def _row_for(result, planned_date: date):
    for session_execution in result.sessions:
        if session_execution.row.planned_date == planned_date:
            return session_execution.row
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
    result = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 11),
        week_start=WEEK_START, sessions=sessions, garmin_docs=docs,
    )
    assert result.sessions[0].row.matching_status == MatchingStatus.MATCHED
    assert len(result.extra_rows) == 1
    assert result.extra_rows[0].matching_status == MatchingStatus.UNMATCHED_ACTUAL
    assert result.extra_rows[0].activity_id == "extra"


# ---------------------------------------------------------------------------
# 7. Multi-user isolation
# ---------------------------------------------------------------------------

def test_multi_user_isolation():
    sessions = [_session("monday", distance_km=8.0)]
    docs = [
        _garmin_doc(activity_id="a1", user_id="other-user", local_date="2024-06-10", distance_km=8.05),
    ]
    result = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 12),
        week_start=WEEK_START, sessions=sessions, garmin_docs=docs,
    )
    row = _row_for(result, date(2024, 6, 10))
    # Another user's activity can never be attributed — session stays missed.
    assert row.matching_status == MatchingStatus.MISSED
    assert all(se.row.activity_id != "a1" for se in result.sessions)
    assert all(r.activity_id != "a1" for r in result.extra_rows)


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


# ---------------------------------------------------------------------------
# C231 #1 — unmatched_actuals restricted to the CURRENT week only.
# ---------------------------------------------------------------------------

def test_unmatched_actual_from_previous_week_is_not_exposed():
    sessions = [_session("monday", distance_km=8.0)]
    docs = [
        # Same-week extra run: must be exposed.
        _garmin_doc(activity_id="this-week", local_date="2024-06-12", distance_km=5.0, duration_min=30),
        # Previous-week extra run: must NEVER be exposed as unmatched_actual.
        _garmin_doc(activity_id="prev-week", local_date="2024-06-02", distance_km=5.0, duration_min=30),
    ]
    result = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 12),
        week_start=WEEK_START, sessions=sessions, garmin_docs=docs,
    )
    extra_ids = {row.activity_id for row in result.extra_rows}
    assert extra_ids == {"this-week"}
    assert "prev-week" not in extra_ids


def test_unmatched_actual_from_next_week_is_not_exposed():
    sessions = [_session("monday", distance_km=8.0)]
    docs = [
        _garmin_doc(activity_id="next-week", local_date="2024-06-18", distance_km=5.0, duration_min=30),
    ]
    result = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 20),
        week_start=WEEK_START, sessions=sessions, garmin_docs=docs,
    )
    assert result.extra_rows == []


# ---------------------------------------------------------------------------
# C231 #2 — Prescription snapshot: immutable once frozen.
# ---------------------------------------------------------------------------

def test_past_session_is_freezable_and_proposed_for_persistence():
    """A past/today session with no existing snapshot is proposed to persist."""
    sessions = [_session("monday", distance_km=8.0)]
    result = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 10),  # today == planned_date
        week_start=WEEK_START, sessions=sessions, garmin_docs=[],
    )
    assert len(result.snapshots_to_persist) == 1
    snap = result.snapshots_to_persist[0]
    assert snap.distance_km == 8.0
    assert snap.planned_date == date(2024, 6, 10)


def test_future_session_is_never_proposed_for_persistence():
    sessions = [_session("monday", distance_km=8.0)]
    result = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 5),  # strictly before Monday
        week_start=WEEK_START, sessions=sessions, garmin_docs=[],
    )
    assert result.snapshots_to_persist == []


def test_frozen_snapshot_overrides_a_recomputed_live_prescription():
    """The BLOCKER scenario: Monday planned 8km, engine recomputes to 10km
    later, actual = 8km. Adherence must stay compared against the frozen
    8km snapshot, not the recomputed 10km live session.
    """
    from training_v2.prescription_snapshot import PrescriptionSnapshot

    prescription_id = f"{USER}:2024-06-10:monday"
    frozen_snapshots = {
        prescription_id: PrescriptionSnapshot(
            user_id=USER,
            prescription_id=prescription_id,
            planned_date=date(2024, 6, 10),
            day="monday",
            workout_type="easy",
            intensity_class="low",
            distance_km=8.0,
            duration_minutes=None,
        )
    }
    # Engine recomputed the live plan to 10km — must be ignored for matching.
    live_sessions = [_session("monday", distance_km=10.0)]
    docs = [_garmin_doc(activity_id="a1", local_date="2024-06-10", distance_km=8.05, duration_min=48)]

    result = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 15),
        week_start=WEEK_START, sessions=live_sessions, garmin_docs=docs,
        frozen_snapshots=frozen_snapshots,
    )
    session_execution = result.sessions[0]
    # Displayed/effective prescription is the FROZEN 8km, not the live 10km.
    assert session_execution.session.distance_km == 8.0
    # Matched against 8km actual => completed_as_planned, never "modified".
    assert session_execution.row.matching_status == MatchingStatus.MATCHED
    assert session_execution.row.adherence_status == AdherenceStatus.COMPLETED_AS_PLANNED
    # Already frozen: never proposed again for persistence.
    assert result.snapshots_to_persist == []


def test_replay_at_j_plus_n_gives_identical_result_once_frozen():
    """Once frozen, replaying the same week at a later reference_date must
    yield the exact same matching/adherence outcome (determinism)."""
    from training_v2.prescription_snapshot import PrescriptionSnapshot

    prescription_id = f"{USER}:2024-06-10:monday"
    frozen_snapshots = {
        prescription_id: PrescriptionSnapshot(
            user_id=USER,
            prescription_id=prescription_id,
            planned_date=date(2024, 6, 10),
            day="monday",
            workout_type="easy",
            intensity_class="low",
            distance_km=8.0,
            duration_minutes=None,
        )
    }
    docs = [_garmin_doc(activity_id="a1", local_date="2024-06-10", distance_km=8.05, duration_min=48)]

    result_j10 = build_week_execution(
        user_id=USER, reference_date=date(2024, 6, 15),
        week_start=WEEK_START, sessions=[_session("monday", distance_km=10.0)],
        garmin_docs=docs, frozen_snapshots=frozen_snapshots,
    )
    result_j30 = build_week_execution(
        user_id=USER, reference_date=date(2024, 7, 5),
        week_start=WEEK_START, sessions=[_session("monday", distance_km=12.0)],
        garmin_docs=docs, frozen_snapshots=frozen_snapshots,
    )
    assert result_j10.sessions[0].session.distance_km == result_j30.sessions[0].session.distance_km == 8.0
    assert (
        result_j10.sessions[0].row.adherence_status
        == result_j30.sessions[0].row.adherence_status
        == AdherenceStatus.COMPLETED_AS_PLANNED
    )
