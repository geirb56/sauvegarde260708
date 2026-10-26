"""C378 Coach Editorial V2: selection, plan exclusion, closed advice, lighter caveats.

Synthetic V2/V3 fixtures only; no network, Garmin, MongoDB or LLM. Every text
asserted here is produced by the existing C359/C365/C374 code paths.
"""

import asyncio
from dataclasses import replace
import json
import re
import socket
from unittest.mock import Mock

import pytest

import hybrid_coach_c359 as hybrid
import hybrid_coach_closed_c374 as closed
from hybrid_coach_editorial_c365 import (
    ADVICE_REGISTRY, EDITORIAL_EXCLUDED_FACTS, _advice_predicate, select_advice,
)
from hybrid_coach_v2_c372 import ScopedV2Evidence, approved_v2_continuous_pacing
from test_hybrid_coach_c359 import _access, synthetic_case
from test_hybrid_coach_c372 import ACCESS, OWNER, calculated_case, phases_for
from test_workout_intelligence_v3 import _w
from workout_analysis_v2 import build_workout_analysis_v2
from workout_intelligence_v3 import build_workout_intelligence_v3, extract_workout_intelligence_input


LANGUAGES = ["fr", "en", "es"]
REGULAR = (300, 300, 300, 300)
FASTER = (330, 320, 310, 300)
SLOWER = (300, 310, 320, 330)
IRREGULAR = (300, 330, 295, 325)
STEADY_SPLITS = [6.0] * 10
SLOWER_HALF = [5.8] * 5 + [6.3] * 5
FASTER_HALF = [6.3] * 5 + [5.8] * 5

# Section 6: interpretations forbidden without additional evidence (FR/EN/ES).
FORBIDDEN = re.compile(
    r"fatigu|tu étais|you were tired|mal g[ée]r|poorly managed|mal gestionad|"
    r"endurance (?:est )?insuffisante|insufficient endurance|resistencia insuficiente|"
    r"vo2|r[ée]cup[èe]res mal|recover poorly|recuperas mal|aurais d[ûu]|should have|"
    r"deber[ií]as haber|prescri|plan pr[ée]vu|planned|conform|complian|cumplimiento|"
    r"objectif de (?:la )?s[ée]ance|session goal|objetivo de la sesi[oó]n",
    re.I,
)


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    forbidden = Mock(side_effect=AssertionError("No external services"))
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(hybrid, "_transport", forbidden)


def continuous_case(splits, *, language="fr", classification=None, confidence="high"):
    """Real V2 analysis over measured km splits; V3 built from the same workout."""
    rows = [{"km": i + 1, "pace_min_km": pace, "avg_hr": 140}
            for i, pace in enumerate(splits)]
    duration = sum(splits)
    workout = _w("cur", "2026-10-10", duration=duration, distance=len(splits),
                 pace=duration / len(splits), km_splits=rows)
    analysis = build_workout_analysis_v2(workout, [], language, [])
    v3 = build_workout_intelligence_v3(
        extract_workout_intelligence_input(workout, [], v2_analysis=analysis), language,
    )
    if classification is not None:
        v3.session_classification.type = classification
        v3.session_classification.confidence = confidence
    return v3, ScopedV2Evidence(OWNER, analysis)


def admitted(v3, evidence=None, *, language="fr", access=ACCESS, **permissions):
    return hybrid.build_admissible_facts(
        v3, access=access, language=language, v2_evidence=evidence,
        permissions=hybrid.HybridPermissions(**permissions),
    )


def fallback(v3, evidence=None, *, language="fr", access=ACCESS, **permissions):
    return asyncio.run(hybrid.generate_hybrid_coach(
        v3, access=access, language=language, v2_evidence=evidence,
        permissions=hybrid.HybridPermissions(**permissions),
        transport=_unavailable,
    ))


async def _unavailable(*args):
    return "", False, {}


def ids(claims):
    return [claim.id for claim in claims]


def assert_safe(result):
    """No forbidden interpretation in observations or advice; provenance on every claim."""
    texts = [result.text] + ([result.advice.text] if result.advice else [])
    for text in texts:
        assert not FORBIDDEN.search(text), text
    for claim in [*result.claims, *([result.advice] if result.advice else [])]:
        assert claim.evidence_ids and claim.conclusion_ids and claim.evidence_refs
    observed = [claim for claim in result.claims if claim.section == "analysis"]
    assert 1 <= len(observed) <= 3 and len(set(ids(observed))) == len(observed)
    assert all(claim.section == "analysis" for claim in result.claims)


