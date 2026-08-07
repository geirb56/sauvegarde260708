"""PR05 — Tests for PlanGoal.

Tests 01–27: required PlanGoal cases.
Tests nr_*: non-regression / py_compile checks.
Total: 29 tests.
"""

import importlib
import sys
from datetime import date

import pytest
from pydantic import ValidationError

from training_v2 import GoalType, PlanGoal, build_plan_goal


# ---------------------------------------------------------------------------
# 1. maintenance valid without date/distance/chrono
# ---------------------------------------------------------------------------

def test_01_maintenance_valid_no_extras():
    g = build_plan_goal(goal_type="maintenance")
    assert g.goal_type == GoalType.maintenance
    assert g.race_date is None
    assert g.target_time_seconds is None
    assert g.target_distance_km is None


# ---------------------------------------------------------------------------
# 2. maintenance refuses a chrono
# ---------------------------------------------------------------------------

def test_02_maintenance_refuses_chrono():
    with pytest.raises(ValidationError):
        build_plan_goal(goal_type="maintenance", target_time_seconds=1800)


# ---------------------------------------------------------------------------
# 3. maintenance refuses a race_date
# ---------------------------------------------------------------------------

def test_03_maintenance_refuses_race_date():
    with pytest.raises(ValidationError):
        build_plan_goal(goal_type="maintenance", race_date=date(2025, 10, 12))


# ---------------------------------------------------------------------------
# 4. maintenance refuses a target_distance
# ---------------------------------------------------------------------------

def test_04_maintenance_refuses_target_distance():
    with pytest.raises(ValidationError):
        build_plan_goal(goal_type="maintenance", target_distance_km=10.0)


# ---------------------------------------------------------------------------
# 5. 5k produces exactly 5.0
# ---------------------------------------------------------------------------

def test_05_5k_canonical_distance():
    g = build_plan_goal(goal_type="5k")
    assert g.target_distance_km == 5.0


# ---------------------------------------------------------------------------
# 6. 10k produces exactly 10.0
# ---------------------------------------------------------------------------

def test_06_10k_canonical_distance():
    g = build_plan_goal(goal_type="10k")
    assert g.target_distance_km == 10.0


# ---------------------------------------------------------------------------
# 7. half_marathon produces exactly 21.0975
# ---------------------------------------------------------------------------

def test_07_half_marathon_canonical_distance():
    g = build_plan_goal(goal_type="half_marathon")
    assert g.target_distance_km == 21.0975


# ---------------------------------------------------------------------------
# 8. marathon produces exactly 42.195
# ---------------------------------------------------------------------------

def test_08_marathon_canonical_distance():
    g = build_plan_goal(goal_type="marathon")
    assert g.target_distance_km == 42.195


# ---------------------------------------------------------------------------
# 8b. standard distance goal rejects caller-provided target_distance_km
# ---------------------------------------------------------------------------

def test_08b_standard_rejects_caller_distance_5k():
    with pytest.raises(ValueError):
        build_plan_goal(goal_type="5k", target_distance_km=5.0)


def test_08b_standard_rejects_caller_distance_10k():
    with pytest.raises(ValueError):
        build_plan_goal(goal_type="10k", target_distance_km=10.0)


def test_08b_standard_rejects_caller_distance_half():
    with pytest.raises(ValueError):
        build_plan_goal(goal_type="half_marathon", target_distance_km=21.0975)


def test_08b_standard_rejects_caller_distance_marathon():
    with pytest.raises(ValueError):
        build_plan_goal(goal_type="marathon", target_distance_km=42.195)


def test_08b_standard_rejects_wrong_distance_10k():
    with pytest.raises(ValueError):
        build_plan_goal(goal_type="10k", target_distance_km=15.0)


# ---------------------------------------------------------------------------
# 9. chrono without race_date accepted
# ---------------------------------------------------------------------------

def test_09_chrono_without_race_date():
    g = build_plan_goal(goal_type="10k", target_time_seconds=2700)
    assert g.target_time_seconds == 2700
    assert g.race_date is None


# ---------------------------------------------------------------------------
# 10. date without chrono accepted
# ---------------------------------------------------------------------------

def test_10_date_without_chrono():
    g = build_plan_goal(goal_type="10k", race_date=date(2025, 10, 12))
    assert g.race_date == date(2025, 10, 12)
    assert g.target_time_seconds is None


# ---------------------------------------------------------------------------
# 11. date + chrono both accepted
# ---------------------------------------------------------------------------

def test_11_date_and_chrono():
    g = build_plan_goal(
        goal_type="10k",
        target_time_seconds=2700,
        race_date=date(2025, 10, 12),
    )
    assert g.target_time_seconds == 2700
    assert g.race_date == date(2025, 10, 12)


# ---------------------------------------------------------------------------
# 12. neither date nor chrono accepted for a standard distance
# ---------------------------------------------------------------------------

def test_12_neither_date_nor_chrono():
    g = build_plan_goal(goal_type="marathon")
    assert g.target_time_seconds is None
    assert g.race_date is None


# ---------------------------------------------------------------------------
# 13. ultra 50 km accepted
# ---------------------------------------------------------------------------

