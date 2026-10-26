"""C379: deterministic realization over existing synthetic V2/V3 fixtures."""

import asyncio
from dataclasses import replace
import json
import re
import socket
from unittest.mock import Mock

import pytest

import hybrid_coach_c359 as hybrid
import hybrid_coach_closed_c374 as closed
from narrative_coach_v3 import build_narrative_context
from test_hybrid_coach_c359 import _access, synthetic_case
from test_hybrid_coach_c372 import ACCESS, calculated_case, phases_for
from test_hybrid_coach_c378 import continuous_case, admitted


SCENARIOS = (
    "homogeneous", "irregular", "faster", "slower", "non_comparable",
    "easy", "variable_easy", "long", "tempo", "hr_only", "no_thresholds",
    "history", "no_history", "partial", "insufficient", "v2_v3_missing",
    "faster_odd", "three_slower", "long_history", "zero_history",
    "variable_easy_en", "faster_es",
)


def scenario(name):
    """Return real builder outputs, never hand-written admissible facts."""
    language = "en" if name.endswith("_en") else "es" if name.endswith("_es") else "fr"
    permissions = hybrid.HybridPermissions()
    evidence = None
    paces = {
        "homogeneous": (300, 300, 300, 300),
        "irregular": (300, 330, 295, 325),
        "faster": (330, 320, 310, 300), "faster_es": (330, 320, 310, 300),
        "slower": (300, 310, 320, 330),
        "faster_odd": (340, 330, 320, 310, 300),
        "three_slower": (300, 315, 330),
        "v2_v3_missing": (300, 300, 300, 300),
    }
    if name in paces:
        v3, evidence = calculated_case(paces[name], language=language)
    elif name == "non_comparable":
        v3, evidence = calculated_case(
            phases=phases_for((300, 300, 300), durations=(60, 240, 600)),
        )
    elif name in {"easy", "variable_easy", "variable_easy_en", "tempo"}:
        splits = [6.0] * 10 if name in {"easy", "tempo"} else [5.8] * 5 + [6.3] * 5
        v3, evidence = continuous_case(
            splits, language=language,
            classification="tempo_probable" if name == "tempo" else "easy_run_probable",
        )
    elif name in {"long", "long_history"}:
        v3 = synthetic_case("long")
        permissions = hybrid.HybridPermissions(history=True)
    elif name in {"history", "zero_history"}:
        v3 = synthetic_case("comparable_history")
        permissions = hybrid.HybridPermissions(history=True)
        if name == "zero_history":
            v3.historical_comparison.pace_at_comparable_hr.pace_difference_sec_per_km = 0
            v3.historical_comparison.hr_at_comparable_pace.hr_difference_bpm = 0
    elif name == "no_history":
        v3 = synthetic_case("comparable_history")
    elif name == "hr_only":
        v3 = synthetic_case("no_physiology")
        v3.session_classification.type = "unknown"
    elif name == "no_thresholds":
        v3 = synthetic_case("no_physiology")
    elif name == "partial":
        v3, evidence = calculated_case()
        v3.effort_pace_observations = v3.effort_pace_observations.model_copy(
            update={"available": False},
        )
    elif name == "insufficient":
        v3 = synthetic_case("sparse")
    else:
        raise AssertionError(name)
    if name == "long_history":
        source = synthetic_case("comparable_history")
        v3.historical_comparison = source.historical_comparison
    return v3, evidence, permissions, language


def evaluation_rows():
    rows = []
    for name in SCENARIOS:
        v3, evidence, permissions, language = scenario(name)
        facts = hybrid.build_admissible_facts(
            v3, access=ACCESS if evidence else _access(), permissions=permissions,
            language=language, v2_evidence=evidence,
        )
        claims = hybrid.select_deterministic_synthesis(facts, language)
        advice, reason = hybrid.admissible_advice(claims, facts, language)
        rows.append({
            "name": name, "language": language,
            "facts": [{"id": f.id, "values": dict(f.values),
                       "limits": list(f.important_limits)} for f in facts],
            "selected": [c.id for c in claims],
            "text": hybrid._render([*claims, *([advice] if advice else [])]),
            "advice": advice.model_dump() if advice else None,
            "advice_reason": reason,
        })
    return rows


@pytest.mark.parametrize("name", SCENARIOS)
def test_closed_deterministic_realization_is_admissible_and_repeatable(name, monkeypatch):
    forbidden = Mock(side_effect=AssertionError("No external services or extra LLM calls"))
    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    v3, evidence, permissions, language = scenario(name)
    before = v3.model_dump_json()
    facts = hybrid.build_admissible_facts(
        v3, access=ACCESS if evidence else _access(), permissions=permissions,
        language=language, v2_evidence=evidence,
    )
    options = closed.build_editorial_options(facts, language)
    chosen = closed.select_deterministic_option(options)
    assert chosen == closed.select_deterministic_option(tuple(reversed(options)))
    closed.validate_option(chosen, facts, language)
    assert len(chosen.supporting) <= 2
    assert "prescription.review" not in (chosen.primary, *chosen.supporting)
    index = {f.id: f for f in facts}
    for claim in chosen.claims:
        assert claim.evidence_ids == [claim.id]
        assert claim.limits == list(index[claim.id].important_limits)
        assert claim.evidence_refs == list(index[claim.id].source_paths)
    advice, reason = hybrid.admissible_advice(list(chosen.claims), facts, language)
    assert (chosen.advice, chosen.advice_reason) == (advice, reason)
    assert v3.model_dump_json() == before
    assert not forbidden.called


