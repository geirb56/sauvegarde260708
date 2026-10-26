"""Closed-choice transport simulations only; no provider, network or databases."""

import asyncio
from copy import deepcopy
from dataclasses import replace
import json
import socket
from unittest.mock import Mock

import pytest

from access_control import Tier, UserAccess
import hybrid_coach_c359 as legacy
import hybrid_coach_closed_c374 as closed
from test_hybrid_coach_c359 import CASES, _access, synthetic_case
from test_hybrid_coach_c372 import ACCESS, calculated_case


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.setenv(legacy.FEATURE_FLAG, "true")
    forbidden = Mock(side_effect=AssertionError("No external services"))
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(legacy, "_transport", forbidden)


def options(v3=None, *, access=None, language="fr", **kwargs):
    facts = legacy.build_admissible_facts(
        v3 or synthetic_case(), access=access or _access(), language=language, **kwargs,
    )
    return facts, closed.build_editorial_options(facts, language)


def run(v3=None, **kwargs):
    return asyncio.run(closed.generate_closed_choice_coach(
        v3 or synthetic_case(), access=kwargs.pop("access", _access()), **kwargs,
    ))


def provider(response=None, captured=None):
    async def transport(system, prompt, user, context_type):
        packet = json.loads(prompt)
        if captured is not None:
            captured.append((system, packet, user, context_type))
        value = response if response is not None else json.dumps({
            "option_id": packet["options"][0]["option_id"],
        })
        return value, True, {"duration_sec": 0.125}
    return transport


def failed(result, reason):
    assert result.mode == "failed"
    assert result.reason == reason
    assert result.text == ""
    assert result.claims == []
    assert result.option_id is None
    assert result.verification_scope == "none"


@pytest.mark.parametrize("name", CASES)
@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_every_option_is_admissible_before_transport(name, language):
    v3 = synthetic_case(name)
    before = deepcopy(v3.model_dump())
    permissions = legacy.HybridPermissions(history=True, prescription=True)
    facts, choices = options(v3, language=language, permissions=permissions)
    assert 1 <= len(choices) <= closed.MAX_OPTIONS
    assert len({o.option_id for o in choices}) == len(choices)
    assert len({(o.primary, o.supporting) for o in choices}) == len(choices)
    for option in choices:
        closed.validate_option(option, facts, language)
        assert 0 <= len(option.supporting) <= 2
        assert len(option.text) <= legacy.MAX_COACH_TEXT_CHARS
        assert all(c.evidence_refs and c.conclusion_ids for c in option.claims)
        result = run(
            v3, language=language, permissions=permissions,
            transport=provider(json.dumps({"option_id": option.option_id})),
        )
        assert result.mode == "editorial_realization"
        chosen = closed.select_deterministic_option(choices)
        assert result.text == chosen.text
        assert result.claims == list(chosen.claims)
        assert not result.provider_attempted and result.transport_kind == "none"
        assert result.provider_duration_sec is None
        assert result.cost is None
    assert v3.model_dump() == before


@pytest.mark.parametrize("classification", ["easy_run_probable", "steady_run_probable"])
@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_type_and_average_are_complementary_not_a_physiological_inference(classification, language):
    v3 = synthetic_case()
    v3.session_classification.type = classification
    facts, choices = options(v3, language=language)
    combined = next(o for o in choices if set((o.primary, *o.supporting)) == {
        "session.kind", "intensity.position",
    })
    assert combined.primary in legacy.primary_fact_candidates(facts)
    assert {"fr": "probablement", "en": "probably", "es": "Probablemente"}[language] in combined.text
    assert {"fr": "chaque phase", "en": "each phase", "es": "cada fase"}[language] in combined.text
    assert {"fr": "temps en zones", "en": "time in zones", "es": "tiempo en zonas"}[language] in combined.text
    # Existing C365 composition/fallback policy is deliberately unchanged.
    with pytest.raises(ValueError, match="redundant_selection"):
        legacy.validate_editorial_selection(json.dumps({
            "primary": {"fact_id": "intensity.position", "form": "direct"},
            "supporting": [{"fact_id": "session.kind", "form": "direct"}],
            "editorial_intent": "describe_session",
        }), facts, language)


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_unknown_hr_is_descriptive_and_not_duplicated(language):
    v3 = synthetic_case("no_physiology")
    v3.session_classification.type = "unknown"
    facts, choices = options(v3, language=language)
    assert {o.primary for o in choices} == {"session.unknown", "intensity.hr"}
    assert all(not o.supporting for o in choices)
    assert all(o.text.count("140") == 1 for o in choices)
    assert all("LT1" not in o.text and "LT2" not in o.text for o in choices)
    for option in choices:
        closed.validate_option(option, facts, language)


