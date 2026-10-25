"""Deterministic boundary/realization checks, not real-LLM quality evaluation."""

import asyncio
from copy import deepcopy
from itertools import permutations, product
import json

import pytest

import hybrid_coach_c359 as hybrid
from hybrid_coach_editorial_c365 import allowed_forms, editorial_intent
from test_hybrid_coach_c359 import (
    CASES, _access, _context, _editorial_text, _facts, _provider, _run, synthetic_case,
)


def _selection(primary="intensity.position", form="direct", supporting=None, intent="describe_session"):
    return {
        "primary": {"fact_id": primary, "form": form},
        "supporting": [] if supporting is None else supporting,
        "editorial_intent": intent,
    }


@pytest.fixture(autouse=True)
def _enabled(monkeypatch):
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")


@pytest.mark.parametrize("selection", [
    {},
    [],
    None,
    {"primary": None, "supporting": [], "editorial_intent": "describe_session"},
    _selection("unknown"),
    _selection("comparison.pace"),
    _selection("prescription.review"),
    _selection(form="causal"),
    _selection(form="rounded"),
    _selection(intent="compare_history"),
    _selection(intent="invented_intent"),
    _selection(primary=42),
    _selection(supporting="intensity.hr"),
    _selection(supporting=[{"fact_id": "intensity.position", "form": "explain"}]),
    _selection(supporting=[{"fact_id": "session.kind", "form": "direct"}]),
    _selection(supporting=[{"fact_id": "intensity.position", "form": "direct"}] * 3),
    {**_selection(), "text": "Ta FC est stable."},
    {**_selection(), "transition": "donc tu progresses"},
    {**_selection(), "primary": {"fact_id": "intensity.position", "form": "direct", "value": 999}},
    {**_selection(), "primary": {"fact_id": "intensity.position", "form": "direct", "relation": "above_LT2"}},
    {**_selection(), "primary": {"fact_id": "intensity.position", "form": "direct", "unit": "km"}},
])
def test_invalid_structures_never_reach_display(selection):
    result = _run(transport=_provider(lambda *_: json.dumps(selection)))
    assert result.mode == "deterministic_fallback"
    assert result.reason == "invalid_editorial_selection"
    assert result.editorial_selection is None
    assert result.claims == hybrid.select_deterministic_synthesis(_facts())


@pytest.mark.parametrize("response", [
    "",
    "{",
    "null trailing",
    '```json\n{}\n```',
    '{"primary": {"fact_id":"intensity.position","fact_id":"session.kind","form":"direct"},'
    '"supporting":[],"editorial_intent":"describe_session"}',
    '{"primary":{"fact_id":"intensity.position","form":"direct"},'
    '"supporting":[],"supporting":[],"editorial_intent":"describe_session"}',
    '{"primary":{"fact_id":"intensity.position","form":"direct"},'
    '"supporting":[],"editorial_intent":NaN}',
])
def test_malformed_and_ambiguous_json_is_rejected(response):
    result = _run(transport=_provider(lambda *_: response))
    assert result.mode == "deterministic_fallback"
    assert result.reason == "invalid_editorial_selection"


@pytest.mark.parametrize("name,expected", [
    ("easy", "intensity.position"),
    ("long", "session.long"),
    ("intervals_4x4", "interval.count"),
    ("sparse", "session.unknown"),
    ("treadmill", "intensity.position"),
    ("comparable_history", "trend.probable_improvement"),
    ("no_physiology", "intensity.hr"),
])
def test_mock_editorial_relevance_and_no_redundant_support(name, expected):
    v3 = synthetic_case(name)
    before = deepcopy(v3.model_dump())
    permissions = hybrid.HybridPermissions(history=True)
    result = _run(v3, permissions=permissions, transport=_provider())
    assert result.mode == "editorial_realization"
    assert result.editorial_selection.primary.fact_id == expected
    assert result.claims[0].id == expected
    ids = [claim.id for claim in result.claims]
    assert len(ids) == len(set(ids))
    if name in {"easy", "treadmill", "sparse", "no_physiology"}:
        assert len(ids) == 1
    if name == "intervals_4x4":
        assert ids == ["interval.count", "intensity.position"]
        assert "160 bpm" in result.text and "régularité" not in result.text
    assert result.text == " ".join(claim.text for claim in result.claims)
    assert all(c.evidence_refs and c.conclusion_ids for c in result.claims)
    assert v3.model_dump() == before