# 1-5. Interval sessions ---------------------------------------------------------

@pytest.mark.parametrize("language", LANGUAGES)
def test_01_regular_intervals_select_regularity_and_keep_consistency_advice(language):
    v3, evidence = calculated_case(REGULAR, language=language)
    facts = admitted(v3, evidence, language=language)
    assert hybrid.primary_fact_candidates(facts)[0] == "interval.regularity"
    result = fallback(v3, evidence, language=language)
    assert ids(result.claims) == ["interval.regularity"]
    assert result.advice.id == "advice.keep_consistency"
    assert result.advice.section == "advice"
    assert result.advice.evidence_ids == ["interval.regularity"]
    assert result.advice_reason == "advice_admitted"
    assert result.language == language
    assert_safe(result)


@pytest.mark.parametrize("paces,direction", [(FASTER, "faster"), (SLOWER, "slower")])
@pytest.mark.parametrize("language", LANGUAGES)
def test_02_03_progressive_intervals_select_direction_with_conditional_distribution_advice(
    paces, direction, language,
):
    v3, evidence = calculated_case(paces, language=language)
    facts = admitted(v3, evidence, language=language)
    index = {fact.id: fact for fact in facts}
    assert dict(index["interval.pace_direction"].values)["direction"] == direction
    assert dict(index["interval.regularity"].values)["regularity_band"] != "homogeneous"
    result = fallback(v3, evidence, language=language)
    assert ids(result.claims) == ["interval.pace_direction"]
    assert result.advice.id == "advice.effort_distribution"
    # A deliberate progression is not treated as an error: the advice is conditional.
    assert {"fr": "où tu recherches", "en": "where you aim", "es": "en la que busques"}[
        language] in result.advice.text
    # Regularity advice is contraindicated when a direction is admitted.
    assert select_advice("interval.regularity", facts, language).reason == (
        "condition_unmet:v2_regularity_band_variable"
        if dict(index["interval.regularity"].values)["regularity_band"] != "variable"
        else "contraindicated:v2_directional_progression_admitted"
    )
    assert_safe(result)


@pytest.mark.parametrize("language", LANGUAGES)
def test_04_irregular_intervals_select_variability_and_stabilize_advice(language):
    v3, evidence = calculated_case(IRREGULAR, language=language)
    facts = admitted(v3, evidence, language=language)
    assert "interval.pace_direction" not in {f.id for f in facts}
    result = fallback(v3, evidence, language=language)
    assert ids(result.claims) == ["interval.regularity"]
    assert result.advice.id == "advice.stabilize_paces"
    assert_safe(result)


@pytest.mark.parametrize("language", LANGUAGES)
def test_05_non_comparable_repetitions_get_no_verdict_and_no_advice(language):
    v3, evidence = calculated_case(
        REGULAR, phases=phases_for(REGULAR, durations=[60, 240, 600, 240]), language=language,
    )
    facts = admitted(v3, evidence, language=language)
    assert not {"interval.regularity", "interval.pace_direction"} & {f.id for f in facts}
    result = fallback(v3, evidence, language=language)
    assert result.claims[0].id == "effort.first"
    assert result.advice is None
    assert result.advice_reason == "no_advice_for_primary"
    assert_safe(result)


# 6-8. Continuous and long runs ---------------------------------------------------

@pytest.mark.parametrize("language", LANGUAGES)
def test_06_steady_easy_run_has_no_pace_evolution_fact_and_no_advice(language):
    v3, evidence = continuous_case(STEADY_SPLITS, language=language,
                                   classification="easy_run_probable")
    facts = admitted(v3, evidence, language=language)
    assert "continuous.pace_halves" not in {f.id for f in facts}
    result = fallback(v3, evidence, language=language)
    assert result.claims[0].id == "intensity.hr"
    assert result.advice is None
    assert_safe(result)


@pytest.mark.parametrize("language", LANGUAGES)
def test_07_easy_run_with_slower_second_half_leads_with_measured_evolution(language):
    v3, evidence = continuous_case(SLOWER_HALF, language=language,
                                   classification="easy_run_probable")
    facts = admitted(v3, evidence, language=language)
    halves = next(f for f in facts if f.id == "continuous.pace_halves")
    assert dict(halves.values)["pace_change_sec_per_km"] == 30
    assert "no_fatigue_or_endurance_inference" in halves.important_limits
    result = fallback(v3, evidence, language=language)
    assert result.claims[0].id == "continuous.pace_halves"
    assert {"fr": "plus lente que la première", "en": "slower than the first",
            "es": "más lenta que la primera"}[language] in result.text
    assert result.advice.id == "advice.continuous_pacing"
    assert_safe(result)


