"""PR #128 — coach/training context legacy load cleanup."""

from __future__ import annotations

import sys
from pathlib import Path

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

def test_legacy_training_load_engine_removed():
    assert not (_BACKEND / "engine" / "training_load_engine.py").exists()
