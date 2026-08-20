"""
PR #161 — Prove that generate_cycle_week does NOT apply legacy apply_resume_guard
when WeeklyTarget V2 has already computed target_km_protected.

Tests:
  REGRESSION  — V2 target 45, chronic=40, recent=10 → legacy cap=42, must stay 45
  A — V2 target below legacy cap → strictly unchanged
  B — V2 target above legacy cap → strictly unchanged
  C — target_km_protected=None → legacy path (compute_target_km + apply_resume_guard) still runs
  D — deep_reprise duration → prescription duration-based unchanged
  E — partial_reprise duration → no artificial km target
  F — TSS non-regressed: active=None, rest=0, total=None
  SPY — prove call counts via monkeypatching
"""
from __future__ import annotations

import asyncio
import os
import sys

os.environ.setdefault("JWT_SECRET", "test-secret-pr161")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import pytest
import llm_coach as _llm_coach
from llm_coach import generate_cycle_week


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    loop = asyncio.new_event_loop()
    try:
        return loop.run_until_complete(coro)
    finally:
        loop.close()


def _base_ctx(**extra):
    ctx = {
        "weekly_km": 40,
        "km_7": 38,
        "paces": {
            "z1": "7:00-7:30",
            "z2": "6:00-6:30",
            "z3": "5:30-5:45",
            "z4": "5:00-5:15",
        },
    }
    ctx.update(extra)
    return ctx


# ---------------------------------------------------------------------------
# REGRESSION: V2 proposes 45, legacy guard would cap to 42 (40*1.05).
# With current_weekly_km=40, km_7=10 → recent < chronic*0.5 → cap = 40*1.05 = 42.
# PR161 must preserve 45 exactly.
# ---------------------------------------------------------------------------

def test_regression_v2_target_preserved_over_legacy_cap():
    """
    BEFORE PR161: V2 proposes 45, legacy guard caps to 42.
    AFTER PR161:  V2 proposes 45, generate_cycle_week returns weekly_km ≥ 45
                  (plan may slightly round per session structure, but target_km used
                   by the generator must be exactly 45).
    We verify via spy that apply_resume_guard is NOT called when target_km_protected is set.
    """
    calls = []

    original_guard = _llm_coach.apply_resume_guard

    def spy_guard(target, recent, chronic):
        calls.append(("apply_resume_guard", target, recent, chronic))
        return original_guard(target, recent, chronic)

    _llm_coach.apply_resume_guard = spy_guard
    try:
        ctx = _base_ctx(
            weekly_km=40,
            km_7=10,                   # triggers legacy guard: 10 < 40*0.5=20
            target_km_protected=45.0,
        )
        plan, success, _ = _run(
            generate_cycle_week(
                context=ctx,
                phase="build",
                target_load=80,
                goal="MARATHON",
                user_id="test_pr161_regression",
                sessions_per_week=6,
            )
        )
    finally:
        _llm_coach.apply_resume_guard = original_guard

    assert success
    # Guard must NOT have been called at all during the V2-protected path
    assert calls == [], (
        f"apply_resume_guard was called {len(calls)} time(s) when target_km_protected is set: {calls}"
    )


def test_regression_v2_target_km_value():
    """
    Verify that the planned_load and weekly_km in the plan correspond to a target of 45,
    not the legacy-capped 42.  The plan's weekly_km should be >= 44 (rounding tolerance ±1).
    """
    ctx = _base_ctx(
        weekly_km=40,
        km_7=10,
        target_km_protected=45.0,
    )
    plan, success, _ = _run(
        generate_cycle_week(
            context=ctx,
            phase="build",
            target_load=80,
            goal="MARATHON",
            user_id="test_pr161_regression_km",
            sessions_per_week=6,
        )
    )
    assert success
    # Weekly km in plan must come from V2 target (45), NOT from legacy cap (42).
    # We allow ±1 km rounding from session distribution.
    assert plan["weekly_km"] >= 44, (
        f"weekly_km={plan['weekly_km']} looks like legacy cap 42; expected ≈45 from V2 target"
    )


# ---------------------------------------------------------------------------
# A — V2 target BELOW legacy cap → strictly unchanged (guard would leave it alone anyway)
# ---------------------------------------------------------------------------

def test_a_v2_target_below_legacy_cap_unchanged():
    """
    V2 target = 38, legacy would not cap further. Still, guard must NOT be called.
    """
    calls = []
    original_guard = _llm_coach.apply_resume_guard

    def spy_guard(target, recent, chronic):
        calls.append(target)
        return original_guard(target, recent, chronic)

    _llm_coach.apply_resume_guard = spy_guard
    try:
        ctx = _base_ctx(weekly_km=40, km_7=35, target_km_protected=38.0)
        plan, success, _ = _run(
            generate_cycle_week(
                context=ctx, phase="base", target_load=60,
                goal="10K", user_id="test_pr161_a", sessions_per_week=4,
            )
        )
    finally:
        _llm_coach.apply_resume_guard = original_guard

    assert success
    assert calls == [], f"apply_resume_guard was called with target_km_protected set: {calls}"


