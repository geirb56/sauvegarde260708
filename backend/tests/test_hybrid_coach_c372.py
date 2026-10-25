"""C372 synthetic V2-to-hybrid integration; no production services or free prose."""

import asyncio
from dataclasses import replace
import json
import socket
from unittest.mock import Mock

import pytest

from access_control import Tier, UserAccess
from activity_phases import ActivityPhase
import hybrid_coach_c359 as hybrid
from hybrid_coach_editorial_c365 import (
    fact_category, realize_clause, validate_editorial_selection,
)
from hybrid_coach_v2_c372 import ScopedV2Evidence
from test_workout_intelligence_v3 import _db, _w
from workout_analysis_v2 import build_workout_analysis_v2
from workout_intelligence_v3 import build_workout_intelligence_v3, extract_workout_intelligence_input
from workout_intelligence_v3_models import WIV3EffortPaceObservations
import workout_intelligence_v3_service as service


OWNER = "user-a"
ACCESS = UserAccess(user_id=OWNER, tier=Tier.PREMIUM)
HOMOGENEOUS = {
    "fr": "Les allures des répétitions comparables sont homogènes.",
    "en": "The comparable repetitions have homogeneous paces.",
    "es": "Los ritmos de las repeticiones comparables son homogéneos.",
}


@pytest.fixture(autouse=True)
def isolated(monkeypatch):
    monkeypatch.delenv(hybrid.FEATURE_FLAG, raising=False)
    monkeypatch.delenv("C355_NARRATIVE_LLM_ENABLED", raising=False)

    def forbidden(*args, **kwargs):
        raise AssertionError("No real network, Garmin, MongoDB or LLM")

    monkeypatch.setattr(socket, "create_connection", forbidden)
    monkeypatch.setattr(socket.socket, "connect", forbidden)
    monkeypatch.setattr(hybrid, "_transport", forbidden)


def phases_for(paces, *, durations=None, source="garmin"):
    phases = []
    for index, pace in enumerate(paces):
        duration = durations[index] if durations is not None else 240
        phases.extend([
            ActivityPhase(
                order=2 * index, phase_type="effort", duration_s=duration,
                distance_m=duration * 1000 / pace, source=source,
            ),
            ActivityPhase(
                order=2 * index + 1, phase_type="recovery", duration_s=120, source=source,
            ),
        ])
    return phases


def calculated_case(paces=(300, 300, 300, 300), *, phases=None, language="fr"):
    workout = _w("cur", "2026-10-10", continuous=False)
    analysis = build_workout_analysis_v2(
        workout, [], language, phases_for(paces) if phases is None else phases,
    )
    intelligence = build_workout_intelligence_v3(
        extract_workout_intelligence_input(workout, [], v2_analysis=analysis), language,
    )
    return intelligence, ScopedV2Evidence(OWNER, analysis)


def facts(v3, evidence, *, language="fr", access=ACCESS):
    return hybrid.build_admissible_facts(
        v3, access=access, language=language, v2_evidence=evidence,
    )


def regularity(v3, evidence, **kwargs):
    return next((f for f in facts(v3, evidence, **kwargs) if f.id == "interval.regularity"), None)


def change_conclusion(evidence, *, metadata=None, numeric=None, **changes):
    analysis = evidence.analysis.model_copy(deep=True)
    item, = analysis.coach_language.conclusions
    if metadata is not None:
        changes["metadata"] = {**item.metadata, **metadata}
    if numeric is not None:
        changes["evidence"] = {**item.evidence, **numeric}
    analysis.coach_language.conclusions = [item.model_copy(update=changes)]
    return replace(evidence, analysis=analysis)


def selection(primary="interval.regularity", supporting=(), form="direct", **extra):
    return json.dumps({
        "primary": {"fact_id": primary, "form": form},
        "supporting": [{"fact_id": id, "form": "direct"} for id in supporting],
        "editorial_intent": "describe_session", **extra,
    })


def run(v3, evidence, **kwargs):
    return asyncio.run(hybrid.generate_hybrid_coach(
        v3, access=kwargs.pop("access", ACCESS), v2_evidence=evidence, **kwargs,
    ))


