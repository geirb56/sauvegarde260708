"""PR75 — Resume guard unit tests.

Rule: if km_7 < 0.5 * current_weekly_km → progression capped at +5 % (not +10 %).
      if km_7 >= 0.5 * current_weekly_km or km_7 is None → normal +10 %.

Pure unit tests: no HTTP, no DB.
"""

from __future__ import annotations

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import pytest

from training_engine import (
    PHASE_VOLUME_MULTIPLIERS,
    VOLUME_GOAL_CONFIG,
    compute_resume_guard,
    compute_target_km,
)


# ---------------------------------------------------------------------------
# compute_resume_guard unit tests
# ---------------------------------------------------------------------------


class TestComputeResumeGuard:
    """Direct tests of the guard helper."""

    def test_normal_case_km_7_above_threshold(self):
        """Test 1 — km_7=25 >= 20 (50% of 40) → no resumption, +10%."""
        guard = compute_resume_guard(40.0, 25.0)
        assert guard["resume_detected"] is False
        assert guard["max_progression"] == 0.10
        assert guard["resume_threshold_km"] == pytest.approx(20.0)

    def test_resume_detected_km_7_below_threshold(self):
        """Test 2 — km_7=15 < 20 (50% of 40) → resumption detected, +5%."""
        guard = compute_resume_guard(40.0, 15.0)
        assert guard["resume_detected"] is True
        assert guard["max_progression"] == 0.05
        assert guard["resume_threshold_km"] == pytest.approx(20.0)

    def test_exactly_at_threshold_not_resumption(self):
        """Test 3 — km_7=20 == 50% of 40 → NOT a resumption (condition is strict <)."""
        guard = compute_resume_guard(40.0, 20.0)
        assert guard["resume_detected"] is False
        assert guard["max_progression"] == 0.10

    def test_just_below_threshold(self):
        """Test 4 — km_7=19.99 < 20 → resumption detected."""
        guard = compute_resume_guard(40.0, 19.99)
        assert guard["resume_detected"] is True
        assert guard["max_progression"] == 0.05

    def test_km_7_zero_triggers_resumption(self):
        """Test 5 — km_7=0 is known and equals 0 → 0 < threshold → resumption."""
        guard = compute_resume_guard(40.0, 0.0)
        assert guard["resume_detected"] is True
        assert guard["max_progression"] == 0.05

    def test_km_7_none_no_guard(self):
        """Test 6 — km_7=None → guard not triggered, normal progression."""
        guard = compute_resume_guard(40.0, None)
        assert guard["resume_detected"] is False
        assert guard["max_progression"] == 0.10
        assert guard["resume_threshold_km"] is None

    def test_km_7_absent_behaves_like_none(self):
        """Test 7 — calling without km_7 (None default) → normal progression."""
        guard = compute_resume_guard(40.0, None)
        assert guard["resume_detected"] is False
        assert guard["max_progression"] == 0.10

    def test_default_weekly_km_with_small_km_7(self):
        """Test 8 — current_weekly_km=20, km_7=5 → threshold=10 → resumption."""
        guard = compute_resume_guard(20.0, 5.0)
        assert guard["resume_detected"] is True
        assert guard["resume_threshold_km"] == pytest.approx(10.0)
        assert guard["max_progression"] == 0.05


# ---------------------------------------------------------------------------
# compute_target_km — resume guard integration tests
# ---------------------------------------------------------------------------


