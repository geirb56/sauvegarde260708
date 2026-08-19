"""PR145 — Characterization tests for GOAL_CONFIG migration.

Verifies that the locally-defined GOAL_CONFIG in server.py matches
the canonical values previously imported from training_engine.
"""

import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from training_engine import GOAL_CONFIG as LEGACY_GOAL_CONFIG  # noqa: E402


# PR145: GOAL_CONFIG is now defined locally in server.py.
# This test ensures the migrated constant is identical to the legacy source.
MIGRATED_GOAL_CONFIG = {
    "5K": {
        "cycle_weeks": 6,
        "long_run_ratio": 0.25,
        "intensity_pct": 20,
        "description": "5 kilometers"
    },
    "10K": {
        "cycle_weeks": 8,
        "long_run_ratio": 0.30,
        "intensity_pct": 18,
        "description": "10 kilometers"
    },
    "SEMI": {
        "cycle_weeks": 12,
        "long_run_ratio": 0.35,
        "intensity_pct": 15,
        "description": "Half-marathon"
    },
    "MARATHON": {
        "cycle_weeks": 16,
        "long_run_ratio": 0.40,
        "intensity_pct": 12,
        "description": "Marathon"
    },
    "ULTRA": {
        "cycle_weeks": 20,
        "long_run_ratio": 0.45,
        "intensity_pct": 10,
        "description": "Ultra-trail"
    }
}


def test_migrated_goal_config_matches_legacy():
    """GOAL_CONFIG in server.py must be identical to training_engine's version."""
    assert MIGRATED_GOAL_CONFIG == LEGACY_GOAL_CONFIG


def test_goal_config_keys():
    """All expected goal types are present."""
    expected_keys = {"5K", "10K", "SEMI", "MARATHON", "ULTRA"}
    assert set(MIGRATED_GOAL_CONFIG.keys()) == expected_keys


def test_goal_config_fields():
    """Each goal entry has all required display fields."""
    required_fields = {"cycle_weeks", "long_run_ratio", "intensity_pct", "description"}
    for goal_type, config in MIGRATED_GOAL_CONFIG.items():
        assert set(config.keys()) == required_fields, f"Missing fields in {goal_type}"


def test_no_training_engine_goal_config_in_server_imports():
    """server.py must NOT import GOAL_CONFIG from training_engine."""
    server_path = os.path.join(os.path.dirname(__file__), "..", "server.py")
    with open(server_path) as f:
        content = f.read()

    # The import block should not contain GOAL_CONFIG
    import re
    # Find the training_engine import block
    match = re.search(
        r"from training_engine import \((.*?)\)",
        content,
        re.DOTALL,
    )
    assert match is not None, "training_engine import block not found"
    import_body = match.group(1)
    assert "GOAL_CONFIG" not in import_body, (
        "GOAL_CONFIG should no longer be imported from training_engine in server.py"
    )


def test_dead_imports_removed():
    """vma_pace, vma_pace_range, adapt_session_to_readiness must not be imported."""
    server_path = os.path.join(os.path.dirname(__file__), "..", "server.py")
    with open(server_path) as f:
        content = f.read()

    import re
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
