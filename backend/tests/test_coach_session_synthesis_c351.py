"""C351 presentation regressions; fixtures are not a live Mongo validation."""

from copy import deepcopy
import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from activity_phases import ActivityPhase
from coach_session_synthesis import SessionSynthesisItem, build_session_synthesis
from coach_language import CoachLanguageV1
from workout_analysis_v2 import WorkoutAnalysisV2Response, build_workout_analysis_v2


FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "coach_session_synthesis_c351.json").read_text())
SESSIONS = {session["date"]: session for session in FIXTURE["sessions"]}
LANGUAGES = ("fr", "en", "es")


def phases():
    result = []
    for effort in FIXTURE["interval_efforts"]:
        for kind, row in (("effort", effort), ("recovery", FIXTURE["interval_recovery"])):
            result.append(ActivityPhase(order=len(result), phase_type=kind,
                                        source="explicit-synthetic-fixture", **row))
    return result


def analyze(date, language="en", **kwargs):
    current = deepcopy(SESSIONS[date])
    history = [deepcopy(row) for day, row in SESSIONS.items() if day < date]
    types = {row["id"]: ("treadmill_running" if day == "2026-10-19" else "running")
             for day, row in SESSIONS.items()}
    return build_workout_analysis_v2(
        current, history, language, phases() if date == "2026-10-10" else None,
        activity_types=types, **kwargs,
    )


def items(analysis):
    synthesis = analysis.session_synthesis
    return ([synthesis.primary] if synthesis.primary else []) + synthesis.supporting


@pytest.mark.parametrize("date", SESSIONS)
@pytest.mark.parametrize("language", LANGUAGES)
def test_five_sessions_are_deterministic_traceable_and_compatible(date, language):
    analysis = analyze(date, language)
    assert analysis == analyze(date, language)
    payload = analysis.model_dump(mode="json")
    assert WorkoutAnalysisV2Response.model_validate(payload) == analysis
    rendered = items(analysis)
    assert len(rendered) <= 3
    assert len({item.code for item in rendered}) == len(rendered)
    assert len({item.text for item in rendered}) == len(rendered)
    assert analysis.signals.intensity.available is False
    for item in rendered:
        assert item.source_paths and item.evidence
        assert item.kind in {"observation", "interpretation"}
        for path in item.source_paths:
            if path.startswith("coach_language.conclusions["):
                index = int(path.split("[")[1].rstrip("]"))
                source = analysis.coach_language.conclusions[index]
                assert item.evidence == source.evidence
                assert item.kind == ("interpretation" if source.kind == "conclusion" else "observation")
            elif path.startswith("meaning.factual_observations["):
                index = int(path.split("[")[1].rstrip("]"))
                source = analysis.meaning.factual_observations[index]
                assert item.evidence == source.evidence
                assert item.text == source.text
                assert item.kind == "observation"
            else:
                assert path in {"phase_analysis.efforts", "phase_analysis.recoveries"}
                rows = getattr(analysis.phase_analysis, path.split(".")[1])
                assert item.evidence["count"] == len(rows)
                assert item.evidence["duration_s"] == rows[0].duration_s
                assert item.kind == "observation"
        assert all(math.isfinite(number) for number in item.evidence.values())
        # Only already computed observations, never an invented scientific conclusion.
        assert all(word not in item.text.lower() for word in (
            "lt1", "lt2", "fatigue", "fatiga", "progress", "progrès",
            "physiological drift", "dérive physiologique", "deriva fisiológica",
            "cardiac efficiency", "efficacité cardiaque", "eficiencia cardíaca",
        ))
    old_payload = deepcopy(payload)
    if old_payload["session_synthesis"]["primary"]:
        old_payload["session_synthesis"]["primary"].pop("kind")
    for item in old_payload["session_synthesis"]["supporting"]:
        item.pop("kind")
    old_analysis = WorkoutAnalysisV2Response.model_validate(old_payload)
    assert all(item.kind == "observation" for item in items(old_analysis))
    del old_payload["session_synthesis"]
    assert WorkoutAnalysisV2Response.model_validate(old_payload).session_synthesis is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_ordinary_unknown_structure_has_contextual_history_not_a_fitness_verdict(language):
    analysis = analyze("2026-10-12", language)
    primary = analysis.session_synthesis.primary
    assert not analysis.signals.session_structure.available
    assert primary.code == "coach.history.pace"
    assert primary.kind == "observation"
    similar = analysis.comparison.similar
    assert primary.evidence["pace_sample_count"] == similar.pace_sample_count == 2
    # Reuse V2's two-decimal minute rounding, not a second historical calculation.
    assert primary.evidence["pace_difference_sec_per_km"] == pytest.approx(27.6)
    assert primary.evidence["pace_difference_sec_per_km"] == similar.pace_difference_min_km * 60
    assert primary.evidence["baseline_pace_min_km"] == similar.avg_pace_min_km == 6.89
    assert "7:21/km" in primary.text and "6:53/km" in primary.text
    assert analysis.session_synthesis.supporting == []
    assert [limit.code for limit in analysis.session_synthesis.limitations] == ["synthesis.history_descriptive"]
    assert "synthesis.recorded_totals" not in {item.code for item in items(analysis)}


