"""PR145 — Characterization tests for GOAL_CONFIG migration.

Verifies that config.training_goals.GOAL_CONFIG is the single source of truth
and that server.py uses it (not a local copy or training_engine).
"""

import sys
import os
import re

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from config.training_goals import GOAL_CONFIG  # noqa: E402
from training_engine import GOAL_CONFIG as LEGACY_GOAL_CONFIG  # noqa: E402


def test_goal_config_matches_legacy():
    """config.training_goals.GOAL_CONFIG must match training_engine's version."""
    assert GOAL_CONFIG == LEGACY_GOAL_CONFIG


def test_goal_config_keys():
    """All expected goal types are present."""
    expected_keys = {"5K", "10K", "SEMI", "MARATHON", "ULTRA"}
    assert set(GOAL_CONFIG.keys()) == expected_keys


def test_goal_config_fields():
    """Each goal entry has all required display fields."""
    required_fields = {"cycle_weeks", "long_run_ratio", "intensity_pct", "description"}
    for goal_type, config in GOAL_CONFIG.items():
        assert set(config.keys()) == required_fields, f"Missing fields in {goal_type}"


def test_server_imports_from_config_training_goals():
    """server.py must import GOAL_CONFIG from config.training_goals, not training_engine."""
    server_path = os.path.join(os.path.dirname(__file__), "..", "server.py")
    with open(server_path) as f:
        content = f.read()

    # Must import from config.training_goals
    assert "from config.training_goals import GOAL_CONFIG" in content, (
        "server.py must import GOAL_CONFIG from config.training_goals"
    )

    # Must NOT import from training_engine
    match = re.search(
        r"from training_engine import \((.*?)\)",
        content,
        re.DOTALL,
    )
    assert match is not None, "training_engine import block not found"
    import_body = match.group(1)
    assert "GOAL_CONFIG" not in import_body, (
        "GOAL_CONFIG should not be in training_engine import block"
    )


def test_dead_imports_removed():
    """vma_pace, vma_pace_range, adapt_session_to_readiness must not be imported."""
    server_path = os.path.join(os.path.dirname(__file__), "..", "server.py")
    with open(server_path) as f:
        content = f.read()

    match = re.search(
        r"from training_engine import \((.*?)\)",
        content,
        re.DOTALL,
    )
    assert match is not None
    import_body = match.group(1)
    for symbol in ["vma_pace", "vma_pace_range", "adapt_session_to_readiness"]:
        assert symbol not in import_body, (
            f"Dead import '{symbol}' should be removed from training_engine imports"
        )
