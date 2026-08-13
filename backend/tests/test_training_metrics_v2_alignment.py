"""RUNINDEX — /training/metrics consumer alignment tests.

Verifies the migration from legacy TrainingLoad helpers to
TrainingLoadSnapshot V2 (build_training_load) in the /training/metrics
endpoint logic.

Requirements verified:
A. Same activities → same ACWR as /run-index (build_training_load)
B. No valid duration → acwr is None (no ACWR=1.0 fallback)
C. Distance only (no duration) → no load created, acwr is None
D. Multi-user isolation: user A garmin activities never influence user B
E. Readiness non-regression: has_sufficient_history flag drives acwr_reliable
F. tsb is None when no Garmin load data
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

from training_v2.training_load import build_training_load, TrainingLoadSnapshot

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_REF = date(2026, 1, 28)
_USER_A = "user_alpha"
_USER_B = "user_beta"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _garmin_act(
    user_id: str,
    days_ago: int,
    duration_s: Optional[float],
    distance_m: Optional[float] = None,
    ref: date = _REF,
) -> dict:
    """Build a minimal garmin_activities document."""
    act_date = ref - timedelta(days=days_ago)
    doc: dict = {
        "user_id": user_id,
        "activity_type": "running",
        "start_time": act_date.isoformat() + "T08:00:00",
    }
    if duration_s is not None:
        doc["duration"] = duration_s
    if distance_m is not None:
        doc["distance"] = distance_m
    return doc


def _acwr_from_snapshot(activities: List[dict], ref: date = _REF) -> Optional[float]:
    """Return build_training_load(...).acwr for the given activity list."""
    return build_training_load(activities, ref).acwr


# ---------------------------------------------------------------------------
# Simulated endpoint logic (mirrors server.py get_training_metrics)
# Mirror only the ACWR/CTL/ATL/TSB/acwr_reliable parts that were migrated.
# ---------------------------------------------------------------------------


def _simulate_endpoint(
    garmin_activities: List[dict],
    ref: date = _REF,
    load_7_km: float = 0.0,
    load_28_km: float = 0.0,
) -> dict:
    """Simulate the current /training/metrics ACWR/TSB logic (PR #123).

    ACWR comes from TrainingLoadSnapshot V2 (duration-based, single source of truth).
    TSB is kept as a LEGACY km-based formula (distance workouts) until a dedicated
    migration PR replaces it with V2 duration-based units.
    ctl / atl are None (not consumed by the frontend; V2 aliases removed).
    """
    load_snapshot: TrainingLoadSnapshot = build_training_load(garmin_activities, ref)

    acwr: Optional[float] = load_snapshot.acwr
    # TSB — LEGACY km-based (distance workouts, NOT V2 duration metrics)
    tsb: Optional[float] = round(load_28_km / 4 - load_7_km, 1) if load_28_km > 0 else None
    acwr_reliable: bool = load_snapshot.has_sufficient_history

    # ACWR status
    if acwr is None:
        acwr_status = "unavailable"
    elif not acwr_reliable:
        acwr_status = "building"
    elif acwr < 0.8:
        acwr_status = "low"
    elif acwr <= 1.3:
        acwr_status = "optimal"
    elif acwr <= 1.5:
        acwr_status = "warning"
    else:
        acwr_status = "danger"

    return {
        "acwr": acwr,
        "acwr_status": acwr_status,
        "acwr_reliable": acwr_reliable,
        "tsb": tsb,
        # ctl/atl not exposed by V2; set to None until migration PR
        "ctl": None,
        "atl": None,
    }


# ---------------------------------------------------------------------------
# A. Same ACWR as /run-index
# ---------------------------------------------------------------------------


def test_a_acwr_matches_build_training_load_single_activity():
    """A. /training/metrics ACWR == build_training_load(activities, ref).acwr."""
    # 4+ weeks of daily 30-min runs to get sufficient history
    acts = [
        _garmin_act(_USER_A, days_ago=d, duration_s=1800.0)
        for d in range(28)
    ]
    result = _simulate_endpoint(acts)
    expected = _acwr_from_snapshot(acts)
    assert result["acwr"] == expected


def test_a_acwr_matches_build_training_load_varied_load():
    """A. Varied daily loads: endpoint ACWR == snapshot ACWR."""
    acts = []
    for d in range(28):
        # alternating 20-min and 40-min runs
        acts.append(_garmin_act(_USER_A, days_ago=d, duration_s=1200.0 if d % 2 == 0 else 2400.0))
    result = _simulate_endpoint(acts)
    expected = _acwr_from_snapshot(acts)
    assert result["acwr"] == expected


# ---------------------------------------------------------------------------
# B. No valid duration → acwr is None
# ---------------------------------------------------------------------------


def test_b_no_activities_acwr_none():
    """B. No activities → acwr is None, not 1.0."""
    result = _simulate_endpoint([])
    assert result["acwr"] is None
    assert result["acwr_status"] == "unavailable"


def test_b_activities_missing_duration_acwr_none():
    """B. Activities present but all lack duration → acwr is None."""
    acts = [
        {"user_id": _USER_A, "activity_type": "running",
         "start_time": (_REF - timedelta(days=d)).isoformat() + "T08:00:00"}
        for d in range(28)
    ]
    result = _simulate_endpoint(acts)
    assert result["acwr"] is None


def test_b_zero_duration_acwr_none():
    """B. Duration=0 contributes no load → acwr is None."""
    acts = [_garmin_act(_USER_A, days_ago=d, duration_s=0.0) for d in range(28)]
    result = _simulate_endpoint(acts)
    assert result["acwr"] is None


# ---------------------------------------------------------------------------
# C. Distance only (no duration) → no load
# ---------------------------------------------------------------------------


def test_c_distance_only_no_load():
    """C. Activities with distance but no duration → acwr is None (no load invented)."""
    acts = [
        _garmin_act(_USER_A, days_ago=d, duration_s=None, distance_m=10_000.0)
        for d in range(28)
    ]
    result = _simulate_endpoint(acts)
    assert result["acwr"] is None
    assert result["tsb"] is None


def test_c_distance_plus_duration_uses_duration():
    """C. When duration is also present, load is computed from duration, not distance."""
    # 30-min run with a very large distance (should not affect ACWR ratio)
    acts_duration_only = [
        _garmin_act(_USER_A, days_ago=d, duration_s=1800.0, distance_m=None)
        for d in range(28)
    ]
    acts_with_distance = [
        _garmin_act(_USER_A, days_ago=d, duration_s=1800.0, distance_m=50_000.0)
        for d in range(28)
    ]
    snap_a = build_training_load(acts_duration_only, _REF)
    snap_b = build_training_load(acts_with_distance, _REF)
    assert snap_a.acwr == snap_b.acwr


# ---------------------------------------------------------------------------
# D. Multi-user isolation
# ---------------------------------------------------------------------------


def test_d_multi_user_isolation():
    """D. User A activities must not bleed into User B computation."""
    # Only user A has activities
    acts_a = [_garmin_act(_USER_A, days_ago=d, duration_s=1800.0) for d in range(28)]
    acts_b: List[dict] = []

    snap_a = build_training_load(acts_a, _REF)
    snap_b = build_training_load(acts_b, _REF)

    assert snap_a.acwr is not None
    assert snap_b.acwr is None, "User B has no activities; ACWR must be None"


def test_d_multi_user_different_loads():
    """D. Different loads per user produce independent ACWRs."""
    acts_a = [_garmin_act(_USER_A, days_ago=d, duration_s=3600.0) for d in range(28)]
    acts_b = [_garmin_act(_USER_B, days_ago=d, duration_s=600.0) for d in range(28)]

    snap_a = build_training_load(acts_a, _REF)
    snap_b = build_training_load(acts_b, _REF)

    # Same ACWR ratio because load is uniform for both users (acute/chronic ratio = 1)
    assert snap_a.acwr is not None
    assert snap_b.acwr is not None
    # The ratio is identical because load is uniform (equal acute/chronic ratio)
    assert snap_a.acwr == snap_b.acwr


# ---------------------------------------------------------------------------
# E. acwr_reliable uses has_sufficient_history
# ---------------------------------------------------------------------------


def test_e_acwr_reliable_requires_28_days():
    """E. acwr_reliable is False when history < 28 calendar days."""
    # Only 10 days of data — chronic load > 0, so acwr is computable but not reliable
    acts = [_garmin_act(_USER_A, days_ago=d, duration_s=1800.0) for d in range(10)]
    result = _simulate_endpoint(acts)
    assert result["acwr"] is not None, "10 days of 30-min runs must produce a non-None acwr"
    assert result["acwr_reliable"] is False
    assert result["acwr_status"] == "building"


def test_e_acwr_reliable_true_after_28_days():
    """E. acwr_reliable is True when history spans >= 28 calendar days."""
    acts = [_garmin_act(_USER_A, days_ago=d, duration_s=1800.0) for d in range(28)]
    result = _simulate_endpoint(acts)
    assert result["acwr_reliable"] is True
    assert result["acwr_status"] in ("low", "optimal", "warning", "danger")


def test_e_acwr_unavailable_wins_over_reliable_flag():
    """E. When acwr is None, acwr_status is 'unavailable' regardless of reliable flag."""
    # No activities at all
    result = _simulate_endpoint([])
    assert result["acwr"] is None
    assert result["acwr_status"] == "unavailable"
    assert result["acwr_reliable"] is False


# ---------------------------------------------------------------------------
# F. TSB is None when no load
# ---------------------------------------------------------------------------


def test_f_tsb_none_when_no_load():
    """F. tsb is None when no distance-based workouts (load_28_km == 0)."""
    result = _simulate_endpoint([])
    assert result["tsb"] is None
    assert result["ctl"] is None
    assert result["atl"] is None


def test_f_tsb_non_none_with_km_load():
    """F. tsb is a number when km-based workouts data is available."""
    acts = [_garmin_act(_USER_A, days_ago=d, duration_s=1800.0) for d in range(28)]
    # TSB is LEGACY km-based; pass non-zero load_28_km to get a non-None tsb
    result = _simulate_endpoint(acts, load_7_km=35.0, load_28_km=140.0)
    assert result["tsb"] is not None
    assert isinstance(result["tsb"], float)
    # tsb = 140/4 - 35 = 35 - 35 = 0.0
    assert result["tsb"] == 0.0
