from __future__ import annotations

import inspect

import coach_service


def test_generate_dynamic_training_plan_removed():
    source = inspect.getsource(coach_service)
    assert "generate_dynamic_training_plan" not in source


def test_no_generate_cycle_week_import_in_coach_service():
    source = inspect.getsource(coach_service)
    assert "generate_cycle_week" not in source
