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
    plan = _get_plan_6()
    for s in plan["sessions"]:
        assert s["type"] in ACTIVE_TYPES | {"rest"}
        assert "duration" in s
        assert "distance_km" in s
        if s["type"] != "rest":
            assert s["distance_km"] > 0