def provider(response, captured=None):
    async def transport(system, prompt, user, context_type):
        if captured is not None:
            captured.append(json.loads(prompt))
        return response, True, {}
    return transport


@pytest.mark.parametrize("paces,band", [
    ([300] * 4, "homogeneous"),
    ([300, 300, 340, 300], "noticeable"),
    ([300, 240, 360, 300], "variable"),
])
def test_real_v2_builder_supplies_exact_band_without_recalculation(paces, band, monkeypatch):
    v3, evidence = calculated_case(paces)
    original = evidence.analysis.model_dump()
    item, = evidence.analysis.coach_language.conclusions
    assert item.metadata["regularity_band"] == band
    # Admission must still work when every calculation entry point is forbidden.
    for module, name in (
        ("workout_analysis_v2", "_effort_regularity"),
        ("workout_analysis_v2", "_effort_comparison_cohort"),
        ("workout_analysis_v2", "_efforts_comparable"),
        ("coach_language", "_repetition_judgment"),
    ):
        monkeypatch.setattr(f"{module}.{name}", Mock(side_effect=AssertionError("No recalculation")))
    fact = regularity(v3, evidence)
    assert fact is not None
    assert dict(fact.values)["regularity_band"] == band
    assert dict(fact.values)["source"] == "workout_analysis_v2"
    assert dict(fact.values)["status"] == "available"
    assert fact.confidence == "none"  # V2 supplies no confidence estimate.
    assert fact_category(fact) == "conclusion"
    assert "not_physiological_stability" in fact.important_limits
    assert "all_comparable_recorded_efforts" in fact.usage_conditions
    assert "workout_analysis_v2.coach_language.conclusions[0].metadata.regularity_band" in fact.source_paths
    assert evidence.analysis.model_dump() == original


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_closed_realization_and_explanatory_scope(language, monkeypatch):
    v3, evidence = calculated_case(language=language)
    fact = regularity(v3, evidence, language=language)
    assert realize_clause(fact, "direct", language) == HOMOGENEOUS[language]
    assert "V2" in realize_clause(fact, "explain", language)
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    result = run(v3, evidence, language=language, transport=provider(selection()))
    assert result.mode == "editorial_realization"
    assert result.text == HOMOGENEOUS[language]
    assert result.claims[0].evidence_refs == list(fact.source_paths)
    assert "regularity_verdict_authority_unavailable" not in result.blockers


@pytest.mark.parametrize("paces,fr,en,es", [
    ([300, 300, 340, 300], "perceptibles", "noticeable", "perceptibles"),
    ([300, 240, 360, 300], "importantes", "large", "importantes"),
])
def test_non_homogeneous_bands_keep_their_distinct_labels(paces, fr, en, es):
    v3, evidence = calculated_case(paces)
    for lang, expected in zip(("fr", "en", "es"), (fr, en, es)):
        assert expected in regularity(v3, evidence, language=lang).assertion


@pytest.mark.parametrize("mode", ["absent", "coach_absent", "empty", "unavailable", "phases_absent",
                                  "phases_unavailable", "regularity_unavailable", "partial"])
def test_missing_or_unavailable_never_becomes_a_negative_verdict(mode):
    v3, evidence = calculated_case()
    if mode == "absent":
        evidence = None
    elif mode == "coach_absent":
        evidence.analysis.coach_language = None
    elif mode == "empty":
        evidence.analysis.coach_language.conclusions = []
    elif mode == "unavailable":
        evidence = change_conclusion(evidence, available=False)
    elif mode == "phases_absent":
        evidence.analysis.phase_analysis.phases = []
    elif mode == "phases_unavailable":
        evidence.analysis.phase_analysis.available = False
    elif mode == "regularity_unavailable":
        evidence.analysis.phase_analysis.effort_regularity.available = False
    else:
        evidence.analysis.phase_analysis.effort_regularity.partial_comparison = True
    assert regularity(v3, evidence) is None
    assert "interval.count" in {f.id for f in facts(v3, evidence)}
    assert all("variations d'allure" not in claim.text
               for claim in hybrid.select_deterministic_synthesis(facts(v3, evidence)))


