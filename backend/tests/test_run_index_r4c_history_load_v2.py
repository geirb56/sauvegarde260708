"""#125 — history[].training_load aligned to TrainingLoad V2.

Test matrix (problem statement requirements)
--------------------------------------------
1.  history[J].training_load == build_training_load(activities_at_J, ref=J).acwr
2.  no future leakage: activities after J are excluded from the snapshot
3.  distance-only activities (no duration) → training_load is None
4.  insufficient history (< 28 days of data) → V2 exact behaviour (acwr can be None)
5.  /run-index current (metrics.training_load) non-regressed: still snapshot.acwr
6.  history entry shape preserved: training_load key always present
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import List, Optional
from unittest.mock import MagicMock

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from garmin.insights import compute_run_index
from training_v2.training_load import build_training_load

# ---------------------------------------------------------------------------
# Anchor date
# ---------------------------------------------------------------------------

_TODAY = date(2026, 3, 10)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _metrics(n: int = 20, ref: date = _TODAY) -> List[dict]:
    docs = []
    for i in range(n):
        d = ref - timedelta(days=i)
        docs.append({
            "date": d.isoformat(),
            "resting_hr": 52.0,
            "hrv": 65.0,
            "sleep_hours": 7.5,
            "sleep_score": 80.0,
        })
    return docs


def _duration_activities(n: int = 20, ref: date = _TODAY) -> List[dict]:
    """Running activities with valid duration, spread every other day."""
    acts = []
    for i in range(n):
        d = ref - timedelta(days=i * 2)
        acts.append({
            "user_id": "tester",
            "type": "running",
            "start_time": d.isoformat() + "T07:00:00",
            "duration": 3000,   # 50 min
            "distance": 10000,  # 10 km
        })
    return acts


def _distance_only_activities(n: int = 10, ref: date = _TODAY) -> List[dict]:
    """Running activities with distance but NO duration (should produce no load)."""
    acts = []
    for i in range(n):
        d = ref - timedelta(days=i * 3)
        acts.append({
            "user_id": "tester",
            "type": "running",
            "start_time": d.isoformat() + "T07:00:00",
            "duration": 0,       # zero → no duration
            "distance": 8000,
        })
    return acts


class AsyncMock(MagicMock):
    async def __call__(self, *args, **kwargs):
        return super().__call__(*args, **kwargs)


def _make_db(metrics_docs: List[dict], activity_docs: List[dict]) -> MagicMock:
    db = MagicMock()

    def _metrics_find(query, projection=None):
        cursor = MagicMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.limit = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=metrics_docs)
        return cursor

    def _activities_find(query, projection=None):
        cursor = MagicMock()
        cursor.sort = MagicMock(return_value=cursor)
        cursor.limit = MagicMock(return_value=cursor)
        cursor.to_list = AsyncMock(return_value=activity_docs)
        return cursor

    db.garmin_daily_metrics.find = _metrics_find
    db.garmin_activities.find = _activities_find
    db.garmin_vo2max.find_one = AsyncMock(return_value=None)
    return db


# ---------------------------------------------------------------------------
# Test 1 — history[J].training_load == build_training_load(acts_at_J, J).acwr
# ---------------------------------------------------------------------------

def test_history_training_load_equals_v2_acwr():
    """Each history entry's training_load must equal the V2 snapshot acwr at that day."""
    acts = _duration_activities(n=30, ref=_TODAY)
    db = _make_db(_metrics(n=20, ref=_TODAY), acts)

    payload = asyncio.run(compute_run_index(db, "tester", reference_date=_TODAY))
    assert payload is not None
    history = payload["history"]
    assert history, "history must not be empty"

    for entry in history:
        day_str = entry["date"]
        hist_day = date.fromisoformat(day_str[:10])

        # Build V2 snapshot using only activities available at hist_day
        hist_acts = [
            a for a in acts
            if datetime.fromisoformat(
                (a.get("start_time") or "")[:10]
            ).date() <= hist_day
        ]
        expected_snapshot = build_training_load(hist_acts, hist_day)
        expected_acwr = expected_snapshot.acwr

        actual = entry["training_load"]
        if expected_acwr is None:
            assert actual is None, (
                f"[{day_str}] expected training_load=None, got {actual}"
            )
        else:
            assert actual is not None, (
                f"[{day_str}] expected training_load={round(expected_acwr, 3)}, got None"
            )
            assert abs(actual - round(expected_acwr, 3)) < 1e-9, (
                f"[{day_str}] training_load mismatch: {actual} != {round(expected_acwr, 3)}"
            )


