"""C355 synthetic fixtures: evidence safety, localization and provider isolation."""

import asyncio
from copy import deepcopy
import json
import logging
import re
import sys
from types import SimpleNamespace

import pytest

import narrative_coach_v3 as narrative
from activity_phases import ActivityPhase
from coach_language import CoachLanguageV1
from narrative_coach_v3_models import NarrativeCoachV3
from workout_analysis_v2 import (
    WorkoutAnalysisEffortRegularity,
    WorkoutAnalysisPhaseAnalysis,
    _build_phase_analysis,
    build_workout_analysis_v2,
)
from workout_intelligence_v3 import build_workout_intelligence_v3
from workout_intelligence_v3_models import (
    WIV3CurrentSession,
    WIV3HistoricalSession,
    WIV3PerformanceTrend,
    WIV3PhysiologicalProfile,
    WIV3PrescriptionAssessment,
    WIV3RelativeEffortReference,
    WIV3SessionClassification,
    WIV3ThresholdEstimate,
    WorkoutIntelligenceV3Input,
)


@pytest.fixture(autouse=True)
def isolate(monkeypatch):
    monkeypatch.delenv("C355_NARRATIVE_LLM_ENABLED", raising=False)
    with narrative._CACHE_LOCK:
        narrative._CACHE.clear()
    yield
    with narrative._CACHE_LOCK:
        narrative._CACHE.clear()


def _session(*, history=(), profile=None, **changes):
    values = dict(id="private-workout", date="2026-06-01", sport="run",
                  activity_type="running", avg_hr=140, avg_pace_min_km=6.0,
                  duration_minutes=50, distance_km=8.3,
                  structure="continuous_recorded")
    values.update(changes)
    data = WorkoutIntelligenceV3Input(
        session=WIV3CurrentSession(**values),
        history=list(history),
        profile=profile or WIV3PhysiologicalProfile(),
    )
    return build_workout_intelligence_v3(data)


def _trend_session(kind="improvement"):
    paces = [6.4, 6.4, 6.0] if kind == "improvement" else [6.0] * 3
    history = [
        WIV3HistoricalSession(
            id=f"private-history-{i}", date=day, sport="run",
            activity_type="running", avg_hr=140, avg_pace_min_km=pace,
            duration_minutes=50, distance_km=8.3, structure="continuous_recorded",
        )
        for i, (day, pace) in enumerate(zip(
            ["2026-04-01", "2026-04-15", "2026-05-15"], paces))
    ]
    return _session(history=history)


def _intervals(count=4, regularity=False):
    return _session(
        structure="intervals", effort_count=count, recovery_count=count - 1,
        effort_regularity_available=regularity,
    )


def _selection(v3, language="en", *, phase_analysis=None, coach_language=None):
    return {"selections": [
        {"id": claim["id"], "variant": 0}
        for claim in narrative.build_narrative_context(
            v3, language, phase_analysis=phase_analysis, coach_language=coach_language,
        )["claims"]
    ]}


def _text(result):
    return " ".join([result.headline, result.analysis, result.interpretation,
                     result.recommendation or "", *result.limitations])


def _run(v3, language="en", **kwargs):
    return asyncio.run(narrative.generate_narrative_coach_v3(v3, language, **kwargs))


def _assert_refs_exist(v3, refs, phase_analysis=None, coach_language=None):
    data = v3.model_dump()
    if phase_analysis is not None:
        data["phase_analysis"] = phase_analysis.model_dump()
    if coach_language is not None:
        data["coach_language"] = coach_language.model_dump()
    for ref in refs:
        value = data
        for part in ref.split("."):
            if isinstance(value, list):
                assert part.isdigit() and int(part) < len(value), ref
                value = value[int(part)]
            else:
                assert isinstance(value, dict) and part in value, ref
                value = value[part]


@pytest.mark.parametrize("language,headline,unavailable", [
    ("en", "Session type uncertain", "No reliable prescription"),
    ("fr", "Type de séance incertain", "Aucune comparaison"),
    ("es", "Tipo de sesión incierto", "No hay una comparación"),
])
def test_unknown_no_splits_is_useful_and_localized(language, headline, unavailable):
    v3 = _session(structure="unknown")
    v3.prescription_assessment = WIV3PrescriptionAssessment(status="unavailable")
    result = narrative.deterministic_fallback(v3, language)
    assert result.headline == headline
    assert {
        "en": "does not reliably identify", "fr": "de façon fiable", "es": "con fiabilidad",
    }[language] in result.analysis
    assert unavailable in _text(result)
    assert result.analysis and result.interpretation and result.limitations
    assert result.recommendation is None
    assert result.generation_mode == "deterministic_fallback"
    assert result.language == language
    assert "limit.scope" in {c["id"] for c in narrative.build_narrative_context(v3)["claims"]}
    assert "session_classification.limitations" in result.evidence_refs
    _assert_refs_exist(v3, result.evidence_refs)


@pytest.mark.parametrize("language", ["en", "fr", "es"])
def test_missing_v3_has_complete_none_result(language):
    result = _run(None, language)
    assert result.generation_mode == "none"
    assert result.language == language
    assert result.headline and result.analysis and result.interpretation and result.limitations
    assert result.recommendation is None and result.evidence_refs == []
    assert narrative.validate_narrative_selection({"selections": []}, None, language) is None


@pytest.mark.parametrize("language,normalized", [
    ("FR-fr", "fr"), ("es_ES", "es"), ("en-US", "en"), ("de", "en"),
])
def test_language_normalization(language, normalized):
    assert narrative.deterministic_fallback(_session(), language).language == normalized


def test_genuine_engine_improvement_has_exact_counts_delta_and_caution():
    v3 = _trend_session()
    assert v3.performance_trend.status == "probable_improvement"
    assert v3.performance_trend.confidence == "medium"
    result = narrative.deterministic_fallback(v3)
    assert "probable improvement" in result.interpretation
    assert "4 observations" in result.interpretation
    assert "24 s/km faster" in result.interpretation
    assert f"over {v3.performance_trend.span_days} days" in result.interpretation
    assert "later minus earlier" not in result.interpretation
    assert "not proof" in result.interpretation
    _assert_refs_exist(v3, result.evidence_refs)


def test_genuine_engine_stable_is_not_progress():
    v3 = _trend_session("stable")
    assert v3.performance_trend.status == "stable"
    result = narrative.deterministic_fallback(v3)
    assert "stable trend" in result.interpretation
    assert "4 observations" in result.interpretation
    assert "0 s/km" in result.interpretation or "+0 s/km" in result.interpretation
    assert "does not establish improvement" in result.interpretation
    assert "trend.improvement" not in {c["id"] for c in narrative.build_narrative_context(v3)["claims"]}


