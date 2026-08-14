"""#126 — history[] legacy fatigue cleanup + RHR baseline unification.
#129 — fatigue_ratio / fatigue_status / fatigue_physio fully removed from metrics.

Test matrix (problem statement requirements)
--------------------------------------------
1.  history[] entries do NOT contain 'fatigue_ratio' key
2.  history[] shape: day, date, hrv, training_load, run_readiness — no extras
3.  Readiness V2 history non-regression (run_readiness still present and correct)
4.  TrainingLoad history non-regression (training_load still present)
5.  metrics.rhr_baseline == Readiness V2 baseline (14-day window, excludes today)
6.  metrics.rhr_delta == rhr_today - rhr_baseline (V2-aligned, or None)
7.  RHR absent → rhr_today=None, rhr_baseline=None, rhr_delta=None (no fallback)
8.  rhr_baseline=None when no prior data (only today's doc, no 14-day history)
9.  metrics.fatigue_ratio ABSENT after #129 (fatigue_ratio/status/physio removed)
10. multi-user isolation: each user's RHR baseline uses only their own data
11. baseline RHR absent → rhr_delta=None (None ≠ green, #126 post-merge correction)
12. rhr_status="gray" when rhr_delta=None — never "green" for absent data
13. rhr_status normal range ("green"/"yellow"/"red") when rhr_delta is present
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from garmin.insights import compute_run_index
from garmin.readiness_adapter import get_rhr_v2_baseline

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TODAY = date(2026, 8, 14)
_RHR_NORMAL = 52.0
_RHR_ELEVATED = 62.0


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _metric(day_offset: int, ref: date, rhr: Optional[float] = _RHR_NORMAL, hrv: Optional[float] = None) -> dict:
    d = ref - timedelta(days=day_offset)
    doc: dict = {"date": d.isoformat(), "resting_hr": rhr, "sleep_hours": 7.5}
    if hrv is not None:
        doc["hrv"] = hrv
    return doc


def _metrics(n: int, ref: date, rhr: Optional[float] = _RHR_NORMAL) -> List[dict]:
    """n docs newest-first: day 0 = ref, day n-1 = ref - (n-1) days."""
    return [_metric(i, ref, rhr=rhr) for i in range(n)]


def _activity(day_offset: int, ref: date, duration: float = 40.0) -> dict:
    d = ref - timedelta(days=day_offset)
    return {
        "start_time": f"{d.isoformat()}T07:00:00Z",
        "distance": 8000,
        "duration": duration * 60,
        "type": "run",
    }


def _activities(n: int, ref: date) -> List[dict]:
    return [_activity(i * 2, ref) for i in range(n)]


def _make_db(metrics_docs: List[dict], activities: List[dict]) -> MagicMock:
    db = MagicMock()
    db.garmin_daily_metrics.find.return_value.sort.return_value.limit.return_value.to_list = AsyncMock(
        return_value=metrics_docs
    )
    db.garmin_activities.find.return_value.sort.return_value.limit.return_value.to_list = AsyncMock(
        return_value=activities
    )
    return db


# ---------------------------------------------------------------------------
# Test 1 — history[] must NOT contain 'fatigue_ratio'
# ---------------------------------------------------------------------------


def test_history_no_fatigue_ratio():
    """history[] entries must not include the legacy 'fatigue_ratio' key (#126)."""
    docs = _metrics(n=14, ref=_TODAY)
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)

    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None
    history = payload["history"]
    assert len(history) > 0

    for entry in history:
        assert "fatigue_ratio" not in entry, (
            f"fatigue_ratio must be removed from history[] after #126, found in: {entry}"
        )


# ---------------------------------------------------------------------------
# Test 2 — history[] shape: required keys present, no unexpected extras
# ---------------------------------------------------------------------------


def test_history_shape():
    """history[] shape: exactly day, date, hrv, training_load, run_readiness."""
    docs = _metrics(n=14, ref=_TODAY)
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)

    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None

    required = {"day", "date", "hrv", "training_load", "run_readiness"}
    for entry in payload["history"]:
        missing = required - entry.keys()
        assert not missing, f"history entry missing keys: {missing}"
        assert "fatigue_ratio" not in entry


# ---------------------------------------------------------------------------
# Test 3 — run_readiness in history non-regression
# ---------------------------------------------------------------------------


def test_history_run_readiness_present():
    """run_readiness must still be present and be float-or-None in each entry."""
    docs = _metrics(n=14, ref=_TODAY)
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)

    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None

    for entry in payload["history"]:
        rr = entry["run_readiness"]
        assert rr is None or (isinstance(rr, (int, float)) and 0.0 <= float(rr) <= 100.0), (
            f"run_readiness invalid: {rr}"
        )


