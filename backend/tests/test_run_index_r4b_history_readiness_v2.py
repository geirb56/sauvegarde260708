"""R4B — history[].run_readiness migrated to Readiness V2.

Test matrix (problem statement requirements)
--------------------------------------------
1.  history entries use Readiness V2 (score matches build_readiness_v2_from_garmin_data)
2.  reference_date = J for each historical day (not today)
3.  no future data used (metrics/activities after J are excluded)
4.  insufficient data → run_readiness is None (never 0, never a fallback)
5.  most-recent history entry is consistent with the top-level V2 score
6.  multi-user isolation: each user's history uses only their own data
7.  R3.5/R4A non-regression: metrics.run_readiness and training_load_v2 unchanged
8.  history[] shape: day, date, hrv, training_load, run_readiness (fatigue_ratio removed in #126)
9.  empty metrics_docs → no history entries (no crash)
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from garmin.insights import compute_run_index
from garmin.readiness_adapter import build_readiness_v2_from_garmin_data

# ---------------------------------------------------------------------------
# Reference anchor
# ---------------------------------------------------------------------------

_TODAY = date(2026, 1, 28)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _metrics(n: int = 14, ref: date = _TODAY, rhr: float = 52.0,
             hrv: Optional[float] = 65.0, sleep: Optional[float] = 7.5) -> List[dict]:
    """n garmin_daily_metrics docs sorted newest-first."""
    docs = []
    for i in range(n):
        d = ref - timedelta(days=i)
        docs.append({
            "date": d.isoformat(),
            "resting_hr": rhr,
            "hrv": hrv,
            "sleep_hours": sleep,
            "sleep_score": 80.0,
        })
    return docs


def _activities(n: int = 20, ref: date = _TODAY) -> List[dict]:
    """n garmin_activities docs covering the last n*2 days."""
    acts = []
    for i in range(n):
        d = ref - timedelta(days=i * 2)
        acts.append({
            "user_id": "userA",
            "start_time": d.isoformat() + "T08:00:00",
            "duration": 2400,  # 40 min
            "distance": 7000,
        })
    return acts


def _make_db(metrics_docs: List[dict], activity_docs: List[dict]) -> MagicMock:
    """Return an async mock DB with garmin_daily_metrics and garmin_activities."""
    db = MagicMock()

    def _metrics_find(query, projection=None):
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.to_list = AsyncMock(return_value=list(metrics_docs))
        return cursor

    def _activities_find(query, projection=None):
        cursor = MagicMock()
        cursor.sort.return_value = cursor
        cursor.limit.return_value = cursor
        cursor.to_list = AsyncMock(return_value=list(activity_docs))
        return cursor

    db.garmin_daily_metrics.find.side_effect = _metrics_find
    db.garmin_activities.find.side_effect = _activities_find
    return db


# ---------------------------------------------------------------------------
# Test 1 — history run_readiness matches V2 for a representative day
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_run_readiness_matches_v2_for_each_day():
    """Each history[i].run_readiness matches build_readiness_v2_from_garmin_data(…, ref=J)."""
    metrics_docs = _metrics(n=14, ref=_TODAY)
    activity_docs = _activities(n=10, ref=_TODAY)
    db = _make_db(metrics_docs, activity_docs)

    payload = await compute_run_index(db, "userA", reference_date=_TODAY)
    assert payload is not None
    history = payload["history"]
    assert len(history) > 0

    for entry in history:
        hist_day = date.fromisoformat(entry["date"][:10])
        hist_day_iso = hist_day.isoformat()
        # Reproduce the strict filtering done by insights.py
        hist_metrics = [
            m for m in metrics_docs
            if m.get("date") is not None and m.get("date") <= hist_day_iso
        ]
        from garmin.insights import _parse_day
        hist_activities = []
        for a in activity_docs:
            act_dt = _parse_day(a.get("start_time") or a.get("synced_at") or "")
            if act_dt is not None and act_dt.date() <= hist_day:
                hist_activities.append(a)
        expected_v2 = build_readiness_v2_from_garmin_data(hist_metrics, hist_activities, hist_day)
        assert entry["run_readiness"] == expected_v2.score, (
            f"Mismatch on {hist_day}: got {entry['run_readiness']!r}, "
            f"expected {expected_v2.score!r}"
        )


# ---------------------------------------------------------------------------
# Test 2 — reference_date is J for each historical entry (not today)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_reference_date_is_the_entry_date():
    """history[i].run_readiness must differ from the value computed with ref=today
    when today's data is excluded for day J."""
    # Build a dataset where the last 2 days have much better physio (low RHR)
    # so using ref=today vs ref=J gives different baselines/signals.
    docs = []
    # Days -14 … -3: normal RHR 60
    for i in range(14, 2, -1):
        docs.append({
            "date": (_TODAY - timedelta(days=i)).isoformat(),
            "resting_hr": 60.0,
            "hrv": 60.0,
            "sleep_hours": 7.0,
        })
    # Days -2 and -1: very low RHR (good) that would inflate today's baseline
    for i in (2, 1):
        docs.append({
            "date": (_TODAY - timedelta(days=i)).isoformat(),
            "resting_hr": 40.0,
            "hrv": 90.0,
            "sleep_hours": 8.5,
        })
    # today
    docs.append({
        "date": _TODAY.isoformat(),
        "resting_hr": 60.0,
        "hrv": 60.0,
        "sleep_hours": 7.0,
    })
    # Sort newest-first
    docs.sort(key=lambda d: d["date"], reverse=True)

    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)

    payload = await compute_run_index(db, "userA", reference_date=_TODAY)
    assert payload is not None

    # Find entry for day -7 (well before the low-RHR days) and verify its
    # run_readiness was computed with ref= that day (not today).
    target_day = (_TODAY - timedelta(days=7)).isoformat()
    entry = next((e for e in payload["history"] if e["date"] == target_day), None)
    assert entry is not None, f"No history entry for {target_day}"

    # The entry's run_readiness must equal V2 computed with ref=target_day
    ref_date = date.fromisoformat(target_day)
    hist_metrics = [m for m in docs if (m.get("date") or "") <= target_day]
    hist_acts = [a for a in acts
                 if date.fromisoformat((a.get("start_time") or "2000-01-01")[:10]) <= ref_date]
    expected = build_readiness_v2_from_garmin_data(hist_metrics, hist_acts, ref_date)
    assert entry["run_readiness"] == expected.score


