"""Regression tests for RunIndex PR76 — resume guard.

The resume guard prevents a plan from assigning an unsafe weekly volume
to an athlete who is *resuming* after a significant drop in training.

Rule:
    If km_7 (last 7 days of running) < 50 % of current_weekly_km (chronic
    average), the allowed progression is capped at +5 % of current_weekly_km
    instead of the normal +10 %.

Scope:
  - apply_resume_guard() unit tests (training_engine)
  - Guard integration in compute_target_km flow
  - Guard NOT triggered when km_7 is normal (≥ 50 % of chronic)
  - Guard NOT triggered when current_weekly_km is 0
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import pytest

from training_engine import apply_resume_guard, compute_target_km


# ---------------------------------------------------------------------------
# apply_resume_guard — unit tests
# ---------------------------------------------------------------------------


class TestApplyResumeGuard:
    """Unit tests for training_engine.apply_resume_guard."""

    def test_guard_triggered_when_km7_below_50pct(self):
        """km_7 = 10 km, chronic = 40 km → 10 < 20 → guard caps at 40 * 1.05 = 42."""
        current_weekly_km = 40.0
        km_7 = 10.0  # 25 % of chronic → below 50 % threshold
        target_km = 50.0  # raw target exceeds cap

        result = apply_resume_guard(target_km, km_7, current_weekly_km)
        cap = current_weekly_km * 1.05
        assert result == cap, (
            f"Guard should cap target at {cap} km. Got {result}."
        )

    def test_guard_not_triggered_when_km7_above_50pct(self):
        """km_7 = 25 km, chronic = 40 km → 25 >= 20 → guard not triggered."""
        current_weekly_km = 40.0
        km_7 = 25.0  # 62.5 % of chronic → above threshold
        target_km = 44.0

        result = apply_resume_guard(target_km, km_7, current_weekly_km)
        assert result == target_km, (
            f"Guard must NOT fire when km_7 >= 50 % of chronic. Got {result}."
        )

    def test_guard_not_triggered_at_exactly_50pct(self):
        """km_7 exactly = 50 % of chronic → no guard (threshold is strict <)."""
        current_weekly_km = 40.0
        km_7 = 20.0  # exactly 50 %
        target_km = 44.0

        result = apply_resume_guard(target_km, km_7, current_weekly_km)
        assert result == target_km, (
            "Guard must NOT fire when km_7 == 50 % of chronic (boundary)."
        )

    def test_guard_not_triggered_when_chronic_is_zero(self):
        """When current_weekly_km == 0 the guard must not crash or fire."""
        result = apply_resume_guard(20.0, 0.0, 0.0)
        assert result == 20.0, "Guard must not fire when chronic volume is zero."

    def test_guard_does_not_increase_target(self):
        """The guard only caps DOWN — it must never raise target_km."""
        current_weekly_km = 30.0
        km_7 = 5.0  # well below threshold
        target_km = 28.0  # already below cap (30 * 1.05 = 31.5)

        result = apply_resume_guard(target_km, km_7, current_weekly_km)
        assert result == target_km, (
            "Guard must not increase target_km even when athlete is resuming."
        )

    def test_guard_cap_formula(self):
        """Cap is exactly current_weekly_km * 1.05 when guard fires."""
        for chronic in [20.0, 35.0, 50.0, 80.0]:
            km_7 = chronic * 0.3  # 30 % — clearly below 50 %
            target_km = chronic * 1.5  # always above the cap
            result = apply_resume_guard(target_km, km_7, chronic)
            expected_cap = chronic * 1.05
            assert abs(result - expected_cap) < 1e-9, (
                f"chronic={chronic}: expected cap={expected_cap}, got {result}."
            )


# ---------------------------------------------------------------------------
# Integration: compute_target_km followed by apply_resume_guard
# ---------------------------------------------------------------------------


class TestResumeGuardIntegration:
    """Integration: apply_resume_guard correctly caps compute_target_km output."""

    def test_resuming_athlete_gets_capped_plan(self):
        """
        Athlete normally runs 50 km/week (chronic).  After a break, km_7 = 15 km.
        Guard must cap the recommended weekly target at ≤ 50 * 1.05 = 52.5 km.
        """
        current_weekly_km = 50.0
        km_7 = 15.0  # 30 % of 50 → guard fires
        goal = "MARATHON"
        phase = "build"

        raw_target = compute_target_km(current_weekly_km, goal, phase)
        protected = apply_resume_guard(raw_target, km_7, current_weekly_km)

        cap = current_weekly_km * 1.05
        assert protected <= cap, (
            f"Resuming athlete: target_km_protected ({protected}) must be ≤ cap ({cap})."
        )

    def test_active_athlete_unaffected(self):
        """Athlete runs consistently: km_7 = 48 km, chronic = 50 km → no cap."""
        current_weekly_km = 50.0
        km_7 = 48.0  # 96 % of 50 → well above 50 % threshold
        goal = "MARATHON"
        phase = "build"

        raw_target = compute_target_km(current_weekly_km, goal, phase)
        protected = apply_resume_guard(raw_target, km_7, current_weekly_km)

        assert protected == raw_target, (
            "Active athlete: guard must not modify target_km."
        )

    def test_resume_guard_applies_across_all_phases(self):
        """For a resuming athlete the guard must fire regardless of phase."""
        current_weekly_km = 40.0
        km_7 = 10.0  # 25 % → guard fires for all phases

        for phase in ["build", "deload", "intensification", "taper", "race"]:
            raw_target = compute_target_km(current_weekly_km, "10K", phase)
            protected = apply_resume_guard(raw_target, km_7, current_weekly_km)
            cap = current_weekly_km * 1.05
            # The cap only applies when the raw target exceeds it
            if raw_target > cap:
                assert protected <= cap, (
                    f"phase={phase}: protected ({protected}) must be ≤ cap ({cap})."
                )
            else:
                # raw_target already ≤ cap → no change expected
                assert protected == raw_target, (
                    f"phase={phase}: guard must not increase target_km."
                )