@pytest.mark.parametrize("n", [0, 1, 2])
def test_insufficient_efforts_are_not_series_verdicts(n):
    v3, evidence = calculated_case([300] * n)
    if n == 2:
        item, = evidence.analysis.coach_language.conclusions
        assert item.kind == "descriptive"
        assert item.metadata["regularity_band"] == "not_assessed"
    assert regularity(v3, evidence) is None


def test_actual_non_comparable_efforts_abstain():
    v3, evidence = calculated_case(
        phases=phases_for([300, 300, 300, 300], durations=[60, 120, 240, 480]),
    )
    assert "repetitions.insufficient_comparability" in evidence.analysis.coach_language.limitations
    assert regularity(v3, evidence) is None


@pytest.mark.parametrize("n", [3, 4])
def test_minimum_series_and_pace_hr_variant(n):
    phases = phases_for([300] * n)
    phases = [p.model_copy(update={"average_hr": 150}) for p in phases]
    v3, evidence = calculated_case(phases=phases)
    item, = evidence.analysis.coach_language.conclusions
    assert item.code == "coach.repetitions.pace_hr"
    assert dict(regularity(v3, evidence).values)["efforts"] == n


def test_actual_distance_comparability_is_preserved():
    v3, evidence = calculated_case(
        phases=phases_for([180, 300, 480], durations=[180, 300, 480]),
    )
    assert evidence.analysis.phase_analysis.effort_regularity.comparability_basis == "distance"
    assert dict(regularity(v3, evidence).values)["comparability_basis"] == "distance"


def test_category_uncertain_in_actual_v2_is_not_reclassified():
    v3, evidence = calculated_case([297, 303, 297, 303])
    assert "repetitions.category_uncertain" in evidence.analysis.coach_language.limitations
    assert regularity(v3, evidence) is None


@pytest.mark.parametrize("metadata", [
    {"regularity_band": "regular"},
    {"regularity_band": "physiological_stability"},
    {"judgment_version": "v2"},
    {"comparison_scope": "two_efforts_only"},
    {"metric": "coefficient_of_variation"},
    {"comparability_basis": "duration_invented"},
    {"comparability_basis": "distance"},  # Valid enum, inconsistent with actual V2 basis.
])
def test_unknown_or_incoherent_metadata_is_rejected(metadata):
    v3, evidence = calculated_case()
    assert regularity(v3, change_conclusion(evidence, metadata=metadata)) is None


@pytest.mark.parametrize("changes", [
    {"code": "coach.pacing"},
    {"category": "history"},
    {"kind": "descriptive"},
])
def test_non_repetition_conclusions_are_not_promoted(changes):
    v3, evidence = calculated_case()
    assert regularity(v3, change_conclusion(evidence, **changes)) is None


@pytest.mark.parametrize("numeric", [
    {"total_effort_count": 2}, {"comparable_effort_count": 3},
    {"absolute_deviation_sec_per_km": -1}, {"absolute_deviation_sec_per_km": float("nan")},
    {"median_pace_sec_per_km": 0}, {"median_pace_sec_per_km": float("inf")},
])
def test_invalid_existing_proof_is_rejected(numeric):
    v3, evidence = calculated_case()
    assert regularity(v3, change_conclusion(evidence, numeric=numeric)) is None


def test_ambiguous_duplicate_verdicts_abstain():
    v3, evidence = calculated_case()
    evidence.analysis.coach_language.conclusions *= 2
    assert regularity(v3, evidence) is None


@pytest.mark.parametrize("available", ["true", 1, None])
def test_bypassed_non_boolean_availability_is_not_admitted(available):
    v3, evidence = calculated_case()
    assert regularity(v3, change_conclusion(evidence, available=available)) is None


@pytest.mark.parametrize("mode", ["source", "phase_source", "effort_source", "version",
                                  "workout", "user", "v3_workout", "effort_count"])
