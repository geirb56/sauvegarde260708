"""PR #129 — Remove legacy fatigue_ratio / fatigue_status / fatigue_physio.

Test matrix
-----------
1.  metrics does NOT contain 'fatigue_ratio'
2.  metrics does NOT contain 'fatigue_status'
3.  metrics does NOT contain 'fatigue_physio'
4.  Readiness V2 fields (run_readiness, run_readiness_status, confidence) still present
5.  history[] entries do NOT contain 'fatigue_ratio'
6.  Recommendation still produced (one of RUN HARD / EASY RUN / REST / UNAVAILABLE)
7.  reasons list does NOT contain a 'Fatigue Ratio' string
8.  multi-user: fatigue fields absent for each user independently
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_TODAY = date(2026, 8, 14)
_RHR_NORMAL = 52.0
_HRV_NORMAL = 55.0

VALID_RECOMMENDATIONS = {"RUN HARD", "EASY RUN", "REST", "UNAVAILABLE"}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _metric(day_offset: int, ref: date, rhr: Optional[float] = _RHR_NORMAL, hrv: Optional[float] = _HRV_NORMAL) -> dict:
    d = ref - timedelta(days=day_offset)
    m: dict = {"date": d.isoformat(), "sleep_hours": 7.5, "sleep_quality": 85}
    if rhr is not None:
        m["rhr"] = rhr
    if hrv is not None:
        m["hrv"] = hrv
    return m


def _metrics(n: int, ref: date) -> List[dict]:
    return [_metric(i, ref) for i in range(n)]


def _activities(n: int, ref: date) -> List[dict]:
    return [
        {
            "activity_type": "running",
            "start_time": (ref - timedelta(days=i)).isoformat(),
            "distance_m": 8000.0,
            "duration_s": 2400.0,
        }
        for i in range(n)
    ]


def _make_db(docs: List[dict], acts: List[dict], user_id: str = "userA") -> MagicMock:
    db = MagicMock()

    async def _find_one(*args, **kwargs):
        return None

    db.garmin_connections.find_one = AsyncMock(return_value=None)
    db.daily_metrics.find_one = AsyncMock(return_value=None)
    db.baselines.find_one = AsyncMock(return_value=None)

    def _make_cursor(items):
        cursor = MagicMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.limit = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=list(items))
        cursor.__aiter__ = MagicMock(return_value=iter(items))
        return cursor

    # garmin_daily_metrics (used by compute_run_index)
    db.garmin_daily_metrics.find = MagicMock(return_value=_make_cursor(docs))
    # garmin_activities
    db.garmin_activities.find = MagicMock(return_value=_make_cursor(acts))

    return db


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


def test_metrics_no_fatigue_ratio():
    """metrics must NOT contain 'fatigue_ratio' after #129."""
    docs = _metrics(n=14, ref=_TODAY)
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)
    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None
    assert "fatigue_ratio" not in payload["metrics"], (
        f"fatigue_ratio must be removed after #129, found: {payload['metrics'].get('fatigue_ratio')}"
    )


def test_metrics_no_fatigue_status():
    """metrics must NOT contain 'fatigue_status' after #129."""
    docs = _metrics(n=14, ref=_TODAY)
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)
    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None
    assert "fatigue_status" not in payload["metrics"], (
        f"fatigue_status must be removed after #129, found: {payload['metrics'].get('fatigue_status')}"
    )


def test_metrics_no_fatigue_physio():
    """metrics must NOT contain 'fatigue_physio' after #129."""
    docs = _metrics(n=14, ref=_TODAY)
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)
    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None
    assert "fatigue_physio" not in payload["metrics"], (
        f"fatigue_physio must be removed after #129, found: {payload['metrics'].get('fatigue_physio')}"
    )


def test_readiness_v2_still_present():
    """Readiness V2 fields must still be present in metrics after #129."""
    docs = _metrics(n=14, ref=_TODAY)
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)
    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None
    m = payload["metrics"]
    assert "run_readiness" in m, "run_readiness must remain in metrics"
    assert "run_readiness_status" in m, "run_readiness_status must remain in metrics"
    assert "confidence" in m, "confidence must remain in metrics"


def test_history_no_fatigue_ratio():
    """history[] entries must NOT contain 'fatigue_ratio' after #129."""
    docs = _metrics(n=14, ref=_TODAY)
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)
    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None
    for entry in payload["history"]:
        assert "fatigue_ratio" not in entry, (
            f"fatigue_ratio must be absent from history[] after #129, found in: {entry}"
        )


def test_recommendation_still_present():
    """recommendation must still be one of the valid values after #129."""
    docs = _metrics(n=14, ref=_TODAY)
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)
    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None
    rec = payload.get("recommendation")
    # Localised forms are also acceptable; check the recommendation_color instead.
    assert payload.get("recommendation_color") in {"green", "yellow", "red", "gray"}, (
        f"recommendation_color must be green/yellow/red/gray, got: {payload.get('recommendation_color')}"
    )


def test_reasons_no_fatigue_ratio_string():
    """reasons must NOT contain a 'Fatigue Ratio' string after #129."""
    docs = _metrics(n=14, ref=_TODAY)
    acts = _activities(n=5, ref=_TODAY)
    db = _make_db(docs, acts)
    payload = asyncio.run(compute_run_index(db, "userA", reference_date=_TODAY))
    assert payload is not None
    reasons = payload.get("reasons", [])
    for r in reasons:
        assert "fatigue ratio" not in r.lower() and "ratio de fatigue" not in r.lower() and "ratio de fatiga" not in r.lower(), (
            f"'Fatigue Ratio' reason must be removed after #129, found: {r!r}"
        )


def test_multi_user_no_fatigue_fields():
    """fatigue fields absent for each of multiple users independently."""
    for user_id in ("userA", "userB", "userC"):
        docs = _metrics(n=10, ref=_TODAY)
        acts = _activities(n=3, ref=_TODAY)
        db = _make_db(docs, acts, user_id=user_id)
        payload = asyncio.run(compute_run_index(db, user_id, reference_date=_TODAY))
        assert payload is not None, f"payload is None for {user_id}"
        m = payload["metrics"]
        for field in ("fatigue_ratio", "fatigue_status", "fatigue_physio"):
            assert field not in m, (
                f"{field} must be absent for {user_id} after #129, found: {m.get(field)}"
            )
