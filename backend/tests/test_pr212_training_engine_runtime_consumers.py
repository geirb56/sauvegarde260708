from __future__ import annotations

import ast
from pathlib import Path


_BACKEND = Path(__file__).resolve().parents[1]
_SERVER = _BACKEND / "server.py"
_ACCESS_CONTROL = _BACKEND / "access_control.py"
_SUBSCRIPTION_MANAGER = _BACKEND / "subscription_manager.py"


def _runtime_python_files() -> list[Path]:
    return sorted(
        path for path in _BACKEND.rglob("*.py")
        if path.name != "training_engine.py"
        and "tests" not in path.parts
    )


def _training_engine_import_count(path: Path) -> int:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    count = 0
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            count += sum(1 for alias in node.names if alias.name == "training_engine")
        elif isinstance(node, ast.ImportFrom):
            if node.module == "training_engine":
                count += 1
    return count


def test_training_engine_runtime_consumers_zero():
    training_engine_runtime_consumers = sum(
        _training_engine_import_count(path)
        for path in _runtime_python_files()
    )
    assert training_engine_runtime_consumers == 0


def test_server_training_engine_imports_zero():
    server_imports = _training_engine_import_count(_SERVER)
    assert server_imports == 0


def test_legacy_full_cycle_runtime_consumers_zero():
    assert '"/training/full-cycle"' not in _SERVER.read_text(encoding="utf-8")
    assert "/api/training/full-cycle" not in _ACCESS_CONTROL.read_text(encoding="utf-8")
    assert "/api/training/full-cycle" not in _SUBSCRIPTION_MANAGER.read_text(encoding="utf-8")
