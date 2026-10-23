"""The 32 C364 cases replayed at the C365 closed-realization boundary.

Raw prose is never accepted, including factual prose. Supported meanings are
tested separately through typed clauses, not certified by lexical matching.
Only synthetic V3 fixtures and injected transport; no editorial-quality claim.
"""

import json
import pytest

import hybrid_coach_c359 as hybrid
from test_hybrid_coach_c359 import _facts, _provider, _run, synthetic_case


# Historical markers removed: all 32 cases now exercise the new boundary.
# This does not claim that the retired prose heuristic has become sound.
SUPPORTED_CLAUSES = {
    "Garmin a enregistré quatre phases d'effort et trois phases de récupération.":
        ("interval.count", "count_words", "quatre phases d'effort et trois"),
    "Garmin a enregistré 4 phases d'effort et 3 phases de récupération.":
        ("interval.count", "direct", "4 phases d'effort et 3"),
    "Ta FC moyenne est de 140 bpm, sous ton LT1 de 150 bpm.":
        ("intensity.position", "direct", "140 bpm, sous ton LT1 de 150 bpm"),
    "À FC comparable, l'écart d'allure observé est de -14,4 s/km sur 5 références.":
        ("comparison.pace", "direct", "−14,4 s/km par rapport à la moyenne de 5"),
    "À FC comparable, l'écart d'allure observé est de -14 s/km sur 5 références.":
        ("comparison.pace", "rounded", "environ −14 s/km"),
    "Ces données ne permettent pas de conclure à une progression.":
        ("intensity.position", "scope", "Cette moyenne ne permet pas de conclure à une progression."),
    "Ta FC moyenne est de 140 bpm, sous ton seuil lactique 1 de 150 bpm.":
        ("intensity.position", "threshold_label", "seuil lactique 1 de 150 bpm"),
}


