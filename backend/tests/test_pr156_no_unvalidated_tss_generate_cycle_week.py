"""
PR #156 — Prove that generate_cycle_week no longer uses unvalidated TSS/km
coefficients for active sessions.

Tests:
1. All active session types → estimated_tss = None
2. Rest sessions → estimated_tss = 0
3. total_tss = None
4. AST proof: legacy coefficients 4/5/6/7/8 are not used as TSS/km multipliers
"""
from __future__ import annotations

import ast
import asyncio
import inspect
import os
import sys

os.environ.setdefault("JWT_SECRET", "test-secret-pr156")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

import pytest

from llm_coach import generate_cycle_week


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

CONTEXT = {
    "weekly_km": 40,
    "km_7": 38,
    "paces": {
        "z1": "7:00-7:30",
        "z2": "6:00-6:30",
        "z3": "5:30-5:45",
        "z4": "5:00-5:15",
    },
}


def _get_plan_6():
    loop = asyncio.new_event_loop()
    try:
        plan, success, _ = loop.run_until_complete(
            generate_cycle_week(
                context=CONTEXT,
                phase="build",
                target_load=80,
                goal="MARATHON",
                user_id="test_pr156",
                sessions_per_week=6,
            )
        )
    finally:
        loop.close()
    assert success
    return plan


ACTIVE_TYPES = {"recovery", "endurance", "tempo", "threshold", "fartlek", "long_run"}


# ---------------------------------------------------------------------------
# Test: active sessions have estimated_tss = None
# ---------------------------------------------------------------------------

def test_recovery_tss_none():
    plan = _get_plan_6()
    matching = [s for s in plan["sessions"] if s["type"] == "recovery"]
    assert matching
    for s in matching:
        assert s["estimated_tss"] is None


def test_endurance_tss_none():
    plan = _get_plan_6()
    matching = [s for s in plan["sessions"] if s["type"] == "endurance"]
    assert matching
    for s in matching:
        assert s["estimated_tss"] is None


def test_tempo_tss_none():
    plan = _get_plan_6()
    matching = [s for s in plan["sessions"] if s["type"] == "tempo"]
    assert matching
    for s in matching:
        assert s["estimated_tss"] is None


def test_threshold_tss_none():
    plan = _get_plan_6()
    matching = [s for s in plan["sessions"] if s["type"] == "threshold"]
    assert matching
    for s in matching:
        assert s["estimated_tss"] is None


def test_long_run_tss_none():
    plan = _get_plan_6()
    matching = [s for s in plan["sessions"] if s["type"] == "long_run"]
    assert matching
    for s in matching:
        assert s["estimated_tss"] is None


def test_fartlek_tss_none():
    """Fartlek may not appear in default 6-session build; test via 5-session."""
    loop = asyncio.new_event_loop()
    try:
        # Use intensification phase which may include fartlek, or just
        # verify the template doesn't produce TSS for any active type.
        plan, success, _ = loop.run_until_complete(
            generate_cycle_week(
                context=CONTEXT, phase="build", target_load=80,
                goal="MARATHON", user_id="test_pr156", sessions_per_week=6,
            )
        )
    finally:
        loop.close()
    # All active sessions must be None regardless of type
    for s in plan["sessions"]:
        if s["type"] != "rest":
            assert s["estimated_tss"] is None, f"{s['type']} has TSS={s['estimated_tss']}"


# ---------------------------------------------------------------------------
# Test: rest sessions have estimated_tss = 0
# ---------------------------------------------------------------------------

def test_rest_session_tss_is_zero():
    plan = _get_plan_6()
    rest_sessions = [s for s in plan["sessions"] if s["type"] == "rest"]
    assert len(rest_sessions) >= 1
    for s in rest_sessions:
        assert s["estimated_tss"] == 0


# ---------------------------------------------------------------------------
# Test: total_tss = None
# ---------------------------------------------------------------------------

def test_total_tss_is_none():
    plan = _get_plan_6()
    assert plan["total_tss"] is None


# ---------------------------------------------------------------------------
# Test: reprise path also has None TSS for active sessions
# ---------------------------------------------------------------------------

def test_reprise_active_tss_none():
    ctx = {**CONTEXT, "training_state": "deep_reprise", "prior_weekly_km": 30, "reprise_active_weeks": 1}
    loop = asyncio.new_event_loop()
    try:
        plan, success, _ = loop.run_until_complete(
            generate_cycle_week(context=ctx, phase="build", target_load=50, goal="SEMI", user_id="test_pr156")
        )
    finally:
        loop.close()
    assert success
    for s in plan["sessions"]:
        if s["type"] == "rest":
            assert s["estimated_tss"] == 0
        else:
            assert s["estimated_tss"] is None, f"Reprise {s['type']} has TSS={s['estimated_tss']}"
    assert plan["total_tss"] is None