def test_provenance_and_identity_are_required(mode):
    v3, evidence = calculated_case()
    if mode == "source":
        evidence = replace(evidence, source="workout_intelligence_v3")
    elif mode == "phase_source":
        evidence.analysis.phase_analysis.source = "synthetic"
    elif mode == "effort_source":
        evidence.analysis.phase_analysis.efforts[0].source = "synthetic"
    elif mode == "version":
        evidence.analysis.version = "v1"
    elif mode == "workout":
        evidence.analysis.workout.id = "other-session"
    elif mode == "user":
        evidence = replace(evidence, user_id="user-b")
    elif mode == "v3_workout":
        v3 = v3.model_copy(update={"workout_id": "other-session"})
    else:
        v3.session_classification.evidence["effort_count"] = 3
    assert regularity(v3, evidence) is None


@pytest.mark.parametrize("available", [False, True])
def test_regularity_independent_of_c371_pace_availability(available):
    v3, evidence = calculated_case()
    if not available:
        v3 = v3.model_copy(update={"effort_pace_observations": WIV3EffortPaceObservations()})
    before = {f.id: f for f in facts(v3, None) if f.id.startswith("effort.")}
    after = {f.id: f for f in facts(v3, evidence) if f.id.startswith("effort.")}
    assert before == after  # C371 facts are not rewritten.
    assert regularity(v3, evidence) is not None
    first = after["effort.first"]
    assert ("recorded_pace" in dict(first.values)) == available


def test_provider_packet_excludes_private_identity_and_raw_v2_prose_and_paces():
    v3, evidence = calculated_case()
    evidence.analysis.coach_language.conclusions[0].text = "EVIL physiological stability"
    packet = hybrid.build_hybrid_context(v3, access=ACCESS, v2_evidence=evidence)
    encoded = json.dumps(packet)
    assert "user-a" not in encoded and '"cur"' not in encoded
    assert "EVIL" not in encoded and "conclusions[" not in encoded
    fact = next(f for f in packet["facts"] if f["evidence_id"] == "interval.regularity")
    assert fact["values"]["regularity_band"] == "homogeneous"
    assert not any("pace" in key for key in fact["values"])
    assert "interval.count" not in {f["evidence_id"] for f in packet["facts"]}
    assert regularity(v3, evidence).assertion == HOMOGENEOUS["fr"]


def test_missing_fact_selection_cannot_fabricate_a_verdict(monkeypatch):
    v3, _ = calculated_case()
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    result = run(v3, None, transport=provider(selection()))
    assert result.mode == "deterministic_fallback"
    assert result.reason == "invalid_editorial_selection"
    assert "interval.regularity" not in {claim.id for claim in result.claims}


@pytest.mark.parametrize("response", [
    selection(text="Your physiological stability proves improved fitness."),
    selection(form="physiological_stability"),
    json.dumps({
        "primary": {"fact_id": "interval.regularity", "form": "direct",
                    "regularity_band": "homogeneous", "interpretation": "No fatigue"},
        "supporting": [], "editorial_intent": "describe_session",
    }),
])
def test_provider_cannot_add_values_or_physiological_interpretation(response, monkeypatch):
    v3, evidence = calculated_case()
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    result = run(v3, evidence, transport=provider(response))
    assert result.mode == "deterministic_fallback"
    assert result.reason == "invalid_editorial_selection"
    assert result.claims[0].id == "interval.regularity"
    assert "physiological stability" not in result.text


@pytest.mark.parametrize("supports", [
    ("effort.first", "effort.last"), ("effort.first", "effort.coverage"), ("interval.count",),
])
def test_regularity_does_not_become_a_repetitive_effort_checklist(supports):
    v3, evidence = calculated_case()
    with pytest.raises(ValueError):
        validate_editorial_selection(selection(supporting=supports), facts(v3, evidence), "fr")


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_deterministic_fallback_prioritizes_v2_without_llm_access(language, monkeypatch):
    v3, evidence = calculated_case()
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    original = UserAccess.can
    monkeypatch.setattr(
        UserAccess, "can", lambda self, feature: feature != "llm_access" and original(self, feature),
    )
    result = run(v3, evidence, language=language)
    assert result.mode == "deterministic_fallback"
    assert not result.provider_attempted
    assert result.claims[0].text == HOMOGENEOUS[language]
    assert result.claims[0].id == "interval.regularity"
    assert len(result.claims) <= 3
    assert len({c.id for c in result.claims} & {
        "interval.count", "effort.first", "effort.last", "effort.coverage",
    }) <= 1


