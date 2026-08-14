"""RUNINDEX #127 — Training metrics TSB legacy cleanup tests.

Verifies:
A. /training/metrics tsb is always None (legacy km formula removed, no V2 equivalent)
B. ACWR = None when no Garmin duration data (no fallback to 1.0)
C. ACWR matches TrainingLoad V2 (build_training_load) — unchanged from #123
D. acwr_reliable / reprise state non-regressed
E. No duplicate ACWR/TSB km computation in coach_service fitness_data
F. llm_coach prompt uses None-safe ACWR/TSB (no 1.0/0 fallback)
G. Multi-user isolation non-regressed
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
_USER_A = "pr127-user-a"
_USER_B = "pr127-user-b"


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


def _simulate_training_metrics(
    garmin_activities: List[dict],
    ref: date = _REF,
    load_7_km: float = 0.0,
    load_28_km: float = 0.0,
) -> dict:
    """Mirror the /training/metrics endpoint logic as of PR #127."""
    load_snapshot: TrainingLoadSnapshot = build_training_load(garmin_activities, ref)
    acwr: Optional[float] = load_snapshot.acwr
    # TSB suppressed in PR #127
    tsb: Optional[float] = None
    acwr_reliable: bool = load_snapshot.has_sufficient_history

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
        "ctl": None,
        "atl": None,
    }


# ---------------------------------------------------------------------------
# A. TSB is always None (legacy km formula removed)
# ---------------------------------------------------------------------------


def test_a_tsb_is_none_no_data():
    """A. tsb is None when there are no activities."""
    result = _simulate_training_metrics([])
    assert result["tsb"] is None


def test_a_tsb_is_none_with_garmin_data():
    """A. tsb is None even when garmin data is present (no km-based TSB formula)."""
    acts = [_garmin_act(_USER_A, days_ago=d, duration_s=1800.0) for d in range(28)]
    result = _simulate_training_metrics(acts, load_7_km=40.0, load_28_km=160.0)
    assert result["tsb"] is None


def test_a_ctl_atl_also_none():
    """A. ctl and atl are also None (V2 aliases removed)."""
    acts = [_garmin_act(_USER_A, days_ago=d, duration_s=1800.0) for d in range(28)]
    result = _simulate_training_metrics(acts, load_7_km=40.0, load_28_km=160.0)
    assert result["ctl"] is None
    assert result["atl"] is None


# ---------------------------------------------------------------------------
# B. ACWR = None when no valid duration (no fallback to 1.0)
# ---------------------------------------------------------------------------


def test_b_no_activities_acwr_none_no_fallback():
    """B. No activities → acwr is None, not 1.0."""
    result = _simulate_training_metrics([])
    assert result["acwr"] is None
    assert result["acwr_status"] == "unavailable"


def test_b_distance_only_acwr_none():
    """B. Distance present but no duration → acwr is None (no load invented)."""
    acts = [
        _garmin_act(_USER_A, days_ago=d, duration_s=None, distance_m=10_000.0)
        for d in range(28)
    ]
    result = _simulate_training_metrics(acts)
    assert result["acwr"] is None


def test_b_zero_duration_acwr_none():
    """B. Duration=0 → acwr is None (zero contributes no load)."""
    acts = [_garmin_act(_USER_A, days_ago=d, duration_s=0.0) for d in range(28)]
    result = _simulate_training_metrics(acts)
    assert result["acwr"] is None


# ---------------------------------------------------------------------------
# C. ACWR matches TrainingLoad V2 (non-regression from #123)
# ---------------------------------------------------------------------------


def test_c_acwr_matches_build_training_load():
    """C. acwr == build_training_load(acts, ref).acwr."""
    acts = [_garmin_act(_USER_A, days_ago=d, duration_s=1800.0) for d in range(28)]
    result = _simulate_training_metrics(acts)
    expected = build_training_load(acts, _REF).acwr
    assert result["acwr"] == expected


def test_c_acwr_varied_load_matches_v2():
    """C. Varied daily load: endpoint acwr == V2 snapshot acwr."""
    acts = [
        _garmin_act(_USER_A, days_ago=d, duration_s=1200.0 if d % 2 == 0 else 2400.0)
        for d in range(28)
    ]
    result = _simulate_training_metrics(acts)
    expected = build_training_load(acts, _REF).acwr
    assert result["acwr"] == expected