@pytest.mark.parametrize("paces", [
    (300, 300, 300, 300), (330, 320, 310, 300), (300, 310, 320, 330),
])
@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_real_v2_regularity_direction_and_recorded_endpoints(paces, language):
    v3, evidence = calculated_case(paces, language=language)
    before = deepcopy(evidence.analysis.model_dump())
    facts, choices = options(v3, access=ACCESS, v2_evidence=evidence, language=language)
    ids = {f.id for f in facts}
    assert "interval.regularity" in ids
    assert "effort.first" in ids and "effort.last" in ids
    regularity_claims = [
        claim for option in choices for claim in option.claims
        if claim.id == "interval.regularity"
    ]
    assert regularity_claims
    # C378: descriptive pace clauses no longer repeat disclaimers in the text; the
    # limits remain attached to the claim and to the admitted fact.
    assert all("not_physiological_stability" in c.limits for c in regularity_claims)
    assert all({"fr": "stabilité physiologique", "en": "physiological stability",
                "es": "estabilidad fisiológica"}[language] not in c.text
               for c in regularity_claims)
    if len(set(paces)) > 1:
        assert "interval.pace_direction" in ids
        combined = choices[0]
        assert combined.primary == "interval.pace_direction"
        assert "interval.regularity" in combined.supporting
        assert {"no_physiological_progression", "no_causal_inference"} <= set(
            combined.claims[0].limits,
        )
        assert ("fatigue" if language != "es" else "fatiga") not in combined.text.lower()
    for option in choices:
        result = run(
            v3, access=ACCESS, v2_evidence=evidence, language=language,
            transport=provider(json.dumps({"option_id": option.option_id})),
        )
        assert result.mode == "editorial_realization"
    assert evidence.analysis.model_dump() == before


def test_wrong_user_or_workout_v2_evidence_is_never_admitted():
    v3, evidence = calculated_case((330, 320, 310, 300))
    wrong_workout = evidence.analysis.model_copy(deep=True)
    wrong_workout.workout.id = "another-workout"
    for scoped in (replace(evidence, user_id="another-user"),
                   replace(evidence, analysis=wrong_workout), None):
        facts, choices = options(v3, access=ACCESS, v2_evidence=scoped)
        assert not any(f.id in {"interval.regularity", "interval.pace_direction"} for f in facts)
        assert all(o.primary not in {"interval.regularity", "interval.pace_direction"} for o in choices)


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_v2_recorded_observations_remain_available_without_regularity(language):
    v3, evidence = calculated_case((330, 320, 310, 300))
    facts, choices = options(v3, access=ACCESS, language=language)
    assert any(f.id == "effort.first" for f in facts)
    assert choices[0].primary == "effort.first"
    assert all("interval.regularity" not in (o.primary, *o.supporting) for o in choices)


def test_closed_engine_does_not_recompute_science(monkeypatch):
    v3, evidence = calculated_case((330, 320, 310, 300))
    for name in (
        "workout_analysis_v2._effort_regularity",
        "workout_analysis_v2._effort_comparison_cohort",
        "workout_analysis_v2._efforts_comparable",
        "coach_language._repetition_judgment",
        "workout_intelligence_v3.build_workout_intelligence_v3",
    ):
        monkeypatch.setattr(name, Mock(side_effect=AssertionError("No recalculation")))
    result = run(v3, access=ACCESS, v2_evidence=evidence, transport=provider())
    assert result.mode == "editorial_realization"
    assert result.claims[0].id == "interval.pace_direction"


def test_unrelated_legacy_incompatibilities_are_not_relaxed():
    v3, evidence = calculated_case((330, 320, 310, 300))
    facts, _ = options(v3, access=ACCESS, v2_evidence=evidence)
    for support in ("effort.first", "effort.last", "effort.coverage"):
        with pytest.raises(closed.SelectionFailure, match="option_not_admissible"):
            closed._validate_composition(
                "interval.pace_direction", ("interval.regularity", support), facts, "fr",
            )
    facts, _ = options(synthetic_case("comparable_history"),
                       permissions=legacy.HybridPermissions(history=True))
    history = [f.id for f in facts if f.id.startswith(("trend.", "comparison."))]
    assert len(history) >= 2
    with pytest.raises(closed.SelectionFailure, match="option_not_admissible"):
        closed._validate_composition(history[0], (history[1],), facts, "fr")