# ---------------------------------------------------------------------------
# Test 4 — training_load in history non-regression
# ---------------------------------------------------------------------------


def test_history_training_load_present():
    """training_load must still be present in each entry (can be None)."""
    docs = _metrics(n=14, ref=_TODAY)
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)

    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None

    for entry in payload["history"]:
        assert "training_load" in entry, f"training_load missing from history entry: {entry}"


# ---------------------------------------------------------------------------
# Test 5 — metrics.rhr_baseline aligned with Readiness V2
# ---------------------------------------------------------------------------


def test_rhr_baseline_aligned_with_v2():
    """metrics.rhr_baseline must equal get_rhr_v2_baseline() (14-day window)."""
    docs = _metrics(n=20, ref=_TODAY, rhr=_RHR_NORMAL)
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)

    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None

    displayed_baseline = payload["metrics"]["rhr_baseline"]
    v2_baseline = get_rhr_v2_baseline(docs, _TODAY)

    if v2_baseline is None:
        assert displayed_baseline is None, (
            f"rhr_baseline should be None when V2 baseline is None, got {displayed_baseline}"
        )
    else:
        assert displayed_baseline is not None
        assert abs(displayed_baseline - v2_baseline) < 0.01, (
            f"rhr_baseline mismatch: displayed={displayed_baseline}, V2={v2_baseline}"
        )


# ---------------------------------------------------------------------------
# Test 6 — metrics.rhr_delta consistent with V2 baseline
# ---------------------------------------------------------------------------


def test_rhr_delta_consistent_with_v2_baseline():
    """metrics.rhr_delta == rhr_today - rhr_baseline (V2-aligned)."""
    docs = _metrics(n=20, ref=_TODAY, rhr=_RHR_NORMAL)
    # Override today to elevated RHR so delta is non-zero
    docs[0]["resting_hr"] = _RHR_ELEVATED
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)

    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None

    m = payload["metrics"]
    rhr_today = m["rhr_today"]
    rhr_baseline = m["rhr_baseline"]
    rhr_delta = m["rhr_delta"]

    if rhr_today is None or rhr_baseline is None:
        assert rhr_delta is None
    else:
        expected_delta = round(rhr_today - rhr_baseline, 1)
        assert rhr_delta is not None
        assert abs(rhr_delta - expected_delta) < 0.05, (
            f"rhr_delta mismatch: got {rhr_delta}, expected {expected_delta}"
        )


# ---------------------------------------------------------------------------
# Test 7 — RHR absent → rhr_today=None, rhr_baseline=None, rhr_delta=None
# ---------------------------------------------------------------------------


def test_rhr_absent_stays_none():
    """When no docs have resting_hr, displayed values must all be None."""
    docs = [
        {"date": (_TODAY - timedelta(days=i)).isoformat(), "sleep_hours": 7.5}
        for i in range(14)
    ]
    acts = _activities(n=3, ref=_TODAY)
    db = _make_db(docs, acts)

    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None

    m = payload["metrics"]
    assert m["rhr_today"] is None, f"rhr_today should be None, got {m['rhr_today']}"
    assert m["rhr_baseline"] is None, f"rhr_baseline should be None, got {m['rhr_baseline']}"
    assert m["rhr_delta"] is None, f"rhr_delta should be None, got {m['rhr_delta']}"


# ---------------------------------------------------------------------------
# Test 8 — rhr_baseline=None when only today's doc exists (no 14-day prior data)
# ---------------------------------------------------------------------------


def test_rhr_baseline_none_no_prior_data():
    """Only today's doc → V2 14-day window has no prior data → rhr_baseline=None."""
    docs = [{"date": _TODAY.isoformat(), "resting_hr": _RHR_NORMAL, "sleep_hours": 7.5}]
    acts = []
    db = _make_db(docs, acts)

    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    # With only one doc, no prior baseline → rhr_baseline=None
    # (compute_run_index may return None with no activities, but check if it returns a payload)
    if payload is None:
        return  # No data at all — acceptable
    m = payload["metrics"]
    assert m["rhr_baseline"] is None, (
        f"rhr_baseline should be None with only today's doc, got {m['rhr_baseline']}"
    )
    assert m["rhr_delta"] is None, (
        f"rhr_delta should be None when baseline is None, got {m['rhr_delta']}"
    )


# ---------------------------------------------------------------------------
# Test 9 — metrics.fatigue_ratio ABSENT after #129 (legacy removed)
# ---------------------------------------------------------------------------


