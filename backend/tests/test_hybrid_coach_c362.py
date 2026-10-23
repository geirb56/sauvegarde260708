"""C362 offline regressions using the unchanged seven C360/C361 fixtures."""

from copy import deepcopy
import json

import pytest

import hybrid_coach_c359 as hybrid
from test_hybrid_coach_c359 import CASES, _access, _context, _facts, _provider, _run, synthetic_case
from workout_intelligence_v3_models import WIV3PrescriptionAssessment


DIRECT_TEXT = {
    "easy": "Ta FC moyenne est de 140 bpm, sous ton LT1 de 150 bpm.",
    "long": "100 min de course, contre 50 min habituellement.",
    "intervals_4x4": "Garmin a enregistré 4 phases d'effort et 3 phases de récupération.",
    "sparse": "Les données disponibles ne permettent pas de qualifier cette séance.",
    "treadmill": "Ta FC moyenne est de 140 bpm, sous ton LT1 de 150 bpm.",
    "comparable_history": (
        "À FC comparable, la variation médiane d'allure est de -24 s/km "
        "entre les périodes comparées. Ce n'est pas une preuve de changement de forme."
    ),
    "no_physiology": "Ta FC moyenne est de 140 bpm.",
}


@pytest.mark.parametrize("name", CASES)
def test_direct_descriptions_need_no_recital_of_unused_caveats(name, monkeypatch):
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    v3 = synthetic_case(name)
    before = deepcopy(v3.model_dump())
    result = _run(
        v3, permissions=hybrid.HybridPermissions(history=True),
        transport=_provider(lambda *_: DIRECT_TEXT[name]),
    )
    assert result.mode == "generated_narrative"
    assert result.text == DIRECT_TEXT[name]
    assert v3.model_dump() == before


@pytest.mark.parametrize("language,text", [
    ("fr", "FC moyenne : 140 bpm, sous LT1."),
    ("en", "Average HR: 140 bpm, below LT1."),
    ("es", "FC media: 140 lpm, por debajo de LT1."),
])
def test_equivalent_factual_average_needs_no_literal_disclaimer(language, text):
    assert hybrid.validate_generated_narrative(text, _facts(language=language), language=language)[0]


@pytest.mark.parametrize("text", [
    "Footing facile : 140 bpm de moyenne.",
    "Ta séance est une sortie longue.",
    "Tu as couru une séance tempo.",
    "C'était probablement une séance tempo.",
    "C'était une séance fractionnée.",
    "Probablement une bonne lecture. Footing facile, sans ambiguïté.",
])
def test_no_certain_or_contradictory_classification(text):
    assert not hybrid.validate_generated_narrative(text, _facts())[0]


def test_unknown_classification_cannot_become_probable_easy():
    assert not hybrid.validate_generated_narrative(
        "Tu as probablement fait un footing facile.", _facts(synthetic_case("sparse")),
    )[0]


@pytest.mark.parametrize("text", [
    "Tu construis ta base aérobie.",
    "Cette séance favorise la récupération.",
    "Tu limites le risque de blessure.",
    "Tes efforts portent leurs fruits.",
    "Tu progresses durablement.",
    "Cette séance développe ton endurance.",
    "Cette sortie constitue une récupération active.",
    "This session builds your aerobic base.",
    "Esta sesión favorece la recuperación.",
    "Ta dérive cardiaque confirme une bonne gestion.",
    "Bravo pour cette belle séance !",
    "Continue comme ça !",
    "Keep it up!",
])
def test_generic_benefits_and_encouragement_are_not_session_evidence(text):
    assert not hybrid.validate_generated_narrative(text, _facts())[0]


@pytest.mark.parametrize("text", [
    "Ajoute une séance demain.",
    "Ralentis lors de la prochaine sortie.",
    "Ta FC moyenne est de 140 bpm. Augmente ton volume.",
    "Run tomorrow at the same pace.",
    "Corre mañana para recuperar.",
])
def test_invented_prescriptions_are_rejected_even_without_numeric_values(text):
    assert hybrid.validate_generated_narrative(text, _facts())[1] == "unauthorized_prescription"


@pytest.mark.parametrize("text", [
    "Ta FC moyenne est de 140 km.",
    "Ta FC moyenne est de 150 bpm.",
    "Ta FC moyenne est de 140 bpm, sous ton LT1 de 170 bpm.",
    "Ta FC moyenne est de 140 bpm, avec LT2 = 150 bpm.",
    "Ta FC moyenne de 140 bpm se situe au-dessus de LT2.",
    "Garmin a enregistré 4 min d'effort et 3 min de récupération.",
    "Ta FC moyenne est de 999 bpm.",
])
def test_values_units_and_roles_are_preserved(text):
    facts = _facts(synthetic_case("intervals_4x4")) if text.startswith("Garmin") else _facts()
    assert not hybrid.validate_generated_narrative(text, facts)[0]


@pytest.mark.parametrize("text", [
    "Les répétitions sont régulières.",
    "Les répétitions sont irrégulières.",
    "La régularité est bonne.",
    "La régularité ne peut pas être jugée. Les répétitions sont régulières.",
    "La régularité ne peut pas être jugée, mais les répétitions sont régulières.",
])
def test_absence_of_regularity_authority_never_becomes_a_verdict(text):
    assert hybrid.validate_generated_narrative(
        text, _facts(synthetic_case("intervals_4x4")),
    )[1] == "unsupported_regularity_claim"


