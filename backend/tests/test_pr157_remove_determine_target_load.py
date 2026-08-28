from __future__ import annotations

import inspect

import coach_service


def test_generate_dynamic_training_plan_stays_v2_only():
    names = set(coach_service.generate_dynamic_training_plan.__code__.co_names)
    forbidden = {
        "determine_target_load",
        "compute_target_km",
        "apply_resume_guard",
        "build_reprise_week_structure",
        "reprise_durations",
        "reprise_deep_durations",
    }
    assert forbidden.isdisjoint(names)


def test_no_generate_cycle_week_import_in_coach_service():
    source = inspect.getsource(coach_service)
    assert "generate_cycle_week" not in source