@pytest.mark.parametrize("language", LANGUAGES)
def test_07b_continuous_advice_abstains_without_justifying_context(language):
    # Negative split: never presented as an error.
    v3, evidence = continuous_case(FASTER_HALF, language=language,
                                   classification="easy_run_probable")
    result = fallback(v3, evidence, language=language)
    assert result.claims[0].id == "continuous.pace_halves"
    assert result.advice is None
    assert result.advice_reason == "condition_unmet:v2_slower_second_half"
    # Unknown or untrusted session type: the pacing intent cannot be assumed.
    for classification, confidence in ((None, "high"), ("easy_run_probable", "low"),
                                       ("tempo_probable", "high")):
        v3, evidence = continuous_case(SLOWER_HALF, language=language,
                                       classification=classification, confidence=confidence)
        result = fallback(v3, evidence, language=language)
        assert result.claims[0].id == "continuous.pace_halves"
        assert result.advice is None
        assert result.advice_reason == "condition_unmet:trusted_easy_or_steady_type"
        assert_safe(result)


@pytest.mark.parametrize("language", LANGUAGES)
def test_08_long_run_keeps_duration_first_and_never_concludes_fatigue(language):
    v3, evidence = continuous_case(SLOWER_HALF, language=language,
                                   classification="long_run_probable")
    v3.session_classification.evidence.update(
        duration_minutes=60.5, habitual_duration_minutes=40,
    )
    facts = admitted(v3, evidence, language=language, history=True)
    assert {"session.long", "continuous.pace_halves"} <= {f.id for f in facts}
    result = fallback(v3, evidence, language=language, history=True)
    assert ids(result.claims)[:2] == ["session.long", "continuous.pace_halves"]
    assert result.advice is None and result.advice_reason == "no_advice_for_primary"
    # Even if the halves fact led, a long run contraindicates pacing advice.
    assert select_advice("continuous.pace_halves", facts, language).reason in {
        "condition_unmet:trusted_easy_or_steady_type", "contraindicated:long_session",
    }
    assert_safe(result)
    long_only = fallback(synthetic_case("long"), access=_access(), language=language,
                         history=True)
    assert long_only.claims[0].id == "session.long"
    assert_safe(long_only)


# 9-12. History and data availability ---------------------------------------------

@pytest.mark.parametrize("language", LANGUAGES)
def test_09_authorized_history_is_kept_as_a_single_admissible_comparison(language):
    result = fallback(synthetic_case("comparable_history"), access=_access(),
                      language=language, history=True)
    assert result.claims[0].id == "intensity.position"
    historical = [c for c in result.claims if c.id.startswith(("trend.", "comparison."))]
    assert len(historical) == 1
    assert {"not_proof_of_fitness", "no_cause", "terrain_weather_not_controlled"} <= set(
        historical[0].limits,
    )
    assert result.advice is None
    assert_safe(result)


@pytest.mark.parametrize("language", LANGUAGES)
def test_10_without_history_permission_or_data_no_history_is_used(language):
    for case, history in (("comparable_history", False), ("easy", True)):
        result = fallback(synthetic_case(case), access=_access(), language=language,
                          history=history)
        assert not any(c.id.startswith(("trend.", "comparison.", "session.long"))
                       for c in result.claims)
        assert_safe(result)


@pytest.mark.parametrize("language", LANGUAGES)
def test_11_average_hr_only_stays_descriptive(language):
    result = fallback(synthetic_case("no_physiology"), access=_access(), language=language)
    assert ids(result.claims) == ["intensity.hr"]
    assert "LT1" not in result.text and "LT2" not in result.text
    assert result.advice is None
    assert_safe(result)


@pytest.mark.parametrize("language", LANGUAGES)
def test_12_partial_data_yields_qualified_observation_without_advice(language):
    result = fallback(synthetic_case("sparse"), access=_access(), language=language)
    assert ids(result.claims) == ["session.unknown"]
    assert result.advice is None
    assert_safe(result)


# 13. Contradictory or absent V2/V3 judgments --------------------------------------

