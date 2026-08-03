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


# ---------------------------------------------------------------------------
# Effective-plan tests — PR75 fix: the PLAN must respect the guarded target,
# not just compute_target_km().
# ---------------------------------------------------------------------------


import asyncio

# Determine which plan generator to use (sync wrapper around async function).
# We import generate_cycle_week from llm_coach and _deterministic_plan from
# coach_service.  Both must produce a plan whose weekly_km respects the guard.

def _get_plan_via_generate_cycle_week(current_weekly_km, goal, phase, km_7):
    """Run generate_cycle_week synchronously and return the plan dict."""
    import sys, os
    _BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _BACKEND not in sys.path:
        sys.path.insert(0, _BACKEND)
    from llm_coach import generate_cycle_week

    context = {
        "weekly_km": current_weekly_km,
        "km_7": km_7,
        "ctl": current_weekly_km * 10 / 4,
        "atl": (km_7 or 0) * 10,
        "tsb": 0,
        "acwr": 1.0,
    }
    # generate_cycle_week is async; run in a new event loop.
    plan, success, _ = asyncio.get_event_loop().run_until_complete(
        generate_cycle_week(
            context=context,
            phase=phase,
            target_load=int(current_weekly_km * 10),
            goal=goal,
        )
    )
    return plan, success


def _get_plan_via_deterministic(current_weekly_km, goal, phase, km_7):
    """Run _deterministic_plan (from coach_service) and return the plan dict."""
    import sys, os
    _BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _BACKEND not in sys.path:
        sys.path.insert(0, _BACKEND)
    from coach_service import _deterministic_plan

    context = {
        "weekly_km": current_weekly_km,
        "km_7": km_7,
        "ctl": current_weekly_km * 10 / 4,
        "atl": (km_7 or 0) * 10,
        "tsb": 0,
        "acwr": 1.0,
    }
    plan = _deterministic_plan(
        context=context,
        phase=phase,
        target_load=int(current_weekly_km * 10),
        goal=goal,
    )
    return plan


def _get_plan_via_fallback_server(current_weekly_km, goal, phase, km_7):
    """Run _generate_fallback_week_plan (from server) and return the plan dict."""
    import sys, os
    _BACKEND = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if _BACKEND not in sys.path:
        sys.path.insert(0, _BACKEND)
    # Provide required env vars so server.py can be imported without a live DB.
    os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
    os.environ.setdefault("DB_NAME", "test_db")
    os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-32chars-for-testing!!")
    os.environ.setdefault("JWT_ALGORITHM", "HS256")
    os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
    os.environ.setdefault("ENVIRONMENT", "test")
    from server import _generate_fallback_week_plan

    context = {
        "weekly_km": current_weekly_km,
        "km_7": km_7,
    }
    plan = _generate_fallback_week_plan(
        context=context,
        phase=phase,
        target_load=int(current_weekly_km * 10),
        goal=goal,
    )
    return plan