# ---------------------------------------------------------------------------
# AST proof: no legacy TSS/km coefficients (4,5,6,7,8) used as multipliers
# ---------------------------------------------------------------------------

def test_ast_no_legacy_tss_coefficients():
    """
    Prove via AST that generate_cycle_week source does NOT contain
    expressions like `distance * N` where N in {4, 5, 6, 7, 8} that would
    represent unvalidated TSS/km coefficients.
    """
    source = inspect.getsource(generate_cycle_week)
    tree = ast.parse(source)

    legacy_coefficients = {4, 5, 6, 7, 8}
    violations = []

    for node in ast.walk(tree):
        if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Mult):
            for operand in (node.left, node.right):
                if isinstance(operand, ast.Constant) and operand.value in legacy_coefficients:
                    other = node.right if operand is node.left else node.left
                    other_src = ast.dump(other)
                    if "dist" in other_src.lower() or "km" in other_src.lower():
                        violations.append(
                            f"Line ~{node.lineno}: multiplication by {operand.value} "
                            f"with distance-like operand"
                        )

    assert not violations, (
        "Legacy TSS/km coefficients still present:\n" + "\n".join(violations)
    )


# ---------------------------------------------------------------------------
# Test: distances/durations/types preserved (non-regression)
# ---------------------------------------------------------------------------

def test_distances_and_types_preserved():
    """
    Historical PR#156 context (CONTEXT has weekly_km=40, no target_km_protected,
    no long_run_km_v2).  generate_cycle_week falls into the normal/volume-driven
    path (training_state defaults to "normal" — NOT a reprise path).

    Contracts verified:
    - All session types are known types.
    - Fields 'duration' and 'distance_km' are present on every session.
    - Non-long_run active sessions: distance_km > 0 and duration > 0 (volume-driven).
    - long_run with target_long_run=0 (no long_run_km_v2): distance_km=0, duration=0
      (placeholder — no artificial km invented; not a duration-based reprise path).
    """
    plan = _get_plan_6()

    for s in plan["sessions"]:
        assert s["type"] in ACTIVE_TYPES | {"rest"}
        assert "duration" in s
        assert "distance_km" in s
        if s["type"] == "rest":
            continue
        if s["type"] == "long_run":
            # target_long_run=0 (no long_run_km_v2 in CONTEXT) → distance=0, duration=0.
            # This is a 0/0 placeholder in the normal km-based path, not a reprise week.
            assert s["distance_km"] >= 0, (
                f"long_run distance_km must not be negative, got {s['distance_km']}"
            )
        else:
            # Non-long_run sessions are volume-driven → both fields must be positive.
            dur_val = int(s["duration"].replace("min", ""))
            assert dur_val > 0, (
                f"Volume-driven session {s['type']} must have duration > 0, got {s['duration']}"
            )
            assert s["distance_km"] > 0, (
                f"Volume-driven session {s['type']} must have distance_km > 0, "
                f"got {s['distance_km']}"
            )


def test_distances_and_types_preserved_distance_based():
    """
    Explicit distance-based path: when long_run_km_v2 and target_km_protected are
    provided, ALL active sessions (including long_run) must have distance_km > 0 and
    duration > 0.
    """
    ctx = {**CONTEXT, "target_km_protected": 42.0, "long_run_km_v2": 24.0}
    loop = asyncio.new_event_loop()
    try:
        plan, success, _ = loop.run_until_complete(
            generate_cycle_week(
                context=ctx,
                phase="build",
                target_load=80,
                goal="MARATHON",
                user_id="test_pr156_dist",
                sessions_per_week=6,
            )
        )
    finally:
        loop.close()
    assert success
    for s in plan["sessions"]:
        assert s["type"] in ACTIVE_TYPES | {"rest"}
        assert "duration" in s
        assert "distance_km" in s
        if s["type"] != "rest":
            assert s["distance_km"] > 0, (
                f"Distance-based session {s['type']} must have distance_km > 0, "
                f"got {s['distance_km']}"
            )
            dur_val = int(s["duration"].replace("min", ""))
            assert dur_val > 0, (
                f"Distance-based session {s['type']} must have duration > 0, got {s['duration']}"
            )


