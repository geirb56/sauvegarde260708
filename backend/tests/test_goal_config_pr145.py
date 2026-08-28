"""PR145/PR146 — GOAL_CONFIG single source of truth tests.

Verifies that config.training_goals.GOAL_CONFIG is the unique definition
and that training_engine.py no longer contains a copy.
"""

import ast
import sys
import os
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.training_goals import GOAL_CONFIG  # noqa: E402


# ------------------------------------------------------------------
# 1. GOAL_CONFIG exists and has expected goals
# ------------------------------------------------------------------

def test_goal_config_exists():
    """config.training_goals.GOAL_CONFIG must exist and be a dict."""
    assert isinstance(GOAL_CONFIG, dict)


def test_goal_config_keys():
    """All expected goal types are present."""
    expected_keys = {"5K", "10K", "SEMI", "MARATHON", "ULTRA"}
    assert set(GOAL_CONFIG.keys()) == expected_keys


# ------------------------------------------------------------------
# 2. Contractual fields
# ------------------------------------------------------------------

def test_goal_config_fields():
    """Each goal entry has all required display fields."""
    required_fields = {"cycle_weeks", "long_run_ratio", "intensity_pct", "description"}
    for goal_type, config in GOAL_CONFIG.items():
        assert set(config.keys()) == required_fields, f"Missing fields in {goal_type}"


# ------------------------------------------------------------------
# 3-4. server.py imports from config.training_goals
# ------------------------------------------------------------------

def test_server_imports_from_config_training_goals():
    """server.py must import GOAL_CONFIG from config.training_goals."""
    server_path = os.path.join(os.path.dirname(__file__), "..", "server.py")
    with open(server_path) as f:
        content = f.read()

    assert "from config.training_goals import GOAL_CONFIG" in content, (
        "server.py must import GOAL_CONFIG from config.training_goals"
    )


# ------------------------------------------------------------------
# 5. server.py does not define GOAL_CONFIG locally
# ------------------------------------------------------------------

def test_server_does_not_define_goal_config():
    """server.py must not define GOAL_CONFIG as a local variable."""
    server_path = os.path.join(os.path.dirname(__file__), "..", "server.py")
    with open(server_path) as f:
        content = f.read()

    # Check for top-level assignment (GOAL_CONFIG = {...)
    assert not re.search(r"^GOAL_CONFIG\s*=\s*\{", content, re.MULTILINE), (
        "server.py must not define GOAL_CONFIG locally"
    )


# ------------------------------------------------------------------
# 6. server.py does not import GOAL_CONFIG from training_engine
# ------------------------------------------------------------------

def test_server_no_goal_config_from_training_engine():
    """server.py must not import anything from training_engine."""
    server_path = os.path.join(os.path.dirname(__file__), "..", "server.py")
    with open(server_path) as f:
        content = f.read()

    assert "from training_engine import" not in content
    assert "import training_engine" not in content


# ------------------------------------------------------------------
# 7. training_engine.py no longer defines GOAL_CONFIG (PR146)
# ------------------------------------------------------------------

def test_training_engine_no_goal_config():
    """training_engine.py must not contain a GOAL_CONFIG definition."""
    engine_path = os.path.join(os.path.dirname(__file__), "..", "training_engine.py")
    with open(engine_path) as f:
        tree = ast.parse(f.read())

    for node in ast.walk(tree):
        if isinstance(node, ast.Assign):
            for target in node.targets:
                if isinstance(target, ast.Name) and target.id == "GOAL_CONFIG":
                    raise AssertionError(
                        "training_engine.py still defines GOAL_CONFIG — "
                        "the orphaned copy should have been removed in PR146"
                    )


# ------------------------------------------------------------------
# Preserved from PR145: dead imports check
# ------------------------------------------------------------------

def test_dead_imports_removed():
    """Legacy training_engine imports must be fully removed from server.py."""
    server_path = os.path.join(os.path.dirname(__file__), "..", "server.py")
    with open(server_path) as f:
        content = f.read()

    assert "from training_engine import" not in content
    assert "import training_engine" not in content