# ---------------------------------------------------------------------------
# Test 2 — no future leakage
# ---------------------------------------------------------------------------

def test_history_training_load_no_future_leakage():
    """Activities after day J must not influence history[J].training_load."""
    # Only one activity: today (the very last history day).
    # All earlier history days must have training_load=None.
    acts = [{
        "user_id": "tester",
        "type": "running",
        "start_time": _TODAY.isoformat() + "T07:00:00",
        "duration": 3600,
        "distance": 12000,
    }]
    # Provide 15 days of metrics (recent user, sparse history)
    db = _make_db(_metrics(n=15, ref=_TODAY), acts)

    payload = asyncio.run(compute_run_index(db, "tester", reference_date=_TODAY))
    assert payload is not None
    history = payload["history"]

    for entry in history:
        day_str = entry["date"]
        hist_day = date.fromisoformat(day_str[:10])
        if hist_day < _TODAY:
            # No activities before today — no chronic load — ACWR must be None
            assert entry["training_load"] is None, (
                f"[{day_str}] expected None (no past activities), got {entry['training_load']}"
            )


# ---------------------------------------------------------------------------
# Test 3 — distance-only activities → training_load is None
# ---------------------------------------------------------------------------

def test_history_training_load_distance_only_is_none():
    """Activities with zero/absent duration must yield training_load=None (no estimation)."""
    acts = _distance_only_activities(n=20, ref=_TODAY)
    db = _make_db(_metrics(n=20, ref=_TODAY), acts)

    payload = asyncio.run(compute_run_index(db, "tester", reference_date=_TODAY))
    assert payload is not None

    for entry in payload["history"]:
        assert entry["training_load"] is None, (
            f"[{entry['date']}] distance-only → expected None, got {entry['training_load']}"
        )


# ---------------------------------------------------------------------------
# Test 4 — insufficient history → V2 exact behaviour
# ---------------------------------------------------------------------------

def test_history_training_load_insufficient_history():
    """When < 28 days of running data exist, acwr follows V2 rules (may be None)."""
    # Only 5 days of activities; well under 28-day chronic window
    acts = [
        {
            "user_id": "tester",
            "type": "running",
            "start_time": (_TODAY - timedelta(days=i)).isoformat() + "T07:00:00",
            "duration": 1800,
            "distance": 6000,
        }
        for i in range(5)
    ]
    db = _make_db(_metrics(n=10, ref=_TODAY), acts)

    payload = asyncio.run(compute_run_index(db, "tester", reference_date=_TODAY))
    assert payload is not None

    for entry in payload["history"]:
        day_str = entry["date"]
        hist_day = date.fromisoformat(day_str[:10])
        hist_acts = [
            a for a in acts
            if datetime.fromisoformat((a["start_time"])[:10]).date() <= hist_day
        ]
        expected = build_training_load(hist_acts, hist_day)
        if expected.acwr is None:
            assert entry["training_load"] is None
        else:
            assert entry["training_load"] is not None
            assert abs(entry["training_load"] - round(expected.acwr, 3)) < 1e-9


# ---------------------------------------------------------------------------
# Test 5 — metrics.training_load non-regressed
# ---------------------------------------------------------------------------

def test_current_metrics_training_load_non_regressed():
    """metrics.training_load must still equal build_training_load(all_acts, today).acwr."""
    acts = _duration_activities(n=20, ref=_TODAY)
    db = _make_db(_metrics(n=20, ref=_TODAY), acts)

    payload = asyncio.run(compute_run_index(db, "tester", reference_date=_TODAY))
    assert payload is not None

    expected_snapshot = build_training_load(acts, _TODAY)
    expected = round(expected_snapshot.acwr, 3) if expected_snapshot.acwr is not None else None
    assert payload["metrics"]["training_load"] == expected


# ---------------------------------------------------------------------------
# Test 6 — history entry shape preserved
# ---------------------------------------------------------------------------

def test_history_entry_shape_includes_training_load_key():
    """Every history entry must contain the training_load key (may be None)."""
    acts = _duration_activities(n=15, ref=_TODAY)
    db = _make_db(_metrics(n=15, ref=_TODAY), acts)

    payload = asyncio.run(compute_run_index(db, "tester", reference_date=_TODAY))
    assert payload is not None

    for entry in payload["history"]:
        assert "training_load" in entry, f"history entry missing 'training_load': {entry}"
        assert "day" in entry
        assert "date" in entry
        assert "hrv" in entry
        assert "fatigue_ratio" not in entry, "fatigue_ratio must be removed from history[] (#126)"
        assert "run_readiness" in entry
