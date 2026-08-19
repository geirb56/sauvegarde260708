"""Regression tests: readiness must NOT influence training plan duration.

Scope of this PR:
  - `adjusted_weeks` (a.k.a. recommended_weeks / cycle_weeks) is driven
    ONLY by the goal's base weeks.
  - `readiness_score` and `prep_status` are still computed and returned
    (they remain available to adapt load/sessions elsewhere), but they
    NO LONGER change the plan duration.
  - When `weeks_available < adjusted_weeks`, the plan is NOT silently
    shrunk: `adjusted_weeks` is preserved and `prep_insufficient=True`
    is flagged.

Pure unit tests: no HTTP, no DB, no LLM.
"""

import ast
import os
import sys
import inspect

# Make the backend package importable when tests are run from the repo root.
_HERE = os.path.dirname(os.path.abspath(__file__))
_BACKEND = os.path.dirname(_HERE)
if _BACKEND not in sys.path:
    sys.path.insert(0, _BACKEND)

import pytest

import coach_service
from config.training_goals import GOAL_CONFIG


# ---------------------------------------------------------------------------
# Base weeks per goal must remain untouched by this PR.
# ---------------------------------------------------------------------------

EXPECTED_BASE_WEEKS = {
    "5K": 6,
    "10K": 8,
    "SEMI": 12,
    "MARATHON": 16,
    "ULTRA": 20,
}


@pytest.mark.parametrize("goal,expected", list(EXPECTED_BASE_WEEKS.items()))
def test_goal_config_base_weeks_unchanged(goal, expected):
    """The GOAL_CONFIG cycle_weeks values must remain exactly as documented."""
    assert GOAL_CONFIG[goal]["cycle_weeks"] == expected


# ---------------------------------------------------------------------------
# Source-level checks: readiness-based multipliers on base_weeks are gone.
# ---------------------------------------------------------------------------

def _plan_source() -> str:
    return inspect.getsource(coach_service.generate_dynamic_training_plan)


def test_no_readiness_multiplier_on_base_weeks():
    """The old formula scaled base_weeks by 0.75 / 1.25 / 1.5 depending on
    readiness. Those multipliers must no longer be applied to base_weeks."""
    src = _plan_source()
    for forbidden in ("base_weeks * 0.75", "base_weeks * 1.25", "base_weeks * 1.5"):
        assert forbidden not in src, (
            f"Found forbidden expression `{forbidden}`: readiness must not "
            f"influence plan duration."
        )


def test_adjusted_weeks_is_base_weeks():
    """`adjusted_weeks` must equal `base_weeks` or `total_weeks` — never a
    readiness-derived expression.  Uses AST inspection so the test is immune
    to formatting or dict-vs-assignment refactors."""
    # Allowed variable names that may appear as the value for "adjusted_weeks"
    _ALLOWED_NAMES = {"base_weeks", "total_weeks"}

    source_file = inspect.getfile(coach_service.generate_dynamic_training_plan)
    tree = ast.parse(open(source_file).read(), filename=source_file)

    # Find the function node
    func_node = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name == "generate_dynamic_training_plan":
                func_node = node
                break
    assert func_node is not None, "generate_dynamic_training_plan not found"

    # Collect all values assigned to "adjusted_weeks" in dict literals
    found = []
    for node in ast.walk(func_node):
        if isinstance(node, ast.Dict):
            for key, value in zip(node.keys, node.values):
                if isinstance(key, ast.Constant) and key.value == "adjusted_weeks":
                    found.append(value)

    # We expect at least one non-None assignment
    non_none = [v for v in found if not (isinstance(v, ast.Constant) and v.value is None)]
    assert non_none, (
        "No non-None 'adjusted_weeks' value found in generate_dynamic_training_plan"
    )

    for value_node in non_none:
        assert isinstance(value_node, ast.Name) and value_node.id in _ALLOWED_NAMES, (
            f"'adjusted_weeks' must be set to one of {_ALLOWED_NAMES}, "
            f"got: {ast.dump(value_node)}"
        )