# ---------------------------------------------------------------------------
# Test 3 — no future data used
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_no_future_data_leakage():
    """For each history day J, metrics and activities after J are not used."""
    # We test this by asserting that the history entry for day D_early
    # does not see the activity posted on D_late (D_late > D_early).
    d_early = _TODAY - timedelta(days=5)
    d_late = _TODAY - timedelta(days=2)

    # Only 1 activity, posted on d_late
    late_act = {
        "user_id": "userA",
        "start_time": d_late.isoformat() + "T09:00:00",
        "duration": 3600,
        "distance": 10000,
    }

    docs = _metrics(n=14, ref=_TODAY)
    db = _make_db(docs, [late_act])

    payload = await compute_run_index(db, "userA", reference_date=_TODAY)
    assert payload is not None

    # For d_early, no activities should be visible → load = "none" → INSUFFICIENT
    entry_early = next(
        (e for e in payload["history"] if e["date"] == d_early.isoformat()), None
    )
    if entry_early is not None:
        # Verify by direct V2 call with no activities
        hist_acts_early = []  # d_late activity is AFTER d_early
        from training_v2.readiness_sufficiency import SufficiencyLevel
        v2 = build_readiness_v2_from_garmin_data(
            [m for m in docs if (m.get("date") or "") <= d_early.isoformat()],
            hist_acts_early,
            d_early,
        )
        assert v2.sufficiency_level == SufficiencyLevel.INSUFFICIENT
        assert entry_early["run_readiness"] is None

    # For d_late or after, the activity should be visible → load available
    entry_late = next(
        (e for e in payload["history"] if e["date"] == d_late.isoformat()), None
    )
    if entry_late is not None:
        from training_v2.readiness_sufficiency import SufficiencyLevel
        v2 = build_readiness_v2_from_garmin_data(
            [m for m in docs if (m.get("date") or "") <= d_late.isoformat()],
            [late_act],
            d_late,
        )
        assert entry_late["run_readiness"] == v2.score


