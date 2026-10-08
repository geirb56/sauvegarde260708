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
    """An observed inactive week + low returning volume → partial_reprise."""
    baseline_acts = [_act(days_ago=d) for d in range(14, 180, 5)]
    # Days 7–13 are inactive; the recent 5 km are below half the observed baseline.
    recent_acts = [_act(days_ago=2, distance_m=5_000.0)]
    acts = baseline_acts + recent_acts
    state = _build(acts)
    assert state.continuity_state == "partial_reprise"
    assert "RECENT_VOLUME_FAR_BELOW_BASELINE" in state.reason_codes


# ---------------------------------------------------------------------------
# 5. Reprise exit — boundary between partial_reprise / reprise_exit / normal
# ---------------------------------------------------------------------------


def test_short_regular_history_is_normal():
    """Short regular history is normal, with low confidence rather than reprise."""
    days_needed = REPRISE_EXIT_STABLE_WEEKS * 7 - 1
    # A few runs spread across the short history window
    acts = [_act(days_ago=d) for d in range(1, days_needed, 7)]
    state = _build(acts)
    assert state.continuity_state == "normal"
    assert state.continuity_confidence == "low"
    assert "CONTINUITY_STABLE" in state.reason_codes


def test_partial_reprise_to_reprise_exit_boundary():
    """An inactive week with returning volume above half baseline → reprise_exit."""
    baseline_acts = [_act(days_ago=d, distance_m=10_000.0) for d in range(14, 60, 7)]
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
# Ten fixed runs establish an observed baseline and an inactive week at days 7–13.
# ---------------------------------------------------------------------------

_BASELINE_DAYS = [14, 15, 16, 17, 18, 19, 20, 21, 24, 29]