def test_uncertain_type_cannot_support_threshold_observation():
    v3 = synthetic_case()
    v3.session_classification.confidence = "low"
    _, choices = options(v3)
    assert all("session.kind" not in o.supporting for o in choices)


@pytest.mark.parametrize("limitation", ["weak_comparability", "one_reference"])
def test_insufficient_history_is_not_promoted(limitation):
    v3 = synthetic_case("comparable_history")
    v3.performance_trend.confidence = "none"
    if limitation == "weak_comparability":
        v3.historical_comparison.comparability = "weak"
    else:
        v3.historical_comparison.pace_at_comparable_hr.reference_count = 1
        v3.historical_comparison.hr_at_comparable_pace.reference_count = 1
    facts, choices = options(v3, permissions=legacy.HybridPermissions(history=True))
    assert not any(f.id.startswith(("comparison.", "trend.")) for f in facts)
    assert choices


@pytest.mark.parametrize("authorized", [False, True])
@pytest.mark.parametrize("available", [False, True])
@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_historical_permission_and_sufficiency(authorized, available, language):
    v3 = synthetic_case("comparable_history" if available else "easy")
    permissions = legacy.HybridPermissions(history=authorized)
    facts, choices = options(v3, permissions=permissions, language=language)
    historical = [f for f in facts if f.id.startswith(("trend.", "comparison."))]
    assert bool(historical) is (authorized and available)
    for option in choices:
        selected = (option.primary, *option.supporting)
        assert sum(i.startswith(("trend.", "comparison.")) or i == "session.long"
                   for i in selected) <= 1
        if option.primary.startswith(("trend.", "comparison.")):
            assert {"fr": "terrain et de la météo", "en": "terrain and weather",
                    "es": "terreno y del clima"}[language] in option.text


@pytest.mark.parametrize("status", ["consistent", "deviation", "unavailable"])
@pytest.mark.parametrize("authorized", [False, True])
@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_prescription_only_from_authority(status, authorized, language):
    v3 = synthetic_case("intervals_4x4")
    v3.prescription_assessment.status = status
    facts, choices = options(
        v3, permissions=legacy.HybridPermissions(prescription=authorized), language=language,
    )
    assert any(f.id == "prescription.review" for f in facts) is (
        authorized and status != "unavailable"
    )
    # C378: admitted for other consumers, never part of a Coach editorial option.
    assert all("prescription.review" not in (o.primary, *o.supporting) for o in choices)
    assert choices[0].primary == "interval.count"


@pytest.mark.parametrize("response,reason", [
    ("{", "invalid_json"), ("NaN", "invalid_json"),
    ('{"option_id":"option_99"}', "unknown_option_id"),
    ('{"option_id":" option_1"}', "unknown_option_id"),
    ('{"option_id":"OPTION_1"}', "unknown_option_id"),
    ('{"option_id":"option_1","option_id":"option_2"}', "multiple_response"),
    ('[{"option_id":"option_1"},{"option_id":"option_2"}]', "multiple_response"),
    ('{"option_ids":["option_1"]}', "multiple_response"),
    ('{"option_id":"option_1"} {"option_id":"option_2"}', "multiple_response"),
    ('{"option_id":1}', "invalid_response"),
    ('{"option_id":["option_1","option_2"]}', "multiple_response"),
    ('{"option_id":"option_1","text":"fatigue"}', "invalid_response"),
    ('{"option_id":"option_1","unit":"km"}', "invalid_response"),
    ('{"abstain":true}', "abstention"),
    ('{"abstain":1}', "invalid_response"),
    ('{"abstain":false}', "invalid_response"),
    ('{"abstain":true,"option_id":"option_1"}', "invalid_response"),
    ("x" * 257, "size_limit"),
])
def test_rejections_never_expose_unvalidated_text(response, reason):
    _, choices = options()
    with pytest.raises(closed.SelectionFailure, match=reason):
        closed.validate_choice(response, choices)
    result = run(transport=provider(response))
    assert result.mode == "editorial_realization" and not result.provider_attempted
    assert result.text == closed.select_deterministic_option(choices).text


def test_timeout_unavailable_and_missing_transport(monkeypatch):
    async def timeout(*args):
        raise asyncio.TimeoutError()

    async def error(*args):
        raise RuntimeError("untrusted secret provider text")

    async def unavailable(*args):
        return "untrusted", False, {}

    async def pending(*args):
        await asyncio.Future()

    monkeypatch.setattr(closed, "TIMEOUT_SECONDS", 0.001)
    for transport in (timeout, pending, error, unavailable):
        result = run(transport=transport)
        assert result.mode == "editorial_realization" and not result.provider_attempted
    result = run()
    assert result.mode == "editorial_realization"
    assert result.provider_attempted is False