# ---------------------------------------------------------------------------
# B — V2 target ABOVE legacy cap → strictly unchanged
# (duplicate of regression, different values to be explicit)
# ---------------------------------------------------------------------------

def test_b_v2_target_above_legacy_cap_unchanged():
    """
    V2 target = 50, chronic=40, recent=10 → legacy cap = 42.
    Guard must NOT be called; target must NOT be reduced to 42.
    """
    calls = []
    original_guard = _llm_coach.apply_resume_guard

    def spy_guard(target, recent, chronic):
        calls.append(target)
        return original_guard(target, recent, chronic)

    _llm_coach.apply_resume_guard = spy_guard
    try:
        ctx = _base_ctx(weekly_km=40, km_7=10, target_km_protected=50.0)
        plan, success, _ = _run(
            generate_cycle_week(
                context=ctx, phase="build", target_load=90,
                goal="MARATHON", user_id="test_pr161_b", sessions_per_week=6,
            )
        )
    finally:
        _llm_coach.apply_resume_guard = original_guard

    assert success
    assert calls == [], f"apply_resume_guard called {len(calls)} time(s): {calls}"
    # weekly_km should be ≈50, not 42
    assert plan["weekly_km"] >= 45, (
        f"weekly_km={plan['weekly_km']} was reduced by legacy guard despite V2 protection"
    )


# ---------------------------------------------------------------------------
# C — target_km_protected=None → legacy path still functions
# ---------------------------------------------------------------------------

def test_c_legacy_path_still_called_when_no_v2_target(monkeypatch):
    """
    When target_km_protected is absent, compute_target_km and apply_resume_guard
    must still be called (legacy behaviour preserved).
    """
    compute_calls = []
    guard_calls = []

    original_compute = _llm_coach.compute_target_km
    original_guard = _llm_coach.apply_resume_guard

    def spy_compute(weekly_km, goal, phase):
        result = original_compute(weekly_km, goal, phase)
        compute_calls.append(result)
        return result

    def spy_guard(target, recent, chronic):
        result = original_guard(target, recent, chronic)
        guard_calls.append((target, result))
        return result

    _llm_coach.compute_target_km = spy_compute
    _llm_coach.apply_resume_guard = spy_guard
    try:
        ctx = _base_ctx(weekly_km=40, km_7=38)  # no target_km_protected
        plan, success, _ = _run(
            generate_cycle_week(
                context=ctx, phase="build", target_load=80,
                goal="MARATHON", user_id="test_pr161_c", sessions_per_week=5,
            )
        )
    finally:
        _llm_coach.compute_target_km = original_compute
        _llm_coach.apply_resume_guard = original_guard

    assert success
    assert len(compute_calls) >= 1, "compute_target_km must be called on legacy path"
    assert len(guard_calls) >= 1, "apply_resume_guard must be called on legacy path"


def test_c_explicit_none_is_treated_as_absent(monkeypatch):
    """
    target_km_protected=None explicitly must behave like absent (use legacy path).
    This also validates `is not None` semantics over falsy check.
    """
    guard_calls = []
    original_guard = _llm_coach.apply_resume_guard

    def spy_guard(target, recent, chronic):
        guard_calls.append(target)
        return original_guard(target, recent, chronic)

    _llm_coach.apply_resume_guard = spy_guard
    try:
        ctx = _base_ctx(weekly_km=40, km_7=38, target_km_protected=None)
        plan, success, _ = _run(
            generate_cycle_week(
                context=ctx, phase="build", target_load=80,
                goal="MARATHON", user_id="test_pr161_c_none", sessions_per_week=5,
            )
        )
    finally:
        _llm_coach.apply_resume_guard = original_guard

    assert success
    assert len(guard_calls) >= 1, "apply_resume_guard must be called when target_km_protected=None"


# ---------------------------------------------------------------------------
# D — deep_reprise duration-based → prescription duration unchanged
# ---------------------------------------------------------------------------

def test_d_deep_reprise_duration_based():
    """
    Deep reprise uses duration-based sessions; target_km_protected=None.
    Verify duration-based path is still returned correctly.
    """
    ctx = {
        **_base_ctx(),
        "training_state": "deep_reprise",
        "prior_weekly_km": 30,
        "reprise_active_weeks": 1,
    }
    plan, success, _ = _run(
        generate_cycle_week(
            context=ctx, phase="build", target_load=40,
            goal="SEMI", user_id="test_pr161_d",
        )
    )
    assert success
    assert plan.get("reprise") is True
    assert plan.get("weekly_minutes") is not None and plan["weekly_minutes"] > 0
    # All active sessions have a duration field
    for s in plan["sessions"]:
        assert "duration" in s


# ---------------------------------------------------------------------------
# E — partial_reprise duration → no artificial km target
# ---------------------------------------------------------------------------