def test_v2_v3_disagreement_is_missing_input_not_opposite_verdict():
    v3, evidence, _, _ = scenario("v2_v3_missing")
    facts = admitted(v3, evidence)
    assert dict(next(f for f in facts if f.id == "interval.regularity").values)[
        "regularity_band"
    ] == "homogeneous"
    without = build_narrative_context(v3, "fr", phase_analysis=evidence.analysis.phase_analysis)
    with_v2 = build_narrative_context(
        v3, "fr", phase_analysis=evidence.analysis.phase_analysis,
        coach_language=evidence.analysis.coach_language,
    )
    assert any(c["id"] == "interval.execution" for c in without["claims"])
    assert any(c["id"] == "interval.judgment" for c in with_v2["claims"])
    assert not any(c["id"] == "interval.execution" for c in with_v2["claims"])


@pytest.mark.parametrize("language", ("fr", "en", "es"))
def test_zero_comparisons_are_not_promoted_and_limits_survive(language):
    v3, _, permissions, _ = scenario("zero_history")
    facts = hybrid.build_admissible_facts(
        v3, access=_access(), permissions=permissions, language=language,
    )
    options = closed.build_editorial_options(facts, language)
    for option in options:
        assert not any(c.id.startswith("comparison.") for c in option.claims)
        assert not re.search(r"(?<!\d)0 (?:bpm|lpm)", option.text)
        assert "current minus" not in option.text
        assert "moins références" not in option.text


def test_tampered_closed_text_is_never_accepted():
    v3, evidence, _, _ = scenario("faster")
    facts = admitted(v3, evidence)
    chosen = closed.select_deterministic_option(closed.build_editorial_options(facts))
    changed = chosen.claims[0].model_copy(update={"text": "Tu as amélioré ta VO2max."})
    with pytest.raises(closed.SelectionFailure, match="scientific_violation"):
        closed.validate_option(replace(chosen, claims=(changed, *chosen.claims[1:])), facts, "fr")


def test_provider_failure_keeps_same_deterministic_output_and_single_attempt(monkeypatch):
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    calls = []

    async def unavailable(*args):
        calls.append(args)
        return "", False, {}

    v3, evidence, _, _ = scenario("faster")
    result = asyncio.run(hybrid.generate_hybrid_coach(
        v3, access=ACCESS, v2_evidence=evidence, transport=unavailable,
    ))
    facts = admitted(v3, evidence)
    assert len(calls) == 1
    assert result.mode == "deterministic_fallback"
    assert result.text == closed.select_deterministic_option(
        closed.build_editorial_options(facts),
    ).text


def test_deterministic_choice_is_not_longest_text():
    v3 = synthetic_case("easy")
    facts = admitted(v3)
    options = closed.build_editorial_options(facts)
    selected = closed.select_deterministic_option(options)
    assert selected.primary == hybrid.primary_fact_candidates(facts)[0]
    assert selected in options
    assert len(selected.text) < max(len(o.text) for o in options)
    assert json.dumps(selected.provider_option({f.id: f for f in facts}))


@pytest.mark.parametrize("language", ("fr", "en", "es"))
def test_group_average_and_recorded_endpoints_remain_distinct(language):
    v3, evidence = calculated_case((330, 320, 310, 300), language=language)
    facts = admitted(v3, evidence, language=language)
    selected = closed.select_deterministic_option(closed.build_editorial_options(facts, language))
    assert selected.primary == "interval.pace_direction"
    assert selected.supporting == ("effort.first", "effort.last")
    assert {"fr": "20 s/km en moyenne", "en": "20 s/km faster on average",
            "es": "20 s/km de media"}[language] in selected.claims[0].text
    assert {"fr": "5'30/km", "en": "5:30/km", "es": "5:30/km"}[language] in selected.text
    assert {"fr": "5'00/km", "en": "5:00/km", "es": "5:00/km"}[language] in selected.text
    assert "30 s/km" not in selected.claims[0].text
    assert selected.advice is None


def test_selection_and_realization_never_recalculate_science(monkeypatch):
    v3, evidence, _, _ = scenario("faster")
    facts = admitted(v3, evidence)
    for name in (
        "workout_analysis_v2._effort_regularity",
        "coach_language._repetition_judgment",
        "workout_intelligence_v3.build_workout_intelligence_v3",
    ):
        monkeypatch.setattr(name, Mock(side_effect=AssertionError("No recalculation")))
    selected = closed.select_deterministic_option(closed.build_editorial_options(facts))
    assert selected.primary == "interval.pace_direction"
    closed.validate_option(selected, facts, "fr")