def test_partial_reprise_volume_below_50pct():
    """After an inactive week, volume below 50% of baseline → partial_reprise.

    Scenario: 10 baseline runs (days 14-29, 10 km each) + 1 recent run
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
    """After an inactive week, volume above 50% of baseline → reprise_exit.

    Scenario: 10 baseline runs (days 14-29, 10 km each) + 1 recent run
    at day 2 (15 km).
      - w30 distance = 100 + 15 = 115 km → baseline = 115 × 7/30 ≈ 26.83 km/week.
      - recent_weekly = 15 km.
      - 15 ≥ 0.5 × 26.83 = 13.42 → NOT partial_reprise.
      - An observed inactive week remains → reprise_exit.
    """
    acts = [_act(days_ago=d) for d in _BASELINE_DAYS] + [
        _act(days_ago=2, distance_m=15_000.0)
    ]
    state = _build(acts)
    assert state.continuity_state == "reprise_exit"
    assert "RECENT_VOLUME_RECOVERING" in state.reason_codes


def test_normal_volume_above_50pct_dense_w30():
    """Four active rolling weeks recover normal continuity, independent of density."""
    acts = [_act(days_ago=d) for d in _BASELINE_DAYS + [8]] + [
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
    baseline_acts = [_act(days_ago=d, distance_m=10_000.0) for d in range(14, 180, 5)]
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
    # An observed inactive week and low returning distance establish partial reprise.
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
    baseline_acts = [_act(days_ago=d) for d in range(14, 180, 5)]
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
# PR94 scenarios updated to distinguish short history from observed inactivity.
# ---------------------------------------------------------------------------


def test_pr94_cas1_short_history_last_run_10d():
    """Ten days without running is partial reprise even with short history."""
    # A few runs spread over 20 days, last one 10 days ago
    acts = [_act(days_ago=d) for d in [10, 14, 18, 20]]
    state = _build(acts)
    assert state.continuity_state == "partial_reprise"
    assert "NO_RUN_LAST_8D" in state.reason_codes


def test_pr94_cas2_history_27d_last_run_27d():
    """A single run 27 days ago is partial reprise, not deep reprise or normal."""
    acts = [_act(days_ago=27)]
    state = _build(acts)
    assert state.continuity_state == "partial_reprise"
    assert "NO_RUN_LAST_8D" in state.reason_codes


def test_pr94_cas3_frontier_deep_reprise():
    """Cas 3 — available_history_days > 28, days_since_last_run = 28 → deep_reprise."""
    # Plenty of history, but last run was exactly 28 days ago
    acts = [_act(days_ago=d) for d in range(28, 150, 7)]
    state = _build(acts)
    assert state.continuity_state == "deep_reprise"
    assert "NO_RUN_LAST_28D" in state.reason_codes


def test_pr94_cas4_partial_reprise_prioritaire():
    """Short history with a fully observed inactive week still permits partial reprise."""
    baseline_acts = [_act(days_ago=d) for d in [14, 15, 16]]
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


@pytest.mark.parametrize("runs_per_week", (2, 3, 5))
def test_regular_frequency_never_implies_reprise(runs_per_week):
    acts = [
        _act(7 * week + offset, distance_m=5_000.0)
        for week in range(16)
        for offset in range(runs_per_week)
    ]
    history = build_training_history(acts, REF)
    assert history.weekly_run_count_buckets_28d == (runs_per_week,) * 4
    state = _build(acts)
    assert state.continuity_state == "normal"
    assert state.continuity_confidence == "high"
    assert "INACTIVE_RUNNING_WEEK" not in state.reason_codes


def test_real_81km_history_four_active_weeks_is_normal():
    acts = [
        _act(day, distance_m=km * 1000)
        for day, km in ((2, 9.1), (5, 9), (9, 10), (12, 11),
                        (16, 10), (19, 11), (23, 10), (26, 11))
    ] + [_act(100)]
    history = build_training_history(acts, REF)
    assert history.window_30d.distance_km == 81.1
    assert history.window_7d.distance_km == 18.1
    assert history.window_30d.activity_count == 8 < 12
    assert history.weekly_run_count_buckets_28d == (2, 2, 2, 2)
    state = _build(acts)
    assert state.continuity_state == "normal"
    assert state.continuity_confidence == "high"
    assert "CONTINUITY_STABLE" in state.reason_codes


def test_taper_volume_below_half_baseline_without_break_is_normal():
    acts = [_act(day) for day in range(7, 120, 3)] + [_act(2, distance_m=1_000)]
    history = build_training_history(acts, REF)
    assert history.window_7d.distance_km < 0.5 * history.window_30d.distance_km * 7 / 30
    assert all(count > 0 for count in history.weekly_run_count_buckets_28d)
    state = _build(acts)
    assert state.continuity_state == "normal"
    assert "RECENT_VOLUME_FAR_BELOW_BASELINE" not in state.reason_codes
    assert "RECENT_VOLUME_RECOVERING" not in state.reason_codes


@pytest.mark.parametrize("days_since", range(8, 28))
@pytest.mark.parametrize("long_history", (False, True))
def test_every_8_to_27_day_gap_is_partial_reprise(days_since, long_history):
    acts = [_act(days_since)]
    if long_history:
        acts += [_act(day) for day in range(35, 140, 7)]
    state = _build(acts)
    assert state.days_since_last_run == days_since
    assert state.continuity_state == "partial_reprise"
    assert "NO_RUN_LAST_8D" in state.reason_codes
    assert "CONTINUITY_STABLE" not in state.reason_codes
    assert "NO_RUN_LAST_28D" not in state.reason_codes


def test_single_run_exactly_28_days_ago_is_deep_reprise():
    state = _build([_act(28)])
    assert state.days_since_last_run == 28
    assert state.continuity_state == "deep_reprise"
    assert "NO_RUN_LAST_28D" in state.reason_codes
    assert "NO_RUN_LAST_8D" not in state.reason_codes


@pytest.mark.parametrize("days_since", (0, 6))
def test_short_history_before_first_run_is_not_an_observed_break(days_since):
    state = _build([_act(days_since)])
    assert state.continuity_state == "normal"
    assert state.continuity_confidence == "low"
    assert "INACTIVE_RUNNING_WEEK" not in state.reason_codes


def test_seven_day_gap_uses_observed_week_not_eight_day_reason():
    state = _build([_act(7)])
    assert state.continuity_state == "reprise_exit"
    assert "INACTIVE_RUNNING_WEEK" in state.reason_codes
    assert "NO_RUN_LAST_8D" not in state.reason_codes


@pytest.mark.parametrize("return_km, expected", ((2, "partial_reprise"), (15, "reprise_exit")))
def test_real_return_requires_inactive_week_then_compares_volume(return_km, expected):
    acts = [_act(day) for day in _BASELINE_DAYS] + [_act(2, distance_m=return_km * 1000)]
    history = build_training_history(acts, REF)
    assert history.weekly_run_count_buckets_28d[1] == 0
    state = _build(acts)
    assert state.continuity_state == expected
    assert "INACTIVE_RUNNING_WEEK" in state.reason_codes
    assert "CONTINUITY_STABLE" not in state.reason_codes
    assert state.load_state == build_training_load(acts, REF).status


@pytest.mark.parametrize("return_km, expected", (
    (11.99, "partial_reprise"), (12.0, "reprise_exit"), (12.01, "reprise_exit"),
))
def test_observed_break_volume_ratio_boundary_is_strict(return_km, expected):
    acts = [_act(day) for day in _BASELINE_DAYS] + [_act(2, distance_m=return_km * 1000)]
    history = build_training_history(acts, REF)
    load = build_training_load(acts, REF)
    runner = build_runner_profile(
        training_history=history, training_load=load, user_profile={}, reference_date=REF,
    ).model_copy(update={"typical_weekly_km": 24.0, "typical_weekly_km_is_observed": True})
    state = build_training_state(
        training_history=history, training_load=load, runner_profile=runner, reference_date=REF,
    )
    assert state.continuity_state == expected
    assert "INACTIVE_RUNNING_WEEK" in state.reason_codes


def test_declared_baseline_never_describes_return_volume_after_observed_break():
    acts = [_act(2, distance_m=1_000), _act(16)]
    history = build_training_history(acts, REF)
    load = build_training_load(acts, REF)
    runner = build_runner_profile(
        training_history=history, training_load=load, user_profile={}, reference_date=REF,
    ).model_copy(update={"typical_weekly_km": 40.0, "typical_weekly_km_is_observed": False})
    state = build_training_state(
        training_history=history, training_load=load, runner_profile=runner, reference_date=REF,
    )
    assert state.continuity_state == "reprise_exit"
    assert "INACTIVE_RUNNING_WEEK" in state.reason_codes
    assert "RECENT_VOLUME_FAR_BELOW_BASELINE" not in state.reason_codes


def test_return_recovers_deterministically_after_four_active_rolling_weeks():
    acts = [_act(day) for day in (14, 16, 18, 21, 24, 29, 100)] + [_act(0, distance_m=2_000)]
    expected_states = ("partial_reprise", "reprise_exit", "reprise_exit", "normal")
    for week, expected in enumerate(expected_states):
        ref = REF + timedelta(days=7 * week)
        if week:
            acts.append({
                "activity_type": "running",
                "start_time": ref.isoformat(),
                "distance": 10_000,
                "duration": 3_600,
            })
        history = build_training_history(acts, ref)
        state = _build(acts, reference_date=ref)
        assert state == _build(acts, reference_date=ref)
        assert state.continuity_state == expected
        if week == 3:
            assert history.weekly_run_count_buckets_28d == (1, 1, 1, 1)
            assert "INACTIVE_RUNNING_WEEK" not in state.reason_codes
            assert "CONTINUITY_STABLE" in state.reason_codes
        else:
            assert "INACTIVE_RUNNING_WEEK" in state.reason_codes


def test_duration_only_active_weeks_do_not_prove_a_break():
    acts = [_act(day, distance_m=None, duration_s=1800) for day in (2, 9, 16, 23, 100)]
    history = build_training_history(acts, REF)
    assert history.weekly_distance_buckets_28d == (0, 0, 0, 0)
    assert history.weekly_run_count_buckets_28d == (1, 1, 1, 1)
    assert _build(acts).continuity_state == "normal"


@pytest.mark.parametrize("return_duration_s", (1800, 7200))
def test_duration_only_return_does_not_fabricate_zero_recent_distance(return_duration_s):
    acts = [_act(day) for day in (14, 16, 23, 100)] + [
        _act(2, distance_m=None, duration_s=return_duration_s),
    ]
    history = build_training_history(acts, REF)
    load = build_training_load(acts, REF)
    runner = build_runner_profile(
        training_history=history, training_load=load, user_profile={}, reference_date=REF,
    )
    assert runner.typical_weekly_km_is_observed is True
    assert runner.typical_weekly_km > 0
    assert history.weekly_run_count_buckets_28d == (1, 0, 2, 1)
    state = build_training_state(
        training_history=history, training_load=load, runner_profile=runner, reference_date=REF,
    )
    # Missing recent distance cannot be compared as zero km or substituted with duration.
    assert state.continuity_state == "reprise_exit"
    assert "INACTIVE_RUNNING_WEEK" in state.reason_codes
    assert "RECENT_VOLUME_RECOVERING" in state.reason_codes
    assert "RECENT_VOLUME_FAR_BELOW_BASELINE" not in state.reason_codes


@pytest.mark.parametrize("known_counts", (False, True))
@pytest.mark.parametrize("inactive_index", (1, 2, 3))
def test_unknown_or_not_fully_observed_week_does_not_prove_rupture(known_counts, inactive_index):
    acts = [_act(2, distance_m=1_000)] + [_act(day) for day in (9, 16, 23, 100)]
    history = build_training_history(acts, REF)
    counts = tuple(0 if index == inactive_index else 1 for index in range(4)) if known_counts else None
    history = history.model_copy(update={
        "weekly_run_count_buckets_28d": counts,
        "available_history_days": (inactive_index + 1) * 7 - 1,
    })
    load = build_training_load(acts, REF)
    runner = build_runner_profile(
        training_history=history, training_load=load, user_profile={}, reference_date=REF,
    )
    assert history.window_7d.distance_km < 0.5 * runner.typical_weekly_km
    state = build_training_state(
        training_history=history, training_load=load, runner_profile=runner, reference_date=REF,
    )
    assert state.continuity_state == "normal"
    assert "INACTIVE_RUNNING_WEEK" not in state.reason_codes
    if counts is not None:
        observed = history.model_copy(update={"available_history_days": (inactive_index + 1) * 7})
        observed_state = build_training_state(
            training_history=observed, training_load=load, runner_profile=runner, reference_date=REF,
        )
        assert observed_state.continuity_state == "partial_reprise"
        assert "INACTIVE_RUNNING_WEEK" in observed_state.reason_codes


@pytest.mark.parametrize("load_status", ("unavailable", "very_low", "low", "balanced", "elevated", "high"))
def test_continuity_change_preserves_every_load_status(load_status):
    acts = [_act(day) for day in (2, 9, 16, 23, 100)]
    history = build_training_history(acts, REF)
    load = build_training_load(acts, REF).model_copy(update={"status": load_status})
    runner = build_runner_profile(
        training_history=history, training_load=load, user_profile={}, reference_date=REF,
    )
    state = build_training_state(
        training_history=history, training_load=load, runner_profile=runner, reference_date=REF,
    )
    assert state.continuity_state == "normal"
    assert state.load_state == load_status
    assert state.load_confidence == load.confidence
    assert state.acwr == load.acwr
    assert f"LOAD_{load_status.upper()}" in state.reason_codes
