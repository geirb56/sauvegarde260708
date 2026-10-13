from __future__ import annotations

import ast
from pathlib import Path


_BACKEND = Path(__file__).resolve().parents[1]
_SERVER = _BACKEND / "server.py"
_ACCESS_CONTROL = _BACKEND / "access_control.py"
_SUBSCRIPTION_MANAGER = _BACKEND / "subscription_manager.py"
_TRAINING_ENGINE_FILE = _BACKEND / "training_engine.py"


def _python_files(*, include_tests: bool) -> list[Path]:
    return sorted(
        path
        for path in _BACKEND.rglob("*.py")
        if path != _TRAINING_ENGINE_FILE
        and (include_tests or "tests" not in path.parts)
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


def _total_imports(*, include_tests: bool) -> int:
    return sum(
        _training_engine_import_count(path)
        for path in _python_files(include_tests=include_tests)
    )


def test_training_engine_file_absent():
    assert not _TRAINING_ENGINE_FILE.exists()


def test_training_engine_runtime_imports_zero():
    assert _total_imports(include_tests=False) == 0


def test_training_engine_test_imports_zero():
    test_imports = sum(
        _training_engine_import_count(path)
        for path in _python_files(include_tests=True)
        if "tests" in path.parts
    )
    assert test_imports == 0


def test_server_training_engine_imports_zero():
    server_imports = _training_engine_import_count(_SERVER)
    assert server_imports == 0


def test_legacy_full_cycle_runtime_consumers_zero():
    assert '"/training/full-cycle"' not in _SERVER.read_text(encoding="utf-8")
    assert "/api/training/full-cycle" not in _ACCESS_CONTROL.read_text(encoding="utf-8")
    assert "/api/training/full-cycle" not in _SUBSCRIPTION_MANAGER.read_text(encoding="utf-8")