class TestComputeTargetKmResumeGuard:
    """Integration tests: compute_target_km with km_7 argument."""

    def test_example_from_spec_resume_detected(self):
        """Spec example: current=40, km_7=15 → target = round(40*1.05) = 42 in build."""
        target = compute_target_km(40, "SEMI", "build", km_7=15.0)
        expected = round(min(VOLUME_GOAL_CONFIG["SEMI"]["max"], 40 * 1.05) * PHASE_VOLUME_MULTIPLIERS["build"])
        assert target == expected
        assert target == 42

    def test_example_from_spec_normal(self):
        """Spec example: current=40, km_7=25 → target = round(40*1.10) = 44 in build."""
        target = compute_target_km(40, "SEMI", "build", km_7=25.0)
        expected = round(min(VOLUME_GOAL_CONFIG["SEMI"]["max"], 40 * 1.10) * PHASE_VOLUME_MULTIPLIERS["build"])
        assert target == expected
        assert target == 44

    def test_config_max_cap_respected_during_resumption(self):
        """Test 9 — resume guard must never bypass config["max"]."""
        goal = "SEMI"
        max_km = VOLUME_GOAL_CONFIG[goal]["max"]  # 80
        # Very high current_weekly_km to stress config["max"]
        current = 200.0
        target = compute_target_km(current, goal, "build", km_7=5.0)
        assert target <= max_km, (
            f"config['max']={max_km} must not be exceeded. Got {target}."
        )

    def test_phase_multiplier_applied_correctly_with_resume(self):
        """Test 10 — resumption uses 1.05 BEFORE the phase multiplier, not after."""
        # With resumption: base = 40 * 1.05 = 42; taper multiplier = 0.5 → round(42*0.5) = 21
        target = compute_target_km(40, "SEMI", "taper", km_7=15.0)
        expected = round(min(VOLUME_GOAL_CONFIG["SEMI"]["max"], 40 * 1.05) * PHASE_VOLUME_MULTIPLIERS["taper"])
        assert target == expected

    def test_no_km_7_preserves_pr2_behaviour(self):
        """Non-regression PR2: without km_7, compute_target_km is unchanged."""
        target_no_km7 = compute_target_km(40, "SEMI", "build")
        target_km7_none = compute_target_km(40, "SEMI", "build", km_7=None)
        expected = round(min(VOLUME_GOAL_CONFIG["SEMI"]["max"], 40 * 1.10) * PHASE_VOLUME_MULTIPLIERS["build"])
        assert target_no_km7 == expected
        assert target_km7_none == expected

    def test_threshold_boundary_exact_equality_no_resumption(self):
        """Test 3 via compute_target_km: km_7 == 50% → normal +10%."""
        target_exact = compute_target_km(40, "SEMI", "build", km_7=20.0)
        target_normal = compute_target_km(40, "SEMI", "build", km_7=None)
        assert target_exact == target_normal

    def test_threshold_boundary_just_below_resumption(self):
        """Test 4 via compute_target_km: km_7=19.99 < 20 → +5% cap."""
        target_below = compute_target_km(40, "SEMI", "build", km_7=19.99)
        target_resume = compute_target_km(40, "SEMI", "build", km_7=15.0)
        # Both should be in resumption territory (capped at +5%)
        target_normal = compute_target_km(40, "SEMI", "build", km_7=None)
        assert target_below < target_normal
        assert target_below == target_resume

    def test_km_7_zero_triggers_resumption_in_target(self):
        """Test 5 via compute_target_km: km_7=0 known → resumption."""
        target_zero = compute_target_km(40, "SEMI", "build", km_7=0.0)
        target_normal = compute_target_km(40, "SEMI", "build", km_7=None)
        assert target_zero < target_normal

    def test_current_20_km_7_5_resumption(self):
        """Test 8 via compute_target_km: current=20, km_7=5 → resumption."""
        target = compute_target_km(20, "10K", "build", km_7=5.0)
        expected = round(min(VOLUME_GOAL_CONFIG["10K"]["max"], 20 * 1.05) * PHASE_VOLUME_MULTIPLIERS["build"])
        assert target == expected

    def test_existing_pr2_taper_non_regression(self):
        """Existing PR2 test: compute_target_km(20, 'SEMI', 'taper') must still == 11."""
        assert compute_target_km(20, "SEMI", "taper") == 11

    def test_existing_pr2_all_goals_progression_cap(self):
        """Existing PR2 regression: without km_7, progression must not exceed +10%."""
        for goal in ("5K", "10K", "SEMI", "MARATHON", "ULTRA"):
            for current in (5, 10, 15, 20, 25, 30, 45, 60):
                target = compute_target_km(current, goal, "build")
                cap = round(min(VOLUME_GOAL_CONFIG[goal]["max"], current * 1.10))
                assert target <= cap, (
                    f"PR2 non-regression failed for goal={goal} current={current}: "
                    f"got {target}, cap {cap}."
                )

    def test_resume_guard_never_exceeds_plus_5_percent(self):
        """When resumption is detected, target must not exceed +5% of current (before phase multiplier)."""
        for goal in ("5K", "10K", "SEMI", "MARATHON", "ULTRA"):
            current = 40.0
            # km_7 = 0 → always triggers resumption
            target = compute_target_km(current, goal, "build", km_7=0.0)
            cap_resume = round(min(VOLUME_GOAL_CONFIG[goal]["max"], current * 1.05) * PHASE_VOLUME_MULTIPLIERS["build"])
            assert target <= cap_resume, (
                f"Resumption cap exceeded for goal={goal}: got {target}, cap {cap_resume}."
            )
