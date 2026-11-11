"""C418: the chat prompt is short and direct; no presentation directive or duplicated guards."""

import json
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest

import llm_coach


@pytest.mark.asyncio
@pytest.mark.parametrize("language, language_name", [
    ("fr", "French (français)"), ("en", "English"), ("es", "Spanish (español)"),
])
@pytest.mark.parametrize("context", [
    {},
    {"workout_detail": {"id": "w1", "avg_pace_display": "6:48/km"},
     "selected_workout_permissions": {"intensity_interpretation_allowed": False}},
    {"today": {"canonical": {"type": "rest"}}},
])
async def test_final_prompt_keeps_grounding_and_language(language, language_name, context):
    context = {**context, "language": language}
    original = deepcopy(context)
    call = AsyncMock(return_value=("mock answer", True, {}))
    with patch("llm_coach._call_gpt", call):
        await llm_coach.enrich_chat_response("What matters most?", context, [])
    system, prompt, _, kind = call.call_args.args
    assert kind == "chat" and context == original
    assert json.dumps(context, ensure_ascii=False, separators=(",", ":")) in prompt
    for text in (system, prompt):
        assert f"Write your ENTIRE response in {language_name}" in text
    for guard in ("sans créer de nouvelle prescription", "selected_workout_permissions",
                  "ce qui est mesuré, ce qui est plausible et ce qui reste inconnu"):
        assert guard in system
    assert "MODE:" not in prompt and "PRESENTATION" not in prompt
    assert "What matters most?" in prompt


def test_prompt_is_short_and_has_no_redundant_layers():
    assert len(llm_coach.SYSTEM_PROMPT_COACH) < 3500
    assert "deux à quatre phrases" in llm_coach.SYSTEM_PROMPT_COACH
    assert "question finale artificielle" not in llm_coach.SYSTEM_PROMPT_COACH