@pytest.mark.parametrize("status,confidence,delta", [
    ("insufficient_data", "none", None),
    ("probable_improvement", "low", -24),
    ("probable_improvement", "none", -24),
    ("probable_improvement", "medium", None),
    ("probable_improvement", "medium", 0),
    ("probable_improvement", "medium", 24),
    ("stable", "low", 0),
])
def test_weak_or_incoherent_trend_never_becomes_progress(status, confidence, delta):
    v3 = _session()
    v3.performance_trend = WIV3PerformanceTrend(
        status=status, confidence=confidence, observation_count=4,
        median_change_sec_per_km=delta,
    )
    context = narrative.build_narrative_context(v3)
    assert "trend.improvement" not in {c["id"] for c in context["claims"]}
    assert "insufficient" in narrative.deterministic_fallback(v3).interpretation


def test_decline_retains_delta_and_caution():
    v3 = _session()
    v3.performance_trend = WIV3PerformanceTrend(
        status="possible_decline", confidence="medium", observation_count=5,
        median_change_sec_per_km=19,
    )
    text = narrative.deterministic_fallback(v3).interpretation
    assert "possible decline" in text and "+19 s/km" in text
    assert "not a confirmed loss" in text


@pytest.mark.parametrize("language,relative", [
    ("en", "relatively easy"),
    ("fr", "relativement facile"),
    ("es", "relativamente suave"),
])
def test_easy_history_is_not_below_unknown_lt1(language, relative):
    v3 = _session()
    v3.session_classification = WIV3SessionClassification(
        type="easy_run_probable", decision_tier="individual_history", confidence="low",
        relative_effort=WIV3RelativeEffortReference(
            status="used", relative_position="low", reference_count=8,
        ),
    )
    result = narrative.deterministic_fallback(v3, language)
    assert relative in result.analysis and "8" in result.analysis
    assert "LT1" in " ".join(result.limitations)
    assert "intensity.position" not in {c["id"] for c in narrative.build_narrative_context(v3)["claims"]}
    assert result.recommendation is not None


def test_known_lt1_uses_actual_assessment_not_automatic_threshold_advice():
    profile = WIV3PhysiologicalProfile(
        lt1=WIV3ThresholdEstimate(
            value_bpm=150, source="lab_test", estimated_on="2026-01-01", confidence="high",
        ),
    )
    v3 = _session(profile=profile)
    result = narrative.deterministic_fallback(v3)
    assert "below LT1" in result.analysis
    assert "intensity_assessment.position" in result.evidence_refs
    assert "intensity.lt1_unknown" not in {c["id"] for c in narrative.build_narrative_context(v3)["claims"]}
    assert result.recommendation is None


@pytest.mark.parametrize("count", [4, 6])
@pytest.mark.parametrize("regularity", [False, True])
def test_interval_counts_do_not_invent_regularity(count, regularity):
    v3 = _intervals(count, regularity)
    result = narrative.deterministic_fallback(v3)
    assert f"{count} effort phases" in result.analysis
    assert f"{count - 1} recovery phases" in result.analysis
    assert "regular repetitions" not in result.analysis
    assert "cannot establish how evenly" in result.interpretation
    assert "does not mean they were irregular" in result.interpretation
    assert "regularity" not in " ".join(result.limitations)
    _assert_refs_exist(v3, result.evidence_refs)
    alternate = _selection(v3)
    next(item for item in alternate["selections"] if item["id"] == "interval.count")["variant"] = 1
    assert f"{count} effort phases" in narrative.validate_narrative_selection(alternate, v3).analysis


def _canonical_phases(count, *, paced=True):
    phases = []
    for index in range(count):
        phases.append(ActivityPhase(
            order=len(phases), native_type="EFFORT", phase_type="effort",
            duration_s=180, distance_m=(750 + index * 5) if paced else None,
            average_speed_mps=((750 + index * 5) / 180) if paced else None,
            average_hr=170, source="synthetic",
        ))
        if index < count - 1:
            phases.append(ActivityPhase(
                order=len(phases), native_type="RECOVERY", phase_type="recovery",
                duration_s=120, average_hr=140, source="synthetic",
            ))
    return _build_phase_analysis(phases)


def _canonical_coached_intervals(paces, language="en"):
    phases = []
    for index, pace in enumerate(paces):
        phases.append(ActivityPhase(
            order=len(phases), native_type="EFFORT", phase_type="effort",
            duration_s=180, distance_m=180000 / pace,
            average_speed_mps=1000 / pace, average_hr=170, source="synthetic",
        ))
        if index < len(paces) - 1:
            phases.append(ActivityPhase(
                order=len(phases), native_type="RECOVERY", phase_type="recovery",
                duration_s=120, average_hr=140, source="synthetic",
            ))
    workout = {
        "id": "private-canonical", "date": "2026-06-01", "type": "run",
        "duration_minutes": sum(p.duration_s for p in phases) / 60,
        "distance_km": sum(p.distance_m or 0 for p in phases) / 1000,
        "avg_heart_rate": 150, "avg_pace_min_km": 6,
    }
    return build_workout_analysis_v2(workout, [], language, phases)


@pytest.mark.parametrize("language", ["en", "fr", "es"])
@pytest.mark.parametrize("paces,band,labels", [
    ([240] * 4, "homogeneous", ("Homogeneous paces", "Allures homogènes", "Ritmos homogéneos")),
    ([240, 252, 240, 252], "noticeable", ("Noticeable pace variations", "Variations d'allure perceptibles", "Variaciones de ritmo perceptibles")),
    ([240, 280, 240, 280], "variable", ("Large pace variations", "Variations d'allure importantes", "Variaciones de ritmo importantes")),
])
def test_reuses_actual_canonical_four_repetition_judgment(language, paces, band, labels, monkeypatch):
    v2 = _canonical_coached_intervals(paces, language)
    assert type(v2.coach_language) is CoachLanguageV1
    conclusion = next(c for c in v2.coach_language.conclusions if c.category == "repetitions")
    assert conclusion.metadata["regularity_band"] == band
    before = deepcopy(v2.model_dump())

    def forbidden(*args, **kwargs):
        pytest.fail("Narrative recomputed the canonical judgment")

    monkeypatch.setattr("coach_language._repetition_judgment", forbidden)
    result = narrative.deterministic_fallback(
        _intervals(4), language, phase_analysis=v2.phase_analysis, coach_language=v2.coach_language,
    )
    assert labels[["en", "fr", "es"].index(language)] in result.interpretation
    assert "4" in result.interpretation
    gap = narrative.format_narrative_number(conclusion.evidence["absolute_deviation_sec_per_km"], language)
    assert f"{gap} s/km" in result.interpretation
    assert "No regularity verdict" not in _text(result)
    assert "not by itself establish" not in result.interpretation
    _assert_refs_exist(_intervals(4), result.evidence_refs, v2.phase_analysis, v2.coach_language)
    assert before == v2.model_dump()


