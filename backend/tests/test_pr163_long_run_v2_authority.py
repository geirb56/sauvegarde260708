from __future__ import annotations

import inspect

import llm_coach


def test_llm_layer_no_long_run_legacy_planner():
    source = inspect.getsource(llm_coach)
    assert "long_run_km_v2" not in source
    assert "generate_cycle_week" not in source
