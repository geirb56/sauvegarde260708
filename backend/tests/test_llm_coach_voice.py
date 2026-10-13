"""Presentation contracts sent to the LLM, not guarantees about generated prose."""

import json
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest

import llm_coach


def test_selected_workout_initial_style_contract():
    context = {"workout_detail": {"id": "w1"}}
    directive = llm_coach._build_response_style_directive(context, [])
    for instruction in (
        "MODE: selected_workout_initial",
        "Takeaway first",
        "3-5 sentences",
        "60-110 words",
        "at most 2-3 numerical facts",
        "including comparison figures",
        "Prioritize comparison.similar",
        "At most one caveat",
        "Secondary metrics",
        "materially change the answer or are requested",
        "No report-like exhaustive recap",
    ):
        assert instruction in directive


def test_selected_workout_followup_style_contract():
    directive = llm_coach._build_response_style_directive(
        {"workout_detail": {"id": "w1"}},
        [{"role": "assistant", "content": "Initial answer"}],
    )
    for instruction in (
        "MODE: selected_workout_followup",
        "Answer the current question directly",
        "1-3 sentences",
        "Do not recap the full workout",
        "Do not repeat an already established caveat",
        "keep all physiological restrictions",
    ):
        assert instruction in directive
    assert "MODE: selected_workout_initial" not in directive


@pytest.mark.parametrize("context, mode", [
    ({}, "general"),
    ({"workout_detail": None}, "general"),
    ({"today": {"canonical": {"type": "rest"}}}, "current_training"),
    ({"current_week_sessions": [{"canonical": {"type": "long_run"}}]}, "current_training"),
])
def test_no_selected_workout_preserves_prescription(context, mode):
    directive = llm_coach._build_response_style_directive(context, [])
    assert f"MODE: {mode}" in directive
    assert "Training V2 remains authoritative internally" in directive
    assert "never replace the served prescription or offer an alternative" in directive
    assert "type, distance, pace, day or adaptation" in directive
    if mode == "current_training":
        assert "exact served prescription first" in directive
        assert "Never decide an adaptation yourself" in directive
    else:
        assert "2-5 sentences" in directive
        assert "not every context section" in directive


@pytest.mark.asyncio
@pytest.mark.parametrize("language, language_name", [
    ("fr", "French (français)"), ("en", "English"), ("es", "Spanish (español)"),
])
@pytest.mark.parametrize("mode", ["selected_workout_initial", "selected_workout_followup", "current_training", "general"])
async def test_final_prompt_keeps_grounding_and_language(language, language_name, mode):
    context = {"language": language}
    history = []
    if mode.startswith("selected_workout"):
        context.update({
            "workout_detail": {"id": "w1", "avg_pace_display": "6:48/km"},
            "selected_workout_permissions": {
                "intensity_interpretation_allowed": False,
                "raw_hr_is_descriptive_only": True,
                "raw_pace_is_descriptive_only": True,
                "progress_regression_allowed": False,
                "physiological_efficiency_allowed": False,
                "causal_explanation_allowed": False,
                "similar_comparable": False,
            },
        })
        if mode.endswith("followup"):
            history = [{"role": "assistant", "content": "Initial answer"}]
    elif mode == "current_training":
        context["today"] = {"canonical": {"type": "rest"}}
    original = deepcopy(context)
    call = AsyncMock(return_value=("mock answer", True, {}))
    with patch("llm_coach._call_gpt", call):
        await llm_coach.enrich_chat_response("What matters most?", context, history)
    system, prompt, _, _ = call.call_args.args
    assert context == original
    assert json.dumps(context, ensure_ascii=False, separators=(",", ":")) in prompt
    assert f"MODE: {mode}" in prompt
    for text in (system, prompt):
        assert f"Write your ENTIRE response in {language_name}" in text
        assert "Use pace display strings verbatim" in text
        assert "intensity_interpretation_allowed is false" in text
        assert "progress, regression" in text
        assert "physiological efficiency" in text
    assert "do not infer effort labels, zones, efficiency, progress, regression, or causes" in prompt
    assert "they do not establish the athlete's historical state on a selected workout date" in prompt
    assert "do not invent a prescription or alter the served prescription" in prompt
    assert "unless the athlete explicitly asks a technical question" in prompt
    assert "at most one natural caveat" in prompt
