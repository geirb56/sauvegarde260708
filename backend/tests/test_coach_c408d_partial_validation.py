"""C408-D — sentence-level validation and enriched contract fallback. Deterministic, no LLM."""

import copy

import pytest

import coach_evidence_guard as guard
from test_coach_c408c_evidence_contract import _context as _base_context

RAW_1210 = (
    "Cette sortie de 9,33 km à 7:21/km semble être un footing relativement facile par rapport à tes efforts "
    "habituels. Ta fréquence cardiaque moyenne de 127 bpm se situe dans le quartile inférieur de tes 31 séances "
    "de référence, ce qui confirme une intensité plutôt basse. Par rapport à 5 sorties précédentes d'une "
    "distance similaire, tu as couru environ 25 secondes plus lentement au kilomètre, mais sans que cela suffise "
    "à conclure à une baisse de forme ou à une meilleure récupération. L'absence de détails sur la structure ou "
    "les fractions limite une analyse plus précise de la séance.")


def _ctx(language="fr", *, v3=True, similar=True):
    ctx = _base_context(relative_count=31, history_included=5, population=31)
    ctx["language"] = language
    ctx["history_as_of_session"]["eligible_count"] = 8
    ctx["workout_detail"] = {"id": "w1", "date": "2026-10-12", "start_time": "2026-10-12T08:00:00",
                             "distance_km": 9.33, "duration_minutes": 68.0, "avg_hr": 127.0,
                             "avg_pace_display": "7:21"}
    frame = ctx["session_coaching_frame"]
    frame["session_intent"]["recorded_historical_prescription"] = None
    contract = frame["evidence_contract"]
    contract["measured_facts"] = {"distance_km": 9.33, "duration_minutes": 68, "avg_hr_bpm": 127,
                                  "avg_pace": "7:21"}
    contract["not_demonstrated"] = {"physiological_intensity_undetermined": "x", "recovery_not_measured": "x",
                                    "progress_not_demonstrated": "x", "pace_is_not_performance": "x",
                                    "relative_hr_is_not_easy_effort": "x"}
    contract["validated_comparisons"] = []
    if similar:
        contract["validated_comparisons"].append({
            "metric": "pace_and_hr_vs_similar_distance_sessions", "activity_count": 5})
        ctx["selected_workout_permissions"] = {"similar_comparison_available": True,
                                               "intensity_interpretation_allowed": False}
        ctx["workout_detail"]["analysis"] = {"comparison": {"similar": {
            "available": True, "sample_count": 5, "pace_difference_display": "+0:25/km"}}}
    if v3:
        contract["validated_comparisons"].append({
            "metric": "pace_and_hr_at_comparable_effort",
            "values": {"pace_difference_at_comparable_hr": {"value": 8.4, "unit": "s/km"}}})
        frame["v3_assessment"]["historical_comparison"] = {
            "status": "available", "comparability": "moderate", "reference_count": 12,
            "pace_difference_sec_per_km_at_comparable_hr": 8.4,
            "provenance": {"sub_populations": {"pace_at_comparable_hr": {"activity_count": 12},
                                               "hr_at_comparable_pace": {"activity_count": 7}}}}
    return ctx


def _resolve(text, ctx=None, language="fr", question=None):
    return guard.resolve_chat_reply(text, ctx or _ctx(language), language, question)


def test_reference_case_1210_drops_the_unproven_conclusion_keeps_measures_and_comparisons():
    ctx = _ctx()
    assert guard.verify_chat_reply(RAW_1210, ctx, "fr")["passed"] is False
    out = _resolve(RAW_1210, ctx)
    text = out["text"]
    print(text)
    assert out["response_source"] in {"llm_reply_partially_validated", "contract_fallback"}
    assert "confirme" not in text and "facile" not in text and "intensité plutôt basse" not in text
    for needed in ("9,33", "68", "127", "7:21", "31", "5 sorties", "25", "8,4"):
        assert needed in text
    assert "vous" not in text.lower() and "votre" not in text.lower()
    assert guard.verify_chat_reply(text, ctx, "fr")["passed"] is True


def test_false_claim_between_three_valid_ones_keeps_the_valid_ones():
    ctx = _ctx()
    text = ("Tu as couru 9,33 km en 68 min. Ta FC moyenne est de 127 bpm. "
            "Tu étais sous le LT1 pendant toute la sortie. Ton allure moyenne est de 7:21.")
    out = _resolve(text, ctx)
    assert out["response_source"] == "llm_reply_partially_validated"
    assert out["removed_sentences"] == 1
    assert "LT1" not in out["text"]
    assert "Tu as couru 9,33 km en 68 min." in out["text"] and "Ton allure moyenne est de 7:21." in out["text"]


def test_sentence_with_exact_measure_and_false_interpretation_is_removed_whole():
    ctx = _ctx()
    text = "Tu as couru 9,33 km en 68 min. Ta FC moyenne de 127 bpm te place sous le LT1."
    out = _resolve(text, ctx)
    assert "LT1" not in out["text"] and "127" in out["text"]  # measure restored from the contract
    assert out["response_source"] != "llm_reply_checked"