@pytest.mark.parametrize("damage", [
    "code", "version", "scope", "metric", "band", "basis", "count",
    "compared", "gap", "median", "kind", "unavailable", "duplicate",
])
def test_repetition_label_fails_closed_on_unapproved_or_ambiguous_judgment(damage):
    v2 = _canonical_coached_intervals([240] * 4)
    coach = v2.coach_language.model_copy(deep=True)
    item = next(c for c in coach.conclusions if c.category == "repetitions")
    if damage == "code":
        item.code = "coach.invented.regularity"
    elif damage in {"version", "scope", "metric", "band", "basis"}:
        key = {
            "version": "judgment_version", "scope": "comparison_scope", "metric": "metric",
            "band": "regularity_band", "basis": "comparability_basis",
        }[damage]
        item.metadata[key] = "unapproved"
    elif damage in {"count", "compared", "gap", "median"}:
        key, value = {
            "count": ("total_effort_count", 6), "compared": ("comparable_effort_count", 3),
            "gap": ("absolute_deviation_sec_per_km", -1), "median": ("median_pace_sec_per_km", 0),
        }[damage]
        item.evidence[key] = value
    elif damage == "kind":
        item.kind = "descriptive"
    elif damage == "unavailable":
        item.available = False
    else:
        coach.conclusions = [item, item.model_copy(deep=True)]
    context = narrative.build_narrative_context(
        _intervals(4), phase_analysis=v2.phase_analysis, coach_language=coach,
    )
    assert "interval.judgment" not in {c["id"] for c in context["claims"]}


def test_six_efforts_without_categorical_coach_judgment_never_inherit_four_label():
    four = _canonical_coached_intervals([240] * 4)
    six = _canonical_phases(6, paced=False)
    result = narrative.deterministic_fallback(
        _intervals(6), phase_analysis=six, coach_language=four.coach_language,
    )
    assert "Homogeneous" not in result.interpretation
    assert "6 effort phases" in result.analysis
    assert "cannot establish how evenly" in result.interpretation


def test_actual_two_effort_comparison_is_not_a_whole_series_judgment():
    v2 = _canonical_coached_intervals([240, 241])
    item = next(c for c in v2.coach_language.conclusions if c.category == "repetitions")
    assert item.metadata["comparison_scope"] == "two_efforts_only"
    result = narrative.deterministic_fallback(
        _intervals(2), phase_analysis=v2.phase_analysis, coach_language=v2.coach_language,
    )
    assert "Homogeneous" not in result.interpretation
    assert "does not by itself establish" in result.interpretation


def test_canonical_judgment_context_and_cache_ignore_prose_but_bind_band(monkeypatch):
    monkeypatch.setenv("C355_NARRATIVE_LLM_ENABLED", "true")
    v2 = _canonical_coached_intervals([240] * 4)
    item = next(c for c in v2.coach_language.conclusions if c.category == "repetitions")
    item.text = "SECRET-ATHLETE needs a threshold test tomorrow and improved."
    item.metadata["athlete"] = "SECRET-EMAIL"
    v3 = _intervals(4)
    calls = []

    async def approved(system, prompt, user, context_type):
        calls.append(prompt)
        assert "SECRET" not in prompt and "threshold test" not in prompt
        return json.dumps({"selections": [
            [index, 0] for index in range(len(json.loads(prompt)["claims"]))
        ]}, separators=(",", ":")), True, {}

    kwargs = dict(phase_analysis=v2.phase_analysis, coach_language=v2.coach_language, transport=approved)
    first = _run(v3, **kwargs)
    assert first.generation_mode == "llm_validated" and "Homogeneous" in first.interpretation
    item.text = "DIFFERENT-SECRET"
    assert _run(v3, **kwargs) == first and len(calls) == 1
    item.metadata["regularity_band"] = "noticeable"
    assert "Noticeable" in _run(v3, **kwargs).interpretation and len(calls) == 2
    assert "interval.judgment" in {
        c["id"] for c in narrative.build_narrative_context(v3, coach_language=v2.coach_language)["claims"]
    }


@pytest.mark.parametrize("language", ["en", "fr", "es"])
def test_four_efforts_reuse_canonical_v2_dispersion_without_regularity_verdict(language, monkeypatch):
    phases = _canonical_phases(4)
    v3 = _intervals(4, True)
    assert phases.effort_regularity.available
    before = deepcopy(phases.model_dump())

    def forbidden_recalculation(*args):
        pytest.fail("Narrative recalculated phase observations")

    monkeypatch.setattr("workout_analysis_v2._effort_regularity", forbidden_recalculation)
    monkeypatch.setattr("workout_analysis_v2._phase_observations", forbidden_recalculation)
    result = narrative.deterministic_fallback(v3, language, phase_analysis=phases)
    spread = narrative.format_narrative_number(phases.effort_regularity.pace_dispersion_sec_per_km, language)
    assert f"{spread} s/km" in result.analysis
    assert "phase_analysis.effort_regularity" in result.evidence_refs
    assert "interval.spread" in {
        c["id"] for c in narrative.build_narrative_context(v3, language, phase_analysis=phases)["claims"]
    }
    assert result.recommendation is None
    _assert_refs_exist(v3, result.evidence_refs, phases)
    assert phases.model_dump() == before
    validated = narrative.validate_narrative_selection(
        _selection(v3, language, phase_analysis=phases), v3, language, phase_analysis=phases,
    )
    assert validated.generation_mode == "llm_validated"
    assert validated.analysis == result.analysis
    assert isinstance(result, NarrativeCoachV3)


def test_six_efforts_without_canonical_judgment_remain_unknown():
    phases = _canonical_phases(6, paced=False)
    assert not phases.effort_regularity.available
    v3 = _intervals(6, False)
    result = narrative.deterministic_fallback(v3, phase_analysis=phases)
    assert "6 effort phases" in result.analysis
    assert "dispersion" not in result.analysis
    assert "cannot establish how evenly" in result.interpretation
    assert "regularity" not in " ".join(result.limitations)
    assert "phase_analysis.effort_regularity.available" in result.evidence_refs
    _assert_refs_exist(v3, result.evidence_refs, phases)


