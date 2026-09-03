"""C231 — Tests for training_v2.prescription_snapshot (immutable snapshot).

Verifies the freeze rule in isolation: a session becomes eligible for
freezing once it is today or in the past, never while strictly future, and
that resolving the effective session correctly prefers a frozen snapshot
over the live (possibly recomputed) prescription.
"""
from __future__ import annotations

import os
import sys
from datetime import date

os.environ.setdefault("JWT_SECRET", "test-secret-pr232a-snapshot")
os.environ.setdefault("ENVIRONMENT", "test")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from training_v2.prescription_snapshot import (  # noqa: E402
    PrescriptionSnapshot,
    is_freezable,
    resolve_effective_session,
    snapshot_from_prescription,
)
from training_v2.workout_generator import WorkoutPrescription  # noqa: E402


def _session(distance_km=8.0, duration_minutes=None):
    return WorkoutPrescription(
        day="monday",
        workout_type="easy",
        intensity_class="low",
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        reason_codes=(),
    )


def test_past_date_is_freezable():
    assert is_freezable(planned_date=date(2024, 6, 10), reference_date=date(2024, 6, 12)) is True


def test_today_is_freezable():
    assert is_freezable(planned_date=date(2024, 6, 10), reference_date=date(2024, 6, 10)) is True


def test_future_date_is_never_freezable():
    assert is_freezable(planned_date=date(2024, 6, 10), reference_date=date(2024, 6, 9)) is False


def test_snapshot_from_prescription_copies_live_values():
    session = _session(distance_km=8.0)
    snap = snapshot_from_prescription(
        user_id="u1",
        prescription_id="u1:2024-06-10:monday",
        planned_date=date(2024, 6, 10),
        session=session,
    )
    assert snap.distance_km == 8.0
    assert snap.workout_type == "easy"
    assert snap.day == "monday"


def test_resolve_effective_session_without_snapshot_returns_live():
    live = _session(distance_km=10.0)
    effective = resolve_effective_session(live_session=live, frozen_snapshot=None)
    assert effective is live


def test_resolve_effective_session_with_snapshot_ignores_live_recompute():
    live = _session(distance_km=10.0)
    frozen = PrescriptionSnapshot(
        user_id="u1",
        prescription_id="u1:2024-06-10:monday",
        planned_date=date(2024, 6, 10),
        day="monday",
        workout_type="easy",
        intensity_class="low",
        distance_km=8.0,
        duration_minutes=None,
    )
    effective = resolve_effective_session(live_session=live, frozen_snapshot=frozen)
    assert effective.distance_km == 8.0
    assert effective.distance_km != live.distance_km


def test_prescription_snapshot_model_is_frozen():
    snap = PrescriptionSnapshot(
        user_id="u1",
        prescription_id="u1:2024-06-10:monday",
        planned_date=date(2024, 6, 10),
        day="monday",
        workout_type="easy",
        intensity_class="low",
        distance_km=8.0,
        duration_minutes=None,
    )
    try:
        snap.distance_km = 99.0  # type: ignore[misc]
        assert False, "PrescriptionSnapshot must be immutable"
    except Exception:
        pass


def test_module_has_no_io_dependencies():
    import ast

    module_path = os.path.join(_BACKEND_DIR, "training_v2", "prescription_snapshot.py")
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
