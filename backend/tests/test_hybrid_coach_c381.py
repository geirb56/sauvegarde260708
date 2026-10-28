"""C381: both public editorial entrypoints are pure, stable and evidence-bound."""

import asyncio
from dataclasses import replace
import random
import socket
from unittest.mock import Mock

import pytest

import hybrid_coach_c359 as hybrid
import hybrid_coach_closed_c374 as closed
from narrative_coach_v3 import build_narrative_context
from test_hybrid_coach_c359 import _access, synthetic_case
from test_hybrid_coach_c372 import ACCESS, calculated_case
from test_hybrid_coach_c379 import scenario


CASES = (
    "easy", "long", "comparable_history", "no_physiology",
    "v2_regular_300x4", "v2_faster_330_300", "v2_slower_300_330",
)


def case(name):
    if name.startswith("v2_"):
        paces = {
            "v2_regular_300x4": (300,) * 4,
            "v2_faster_330_300": (330, 320, 310, 300),
            "v2_slower_300_330": (300, 310, 320, 330),
        }[name]
        v3, evidence = calculated_case(paces)
        return v3, evidence, ACCESS, hybrid.HybridPermissions()
    return (synthetic_case(name), None, _access(),
            hybrid.HybridPermissions(history=name in {"long", "comparable_history"}))


@pytest.fixture(autouse=True)
def no_io(monkeypatch):
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    forbidden = Mock(side_effect=AssertionError("C381 forbids provider/network calls"))
    monkeypatch.setattr(hybrid, "_transport", forbidden)
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    yield forbidden
    forbidden.assert_not_called()


@pytest.mark.parametrize("name", CASES)
def test_both_entrypoints_match_under_fact_option_and_id_permutations(name, monkeypatch, no_io):
    v3, evidence, access, permissions = case(name)
    before = v3.model_dump_json(), evidence.analysis.model_dump_json() if evidence else None
    facts = hybrid.build_admissible_facts(
        v3, access=access, permissions=permissions, v2_evidence=evidence,
    )
    expected = closed.select_deterministic_option(closed.build_editorial_options(facts))
    real_builder = closed.build_editorial_options
    # Freeze calculations only after creating the real V2/V3 authority snapshots.
    for target in (
        "workout_analysis_v2._effort_regularity",
        "workout_analysis_v2._effort_comparison_cohort",
        "coach_language._repetition_judgment",
        "workout_intelligence_v3.build_workout_intelligence_v3",
    ):
        monkeypatch.setattr(target, Mock(side_effect=AssertionError("No recalculation")))
    for seed in range(3):
        shuffled = list(facts)
        random.Random(seed).shuffle(shuffled)
        monkeypatch.setattr(hybrid, "build_admissible_facts", lambda *a, **kw: tuple(shuffled))

        def permuted(*args, **kwargs):
            options = [replace(o, option_id=f"opaque_{seed}_{i}")
                       for i, o in enumerate(real_builder(*args, **kwargs))]
            random.Random(seed).shuffle(options)
            return tuple(options)

        monkeypatch.setattr(closed, "build_editorial_options", permuted)
        for entrypoint in (hybrid.generate_hybrid_coach, closed.generate_closed_choice_coach):
            for transport in (None, no_io):
                result = asyncio.run(entrypoint(
                    v3, access=access, permissions=permissions, v2_evidence=evidence,
                    transport=transport,
                ))
                assert result.mode == "editorial_realization"
                assert result.text == expected.text
                assert result.claims == list(expected.claims)
                assert result.advice == expected.advice
                assert result.provider_attempted is False and result.transport_kind == "none"
                assert result.provider_duration_sec is None and result.cost is None
                assert result.verification_scope == "closed_realization"
                assert "production_wiring_not_validated" in result.blockers
                assert "real_llm_editorial_quality_not_evaluated" not in result.blockers
                for claim in result.claims:
                    fact = next(f for f in facts if f.id == claim.id)
                    assert claim.limits == list(fact.important_limits)
                    assert claim.evidence_refs == list(fact.source_paths)
    assert before == (v3.model_dump_json(), evidence.analysis.model_dump_json() if evidence else None)