@pytest.mark.parametrize("spread", [0, 4.5])
def test_v2_dispersion_is_reported_verbatim_including_zero(spread):
    phases = WorkoutAnalysisPhaseAnalysis(
        available=True,
        effort_regularity=WorkoutAnalysisEffortRegularity(
            available=True, effort_count=4, comparable_effort_count=4,
            pace_sample_count=4, pace_dispersion_sec_per_km=spread,
        ),
    )
    result = narrative.deterministic_fallback(_intervals(4), phase_analysis=phases)
    assert f"{spread:g} s/km" in result.analysis
    assert "does not by itself establish that they were regular" in result.interpretation


def test_v2_partial_comparison_and_absent_metrics_are_not_full_coverage():
    phases = WorkoutAnalysisPhaseAnalysis(
        available=True,
        effort_regularity=WorkoutAnalysisEffortRegularity(
            available=True, effort_count=4, comparable_effort_count=3,
            pace_sample_count=3, partial_comparison=True, pace_dispersion_sec_per_km=5,
        ),
    )
    result = narrative.deterministic_fallback(_intervals(4), phase_analysis=phases)
    assert "3 of 4 effort phases" in result.analysis
    assert "4 of 4 effort phases" not in result.analysis
    phases.effort_regularity.pace_dispersion_sec_per_km = None
    assert "dispersion" not in narrative.deterministic_fallback(
        _intervals(4), phase_analysis=phases,
    ).analysis


def test_mismatched_phase_counts_do_not_authorize_spread_claims():
    phases = _canonical_phases(4)
    result = narrative.deterministic_fallback(_intervals(6), phase_analysis=phases)
    assert "6 effort phases" in result.analysis and "dispersion" not in result.analysis
    assert "cannot establish how evenly" in result.interpretation
    assert "regularity" not in " ".join(result.limitations)


def test_llm_validation_and_cache_bind_optional_canonical_phase_metrics(monkeypatch):
    monkeypatch.setenv("C355_NARRATIVE_LLM_ENABLED", "true")
    calls = []
    phases = _canonical_phases(4)
    phases.source = "PRIVATE-PHASE-URL"
    v3 = _intervals(4)

    async def approved(system, prompt, user, context_type):
        calls.append(prompt)
        return json.dumps({"selections": [
            {"id": c["id"], "variant": 0} for c in json.loads(prompt)["claims"]
        ]}), True, {}

    first = _run(v3, phase_analysis=phases, transport=approved)
    assert first.generation_mode == "llm_validated"
    assert "phase_analysis.effort_regularity" in first.evidence_refs
    assert _run(v3, phase_analysis=phases, transport=approved) == first
    phases.effort_regularity.pace_dispersion_sec_per_km += 2
    second = _run(v3, phase_analysis=phases, transport=approved)
    assert second.analysis != first.analysis
    assert len(calls) == 2 and all("PRIVATE" not in prompt for prompt in calls)
    without_phase_claims = _selection(v3)
    assert narrative.validate_narrative_selection(
        without_phase_claims, v3, phase_analysis=phases,
    ) is None


@pytest.mark.parametrize("language", ["en", "fr", "es"])
def test_compact_selection_survives_existing_transport_response_limit(monkeypatch, language):
    from llm_coach import _clean_response

    monkeypatch.setenv("C355_NARRATIVE_LLM_ENABLED", "true")
    v3 = _intervals(4)
    phases = _canonical_phases(4)
    context = narrative.build_narrative_context(v3, language, phase_analysis=phases)
    payload = {"selections": [[index, 0] for index in range(len(context["claims"]))]}
    text = json.dumps(payload, separators=(",", ":"))
    assert len(text) < 700
    assert _clean_response(text) == text
    result = narrative.validate_narrative_selection(payload, v3, language, phase_analysis=phases)
    assert result.generation_mode == "llm_validated"

    async def compact_transport(system, prompt, user, context_type):
        assert "under 700 characters" in system
        assert json.loads(prompt) == context
        return text, True, {}

    assert _run(v3, language, phase_analysis=phases, transport=compact_transport) == result


@pytest.mark.parametrize("bad_pair", [
    [True, 0], [-1, 0], [999, 0], [0, True], [0, -1], [0, 999],
    [0], [0, 0, 0], ["session.kind", 0],
])
def test_compact_selection_rejects_invalid_indices(bad_pair):
    v3 = _intervals()
    count = len(narrative.build_narrative_context(v3)["claims"])
    payload = {"selections": [[index, 0] for index in range(count)]}
    payload["selections"][0] = bad_pair
    assert narrative.validate_narrative_selection(payload, v3) is None


def test_compact_selection_cannot_duplicate_or_omit_limitations():
    v3 = _intervals()
    count = len(narrative.build_narrative_context(v3)["claims"])
    payload = {"selections": [[index, 0] for index in range(count)]}
    payload["selections"][-1] = [0, 0]
    assert narrative.validate_narrative_selection(payload, v3) is None


@pytest.mark.parametrize("status,expected", [
    ("consistent", "consistent with"),
    ("deviation", "deviation from"),
    ("unavailable", "conformity cannot be judged"),
    ("indeterminate", "conformity remains indeterminate"),
])
def test_prescription_authority_no_new_plan(status, expected):
    v3 = _session()
    v3.prescription_assessment = WIV3PrescriptionAssessment(status=status)
    result = narrative.deterministic_fallback(v3)
    assert expected in _text(result)
    assert (result.recommendation is not None) == (status == "deviation")
    if status == "deviation":
        assert "does not replace or modify" in result.recommendation


def test_context_does_not_forward_free_text_ids_dates_or_engine_advice():
    v3 = _session()
    v3.workout_id = "SECRET-WORKOUT-ID"
    v3.analyzed_date = "SECRET-DATE"
    v3.coach_assessment.diagnosis.text = "SECRET-NAME recommends threshold test and 6 repetitions"
    v3.coach_assessment.advice = v3.coach_assessment.diagnosis.model_copy()
    v3.session_classification.source_paths = ["SECRET-EMAIL@example.com"]
    v3.prescription_assessment.prescription_id = "SECRET-PRESCRIPTION"
    encoded = json.dumps(narrative.build_narrative_context(v3))
    rendered = _text(narrative.deterministic_fallback(v3))
    assert "SECRET" not in encoded and "SECRET" not in rendered
    assert "threshold test" not in rendered
    assert "6 repetitions" not in rendered
    assert "workout_id" not in encoded and "analyzed_date" not in encoded