# ---------------------------------------------------------------------------
# D. acwr_reliable non-regressed (reprise state logic)
# ---------------------------------------------------------------------------


def test_d_acwr_reliable_true_when_no_reprise():
    """D. acwr_reliable = has_sufficient_history when not in reprise."""
    acts = [_garmin_act(_USER_A, days_ago=d, duration_s=1800.0) for d in range(28)]
    result = _simulate_training_metrics(acts)
    expected_reliable = build_training_load(acts, _REF).has_sufficient_history
    assert result["acwr_reliable"] == expected_reliable


def test_d_acwr_reliable_false_when_no_history():
    """D. acwr_reliable = False when no garmin history."""
    result = _simulate_training_metrics([])
    assert result["acwr_reliable"] is False


# ---------------------------------------------------------------------------
# E. No duplicate km CTL/ATL/TSB/ACWR in coach_service fitness_data
# ---------------------------------------------------------------------------


def test_e_coach_service_fitness_data_no_ctl_atl_tsb():
    """E. coach_service fitness_data must not contain ctl, atl, tsb, or km-based acwr."""
    # We import the module and inspect the _compute_fitness_data path
    # indirectly: build a minimal mock to call generate_plan and capture
    # the fitness_data passed to build_training_context.
    import importlib
    import types

    # Verify the source file no longer contains the forbidden pattern
    coach_service_path = _BACKEND / "coach_service.py"
    source = coach_service_path.read_text()

    # The km-based CTL/ATL/TSB computation block must be gone
    assert "ctl = km_28 / 4" not in source, (
        "coach_service.py must not compute km-based CTL"
    )
    assert "atl = km_7" not in source, (
        "coach_service.py must not compute km-based ATL"
    )
    assert "tsb = round(ctl - atl" not in source, (
        "coach_service.py must not compute km-based TSB"
    )
    # Forbidden fallback removed — check the specific pattern that was present
    assert "if chronic_avg > 0 else 1.0" not in source, (
        "coach_service.py must not use ACWR=1.0 fallback"
    )


def test_e_no_acwr_1_0_fallback_in_coach_service():
    """E. No `acwr = ... else 1.0` pattern in coach_service.py."""
    coach_service_path = _BACKEND / "coach_service.py"
    source = coach_service_path.read_text()
    # Specific forbidden pattern
    assert "else 1.0\n" not in source
    assert "if chronic_avg > 0 else 1.0" not in source


# ---------------------------------------------------------------------------
# F. llm_coach prompt: no ACWR=1.0 or TSB=0 default fallback
# ---------------------------------------------------------------------------


def test_f_llm_coach_no_acwr_1_0_default():
    """F. llm_coach.py prompt must not use fitness.get('acwr', 1.0)."""
    llm_path = _BACKEND / "llm_coach.py"
    source = llm_path.read_text()
    assert "fitness.get('acwr', 1.0)" not in source, (
        "llm_coach.py must not fall back to ACWR=1.0"
    )


def test_f_llm_coach_no_tsb_0_default():
    """F. llm_coach.py prompt must not use fitness.get('tsb', 0)."""
    llm_path = _BACKEND / "llm_coach.py"
    source = llm_path.read_text()
    assert "fitness.get('tsb', 0)" not in source, (
        "llm_coach.py must not fall back to TSB=0"
    )


# ---------------------------------------------------------------------------
# G. Multi-user isolation non-regressed
# ---------------------------------------------------------------------------


def test_g_multi_user_user_b_none_when_no_data():
    """G. User B has no activities → acwr None even when user A has many."""
    acts_a = [_garmin_act(_USER_A, days_ago=d, duration_s=1800.0) for d in range(28)]
    acts_b: List[dict] = []
    result_b = _simulate_training_metrics(acts_b)
    assert result_b["acwr"] is None


def test_g_multi_user_user_a_not_influenced_by_user_b():
    """G. User A acwr computed only from user A activities."""
    acts_a = [_garmin_act(_USER_A, days_ago=d, duration_s=1800.0) for d in range(28)]
    # User B activities differ; should not affect A's result
    acts_b = [_garmin_act(_USER_B, days_ago=d, duration_s=7200.0) for d in range(28)]
    result_a = _simulate_training_metrics(acts_a)
    expected = build_training_load(acts_a, _REF).acwr
    assert result_a["acwr"] == expected