@pytest.mark.parametrize("name,expected", [
    ("easy", "intensity.position"),
    ("long", "session.long"),
    ("intervals_4x4", "interval.count"),
    ("sparse", "session.unknown"),
    ("no_physiology", "intensity.hr"),
])
def test_contextual_primary_policy_for_session_types(name, expected):
    facts = _facts(
        synthetic_case(name),
        permissions=hybrid.HybridPermissions(history=True),
    )
    assert hybrid.primary_fact_candidates(facts)[0] == expected
    assert hybrid.select_deterministic_synthesis(facts)[0].id == expected


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_documented_type_level_prescription_deviation_is_primary(language):
    v3 = synthetic_case("intervals_4x4")
    v3.prescription_assessment.status = "deviation"
    facts = _facts(
        v3, permissions=hybrid.HybridPermissions(prescription=True), language=language,
    )
    review = next(fact for fact in facts if fact.id == "prescription.review")
    assert dict(review.values) == {"status": "deviation"}
    assert hybrid.primary_fact_candidates(facts) == ("prescription.review",)
    assert hybrid.select_deterministic_synthesis(facts)[0].id == "prescription.review"


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_distinctive_long_run_can_lead_a_supported_high_average_hr(language):
    v3 = synthetic_case("long")
    v3.intensity_assessment = v3.intensity_assessment.model_copy(update={
        "hr_used_bpm": 180, "position": "above_LT2", "confidence": "high",
    })
    permissions = hybrid.HybridPermissions(history=True)
    facts = _facts(v3, permissions=permissions, language=language)
    assert hybrid.primary_fact_candidates(facts) == (
        "session.long", "intensity.position",
    )
    assert hybrid.select_deterministic_synthesis(facts)[0].id == "session.long"
    packet = _context(v3, permissions=permissions, language=language)
    assert packet["primary_fact_candidates"] == ["session.long", "intensity.position"]
    valid = json.dumps({
        "primary": {"fact_id": "session.long", "form": "direct"},
        "supporting": [{"fact_id": "intensity.position", "form": "direct"}],
        "editorial_intent": "describe_session",
    })
    result = _run(
        v3, permissions=permissions, language=language,
        transport=_provider(lambda *_: valid),
    )
    assert result.mode == "editorial_realization"
    assert result.claims[0].id == "session.long"
    assert [claim.id for claim in result.claims] == [
        "session.long", "intensity.position",
    ]
    expected_claims = [
        hybrid.realize_clause(fact, "direct", language)
        for fact in (next(f for f in facts if f.id == "session.long"),
                     next(f for f in facts if f.id == "intensity.position"))
    ]
    assert [claim.text for claim in result.claims] == expected_claims
    assert all(claim.evidence_refs and claim.conclusion_ids for claim in result.claims)
    refused = json.dumps(_selection("session.kind"))
    fallback = _run(
        v3, permissions=permissions, language=language,
        transport=_provider(lambda *_: refused),
    )
    assert fallback.mode == "deterministic_fallback"
    assert fallback.claims[0].id == "session.long"


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_corroborated_history_leads_for_a_reliably_classified_continuous_session(language):
    v3 = synthetic_case("comparable_history")
    permissions = hybrid.HybridPermissions(history=True)
    facts = _facts(v3, permissions=permissions, language=language)
    candidates = hybrid.primary_fact_candidates(facts)
    assert candidates and all(
        fact_id.startswith(("trend.", "comparison.")) for fact_id in candidates
    )
    assert hybrid.select_deterministic_synthesis(facts)[0].id == candidates[0]
    packet = _context(v3, permissions=permissions, language=language)
    assert packet["primary_fact_candidates"] == list(candidates)
    primary = next(fact for fact in facts if fact.id == candidates[0])
    valid = json.dumps(_selection(
        candidates[0], form="explain", intent="compare_history",
    ))
    selected = _run(
        v3, permissions=permissions, language=language,
        transport=_provider(lambda *_: valid),
    )
    assert selected.mode == "editorial_realization"
    assert selected.claims[0].id == candidates[0]
    assert selected.claims[0].text == hybrid.realize_clause(primary, "explain", language)
    intensity = next((fact for fact in facts if fact.id == "intensity.position"), None)
    if intensity is not None:
        invalid = json.dumps(_selection("intensity.position", intent="describe_session"))
        result = _run(
            v3, permissions=permissions, language=language,
            transport=_provider(lambda *_: invalid),
        )
        assert result.mode == "deterministic_fallback"
        assert result.claims[0].id == candidates[0]
        assert result.claims[0].text == next(f.assertion for f in facts if f.id == candidates[0])
    assert all(fact.source_paths for fact in facts if fact.id in candidates)


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_unknown_session_type_does_not_admit_a_direction_or_free_llm_choice(language):
    v3 = synthetic_case("sparse")
    permissions = hybrid.HybridPermissions(history=True)
    facts = _facts(v3, permissions=permissions, language=language)
    assert hybrid.primary_fact_candidates(facts) == ("session.unknown",)
    assert "interval.pace_direction" not in {fact.id for fact in facts}
    packet = _context(v3, permissions=permissions, language=language)
    assert packet["primary_fact_candidates"] == ["session.unknown"]
    result = _run(
        v3, permissions=permissions, language=language,
        transport=_provider(lambda *_: json.dumps(_selection(
            "interval.pace_direction",
        ))),
    )
    assert result.mode == "deterministic_fallback"
    assert result.claims[0].id == "session.unknown"
    assert result.claims[0].text == next(f.assertion for f in facts if f.id == "session.unknown")
    assert result.claims[0].evidence_refs
    valid = json.dumps(_selection("session.unknown", intent="qualify_data"))
    chosen = _run(
        v3, permissions=permissions, language=language,
        transport=_provider(lambda *_: valid),
    )
    assert chosen.mode == "editorial_realization"
    assert chosen.claims[0].id == "session.unknown"


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_unknown_session_with_corroborated_history_keeps_cautious_primary(language):
    v3 = synthetic_case("sparse")
    history = synthetic_case("comparable_history")
    v3 = v3.model_copy(update={
        "historical_comparison": history.historical_comparison,
        "performance_trend": history.performance_trend,
    })
    permissions = hybrid.HybridPermissions(history=True)
    facts = _facts(v3, permissions=permissions, language=language)
    historical = next(
        fact for fact in facts if fact.id.startswith(("trend.", "comparison."))
    )
    unknown = next(fact for fact in facts if fact.id == "session.unknown")

    assert hybrid.primary_fact_candidates(facts) == ("session.unknown",)
    assert _context(v3, permissions=permissions, language=language)[
        "primary_fact_candidates"
    ] == ["session.unknown"]
    fallback = hybrid.select_deterministic_synthesis(facts)
    assert [claim.id for claim in fallback] == ["session.unknown"]
    assert fallback[0].text == unknown.assertion
    assert fallback[0].evidence_refs == list(unknown.source_paths)
    assert historical.source_paths

    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    valid = json.dumps(_selection("session.unknown", intent="qualify_data"))
    selected = _run(
        v3, permissions=permissions, language=language,
        transport=_provider(lambda *_: valid),
    )
    assert selected.mode == "editorial_realization"
    assert [claim.id for claim in selected.claims] == ["session.unknown"]
    assert selected.text == unknown.assertion
    assert selected.claims[0].evidence_refs == list(unknown.source_paths)

    refused = json.dumps(_selection(historical.id, intent="compare_history"))
    rejected = _run(
        v3, permissions=permissions, language=language,
        transport=_provider(lambda *_: refused),
    )
    assert rejected.mode == "deterministic_fallback"
    assert [claim.id for claim in rejected.claims] == ["session.unknown"]
    assert rejected.text == unknown.assertion


