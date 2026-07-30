import importlib

import pytest

import demo_mode


def _reload_demo_mode(monkeypatch, environment: str, demo_mode_value: str):
    monkeypatch.setenv("ENVIRONMENT", environment)
    monkeypatch.setenv("DEMO_MODE", demo_mode_value)
    importlib.reload(demo_mode)


def test_demo_mode_forbidden_in_production(monkeypatch):
    _reload_demo_mode(monkeypatch, "production", "true")
    with pytest.raises(RuntimeError):
        demo_mode.validate_demo_mode_safety()


def test_demo_mode_allowed_in_development(monkeypatch):
    _reload_demo_mode(monkeypatch, "development", "true")
    demo_mode.validate_demo_mode_safety()

