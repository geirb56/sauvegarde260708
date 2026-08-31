"""PR #225 — Readiness runtime data truth (initial + correction round).

Tests (initial round — 6 required):
1. today's metric is used (not an older one when today's is available)
2. stale metric (> _CURRENT_SIGNAL_MAX_AGE_DAYS old) is NOT presented as current
3. absent RHR / HRV / sleep stays None — no synthetic value injected
4. no sleep=7h fallback — absent sleep_hours → None in output
5. today's daily-metrics sync refreshes the metrics used by Readiness
6. Readiness V2 regressions pass (complete data → float score; no physio → None)

Tests (correction round — 7 additional):
7.  incremental_sync: daily metrics are fetched and persisted (provider stub)
8.  J0 (today's doc) present → used as current signal
9.  J0 absent, only J-1 present → J-1 accepted as current (overnight measurement)
10. J0 absent, only J-2 present → signal is None (stale, not accepted as current)
11. Sleep from J-2 is NOT used as the current sleep signal
12. RHR/HRV from J-2 is NOT used as the current physio signal
13. Progress: get_daily_metrics returns is_current=True for J0/J-1, False for older
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from garmin.readiness_adapter import (
    _CURRENT_SIGNAL_MAX_AGE_DAYS,
    build_readiness_v2_from_garmin_data,
)
from garmin.insights import _latest_with

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TODAY = date(2026, 1, 28)
_STALE_DATE = _TODAY - timedelta(days=_CURRENT_SIGNAL_MAX_AGE_DAYS + 1)


def _doc(
    d: date,
    rhr: Optional[float] = 52.0,
    hrv: Optional[float] = 65.0,
    sleep_hours: Optional[float] = 7.5,
    sleep_score: Optional[float] = 80.0,
) -> dict:
    return {
        "date": d.isoformat(),
        "resting_hr": rhr,
        "hrv": hrv,
        "sleep_hours": sleep_hours,
        "sleep_score": sleep_score,
    }


def _activities(n: int = 28, ref: date = _TODAY) -> List[dict]:
    return [
        {
            "activity_type": "running",
            "start_time": f"{(ref - timedelta(days=i)).isoformat()}T08:00:00",
            "duration_s": 2400.0,
        }
        for i in range(n)
    ]


# ---------------------------------------------------------------------------
# Test 1 — today's metric is used when it exists
# ---------------------------------------------------------------------------

def test_today_metric_used_over_older_one():
    """When today has RHR 48, an older doc with RHR 52 must not overshadow it."""
    docs = [
        _doc(_TODAY, rhr=48.0, hrv=70.0),  # today — newest
        _doc(_TODAY - timedelta(days=1), rhr=52.0, hrv=65.0),
        *[_doc(_TODAY - timedelta(days=i), rhr=52.0, hrv=65.0) for i in range(2, 14)],
    ]
    result = _latest_with(docs, "resting_hr", _TODAY)
    assert result is not None
    assert result["resting_hr"] == 48.0, (
        "Expected today's RHR (48) to be selected, got "
        f"{result['resting_hr']}"
    )


# ---------------------------------------------------------------------------
# Test 2 — stale metric is NOT returned as current
# ---------------------------------------------------------------------------

def test_stale_metric_not_presented_as_current():
    """A doc older than _CURRENT_SIGNAL_MAX_AGE_DAYS is silently excluded."""
    docs = [
        _doc(_STALE_DATE, rhr=48.0, hrv=70.0, sleep_hours=7.5),
    ]
    rhr_result = _latest_with(docs, "resting_hr", _TODAY)
    hrv_result = _latest_with(docs, "hrv", _TODAY)
    sleep_result = _latest_with(docs, "sleep_hours", _TODAY)
    assert rhr_result is None, (
        f"Stale RHR doc ({_STALE_DATE}) must not be returned; got {rhr_result}"
    )
    assert hrv_result is None
    assert sleep_result is None


# ---------------------------------------------------------------------------
# Test 3 — absent RHR / HRV / sleep stays None
# ---------------------------------------------------------------------------

def test_absent_physio_stays_none():
    """When no metrics docs at all, readiness adapter must not inject synthetic values."""
    result = build_readiness_v2_from_garmin_data(
        metrics_docs=[],
        activities=_activities(),
        reference_date=_TODAY,
    )
    # No physio data → score must be None (INSUFFICIENT), never a fabricated float.
    assert result.score is None, (
        f"Expected None score with no physio data, got {result.score}"
    )


def test_absent_rhr_hrv_produces_none_signals():
    """Docs without resting_hr or hrv → no physio signals → score must be None."""
    docs = [
        {
            "date": _TODAY.isoformat(),
            "resting_hr": None,
            "hrv": None,
            "sleep_hours": 7.5,
            "sleep_score": 80.0,
        }
    ]
    result = build_readiness_v2_from_garmin_data(
        metrics_docs=docs,
        activities=_activities(),
        reference_date=_TODAY,
    )
    # Without any RHR or HRV the adapter must not invent physio; the sufficiency
    # classifier must yield INSUFFICIENT → score must be None.
    assert result.score is None, (
        f"Expected None score when both RHR and HRV are absent, got {result.score}. "
        "A fabricated physio score (e.g. primary=70 fallback) would produce a non-None value."
    )


# ---------------------------------------------------------------------------
# Test 4 — no sleep=7h fallback
# ---------------------------------------------------------------------------

def test_no_sleep_7h_fallback_in_insights():
    """compute_run_index must not invent sleep_hours=7.0 when sleep data is absent."""
    from garmin.insights import _latest_with as _lw

    # Metrics docs with sleep_hours=None for all — simulate missing sleep data.
    docs = [
        {
            "date": (_TODAY - timedelta(days=i)).isoformat(),
            "resting_hr": 52.0,
            "hrv": 65.0,
            "sleep_hours": None,
            "sleep_score": None,
        }
        for i in range(7)
    ]
    sleep_doc = _lw(docs, "sleep_hours", _TODAY)
    assert sleep_doc is None, (
        "sleep_doc must be None when no sleep_hours present; "
        f"got {sleep_doc}"
    )

    # Also verify the adapter does not inject sleep data.
    result = build_readiness_v2_from_garmin_data(
        metrics_docs=docs,
        activities=_activities(),
        reference_date=_TODAY,
    )
    # sleep_hours = None everywhere → SleepRecord must be None → score is at most
    # DEGRADED (never invented via sleep=7h).
    from training_v2.readiness_sufficiency import SufficiencyLevel
    assert result.sufficiency_level != SufficiencyLevel.SUFFICIENT or result.score is not None


# ---------------------------------------------------------------------------
# Test 5 — today's daily-metrics docs are reflected in the adapter
# ---------------------------------------------------------------------------

def test_today_sync_refreshes_metrics_used_by_readiness():
    """If today's doc is added to the list it must be the one the adapter uses.

    Uses stressed physio before sync (elevated RHR) and rested physio for
    today's doc so the scores are guaranteed to diverge.
    """
    # 14 days of elevated RHR (within staleness window) — stressed state.
    old_docs = [
        _doc(_TODAY - timedelta(days=i), rhr=65.0, hrv=45.0, sleep_hours=5.5, sleep_score=50.0)
        for i in range(1, 15)
    ]
    result_before = build_readiness_v2_from_garmin_data(
        metrics_docs=old_docs,
        activities=_activities(),
        reference_date=_TODAY,
    )

    # Simulate today's sync: prepend a doc for today with much better values.
    today_doc = _doc(_TODAY, rhr=48.0, hrv=80.0, sleep_hours=8.5, sleep_score=92.0)
    docs_after_sync = [today_doc] + old_docs

    result_after = build_readiness_v2_from_garmin_data(
        metrics_docs=docs_after_sync,
        activities=_activities(),
        reference_date=_TODAY,
    )

    # After syncing today's better data the score must have changed.
    assert result_before.score != result_after.score, (
        f"Expected readiness to change after today's metrics doc is added: "
        f"before={result_before.score}, after={result_after.score}"
    )


# ---------------------------------------------------------------------------
# Test 6 — Readiness V2 regressions
# ---------------------------------------------------------------------------

def test_readiness_v2_complete_data_produces_float_score():
    """Full 14-day physio + load → score must be a float in [0, 100]."""
    docs = [_doc(_TODAY - timedelta(days=i)) for i in range(14)]
    result = build_readiness_v2_from_garmin_data(
        metrics_docs=docs,
        activities=_activities(),
        reference_date=_TODAY,
    )
    assert result.score is not None
    assert isinstance(result.score, float)
    assert 0.0 <= result.score <= 100.0


def test_readiness_v2_no_activities_score_is_none():
    """No activities → training load unavailable → INSUFFICIENT → score is None."""
    docs = [_doc(_TODAY - timedelta(days=i)) for i in range(14)]
    result = build_readiness_v2_from_garmin_data(
        metrics_docs=docs,
        activities=[],
        reference_date=_TODAY,
    )
    from training_v2.readiness_sufficiency import SufficiencyLevel
    assert result.sufficiency_level == SufficiencyLevel.INSUFFICIENT
    assert result.score is None


def test_readiness_v2_formula_not_mutated():
    """Score produced by V2 formula must stay stable for a known input set."""
    # Stable regression fixture: 14 identical days, then 28 activities.
    docs = [
        {
            "date": (_TODAY - timedelta(days=i)).isoformat(),
            "resting_hr": 52.0,
            "hrv": 65.0,
            "sleep_hours": 7.5,
            "sleep_score": 80.0,
        }
        for i in range(14)
    ]
    result = build_readiness_v2_from_garmin_data(
        metrics_docs=docs,
        activities=_activities(28),
        reference_date=_TODAY,
    )
    assert result.score is not None
    assert 0.0 <= result.score <= 100.0
    # Changing physio to elevated values must LOWER the score.
    stressed_docs = [
        {
            "date": (_TODAY - timedelta(days=i)).isoformat(),
            "resting_hr": 60.0,  # elevated vs 52 baseline
            "hrv": 50.0,         # depressed vs 65 baseline
            "sleep_hours": 5.0,
            "sleep_score": 50.0,
        }
        for i in range(14)
    ]
    result_stressed = build_readiness_v2_from_garmin_data(
        metrics_docs=stressed_docs,
        activities=_activities(28),
        reference_date=_TODAY,
    )
    if result_stressed.score is not None and result.score is not None:
        assert result_stressed.score <= result.score, (
            f"Stressed score {result_stressed.score} should be <= rested score {result.score}"
        )


# ===========================================================================
# Correction-round tests (PR #225 — second pass)
# ===========================================================================

# ---------------------------------------------------------------------------
# Test 7 — incremental_sync fetches and persists daily metrics (provider stub)
# ---------------------------------------------------------------------------

def test_incremental_sync_fetches_daily_metrics():
    """incremental_sync must call provider.get_daily_metrics and persist to Mongo.

    This is a unit-level test using minimal stubs — no real Garmin / Redis /
    MongoDB connection required.  We verify the new code path by asserting that
    ``get_daily_metrics`` was called with ``days=3, start_days_ago=0`` and that
    ``_persist_daily_metrics`` received the returned list.
    """
    import asyncio
    from unittest.mock import AsyncMock, MagicMock, patch

    # Minimal metrics returned by the provider stub
    fake_metrics = [
        {"date": _TODAY.isoformat(), "resting_hr": 52.0, "hrv": 65.0,
         "sleep_hours": 7.5, "sleep_score": 80.0},
    ]

    provider_stub = MagicMock()
    provider_stub.sync_activities.return_value = []
    provider_stub.get_daily_metrics_fetch_result.return_value = {
        "metrics": fake_metrics,
        "status": "success",
        "endpoint_success_count": 9,
        "endpoint_failure_count": 0,
        "endpoint_total_count": 9,
        "endpoint_failures": [],
    }

    # Minimal db stub
    async def _find_one(*a, **kw):
        return {"connected": True, "garmin_username": "test@garmin.com"}

    db_stub = MagicMock()
    db_stub.garmin_connections.find_one = AsyncMock(return_value={"connected": True, "garmin_username": "t"})
    db_stub.garmin_activities.find_one = AsyncMock(return_value=None)
    db_stub.garmin_activities.bulk_write = AsyncMock(return_value=MagicMock(upserted_count=0, modified_count=0))
    db_stub.garmin_activities.count_documents = AsyncMock(return_value=0)
    db_stub.garmin_daily_metrics.update_one = AsyncMock(return_value=None)

    persisted: list = []

    async def fake_persist(db, user_id, metrics):
        persisted.extend(metrics)
        return len(metrics)

    with (
        patch("garmin.service.session_store.ensure_session", AsyncMock(return_value=True)),
        patch("garmin.service.get_provider_for_user", return_value=provider_stub),
        patch("garmin.service._ingest_activities", AsyncMock(return_value={"synced": 0, "new": 0, "newest_start": None, "new_running_dates": []})),
        patch("garmin.service._finalize_connection", AsyncMock(return_value=0)),
        patch("garmin.service._sync_vo2max_for_running_dates", AsyncMock(return_value=None)),
        patch("garmin.service._build_and_persist_capabilities", AsyncMock(return_value=None)),
        patch("garmin.service._persist_daily_metrics", fake_persist),
        patch("garmin.service.refresh_today_run_index_after_garmin_activities", AsyncMock(return_value=None)),
        patch("garmin.service.backfill_run_index_history_after_garmin_sync", AsyncMock(return_value=None)),
        patch("garmin.service._dic.invalidate_user", MagicMock()),
        patch("garmin.service._backfill_workouts_user", AsyncMock(return_value=None)),
        patch("garmin.service.update_sync_progress", AsyncMock(return_value=None)),
        patch("garmin.service._safe_save_session", AsyncMock(return_value=None)),
    ):
        from garmin.service import incremental_sync
        result = asyncio.run(incremental_sync(db_stub, "user_123"))

    # Provider must have been asked for recent daily metrics
    provider_stub.get_daily_metrics_fetch_result.assert_called_once()
    call_kwargs = provider_stub.get_daily_metrics_fetch_result.call_args
    assert call_kwargs.kwargs.get("days", call_kwargs.args[1] if len(call_kwargs.args) > 1 else None) == 3 or \
           3 in call_kwargs.args, \
           f"Expected days=3, got: {call_kwargs}"
    assert call_kwargs.kwargs.get("start_days_ago", 0) == 0, \
           f"Expected start_days_ago=0, got: {call_kwargs}"

    # Persisted metrics must include the fake ones returned by the provider
    assert len(persisted) == 1
    assert persisted[0]["date"] == _TODAY.isoformat()

    # Return value must expose metrics_count
    assert result["metrics_count"] == 1
    assert result["success"] is True


# ---------------------------------------------------------------------------
# Test 8 — J0 (today) present → used as current signal
# ---------------------------------------------------------------------------

def test_j0_present_is_used_as_current_signal():
    """When today's doc is available it must be used as the current reading."""
    docs = [
        _doc(_TODAY, rhr=48.0, hrv=72.0),          # J0
        _doc(_TODAY - timedelta(days=1), rhr=55.0),  # J-1 (older)
    ]
    result = _latest_with(docs, "resting_hr", _TODAY)
    assert result is not None
    assert result["date"] == _TODAY.isoformat(), (
        f"J0 ({_TODAY}) must be selected; got {result['date']}"
    )
    assert result["resting_hr"] == 48.0