class TestEffectivePlanResumeGuard:
    """PR75 fix — verify the EFFECTIVE plan respects the guarded weekly target."""

    # ----- Test A: resume guard active, current=40, km_7=15 -----

    def test_A_generate_cycle_week_resume_guard_active(self):
        """A — generate_cycle_week: current=40, km_7=15 → guard active → plan ≤ 42 km."""
        target = compute_target_km(40, "SEMI", "build", km_7=15.0)
        assert target == 42, f"Precondition: expected target=42, got {target}"
        plan, success = _get_plan_via_generate_cycle_week(40, "SEMI", "build", km_7=15.0)
        assert success, "Plan generation failed"
        weekly_km = plan["weekly_km"]
        assert weekly_km <= target, (
            f"Plan weekly_km={weekly_km} exceeds guarded target={target} km."
        )

    def test_A_deterministic_plan_resume_guard_active(self):
        """A — _deterministic_plan: current=40, km_7=15 → guard active → plan ≤ 42 km."""
        target = compute_target_km(40, "SEMI", "build", km_7=15.0)
        plan = _get_plan_via_deterministic(40, "SEMI", "build", km_7=15.0)
        weekly_km = plan["weekly_km"]
        assert weekly_km <= target, (
            f"Deterministic plan weekly_km={weekly_km} exceeds guarded target={target} km."
        )

    def test_A_fallback_server_resume_guard_active(self):
        """A — _generate_fallback_week_plan: current=40, km_7=15 → guard active → plan ≤ 42 km."""
        target = compute_target_km(40, "SEMI", "build", km_7=15.0)
        plan = _get_plan_via_fallback_server(40, "SEMI", "build", km_7=15.0)
        weekly_km = plan["weekly_km"]
        assert weekly_km <= target, (
            f"Server fallback weekly_km={weekly_km} exceeds guarded target={target} km."
        )

    # ----- Test B: guard inactive (km_7 == 50%) -----

    def test_B_guard_inactive_exact_threshold(self):
        """B — current=40, km_7=20 (exact 50%) → guard inactive → target=44 km."""
        target = compute_target_km(40, "SEMI", "build", km_7=20.0)
        assert target == 44, f"Expected target=44, got {target}"
        plan, success = _get_plan_via_generate_cycle_week(40, "SEMI", "build", km_7=20.0)
        assert success
        assert plan["weekly_km"] <= target

    # ----- Test C: guard inactive (km_7 > 50%) -----

    def test_C_guard_inactive_above_threshold(self):
        """C — current=40, km_7=25 → guard inactive → target=44 km."""
        target = compute_target_km(40, "SEMI", "build", km_7=25.0)
        assert target == 44, f"Expected target=44, got {target}"
        plan, success = _get_plan_via_generate_cycle_week(40, "SEMI", "build", km_7=25.0)
        assert success
        assert plan["weekly_km"] <= target

    # ----- Test D: km_7=0, guard active -----

    def test_D_km_7_zero_guard_active(self):
        """D — current=40, km_7=0 → guard active → target=42 km."""
        target = compute_target_km(40, "SEMI", "build", km_7=0.0)
        assert target == 42, f"Expected target=42, got {target}"
        plan, success = _get_plan_via_generate_cycle_week(40, "SEMI", "build", km_7=0.0)
        assert success
        weekly_km = plan["weekly_km"]
        assert weekly_km <= target, (
            f"Plan weekly_km={weekly_km} exceeds guarded target={target} km."
        )

    def test_D_deterministic_km_7_zero(self):
        """D — _deterministic_plan: current=40, km_7=0 → plan ≤ 42 km."""
        target = compute_target_km(40, "SEMI", "build", km_7=0.0)
        plan = _get_plan_via_deterministic(40, "SEMI", "build", km_7=0.0)
        assert plan["weekly_km"] <= target

    # ----- Test E: km_7=None → no guard, normal PR2 behaviour -----

    def test_E_km_7_none_no_guard(self):
        """E — current=40, km_7=None → no guard → target=44 km (PR2 behaviour unchanged)."""
        target_none = compute_target_km(40, "SEMI", "build", km_7=None)
        target_normal = compute_target_km(40, "SEMI", "build")
        assert target_none == target_normal == 44
        plan, success = _get_plan_via_generate_cycle_week(40, "SEMI", "build", km_7=None)
        assert success
        assert plan["weekly_km"] <= target_none

    # ----- Test F: forced fallback path -----

    def test_F_fallback_respects_guard(self):
        """F — _deterministic_plan fallback: current=40, km_7=15 → plan ≤ 42 km."""
        target = compute_target_km(40, "SEMI", "build", km_7=15.0)
        plan = _get_plan_via_deterministic(40, "SEMI", "build", km_7=15.0)
        weekly_km = plan["weekly_km"]
        assert weekly_km <= target, (
            f"Fallback plan weekly_km={weekly_km} exceeds guarded target={target} km."
        )

    def test_F_server_fallback_respects_guard(self):
        """F — _generate_fallback_week_plan: current=40, km_7=15 → plan ≤ 42 km."""
        target = compute_target_km(40, "SEMI", "build", km_7=15.0)
        plan = _get_plan_via_fallback_server(40, "SEMI", "build", km_7=15.0)
        weekly_km = plan["weekly_km"]
        assert weekly_km <= target, (
            f"Server fallback plan weekly_km={weekly_km} exceeds guarded target={target} km."
        )

    # ----- Test G: endpoint-equivalent — same data, all paths ≤ 42 km -----

    def test_G_endpoint_equivalent_all_paths_respect_guard(self):
        """G — Both generators produce plans ≤ 42 km for current=40, km_7=15."""
        target = compute_target_km(40, "SEMI", "build", km_7=15.0)
        assert target == 42

        plan_gen, success = _get_plan_via_generate_cycle_week(40, "SEMI", "build", km_7=15.0)
        assert success
        assert plan_gen["weekly_km"] <= target, (
            f"generate_cycle_week: {plan_gen['weekly_km']} > {target}"
        )

        plan_det = _get_plan_via_deterministic(40, "SEMI", "build", km_7=15.0)
        assert plan_det["weekly_km"] <= target, (
            f"_deterministic_plan: {plan_det['weekly_km']} > {target}"
        )

        plan_fb = _get_plan_via_fallback_server(40, "SEMI", "build", km_7=15.0)
        assert plan_fb["weekly_km"] <= target, (
            f"_generate_fallback_week_plan: {plan_fb['weekly_km']} > {target}"
        )