@pytest.mark.parametrize("name", CASES)
def test_narrative_same_input_and_c379_pure_selection_agree(name):
    v3, evidence, access, permissions = case(name)
    facts = hybrid.build_admissible_facts(
        v3, access=access, permissions=permissions, v2_evidence=evidence,
    )
    selected = closed.select_deterministic_option(closed.build_editorial_options(facts))
    assert hybrid.select_deterministic_synthesis(facts) == list(selected.claims)
    narrative = build_narrative_context(
        v3, "fr", phase_analysis=evidence.analysis.phase_analysis if evidence else None,
        coach_language=evidence.analysis.coach_language if evidence else None,
    )
    if name.startswith("v2_"):
        judgment = next(c for c in narrative["claims"] if c["id"] == "interval.judgment")
        assert ("homogènes" if name == "v2_regular_300x4" else "perceptibles") in str(judgment)
        if name != "v2_regular_300x4":
            assert selected.primary == "interval.pace_direction"
            assert selected.supporting == ("effort.first", "effort.last")
            assert "en moyenne 20 s/km" in selected.claims[0].text
            assert "5'30/km" in selected.text and "5'00/km" in selected.text
            assert "30 s/km" not in selected.claims[0].text
        else:
            assert selected.primary == "interval.regularity" and selected.advice is None
            assert selected.supporting == ("effort.first",)
            assert "4 min" in selected.text and "5'00/km" in selected.text
            assert "effort.last" not in {c.id for c in selected.claims}
    if name == "no_physiology":
        assert selected.primary == "intensity.hr" and "140 bpm" in selected.text
        assert "seuil" not in selected.text
    if name == "easy":
        assert selected.primary == "session.kind" and "probablement" in selected.text
    # Reuse the independent C379 fixture path, not a second scientific calculation.
    if name == "long":
        other, other_evidence, other_permissions, language = scenario(name)
        other_facts = hybrid.build_admissible_facts(
            other, access=ACCESS if other_evidence else _access(),
            permissions=other_permissions, language=language, v2_evidence=other_evidence,
        )
        assert hybrid.select_deterministic_synthesis(other_facts, language)[0].id == selected.primary


def test_absent_v2_verdict_is_not_a_contradictory_irregularity_claim():
    v3, evidence = calculated_case((300,) * 4)
    without = build_narrative_context(v3, "fr", phase_analysis=evidence.analysis.phase_analysis)
    assert not any(c["id"] == "interval.judgment" for c in without["claims"])
    assert "elle ne suffit pas à déterminer" in str(without)
    without_phases = build_narrative_context(v3, "fr")
    assert "ne signifie pas" in str(without_phases)
    with_v2 = build_narrative_context(
        v3, "fr", phase_analysis=evidence.analysis.phase_analysis,
        coach_language=evidence.analysis.coach_language,
    )
    assert "homogènes" in str(with_v2)


@pytest.mark.parametrize("damage", ("missing", "owner", "contradictory", "quality"))
def test_incomplete_or_contradictory_evidence_never_invents_group_comparisons(damage):
    v3, evidence = calculated_case((330, 320, 310, 300))
    if damage == "missing":
        evidence = None
    elif damage == "owner":
        evidence = replace(evidence, user_id="other-owner")
    elif damage == "contradictory":
        evidence.analysis.coach_language.conclusions[0].metadata["direction"] = "slower"
    else:
        evidence.analysis.phase_analysis.effort_regularity.available = False
    facts = hybrid.build_admissible_facts(v3, access=ACCESS, v2_evidence=evidence)
    assert "interval.pace_direction" not in {f.id for f in facts}
    selected = closed.select_deterministic_option(closed.build_editorial_options(facts))
    assert "en moyenne 20 s/km" not in selected.text


def test_empty_and_equal_comparisons_remain_honest():
    assert hybrid.select_deterministic_synthesis(()) == []
    with pytest.raises(closed.SelectionFailure):
        closed.select_deterministic_option(())
    v3 = synthetic_case("comparable_history")
    v3.historical_comparison.pace_at_comparable_hr.pace_difference_sec_per_km = 0
    v3.historical_comparison.hr_at_comparable_pace.hr_difference_bpm = 0
    facts = hybrid.build_admissible_facts(
        v3, access=_access(), permissions=hybrid.HybridPermissions(history=True),
    )
    assert all(not c.id.startswith("comparison.")
               for option in closed.build_editorial_options(facts) for c in option.claims)


@pytest.mark.parametrize("damage", ("classification", "confidence", "corroboration", "history"))
def test_easy_lead_requires_trust_corroboration_and_no_distinctive_evidence(damage):
    v3 = synthetic_case("easy")
    permissions = hybrid.HybridPermissions()
    if damage == "classification":
        v3.session_classification.type = "steady_run_probable"
    elif damage == "confidence":
        v3.session_classification.confidence = "low"
    elif damage == "corroboration":
        v3.intensity_assessment.position = "above_LT2"
    else:
        v3 = synthetic_case("comparable_history")
        permissions = hybrid.HybridPermissions(history=True)
    facts = hybrid.build_admissible_facts(v3, access=_access(), permissions=permissions)
    assert hybrid.select_deterministic_synthesis(facts)[0].id != "session.kind"


