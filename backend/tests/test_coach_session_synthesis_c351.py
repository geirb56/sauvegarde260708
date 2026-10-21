"""C351 presentation regressions; fixtures are not a live Mongo validation."""

from copy import deepcopy
import json
import math
from pathlib import Path

import pytest
from pydantic import ValidationError

from activity_phases import ActivityPhase
from coach_session_synthesis import SessionSynthesisItem
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
        assert all(math.isfinite(number) for number in item.evidence.values())
        # Only already computed observations, never an invented scientific conclusion.
        assert all(word not in item.text.lower() for word in (
            "lt1", "lt2", "fatigue", "fatiga", "progress", "progrès",
            "physiological drift", "dérive physiologique", "deriva fisiológica",
            "cardiac efficiency", "efficacité cardiaque", "eficiencia cardíaca",
        ))
    old_payload = deepcopy(payload)
    del old_payload["session_synthesis"]
    assert WorkoutAnalysisV2Response.model_validate(old_payload).session_synthesis is None


@pytest.mark.parametrize("language", LANGUAGES)
def test_ordinary_unknown_structure_has_contextual_history_not_a_fitness_verdict(language):
    analysis = analyze("2026-10-12", language)
    primary = analysis.session_synthesis.primary
    assert not analysis.signals.session_structure.available
    assert primary.code == "coach.history.pace"
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
def test_05_10_and_26_09_only_report_known_totals_without_manufactured_history(language):
    for date, distance in (("2026-10-05", 8.44), ("2026-09-26", 10.4)):
        analysis = analyze(date, language)
        primary = analysis.session_synthesis.primary
        assert primary.code == "synthesis.recorded_totals"
        assert primary.evidence["distance_km"] == distance
        assert analysis.session_synthesis.supporting == []
    assert "duration_minutes" not in analyze("2026-10-05").session_synthesis.primary.evidence


@pytest.mark.parametrize("language", LANGUAGES)
def test_intervals_prioritize_existing_repetition_judgment_and_recorded_recoveries(language):
    analysis = analyze("2026-10-10", language)
    selected = items(analysis)
    conclusion, = analysis.coach_language.conclusions
    assert selected[0].code == conclusion.code == "coach.repetitions.pace_hr"
    assert selected[0].text == conclusion.text
    assert selected[0].evidence == conclusion.evidence
    assert selected[1].code == "fact.recoveries"
    assert selected[1].evidence == {"count": 4, "duration_s": 180}
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
    assert "127" in primary.text and "131.5" in primary.text


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