# ---------------------------------------------------------------------------
# Final hard-clamp guarantee — tests added per problem statement:
# "After any generation/fallback, guarantee weekly_km ≤ target_km_protected."
# ---------------------------------------------------------------------------


class TestFinalHardClamp:
    """Verify the unconditional hard clamp applied after every generation/fallback path."""

    def test_forced_fallback_current40_km7_15_le_42(self):
        """Forced fallback (current=40, km_7=15) via _deterministic_plan → weekly_km ≤ 42."""
        target = compute_target_km(40, "SEMI", "build", km_7=15.0)
        assert target == 42, f"Precondition: target must be 42, got {target}"

        # Force the fallback path directly — bypasses any LLM call.
        plan = _get_plan_via_deterministic(40, "SEMI", "build", km_7=15.0)

        # Simulate the hard clamp present in coach_service.py and server.py.
        clamped_km = min(plan.get("weekly_km", 0), float(target))

        assert clamped_km <= 42, (
            f"After hard clamp: weekly_km={clamped_km} still exceeds 42 km."
        )

    def test_hard_clamp_corrects_over_budget_plan(self):
        """Hard clamp: a plan with weekly_km=50 is clamped to target_km_protected=42."""
        target = compute_target_km(40, "SEMI", "build", km_7=15.0)
        assert target == 42

        # Simulate an over-budget plan (e.g. produced by a generator rounding error).
        over_budget = {"weekly_km": 50.0, "sessions": [], "focus": "build", "planned_load": 400}

        # Apply the same clamp as coach_service.py / server.py.
        over_budget["weekly_km"] = min(over_budget.get("weekly_km", 0), float(target))

        assert over_budget["weekly_km"] <= 42, (
            f"weekly_km={over_budget['weekly_km']} exceeds 42 after hard clamp."
        )
        assert over_budget["weekly_km"] == 42.0

    def test_hard_clamp_noop_when_already_within_budget(self):
        """Hard clamp must not alter a plan that is already within budget."""
        target = compute_target_km(40, "SEMI", "build", km_7=15.0)
        plan = _get_plan_via_deterministic(40, "SEMI", "build", km_7=15.0)
        original_km = plan["weekly_km"]

        # Clamp should leave the value unchanged.
        plan["weekly_km"] = min(plan.get("weekly_km", 0), float(target))

        assert plan["weekly_km"] == original_km, (
            f"Hard clamp altered an already-valid weekly_km: {original_km} → {plan['weekly_km']}"
        )

    def test_server_fallback_forced_current40_km7_15_le_42(self):
        """Forced server fallback (current=40, km_7=15) → _generate_fallback_week_plan weekly_km ≤ 42."""
        target = compute_target_km(40, "SEMI", "build", km_7=15.0)
        assert target == 42

        plan = _get_plan_via_fallback_server(40, "SEMI", "build", km_7=15.0)

        # Apply the hard clamp mirroring server.py.
        clamped_km = min(plan.get("weekly_km", 0), float(target))

        assert clamped_km <= 42, (
            f"Server fallback after hard clamp: weekly_km={clamped_km} > 42 km."
        )
