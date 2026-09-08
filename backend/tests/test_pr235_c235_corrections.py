"""C235 (corrective audit) — targeted regression tests for the 4 blockers.

Blockers fixed here (see PR #235 corrective audit report):
1. ``/training/today`` was not truly idempotent: a second call recomputed
   Readiness + ``resolve_today_final_prescription`` (DailyAdaptation) before
   reading the existing snapshot.
2. Today and Week did not expose a common snapshot identity
   (``prescription_id``).
3. Today returned live ``reason_codes`` from DailyAdaptation while Week
   returned the frozen snapshot's ``reason_codes``.
4. The "structured_factory AT MOST ONCE globally" claim was not true under
   genuine concurrency.

Reuses the fake-DB/httpx harness from test_pr232a_c231_week_endpoint.py.

Run from the backend directory:
    python -m pytest tests/test_pr235_c235_corrections.py -v
"""
from __future__ import annotations

import asyncio
import os
import sys
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-pr235-c235-secret-32characters!!")
os.environ.setdefault("JWT_SECRET", "test-pr235-c235-secret-32characters!!")
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


# ---------------------------------------------------------------------------
# Blocker #1 — second Today must NOT invoke DailyAdaptation at all.
# ---------------------------------------------------------------------------

async def test_second_today_never_invokes_daily_adaptation():
    """The mandatory C235 test (spec §6): a second GET /training/today for
    the same day must NOT call ``build_daily_adaptation`` — the existing
    snapshot must be read directly, with zero adaptation recomputation.

    This test MUST fail on the pre-C235-correction head (7fcee2c...), where
    the handler unconditionally called ``resolve_today_final_prescription``
    (which invokes ``build_daily_adaptation``) on every call.
    """
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_connected(fake_db, connected=True)

    from training_v2.daily_adaptation import build_daily_adaptation as _real_adaptation

    call_count = {"n": 0}

    def _counting_adaptation(**kwargs):
        call_count["n"] += 1
        return _real_adaptation(**kwargs)

    with patch(
        "training_v2.today_prescription.build_daily_adaptation",
        side_effect=_counting_adaptation,
    ):
        first = await _harness._get_today(fake_db)
        assert first["status"] == 200, first["body"]
        assert call_count["n"] == 1, (
            "the FIRST Today call must invoke DailyAdaptation exactly once "
            "to create the snapshot"
        )

        second = await _harness._get_today(fake_db)
        assert second["status"] == 200, second["body"]
        assert call_count["n"] == 1, (
            "a SECOND same-day Today call must NEVER invoke DailyAdaptation "
            "again — the existing snapshot is the served truth (C235 blocker #1)"
        )


# ---------------------------------------------------------------------------
# Blocker #3 — reason_codes must stay frozen (Today == Week == snapshot),
# never re-derived from a fresh (possibly different) live DailyAdaptation.
# ---------------------------------------------------------------------------