def test_13_contradictory_or_foreign_v2_judgments_are_never_admitted():
    v3, evidence = continuous_case(SLOWER_HALF, classification="easy_run_probable")
    analysis = evidence.analysis.model_copy(deep=True)
    item, = analysis.coach_language.conclusions
    analysis.coach_language.conclusions = [item.model_copy(update={
        "metadata": {**item.metadata, "direction": "faster"},
    })]
    contradicted = replace(evidence, analysis=analysis)
    for scoped in (contradicted, replace(evidence, user_id="another-user"), None):
        assert approved_v2_continuous_pacing(
            scoped, user_id=OWNER, workout_id=v3.workout_id,
        ) is None
        facts = admitted(v3, scoped)
        assert "continuous.pace_halves" not in {f.id for f in facts}
        assert select_advice("continuous.pace_halves", facts, "fr").reason == "no_primary_fact"
    v3, evidence = calculated_case(FASTER)
    for scoped in (replace(evidence, user_id="another-user"), None):
        facts = admitted(v3, scoped)
        assert not {"interval.regularity", "interval.pace_direction"} & {f.id for f in facts}
        result = fallback(v3, scoped)
        assert result.advice is None
        assert_safe(result)


# 14. Prescription present ---------------------------------------------------------

@pytest.mark.parametrize("status", ["consistent", "deviation"])
@pytest.mark.parametrize("language", LANGUAGES)
def test_14_prescription_is_admitted_by_c359_but_never_in_coach_comment(status, language):
    v3, evidence = calculated_case(SLOWER, language=language)
    v3.prescription_assessment.status = status
    facts = admitted(v3, evidence, language=language, prescription=True)
    assert "prescription.review" in {f.id for f in facts}
    assert "prescription.review" in EDITORIAL_EXCLUDED_FACTS
    assert "prescription.review" not in hybrid.primary_fact_candidates(facts)
    packet = hybrid.build_hybrid_context(
        v3, access=ACCESS, language=language, v2_evidence=evidence,
        permissions=hybrid.HybridPermissions(prescription=True),
    )
    assert "prescription.review" not in {f["evidence_id"] for f in packet["facts"]}
    result = fallback(v3, evidence, language=language, prescription=True)
    assert "prescription.review" not in ids(result.claims)
    assert_safe(result)
    for option in closed.build_editorial_options(facts, language):
        assert "prescription.review" not in (option.primary, *option.supporting)
    with pytest.raises(closed.SelectionFailure):
        closed._validate_composition(
            "interval.pace_direction", ("prescription.review",), facts, language,
        )


# 15. Insufficient evidence ------------------------------------------------------

@pytest.mark.parametrize("language", LANGUAGES)
def test_15_insufficient_evidence_abstains_from_advice(language):
    result = fallback(synthetic_case("intervals_4x4"), access=_access(), language=language)
    assert ids(result.claims) == ["interval.count", "intensity.position"]
    assert result.advice is None and result.advice_reason == "no_advice_for_primary"
    assert "regularity_verdict_authority_unavailable" in result.blockers
    assert_safe(result)
    nothing = fallback(synthetic_case(), access=None, language=language)
    assert nothing.mode == "denied" and nothing.advice is None


# Cross-cutting guarantees ------------------------------------------------------

def test_advice_registry_is_closed_complete_and_fails_closed():
    assert len({rule.id for rule in ADVICE_REGISTRY}) == len(ADVICE_REGISTRY) == 4
    for rule in ADVICE_REGISTRY:
        assert rule.id.startswith("advice.") and rule.trigger_fact
        assert rule.conditions and rule.contraindications and rule.provenance
        assert {language for language, _ in rule.texts} == set(LANGUAGES)
        assert all(text and not FORBIDDEN.search(text) for _, text in rule.texts)
    assert _advice_predicate("invented_condition", {}) is False
    v3, evidence = calculated_case(REGULAR)
    facts = admitted(v3, evidence)
    # A fact is required as trigger: advice never attaches to an absent observation.
    assert select_advice(None, facts, "fr").reason == "no_primary_fact"
    assert select_advice("interval.count", facts, "fr").reason == "no_primary_fact"