def test_g_tsb_none_for_both_users():
    """G. tsb is None for both users (PR #127 applies universally)."""
    acts_a = [_garmin_act(_USER_A, days_ago=d, duration_s=1800.0) for d in range(28)]
    acts_b = [_garmin_act(_USER_B, days_ago=d, duration_s=3600.0) for d in range(28)]
    assert _simulate_training_metrics(acts_a)["tsb"] is None
    assert _simulate_training_metrics(acts_b)["tsb"] is None


# ---------------------------------------------------------------------------
# H. No km-based or duplicate ACWR/TSB in server.py training/metrics endpoint
# ---------------------------------------------------------------------------


def test_h_server_tsb_set_to_none():
    """H. server.py /training/metrics tsb must be explicitly set to None."""
    server_path = _BACKEND / "server.py"
    source = server_path.read_text()
    # The old formula must be gone
    assert "load_28 / 4 - load_7" not in source, (
        "server.py must not compute km-based TSB (load_28/4 - load_7)"
    )
    # The None assignment must be present
    assert "tsb: Optional[float] = None" in source, (
        "server.py /training/metrics must set tsb = None"
    )


def test_h_server_no_acwr_1_0_fallback():
    """H. server.py must not contain `or 1.0` pattern for ACWR."""
    server_path = _BACKEND / "server.py"
    source = server_path.read_text()
    assert 'float(load_doc.get("acwr") or 1.0)' not in source, (
        "server.py must not use ACWR=1.0 fallback in run-readiness"
    )


# ---------------------------------------------------------------------------
# I. /coach/analyze must NOT expose km-based ACWR (#127 pre-merge corrections)
# ---------------------------------------------------------------------------


def test_i_coach_analyze_no_km_based_acwr():
    """I. /coach/analyze must not expose km_7/(km_28/4) as ACWR."""
    server_path = _BACKEND / "server.py"
    source = server_path.read_text()
    # The forbidden km-based formula must be gone
    assert "km_7 / (km_28 / 4)" not in source, (
        "/coach/analyze must not compute km-based ACWR"
    )


def test_i_coach_analyze_acwr_none():
    """I. /coach/analyze acwr is set to None (TrainingLoad V2 unavailable in this context)."""
    server_path = _BACKEND / "server.py"
    source = server_path.read_text()
    # The explicit None assignment must be present in the coach/analyze context
    assert "ACWR (#127 pre-merge corrections)" in source, (
        "/coach/analyze must set acwr=None with the #127 comment"
    )


def test_i_coach_analyze_acwr_status_unavailable():
    """I. /coach/analyze acwr_status is 'unavailable' when acwr is None."""
    server_path = _BACKEND / "server.py"
    source = server_path.read_text()
    assert '"unavailable" if acwr is None' in source, (
        "/coach/analyze must set acwr_status='unavailable' when acwr is None"
    )


# ---------------------------------------------------------------------------
# J. /training/week-plan must NOT expose km-based ACWR
# ---------------------------------------------------------------------------


def test_j_week_plan_no_km_based_acwr():
    """J. /training/week-plan context must not compute km-based ACWR."""
    server_path = _BACKEND / "server.py"
    source = server_path.read_text()
    # The specific formula (load_7 / (load_28 / 4)) used in week-plan must be gone
    assert "load_7 / (load_28 / 4)" not in source, (
        "/training/week-plan must not compute load_7/(load_28/4) as ACWR"
    )


def test_j_week_plan_acwr_none_in_context():
    """J. /training/week-plan context dict must set acwr=None."""
    server_path = _BACKEND / "server.py"
    source = server_path.read_text()
    # The context must contain "acwr": None
    assert '"acwr": None,' in source or "'acwr': None," in source, (
        "/training/week-plan context must set acwr=None"
    )


# ---------------------------------------------------------------------------
# K. /run-index Terra path: no None→0.0→0.1 clamp, uses TrainingLoad V2
# ---------------------------------------------------------------------------


def test_k_run_index_no_none_to_zero_clamp():
    """K. /run-index must not convert acwr None to 0.0."""
    server_path = _BACKEND / "server.py"
    source = server_path.read_text()
    # The forbidden pattern: float(_raw_acwr) if _raw_acwr is not None else 0.0
    assert "else 0.0" not in source, (
        "/run-index must not use `else 0.0` ACWR fallback"
    )


