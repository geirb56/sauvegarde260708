from __future__ import annotations

import ast
from pathlib import Path

import llm_coach


def test_generate_cycle_week_removed_from_llm_coach():
    assert not hasattr(llm_coach, "generate_cycle_week")


def test_llm_coach_has_no_training_engine_import():
    source = Path(llm_coach.__file__).read_text(encoding="utf-8")
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.ImportFrom):
            assert node.module != "training_engine"