def test_disabled_default_and_denied_access_do_not_attempt_provider():
    v3, evidence = calculated_case()
    assert run(v3, evidence).mode == "disabled"
    free = UserAccess(user_id=OWNER, tier=Tier.FREE)
    assert run(v3, evidence, access=free).mode == "denied"
    assert facts(v3, evidence, access=free) == ()


def test_provider_failure_keeps_deterministic_v2_fallback(monkeypatch):
    v3, evidence = calculated_case()
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")

    async def failed(*args):
        raise TimeoutError()

    result = run(v3, evidence, transport=failed)
    assert result.mode == "deterministic_fallback"
    assert result.reason == "timeout"
    assert result.claims[0].id == "interval.regularity"


def test_provider_cannot_mutate_admitted_snapshot(monkeypatch):
    v3, evidence = calculated_case()
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")

    async def mutate(*args):
        evidence.analysis.coach_language.conclusions[0].metadata["regularity_band"] = "variable"
        return selection(), True, {}

    result = run(v3, evidence, transport=mutate)
    assert result.mode == "editorial_realization"
    assert result.text == HOMOGENEOUS["fr"]
    assert dict(regularity(v3, evidence).values)["regularity_band"] == "variable"


def test_same_pass_scoped_cached_loader_really_calculates_v2_and_preserves_existing_api(monkeypatch):
    workout = _w("cur", "2026-10-10", continuous=False)
    phases = phases_for([300, 240, 360, 300])
    db = _db(workout, [], phases=phases)
    old_db = _db(workout, [], phases=phases)
    real_builder = service.build_workout_analysis_v2
    builder = Mock(wraps=real_builder)
    monkeypatch.setattr(service, "build_workout_analysis_v2", builder)
    result = asyncio.run(service.load_scoped_workout_intelligence_v3_with_v2(
        db=db, user_id=OWNER, workout_id="cur", language="en",
    ))
    builder.assert_called_once()
    loaded, v3, evidence = result
    assert loaded["id"] == v3.workout_id == evidence.analysis.workout.id == "cur"
    assert evidence.user_id == OWNER
    item, = evidence.analysis.coach_language.conclusions
    assert item.metadata["regularity_band"] == "variable"
    assert dict(regularity(v3, evidence).values)["regularity_band"] == "variable"
    _, old_v3 = asyncio.run(service.load_scoped_workout_intelligence_v3(
        db=old_db, user_id=OWNER, workout_id="cur", language="en",
    ))
    assert v3.model_dump() == old_v3.model_dump()
    assert {name: coll.queries for name, coll in vars(db).items()} == {
        name: coll.queries for name, coll in vars(old_db).items()
    }
    assert all(q["user_id"] == OWNER for coll in vars(db).values() for q in coll.queries)
    monkeypatch.setenv(hybrid.FEATURE_FLAG, "true")
    result = run(v3, evidence, language="en", transport=provider(selection()))
    assert result.mode == "editorial_realization"
    assert result.text == "The comparable repetitions show large pace variations."
    assert asyncio.run(service.load_scoped_workout_intelligence_v3_with_v2(
        db=db, user_id="user-b", workout_id="cur", language="en",
    )) is None


def test_loader_missing_phases_does_not_invent_regularity():
    db = _db(_w("cur", "2026-10-10", continuous=False), [])
    _, v3, evidence = asyncio.run(service.load_scoped_workout_intelligence_v3_with_v2(
        db=db, user_id=OWNER, workout_id="cur", language="en",
    ))
    assert not evidence.analysis.phase_analysis.available
    assert regularity(v3, evidence) is None


def test_loader_v2_failure_preserves_existing_unavailable_behavior(monkeypatch):
    db = _db(_w("cur", "2026-10-10", continuous=False), [])
    monkeypatch.setattr(service, "build_workout_analysis_v2", Mock(side_effect=ValueError("unavailable")))
    workout, v3, evidence = asyncio.run(service.load_scoped_workout_intelligence_v3_with_v2(
        db=db, user_id=OWNER, workout_id="cur", language="en",
    ))
    assert workout["id"] == "cur"
    assert v3 is None and evidence is None