def test_loader_coach_language_compatibility_never_consumes_free_text(monkeypatch):
    monkeypatch.setenv("C355_NARRATIVE_LLM_ENABLED", "true")
    v3 = _session()

    class UnreadableCoach:
        def __getattribute__(self, name):
            pytest.fail("Optional coach free text was read")

    async def approved(system, prompt, user, context_type):
        assert "UnreadableCoach" not in prompt
        return json.dumps(_selection(v3)), True, {}

    expected = narrative.deterministic_fallback(v3)
    assert narrative.deterministic_fallback(v3, coach_language=UnreadableCoach()) == expected
    result = _run(v3, coach_language=UnreadableCoach(), transport=approved)
    assert result.analysis == expected.analysis and result.generation_mode == "llm_validated"


@pytest.mark.parametrize("attack", [
    "existing_refs", "invented_refs", "progress", "threshold", "omission",
    "duplicate", "unknown_id", "bool_variant", "negative_variant", "large_variant",
    "string_variant", "nested_id", "none", "wrong_container",
])
def test_evidence_validator_fails_closed_even_for_existing_refs(attack):
    v3 = _session()
    payload = _selection(v3)
    if attack == "existing_refs":
        payload.update(analysis="Your repetitions are regular.", evidence_refs=["session_classification.type"])
    elif attack == "invented_refs":
        payload["evidence_refs"] = ["session.avg_pace_min_km"]
    elif attack in {"progress", "threshold"}:
        payload["selections"][0]["text"] = (
            "You improved dramatically." if attack == "progress" else "Do a threshold test tomorrow."
        )
    elif attack == "omission":
        payload["selections"].pop()
    elif attack == "duplicate":
        payload["selections"][-1] = payload["selections"][0]
    elif attack == "unknown_id":
        payload["selections"][0]["id"] = "trend.improvement"
    elif attack in {"bool_variant", "negative_variant", "large_variant", "string_variant"}:
        payload["selections"][0]["variant"] = {
            "bool_variant": True, "negative_variant": -1,
            "large_variant": 999, "string_variant": "0",
        }[attack]
    elif attack == "nested_id":
        payload["selections"][0]["id"] = {}
    elif attack == "none":
        payload = None
    else:
        payload["selections"] = {}
    assert narrative.validate_narrative_selection(payload, v3) is None


def test_approved_selection_can_reorder_but_cannot_change_language():
    v3 = _intervals()
    payload = _selection(v3, "fr")
    payload["selections"].reverse()
    result = narrative.validate_narrative_selection(payload, v3, "fr")
    assert result.language == "fr" and result.generation_mode == "llm_validated"
    assert "Garmin a enregistré 4" in result.analysis
    _assert_refs_exist(v3, result.evidence_refs)
    payload["language"] = "es"
    assert narrative.validate_narrative_selection(payload, v3, "fr") is None


def test_disabled_is_default_even_with_injected_transport():
    async def forbidden(*args):
        pytest.fail("disabled provider was called")
    result = _run(_session(), transport=forbidden)
    assert result.generation_mode == "deterministic_fallback"


@pytest.mark.parametrize("failure", ["unavailable", "exception", "invalid_json", "oversize", "duplicate_key", "contradiction"])
def test_provider_failures_use_identical_fallback_and_are_not_cached(monkeypatch, failure, caplog):
    monkeypatch.setenv("C355_NARRATIVE_LLM_ENABLED", "true")
    v3 = _session()
    calls = []

    async def failing(*args):
        calls.append(args)
        if failure == "exception":
            raise RuntimeError("PRIVATE-PROVIDER-ERROR")
        text = {
            "unavailable": None,
            "invalid_json": "{PRIVATE-PROVIDER-ERROR",
            "oversize": "X" * (narrative.MAX_RESPONSE_CHARS + 1),
            "duplicate_key": '{"selections":[],"selections":[]}',
            "contradiction": json.dumps({
                "analysis": "You made progress; test LT1 tomorrow.",
                "evidence_refs": ["session_classification.type"],
            }),
        }[failure]
        return text, failure != "unavailable", {}

    with caplog.at_level(logging.INFO, logger=narrative.__name__):
        first = _run(v3, transport=failing)
        second = _run(v3, transport=failing)
    assert first == second == narrative.deterministic_fallback(v3)
    assert len(calls) == 2 and not narrative._CACHE
    assert "PRIVATE" not in caplog.text


def test_outer_timeout_cancels_provider_and_is_not_cached(monkeypatch):
    monkeypatch.setenv("C355_NARRATIVE_LLM_ENABLED", "1")
    monkeypatch.setattr(narrative, "LLM_TIMEOUT_SECONDS", 0.01)
    cancelled = []

    async def blocked(*args):
        try:
            await asyncio.Event().wait()
        finally:
            cancelled.append(True)

    assert _run(_session(), transport=blocked).generation_mode == "deterministic_fallback"
    assert cancelled == [True] and not narrative._CACHE


def test_callers_cancellation_is_not_hidden(monkeypatch):
    monkeypatch.setenv("C355_NARRATIVE_LLM_ENABLED", "true")

    async def cancelled(*args):
        raise asyncio.CancelledError

    with pytest.raises(asyncio.CancelledError):
        _run(_session(), transport=cancelled)


def test_valid_llm_is_cached_without_pii_and_copies_are_isolated(monkeypatch, caplog):
    monkeypatch.setenv("C355_NARRATIVE_LLM_ENABLED", "true")
    v3 = _intervals()
    calls = []

    async def approved(system, prompt, user, context_type):
        calls.append((system, prompt, user, context_type))
        context = json.loads(prompt)
        return json.dumps({"selections": [
            {"id": claim["id"], "variant": len(claim["variants"]) - 1}
            for claim in context["claims"]
        ]}), True, {}

    with caplog.at_level(logging.INFO, logger=narrative.__name__):
        result = _run(v3, transport=approved)
        original = result.model_copy(deep=True)
        result.analysis = "CACHE-POISON"
        result.limitations.clear()
        result.evidence_refs.append("INVENTED")
        changed_id = v3.model_copy(update={"workout_id": "different-private-id"})
        assert _run(changed_id, transport=approved) == original
    assert len(calls) == 1
    assert calls[0][2:] == ("anonymous", "c355_narrative")
    assert "private-workout" not in calls[0][1]
    assert "private-workout" not in caplog.text
    assert "cache_hit" in caplog.text
    assert all(len(key) == 64 for key in narrative._CACHE)