@pytest.mark.parametrize("entrypoint", (hybrid.generate_hybrid_coach, closed.generate_closed_choice_coach))
def test_every_candidate_is_checked_before_ranking_and_selected_is_checked_again(entrypoint, monkeypatch):
    events = []
    validator = closed.validate_option
    selector = closed.select_deterministic_option

    def validate(option, facts, language):
        events.append(("validate", option.option_id))
        return validator(option, facts, language)

    def select(options):
        assert {o.option_id for o in options} <= {i for event, i in events if event == "validate"}
        selected = selector(options)
        events.append(("select", selected.option_id))
        return selected

    monkeypatch.setattr(closed, "validate_option", validate)
    monkeypatch.setattr(closed, "select_deterministic_option", select)
    result = asyncio.run(entrypoint(synthetic_case(), access=_access()))
    assert result.mode == "editorial_realization"
    position = next(i for i, event in enumerate(events) if event[0] == "select")
    assert events[position + 1] == ("validate", events[position][1])


@pytest.mark.parametrize("entrypoint", (hybrid.generate_hybrid_coach, closed.generate_closed_choice_coach))
@pytest.mark.parametrize("stage", ("unselected_candidate", "selected"))
def test_tampered_composition_fails_closed_without_provider(entrypoint, stage, monkeypatch, no_io):
    builder = closed.build_editorial_options
    selector = closed.select_deterministic_option

    def corrupt(option):
        return replace(option, claims=(option.claims[0].model_copy(update={
            "text": "Unvalidated physiology",
        }), *option.claims[1:]))

    if stage == "unselected_candidate":
        def invalid_options(*args, **kwargs):
            options = builder(*args, **kwargs)
            return (*options[:-1], corrupt(options[-1]))
        monkeypatch.setattr(closed, "build_editorial_options", invalid_options)
    else:
        monkeypatch.setattr(closed, "select_deterministic_option",
                            lambda options: corrupt(selector(options)))
    result = asyncio.run(entrypoint(synthetic_case(), access=_access(), transport=no_io))
    assert result.text == "" and result.claims == [] and not result.provider_attempted
    assert result.reason in {"scientific_violation", "option_not_admissible"}


def test_semantic_ties_use_content_not_ids_or_input_order():
    v3, evidence, access, permissions = case("easy")
    facts = hybrid.build_admissible_facts(v3, access=access, permissions=permissions)
    selected = closed.select_deterministic_option(closed.build_editorial_options(facts))
    # Selector-only inputs demonstrate a total content tie-break; entrypoints
    # independently rebuild and reject all changed realizations before ranking.
    variants = tuple(replace(
        selected, option_id=f"opaque_{index}",
        claims=(selected.claims[0].model_copy(update={"text": text}), *selected.claims[1:]),
    ) for index, text in enumerate(("Zulu", "Alpha", "Middle")))
    for seed in range(3):
        shuffled = list(variants)
        random.Random(seed).shuffle(shuffled)
        assert closed.select_deterministic_option(tuple(shuffled)).claims[0].text == "Alpha"
        renamed = tuple(replace(o, option_id=f"renamed_{seed}_{i}")
                        for i, o in enumerate(reversed(shuffled)))
        assert closed.select_deterministic_option(renamed).claims[0].text == "Alpha"


@pytest.mark.parametrize("entrypoint", (hybrid.generate_hybrid_coach, closed.generate_closed_choice_coach))
@pytest.mark.parametrize("target", (
    "hybrid_coach_c359.build_admissible_facts",
    "hybrid_coach_closed_c374.build_editorial_options",
    "hybrid_coach_closed_c374.validate_option",
    "hybrid_coach_c359.admissible_advice",
))
def test_invalid_candidate_failures_are_atomic_for_both_entrypoints(entrypoint, target, monkeypatch, no_io):
    monkeypatch.setattr(target, Mock(side_effect=KeyError("private candidate details")))
    result = asyncio.run(entrypoint(synthetic_case(), access=_access(), transport=no_io))
    assert result.reason == "option_not_admissible"
    assert result.text == "" and result.claims == [] and result.advice is None
    assert result.verification_scope == "none" and result.elapsed_ms >= 0
    assert result.transport_kind == "none" and not result.provider_attempted
    assert "private candidate details" not in result.model_dump_json()