@pytest.mark.parametrize("name,text,supported", [
    pytest.param(
        "intervals_4x4", "Les répétitions sont irrégulières.", False,
        id="regularity-irregular",
    ),
    pytest.param(
        "intervals_4x4", "Sans régularité dans leur durée.", False,
        id="regularity-without",
    ),
    pytest.param(
        "intervals_4x4", "Les intervalles manquent de régularité.", False,
        id="regularity-lacking",
    ),
    pytest.param(
        "intervals_4x4", "Les répétitions sont homogènes.", False,
        id="regularity-homogeneous",
    ),
    pytest.param(
        "intervals_4x4", "Les intervalles ont une intensité stable.", False,
        id="regularity-stable-intensity",
    ),
    pytest.param(
        "intervals_4x4", "Sans structure stricte des intervalles.", False,
        id="regularity-no-strict-structure",
    ),
    pytest.param(
        "intervals_4x4",
        "Garmin a enregistré quatre phases d'effort et trois phases de récupération.",
        True, id="factual-count-words",
    ),
    pytest.param(
        "intervals_4x4",
        "Garmin a enregistré 4 phases d'effort et 3 phases de récupération.",
        True, id="factual-count-digits",
    ),
    pytest.param(
        "intervals_4x4",
        "Garmin a enregistré cinq phases d'effort et deux phases de récupération.",
        False, id="invented-count-words",
    ),
    pytest.param(
        "intervals_4x4", "Chaque effort reproduit exactement le précédent.", False,
        id="unseen-regularity-paraphrase",
    ),
    pytest.param(
        "easy", "Tu es resté sous LT1 pendant toute la séance.", False,
        id="hr-entire-session",
    ),
    pytest.param(
        "easy", "Ta fréquence cardiaque est restée stable.", False,
        id="hr-stability",
    ),
    pytest.param(
        "easy", "Tu as maintenu une intensité faible pendant toute la sortie.", False,
        id="hr-low-throughout",
    ),
    pytest.param(
        "easy", "L'ensemble de la séance s'est déroulé sous LT1.", False,
        id="hr-entire-session-paraphrase",
    ),
    pytest.param(
        "easy", "Ta FC moyenne est de 140 bpm, sous ton LT1 de 150 bpm.", True,
        id="factual-average",
    ),
    pytest.param(
        "easy", "Cette séance développe ton endurance fondamentale.", False,
        id="benefit-endurance",
    ),
    pytest.param(
        "easy", "Elle peut être bénéfique pour ton endurance.", False,
        id="benefit-conditional",
    ),
    pytest.param(
        "easy", "Elle favorise la récupération.", False, id="benefit-recovery",
    ),
    pytest.param(
        "easy", "Tu as limité ta fatigue.", False,
        id="benefit-fatigue",
    ),
    pytest.param(
        "easy", "Tu améliores ton efficacité aérobie.", False,
        id="benefit-aerobic-efficiency",
    ),
    pytest.param(
        "easy", "Ton organisme ressort renforcé de cet effort.", False,
        id="unseen-benefit-paraphrase",
    ),
    pytest.param(
        "comparable_history",
        "À FC comparable, l'écart d'allure observé est de -14,4 s/km sur 5 références.",
        True, id="comparison-exact",
    ),
    pytest.param(
        "comparable_history",
        "À FC comparable, l'écart d'allure observé est de -14 s/km sur 5 références.",
        True, id="comparison-reasonable-rounding",
    ),
    pytest.param(
        "comparable_history", "À FC comparable, tu es plus lent de -14,4 s/km.", False,
        id="comparison-direction",
    ),
    pytest.param(
        "comparable_history",
        "À allure comparable, ta FC est plus basse de -14,4 bpm.",
        False, id="comparison-wrong-unit",
    ),
    pytest.param(
        "comparable_history",
        "À FC comparable, la variation médiane entre périodes est de -14,4 s/km.",
        False, id="comparison-wrong-reference",
    ),
    pytest.param(
        "comparable_history",
        "Ta variation médiane entre périodes est de -24 s/km sur 5 observations.",
        False, id="comparison-wrong-observation-count",
    ),
    pytest.param(
        "comparable_history",
        "À FC comparable, l'écart d'allure observé est de +14,4 s/km.",
        False, id="comparison-wrong-sign",
    ),
    pytest.param(
        "comparable_history",
        "Ton historique confirme une amélioration physiologique.",
        False, id="comparison-not-physiological-progress",
    ),
    pytest.param(
        "easy", "Ces données ne permettent pas de conclure à une progression.", True,
        id="negated-progression",
    ),
    pytest.param(
        "easy", "Ta FC moyenne est de 140 bpm, sous ton seuil lactique 1 de 150 bpm.",
        True, id="threshold-label-not-measurement",
    ),
    pytest.param(
        "easy", "Prévois désormais une sortie supplémentaire chaque semaine.", False,
        id="unauthorized-prescription",
    ),
])
def test_c364_scientific_contract_specification(name, text, supported, monkeypatch):
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    v3 = synthetic_case(name)
    permissions = hybrid.HybridPermissions(history=name == "comparable_history")
    facts = _facts(v3, permissions=permissions)
    result = _run(
        v3, permissions=permissions, transport=_provider(lambda *_: text),
    )
    assert result.mode == "deterministic_fallback"
    assert result.reason == "invalid_editorial_selection"
    expected_claims = hybrid.select_deterministic_synthesis(facts)
    assert result.claims == expected_claims
    assert result.text == " ".join(claim.text for claim in expected_claims)
    assert result.editorial_selection is None
    if supported:
        fact_id, form, fragment = SUPPORTED_CLAUSES[text]
        selection = json.dumps({
            "primary": {"fact_id": fact_id, "form": form},
            "supporting": [],
            "editorial_intent": "compare_history" if fact_id.startswith("comparison.") else "describe_session",
        })
        realized = _run(v3, permissions=permissions, transport=_provider(lambda *_: selection))
        assert realized.mode == "editorial_realization"
        assert fragment in realized.text
        assert realized.claims[0].evidence_ids == [fact_id]
        assert realized.claims[0].evidence_refs