def test_truncation_and_context_limits(monkeypatch):
    async def truncated(*args):
        return '{"option_id":"option_1"}', True, {"response_truncated": True}

    assert run(transport=truncated).mode == "editorial_realization"
    monkeypatch.setattr(closed, "MAX_CONTEXT_CHARS", 1)
    transport = Mock(side_effect=AssertionError("must not call"))
    result = run(transport=transport)
    assert result.mode == "editorial_realization"
    transport.assert_not_called()


def test_feature_flag_default_off_and_permissions(monkeypatch):
    transport = Mock(side_effect=AssertionError("must not call"))
    monkeypatch.delenv(legacy.FEATURE_FLAG, raising=False)
    assert run(transport=transport).mode == "disabled"
    monkeypatch.setenv(legacy.FEATURE_FLAG, "true")
    assert run(access=None, transport=transport).mode == "denied"
    assert run(access=_access(Tier.FREE), transport=transport).mode == "denied"

    class NoLLM(UserAccess):
        def can(self, feature):
            return feature != "llm_access"

    result = run(access=NoLLM(user_id="owner", tier=Tier.PREMIUM), transport=transport)
    assert result.mode == "denied"
    assert result.reason == "llm_access_not_authorized"
    transport.assert_not_called()


def test_compatibility_option_payload_has_no_identity_or_prose_and_is_not_sent():
    captured = []
    result = run(transport=provider(captured=captured))
    assert result.mode == "editorial_realization"
    assert captured == [] and not result.provider_attempted
    facts, choices = options()
    packet = {"options": [o.provider_option({f.id: f for f in facts}) for o in choices]}
    dumped = json.dumps(packet)
    assert "synthetic-owner" not in dumped and "synthetic-session" not in dumped
    assert "source_paths" not in dumped and "assertion" not in dumped
    assert "text" not in dumped
    assert closed.OptionChoice.model_json_schema()["additionalProperties"] is False
    for option in packet["options"]:
        assert option["clauses"]
        assert all(c["allowed_forms"] == ["direct"] for c in option["clauses"])


@pytest.mark.parametrize("corruption,reason", [
    ("text", "scientific_violation"), ("missing_fact", "option_not_admissible"),
    ("intent", "scientific_violation"), ("form", "option_not_admissible"),
])
def test_all_options_checked_before_call_including_unselected(monkeypatch, corruption, reason):
    _, choices = options()
    last = choices[-1]
    if corruption == "text":
        last = replace(last, claims=(last.claims[0].model_copy(update={"text": "Fatigue"}),))
    elif corruption == "missing_fact":
        last = replace(last, primary="unauthorized")
    elif corruption == "intent":
        last = replace(last, editorial_intent="invent_science")
    else:
        last = replace(last, forms=("invent",))
    monkeypatch.setattr(closed, "build_editorial_options", lambda *args: (*choices[:-1], last))
    transport = Mock(side_effect=AssertionError("must not call"))
    failed(run(transport=transport), reason)
    transport.assert_not_called()


def test_selected_option_rechecked_after_selection(monkeypatch):
    _, choices = options()
    monkeypatch.setattr(closed, "build_editorial_options", lambda *args: choices)

    def corrupt(options):
        selected = options[0]
        selected.claims[0].__dict__["text"] = "Unvalidated text"
        return selected

    monkeypatch.setattr(closed, "select_deterministic_option", corrupt)
    failed(run(), "scientific_violation")


def test_realization_and_option_count_budgets(monkeypatch):
    monkeypatch.setattr(legacy, "MAX_COACH_TEXT_CHARS", 1)
    failed(run(transport=provider()), "size_limit")


def test_empty_duplicate_and_excess_option_sets_fail_before_provider(monkeypatch):
    _, choices = options()
    transport = Mock(side_effect=AssertionError("must not call"))
    for invalid in ((), (choices[0], choices[0]), (choices[0],) * (closed.MAX_OPTIONS + 1)):
        monkeypatch.setattr(closed, "build_editorial_options", lambda *args: invalid)
        failed(run(transport=transport), "option_not_admissible")
    transport.assert_not_called()


def test_legacy_fallback_is_unchanged():
    facts, _ = options()
    before = legacy.select_deterministic_synthesis(facts)
    result = run(transport=provider("{"))
    assert result.mode == "editorial_realization" and not result.provider_attempted
    assert legacy.select_deterministic_synthesis(facts) == before
    assert [c.id for c in before] == ["session.kind", "intensity.position"]