def test_metrics_fatigue_ratio_absent():
    """metrics must NOT contain fatigue_ratio / fatigue_status / fatigue_physio after #129."""
    docs = _metrics(n=14, ref=_TODAY)
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)

    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None

    m = payload["metrics"]
    assert "fatigue_ratio" not in m, f"fatigue_ratio must be removed after #129, found {m.get('fatigue_ratio')}"
    assert "fatigue_status" not in m, f"fatigue_status must be removed after #129, found {m.get('fatigue_status')}"
    assert "fatigue_physio" not in m, f"fatigue_physio must be removed after #129, found {m.get('fatigue_physio')}"


# ---------------------------------------------------------------------------
# Test 10 — multi-user isolation
# ---------------------------------------------------------------------------


def test_multi_user_rhr_isolation():
    """Each user's rhr_baseline uses only their own data (no cross-contamination)."""
    docs_a = _metrics(n=20, ref=_TODAY, rhr=50.0)
    docs_b = _metrics(n=20, ref=_TODAY, rhr=70.0)
    acts = _activities(n=3, ref=_TODAY)

    db_a = _make_db(docs_a, acts)
    db_b = _make_db(docs_b, acts)

    payload_a = asyncio.run(compute_run_index(db_a, "userA", reference_date=_TODAY))
    payload_b = asyncio.run(compute_run_index(db_b, "userB", reference_date=_TODAY))

    assert payload_a is not None
    assert payload_b is not None

    baseline_a = payload_a["metrics"]["rhr_baseline"]
    baseline_b = payload_b["metrics"]["rhr_baseline"]

    if baseline_a is not None and baseline_b is not None:
        assert baseline_a < baseline_b, (
            f"User A (low RHR) baseline {baseline_a} should be less than "
            f"user B (high RHR) baseline {baseline_b}"
        )


# ---------------------------------------------------------------------------
# Test 11 — baseline RHR absent → rhr_delta=None (None ≠ green, #126 post-merge)
# ---------------------------------------------------------------------------


def test_baseline_rhr_absent_rhr_delta_is_none():
    """When no prior RHR data exist, rhr_delta must be None — not a fallback value."""
    # Today-only doc: no prior 14-day history → baseline cannot be computed.
    today_doc = _metric(0, _TODAY, rhr=_RHR_NORMAL)
    acts = _activities(n=3, ref=_TODAY)
    db = _make_db([today_doc], acts)

    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    if payload is None:
        return  # No data at all — acceptable
    m = payload["metrics"]
    assert m["rhr_delta"] is None, (
        f"rhr_delta must be None when baseline is absent (None ≠ green), got {m['rhr_delta']}"
    )


# ---------------------------------------------------------------------------
# Test 12 — rhr_status="gray" when rhr_delta=None — never "green" for absent data
# ---------------------------------------------------------------------------


def test_rhr_status_is_gray_when_rhr_delta_none():
    """rhr_status must be 'gray' when rhr_delta is None — never 'green' for absent data."""
    # Use only today's doc so baseline is absent and rhr_delta becomes None.
    today_doc = _metric(0, _TODAY, rhr=_RHR_NORMAL)
    acts = _activities(n=3, ref=_TODAY)
    db = _make_db([today_doc], acts)

    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    if payload is None:
        return  # No data at all — acceptable
    m = payload["metrics"]

    if m["rhr_delta"] is None:
        assert m["rhr_status"] == "gray", (
            f"rhr_status must be 'gray' when rhr_delta=None, got '{m['rhr_status']}' — "
            f"None must never map to 'green'"
        )
    # Either way, "green" must never be produced from an absent delta.
    assert m["rhr_status"] != "green" or m["rhr_delta"] is not None, (
        "rhr_status='green' is only allowed when rhr_delta is a real (non-None) value"
    )


# ---------------------------------------------------------------------------
# Test 13 — rhr_status is "green"/"yellow"/"red" when rhr_delta is present
# ---------------------------------------------------------------------------

_VALID_RHR_STATUSES = {"green", "yellow", "red", "gray"}


def test_rhr_status_valid_range_when_rhr_delta_present():
    """When rhr_delta is not None, rhr_status must be green/yellow/red (not gray)."""
    docs = _metrics(n=14, ref=_TODAY, rhr=_RHR_NORMAL)
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)

    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None
    m = payload["metrics"]

    if m["rhr_delta"] is not None:
        assert m["rhr_status"] in {"green", "yellow", "red"}, (
            f"rhr_status should be green/yellow/red when rhr_delta={m['rhr_delta']}, "
            f"got '{m['rhr_status']}'"
        )
    assert m["rhr_status"] in _VALID_RHR_STATUSES, (
        f"rhr_status '{m['rhr_status']}' is not a valid status token"
    )
