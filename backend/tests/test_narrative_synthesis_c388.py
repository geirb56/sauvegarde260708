"""C388: Narrative V3 restores validated V2 session_synthesis facts.

Deterministic fixtures only (C387B figures); this is not a live runtime validation.
"""

import re

import pytest

import narrative_coach_v3 as narrative
from coach_language import CoachConclusionV1, CoachLanguageV1
from coach_session_synthesis import (
    CoachSessionSynthesisV2, SessionSynthesisItem, SessionSynthesisLimit,
)
from test_coach_session_synthesis_c351 import analyze
from test_narrative_coach_v3 import _intervals, _session

FORBIDDEN = re.compile(
    r"progress|progrès|regress|fatigue|fatiga|drift|dérive|deriva|baisse de forme|"
    r"better efficiency|meilleure efficacité|mejor eficiencia|well executed|bien exécut|bien ejecut",
    re.I,
)
LANGS = ("fr", "en", "es")


def _text(result):
    return " ".join([result.headline, result.analysis, result.interpretation,
                     result.recommendation or "", *result.limitations])


def _history(scope, gap, count, current, baseline, code="coach.history.pace"):
    evidence = {"pace_sample_count": count, "pace_difference_sec_per_km": gap,
                "baseline_pace_min_km": baseline, "current_pace_min_km": current}
    conclusion = CoachConclusionV1(
        code=code, text="v2 prose that must never be copied", evidence=evidence,
        metadata={"comparability": scope, "population": "pace_only",
                  "session_structure": "unknown"},
        category="history", priority=50, replaces_factual_codes=["fact.similar_pace"],
        kind="descriptive")
    coach = CoachLanguageV1(conclusions=[conclusion])
    item = SessionSynthesisItem(
        code=code, text="v2 prose", evidence=evidence,
        source_paths=["coach_language.conclusions[0]"])
    synthesis = CoachSessionSynthesisV2(
        status="available", primary=item,
        limitations=[SessionSynthesisLimit(code="synthesis.history_descriptive", text="x",
                                           source_paths=["coach_language.conclusions[0]"])])
    return coach, synthesis


def _run(v3, lang, coach, synthesis, phases=None):
    return narrative.deterministic_fallback(
        v3, lang, phase_analysis=phases, coach_language=coach, session_synthesis=synthesis)


# Case 1: footing 12/10/2026 (garmin-24701222152), real V2 fixture of C351.
@pytest.mark.parametrize("lang", LANGS)
def test_case1_footing_reports_pace_gap_and_references_without_form_verdict(lang):
    analysis = analyze("2026-10-12", lang)
    v3 = _session(distance_km=9.33, avg_pace_min_km=7 + 21 / 60, avg_hr=127)
    before = narrative.deterministic_fallback(
        v3, lang, phase_analysis=analysis.phase_analysis, coach_language=analysis.coach_language)
    after = _run(v3, lang, analysis.coach_language, analysis.session_synthesis, analysis.phase_analysis)
    primary = analysis.session_synthesis.primary
    assert primary.evidence["pace_difference_sec_per_km"] == pytest.approx(27.6)
    assert "7:21/km" in after.analysis and "6:53/km" in after.analysis
    assert ("27,6" if lang != "en" else "27.6") in after.analysis
    assert "2" in after.analysis
    assert "7:21" not in before.analysis
    # Method sentence no longer leads; headline classification is kept.
    assert after.headline == before.headline
    assert not after.analysis.startswith(before.analysis)
    joined = _text(after)
    assert not FORBIDDEN.search(after.analysis + " ".join(after.limitations))
    assert "split" not in after.analysis.lower()
    # Distance-only scope reserve stays in limitations.
    assert any(w in " ".join(after.limitations).lower() for w in ("distance", "distancia"))
    # V2 prose is never copied.
    assert primary.text not in joined


def test_case1_exact_c387b_gap_displays_french_decimals_without_changing_source():
    coach, synthesis = _history("distance_only", 25.3, 5, 441 / 60, 441 / 60 - 25.3 / 60)
    after = _run(_session(distance_km=9.33), "fr", coach, synthesis)
    assert "25,3 s/km plus lente" in after.analysis and "5 sorties" in after.analysis
    assert "7:21/km" in after.analysis
    assert synthesis.primary.evidence["pace_difference_sec_per_km"] == 25.3
    assert "25.3" not in _text(after)
    assert not FORBIDDEN.search(after.analysis + " ".join(after.limitations))


# Case 3: long run 13/09/2026 (garmin-24346252881): faster than 4 distance-comparable references.
@pytest.mark.parametrize("lang,gap_txt,faster", [
    ("fr", "70,7 s/km plus rapide", "plus rapide"), ("en", "70.7 s/km faster", "faster"),
    ("es", "70,7 s/km más rápido", "más rápido")])
def test_case3_long_run_keeps_gap_and_comparability_limit(lang, gap_txt, faster):
    coach, synthesis = _history("distance_only", -70.7, 4, 343 / 60, 343 / 60 + 70.7 / 60)
    v3 = _session(distance_km=21.27, avg_pace_min_km=343 / 60, avg_hr=160, duration_minutes=122)
    after = _run(v3, lang, coach, synthesis)
    assert gap_txt in after.analysis and "5:43/km" in after.analysis
    assert "4" in after.analysis
    assert any(w in " ".join(after.limitations).lower() for w in ("distance", "distancia"))
    assert not FORBIDDEN.search(after.analysis + " ".join(after.limitations))
    assert after.analysis.startswith(after.analysis.split(" (")[0]) and "5:43/km" in after.analysis.split(".")[0]
    assert after.recommendation is None


