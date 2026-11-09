"""C410 — pre-beta Coach fixes A/B/C on the C408 evidence guard (real V2/V3 engines, no model call)."""

import pytest

import coach_evidence_guard as guard
import test_coach_c408_scenarios as sc
import test_coach_c408d_partial_validation as c408d
from workout_analysis_v2 import ActivityPhase


def _phase(order, kind, duration, distance, hr):
    return ActivityPhase(
        order=order, native_type=kind.upper(), phase_type=kind, duration_s=duration, distance_m=distance,
        average_speed_mps=(distance / duration) if distance else None, average_hr=hr, max_hr=None,
        min_hr=None, source="garmin")


def _intervals(durations):
    rows = [("warmup", 600, None, 130)]
    for index, duration in enumerate(durations):
        rows += [("effort", duration, 1000 + 5 * index, 172 + index), ("recovery", 120, None, 140)]
    rows.append(("cooldown", 600, None, 130))
    return [_phase(i, *row) for i, row in enumerate(rows)]


def _interval_context(durations):
    context, frame, _ = sc._build(
        sc._w("cur", sc.DAY, hr=160, pace=5.2, duration=45, continuous=False), sc._history(),
        phases=_intervals(durations))
    context["session_coaching_frame"] = frame
    return context


# ------------------------------------------------------------------ A: structure of the interval session

PACES = "4:00, 3:59, 3:58 et 3:56"
A_TEXTS = {
    "fr": f"Tu as réalisé 4 × 4 min. Les allures des répétitions étaient de {PACES}.",
    "en": f"You ran 4 x 4 min. The repetition paces were {PACES.replace(' et ', ' and ')}.",
    "es": f"Hiciste 4 × 4 min. Los ritmos de las repeticiones fueron {PACES.replace(' et ', ' y ')}.",
}


def test_contract_carries_the_recorded_structure_only_for_even_efforts():
    even = _interval_context([240] * 4)["session_coaching_frame"]["evidence_contract"]["measured_facts"]
    assert even["recorded_effort_structure"]["effort_count"] == 4
    assert even["recorded_effort_structure"]["effort_duration_s"] == 240
    uneven = _interval_context([240, 180, 240, 120])["session_coaching_frame"]["evidence_contract"]["measured_facts"]
    assert "recorded_effort_structure" not in uneven


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_replay_10_10_structure_and_paces_both_survive(language):
    context = _interval_context([240] * 4)
    out = guard.resolve_chat_reply(A_TEXTS[language], context, language)
    assert out["response_source"] == "llm_reply_checked" and out["rejected_checks"] == []
    assert "4 ×" in out["text"] or "4 x" in out["text"]
    assert "4:00" in out["text"] and "3:56" in out["text"]


@pytest.mark.parametrize("language,bad", [
    ("fr", "Tu as aussi clairement progressé grâce à ce fractionné."),
    ("en", "You clearly made progress thanks to these intervals."),
    ("es", "Claramente progresaste gracias a este fraccionado."),
])
def test_a_distinct_error_does_not_remove_the_valid_structure(language, bad):
    context = _interval_context([240] * 4)
    out = guard.resolve_chat_reply(A_TEXTS[language] + " " + bad, context, language)
    assert out["response_source"] != "llm_reply_checked"
    assert ("4 ×" in out["text"] or "4 x" in out["text"]) and "4:00" in out["text"]
    assert guard.verify_chat_reply(out["text"], context, language)["passed"] is True


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_fallback_restores_the_structure_before_the_paces(language):
    context = _interval_context([240] * 4)
    text = guard.build_contract_fallback(context, language)
    assert "4 × 4 min" in text
    assert text.index("4 × 4 min") < text.index("4:00")


def test_a_wrong_structure_is_never_validated():
    context = _interval_context([240] * 4)
    out = guard.resolve_chat_reply("Tu as réalisé 5 × 4 min. Allures : 4:00, 3:58, 4:02 et 3:59.", context, "fr")
    assert out["response_source"] != "llm_reply_checked"
    assert "5 ×" not in out["text"]
    out = guard.resolve_chat_reply("Tu as réalisé 4 × 6 min.", context, "fr")
    assert "6 min" not in out["text"]


def test_no_structure_fact_is_invented_without_recorded_efforts():
    context, frame, _ = sc._build(sc._w("cur", sc.DAY, hr=133, pace=6.3), sc._history())
    assert "recorded_effort_structure" not in frame["evidence_contract"]["measured_facts"]
    context["session_coaching_frame"] = frame
    assert "×" not in guard.build_contract_fallback(context, "fr")


# ------------------------------------------------------------------ B: probable type is never certain

def _long_run_context(language="fr"):
    context, frame, _ = sc._build(sc._w("cur", sc.DAY, hr=140, pace=6.2, duration=110), sc._history())
    context["session_coaching_frame"] = frame
    context["language"] = language
    return context


B_CERTAIN = {
    "fr": ["C'était clairement une sortie longue.", "Sans aucun doute une sortie longue.",
           "Cette séance était une sortie longue, clairement."],
    "en": ["This was clearly a long run.", "It was definitely a long run.", "It was a long run."],
    "es": ["Fue claramente una tirada larga.", "Es sin duda una tirada larga."],
}
B_PROBABLE = {
    "fr": "Cette séance ressemble à une sortie longue.",
    "en": "This session looks like a long run.",
    "es": "Esta sesión parece una tirada larga.",
}


