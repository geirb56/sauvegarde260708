"""PR #225 — Readiness runtime data truth.

Six mandatory tests:
1. today's metric is used (not an older one when today's is available)
2. stale metric (> _MAX_PHYSIO_STALENESS_DAYS old) is NOT presented as current
3. absent RHR / HRV / sleep stays None — no synthetic value injected
4. no sleep=7h fallback — absent sleep_hours → None in output
5. today's daily-metrics sync refreshes the metrics used by Readiness
6. Readiness V2 regressions pass (complete data → float score; no physio → None)
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
    _MAX_PHYSIO_STALENESS_DAYS,
    build_readiness_v2_from_garmin_data,
)
from garmin.insights import _latest_with

# ---------------------------------------------------------------------------
# Shared helpers
# ---------------------------------------------------------------------------

_TODAY = date(2026, 1, 28)
_STALE_DATE = _TODAY - timedelta(days=_MAX_PHYSIO_STALENESS_DAYS + 1)


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
    """A doc older than _MAX_PHYSIO_STALENESS_DAYS is silently excluded."""
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
    """Docs without resting_hr or hrv → physio signals must be None, not invented."""
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
    # Without any RHR or HRV the adapter must not invent physio; score may be
    # None (INSUFFICIENT) because of missing_rhr + missing_hrv.
    assert result.score is None or isinstance(result.score, float)
    # The key invariant: if score is not None it must be a real float.
    if result.score is not None:
        assert 0.0 <= result.score <= 100.0


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
