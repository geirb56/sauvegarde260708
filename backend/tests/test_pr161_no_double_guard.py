from __future__ import annotations

import inspect

import llm_coach


def test_llm_module_no_legacy_plan_engine_symbols():
    source = inspect.getsource(llm_coach)
    for symbol in (
        "compute_target_km",
        "apply_resume_guard",
        "build_reprise_week_structure",
        "REPRISE_DEEP_SESSION_MINUTES",
        "reprise_deep_durations",
        "reprise_durations",
        "VOLUME_GOAL_CONFIG",
    ):
        assert symbol not in source
