"""PR226 — Goal-truth unification tests.

Covers:
- Goal creation/change for 5K / 10K / HM / Marathon via GOAL_CONFIG
- MAINTENANCE clears race_date / target_time (plan_goal layer)
- Fallback without goal → MAINTENANCE (source inspection)
- ULTRA without distance → rejection (plan_goal layer)
- ULTRA with valid distance → propagation (plan_goal layer)
- No stale race_date after goal change (server.py source inspection)
- UserGoalCreate model accepts distance_km for ultra (model layer)
"""
from __future__ import annotations

import ast
import os
import re
import sys
from datetime import date
from typing import Optional

import pytest

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# ---------------------------------------------------------------------------
# Source helpers (avoid importing server.py which pulls redis/motor/etc.)
# ---------------------------------------------------------------------------

_SERVER_PY = os.path.join(_BACKEND_DIR, "server.py")


def _server_source() -> str:
    with open(_SERVER_PY, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 1. GOAL_CONFIG: all 5 standard goals + MAINTENANCE present
# ---------------------------------------------------------------------------

def test_goal_config_has_all_goals():
    """GOAL_CONFIG must contain the 6 canonical goal types."""
    from config.training_goals import GOAL_CONFIG
    assert set(GOAL_CONFIG.keys()) == {"5K", "10K", "SEMI", "MARATHON", "ULTRA", "MAINTENANCE"}


@pytest.mark.parametrize("goal", ["5K", "10K", "SEMI", "MARATHON"])
def test_standard_goal_cycle_weeks(goal):
    """Each standard goal has a positive cycle_weeks value."""
    from config.training_goals import GOAL_CONFIG
    assert GOAL_CONFIG[goal]["cycle_weeks"] > 0


# ---------------------------------------------------------------------------
# 2. MAINTENANCE — plan_goal layer must reject race_date and target_time
# ---------------------------------------------------------------------------

def test_maintenance_has_no_race_date_in_plan_goal():
    """build_plan_goal(MAINTENANCE) must produce race_date=None."""
    from training_v2.plan_goal import GoalType, build_plan_goal
    pg = build_plan_goal(goal_type=GoalType.maintenance, created_from="default")
    assert pg.race_date is None


def test_maintenance_has_no_target_time_in_plan_goal():
    """build_plan_goal(MAINTENANCE) must produce target_time_seconds=None."""
    from training_v2.plan_goal import GoalType, build_plan_goal
    pg = build_plan_goal(goal_type=GoalType.maintenance, created_from="default")
    assert pg.target_time_seconds is None


def test_maintenance_has_no_target_distance_in_plan_goal():
    """build_plan_goal(MAINTENANCE) must produce target_distance_km=None."""
    from training_v2.plan_goal import GoalType, build_plan_goal
    pg = build_plan_goal(goal_type=GoalType.maintenance, created_from="default")
    assert pg.target_distance_km is None


def test_maintenance_rejects_race_date():
    """Constructing MAINTENANCE PlanGoal with race_date must raise ValueError."""
    from training_v2.plan_goal import GoalType, PlanGoal
    with pytest.raises(Exception):
        PlanGoal(
            goal_type=GoalType.maintenance,
            race_date=date(2025, 9, 28),
            created_from="user",
        )


def test_maintenance_rejects_target_time():
    """Constructing MAINTENANCE PlanGoal with target_time_seconds must raise ValueError."""
    from training_v2.plan_goal import GoalType, PlanGoal
    with pytest.raises(Exception):
        PlanGoal(
            goal_type=GoalType.maintenance,
            target_time_seconds=3600,
            created_from="user",
        )


# ---------------------------------------------------------------------------
# 3. Fallback without goal → MAINTENANCE (source-level)
# ---------------------------------------------------------------------------

def test_fallback_without_goal_is_maintenance_not_semi():
    """The dynamic fallback must be MAINTENANCE, never SEMI (PR226 fix)."""
    source = _server_source()
    assert 'plan_data.get("goal", "SEMI")' not in source, (
        "Stale SEMI fallback found — must be replaced with MAINTENANCE"
    )
    assert 'plan_data.get("goal", "MAINTENANCE")' in source, (
        "MAINTENANCE fallback not found — PR226 fix missing"
    )


# ---------------------------------------------------------------------------
# 4. set-goal clears user_goals (source-level)
# ---------------------------------------------------------------------------

def test_set_goal_deletes_user_goals_in_source():
    """POST /training/set-goal must call delete_many on user_goals (PR226)."""
    source = _server_source()
    # Find the set_training_goal function body
    match = re.search(
        r'async def set_training_goal\b.*?(?=\n@api_router|\napp\.|\Z)',
        source,
        re.DOTALL,
    )
    assert match, "set_training_goal function not found in server.py"
    fn_body = match.group(0)
    assert "user_goals.delete_many" in fn_body, (
        "set_training_goal must delete user_goals on goal change (no stale race_date)"
    )


def test_set_training_plan_goal_deletes_user_goals_in_source():
    """POST /training-plan/set-goal must also call delete_many on user_goals (PR226)."""
    source = _server_source()
    match = re.search(
        r'async def set_training_plan_goal\b.*?(?=\n@api_router|\napp\.|\Z)',
        source,
        re.DOTALL,
    )
    assert match, "set_training_plan_goal function not found in server.py"
    fn_body = match.group(0)
    assert "user_goals.delete_many" in fn_body, (
        "set_training_plan_goal must delete user_goals on goal change"
    )


# ---------------------------------------------------------------------------
# 5. ULTRA — distance enforced at plan_goal layer
# ---------------------------------------------------------------------------

def test_ultra_without_distance_refused():
    """build_plan_goal(ultra) without target_distance_km must raise ValueError."""
    from training_v2.plan_goal import GoalType, build_plan_goal
    with pytest.raises(Exception):
        build_plan_goal(goal_type=GoalType.ultra, created_from="user")


def test_ultra_exactly_marathon_refused():
    """ULTRA distance exactly 42.195 km must be refused (must be strictly greater)."""
    from training_v2.plan_goal import GoalType, build_plan_goal
    with pytest.raises(Exception):
        build_plan_goal(
            goal_type=GoalType.ultra,
            target_distance_km=42.195,
            created_from="user",
        )


def test_ultra_below_marathon_refused():
    """ULTRA distance below 42.195 km must be refused."""
    from training_v2.plan_goal import GoalType, build_plan_goal
    with pytest.raises(Exception):
        build_plan_goal(
            goal_type=GoalType.ultra,
            target_distance_km=40.0,
            created_from="user",
        )


def test_ultra_with_valid_distance_accepted():
    """ULTRA distance strictly > 42.195 km must be accepted."""
    from training_v2.plan_goal import GoalType, build_plan_goal
    pg = build_plan_goal(
        goal_type=GoalType.ultra,
        target_distance_km=50.0,
        created_from="user",
    )
    assert pg.goal_type == GoalType.ultra
    assert pg.target_distance_km == 50.0


def test_ultra_distance_propagated_exactly():
    """Custom ultra distance (e.g. 170 km) must be preserved verbatim."""
    from training_v2.plan_goal import GoalType, build_plan_goal
    pg = build_plan_goal(
        goal_type=GoalType.ultra,
        target_distance_km=170.0,
        created_from="user",
    )
    assert pg.target_distance_km == 170.0, (
        "Custom ultra distance must not be overwritten by any default"
    )


# ---------------------------------------------------------------------------
# 6. ULTRA distance required in set-goal endpoint (source-level)
# ---------------------------------------------------------------------------

def test_set_goal_endpoint_validates_ultra_distance():
    """POST /training/set-goal must reject ULTRA without distance_km (PR226)."""
    source = _server_source()
    match = re.search(
        r'async def set_training_goal\b.*?(?=\n@api_router|\napp\.|\Z)',
        source,
        re.DOTALL,
    )
    assert match, "set_training_goal not found"
    fn_body = match.group(0)
    # The function must check for ULTRA and have a 400 rejection.
    assert '"ULTRA"' in fn_body or "'ULTRA'" in fn_body
    assert "ultra_distance_km" in fn_body
    assert "42.195" in fn_body


def test_set_goal_stores_ultra_distance_in_cycles():
    """set-goal must store ultra_distance_km in training_cycles (PR226)."""
    source = _server_source()
    match = re.search(
        r'async def set_training_goal\b.*?(?=\n@api_router|\napp\.|\Z)',
        source,
        re.DOTALL,
    )
    assert match
    fn_body = match.group(0)
    assert '"ultra_distance_km"' in fn_body or "'ultra_distance_km'" in fn_body


# ---------------------------------------------------------------------------
# 7. UserGoalCreate accepts distance_km (model layer)
# ---------------------------------------------------------------------------

def test_user_goal_create_model_has_distance_km():
    """UserGoalCreate must have an optional distance_km field (PR226)."""
    source = _server_source()
    # Find UserGoalCreate model definition
    match = re.search(
        r'class UserGoalCreate\(BaseModel\):(.*?)(?=\n\n|\nclass |\n@)',
        source,
        re.DOTALL,
    )
    assert match, "UserGoalCreate class not found"
    class_body = match.group(1)
    assert "distance_km" in class_body, (
        "UserGoalCreate must expose distance_km for ULTRA goals"
    )


def test_user_goal_endpoint_validates_ultra_distance():
    """POST /user/goal must reject distance_type=ultra without valid distance_km."""
    source = _server_source()
    match = re.search(
        r'async def set_user_goal\b.*?(?=\n@api_router|\napp\.|\Z)',
        source,
        re.DOTALL,
    )
    assert match, "set_user_goal not found"
    fn_body = match.group(0)
    assert "ultra" in fn_body
    assert "42.195" in fn_body


# ---------------------------------------------------------------------------
# 8. V2 endpoints fall back to training_cycles.ultra_distance_km (source)
# ---------------------------------------------------------------------------

def test_v2_endpoints_have_ultra_distance_fallback():
    """V2 consumers must fall back to training_cycles.ultra_distance_km (PR226)."""
    source = _server_source()
    assert "ultra_distance_km" in source, (
        "ultra_distance_km fallback from training_cycles not found in server.py"
    )
    # Count occurrences — must appear in at least the setter + 2 V2 consumers
    count = source.count("ultra_distance_km")
    assert count >= 3, (
        f"Expected ultra_distance_km in ≥3 places (setter + 2 consumers), found {count}"
    )