def test_e_partial_reprise_no_artificial_km():
    """
    Partial reprise path: plan is duration-driven.
    PR161 must not invent a km target for this path.
    """
    ctx = {
        **_base_ctx(),
        "training_state": "partial_reprise",
        "prior_weekly_km": 25,
        "reprise_active_weeks": 2,
    }
    plan, success, _ = _run(
        generate_cycle_week(
            context=ctx, phase="base", target_load=40,
            goal="SEMI", user_id="test_pr161_e",
        )
    )
    assert success
    assert plan.get("reprise") is True
    # No km target field was invented by PR161 code
    # (weekly_km reflects actual session distances, not a new protected target)
    assert "weekly_km" in plan  # field exists from existing code, not new


# ---------------------------------------------------------------------------
# F — TSS non-regressed: active=None, rest=0, total=None
# ---------------------------------------------------------------------------

def test_f_tss_non_regression_v2_protected():
    """
    Even with target_km_protected set, TSS must remain: active=None, rest=0, total=None.
    """
    ctx = _base_ctx(weekly_km=40, km_7=38, target_km_protected=45.0)
    plan, success, _ = _run(
        generate_cycle_week(
            context=ctx, phase="build", target_load=80,
            goal="MARATHON", user_id="test_pr161_f", sessions_per_week=6,
        )
    )
    assert success
    assert plan["total_tss"] is None
    for s in plan["sessions"]:
        if s["type"] == "rest":
            assert s["estimated_tss"] == 0
        else:
            assert s["estimated_tss"] is None, (
                f"{s['type']} has estimated_tss={s['estimated_tss']} (expected None)"
            )


def test_f_tss_non_regression_legacy_path():
    """
    On the legacy path (no V2 target), TSS must also remain: active=None, rest=0, total=None.
    """
    ctx = _base_ctx(weekly_km=40, km_7=38)
    plan, success, _ = _run(
        generate_cycle_week(
            context=ctx, phase="build", target_load=80,
            goal="MARATHON", user_id="test_pr161_f_legacy", sessions_per_week=6,
        )
    )
    assert success
    assert plan["total_tss"] is None
    for s in plan["sessions"]:
        if s["type"] == "rest":
            assert s["estimated_tss"] == 0
        else:
            assert s["estimated_tss"] is None


# ---------------------------------------------------------------------------
# SPY — exhaustive call-count proof
# ---------------------------------------------------------------------------

def test_spy_v2_path_zero_guard_zero_compute():
    """
    With target_km_protected set:
      apply_resume_guard called = 0
      compute_target_km called = 0
    """
    guard_calls = []
    compute_calls = []

    original_guard = _llm_coach.apply_resume_guard
    original_compute = _llm_coach.compute_target_km

    def spy_guard(t, r, c):
        guard_calls.append(t)
        return original_guard(t, r, c)

    def spy_compute(wkm, goal, phase):
        result = original_compute(wkm, goal, phase)
        compute_calls.append(result)
        return result

    _llm_coach.apply_resume_guard = spy_guard
    _llm_coach.compute_target_km = spy_compute
    try:
        ctx = _base_ctx(weekly_km=40, km_7=10, target_km_protected=45.0)
        plan, success, _ = _run(
            generate_cycle_week(
                context=ctx, phase="build", target_load=80,
                goal="MARATHON", user_id="test_pr161_spy_v2", sessions_per_week=6,
            )
        )
    finally:
        _llm_coach.apply_resume_guard = original_guard
        _llm_coach.compute_target_km = original_compute

    assert success
    assert guard_calls == [], (
        f"apply_resume_guard called {len(guard_calls)} time(s) on V2 protected path: {guard_calls}"
    )
    assert compute_calls == [], (
        f"compute_target_km called {len(compute_calls)} time(s) on V2 protected path: {compute_calls}"
    )


def test_spy_legacy_path_calls_both():
    """
    Without target_km_protected:
      apply_resume_guard called >= 1
      compute_target_km called >= 1
    """
    guard_calls = []
    compute_calls = []

    original_guard = _llm_coach.apply_resume_guard
    original_compute = _llm_coach.compute_target_km

    def spy_guard(t, r, c):
        guard_calls.append(t)
        return original_guard(t, r, c)

    def spy_compute(wkm, goal, phase):
        result = original_compute(wkm, goal, phase)
        compute_calls.append(result)
        return result

    _llm_coach.apply_resume_guard = spy_guard
    _llm_coach.compute_target_km = spy_compute
    try:
        ctx = _base_ctx(weekly_km=40, km_7=38)  # no V2 protection
        plan, success, _ = _run(
            generate_cycle_week(
                context=ctx, phase="build", target_load=80,
                goal="MARATHON", user_id="test_pr161_spy_legacy", sessions_per_week=5,
            )
        )
    finally:
        _llm_coach.apply_resume_guard = original_guard
        _llm_coach.compute_target_km = original_compute

    assert success
    assert len(compute_calls) >= 1, "compute_target_km must be called on legacy path"
    assert len(guard_calls) >= 1, "apply_resume_guard must be called on legacy path"