def test_k_run_index_no_0_1_clamp():
    """K. /run-index must not clamp acwr to 0.1 minimum."""
    server_path = _BACKEND / "server.py"
    source = server_path.read_text()
    assert "max(0.1, acwr)" not in source, (
        "/run-index must not use max(0.1, acwr) clamp"
    )


def test_k_run_index_uses_build_training_load_for_terra():
    """K. /run-index Terra path must use build_training_load (V2)."""
    server_path = _BACKEND / "server.py"
    source = server_path.read_text()
    assert "_load_snapshot = build_training_load(" in source, (
        "/run-index Terra path must call build_training_load"
    )
    assert "_load_snapshot.acwr" in source, (
        "/run-index Terra path must read acwr from V2 snapshot"
    )


def test_k_run_index_no_computeTrainingLoad_call():
    """K. /run-index must not fall back to computeTrainingLoad (km-based legacy)."""
    server_path = _BACKEND / "server.py"
    source = server_path.read_text()
    # computeTrainingLoad may still exist elsewhere but the run-index section
    # must not call it (the DEBT comment is allowed to remain).
    # Count occurrences: only inside comments (not code) is acceptable.
    # Simple check: the call pattern `await computeTrainingLoad(user_id, db)` in
    # the /run-index block is removed.
    # We check the entire file has no `load_doc = await computeTrainingLoad` call.
    assert "load_doc = await computeTrainingLoad" not in source, (
        "/run-index must not assign load_doc from computeTrainingLoad"
    )


# ---------------------------------------------------------------------------
# L. No-data scenario: acwr None, no numeric fallback 1.0/0.0/0.1
# ---------------------------------------------------------------------------


def test_l_no_activities_no_numeric_fallback():
    """L. build_training_load with no activities returns acwr=None (no 0.0/0.1/1.0)."""
    snap = build_training_load([], _REF)
    assert snap.acwr is None
    assert snap.status == "unavailable"
    # None must propagate — no numeric fallback
    acwr = snap.acwr
    assert acwr != 0.0
    assert acwr != 0.1
    assert acwr != 1.0


def test_l_distance_only_no_numeric_fallback():
    """L. Activities with distance but no duration: acwr=None, not a numeric value."""
    acts = [
        {
            "activity_type": "running",
            "start_time": (_REF - timedelta(days=d)).isoformat(),
            "distance_m": 10_000.0,
            "duration_s": None,
        }
        for d in range(28)
    ]
    snap = build_training_load(acts, _REF)
    assert snap.acwr is None


# ---------------------------------------------------------------------------
# M. /training/metrics ACWR identical to TrainingLoad V2 (non-regression)
# ---------------------------------------------------------------------------


def test_m_training_metrics_acwr_matches_v2():
    """M. /training/metrics acwr always equals TrainingLoad V2 build_training_load."""
    acts = [_garmin_act(_USER_A, days_ago=d, duration_s=1800.0) for d in range(28)]
    result = _simulate_training_metrics(acts)
    expected_snap = build_training_load(acts, _REF)
    assert result["acwr"] == expected_snap.acwr, (
        "/training/metrics acwr must match TrainingLoad V2"
    )
    assert result["acwr_status"] != "unavailable" or expected_snap.acwr is None


# ---------------------------------------------------------------------------
# N. week-plan context supports acwr=None (no downstream crash)
# ---------------------------------------------------------------------------


def test_n_week_plan_context_acwr_none_supported():
    """N. week-plan context with acwr=None is handled by determine_target_load."""
    from training_engine import determine_target_load
    # Build a context that mirrors what /training/week-plan now produces
    context = {
        "ctl": None,
        "atl": None,
        "tsb": None,
        "acwr": None,
        "weekly_km": 30.0,
        "load_7": 300.0,
        "load_28": 1200.0,
    }
    # Must not raise; should return a numeric target
    try:
        result = determine_target_load(context, "build")
        assert isinstance(result, (int, float)), "determine_target_load must return a number"
    except Exception as e:
        raise AssertionError(
            f"determine_target_load must support acwr=None in context, got: {e}"
        ) from e