# Case 2: interval 10/10/2026 (garmin-24671804067), real V2 fixture.
@pytest.mark.parametrize("lang", LANGS)
def test_case2_intervals_name_repetition_3_and_hr_evolution_without_drift(lang):
    analysis = analyze("2026-10-10", lang)
    v3 = _intervals(4)
    after = _run(v3, lang, analysis.coach_language, analysis.session_synthesis, analysis.phase_analysis)
    comma = lang != "en"
    assert "4:31/km" in after.analysis
    assert re.search(r"\b3\b", after.analysis) and ("17,5" if comma else "17.5") in after.analysis
    assert "151" in after.analysis and "159" in after.analysis
    assert ("6,6" if comma else "6.6") in after.interpretation
    assert not FORBIDDEN.search(after.analysis + after.interpretation)
    # HR evolution is paired with an explicit non-drift reserve.
    assert re.search(r"drift|dérive|deriva", " ".join(after.limitations), re.I)
    assert after.analysis != _intervals(4) and len(after.analysis) > 120
    assert "phases d'effort" not in after.analysis.split(".")[0] or lang != "fr"


# Cross-cutting guards.
def test_absent_or_unavailable_synthesis_is_identical_to_previous_behaviour():
    analysis = analyze("2026-10-10", "en")
    base = narrative.deterministic_fallback(
        _intervals(4), "en", phase_analysis=analysis.phase_analysis,
        coach_language=analysis.coach_language)
    insufficient = CoachSessionSynthesisV2(status="insufficient", abstention="n/a")
    assert _run(_intervals(4), "en", analysis.coach_language, None, analysis.phase_analysis) == base
    assert _run(_intervals(4), "en", analysis.coach_language, insufficient, analysis.phase_analysis) == base
    assert _run(_session(), "en", None, insufficient) == narrative.deterministic_fallback(_session(), "en")


def test_unauthorized_or_tampered_synthesis_is_ignored():
    coach, synthesis = _history("distance_only", -70.7, 4, 5.7, 6.9)
    base = narrative.deterministic_fallback(_session(), "en", coach_language=coach)
    # Evidence no longer matches the validated coach conclusion.
    forged = synthesis.model_copy(deep=True)
    forged.primary.evidence["pace_difference_sec_per_km"] = -10.0
    assert _run(_session(), "en", coach, forged) == base
    # Unknown comparability scope is not an authorized population.
    bad_coach, bad = _history("unknown", -70.7, 4, 5.7, 6.9)
    assert _run(_session(), "en", bad_coach, bad) == narrative.deterministic_fallback(
        _session(), "en", coach_language=bad_coach)
    # Coach conclusion missing entirely.
    assert _run(_session(), "en", None, synthesis) == narrative.deterministic_fallback(_session(), "en")
    # Non-model object is rejected.
    assert _run(_session(), "en", coach, {"primary": {}}) == base
    # History facts are not used for interval sessions.
    assert _run(_intervals(4), "en", coach, synthesis) == narrative.deterministic_fallback(
        _intervals(4), "en", coach_language=coach)


def test_nonfinite_evidence_cannot_reach_text():
    coach, synthesis = _history("distance_only", 10.0, 3, 6.0, 6.2)
    synthesis.primary.evidence["pace_difference_sec_per_km"] = float("nan")
    result = _run(_session(), "en", coach, synthesis)
    assert "nan" not in _text(result).lower()


def test_no_history_no_phases_session_without_synthesis_keeps_generic_text():
    result = narrative.deterministic_fallback(_session(), "fr")
    assert result.analysis and result.generation_mode == "deterministic_fallback"


def test_no_new_prescription_advice_and_premium_contract_unchanged():
    coach, synthesis = _history("distance_only", 25.3, 5, 7.35, 6.93)
    result = _run(_session(), "en", coach, synthesis)
    base = narrative.deterministic_fallback(_session(), "en", coach_language=coach)
    assert result.recommendation == base.recommendation
    assert set(result.model_dump()) == set(base.model_dump())


def test_llm_validation_stays_closed_and_binds_synthesis():
    coach, synthesis = _history("distance_only", 25.3, 5, 7.35, 6.93)
    v3 = _session()
    ctx = narrative.build_narrative_context(v3, "en", coach_language=coach, session_synthesis=synthesis)
    plain = narrative.build_narrative_context(v3, "en", coach_language=coach)
    assert len(ctx["claims"]) > len(plain["claims"])
    payload = {"selections": [{"id": c["id"], "variant": 0} for c in ctx["claims"]]}
    assert narrative.validate_narrative_selection(
        payload, v3, "en", coach_language=coach, session_synthesis=synthesis) is not None
    # A selection built for the synthesis-enriched catalog is rejected without it.
    assert narrative.validate_narrative_selection(payload, v3, "en", coach_language=coach) is None


def test_no_cross_user_state_between_calls():
    coach, synthesis = _history("distance_only", 25.3, 5, 7.35, 6.93)
    _run(_session(), "en", coach, synthesis)
    again = narrative.deterministic_fallback(_session(), "en", coach_language=coach)
    assert "25.3" not in _text(again)