def test_v3_classification_is_probable_not_certain():
    classification = _long_run_context()["session_coaching_frame"]["v3_assessment"]["classification"]
    assert classification["probable_type"] == "long_run_probable"
    assert classification["confidence"] != "high"


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_replay_13_09_categorical_type_is_rejected_and_replaced_by_the_v3_wording(language):
    context = _long_run_context(language)
    for text in B_CERTAIN[language]:
        assert "type_certainty_not_established" in guard.check_contract_claims(text, context), text
        out = guard.resolve_chat_reply(text, context, language)
        assert out["response_source"] != "llm_reply_checked"
        lowered = out["text"].lower()
        assert "clairement" not in lowered and "clearly" not in lowered and "claramente" not in lowered
        assert any(word in lowered for word in ("probablement", "probably", "probablemente"))
        assert any(word in lowered for word in ("faible", "low", "baja"))  # the engine's confidence
        assert guard.verify_chat_reply(out["text"], context, language)["passed"] is True


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_hedged_type_wording_is_accepted(language):
    context = _long_run_context(language)
    assert "type_certainty_not_established" not in guard.check_contract_claims(B_PROBABLE[language], context)


def test_negated_and_unrelated_type_mentions_are_left_alone():
    context = _long_run_context()
    for text in ("Ce n'était clairement pas une sortie longue.", "Ta dernière sortie longue date de mai."):
        assert "type_certainty_not_established" not in guard.check_contract_claims(text, context)


def test_certainty_is_dropped_but_the_valid_facts_are_kept():
    context = _long_run_context()
    out = guard.resolve_chat_reply(
        "Tu as couru 17,74 km en 110 minutes. C'était clairement une sortie longue. "
        "La durée de cette séance représente 2,2 fois ta durée habituelle (médiane de tes 10 séances précédentes).",
        context, "fr")
    assert "17,74" in out["text"] and "2,2" in out["text"] and "clairement" not in out["text"]
    assert out["text"].count("sortie longue") == 1


def test_no_type_sentence_is_added_when_nothing_categorical_was_said():
    context = _long_run_context()
    assert "classe cette séance" not in guard.build_contract_fallback(context, "fr")


# ------------------------------------------------------------------ C: HR position, one statement, right population

def test_replay_26_10_hr_position_is_stated_once_with_exact_population():
    context = c408d._ctx("fr")
    text = ("Tu as couru 9,33 km à 7:21/km. Ta FC de 127 bpm est dans la partie basse de tes 31 séances de référence. "
            "Ta FC de 127 bpm est basse par rapport à tes 31 séances de référence, soit une position relative basse.")
    assert "redundant_hr_position" in guard.check_contract_claims(text, context)
    out = guard.resolve_chat_reply(text, context, "fr")
    assert out["response_source"] != "llm_reply_checked"
    assert out["text"].count("31 séances") == 1
    assert guard.verify_chat_reply(out["text"], context, "fr")["passed"] is True


@pytest.mark.parametrize("language,text", [
    ("fr", "Ta FC est dans la partie basse de tes 31 séances de référence. Ta FC est basse par rapport à tes 31 séances."),
    ("en", "Your HR is in the lower part of your 31 reference sessions. Your HR is low versus your 31 sessions."),
    ("es", "Tu FC está en la parte baja de tus 31 sesiones de referencia. Tu FC es baja frente a tus 31 sesiones."),
])
def test_redundant_hr_position_is_rejected_in_every_language(language, text):
    context = c408d._ctx(language)
    assert "redundant_hr_position" in guard.check_contract_claims(text, context)
    single = text.split(". ")[0].rstrip(".") + "."
    assert "redundant_hr_position" not in guard.check_contract_claims(single, context)


@pytest.mark.parametrize("language,text", [
    ("fr", "Ta FC est dans la partie basse de tes 31 séances habituelles, comparables en distance."),
    ("fr", "Ta FC est dans la partie basse de tes 31 dernières sorties."),
    ("fr", "Ta FC est basse par rapport à toutes tes séances."),
    ("en", "Your HR is in the lower part of your 31 sessions of the same distance."),
    ("en", "Your HR is low compared with your last 31 runs."),
    ("en", "Your HR is low compared with all your sessions."),
    ("es", "Tu FC está en la parte baja de tus 31 sesiones de la misma distancia."),
    ("es", "Tu FC es baja frente a todas tus sesiones."),
])
def test_misleading_reference_population_is_rejected(language, text):
    assert "population_misdescribed" in guard.check_contract_claims(text, c408d._ctx(language)), text


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_exact_count_and_criteria_remain_in_the_fallback(language):
    text = guard.build_contract_fallback(c408d._ctx(language), language)
    assert "31" in text
    assert text.count("31") == 1  # the reference population is told once
    if language == "fr":
        assert "même environnement" in text and "hors fractionné et compétition" in text


def test_reference_case_12_10_keeps_measures_and_historical_comparisons():
    context = c408d._ctx("fr")
    out = guard.resolve_chat_reply(c408d.RAW_1210, context, "fr")
    for needed in ("9,33", "68", "127", "7:21", "31", "3 sorties", "25", "8,4"):
        assert needed in out["text"]
    assert out["text"].count("31 séances") <= 1
    assert guard.verify_chat_reply(out["text"], context, "fr")["passed"] is True