@pytest.mark.parametrize("language", LANGUAGES)
def test_05_10_and_26_09_abstain_instead_of_repeating_displayed_totals(language):
    for date, distance in (("2026-10-05", 8.44), ("2026-09-26", 10.4)):
        analysis = analyze(date, language)
        assert SESSIONS[date]["distance_km"] == distance
        assert analysis.session_synthesis.status == "insufficient"
        assert analysis.session_synthesis.primary is None
        assert analysis.session_synthesis.supporting == []
        assert analysis.session_synthesis.limitations == []
        assert analysis.session_synthesis.abstention


@pytest.mark.parametrize("language", LANGUAGES)
def test_intervals_prioritize_existing_repetition_judgment_and_recorded_recoveries(language):
    analysis = analyze("2026-10-10", language)
    selected = items(analysis)
    conclusion, = analysis.coach_language.conclusions
    assert selected[0].code == conclusion.code == "coach.repetitions.pace_hr"
    assert selected[0].text == conclusion.text
    assert selected[0].evidence == conclusion.evidence
    assert selected[0].kind == ("interpretation" if conclusion.kind == "conclusion" else "observation")
    assert selected[1].code == "fact.recoveries"
    assert selected[1].evidence == {"count": 4, "duration_s": 180}
    assert selected[1].kind == "observation"
    assert selected[0].evidence["heart_rate_change_bpm"] == 8
    assert "4 × 3 min" in selected[1].text
    assert not any(item.code in ("fact.effort_hr_evolution", "fact.effort_extremes",
                                 "fact.effort_dispersion") for item in selected)
    assert analysis.phase_analysis.effort_regularity.pace_dispersion_sec_per_km == pytest.approx(7.687, abs=.001)


@pytest.mark.parametrize("language", LANGUAGES)
def test_19_10_abstains_without_borrowing_outdoor_metrics(language):
    analysis = analyze("2026-10-19", language)
    assert analysis.session_synthesis.status == "insufficient"
    assert items(analysis) == []
    assert analysis.session_synthesis.abstention
    assert analysis.session_synthesis.limitations == []
    assert analysis.pacing.average_pace_min_km is None


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("structure", [None, "continuous"])
@pytest.mark.parametrize("reference_type", [None, "running", "treadmill_running"])
def test_environment_gate_also_covers_legacy_continuous_history(language, structure, reference_type):
    current = {**SESSIONS["2026-10-12"], "session_structure": structure, "is_race": False}
    history = [{**SESSIONS[day], "session_structure": "continuous", "is_race": False}
               for day in ("2026-09-26", "2026-10-05")]
    types = {current["id"]: "treadmill_running"}
    if reference_type:
        types.update({row["id"]: reference_type for row in history})
    analysis = build_workout_analysis_v2(current, history, language, activity_types=types)
    historical = [item for item in items(analysis) if item.code.startswith("coach.history.")]
    assert bool(historical) is (reference_type == "treadmill_running")