async def test_reason_codes_frozen_across_today_and_week_despite_live_drift():
    """First Today freezes reason_codes A. Even if a later (hypothetical)
    live DailyAdaptation call would produce different reason_codes B, the
    second Today call and Week must both keep exposing A — never B, and
    never a mix.
    """
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_connected(fake_db, connected=True)

    from training_v2.daily_adaptation import build_daily_adaptation as _real_adaptation

    call_count = {"n": 0}

    def _drifting_adaptation(**kwargs):
        call_count["n"] += 1
        result = _real_adaptation(**kwargs)
        if call_count["n"] > 1:
            # Only reachable if the fast-path regresses and DailyAdaptation
            # is invoked again — simulates live inputs (Training Paces,
            # readiness, ...) having since changed the decision.
            result = result.model_copy(
                update={"reason_codes": ("LIVE_DRIFT_SHOULD_NEVER_LEAK",)}
            )
        return result

    with patch(
        "training_v2.today_prescription.build_daily_adaptation",
        side_effect=_drifting_adaptation,
    ):
        first = await _harness._get_today(fake_db)
        assert first["status"] == 200, first["body"]
        frozen_reason_codes = first["body"]["reason_codes"]

        second = await _harness._get_today(fake_db)
        assert second["status"] == 200, second["body"]
        assert second["body"]["reason_codes"] == frozen_reason_codes
        assert "LIVE_DRIFT_SHOULD_NEVER_LEAK" not in second["body"]["reason_codes"]

    week = await _harness._get_week(fake_db)
    assert week["status"] == 200, week["body"]
    monday_session = next(
        s for s in week["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    assert monday_session["reason_codes"] == frozen_reason_codes
    assert "LIVE_DRIFT_SHOULD_NEVER_LEAK" not in monday_session["reason_codes"]


# ---------------------------------------------------------------------------
# Blocker #2/#4 — Today and Week must expose the SAME prescription_id, and
# converge on the same parent + structured for the same served day.
# ---------------------------------------------------------------------------

async def test_today_and_week_expose_same_prescription_id_identity():
    """Today.prescription_id must equal Week's today-session prescription_id,
    and the parent/structured payloads for that same day must be identical
    (C235 blocker #2/#4)."""
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_garmin_activities(fake_db, n=8)
    _harness._seed_connected(fake_db, connected=True)

    today_result = await _harness._get_today(fake_db)
    assert today_result["status"] == 200, today_result["body"]
    today_body = today_result["body"]

    week_result = await _harness._get_week(fake_db)
    assert week_result["status"] == 200, week_result["body"]
    monday_session = next(
        s for s in week_result["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )

    assert today_body["prescription_id"] is not None
    assert monday_session["prescription_id"] is not None
    assert today_body["prescription_id"] == monday_session["prescription_id"]

    # Parent convergence (served_prescription is the legacy RUNTIME dict —
    # compare via the fields it actually exposes; structured_prescription
    # below carries the full native V2 workout_type/distance/duration).
    assert today_body["served_prescription"]["distance_km"] == monday_session["distance_km"]
    assert today_body["reason_codes"] == monday_session["reason_codes"]
    # C235 (final correction) — strict assertion: Week MUST expose the
    # field at all (a previous version of this test used `.get(key,
    # default=today_body[key])`, which silently compared today==today and
    # passed even when Week omitted the field entirely — never valid).
    assert "session_modified_from_planned" in monday_session
    assert (
        today_body["session_modified_from_planned"]
        == monday_session["session_modified_from_planned"]
    )

    # Structured convergence (already covered by C234 tests, re-asserted here
    # alongside the identity check for completeness).
    assert today_body["structured_prescription"] == monday_session["structured"]
    assert (
        today_body["structured_prescription"]["workout_type"]
        == monday_session["workout_type"]
    )


async def test_week_first_then_today_still_expose_same_prescription_id():
    """Order-independence: Week-first must equally converge with Today on
    the same prescription_id (mirrors the existing parent/structured
    convergence tests, extended with the new identity field)."""
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_garmin_activities(fake_db, n=8)
    _harness._seed_connected(fake_db, connected=True)

    week_result = await _harness._get_week(fake_db)
    assert week_result["status"] == 200, week_result["body"]
    monday_session = next(
        s for s in week_result["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )

    today_result = await _harness._get_today(fake_db)
    assert today_result["status"] == 200, today_result["body"]
    today_body = today_result["body"]

    assert today_body["prescription_id"] == monday_session["prescription_id"]
    assert "session_modified_from_planned" in monday_session
    assert (
        today_body["session_modified_from_planned"]
        == monday_session["session_modified_from_planned"]
    )


# ---------------------------------------------------------------------------
# Blocker #4 — concurrency: honest guarantee is "final persisted document is
# unique/atomic + all callers converge", NOT "factory invoked at most once
# globally". Force genuine interleaving by injecting a real await yield
# point into find_one, so two concurrent callers can both observe "no
# snapshot" before either wins the write.
# ---------------------------------------------------------------------------

async def test_concurrent_first_serve_converges_on_single_winning_snapshot():
    """Two genuinely-concurrent first-serve callers may BOTH execute
    structured_factory (see served_prescription.py's honest concurrency
    docstring), but exactly one snapshot document must win, and both
    callers must converge on that SAME winning parent + structured payload
    — no divergence, no overwrite."""
    fake_db = _harness._FakeDB()
    _harness._seed_cycle(fake_db)
    _harness._seed_connected(fake_db, connected=True)

    real_find_one = fake_db.training_prescription_snapshots.find_one

    async def _yielding_find_one(*args, **kwargs):
        # Force a genuine event-loop suspension so two concurrently
        # scheduled callers can both observe "not found" before either one
        # writes — this is what actually demonstrates the race described in
        # the C235 corrective audit (blocker #9), rather than a sequential
        # asyncio.gather that never truly interleaves.
        await asyncio.sleep(0)
        return await real_find_one(*args, **kwargs)

    fake_db.training_prescription_snapshots.find_one = _yielding_find_one

    factory_calls = {"n": 0}
    from training_v2.structured_workout import (
        build_structured_workout_prescription as _real_engine,
    )

    def _counting_engine(**kwargs):
        factory_calls["n"] += 1
        return _real_engine(**kwargs)

    with patch(
        "training_v2.structured_workout.build_structured_workout_prescription",
        side_effect=_counting_engine,
    ):
        results = await asyncio.gather(
            _harness._get_today(fake_db), _harness._get_today(fake_db)
        )

    first, second = results
    assert first["status"] == 200, first["body"]
    assert second["status"] == 200, second["body"]

    # Exactly one snapshot document persisted — never two, never an
    # overwrite of a different candidate.
    docs = list(fake_db.training_prescription_snapshots._docs)
    assert len(docs) == 1

    # Both concurrent callers converge on the SAME winning served
    # prescription + structured payload — no divergence.
    assert first["body"]["served_prescription"] == second["body"]["served_prescription"]
    assert first["body"]["structured_prescription"] == second["body"]["structured_prescription"]
    assert first["body"]["reason_codes"] == second["body"]["reason_codes"]
    assert first["body"]["prescription_id"] == second["body"]["prescription_id"]

    # HONEST claim (never "at most once"): under genuine concurrency, the
    # factory may run more than once (both callers' candidates are pure and
    # cheap); only the FINAL persisted document is guaranteed unique.
    assert factory_calls["n"] >= 1


# ---------------------------------------------------------------------------
# C235 (final correction) — Week must expose the WINNING snapshot's own
# frozen `modified_from_planned` fact (never recomputed against the live
# plan), converge with Today's `session_modified_from_planned`, and report
# `None` (never a fabricated `False`) for a legacy snapshot predating the
# field. These are pure/direct unit tests against
# ``training_v2.week_execution.build_week_execution`` — no HTTP harness
# needed since this is a bridge-level fact, not an endpoint concern.
# ---------------------------------------------------------------------------

def _week_exec_session(day: str, distance_km: float = 8.0):
    from training_v2.workout_generator import WorkoutPrescription

    return WorkoutPrescription(
        day=day,
        workout_type="easy",
        intensity_class="low",
        distance_km=distance_km,
        duration_minutes=None,
        reason_codes=(),
    )


async def test_week_modified_from_planned_reads_frozen_snapshot_never_recomputed_true():
    """C235 (final correction) test C: even if the CURRENT live session
    differs sharply from the frozen served value, Week must report the
    snapshot's own frozen ``modified_from_planned`` (True here) — never a
    fresh ``served != live_planned`` comparison at read time."""
    from datetime import date as _date
    from training_v2.week_execution import build_week_execution
    from training_v2.prescription_snapshot import PrescriptionSnapshot

    user_id = "u-c235-final"
    week_start = _date(2024, 6, 10)  # Monday
    prescription_id = f"{user_id}:2024-06-10:monday"
    frozen_snapshots = {
        prescription_id: PrescriptionSnapshot(
            user_id=user_id, prescription_id=prescription_id,
            planned_date=_date(2024, 6, 10), day="monday",
            workout_type="easy", intensity_class="low", distance_km=5.0,
            modified_from_planned=True,
        )
    }
    # The CURRENT live plan has since drifted to a very different distance —
    # this must NEVER influence the frozen modified_from_planned fact.
    sessions = [_week_exec_session("monday", distance_km=99.0)]
    result = build_week_execution(
        user_id=user_id,
        reference_date=_date(2024, 6, 12),
        week_start=week_start,
        sessions=sessions,
        garmin_docs=[],
        frozen_snapshots=frozen_snapshots,
    )
    se = next(s for s in result.sessions if s.planned_date == _date(2024, 6, 10))
    assert se.modified_from_planned is True


async def test_week_modified_from_planned_reads_frozen_snapshot_never_recomputed_false():
    """Mirror of the above with a frozen ``False`` — must stay False even
    though the live plan has since drifted."""
    from datetime import date as _date
    from training_v2.week_execution import build_week_execution
    from training_v2.prescription_snapshot import PrescriptionSnapshot

    user_id = "u-c235-final-2"
    week_start = _date(2024, 6, 10)
    prescription_id = f"{user_id}:2024-06-10:monday"
    frozen_snapshots = {
        prescription_id: PrescriptionSnapshot(
            user_id=user_id, prescription_id=prescription_id,
            planned_date=_date(2024, 6, 10), day="monday",
            workout_type="easy", intensity_class="low", distance_km=8.0,
            modified_from_planned=False,
        )
    }
    sessions = [_week_exec_session("monday", distance_km=42.0)]
    result = build_week_execution(
        user_id=user_id,
        reference_date=_date(2024, 6, 12),
        week_start=week_start,
        sessions=sessions,
        garmin_docs=[],
        frozen_snapshots=frozen_snapshots,
    )
    se = next(s for s in result.sessions if s.planned_date == _date(2024, 6, 10))
    assert se.modified_from_planned is False


async def test_week_modified_from_planned_none_for_legacy_snapshot_never_false():
    """C235 (final correction) test D: a legacy snapshot predating the
    ``modified_from_planned`` field must yield ``None`` — never a
    fabricated ``False``."""
    from datetime import date as _date
    from training_v2.week_execution import build_week_execution
    from training_v2.prescription_snapshot import PrescriptionSnapshot

    user_id = "u-c235-final-legacy"
    week_start = _date(2024, 6, 10)
    prescription_id = f"{user_id}:2024-06-10:monday"
    # No modified_from_planned kwarg supplied — mirrors a legacy (pre-C231)
    # document freshly deserialized from Mongo, defaulting to None.
    frozen_snapshots = {
        prescription_id: PrescriptionSnapshot(
            user_id=user_id, prescription_id=prescription_id,
            planned_date=_date(2024, 6, 10), day="monday",
            workout_type="easy", intensity_class="low", distance_km=8.0,
        )
    }
    sessions = [_week_exec_session("monday", distance_km=8.0)]
    result = build_week_execution(
        user_id=user_id,
        reference_date=_date(2024, 6, 12),
        week_start=week_start,
        sessions=sessions,
        garmin_docs=[],
        frozen_snapshots=frozen_snapshots,
    )
    se = next(s for s in result.sessions if s.planned_date == _date(2024, 6, 10))
    assert se.modified_from_planned is None
    assert se.modified_from_planned is not False