def test_13_ultra_50km():
    g = build_plan_goal(goal_type="ultra", target_distance_km=50.0)
    assert g.goal_type == GoalType.ultra
    assert g.target_distance_km == 50.0


# ---------------------------------------------------------------------------
# 14. ultra 100 km accepted
# ---------------------------------------------------------------------------

def test_14_ultra_100km():
    g = build_plan_goal(goal_type="ultra", target_distance_km=100.0)
    assert g.target_distance_km == 100.0


# ---------------------------------------------------------------------------
# 15. ultra 42.195 km refused (must be strictly greater)
# ---------------------------------------------------------------------------

def test_15_ultra_exactly_marathon_refused():
    with pytest.raises(ValidationError):
        build_plan_goal(goal_type="ultra", target_distance_km=42.195)


# ---------------------------------------------------------------------------
# 16. ultra < 42.195 km refused
# ---------------------------------------------------------------------------

def test_16_ultra_below_marathon_refused():
    with pytest.raises(ValidationError):
        build_plan_goal(goal_type="ultra", target_distance_km=30.0)


# ---------------------------------------------------------------------------
# 17. ultra without distance refused
# ---------------------------------------------------------------------------

def test_17_ultra_no_distance_refused():
    with pytest.raises(ValidationError):
        build_plan_goal(goal_type="ultra")


# ---------------------------------------------------------------------------
# 18. ultra without chrono accepted
# ---------------------------------------------------------------------------

def test_18_ultra_without_chrono():
    g = build_plan_goal(goal_type="ultra", target_distance_km=55.0)
    assert g.target_time_seconds is None


# ---------------------------------------------------------------------------
# 19. ultra without date accepted
# ---------------------------------------------------------------------------

def test_19_ultra_without_date():
    g = build_plan_goal(goal_type="ultra", target_distance_km=55.0)
    assert g.race_date is None


# ---------------------------------------------------------------------------
# 20. target_time_seconds = 0 refused
# ---------------------------------------------------------------------------

def test_20_zero_chrono_refused():
    with pytest.raises(ValidationError):
        build_plan_goal(goal_type="10k", target_time_seconds=0)


# ---------------------------------------------------------------------------
# 21. negative target_time_seconds refused
# ---------------------------------------------------------------------------

def test_21_negative_chrono_refused():
    with pytest.raises(ValidationError):
        build_plan_goal(goal_type="10k", target_time_seconds=-100)


# ---------------------------------------------------------------------------
# 22. extremely ambitious chrono accepted structurally
# ---------------------------------------------------------------------------

def test_22_ambitious_chrono_accepted():
    # marathon in 2h30 → 9000 seconds
    g = build_plan_goal(goal_type="marathon", target_time_seconds=9000)
    assert g.target_time_seconds == 9000


# ---------------------------------------------------------------------------
# 23. provenance "user"
# ---------------------------------------------------------------------------

def test_23_provenance_user():
    g = build_plan_goal(goal_type="10k")
    assert g.created_from == "user"


# ---------------------------------------------------------------------------
# 24. default objective: maintenance + created_from=default
# ---------------------------------------------------------------------------

def test_24_default_maintenance():
    g = build_plan_goal(goal_type="maintenance", created_from="default")
    assert g.goal_type == GoalType.maintenance
    assert g.created_from == "default"


# ---------------------------------------------------------------------------
# 25. model is immutable
# ---------------------------------------------------------------------------

def test_25_model_immutable():
    g = build_plan_goal(goal_type="10k")
    with pytest.raises(Exception):
        g.target_time_seconds = 1000  # type: ignore[misc]


# ---------------------------------------------------------------------------
# 26. identical calls produce identical results
# ---------------------------------------------------------------------------

def test_26_deterministic():
    kwargs = dict(
        goal_type="marathon",
        target_time_seconds=14400,
        race_date=date(2025, 4, 6),
    )
    g1 = build_plan_goal(**kwargs)
    g2 = build_plan_goal(**kwargs)
    assert g1 == g2


# ---------------------------------------------------------------------------
# 27. no legacy imports
# ---------------------------------------------------------------------------

def test_27_no_legacy_imports():
    import training_v2.plan_goal as pg_module

    forbidden = {
        "training_engine",
        "training_load_engine",
        "llm_coach",
        "coach_service",
    }
    for name in list(pg_module.__dict__.keys()) + list(sys.modules.keys()):
        assert name not in forbidden, f"Forbidden legacy module imported: {name}"

    # Also verify by inspecting the source
    import inspect

    source = inspect.getsource(pg_module)
    for module in forbidden:
        assert f"import {module}" not in source


# ---------------------------------------------------------------------------
# Non-regression: py_compile on new modules
# ---------------------------------------------------------------------------

def test_nr_py_compile_plan_goal():
    import py_compile
    import training_v2.plan_goal as pg

    py_compile.compile(pg.__file__, doraise=True)


def test_nr_exports():
    """All expected symbols are exported from training_v2."""
    import training_v2

    assert hasattr(training_v2, "PlanGoal")
    assert hasattr(training_v2, "GoalType")
    assert hasattr(training_v2, "build_plan_goal")
    # PR04 symbols still present
    assert hasattr(training_v2, "TrainingState")
    assert hasattr(training_v2, "build_training_state")