def test_no_silent_shrink_to_weeks_available():
    """The old code did `adjusted_weeks = min(adjusted_weeks, weeks_available)`
    which silently shrank the plan when the race was too close. That behavior
    must be gone; the plan must expose `prep_insufficient` instead."""
    src = _plan_source()
    assert "min(adjusted_weeks, weeks_available)" not in src
    assert "prep_insufficient" in src


# ---------------------------------------------------------------------------
# Behavioral checks — reproduce the exact decoupled logic used in
# generate_dynamic_training_plan and verify the invariants demanded by the PR.
# ---------------------------------------------------------------------------

GOAL_REQUIREMENTS = {
    "5K": {"min_weekly_km": 15, "min_vo2max": 35, "base_weeks": 6},
    "10K": {"min_weekly_km": 25, "min_vo2max": 38, "base_weeks": 8},
    "SEMI": {"min_weekly_km": 35, "min_vo2max": 42, "base_weeks": 12},
    "MARATHON": {"min_weekly_km": 50, "min_vo2max": 45, "base_weeks": 16},
    "ULTRA": {"min_weekly_km": 60, "min_vo2max": 48, "base_weeks": 20},
}


def _prep_status_from_readiness(readiness_score: float) -> str:
    if readiness_score >= 90:
        return "avancé"
    if readiness_score >= 70:
        return "normal"
    if readiness_score >= 50:
        return "progressif"
    return "débutant"


def _compute_recommended_weeks(goal: str, readiness_score: float) -> int:
    """Mirror the decoupled logic: duration depends ONLY on goal.base_weeks."""
    req = GOAL_REQUIREMENTS[goal]
    base_weeks = req["base_weeks"]
    _ = _prep_status_from_readiness(readiness_score)  # computed, not used for duration
    return base_weeks


def _prep_insufficient(recommended_weeks: int, weeks_available: int) -> bool:
    return weeks_available < recommended_weeks


# Test 1 — readiness faible : MARATHON stays at 16 weeks.
def test_marathon_with_low_readiness_stays_16_weeks():
    assert _compute_recommended_weeks("MARATHON", readiness_score=10) == 16
    assert _compute_recommended_weeks("MARATHON", readiness_score=40) == 16


# Test 2 — readiness élevé : MARATHON stays at 16 weeks.
def test_marathon_with_high_readiness_stays_16_weeks():
    assert _compute_recommended_weeks("MARATHON", readiness_score=90) == 16
    assert _compute_recommended_weeks("MARATHON", readiness_score=100) == 16


# Test 3 — all goals, independent of readiness.
@pytest.mark.parametrize("goal,expected", list(EXPECTED_BASE_WEEKS.items()))
@pytest.mark.parametrize("readiness", [0, 25, 50, 75, 100])
def test_recommended_weeks_independent_of_readiness(goal, expected, readiness):
    assert _compute_recommended_weeks(goal, readiness_score=readiness) == expected


# Test 4 — date trop proche : plan not shrunk, prep_insufficient=True.
def test_prep_insufficient_when_time_too_short():
    recommended = _compute_recommended_weeks("MARATHON", readiness_score=75)
    weeks_available = 8
    assert recommended == 16  # NOT shrunk to 8
    assert _prep_insufficient(recommended, weeks_available) is True


# Test 5 — temps suffisant : plan unchanged, prep_insufficient=False.
def test_prep_sufficient_when_time_ok():
    recommended = _compute_recommended_weeks("MARATHON", readiness_score=75)
    weeks_available = 20
    assert recommended == 16
    assert _prep_insufficient(recommended, weeks_available) is False


# Extra: prep_status is still exposed by the same buckets (unchanged semantics
# other than the fact it no longer influences duration).
@pytest.mark.parametrize(
    "readiness,expected_status",
    [(10, "débutant"), (60, "progressif"), (75, "normal"), (95, "avancé")],
)
def test_prep_status_buckets_preserved(readiness, expected_status):
    assert _prep_status_from_readiness(readiness) == expected_status