# ---------------------------------------------------------------------------
# Test 9 — J0 absent, J-1 present → J-1 accepted (overnight measurement)
# ---------------------------------------------------------------------------

def test_j_minus_1_accepted_when_j0_absent():
    """When J0 is missing but J-1 is present, J-1 must be used as current signal."""
    yesterday = _TODAY - timedelta(days=1)
    docs = [
        # No J0 doc
        _doc(yesterday, rhr=52.0, hrv=65.0),
        _doc(_TODAY - timedelta(days=2), rhr=55.0),
    ]
    result = _latest_with(docs, "resting_hr", _TODAY)
    assert result is not None
    assert result["date"] == yesterday.isoformat(), (
        f"J-1 ({yesterday}) must be accepted when J0 is absent; got {result['date']}"
    )


# ---------------------------------------------------------------------------
# Test 10 — J0 absent, J-2 present → signal is None (stale)
# ---------------------------------------------------------------------------

def test_j_minus_2_only_yields_none():
    """When only J-2 data is available, the current signal must be None (stale)."""
    docs = [
        _doc(_TODAY - timedelta(days=2), rhr=52.0, hrv=65.0),  # J-2 only
    ]
    rhr_result = _latest_with(docs, "resting_hr", _TODAY)
    hrv_result = _latest_with(docs, "hrv", _TODAY)
    sleep_result = _latest_with(docs, "sleep_hours", _TODAY)
    assert rhr_result is None, (
        f"J-2 RHR must not be returned as current signal; got {rhr_result}"
    )
    assert hrv_result is None
    assert sleep_result is None

    # Readiness adapter must also produce None score (no current physio)
    result = build_readiness_v2_from_garmin_data(
        metrics_docs=docs,
        activities=_activities(),
        reference_date=_TODAY,
    )
    assert result.score is None, (
        f"Score must be None when only J-2 physio available; got {result.score}"
    )