def test_cache_varies_by_evidence_language_and_generation_version(monkeypatch):
    monkeypatch.setenv("C355_NARRATIVE_LLM_ENABLED", "true")
    calls = []

    async def approved(system, prompt, user, context_type):
        calls.append(json.loads(prompt))
        return json.dumps({"selections": [
            {"id": c["id"], "variant": 0} for c in calls[-1]["claims"]
        ]}), True, {}

    first = _run(_intervals(4), "en", transport=approved)
    assert "4 effort" in first.analysis
    assert "6 effort" in _run(_intervals(6), "en", transport=approved).analysis
    assert _run(_intervals(4), "es", transport=approved).language == "es"
    monkeypatch.setattr(narrative, "GENERATION_VERSION", "test-new-version")
    _run(_intervals(4), "en", transport=approved)
    assert len(calls) == 4


def test_lru_is_bounded_and_evicts_oldest(monkeypatch):
    monkeypatch.setenv("C355_NARRATIVE_LLM_ENABLED", "true")
    monkeypatch.setattr(narrative, "CACHE_MAX_ENTRIES", 2)
    calls = []

    async def approved(system, prompt, user, context_type):
        calls.append(prompt)
        return json.dumps({"selections": [
            {"id": c["id"], "variant": 0} for c in json.loads(prompt)["claims"]
        ]}), True, {}

    for count in [4, 5, 4, 6, 5]:
        _run(_intervals(count), transport=approved)
    assert len(calls) == 4 and len(narrative._CACHE) == 2


def test_default_transport_reuses_lazy_llm_call_with_anonymous_identity(monkeypatch):
    monkeypatch.setenv("C355_NARRATIVE_LLM_ENABLED", "true")
    calls = []

    async def fake_call(*args):
        calls.append(args)
        return json.dumps(_selection(_session())), True, {}

    monkeypatch.setitem(sys.modules, "llm_coach", SimpleNamespace(_call_gpt=fake_call))
    assert _run(_session()).generation_mode == "llm_validated"
    assert calls[0][2:] == ("anonymous", "c355_narrative")


def test_narrative_never_mutates_canonical_output():
    v3 = _trend_session()
    before = deepcopy(v3.model_dump())
    context = narrative.build_narrative_context(v3)
    narrative.deterministic_fallback(v3)
    narrative.validate_narrative_selection(_selection(v3), v3)
    _run(v3)
    assert v3.model_dump() == before
    assert context == narrative.build_narrative_context(v3)


@pytest.mark.parametrize("language", ["en", "fr", "es"])
def test_all_required_output_fields_are_deterministic(language):
    v3 = _trend_session()
    first = narrative.deterministic_fallback(v3, language)
    assert first == narrative.deterministic_fallback(v3, language)
    assert set(first.model_dump()) == {
        "headline", "analysis", "interpretation", "recommendation", "limitations",
        "evidence_refs", "language", "generation_mode",
    }
    _assert_refs_exist(v3, first.evidence_refs)


@pytest.mark.parametrize("language", ["en", "fr", "es"])
def test_visible_narratives_have_no_internal_versions_or_generic_classification_filler(language):
    scenarios = [
        (_session(), None), (_trend_session(), None),
        (_intervals(4), _canonical_phases(4)),
        (_intervals(6), _canonical_phases(6, paced=False)),
        (None, None),
    ]
    for v3, phases in scenarios:
        result = narrative.deterministic_fallback(v3, language, phase_analysis=phases)
        text = _text(result)
        assert "V3" not in text and "V2" not in text
        assert "session type assessed" not in text
        assert "session.classification" not in {
            claim["id"] for claim in narrative.build_narrative_context(v3, language, phase_analysis=phases)["claims"]
        }


@pytest.mark.parametrize("basis,expected", [("duration", "similar duration"), ("distance", "similar distance")])
def test_interval_interpretation_explains_actual_comparison_basis(basis, expected):
    phases = _canonical_phases(4)
    phases.effort_regularity.comparability_basis = basis
    result = narrative.deterministic_fallback(_intervals(4), phase_analysis=phases)
    assert "4 of the 4 efforts were grouped" in result.interpretation
    assert expected in result.interpretation
    assert "not by itself establish" in result.interpretation
    assert "phase_analysis.effort_regularity.comparability_basis" in result.evidence_refs
    assert len(result.limitations) == 1


def test_six_unassessed_efforts_do_not_get_a_trend_or_execution_verdict():
    result = narrative.deterministic_fallback(_intervals(6), phase_analysis=_canonical_phases(6, paced=False))
    assert "cannot establish how evenly" in result.interpretation
    assert "improvement" not in result.interpretation
    assert "6 effort phases" in result.analysis
    assert "heart rate" not in result.analysis


@pytest.mark.parametrize("language", ["en", "fr", "es"])
@pytest.mark.parametrize("status", ["consistent", "deviation", "unavailable", "indeterminate"])
def test_relevant_catalog_keeps_narratives_within_six_useful_sentences(language, status):
    judged = _canonical_coached_intervals([240] * 4)
    scenarios = [
        (_session(), None, None), (_trend_session(), None, None),
        (_intervals(4), _canonical_phases(4), None),
        (_intervals(6), _canonical_phases(6, paced=False), None),
        (_intervals(4), judged.phase_analysis, judged.coach_language),
    ]
    for v3, phases, coach in scenarios:
        v3.prescription_assessment = WIV3PrescriptionAssessment(status=status)
        result = narrative.deterministic_fallback(
            v3, language, phase_analysis=phases, coach_language=coach,
        )
        sentences = 1 + sum(len(re.findall(r"[.!?](?:\s|$)", part)) for part in (
            result.analysis, result.interpretation, result.recommendation or "", *result.limitations,
        ))
        assert 3 <= sentences <= 6, result.model_dump()
        assert len(narrative.build_narrative_context(
            v3, language, phase_analysis=phases, coach_language=coach,
        )["claims"]) <= 6


def test_relative_context_deterministically_omits_metric_exhaustiveness():
    v3 = _session()
    v3.session_classification = WIV3SessionClassification(
        type="easy_run_probable", decision_tier="individual_history", confidence="low",
        limitations=["no_splits_whole_session_averages_only"],
        relative_effort=WIV3RelativeEffortReference(
            status="used", relative_position="low", reference_count=12,
        ),
    )
    context = narrative.build_narrative_context(v3)
    ids = {claim["id"] for claim in context["claims"]}
    assert "intensity.relative" in ids and "limit.scope" in ids
    assert not ids.intersection({
        "intensity.hr", "intensity.relative_count", "comparison.pace",
        "intensity.average", "intensity.lt1_unknown", "trend.caution",
    })
    result = narrative.deterministic_fallback(v3)
    assert result.analysis.count(".") == 1
    assert sum("LT1" in limitation for limitation in result.limitations) == 1