def test_long_run_and_historical_trend_are_not_double_reported():
    long_facts = _facts(
        synthetic_case("long"),
        permissions=hybrid.HybridPermissions(history=True),
    )
    trend_facts = _facts(
        synthetic_case("comparable_history"),
        permissions=hybrid.HybridPermissions(history=True),
    )
    trend = next(fact for fact in trend_facts if fact.id.startswith("trend."))
    combined = long_facts + (trend,)
    response = json.dumps({
        "primary": {"fact_id": "session.long", "form": "direct"},
        "supporting": [{"fact_id": trend.id, "form": "direct"}],
        "editorial_intent": "describe_session",
    })
    with pytest.raises(ValueError, match="redundant_selection"):
        hybrid.validate_editorial_selection(response, combined, "fr")


@pytest.mark.parametrize("language", ["fr", "en", "es"])
@pytest.mark.parametrize("name", CASES)
def test_all_admitted_forms_are_locally_realizable_and_traceable(name, language):
    permissions = hybrid.HybridPermissions(history=True, prescription=True)
    facts = _facts(synthetic_case(name), permissions=permissions, language=language)
    for fact in facts:
        isolated_fact = (fact,)
        for form in allowed_forms(fact, language):
            selection = hybrid.validate_editorial_selection(json.dumps(_selection(
                fact.id, form, intent=editorial_intent(fact),
            )), isolated_fact, language)
            claims = hybrid.realize_editorial_selection(selection, isolated_fact, language)
            assert len(claims) == 1
            claim = claims[0]
            assert claim.id == fact.id and claim.text
            assert claim.evidence_ids == [fact.id]
            assert claim.evidence_refs == list(fact.source_paths)
            assert claim.conclusion_ids == [fact.allowed_conclusion]