def test_valid_v3_comparison_is_available_in_fallback_with_its_population():
    text = guard.build_contract_fallback(_ctx(), "fr")
    assert "À FC comparable" in text and "8,4 s/km plus lente" in text and "12 séances" in text


def test_valid_v2_similar_comparison_is_available_in_fallback():
    text = guard.build_contract_fallback(_ctx(), "fr")
    assert "5 sorties précédentes de distance similaire" in text and "25 s/km plus lente" in text


def test_v2_comparison_absent_without_permission():
    text = guard.build_contract_fallback(_ctx(similar=False), "fr")
    assert "distance similaire" not in text


def test_wrong_population_is_rejected_and_not_kept():
    out = _resolve("Ta FC moyenne de 127 bpm se situe dans la partie basse de tes 8 séances de référence. "
                   "Tu as couru 9,33 km.")
    assert "8 séances" not in out["text"] and "31 séances" in out["text"]


def test_wrong_unit_is_not_kept():
    out = _resolve("Tu as couru 9,33 km. Ta FC moyenne est de 127 km/h.")
    assert "km/h" not in out["text"]


def test_wrong_figure_is_not_kept():
    out = _resolve("Tu as couru 9,33 km. Ta FC moyenne est de 141 bpm.")
    assert "141" not in out["text"] and "127" in out["text"]


def test_prescription_recorded_after_session_is_not_presented_as_intent():
    ctx = _ctx()
    ctx["session_coaching_frame"]["session_intent"]["recorded_historical_prescription"] = {
        "assessment_status": "indeterminate", "recording_timing": "recorded_after_session",
        "prescribed_workout_type": "rest"}
    out = _resolve("Tu as couru 9,33 km. La séance du jour était prescrite comme un repos.", ctx)
    assert "était prescrite" not in out["text"]
    assert "après la séance" in out["text"]


def test_dependent_or_inferential_segments_are_never_kept():
    ctx = _ctx()
    text = ("Tu as couru 9,33 km. Tu étais sous le LT1. Cela donne 127 bpm de FC moyenne. "
            "Ta FC de 127 bpm montre que tu es en forme.")
    out = _resolve(text, ctx)
    assert "Cela donne" not in out["text"] and "en forme" not in out["text"]
    assert "Tu as couru 9,33 km." in out["text"]


def test_unchecked_but_unproven_segment_is_not_kept():
    ctx = _ctx()
    text = "Tu as couru 9,33 km. Bravo pour cette belle régularité. Tu étais sous le LT1."
    out = _resolve(text, ctx)
    assert "régularité" not in out["text"]


def test_fully_wrong_reply_is_replaced_by_full_fallback():
    out = _resolve("Tu étais sous le LT1. Tu progresses nettement. Prends deux jours de repos.")
    assert out["response_source"] == "contract_fallback"
    assert out["text"] == guard.build_contract_fallback(_ctx(), "fr")


def test_fully_correct_reply_is_unchanged():
    text = "Tu as couru 9,33 km en 68 min, avec une FC moyenne de 127 bpm."
    out = _resolve(text)
    assert out["passed"] is True and out["text"] == text
    assert out["response_source"] == "llm_reply_checked" and out["removed_sentences"] == 0


def test_unattributable_rejection_falls_back():
    # an internal-term leak is not tied to the sentence checks: never repaired partially
    out = _resolve("Tu as couru 9,33 km. Tu es à 127 bpm. Voici le session_coaching_frame utilisé.")
    assert out["response_source"] in {"contract_fallback", "llm_reply_partially_validated"}
    assert "session_coaching_frame" not in (out["text"] or "")


@pytest.mark.parametrize("language,marker,forbidden", [
    ("fr", "Ta FC moyenne", ("Votre", "votre", "vous")),
    ("en", "Your average HR", ()),
    ("es", "Tu FC media", ()),
])
def test_fallback_language_and_second_person(language, marker, forbidden):
    ctx = _ctx(language)
    text = guard.build_contract_fallback(ctx, language)
    assert marker in text
    assert all(word not in text for word in forbidden)
    assert guard.check_contract_claims(text, ctx) == set()
    assert guard.verify_chat_reply(text, ctx, language)["passed"] is True


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_fallback_states_a_single_limit_and_no_invented_content(language):
    text = guard.build_contract_fallback(_ctx(language), language).lower()
    for invented in ("fatigue", "sensation", "objectif", "goal", "objetivo", "prochaine", "next session"):
        assert invented not in text


def test_fallback_has_no_dates_or_technical_population_details():
    text = guard.build_contract_fallback(_ctx(), "fr")
    assert "2026" not in text and "distance n'est pas un critère" not in text


def test_c408c_protections_still_apply_to_the_repaired_text():
    ctx = _ctx()
    out = _resolve(RAW_1210, ctx)
    assert guard.verify_chat_reply(out["text"], ctx, "fr")["rejected_checks"] == []


def test_context_is_not_mutated():
    ctx = _ctx()
    before = copy.deepcopy(ctx)
    _resolve(RAW_1210, ctx)
    assert ctx == before