@pytest.mark.parametrize("language,advice", [
    ("en", "keep the effort comfortable"),
    ("fr", "garder un effort confortable"),
    ("es", "mantener un esfuerzo cómodo"),
])
def test_relative_easy_low_effort_has_only_cautious_comfort_advice(language, advice):
    v3 = _session()
    v3.session_classification = WIV3SessionClassification(
        type="easy_run_probable", decision_tier="individual_history", confidence="low",
        limitations=["no_splits_whole_session_averages_only"],
        relative_effort=WIV3RelativeEffortReference(
            status="used", relative_position="low", reference_count=12,
        ),
    )
    result = narrative.deterministic_fallback(v3, language)
    assert advice in result.recommendation
    assert all(word not in result.recommendation for word in ("LT1", "LT2", "bpm", "s/km", "min/km"))
    assert "session_classification.relative_effort.relative_position" in result.evidence_refs
    sentences = 1 + sum(len(re.findall(r"[.!?](?:\s|$)", part)) for part in (
        result.analysis, result.interpretation, result.recommendation, *result.limitations,
    ))
    assert sentences <= 6


@pytest.mark.parametrize("change", [
    "not_easy", "not_history", "not_used", "not_low", "no_references", "deviation",
])
def test_comfort_advice_never_overrides_prescription_or_unsupported_effort(change):
    v3 = _session()
    cls = WIV3SessionClassification(
        type="easy_run_probable", decision_tier="individual_history", confidence="low",
        relative_effort=WIV3RelativeEffortReference(
            status="used", relative_position="low", reference_count=12,
        ),
    )
    v3.session_classification = cls
    if change == "not_easy":
        cls.type = "steady_run_probable"
    elif change == "not_history":
        cls.decision_tier = "personal_thresholds"
    elif change == "not_used":
        cls.relative_effort.status = "insufficient_references"
    elif change == "not_low":
        cls.relative_effort.relative_position = "high"
    elif change == "no_references":
        cls.relative_effort.reference_count = 0
    else:
        v3.prescription_assessment = WIV3PrescriptionAssessment(status="deviation")
    result = narrative.deterministic_fallback(v3)
    assert "comfortable" not in (result.recommendation or "")
    assert "advice.comfortable" not in {
        claim["id"] for claim in narrative.build_narrative_context(v3)["claims"]
    }
    if change == "deviation":
        assert "existing Training prescription" in result.recommendation


@pytest.mark.parametrize("language,phrase", [
    ("en", "24 s/km faster"), ("fr", "plus rapide de 24 s/km"),
    ("es", "24 s/km más rápido"),
])
def test_improvement_sign_is_explained_without_signed_delta_jargon(language, phrase):
    v3 = _trend_session()
    result = narrative.deterministic_fallback(v3, language)
    assert phrase in result.interpretation and "-24" not in result.interpretation
    assert str(v3.performance_trend.observation_count) in result.interpretation
    assert str(v3.performance_trend.span_days) in result.interpretation
    assert "performance_trend.span_days" in result.evidence_refs


def test_missing_trend_span_stays_missing():
    v3 = _trend_session()
    v3.performance_trend.span_days = None
    result = narrative.deterministic_fallback(v3)
    assert "24 s/km faster" in result.interpretation
    assert "days" not in result.interpretation and "None" not in result.interpretation
    assert "performance_trend.span_days" not in result.evidence_refs


@pytest.mark.parametrize("language,decimal", [("fr", ","), ("en", "."), ("es", ",")])
@pytest.mark.parametrize("value,signed,expected", [
    (16.5621, False, "16{d}6"),
    (6.600000, False, "6{d}6"),
    (-3.0000, False, "−3"),
    (3, True, "+3"),
    (-6.6, True, "−6{d}6"),
    (0, True, "0"),
    (-0.0, False, "0"),
    (-0.04, True, "0"),
    (0.04, True, "0"),
    (0.06, True, "+0{d}1"),
    (1234.56, False, "1234{d}6"),
])
def test_c357_localized_display_numbers(language, decimal, value, signed, expected):
    assert narrative.format_narrative_number(value, language, signed=signed) == expected.format(d=decimal)


@pytest.mark.parametrize("value", [None, True, False, "", "6.6", float("nan"), float("inf"), -float("inf")])
@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_c357_absent_or_invalid_number_never_becomes_zero(value, language):
    assert narrative.format_narrative_number(value, language) is None


def _polish_scenarios():
    """Synthetic analogues only, not observations from the named Garmin dates."""
    four = _canonical_coached_intervals([240, 241, 240, 241])
    six = _canonical_phases(6, paced=False)
    easy = _session()
    easy.session_classification = WIV3SessionClassification(
        type="easy_run_probable", decision_tier="individual_history", confidence="low",
        limitations=["no_splits_whole_session_averages_only"],
        relative_effort=WIV3RelativeEffortReference(
            status="used", relative_position="low", reference_count=8,
        ),
    )
    return [
        ("10/10/2026", _intervals(4), four.phase_analysis, four.coach_language),
        ("19/09/2026", _intervals(6), six, None),
        ("12/10/2026", easy, None, None),
        ("19/10/2026", _session(structure="unknown", activity_type="treadmill_running"), None, None),
    ]


def test_c357_french_catalog_variants_use_tutoiement():
    scenarios = _polish_scenarios() + [
        ("missing", None, None, None),
        ("stable", _trend_session("stable"), None, None),
        ("improvement", _trend_session(), None, None),
        ("insufficient", _session(), None, None),
    ]
    for _, v3, phases, coach in scenarios:
        for status in ("consistent", "deviation", "unavailable", "indeterminate"):
            if v3 is not None:
                v3.prescription_assessment = WIV3PrescriptionAssessment(status=status)
            context = narrative.build_narrative_context(v3, "fr", phase_analysis=phases, coach_language=coach)
            for claim in context["claims"]:
                for text in claim["variants"]:
                    assert not re.search(r"\b(vous|votre|vos|relisez)\b", text, re.I), text
                    assert not re.search(r"\b(dernières|derniers)\b", text, re.I), text