def test_composition_space_has_no_free_transition_or_hidden_prose():
    facts = _facts(synthetic_case("comparable_history"), permissions=hybrid.HybridPermissions(history=True))
    accepted = 0
    # Exhaust all orders/subsets up to the contract limit and the direct/explain forms.
    for size in range(1, 4):
        for chosen in permutations(facts, size):
            for forms in product(("direct", "explain"), repeat=size):
                clauses = [{"fact_id": f.id, "form": form} for f, form in zip(chosen, forms)]
                response = json.dumps({
                    "primary": clauses[0], "supporting": clauses[1:],
                    "editorial_intent": editorial_intent(chosen[0]),
                })
                try:
                    selection = hybrid.validate_editorial_selection(response, facts, "fr")
                except ValueError:
                    continue
                claims = hybrid.realize_editorial_selection(selection, facts, "fr")
                expected = [
                    hybrid.realize_clause(fact, form, "fr") for fact, form in zip(chosen, forms)
                ]
                assert [c.text for c in claims] == expected
                assert hybrid._render(claims) == " ".join(expected)
                accepted += 1
    assert accepted > 0


@pytest.mark.parametrize("fact_id,expected", [
    ("comparison.pace", "−14,4 s/km"),
    ("comparison.hr", "0 bpm"),
    ("trend.probable_improvement", "−24 s/km"),
])
def test_distinct_comparison_roles_signs_units_and_counts(fact_id, expected):
    v3 = synthetic_case("comparable_history")
    selection = json.dumps(_selection(fact_id, intent="compare_history"))
    result = _run(v3, permissions=hybrid.HybridPermissions(history=True),
                  transport=_provider(lambda *_: selection))
    assert result.mode == "editorial_realization"
    assert expected in result.text
    if fact_id == "comparison.pace":
        assert "moyenne de 5" in result.text and "médiane" not in result.text
    if fact_id == "comparison.hr":
        assert "moyenne de 2" in result.text
    if fact_id.startswith("trend."):
        assert "6 observations" in result.text and "92 jours" in result.text


def test_threshold_precision_does_not_change_comparison_by_rounding():
    v3 = synthetic_case()
    v3.intensity_assessment.hr_used_bpm = 149.96
    v3.intensity_assessment.lt1.value_bpm = 149.97
    result = _run(v3, transport=_provider())
    assert result.mode == "editorial_realization"
    assert "149,96 bpm" in result.text and "149,97 bpm" in result.text
    assert "150 bpm" not in result.text


@pytest.mark.parametrize("delta,expected", [(-14.4, "−14"), (14.4, "+14"), (-1.1, "−1"), (0, None)])
def test_approximation_is_explicit_and_keeps_direction(delta, expected):
    v3 = synthetic_case("comparable_history")
    v3.historical_comparison.pace_at_comparable_hr.pace_difference_sec_per_km = delta
    response = json.dumps(_selection("comparison.pace", "rounded", intent="compare_history"))
    result = _run(v3, permissions=hybrid.HybridPermissions(history=True),
                  transport=_provider(lambda *_: response))
    if expected is None:
        assert result.mode == "deterministic_fallback"
    else:
        assert result.mode == "editorial_realization"
        assert "environ " + expected + " s/km" in result.text


def test_llm_can_choose_observation_order_and_omit_default_primary():
    selection = _selection("intensity.position", supporting=[{"fact_id": "interval.count", "form": "direct"}])
    result = _run(synthetic_case("intervals_4x4"),
                  transport=_provider(lambda *_: json.dumps(selection)))
    assert [c.id for c in result.claims] == ["intensity.position", "interval.count"]
    assert result.text.startswith("Ta FC moyenne")
    selection["supporting"] = []
    result = _run(synthetic_case("intervals_4x4"),
                  transport=_provider(lambda *_: json.dumps(selection)))
    assert result.mode == "editorial_realization" and len(result.claims) == 1


