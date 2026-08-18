"""PR138 — architecture guards for the extracted performance module."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


REPO_BACKEND = Path(__file__).resolve().parents[1]
DECISION_MODULES = [
    REPO_BACKEND / "training_v2" / "training_state.py",
    REPO_BACKEND / "training_v2" / "weekly_target.py",
    REPO_BACKEND / "training_v2" / "weekly_reconciliation.py",
    REPO_BACKEND / "training_v2" / "readiness_decision.py",
    REPO_BACKEND / "training_v2" / "daily_adaptation.py",
]


@pytest.mark.parametrize("module_path", DECISION_MODULES)
def test_decision_modules_do_not_import_performance(module_path: Path):
    source = module_path.read_text()
    assert "training_v2.performance" not in source
    assert "from .performance import" not in source
    assert "from training_v2 import vma_pace" not in source
    assert "from training_v2 import vma_pace_range" not in source


def test_training_v2_public_namespace_does_not_expose_legacy_performance_api():
    import training_v2

    assert not hasattr(training_v2, "DEFAULT_COMPATIBILITY_VMA_KMH")
    assert not hasattr(training_v2, "build_legacy_performance_compatibility")
