from __future__ import annotations

import inspect

import server


def test_runtime_week_plan_path_does_not_call_generate_cycle_week():
    source = inspect.getsource(server.get_week_plan)
    assert "generate_cycle_week" not in source