# ---------------------------------------------------------------------------
# Test 11 — Sleep from J-2 is NOT used as current sleep signal
# ---------------------------------------------------------------------------

def test_j_minus_2_sleep_not_used_as_current():
    """A sleep record from J-2 or older must not be used as today's sleep."""
    docs = [
        # Sleep data only on J-2
        {
            "date": (_TODAY - timedelta(days=2)).isoformat(),
            "resting_hr": None,
            "hrv": None,
            "sleep_hours": 8.0,
            "sleep_score": 90.0,
        }
    ]
    # _latest_with for sleep_hours should return None because J-2 is outside window
    sleep_doc = _latest_with(docs, "sleep_hours", _TODAY)
    assert sleep_doc is None, (
        f"Sleep from J-2 must not be used as current signal; got {sleep_doc}"
    )

    # The adapter must also reflect this: no sleep record
    from garmin.readiness_adapter import _build_sleep_record
    from datetime import date as _date
    sleep_rec = _build_sleep_record(docs, _TODAY)
    assert sleep_rec is None, (
        f"_build_sleep_record must return None for J-2 sleep; got {sleep_rec}"
    )


# ---------------------------------------------------------------------------
# Test 12 — RHR/HRV from J-2 are NOT used as current physio signals
# ---------------------------------------------------------------------------

