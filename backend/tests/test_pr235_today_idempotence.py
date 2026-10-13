"""#235 — Today first-serve vs. second-serve idempotence (spec §6/§11).

Two successive ``GET /training/today`` calls on the same day must:
- invoke the #234 Structured Workout engine AT MOST ONCE (the second call
  reuses the frozen snapshot, never rebuilds it);
- return byte-for-byte identical ``structured_prescription`` payloads.

Reuses the fake-DB/httpx harness from test_pr232a_c231_week_endpoint.py.

Run from the backend directory:
    python -m pytest tests/test_pr235_today_idempotence.py -v
"""
from __future__ import annotations

import os
import sys
from unittest.mock import patch

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-pr235-idem-secret-32characters!")
os.environ.setdefault("JWT_SECRET", "test-pr235-idem-secret-32characters!")
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
from training_v2.structured_workout import (  # noqa: E402
    build_structured_workout_prescription as _real_engine,
)

pytestmark = pytest.mark.asyncio


async def test_today_second_call_never_rebuilds_structured():
    """First GET Today -> creates the snapshot (engine called once). Second
    GET Today (same day) -> reuses it (engine NOT called again)."""
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_connected(fake_db, connected=True)

    call_count = {"n": 0}

    def _counting_engine(**kwargs):
        call_count["n"] += 1
        return _real_engine(**kwargs)

    with patch(
        "training_v2.structured_workout.build_structured_workout_prescription",
        side_effect=_counting_engine,
    ):
        first = await _harness._get_today(fake_db)
        assert first["status"] == 200, first["body"]
        calls_after_first = call_count["n"]
        assert calls_after_first >= 1, "engine must be invoked to build the first snapshot"

        second = await _harness._get_today(fake_db)
        assert second["status"] == 200, second["body"]
        assert call_count["n"] == calls_after_first, (
            "the second same-day Today call must NEVER re-invoke the "
            "Structured Workout engine — it must reuse the frozen snapshot"
        )

    assert first["body"]["structured_prescription"] == second["body"]["structured_prescription"]


async def test_today_second_call_snapshot_document_unchanged():
    """No second snapshot document is written, and the persisted one is
    byte-for-byte unchanged after a second Today call."""
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_connected(fake_db, connected=True)

    first = await _harness._get_today(fake_db)
    assert first["status"] == 200, first["body"]
    docs_after_first = [dict(d) for d in fake_db.training_prescription_snapshots._docs]
    assert len(docs_after_first) == 1

    second = await _harness._get_today(fake_db)
    assert second["status"] == 200, second["body"]
    docs_after_second = [dict(d) for d in fake_db.training_prescription_snapshots._docs]

    assert docs_after_second == docs_after_first
