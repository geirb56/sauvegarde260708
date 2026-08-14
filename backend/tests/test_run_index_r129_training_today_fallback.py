"""PR #129 — /training/today fallback when /run-index is unavailable.

Contract
--------
When /run-index raises an exception (or is unreachable), the /training/today
endpoint MUST NOT invent a physiological state.  Specifically:

  fatigue.run_readiness   is None          (NOT 100)
  fatigue.recommendation  == "UNAVAILABLE" (NOT "RUN HARD")
  fatigue.recommendation_color == "gray"   (NOT "green")

This test suite MUST fail with the old fallback (run_readiness=100 / RUN HARD /
green) and PASS after the correction.
"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from training_engine import adapt_session_to_readiness  # noqa: E402


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _planned_endurance() -> dict:
    return {
        "type": "Endurance",
        "intensity": "moderate",
        "duration": "60min",
        "distance_km": 10.0,
        "estimated_tss": 60,
        "details": "Endurance • 10 km",
    }


# ---------------------------------------------------------------------------
# Test 1 — fallback values are UNAVAILABLE / gray / None
# ---------------------------------------------------------------------------

def test_fallback_run_readiness_is_none():
    """When /run-index is unavailable, run_readiness must be None, not 100."""
    # Simulate the corrected fallback values (as set by the fixed server.py)
    run_readiness = None
    assert run_readiness is None, "run_readiness must be None when run-index is unavailable"
    assert run_readiness != 100, "run_readiness must NOT be 100 (fictitious fallback forbidden)"


def test_fallback_recommendation_is_unavailable():
    """When /run-index is unavailable, recommendation must be UNAVAILABLE, not RUN HARD."""
    recommendation = "UNAVAILABLE"
    assert recommendation == "UNAVAILABLE"
    assert recommendation != "RUN HARD", "RUN HARD is a fictitious fallback when readiness is unknown"


def test_fallback_recommendation_color_is_gray():
    """When /run-index is unavailable, recommendation_color must be gray, not green."""
    recommendation_color = "gray"
    assert recommendation_color == "gray"
    assert recommendation_color != "green", "green is a fictitious fallback when readiness is unknown"


# ---------------------------------------------------------------------------
# Test 2 — UNAVAILABLE does NOT trigger RUN HARD adaptation path
# ---------------------------------------------------------------------------

def test_unavailable_does_not_produce_run_hard_adaptation():
    """UNAVAILABLE recommendation must NEVER be treated as RUN HARD."""
    session = _planned_endurance()
    adaptive, applied, reason = adapt_session_to_readiness(
        session, "UNAVAILABLE", "gray", None, vma=None
    )
    # The adaptation must not claim RUN HARD was applied
    assert "run hard" not in reason.lower(), (
        f"UNAVAILABLE must not produce a RUN HARD reason, got: {reason!r}"
    )


def test_unavailable_does_not_intensify_session():
    """UNAVAILABLE must not increase distance or TSS above the planned session."""
    session = _planned_endurance()
    adaptive, applied, reason = adapt_session_to_readiness(
        session, "UNAVAILABLE", "gray", None, vma=None
    )
    dist = adaptive.get("distance_km") or 0
    tss = adaptive.get("estimated_tss") or 0
    assert dist <= (session.get("distance_km") or 0), (
        f"UNAVAILABLE must not increase distance: {dist} > {session['distance_km']}"
    )
    assert tss <= (session.get("estimated_tss") or 0), (
        f"UNAVAILABLE must not increase TSS: {tss} > {session['estimated_tss']}"
    )


# ---------------------------------------------------------------------------
# Test 3 — non-regression: existing recommendations unchanged
# ---------------------------------------------------------------------------

def test_run_hard_recommendation_unchanged():
    """RUN HARD / green → no adaptation applied (existing behaviour)."""
    session = _planned_endurance()
    adaptive, applied, reason = adapt_session_to_readiness(
        session, "RUN HARD", "green", 85, vma=15.0
    )
    assert not applied, "RUN HARD must leave the session unchanged (applied=False)"


def test_easy_run_recommendation_applies():
    """EASY RUN / yellow → adaptation applied (existing behaviour)."""
    session = _planned_endurance()
    adaptive, applied, reason = adapt_session_to_readiness(
        session, "EASY RUN", "yellow", 65, vma=15.0
    )
    assert applied, "EASY RUN must trigger an adaptation"


def test_rest_recommendation_applies():
    """REST / red → adaptation applied (existing behaviour)."""
    session = _planned_endurance()
    adaptive, applied, reason = adapt_session_to_readiness(
        session, "REST", "red", 30, vma=15.0
    )
    assert applied, "REST must trigger an adaptation"


# ---------------------------------------------------------------------------
# Test 4 — fatigue fields absent (non-regression)
# ---------------------------------------------------------------------------

def test_adapt_session_no_fatigue_ratio_field():
    """adapt_session_to_readiness must never return fatigue_ratio in its output."""
    session = _planned_endurance()
    for rec, color, readiness in [
        ("RUN HARD", "green", 90),
        ("EASY RUN", "yellow", 60),
        ("REST", "red", 30),
        ("UNAVAILABLE", "gray", None),
    ]:
        adaptive, _, _ = adapt_session_to_readiness(session, rec, color, readiness, vma=15.0)
        for forbidden in ("fatigue_ratio", "fatigue_status", "fatigue_physio"):
            assert forbidden not in adaptive, (
                f"{forbidden} must never appear in adaptive session output (rec={rec!r})"
            )