@pytest.mark.parametrize("language", LANGUAGES)
def test_approved_execution_precedes_history_without_duplicate_pacing(language):
    # Independently synthetic measured rows, not assigned to any real dated run.
    current = dict(id="synthetic-continuous", type="run", date="2026-10-20",
                   distance_km=4, duration_minutes=22, avg_pace_min_km=5.5,
                   session_structure="continuous",
                   km_splits=[{"km": index, "pace_min_km": pace}
                              for index, pace in enumerate((5, 5, 6, 6), 1)],
                   split_analysis={"pace_drop": 1})
    history = [{**current, "id": f"synthetic-prior-{day}", "date": f"2026-10-0{day}",
                "avg_pace_min_km": 5} for day in (1, 2)]
    types = {row["id"]: "running" for row in [current, *history]}
    analysis = build_workout_analysis_v2(current, history, language, activity_types=types)
    assert [item.code for item in items(analysis)] == ["coach.pacing", "coach.history.pace"]
    assert analysis.session_synthesis.primary.evidence["second_half_pace_change_sec_per_km"] == 60
    assert "fact.pace_change" in analysis.session_synthesis.primary.replaces_factual_codes
    assert analysis.meaning.factual_observations  # Legacy facts are not removed.
    assert analysis.session_synthesis.primary.kind == "interpretation"


@pytest.mark.parametrize("number", [None, True, float("nan"), float("inf"), "0"])
def test_non_finite_or_missing_evidence_never_enters_contract(number):
    with pytest.raises(ValidationError):
        SessionSynthesisItem(code="test", text="test", evidence={"value": number},
                             source_paths=["summary"])


def test_zero_is_not_missing_and_locales_are_distinct():
    item = SessionSynthesisItem(code="test", text="test", evidence={"change": 0},
                               source_paths=["summary"])
    assert item.evidence == {"change": 0}
    texts = [analyze("2026-10-12", language).session_synthesis.primary.text for language in LANGUAGES]
    assert len(set(texts)) == 3
    assert item.kind == "observation"
    legacy = item.model_dump()
    legacy.pop("kind")
    assert SessionSynthesisItem.model_validate(legacy).kind == "observation"


@pytest.mark.parametrize("language", LANGUAGES)
def test_hr_only_history_keeps_its_own_population_and_explicit_scope(language):
    current = {**SESSIONS["2026-10-12"], "avg_pace_min_km": None}
    history = [deepcopy(SESSIONS[day]) for day in ("2026-09-26", "2026-10-05")]
    types = {row["id"]: "running" for row in [current, *history]}
    analysis = build_workout_analysis_v2(current, history, language, activity_types=types)
    primary = analysis.session_synthesis.primary
    assert primary.code == "coach.history.hr"
    assert primary.evidence["hr_sample_count"] == 2
    assert primary.evidence["current_heart_rate_bpm"] == 127
    assert primary.evidence["baseline_heart_rate_bpm"] == 131.5
    assert [limit.code for limit in analysis.session_synthesis.limitations] == [
        "synthesis.history_descriptive", "synthesis.hr_observation",
    ]
    assert "127" in primary.text and ("131.5" if language == "en" else "131,5") in primary.text


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("unproven_type", [None, "treadmill_running"])
def test_rejected_pace_population_does_not_hide_independently_proven_hr(language, unproven_type):
    current = {**SESSIONS["2026-10-12"], "session_structure": "continuous", "is_race": False}
    history = [{**SESSIONS[day], "session_structure": "continuous", "is_race": False}
               for day in ("2026-09-26", "2026-10-05")]
    # An additional, explicitly synthetic pace-only reference contaminates only
    # the pace environment. Its missing HR must not invalidate the HR population.
    history.append({**history[0], "id": "synthetic-pace-only", "date": "2026-10-01",
                    "avg_heart_rate": None})
    types = {row["id"]: "running" for row in [current, *history[:2]]}
    if unproven_type:
        types[history[2]["id"]] = unproven_type
    analysis = build_workout_analysis_v2(current, history, language, activity_types=types)
    assert analysis.comparison.similar.pace_sample_count == 3
    assert analysis.comparison.similar.hr_sample_count == 2
    primary = analysis.session_synthesis.primary
    assert primary.code == "coach.history.hr"
    assert primary.evidence["hr_sample_count"] == 2
    assert primary.evidence["baseline_heart_rate_bpm"] == 131.5
    assert primary.source_paths == ["coach_language.conclusions[0]"]


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("metrics", [
    {"distance_km": 8.44}, {"duration_minutes": 42},
    {"avg_pace_min_km": 7.2}, {"avg_heart_rate": 129},
    {"distance_km": 10.4, "duration_minutes": 68.3,
     "avg_pace_min_km": 6.6, "avg_heart_rate": 134},
])
def test_metrics_alone_never_become_a_synthesis(language, metrics):
    analysis = build_workout_analysis_v2(
        dict(id="synthetic-totals-only", type="run", date="2026-10-05", **metrics), [], language,
    )
    assert analysis.session_synthesis.status == "insufficient"
    assert items(analysis) == []
    assert analysis.session_synthesis.abstention