@pytest.mark.parametrize("language,decimal", [("fr", ","), ("en", "."), ("es", ",")])
def test_c357_rounding_is_display_only_for_canonical_phase_evidence(language, decimal, monkeypatch):
    v2 = _canonical_coached_intervals([240, 241, 240, 241])
    v3 = _intervals(4)
    conclusion = next(c for c in v2.coach_language.conclusions if c.category == "repetitions")
    # Inject an already-judged display metric, not a new regularity calculation.
    conclusion.evidence["absolute_deviation_sec_per_km"] = 16.5621
    before = deepcopy((v2.model_dump(), v3.model_dump()))
    monkeypatch.setattr("coach_language._repetition_judgment",
                        lambda *args, **kwargs: pytest.fail("Narrative must not recalculate"))
    result = narrative.deterministic_fallback(
        v3, language, phase_analysis=v2.phase_analysis, coach_language=v2.coach_language,
    )
    assert f"16{decimal}6 s/km" in result.interpretation
    assert "16.5621" not in _text(result)
    assert (v2.model_dump(), v3.model_dump()) == before
    _assert_refs_exist(v3, result.evidence_refs, v2.phase_analysis, v2.coach_language)


@pytest.mark.parametrize("language,decimal", [("fr", ","), ("en", "."), ("es", ",")])
@pytest.mark.parametrize("status,delta,expected", [
    ("stable", -3.0000, "−3"),
    ("possible_decline", 6.600000, "+6{d}6"),
    ("probable_improvement", -16.5621, "16{d}6"),
])
def test_c357_rounds_trend_prose_without_changing_trend(language, decimal, status, delta, expected):
    v3 = _session()
    v3.performance_trend = WIV3PerformanceTrend(
        status=status, confidence="medium", observation_count=5, median_change_sec_per_km=delta,
    )
    before = deepcopy(v3.model_dump())
    result = narrative.deterministic_fallback(v3, language)
    assert expected.format(d=decimal) + " s/km" in result.interpretation
    assert v3.model_dump() == before


@pytest.mark.parametrize("language,decimal", [("fr", ","), ("en", "."), ("es", ",")])
def test_c357_rounds_measured_hr_and_keeps_absent_hr_absent(language, decimal):
    v3 = _session()
    v3.session_classification = WIV3SessionClassification(
        type="steady_run_probable", decision_tier="personal_thresholds", confidence="medium",
    )
    v3.intensity_assessment.hr_used_bpm = 140.5621
    result = narrative.deterministic_fallback(v3, language)
    assert f"140{decimal}6" in result.analysis
    assert v3.intensity_assessment.hr_used_bpm == 140.5621
    v3.intensity_assessment.hr_used_bpm = None
    result = narrative.deterministic_fallback(v3, language)
    assert "bpm" not in result.analysis and "lpm" not in result.analysis
    assert all(value not in _text(result) for value in ("None", "nan", "inf"))


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_c357_synthetic_scenarios_have_no_redundant_claims_and_keep_uncertainty(language):
    for date, v3, phases, coach in _polish_scenarios():
        context = narrative.build_narrative_context(v3, language, phase_analysis=phases, coach_language=coach)
        ids = [claim["id"] for claim in context["claims"]]
        result = narrative.deterministic_fallback(v3, language, phase_analysis=phases, coach_language=coach)
        parts = [result.analysis, result.interpretation, result.recommendation or "", *result.limitations]
        sentences = [s.strip() for part in parts for s in re.split(r"(?<=[.!?])\s+", part) if s.strip()]
        assert len(sentences) == len(set(sentences))
        assert ids.count("prescription.status") == 1
        assert "interval.regularity" not in ids
        if date == "10/10/2026":
            assert "interval.judgment" in ids and "interval.cohort" not in ids
            assert "4" in result.interpretation
        elif date == "19/09/2026":
            assert "6" in result.analysis and "5" in result.analysis
            assert "interval.execution" in ids and "interval.judgment" not in ids
            assert {"fr": "ne signifie pas", "en": "does not mean", "es": "no significa"}[language] in result.interpretation
        elif date == "12/10/2026":
            assert "intensity.relative" in ids and "intensity.position" not in ids
            assert _text(result).count("LT1") == 1
        else:
            assert "session.unknown" in ids
            assert "intensity.hr" not in ids
        _assert_refs_exist(v3, result.evidence_refs, phases, coach)


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_c357_polished_selection_still_rejects_missing_evidence_and_free_prose(language):
    for _, v3, phases, coach in _polish_scenarios():
        kwargs = dict(phase_analysis=phases, coach_language=coach)
        payload = _selection(v3, language, **kwargs)
        approved = narrative.validate_narrative_selection(payload, v3, language, **kwargs)
        assert approved is not None
        fallback = narrative.deterministic_fallback(v3, language, **kwargs)
        assert approved.model_dump(exclude={"generation_mode"}) == fallback.model_dump(exclude={"generation_mode"})
        for claim in payload["selections"]:
            omitted = {"selections": [entry for entry in payload["selections"] if entry != claim]}
            assert narrative.validate_narrative_selection(omitted, v3, language, **kwargs) is None
        payload["analysis"] = fallback.analysis
        assert narrative.validate_narrative_selection(payload, v3, language, **kwargs) is None


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_c357_default_llm_off_and_api_contracts_remain_intact(language):
    from narrative_coach_v3_models import WorkoutIntelligenceV3NarrativeResponse
    from workout_analysis_v2 import WorkoutAnalysisV2Response

    async def forbidden(*args):
        pytest.fail("Default narrative must not call an LLM")

    v2 = _canonical_coached_intervals([240, 241, 240, 241], language)
    before_v2 = deepcopy(v2.model_dump())
    for _, v3, phases, coach in _polish_scenarios():
        before_v3 = deepcopy(v3.model_dump())
        kwargs = dict(phase_analysis=phases, coach_language=coach)
        result = _run(v3, language, transport=forbidden, **kwargs)
        assert result == narrative.deterministic_fallback(v3, language, **kwargs)
        envelope = WorkoutIntelligenceV3NarrativeResponse(
            workout_id=v3.workout_id, workout_intelligence_v3=v3, narrative_coach_v3=result,
        )
        assert set(envelope.model_dump()) == {"workout_id", "workout_intelligence_v3", "narrative_coach_v3"}
        assert envelope.model_dump()["workout_intelligence_v3"] == before_v3
        assert set(result.model_dump()) == {
            "headline", "analysis", "interpretation", "recommendation", "limitations",
            "evidence_refs", "language", "generation_mode",
        }
    narrative.deterministic_fallback(
        _intervals(4), language, phase_analysis=v2.phase_analysis, coach_language=v2.coach_language,
    )
    assert v2.model_dump() == before_v2
    assert WorkoutAnalysisV2Response.model_validate(before_v2).model_dump() == before_v2