def test_rich_pack_contains_only_whitelisted_v3_comparisons_and_metadata():
    permissions = hybrid.HybridPermissions(history=True)
    v3 = synthetic_case("comparable_history")
    packet = _context(v3, permissions=permissions)
    facts = {f["evidence_id"]: f for f in packet["facts"]}
    comparison = facts["comparison.pace"]
    assert comparison["values"]["pace_difference"] == \
        v3.historical_comparison.pace_at_comparable_hr.pace_difference_sec_per_km
    assert comparison["units"]["pace_difference"] == "s/km"
    assert "negative is faster" in comparison["meaning"]["pace_difference"]
    assert comparison["priority"] > facts["session.kind"]["priority"]
    assert "not_proof_of_fitness" in comparison["forbidden_conclusions"]
    for fact in packet["facts"]:
        assert set(fact["values"]) == set(fact["meaning"])
        assert fact["confidence"] and fact["allowed_conclusion"]
    serialized = json.dumps(packet)
    for excluded in ("synthetic-prior", "source_paths", "assertion", "workout_id"):
        assert excluded not in serialized
    assert not any(f.id.startswith("comparison.") for f in _facts(v3))


@pytest.mark.parametrize("status,comparability", [
    ("insufficient", "strong"), ("available", "moderate"),
    ("available", "low"), ("not_applicable", "strong"),
])
def test_comparison_must_be_established_and_strong(status, comparability):
    v3 = synthetic_case("comparable_history")
    v3.historical_comparison.status = status
    v3.historical_comparison.comparability = comparability
    assert not any(f.id.startswith("comparison.") for f in _facts(
        v3, permissions=hybrid.HybridPermissions(history=True),
    ))


def test_unknown_reference_structure_and_nonfinite_delta_are_not_admitted():
    v3 = synthetic_case("comparable_history")
    v3.historical_comparison.pace_at_comparable_hr.pace_difference_sec_per_km = float("nan")
    assert "comparison.pace" not in {f.id for f in _facts(
        v3, permissions=hybrid.HybridPermissions(history=True),
    )}
    v3.historical_comparison.limitations.append("reference_structure_unknown")
    assert not any(f.id.startswith("comparison.") for f in _facts(
        v3, permissions=hybrid.HybridPermissions(history=True),
    ))


@pytest.mark.parametrize("text", [
    "Ton historique confirme une amélioration physiologique.",
    "Ta FC moyenne est de 140 bpm, due à une meilleure efficacité physiologique.",
    "Tes répétitions sont régulières grâce à ton endurance.",
    "Toute la séance était sous LT1.",
])
def test_rich_history_does_not_authorize_new_physiological_conclusions(text):
    assert not hybrid.validate_generated_narrative(text, _facts(
        synthetic_case("comparable_history"), permissions=hybrid.HybridPermissions(history=True),
    ))[0]


def test_missing_history_or_prescription_permission_cannot_be_bypassed_in_prose():
    for text in (
        "Ton historique est comparable à cette séance.",
        "Ton objectif d'entraînement est atteint.",
        "Ta prescription est respectée.",
    ):
        assert not hybrid.validate_generated_narrative(text, _facts())[0]


def test_consistency_is_limited_to_type_and_requires_prescription_permission():
    v3 = synthetic_case()
    v3.prescription_assessment = WIV3PrescriptionAssessment(status="consistent")
    assert "prescription.review" not in {f.id for f in _facts(v3)}
    fact = next(f for f in _facts(
        v3, permissions=hybrid.HybridPermissions(prescription=True),
    ) if f.id == "prescription.review")
    assert dict(fact.values) == {"status": "consistent"}
    assert "type_only_not_full_compliance" in fact.important_limits


def test_zero_historical_difference_is_not_missing():
    v3 = synthetic_case("comparable_history")
    v3.historical_comparison.pace_at_comparable_hr.pace_difference_sec_per_km = 0
    fact = next(f for f in _facts(
        v3, permissions=hybrid.HybridPermissions(history=True),
    ) if f.id == "comparison.pace")
    assert dict(fact.values)["pace_difference"] == 0


def test_rich_and_poor_responses_follow_value_not_word_quota(monkeypatch):
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    poor = _run(synthetic_case("sparse"), transport=_provider(lambda *_: DIRECT_TEXT["sparse"]))
    rich = _run(
        synthetic_case("comparable_history"),
        permissions=hybrid.HybridPermissions(history=True),
        transport=_provider(lambda *_: DIRECT_TEXT["comparable_history"]),
    )
    assert poor.mode == rich.mode == "generated_narrative"
    assert len(poor.text) < len(rich.text)
    assert len(_context(synthetic_case("sparse"))["facts"]) < len(_context(
        synthetic_case("comparable_history"), permissions=hybrid.HybridPermissions(history=True),
    )["facts"])
    assert hybrid.validate_generated_narrative("140 bpm.", _facts())[0]
    assert not hybrid.validate_generated_narrative("x" * (hybrid.MAX_RESPONSE_CHARS + 1), _facts())[0]


def test_prompt_preserves_free_writing_and_scientific_selection(monkeypatch):
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")

    async def provider(system, prompt, user, context_type):
        assert "word quota" in system and "60–110" not in system
        assert "NOT caveats to recite" in system
        assert "Never turn probable classification into certainty" in system
        assert "No invented training goal" in system
        assert "Select the distinctive observation first" in system
        assert json.loads(prompt)["threshold_conventions"]["LT1"].startswith("Personal first lactate")
        return DIRECT_TEXT["easy"], True, {}

    assert _run(transport=provider).mode == "generated_narrative"


def test_rejected_science_still_uses_deterministic_fallback(monkeypatch):
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    result = _run(transport=_provider(lambda *_: "Tu construis ta base aérobie."))
    assert result.mode == "deterministic_fallback"
    assert result.text == hybrid._render(hybrid.select_deterministic_synthesis(_facts()))
    assert result.verdict == "HOLD"