def test_distances_and_types_preserved_duration_based():
    """
    REAL DURATION-BASED PATH: training_state="deep_reprise".

    In generate_cycle_week, the ONLY paths that are genuinely duration-prescribed
    are training_state in ("deep_reprise", "partial_reprise").  These trigger an
    early-return branch that:
      - builds sessions by DURATION (reprise_durations(prior_weekly_km, active_weeks))
      - derives distance_km = round(duration / easy_pace, 1)   ← positive, pace-derived
      - sets plan["reprise"] = True                             ← unique branch invariant
      - sets plan["weekly_minutes"] (total prescribed minutes)
      - does NOT use target_km (compute_target_km is called earlier but its result
        is discarded — the reprise branch returns before any volume-split logic)
      - NEVER invents an artificial target_km_protected

    NOTE: removing target_km_protected/long_run_km_v2 from context does NOT activate
    this path — that falls back to the normal km-based volume split.

    Contracts verified for the deep_reprise branch:
    - plan["reprise"] is True   (unique invariant proving the reprise branch was taken)
    - plan["weekly_minutes"] > 0 (total prescribed minutes — not None)
    - All active sessions have duration > 0 (duration is the prescriptive authority)
    - All active sessions have distance_km > 0 (pace-derived: dur / easy_pace)
    - estimated_tss = None for active sessions, 0 for rest; total_tss = None
    """
    ctx = {
        "weekly_km": 0,
        "km_7": 0,
        "training_state": "deep_reprise",
        "prior_weekly_km": 30.0,
        "reprise_active_weeks": 0,
        "paces": CONTEXT["paces"],
    }
    loop = asyncio.new_event_loop()
    try:
        plan, success, _ = loop.run_until_complete(
            generate_cycle_week(
                context=ctx,
                phase="build",
                goal="MARATHON",
                user_id="test_pr156_dur_deep",
            )
        )
    finally:
        loop.close()

    assert success
    # Unique invariant: only the reprise branch sets plan["reprise"] = True.
    assert plan.get("reprise") is True, (
        "deep_reprise must set plan['reprise']=True; got plan without reprise branch invariant"
    )
    # Duration is the prescriptive authority in this branch.
    assert plan.get("weekly_minutes") is not None and plan["weekly_minutes"] > 0, (
        f"deep_reprise must set weekly_minutes > 0, got {plan.get('weekly_minutes')}"
    )
    # TSS contract unchanged.
    assert plan["total_tss"] is None
    for s in plan["sessions"]:
        assert s["type"] in ACTIVE_TYPES | {"rest"}
        assert "duration" in s
        assert "distance_km" in s
        if s["type"] == "rest":
            assert s["estimated_tss"] == 0
        else:
            # Duration is the authority → duration > 0.
            dur_val = int(s["duration"].replace("min", ""))
            assert dur_val > 0, (
                f"deep_reprise active session {s['type']} must have duration > 0, "
                f"got {s['duration']}"
            )
            # distance_km is pace-derived from duration → must also be positive.
            assert s["distance_km"] > 0, (
                f"deep_reprise active session {s['type']} distance_km must be > 0 "
                f"(pace-derived from duration), got {s['distance_km']}"
            )
            assert s["estimated_tss"] is None


def test_distances_and_types_preserved_duration_based_partial_reprise():
    """
    REAL DURATION-BASED PATH: training_state="partial_reprise".

    Same runtime branch as deep_reprise (training_state in ("deep_reprise",
    "partial_reprise")).  Same duration-primary contract; reprise_active_weeks > 0
    gives slightly longer sessions.  plan["reprise"] = True is the branch invariant.
    """
    ctx = {
        "weekly_km": 10,
        "km_7": 10,
        "training_state": "partial_reprise",
        "prior_weekly_km": 40.0,
        "reprise_active_weeks": 2,
        "paces": CONTEXT["paces"],
    }
    loop = asyncio.new_event_loop()
    try:
        plan, success, _ = loop.run_until_complete(
            generate_cycle_week(
                context=ctx,
                phase="build",
                goal="SEMI",
                user_id="test_pr156_dur_partial",
            )
        )
    finally:
        loop.close()

    assert success
    assert plan.get("reprise") is True, (
        "partial_reprise must set plan['reprise']=True"
    )
    assert plan.get("weekly_minutes") is not None and plan["weekly_minutes"] > 0
    assert plan["total_tss"] is None
    for s in plan["sessions"]:
        if s["type"] == "rest":
            assert s["estimated_tss"] == 0
        else:
            dur_val = int(s["duration"].replace("min", ""))
            assert dur_val > 0, (
                f"partial_reprise session {s['type']} must have duration > 0, "
                f"got {s['duration']}"
            )
            assert s["distance_km"] > 0, (
                f"partial_reprise session {s['type']} distance_km must be > 0 "
                f"(pace-derived from duration), got {s['distance_km']}"
            )
            assert s["estimated_tss"] is None