def test_removed_totals_cannot_be_reintroduced_by_context_candidates():
    totals = SessionSynthesisItem(code="synthesis.recorded_totals", text="8.44 km",
                                 evidence={"distance_km": 8.44}, source_paths=["summary"])
    synthesis = build_session_synthesis(
        CoachLanguageV1(), [], [(100, "totals", totals)], {}, "en",
    )
    assert synthesis.status == "insufficient"
    assert synthesis.primary is None


def test_item_kind_cannot_claim_an_unsupported_training_judgment():
    with pytest.raises(ValidationError):
        SessionSynthesisItem(code="test", text="test", kind="training_judgment",
                             evidence={"count": 4}, source_paths=["phase_analysis.efforts"])


def test_single_continuous_phase_does_not_repackage_total_duration_as_repetitions():
    workout = dict(id="synthetic-single-phase", type="run", date="2026-10-05",
                   distance_km=8, duration_minutes=48, avg_pace_min_km=6)
    phase = ActivityPhase(order=0, phase_type="effort", source="synthetic",
                          duration_s=2880, distance_m=8000)
    analysis = build_workout_analysis_v2(workout, [], phases=[phase])
    assert analysis.signals.session_structure.code == "continuous"
    assert analysis.session_synthesis.status == "insufficient"


@pytest.mark.parametrize("language", LANGUAGES)
@pytest.mark.parametrize("context_only", [False, True])
def test_rejected_repetition_interpretation_keeps_observations_and_traced_limit(language, context_only):
    measured = phases()
    for index, phase in enumerate(measured):
        if phase.phase_type == "effort":
            measured[index] = phase.model_copy(update={
                "duration_s": 60 if index == 4 else 240,
                "distance_m": 200 if index == 4 else 800,
                "average_hr": None if context_only else phase.average_hr,
            })
    analysis = build_workout_analysis_v2(SESSIONS["2026-10-10"], [], language, measured)
    assert analysis.coach_language.conclusions == []
    assert analysis.coach_language.limitations == ["repetitions.insufficient_comparability"]
    synthesis = analysis.session_synthesis
    assert synthesis.status == "available"
    assert all(item.kind == "observation" for item in items(analysis))
    assert "fact.recoveries" in {item.code for item in items(analysis)}
    # Dispersion remains in the phase section, not duplicated in the synthesis.
    assert "fact.effort_dispersion" not in {item.code for item in items(analysis)}
    assert analysis.phase_analysis.effort_regularity.partial_comparison
    assert analysis.phase_analysis.effort_regularity.pace_dispersion_sec_per_km == 0
    limit = synthesis.limitations[0]
    assert limit.code == "synthesis.repetition_interpretation"
    assert limit.source_paths == ["coach_language.limitations[0]"]
    assert limit.text
    assert WorkoutAnalysisV2Response.model_validate(analysis.model_dump()) == analysis
    if context_only:
        assert [item.code for item in items(analysis)] == ["fact.recoveries"]