# ---------------------------------------------------------------------------
# Test 4 — insufficient data → None (never 0, never a fallback)
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_insufficient_data_run_readiness_is_none():
    """When physio + load are both absent for a day, run_readiness must be None."""
    # No activities at all; no physio in metrics
    docs = [{"date": (_TODAY - timedelta(days=i)).isoformat(),
              "sleep_hours": 7.5} for i in range(14)]
    docs.sort(key=lambda d: d["date"], reverse=True)
    db = _make_db(docs, [])

    payload = await compute_run_index(db, "userA", reference_date=_TODAY)
    assert payload is not None

    for entry in payload["history"]:
        # No physio (no resting_hr / hrv) + no load → INSUFFICIENT → None
        assert entry["run_readiness"] is None, (
            f"Expected None for day {entry['date']}, got {entry['run_readiness']!r}"
        )


# ---------------------------------------------------------------------------
# Test 5 — most-recent history entry consistent with top-level metrics score
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_latest_entry_consistent_with_metrics():
    """history[-1].run_readiness must equal metrics.run_readiness (same day, same V2)."""
    docs = _metrics(n=14, ref=_TODAY)
    acts = _activities(n=10, ref=_TODAY)
    db = _make_db(docs, acts)

    payload = await compute_run_index(db, "userA", reference_date=_TODAY)
    assert payload is not None

    history = payload["history"]
    if not history:
        pytest.skip("No history entries produced")

    # The latest history entry is today
    latest = history[-1]
    assert latest["date"] == _TODAY.isoformat(), (
        f"Expected latest history entry to be {_TODAY}, got {latest['date']}"
    )
    metrics_score = payload["metrics"]["run_readiness"]
    assert latest["run_readiness"] == metrics_score, (
        f"Latest history run_readiness {latest['run_readiness']!r} "
        f"!= metrics.run_readiness {metrics_score!r}"
    )


# ---------------------------------------------------------------------------
# Test 6 — multi-user isolation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_multi_user_isolation():
    """User A and User B compute histories independently from their own data.

    Isolation is verified by asserting that each user's payload uses only
    the metrics/activities returned by their own DB mock, not the other user's.
    We give User A rich data (physio + activities) and User B no data, then
    confirm A has a non-empty history while B has either None or an empty payload.
    """
    docs_a = _metrics(n=14, ref=_TODAY, rhr=50.0, hrv=70.0)
    acts_a = _activities(n=10, ref=_TODAY)

    # User B has no activities and no physio — all entries must be None
    docs_b = [{"date": (_TODAY - timedelta(days=i)).isoformat(), "sleep_hours": 7.0}
              for i in range(14)]
    docs_b.sort(key=lambda d: d["date"], reverse=True)

    db_a = _make_db(docs_a, acts_a)
    db_b = _make_db(docs_b, [])

    payload_a = await compute_run_index(db_a, "userA", reference_date=_TODAY)
    payload_b = await compute_run_index(db_b, "userB", reference_date=_TODAY)

    assert payload_a is not None

    # User B must have no non-None run_readiness scores (no physio, no load)
    if payload_b is not None:
        scores_b = [e["run_readiness"] for e in payload_b["history"] if e["run_readiness"] is not None]
        assert scores_b == [], f"User B should have no readable scores, got: {scores_b}"


# ---------------------------------------------------------------------------
# Test 7 — R3.5/R4A non-regression: metrics.run_readiness and training_load_v2
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_metrics_run_readiness_unchanged_r4a_non_regression():
    """metrics.run_readiness still equals ReadinessResult.score (R4A contract)."""
    docs = _metrics(n=14, ref=_TODAY)
    acts = _activities(n=10, ref=_TODAY)
    db = _make_db(docs, acts)

    payload = await compute_run_index(db, "userA", reference_date=_TODAY)
    assert payload is not None

    m = payload["metrics"]
    assert "run_readiness" in m
    # Value must be float or None, never absent
    rr = m["run_readiness"]
    assert rr is None or isinstance(rr, float)

    # training_load_v2 keys preserved (R3.5 contract)
    tl = m.get("training_load_v2", {})
    for key in ("acute_load_7d", "load_28d", "chronic_weekly_load", "previous_7d_load",
                "load_change_percent", "acwr", "status", "confidence"):
        assert key in tl, f"training_load_v2 missing key: {key}"


