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
    assert len(llm_coach.SYSTEM_PROMPT_COACH) < 5500
    assert "deux à quatre phrases" in llm_coach.SYSTEM_PROMPT_COACH
    assert "question finale artificielle" not in llm_coach.SYSTEM_PROMPT_COACH


def test_c422_prompt_targets_c421_schema_and_conversational_behaviour():
    p = llm_coach.SYSTEM_PROMPT_COACH
    for field in ("recorded_structure", "inferred_structure", "validated_comparisons",
                  "scientific_permissions", "allowed_conclusions", "material_limitations"):
        assert field in p
    for fragment in ("Commence par répondre à sa vraie question", "Tutoie", "une seule précaution pertinente",
                     "refuse seulement cette conclusion", "ne résume pas une séance fractionnée par sa seule allure moyenne",
                     "jamais une séance programmée"):
        assert fragment in p
    assert "Ne modifie ni les allures ni les prescriptions" in p


def test_c422_fix_allowed_conclusions_scope_and_structure_priority():
    p = llm_coach.SYSTEM_PROMPT_COACH
    assert "n'énonce que des conclusions de allowed_conclusions" not in p
    for fragment in ("Seules les conclusions V3 listées dans allowed_conclusions",
                     "une liste vide ne t'empêche pas d'expliquer",
                     "sans diagnostic physiologique, sans causalité inventée et sans prescription personnalisée",
                     "recorded_by_garmin", "pattern_observed",
                     "recorded_unclassified n'est qu'une information descriptive et ne masque pas un motif inféré fiable",
                     "sans structure exploitable, n'en invente aucune"):
        assert fragment in p
    for guard in ("scientific_permissions", "selected_workout_permissions", "N'invente ni seuils (LT1/LT2)"):
        assert guard in p