@pytest.mark.parametrize("language", LANGUAGES)
def test_closed_options_carry_validated_advice_and_reject_tampering(language):
    v3, evidence = calculated_case(IRREGULAR, language=language)
    facts = admitted(v3, evidence, language=language)
    options = closed.build_editorial_options(facts, language)
    lead = options[0]
    assert lead.primary == "interval.regularity"
    assert lead.advice.id == "advice.stabilize_paces"
    index = {fact.id: fact for fact in facts}
    assert lead.provider_option(index)["advice_id"] == "advice.stabilize_paces"
    assert "advice" not in json.dumps([c for o in options for c in o.provider_option(index)["clauses"]])
    tampered = replace(lead, advice=lead.advice.model_copy(update={"text": "Tu étais fatigué."}))
    with pytest.raises(closed.SelectionFailure, match="scientific_violation"):
        closed.validate_option(tampered, facts, language)
    result = asyncio.run(closed.generate_closed_choice_coach(
        v3, access=ACCESS, language=language, v2_evidence=evidence,
        transport=lambda *a: _choice(lead.option_id),
    ))
    assert result.mode == "editorial_realization"
    assert result.advice == lead.advice and result.language == language


async def _prose(text):
    return text, True, {}


async def _choice(option_id):
    return json.dumps({"option_id": option_id}), True, {}


@pytest.mark.parametrize("paces", [REGULAR, FASTER, SLOWER, IRREGULAR])
@pytest.mark.parametrize("language", LANGUAGES)
def test_lighter_caveats_never_admit_forbidden_interpretations(paces, language):
    """Removing repeated disclaimers keeps limits structurally and texts descriptive."""
    v3, evidence = calculated_case(paces, language=language)
    facts = admitted(v3, evidence, language=language)
    for option in closed.build_editorial_options(facts, language):
        closed.validate_option(option, facts, language)
        assert not FORBIDDEN.search(option.text)
        for claim in option.claims:
            fact = next(f for f in facts if f.id == claim.id)
            assert claim.limits == list(fact.important_limits) and claim.limits
            assert claim.text.count(".") <= 2  # one observation, no stacked disclaimers
    # Closed realization still blocks every forbidden interpretation: provider prose
    # never reaches output and a tampered clause is rejected against the rebuild.
    lead = closed.build_editorial_options(facts, language)[0]
    for text in ("Tu étais fatigué.", "Ton endurance est insuffisante.",
                 "Tu as amélioré ta VO2max.", "Tu as mal géré ton effort.",
                 "Tu récupères mal.", "Tu aurais dû courir plus vite."):
        assert FORBIDDEN.search(text)
        tampered = replace(lead, claims=(lead.claims[0].model_copy(update={
            "text": lead.claims[0].text + " " + text,
        }), *lead.claims[1:]))
        with pytest.raises(closed.SelectionFailure, match="scientific_violation"):
            closed.validate_option(tampered, facts, language)
        result = asyncio.run(hybrid.generate_hybrid_coach(
            v3, access=ACCESS, language=language, v2_evidence=evidence,
            transport=lambda *a, t=text: _prose(t),
        ))
        assert result.mode == "deterministic_fallback"
        assert result.reason == "invalid_editorial_selection"
        assert text not in result.text and not FORBIDDEN.search(result.text)


@pytest.mark.parametrize("language", LANGUAGES)
def test_indispensable_limits_remain_visible(language):
    facts = admitted(synthetic_case("comparable_history"), access=_access(),
                     language=language, history=True)
    options = closed.build_editorial_options(facts, language)
    for option in options:
        for claim in option.claims:
            if claim.id == "intensity.position":
                assert {"fr": "chaque phase", "en": "each phase", "es": "cada fase"}[
                    language] in claim.text
            if claim.id.startswith(("comparison.", "trend.")):
                assert {"fr": "terrain et de la météo", "en": "terrain and weather",
                        "es": "terreno y del clima"}[language] in claim.text


@pytest.mark.parametrize("language", LANGUAGES)
def test_fallback_and_options_are_deterministic(language):
    v3, evidence = continuous_case(SLOWER_HALF, language=language,
                                   classification="steady_run_probable")
    first = fallback(v3, evidence, language=language)
    second = fallback(v3, evidence, language=language)
    for result in (first, second):
        result.elapsed_ms = None
    assert first == second
    facts = admitted(v3, evidence, language=language)
    assert closed.build_editorial_options(facts, language) == closed.build_editorial_options(
        facts, language,
    )


def test_selection_never_relies_on_metric_presence_alone():
    # A count or endpoint never outranks a V2 verdict covering all comparable efforts.
    v3, evidence = calculated_case(IRREGULAR)
    candidates = hybrid.primary_fact_candidates(admitted(v3, evidence))
    assert candidates[0] == "interval.regularity"
    assert not {"effort.first", "effort.last", "interval.count"} & set(candidates)