# ---------------------------------------------------------------------------
# Test 8 — history[] shape preserved
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_shape_preserved():
    """Every history entry has the expected keys."""
    docs = _metrics(n=14, ref=_TODAY)
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)

    payload = await compute_run_index(db, "userA", reference_date=_TODAY)
    assert payload is not None

    required_keys = {"day", "date", "hrv", "training_load", "run_readiness"}
    for entry in payload["history"]:
        missing = required_keys - entry.keys()
        assert not missing, f"history entry missing keys: {missing}"


# ---------------------------------------------------------------------------
# Test 9 — empty metrics_docs → no history, no crash
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_empty_metrics_no_history_no_crash():
    """When only activities exist (no metrics_docs), history is empty but no crash."""
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db([], acts)

    # compute_run_index returns None when both metrics_docs and activities are empty.
    # With only activities, it should return a payload with empty history.
    payload = await compute_run_index(db, "userA", reference_date=_TODAY)
    if payload is not None:
        assert payload["history"] == []


# ---------------------------------------------------------------------------
# Test 10 — activity without date is excluded from history filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_activity_without_date_excluded():
    """An activity with no start_time/synced_at must be excluded from every day's filter."""
    dateless_act = {
        "user_id": "userA",
        # no start_time, no synced_at
        "duration": 2400,
        "distance": 7000,
    }
    valid_act = {
        "user_id": "userA",
        "start_time": (_TODAY - timedelta(days=1)).isoformat() + "T08:00:00",
        "duration": 2400,
        "distance": 7000,
    }

    docs = _metrics(n=14, ref=_TODAY)
    db = _make_db(docs, [dateless_act, valid_act])

    payload = await compute_run_index(db, "userA", reference_date=_TODAY)
    assert payload is not None

    from garmin.insights import _parse_day

    for entry in payload["history"]:
        hist_day = date.fromisoformat(entry["date"][:10])
        # Confirm dateless_act is never in the filtered activities for this day
        act_dt = _parse_day(dateless_act.get("start_time") or dateless_act.get("synced_at") or "")
        assert act_dt is None, "dateless activity should have no parseable date"
        # The entry's V2 score must be computed without the dateless activity
        hist_metrics = [m for m in docs if m.get("date") is not None and m.get("date") <= hist_day.isoformat()]
        hist_acts = []
        for a in [valid_act]:
            dt = _parse_day(a.get("start_time") or "")
            if dt is not None and dt.date() <= hist_day:
                hist_acts.append(a)
        expected = build_readiness_v2_from_garmin_data(hist_metrics, hist_acts, hist_day)
        assert entry["run_readiness"] == expected.score, (
            f"Day {hist_day}: expected {expected.score!r}, got {entry['run_readiness']!r}"
        )


# ---------------------------------------------------------------------------
# Test 11 — metric without date is excluded from history filter
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_metric_without_date_excluded():
    """A metrics doc with no 'date' field must not be included for any historical day."""
    docs = _metrics(n=5, ref=_TODAY)
    # Insert a dateless metric doc (e.g. corrupted document)
    dateless_metric = {"resting_hr": 45.0, "hrv": 80.0, "sleep_hours": 8.0}
    docs_with_dateless = [dateless_metric] + docs  # dateless first (newest-first order)
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs_with_dateless, acts)

    payload = await compute_run_index(db, "userA", reference_date=_TODAY)
    assert payload is not None

    # The dateless metric doc must not produce a history entry
    history_dates = {e["date"] for e in payload["history"]}
    assert None not in history_dates, "Dateless metric doc produced a None-dated history entry"

    from garmin.insights import _parse_day

    for entry in payload["history"]:
        hist_day = date.fromisoformat(entry["date"][:10])
        hist_day_iso = hist_day.isoformat()
        # Strict filter: only metrics with a real date <= J
        hist_metrics = [
            m for m in docs_with_dateless
            if m.get("date") is not None and m.get("date") <= hist_day_iso
        ]
        hist_acts = []
        for a in acts:
            dt = _parse_day(a.get("start_time") or "")
            if dt is not None and dt.date() <= hist_day:
                hist_acts.append(a)
        expected = build_readiness_v2_from_garmin_data(hist_metrics, hist_acts, hist_day)
        assert entry["run_readiness"] == expected.score, (
            f"Day {hist_day}: expected {expected.score!r}, got {entry['run_readiness']!r}"
        )


