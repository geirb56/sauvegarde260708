from __future__ import annotations

import ast
from pathlib import Path

def test_runtime_week_plan_path_does_not_call_generate_cycle_week():
    source = Path(__file__).resolve().parent.parent.joinpath("server.py").read_text(encoding="utf-8")
    tree = ast.parse(source)
    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            if isinstance(node.func, ast.Name) and node.func.id == "generate_cycle_week":
                calls.append(node.lineno)
            if isinstance(node.func, ast.Attribute) and node.func.attr == "generate_cycle_week":
                calls.append(node.lineno)
    assert not calls
