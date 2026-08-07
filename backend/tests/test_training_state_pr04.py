"""PR04 — Tests for TrainingState (two-axis: continuity + load).

All tests are deterministic: they use a fixed reference_date of 2026-08-06.

Run from the backend directory:
    python -m pytest tests/test_training_state_pr04.py -q
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

from training_v2.training_history import build_training_history
from training_v2.training_load import build_training_load
from training_v2.runner_profile import build_runner_profile
from training_v2.training_state import (
    TrainingState,
    build_training_state,
    NO_RUN_DEEP_REPRISE_DAYS,
    PARTIAL_REPRISE_VOLUME_RATIO,
    REPRISE_EXIT_STABLE_WEEKS,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REF = date(2026, 8, 6)


def _act(days_ago: int, distance_m: float = 10_000.0, duration_s: float = 3_600.0) -> dict:
    run_date = REF - timedelta(days=days_ago)
    return {
        "activity_type": "running",
        "start_time": run_date.isoformat() + "T08:00:00.0",
        "distance": distance_m,
        "duration": duration_s,
    }


def _build(activities, profile=None, reference_date=REF):
    history = build_training_history(activities, reference_date)
    load_snap = build_training_load(activities, reference_date)
    runner = build_runner_profile(
        training_history=history,
        training_load=load_snap,
        user_profile=profile or {},
        reference_date=reference_date,
    )
    return build_training_state(
        training_history=history,
        training_load=load_snap,
        runner_profile=runner,
        reference_date=reference_date,
    )


# ---------------------------------------------------------------------------
# 1. No history
# ---------------------------------------------------------------------------


def test_no_history_empty():
    state = _build([])
    assert state.continuity_state == "no_history"
    assert state.days_since_last_run is None
    assert state.continuity_confidence == "none"
    assert "NO_RUNNING_HISTORY" in state.reason_codes


# ---------------------------------------------------------------------------
# 2. Declared profile but no history
# ---------------------------------------------------------------------------


def test_declared_profile_no_history():
    """Declared weekly_km must NOT fabricate continuity."""
    state = _build([], profile={"weekly_km": 30})
    assert state.continuity_state == "no_history"
    assert state.days_since_last_run is None
    assert state.continuity_confidence == "none"


# ---------------------------------------------------------------------------
# 3. Deep reprise
# ---------------------------------------------------------------------------


def test_deep_reprise():
    """Prior history + no run in last 28 days → deep_reprise."""
    # Last run was 30 days ago; plenty of history before that.
    acts = [_act(days_ago=d) for d in range(30, 150, 7)]
    state = _build(acts)
    assert state.continuity_state == "deep_reprise"
    assert "NO_RUN_LAST_28D" in state.reason_codes


def test_deep_reprise_boundary():
    """Exactly 28 days since last run → deep_reprise."""
    acts = [_act(days_ago=d) for d in range(28, 150, 7)]
    state = _build(acts)
    assert state.continuity_state == "deep_reprise"


def test_no_history_not_deep_reprise():
    """no_history must NOT be classified as deep_reprise."""
    state = _build([])
    assert state.continuity_state == "no_history"
    assert state.continuity_state != "deep_reprise"


# ---------------------------------------------------------------------------
# 4. Partial reprise
# ---------------------------------------------------------------------------


def test_partial_reprise():
    """Observable baseline + recent volume far below baseline → partial_reprise."""
    # Historical baseline: ~50 km/week for 6 months (acts every ~5 days, 10 km each)
    baseline_acts = [_act(days_ago=d) for d in range(8, 180, 5)]
    # Recent week: only 5 km (far below 50% of ~14 km weekly baseline from 30d window)
    recent_acts = [_act(days_ago=2, distance_m=5_000.0)]
    acts = baseline_acts + recent_acts
    state = _build(acts)
    assert state.continuity_state == "partial_reprise"
    assert "RECENT_VOLUME_FAR_BELOW_BASELINE" in state.reason_codes


# ---------------------------------------------------------------------------
# 5. Reprise exit — boundary between partial_reprise / reprise_exit / normal
# ---------------------------------------------------------------------------


def test_reprise_exit_short_history():
    """Short history (< REPRISE_EXIT_STABLE_WEEKS * 7 days) with recent run → reprise_exit."""
    days_needed = REPRISE_EXIT_STABLE_WEEKS * 7 - 1
    # A few runs spread across the short history window
    acts = [_act(days_ago=d) for d in range(1, days_needed, 7)]
    state = _build(acts)
    assert state.continuity_state == "reprise_exit"


def test_partial_reprise_to_reprise_exit_boundary():
    """Volume just above 50% of baseline but history sparse → reprise_exit.

    Scenario:
      - Historical runs every 7 days from day 8 to day 57 (8 runs, 10 km each).
      - 30d window: runs at days 8, 15, 22, 29 + recent day 2 = 5 runs, 46 km.
      - Baseline (weekly equivalent): 46 * 7 / 30 ≈ 10.73 km.
      - Recent weekly (w7): 6 km.
      - 6 km ≥ 50% of 10.73 km (= 5.37) → NOT partial_reprise.
      - available_history_days = 57, w30.activity_count = 5 < 12 → reprise_exit.
    """
    baseline_acts = [_act(days_ago=d, distance_m=10_000.0) for d in range(8, 60, 7)]
    recent_acts = [_act(days_ago=2, distance_m=6_000.0)]
    acts = baseline_acts + recent_acts
    state = _build(acts)
    assert state.continuity_state == "reprise_exit"


# ---------------------------------------------------------------------------
# 5b. Declared baseline must NOT be used as observable baseline (Fix 1)
# ---------------------------------------------------------------------------


def test_declared_baseline_no_history_no_partial_reprise():
    """Declared weekly_km with no observed history must NOT trigger partial_reprise.

    This test validates the 'declared weekly km ≠ observed baseline' invariant.

    Scenario (from problem statement):
      - No observed running history at all.
      - User declares weekly_km = 40 in their profile.
      - Result: no_history (never partial_reprise) because there is no
        observed baseline to compare against.
    """
    state = _build([], profile={"weekly_km": 40})
    assert state.continuity_state == "no_history"
    assert state.continuity_state != "partial_reprise"


def test_declared_baseline_not_used_as_observable_baseline():
    """typical_weekly_km_is_observed must be False when only declared data exists.

    Validates that RunnerProfile correctly exposes provenance, and that the
    observed baseline from the 30d window (1.17 km/week) is used instead of
    the declared value (40 km/week).

    With 1 recent run at 5 km and declared 40 km/week:
      - window_30d contributes: 5 km × 7 / 30 ≈ 1.17 km/week (observed, is_observed=True).
      - Declared 40 km/week is ignored.
      - Recent weekly (5 km) > 50% of observed baseline (0.58 km) → NOT partial_reprise.
    """
    acts = [_act(days_ago=2, distance_m=5_000.0)]
    history = build_training_history(acts, REF)
    load_snap = build_training_load(acts, REF)
    runner = build_runner_profile(
        training_history=history,
        training_load=load_snap,
        user_profile={"weekly_km": 40},
        reference_date=REF,
    )
    # Provenance flag must be True: the 30d window has a run → observed.
    assert runner.typical_weekly_km_is_observed is True
    # Observed baseline is ~1.17 km/week, NOT 40 km/week.
    assert runner.typical_weekly_km is not None
    assert runner.typical_weekly_km < 40
    state = build_training_state(
        training_history=history,
        training_load=load_snap,
        runner_profile=runner,
        reference_date=REF,
    )
    assert state.continuity_state != "partial_reprise"


def test_no_history_typical_weekly_km_is_observed_false():
    """With no observed history, typical_weekly_km_is_observed must be False."""
    history = build_training_history([], REF)
    load_snap = build_training_load([], REF)
    runner = build_runner_profile(
        training_history=history,
        training_load=load_snap,
        user_profile={"weekly_km": 40},
        reference_date=REF,
    )
    assert runner.typical_weekly_km_is_observed is False


# ---------------------------------------------------------------------------
# 5c. Deterministic partial_reprise → reprise_exit → normal sequence (Fix 3)
#
# Scenarios use a controlled baseline (10 fixed runs in days 8-29,
# each 10 km) so the arithmetic is exact and reproducible.
#
# Baseline (before adding recent run):
#   10 runs × 10 km = 100 km in 30d
#   typical_weekly_km = 100 × 7 / 30 ≈ 23.33 km/week (but recalculated
#   after adding the recent run — see per-test comments).
#
# available_history_days = 29 ≥ REPRISE_EXIT_STABLE_WEEKS × 7 = 28
#   → second reprise_exit branch applies (sparse-w30 criterion).
# ---------------------------------------------------------------------------

_BASELINE_DAYS = [8, 10, 12, 14, 16, 18, 20, 22, 24, 29]  # 10 runs, oldest day 29


def test_partial_reprise_volume_below_50pct():
    """Volume strictly below 50% of observed baseline → partial_reprise.

    Scenario: 10 baseline runs (days 8-29, 10 km each) + 1 recent run
    at day 2 (12 km).
      - w30 distance = 100 + 12 = 112 km → baseline = 112 × 7/30 ≈ 26.13 km/week.
      - recent_weekly = 12 km.
      - 12 < 0.5 × 26.13 = 13.07 → partial_reprise.
    """
    acts = [_act(days_ago=d) for d in _BASELINE_DAYS] + [
        _act(days_ago=2, distance_m=12_000.0)
    ]
    state = _build(acts)
    assert state.continuity_state == "partial_reprise"
    assert "RECENT_VOLUME_FAR_BELOW_BASELINE" in state.reason_codes


def test_reprise_exit_volume_above_50pct_sparse_w30():
    """Volume above 50% of baseline but w30 sparse (< 12 runs) → reprise_exit.

    Scenario: 10 baseline runs (days 8-29, 10 km each) + 1 recent run
    at day 2 (15 km).
      - w30 distance = 100 + 15 = 115 km → baseline = 115 × 7/30 ≈ 26.83 km/week.
      - recent_weekly = 15 km.
      - 15 ≥ 0.5 × 26.83 = 13.42 → NOT partial_reprise.
      - w30.activity_count = 11 < 12 → reprise_exit.
    """
    acts = [_act(days_ago=d) for d in _BASELINE_DAYS] + [
        _act(days_ago=2, distance_m=15_000.0)
    ]
    state = _build(acts)
    assert state.continuity_state == "reprise_exit"
    assert "RECENT_VOLUME_RECOVERING" in state.reason_codes


def test_normal_volume_above_50pct_dense_w30():
    """Volume above 50% of baseline AND w30 dense (≥ 12 runs) → normal.

    Scenario: 11 baseline runs (days 8-29 + day 26, 10 km each) + 1 recent
    run at day 2 (15 km). w30.activity_count = 12.
      - w30 distance = 110 + 15 = 125 km → baseline = 125 × 7/30 ≈ 29.17 km/week.
      - recent_weekly = 15 km < 29.17 (volume below baseline).
      - w30.activity_count = 12, NOT < 12 → reprise_exit branch skipped → normal.
    """
    acts = [_act(days_ago=d) for d in _BASELINE_DAYS + [26]] + [
        _act(days_ago=2, distance_m=15_000.0)
    ]
    state = _build(acts)
    assert state.continuity_state == "normal"
    assert "CONTINUITY_STABLE" in state.reason_codes




def test_normal():
    """Long history, consistent recent volume → normal."""
    # ~60 days of 3 runs/week, each 10 km
    acts = [_act(days_ago=d) for d in range(0, 120, 3)]
    state = _build(acts)
    assert state.continuity_state == "normal"
    assert "CONTINUITY_STABLE" in state.reason_codes


# ---------------------------------------------------------------------------
# 7. Normal continuity + elevated load (architectural test)
# ---------------------------------------------------------------------------


def test_normal_continuity_elevated_load():
    """A runner can simultaneously be normal continuity and elevated load."""
    # Long consistent history
    base_acts = [_act(days_ago=d) for d in range(7, 120, 3)]
    # Very high acute load this week: 5 long runs
    acute_acts = [_act(days_ago=d, distance_m=20_000.0, duration_s=7_200.0) for d in range(0, 7)]
    acts = base_acts + acute_acts

    history = build_training_history(acts, REF)
    load_snap = build_training_load(acts, REF)
    runner = build_runner_profile(
        training_history=history,
        training_load=load_snap,
        user_profile={},
        reference_date=REF,
    )
    state = build_training_state(
        training_history=history,
        training_load=load_snap,
        runner_profile=runner,
        reference_date=REF,
    )
    assert state.continuity_state == "normal"
    assert state.load_state in ("elevated", "high")


# ---------------------------------------------------------------------------
# 8. Partial reprise + elevated load (independence test)
# ---------------------------------------------------------------------------


def test_partial_reprise_and_elevated_load():
    """Two axes are independent: partial_reprise + elevated load simultaneously."""
    # Baseline history well established
    baseline_acts = [_act(days_ago=d, distance_m=10_000.0) for d in range(8, 180, 5)]
    # Very intense single run this week (high acute load, very low volume km)
    recent_acts = [_act(days_ago=1, distance_m=2_000.0, duration_s=10_800.0)]
    acts = baseline_acts + recent_acts

    history = build_training_history(acts, REF)
    load_snap = build_training_load(acts, REF)
    runner = build_runner_profile(
        training_history=history,
        training_load=load_snap,
        user_profile={},
        reference_date=REF,
    )
    state = build_training_state(
        training_history=history,
        training_load=load_snap,
        runner_profile=runner,
        reference_date=REF,
    )
    # Must be partial reprise: only 2 km this week vs ~14 km/week baseline
    assert state.continuity_state == "partial_reprise"
    # Load state mirrors TrainingLoadSnapshot.status exactly
    assert state.load_state == load_snap.status


# ---------------------------------------------------------------------------
# 9. ACWR absent
# ---------------------------------------------------------------------------


def test_acwr_absent():
    """When no load history is available, acwr must be None and load_state unavailable."""
    state = _build([])
    assert state.acwr is None
    assert state.load_state == "unavailable"
    assert "LOAD_UNAVAILABLE" in state.reason_codes


def test_acwr_no_fallback():
    """Absent ACWR must never be replaced by 1.0 or 'balanced'."""
    state = _build([])
    assert state.acwr != 1.0
    assert state.load_state != "balanced"
    assert state.load_state != "normal"


# ---------------------------------------------------------------------------
# 10. Continuity confidence — boundary tests
# ---------------------------------------------------------------------------


def test_continuity_confidence_0_days():
    state = _build([])
    assert state.continuity_confidence == "none"


def test_continuity_confidence_1_day():
    acts = [_act(days_ago=1)]
    state = _build(acts)
    assert state.continuity_confidence == "low"


def test_continuity_confidence_29_days():
    acts = [_act(days_ago=0), _act(days_ago=29)]
    state = _build(acts)
    # available_history_days = 29 → "low"
    assert state.continuity_confidence == "low"


def test_continuity_confidence_30_days():
    acts = [_act(days_ago=0), _act(days_ago=30)]
    state = _build(acts)
    # available_history_days = 30 → "medium"
    assert state.continuity_confidence == "medium"


def test_continuity_confidence_89_days():
    acts = [_act(days_ago=0), _act(days_ago=89)]
    state = _build(acts)
    # available_history_days = 89 → "medium"
    assert state.continuity_confidence == "medium"


def test_continuity_confidence_90_days():
    acts = [_act(days_ago=0), _act(days_ago=90)]
    state = _build(acts)
    # available_history_days = 90 → "high"
    assert state.continuity_confidence == "high"


# ---------------------------------------------------------------------------
# 11. Overall confidence = minimum of both
# ---------------------------------------------------------------------------


def test_overall_confidence_minimum():
    """overall_confidence must be the lower of continuity and load confidence."""
    # Very short history → continuity_confidence = low or none
    # Load will also be low/none with few activities
    state = _build([_act(days_ago=2)])
    order = ["none", "low", "medium", "high"]
    cont_idx = order.index(state.continuity_confidence)
    load_idx = order.index(state.load_confidence)
    overall_idx = order.index(state.overall_confidence)
    assert overall_idx == min(cont_idx, load_idx)


def test_overall_confidence_high_vs_none():
    """If one confidence is none, overall must be none regardless of the other."""
    # No history → continuity none; load also none
    state = _build([])
    assert state.overall_confidence == "none"


def test_overall_confidence_minimum_long_history():
    """With long history, verify minimum rule holds for high continuity."""
    acts = [_act(days_ago=d) for d in range(0, 120, 3)]
    state = _build(acts)
    order = ["none", "low", "medium", "high"]
    cont_idx = order.index(state.continuity_confidence)
    load_idx = order.index(state.load_confidence)
    overall_idx = order.index(state.overall_confidence)
    assert overall_idx == min(cont_idx, load_idx)


# ---------------------------------------------------------------------------
# 12. Reason codes
# ---------------------------------------------------------------------------


def test_reason_codes_no_history():
    state = _build([])
    assert state.reason_codes == ["NO_RUNNING_HISTORY", "LOAD_UNAVAILABLE"]
    for code in state.reason_codes:
        # Must be uppercase snake_case, no spaces, no natural language
        assert code == code.upper()
        assert " " not in code


def test_reason_codes_normal():
    acts = [_act(days_ago=d) for d in range(0, 120, 3)]
    state = _build(acts)
    assert "CONTINUITY_STABLE" in state.reason_codes
    for code in state.reason_codes:
        assert code == code.upper()
        assert " " not in code


def test_reason_codes_deep_reprise():
    acts = [_act(days_ago=d) for d in range(30, 150, 7)]
    state = _build(acts)
    assert "NO_RUN_LAST_28D" in state.reason_codes


def test_reason_codes_partial_reprise():
    baseline_acts = [_act(days_ago=d) for d in range(8, 180, 5)]
    recent_acts = [_act(days_ago=2, distance_m=5_000.0)]
    state = _build(baseline_acts + recent_acts)
    assert "RECENT_VOLUME_FAR_BELOW_BASELINE" in state.reason_codes


# ---------------------------------------------------------------------------
# 13. Immutability
# ---------------------------------------------------------------------------


def test_immutability():
    state = _build([])
    with pytest.raises(Exception):
        state.continuity_state = "hacked"  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 14. Determinism
# ---------------------------------------------------------------------------


def test_determinism():
    acts = [_act(days_ago=d) for d in range(0, 60, 5)]
    s1 = _build(acts)
    s2 = _build(acts)
    assert s1 == s2


def test_determinism_different_dates():
    acts = [_act(days_ago=d) for d in range(0, 60, 5)]
    # Two different reference dates must independently produce consistent results
    ref1 = date(2026, 8, 6)
    ref2 = date(2026, 8, 7)

    def _build_at(ref):
        history = build_training_history(acts, ref)
        load_snap = build_training_load(acts, ref)
        runner = build_runner_profile(
            training_history=history,
            training_load=load_snap,
            user_profile={},
            reference_date=ref,
        )
        return build_training_state(
            training_history=history,
            training_load=load_snap,
            runner_profile=runner,
            reference_date=ref,
        )

    # Each call to the same ref is deterministic
    s1a = _build_at(ref1)
    s1b = _build_at(ref1)
    assert s1a == s1b

    s2a = _build_at(ref2)
    s2b = _build_at(ref2)
    assert s2a == s2b

    # Different reference dates produce different reference_date fields
    assert s1a.reference_date != s2a.reference_date


# ---------------------------------------------------------------------------
# 15. No legacy dependency imports
# ---------------------------------------------------------------------------


def test_no_legacy_imports():
    """training_state.py must not import from legacy modules."""
    import ast

    source_file = Path(
        __file__
    ).resolve().parents[1] / "training_v2" / "training_state.py"
    tree = ast.parse(source_file.read_text())

    forbidden = {
        "training_engine",
        "training_load_engine",
        "llm_coach",
        "coach_service",
    }
    imported_modules: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imported_modules.append(alias.name)
        elif isinstance(node, ast.ImportFrom):
            if node.module:
                imported_modules.append(node.module)

    for mod in imported_modules:
        for forbidden_name in forbidden:
            assert forbidden_name not in mod, (
                f"training_state.py must not import from '{forbidden_name}' (found: {mod})"
            )


# ---------------------------------------------------------------------------
# 16. load_state mirrors TrainingLoadSnapshot.status exactly
# ---------------------------------------------------------------------------


def test_load_state_mirrors_snapshot():
    acts = [_act(days_ago=d) for d in range(0, 60, 5)]
    history = build_training_history(acts, REF)
    load_snap = build_training_load(acts, REF)
    runner = build_runner_profile(
        training_history=history,
        training_load=load_snap,
        user_profile={},
        reference_date=REF,
    )
    state = build_training_state(
        training_history=history,
        training_load=load_snap,
        runner_profile=runner,
        reference_date=REF,
    )
    assert state.load_state == load_snap.status
    assert state.acwr == load_snap.acwr
    assert state.load_confidence == load_snap.confidence


# ---------------------------------------------------------------------------
# PR94 — Correction finale : reprise_exit pour historiques courts
# ---------------------------------------------------------------------------


def test_pr94_cas1_short_history_last_run_10d():
    """Cas 1 — available_history_days=20, days_since_last_run=10 → reprise_exit.

    Scenario: single run 10 days ago.
      - has_any_running_history = True
      - available_history_days = 0 (only one run, same day as first → 0 days span)
        but days_since_last_run = 10 < 28 (not deep_reprise)
      - available_history_days < REPRISE_EXIT_STABLE_WEEKS * 7 = 28
      - No partial_reprise trigger (no observable baseline > 0)
      → reprise_exit (regardless of w7.activity_count == 0)
    """
    # A few runs spread over 20 days, last one 10 days ago
    acts = [_act(days_ago=d) for d in [10, 14, 18, 20]]
    state = _build(acts)
    assert state.continuity_state == "reprise_exit"
    assert "RECENT_VOLUME_RECOVERING" in state.reason_codes


def test_pr94_cas2_history_27d_last_run_27d():
    """Cas 2 — available_history_days=27, days_since_last_run=27 → reprise_exit.

    Scenario: single run exactly 27 days ago.
      - has_any_running_history = True
      - days_since_last_run = 27 < 28 → NOT deep_reprise
      - available_history_days = 0 (single-run span) < 28
      - w7.activity_count = 0 (last run was 27 days ago)
      → reprise_exit
    """
    acts = [_act(days_ago=27)]
    state = _build(acts)
    assert state.continuity_state == "reprise_exit"
    assert "RECENT_VOLUME_RECOVERING" in state.reason_codes


def test_pr94_cas3_frontier_deep_reprise():
    """Cas 3 — available_history_days > 28, days_since_last_run = 28 → deep_reprise."""
    # Plenty of history, but last run was exactly 28 days ago
    acts = [_act(days_ago=d) for d in range(28, 150, 7)]
    state = _build(acts)
    assert state.continuity_state == "deep_reprise"
    assert "NO_RUN_LAST_28D" in state.reason_codes


def test_pr94_cas4_partial_reprise_prioritaire():
    """Cas 4 — historique court + baseline valide + volume récent < 50% → partial_reprise.

    partial_reprise must remain prioritaire over reprise_exit.

    Scenario:
      - Short history: runs at days 8, 10, 12, 14, 16 (5 runs, 10 km each, span 16 days)
        → available_history_days = 16 < 28
      - Recent run at day 3: 2 km
      - w30 distance = 52 km → baseline ≈ 52 × 7/30 ≈ 12.13 km/week
      - recent_weekly = 2 km < 50% × 12.13 = 6.07 → partial_reprise
    """
    baseline_acts = [_act(days_ago=d) for d in [8, 10, 12, 14, 16]]
    recent_acts = [_act(days_ago=3, distance_m=2_000.0)]
    acts = baseline_acts + recent_acts
    state = _build(acts)
    assert state.continuity_state == "partial_reprise"
    assert "RECENT_VOLUME_FAR_BELOW_BASELINE" in state.reason_codes


def test_pr94_cas5_normal_deep_history_stable():
    """Cas 5 — historique suffisamment profond et continuité stable → normal."""
    # ~120 days of 3 runs/week, each 10 km
    acts = [_act(days_ago=d) for d in range(0, 120, 3)]
    state = _build(acts)
    assert state.continuity_state == "normal"
    assert "CONTINUITY_STABLE" in state.reason_codes
