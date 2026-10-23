"""C364 STOP specifications, not a certified validator or a product evaluation.

Strict xfails expose unresolved C362 acceptance/rejection gaps. Remove a marker
only when a future solution satisfies its assertion; never count xfails as
scientific safety successes. Only synthetic V3 fixtures and injected transport.
"""

import pytest

import hybrid_coach_c359 as hybrid
from test_hybrid_coach_c359 import _facts, _provider, _run, synthetic_case


UNSUPPORTED_ACCEPTED = pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="C364 STOP: unsupported prose still accepted by C362 heuristics",
)
SUPPORTED_REJECTED = pytest.mark.xfail(
    strict=True,
    raises=AssertionError,
    reason="C364 STOP: supported prose still rejected by C362 heuristics",
)


@pytest.mark.parametrize("name,text,supported", [
    pytest.param(
        "intervals_4x4", "Les répétitions sont irrégulières.", False,
        id="regularity-irregular",
    ),
    pytest.param(
        "intervals_4x4", "Sans régularité dans leur durée.", False,
        id="regularity-without", marks=UNSUPPORTED_ACCEPTED,
    ),
    pytest.param(
        "intervals_4x4", "Les intervalles manquent de régularité.", False,
        id="regularity-lacking", marks=UNSUPPORTED_ACCEPTED,
    ),
    pytest.param(
        "intervals_4x4", "Les répétitions sont homogènes.", False,
        id="regularity-homogeneous",
    ),
    pytest.param(
        "intervals_4x4", "Les intervalles ont une intensité stable.", False,
        id="regularity-stable-intensity", marks=UNSUPPORTED_ACCEPTED,
    ),
    pytest.param(
        "intervals_4x4", "Sans structure stricte des intervalles.", False,
        id="regularity-no-strict-structure", marks=UNSUPPORTED_ACCEPTED,
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
        False, id="invented-count-words", marks=UNSUPPORTED_ACCEPTED,
    ),
    pytest.param(
        "intervals_4x4", "Chaque effort reproduit exactement le précédent.", False,
        id="unseen-regularity-paraphrase", marks=UNSUPPORTED_ACCEPTED,
    ),
    pytest.param(
        "easy", "Tu es resté sous LT1 pendant toute la séance.", False,
        id="hr-entire-session",
    ),
    pytest.param(
        "easy", "Ta fréquence cardiaque est restée stable.", False,
        id="hr-stability", marks=UNSUPPORTED_ACCEPTED,
    ),
    pytest.param(
        "easy", "Tu as maintenu une intensité faible pendant toute la sortie.", False,
        id="hr-low-throughout", marks=UNSUPPORTED_ACCEPTED,
    ),
    pytest.param(
        "easy", "L'ensemble de la séance s'est déroulé sous LT1.", False,
        id="hr-entire-session-paraphrase", marks=UNSUPPORTED_ACCEPTED,
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
        id="benefit-conditional", marks=UNSUPPORTED_ACCEPTED,
    ),
    pytest.param(
        "easy", "Elle favorise la récupération.", False, id="benefit-recovery",
    ),
    pytest.param(
        "easy", "Tu as limité ta fatigue.", False,
        id="benefit-fatigue", marks=UNSUPPORTED_ACCEPTED,
    ),
    pytest.param(
        "easy", "Tu améliores ton efficacité aérobie.", False,
        id="benefit-aerobic-efficiency",
    ),
    pytest.param(
        "easy", "Ton organisme ressort renforcé de cet effort.", False,
        id="unseen-benefit-paraphrase", marks=UNSUPPORTED_ACCEPTED,
    ),
    pytest.param(
        "comparable_history",
        "À FC comparable, l'écart d'allure observé est de -14,4 s/km sur 5 références.",
        True, id="comparison-exact",
    ),
    pytest.param(
        "comparable_history",
        "À FC comparable, l'écart d'allure observé est de -14 s/km sur 5 références.",
        True, id="comparison-reasonable-rounding", marks=SUPPORTED_REJECTED,
    ),
    pytest.param(
        "comparable_history", "À FC comparable, tu es plus lent de -14,4 s/km.", False,
        id="comparison-direction", marks=UNSUPPORTED_ACCEPTED,
    ),
    pytest.param(
        "comparable_history",
        "À allure comparable, ta FC est plus basse de -14,4 bpm.",
        False, id="comparison-wrong-unit",
    ),
    pytest.param(
        "comparable_history",
        "À FC comparable, la variation médiane entre périodes est de -14,4 s/km.",
        False, id="comparison-wrong-reference", marks=UNSUPPORTED_ACCEPTED,
    ),
    pytest.param(
        "comparable_history",
        "Ta variation médiane entre périodes est de -24 s/km sur 5 observations.",
        False, id="comparison-wrong-observation-count", marks=UNSUPPORTED_ACCEPTED,
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
        id="negated-progression", marks=SUPPORTED_REJECTED,
    ),
    pytest.param(
        "easy", "Ta FC moyenne est de 140 bpm, sous ton seuil lactique 1 de 150 bpm.",
        True, id="threshold-label-not-measurement", marks=SUPPORTED_REJECTED,
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
    valid, reason, _ = hybrid.validate_generated_narrative(text, facts)
    result = _run(
        v3, permissions=permissions, transport=_provider(lambda *_: text),
    )

    expected_mode = "generated_narrative" if supported else "deterministic_fallback"
    assert (valid, result.mode) == (supported, expected_mode), (reason, result.reason)
    if supported:
        assert result.text == text
    else:
        expected_claims = hybrid.select_deterministic_synthesis(facts)
        assert result.claims == expected_claims
        assert result.text == " ".join(claim.text for claim in expected_claims)