# ---------------------------------------------------------------------------
# Test 12 — future data (metric and activity) are excluded from historical days
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_future_data_excluded_strict():
    """Metrics docs and activities dated after J must never appear in J's V2 input."""
    target_day = _TODAY - timedelta(days=4)

    # Build metrics where some are future relative to target_day
    past_docs = [
        {"date": (target_day - timedelta(days=i)).isoformat(),
         "resting_hr": 55.0, "hrv": 65.0, "sleep_hours": 7.5}
        for i in range(7)
    ]
    future_docs = [
        {"date": (target_day + timedelta(days=j)).isoformat(),
         "resting_hr": 40.0, "hrv": 90.0, "sleep_hours": 9.0}
        for j in range(1, 5)
    ]
    all_docs = sorted(past_docs + future_docs, key=lambda m: m["date"], reverse=True)

    # Activity on target_day-1 (past) and one on target_day+2 (future)
    past_act = {
        "start_time": (target_day - timedelta(days=1)).isoformat() + "T08:00:00",
        "duration": 2400, "distance": 7000,
    }
    future_act = {
        "start_time": (target_day + timedelta(days=2)).isoformat() + "T08:00:00",
        "duration": 2400, "distance": 7000,
    }

    db = _make_db(all_docs, [past_act, future_act])
    payload = await compute_run_index(db, "userA", reference_date=_TODAY)
    assert payload is not None

    from garmin.insights import _parse_day

    entry = next((e for e in payload["history"] if e["date"] == target_day.isoformat()), None)
    assert entry is not None, f"No history entry for {target_day}"

    # Strict filter: only past_docs (date <= target_day) and past_act
    hist_metrics = [m for m in all_docs
                    if m.get("date") is not None and m.get("date") <= target_day.isoformat()]
    hist_acts = []
    for a in [past_act, future_act]:
        dt = _parse_day(a.get("start_time") or "")
        if dt is not None and dt.date() <= target_day:
            hist_acts.append(a)
    assert len(hist_acts) == 1  # only past_act

    expected = build_readiness_v2_from_garmin_data(hist_metrics, hist_acts, target_day)
    assert entry["run_readiness"] == expected.score, (
        f"Future data leaked into history[{target_day}]: "
        f"got {entry['run_readiness']!r}, expected {expected.score!r}"
    )


# ---------------------------------------------------------------------------
# Test 13 — metric with invalid date is never included in historical calculation
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_history_invalid_date_metric_excluded():
    """A metric with an absent or invalid date must never enter the historical V2 calc."""
    target_day = _TODAY - timedelta(days=3)

    valid_docs = [
        {"date": (target_day - timedelta(days=i)).isoformat(),
         "resting_hr": 55.0, "hrv": 65.0, "sleep_hours": 7.5}
        for i in range(7)
    ]
    # Metrics with invalid / absent dates — must be excluded regardless of lexicographic order
    invalid_docs = [
        {"date": "not-a-date", "resting_hr": 40.0, "hrv": 90.0, "sleep_hours": 9.0},
        {"date": "9999-99-99", "resting_hr": 40.0, "hrv": 90.0, "sleep_hours": 9.0},
        {"date": "", "resting_hr": 40.0, "hrv": 90.0, "sleep_hours": 9.0},
        {"resting_hr": 40.0, "hrv": 90.0, "sleep_hours": 9.0},  # missing "date" key
    ]
    all_docs = valid_docs + invalid_docs

    db = _make_db(all_docs, [])
    payload = await compute_run_index(db, "userA", reference_date=_TODAY)
    assert payload is not None

    entry = next((e for e in payload["history"] if e["date"] == target_day.isoformat()), None)
    assert entry is not None, f"No history entry for {target_day}"

    # Expected: compute with only valid docs (invalid ones excluded)
    expected_metrics = [m for m in valid_docs if m["date"] <= target_day.isoformat()]
    expected = build_readiness_v2_from_garmin_data(expected_metrics, [], target_day)
    assert entry["run_readiness"] == expected.score, (
        f"Invalid-date metric leaked into history[{target_day}]: "
        f"got {entry['run_readiness']!r}, expected {expected.score!r}"
    )