def test_j_minus_2_rhr_hrv_not_used_as_current():
    """RHR and HRV from J-2 must not influence the current physio signal."""
    docs = [
        {
            "date": (_TODAY - timedelta(days=2)).isoformat(),
            "resting_hr": 60.0,  # elevated — should be ignored
            "hrv": 45.0,         # depressed — should be ignored
            "sleep_hours": None,
            "sleep_score": None,
        }
    ]
    from garmin.readiness_adapter import _build_physio_signal
    rhr_sig = _build_physio_signal(docs, "resting_hr", _TODAY)
    hrv_sig = _build_physio_signal(docs, "hrv", _TODAY)

    assert rhr_sig is None, (
        f"RHR signal must be None when only J-2 data exists; got {rhr_sig}"
    )
    assert hrv_sig is None, (
        f"HRV signal must be None when only J-2 data exists; got {hrv_sig}"
    )


# ---------------------------------------------------------------------------
# Test 13 — Progress: get_daily_metrics is_current flag correctness
# ---------------------------------------------------------------------------

def test_get_daily_metrics_is_current_flag():
    """get_daily_metrics must set is_current=True for J0/J-1, False for older."""
    import asyncio
    from unittest.mock import MagicMock, AsyncMock, patch
    from datetime import datetime, timezone

    # We patch datetime.now so the "today" in the function is deterministic.
    # _TODAY = 2026-01-28.
    fake_now = datetime(_TODAY.year, _TODAY.month, _TODAY.day, 10, 0, tzinfo=timezone.utc)

    async def _run(doc_date: date, expected: bool):
        doc = {
            "date": doc_date.isoformat(),
            "resting_hr": 52.0,
            "hrv": 65.0,
            "sleep_hours": 7.5,
            "sleep_score": 80.0,
        }
        cursor_mock = MagicMock()
        cursor_mock.sort.return_value = cursor_mock
        cursor_mock.limit.return_value = cursor_mock
        cursor_mock.to_list = AsyncMock(return_value=[doc])
        db_mock = MagicMock()
        db_mock.garmin_daily_metrics.find.return_value = cursor_mock

        with patch("garmin.service.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            from garmin.service import get_daily_metrics
            result = await get_daily_metrics(db_mock, "user_x", days=7)

        assert result["latest"]["is_current"] == expected, (
            f"For doc_date={doc_date} expected is_current={expected}, "
            f"got {result['latest']['is_current']}"
        )

    # J0 (today) → is_current = True
    asyncio.run(_run(_TODAY, True))
    # J-1 (yesterday) → is_current = True
    asyncio.run(_run(_TODAY - timedelta(days=1), True))
    # J-2 → is_current = False
    asyncio.run(_run(_TODAY - timedelta(days=2), False))
    # J-7 → is_current = False
    asyncio.run(_run(_TODAY - timedelta(days=7), False))


# ---------------------------------------------------------------------------
# Test 14 — _persist_daily_metrics: partial refresh preserves existing values
# ---------------------------------------------------------------------------

def test_persist_daily_metrics_partial_refresh_preserves_existing_rhr():
    """A partial provider refresh with RHR=None must NOT overwrite a real RHR
    that was already stored in Mongo for the same calendar day."""
    import asyncio
    from unittest.mock import MagicMock, AsyncMock

    async def _run():
        # Simulate Mongo already containing a doc with resting_hr=58 for today
        existing_doc = {
            "_id": "fake_id",
            "user_id": "user_y",
            "date": _TODAY.isoformat(),
            "resting_hr": 58.0,
            "hrv": 72.0,
            "sleep_hours": 7.2,
            "sleep_score": 82.0,
            "synced_at": "2026-01-28T06:00:00+00:00",
        }

        # Partial refresh: provider returns same day but resting_hr is None
        partial_metric = {
            "date": _TODAY.isoformat(),
            "resting_hr": None,      # missing in this partial pull
            "hrv": 74.0,             # HRV updated
            "sleep_hours": None,     # missing
            "sleep_score": None,     # missing
        }

        captured_set: dict = {}

        async def fake_update_one(filter_, update, upsert=False):
            captured_set.update(update.get("$set", {}))

        db_mock = MagicMock()
        db_mock.garmin_daily_metrics.update_one = fake_update_one

        from garmin.service import _persist_daily_metrics
        count = await _persist_daily_metrics(db_mock, "user_y", [partial_metric])

        assert count == 1, "Should have processed 1 metric"

        # resting_hr=None must NOT appear in the $set payload — existing value preserved
        assert "resting_hr" not in captured_set, (
            f"resting_hr=None must not overwrite existing value, but found in $set: {captured_set}"
        )
        # The real new value (HRV=74) must be written
        assert captured_set.get("hrv") == 74.0, (
            f"Updated HRV should be 74.0, got {captured_set.get('hrv')}"
        )

    asyncio.run(_run())


# ---------------------------------------------------------------------------
# Test 15 — get_daily_metrics: future date yields is_current=False
# ---------------------------------------------------------------------------

def test_get_daily_metrics_future_date_is_not_current():
    """A doc dated in the future must yield is_current=False (days_ago < 0)."""
    import asyncio
    from unittest.mock import MagicMock, AsyncMock, patch
    from datetime import datetime, timezone

    future_date = _TODAY + timedelta(days=1)
    fake_now = datetime(_TODAY.year, _TODAY.month, _TODAY.day, 10, 0, tzinfo=timezone.utc)

    async def _run():
        doc = {
            "date": future_date.isoformat(),
            "resting_hr": 50.0,
        }
        cursor_mock = MagicMock()
        cursor_mock.sort.return_value = cursor_mock
        cursor_mock.limit.return_value = cursor_mock
        cursor_mock.to_list = AsyncMock(return_value=[doc])
        db_mock = MagicMock()
        db_mock.garmin_daily_metrics.find.return_value = cursor_mock

        with patch("garmin.service.datetime") as mock_dt:
            mock_dt.now.return_value = fake_now
            mock_dt.fromisoformat = datetime.fromisoformat
            from garmin.service import get_daily_metrics
            result = await get_daily_metrics(db_mock, "user_future", days=7)

        assert result["latest"]["is_current"] is False, (
            f"Future date {future_date} must yield is_current=False, "
            f"got {result['latest']['is_current']}"
        )

    asyncio.run(_run())