def test_history_and_prescription_are_filtered_before_prompt_and_selection():
    v3 = synthetic_case("comparable_history")
    v3.prescription_assessment.status = "consistent"
    packet = _context(v3)
    assert not any(f["required_permissions"] for f in packet["facts"])
    for fact_id, intent in [("trend.probable_improvement", "compare_history"),
                            ("prescription.review", "review_prescription")]:
        result = _run(v3, transport=_provider(lambda *_: json.dumps(_selection(fact_id, intent=intent))))
        assert result.mode == "deterministic_fallback"
        assert fact_id not in {c.id for c in result.claims}
    packet = _context(v3, permissions=hybrid.HybridPermissions(history=True, prescription=True))
    by_id = {f["evidence_id"]: f for f in packet["facts"]}
    assert by_id["trend.probable_improvement"]["required_permissions"] == ["history"]
    assert by_id["prescription.review"]["required_permissions"] == ["prescription"]


def test_permission_values_must_be_true_not_truthy():
    v3 = synthetic_case("long")
    for value in (1, "true"):
        facts = _facts(v3, permissions=hybrid.HybridPermissions(history=value, prescription=value))
        assert not any(f.id == "session.long" or f.id.startswith(("comparison.", "trend.")) for f in facts)


def test_no_llm_access_and_flag_off_do_not_call_provider(monkeypatch):
    async def forbidden(*args):
        pytest.fail("provider must not be called")

    access = _access()
    original = type(access).can
    monkeypatch.setattr(type(access), "can", lambda self, feature: feature != "llm_access" and original(self, feature))
    result = _run(access=access, transport=forbidden)
    assert result.reason == "llm_access_not_authorized"
    assert result.claims and not result.provider_attempted
    monkeypatch.delenv(hybrid.FEATURE_FLAG)
    disabled = _run(access=access, transport=forbidden)
    assert disabled.mode == "disabled" and disabled.text == "" and disabled.claims == []


def test_no_authorized_facts_do_not_call_provider():
    v3 = synthetic_case("long")
    v3.intensity_assessment.hr_used_bpm = None

    async def forbidden(*args):
        pytest.fail("provider must not be called")

    result = _run(v3, transport=forbidden)
    assert result.reason == "no_authorized_facts"
    assert not result.provider_attempted and result.claims == [] and result.text == ""


def test_rendering_uses_the_admitted_snapshot_not_mutable_v3_after_transport():
    v3 = synthetic_case()

    async def provider(system, prompt, *args):
        v3.intensity_assessment.hr_used_bpm = 999
        v3.coach_assessment.diagnosis.text = "Tu progresses grâce à ta fatigue."
        return _editorial_text(json.loads(prompt)), True, {}

    result = _run(v3, transport=provider)
    assert result.mode == "editorial_realization"
    assert "140 bpm" in result.text and "999" not in result.text and "fatigue" not in result.text


@pytest.mark.parametrize("failure", ["timeout", "exception", "truncated", "overlength", "failed", "not_text"])
def test_provider_failures_are_atomic_and_never_expose_response(failure, monkeypatch):
    async def provider(*args):
        if failure == "timeout":
            await asyncio.Future()
        if failure == "exception":
            raise RuntimeError("private-provider-payload")
        response = _editorial_text(json.loads(args[1]))
        if failure == "overlength":
            response += " " * hybrid.MAX_RESPONSE_CHARS
        if failure == "not_text":
            response = {"text": "private-provider-payload"}
        return response, failure != "failed", {"response_truncated": failure == "truncated"}

    monkeypatch.setattr(hybrid, "TIMEOUT_SECONDS", 0.01)
    result = _run(transport=provider)
    assert result.mode == "deterministic_fallback"
    assert result.editorial_selection is None
    assert result.claims == hybrid.select_deterministic_synthesis(_facts())
    assert "private-provider-payload" not in result.model_dump_json()
    if failure == "timeout":
        assert result.reason == "timeout"


def test_generation_never_calls_the_retired_lexical_validator(monkeypatch):
    def forbidden(*args, **kwargs):
        pytest.fail("C362 heuristics cannot certify C365 output")

    monkeypatch.setattr(hybrid, "validate_generated_narrative", forbidden)
    assert _run(transport=_provider()).mode == "editorial_realization"
    assert _run(transport=_provider(lambda *_: "Ta FC est stable.")).mode == "deterministic_fallback"
