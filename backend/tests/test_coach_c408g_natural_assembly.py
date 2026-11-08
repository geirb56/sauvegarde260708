"""C408-G — natural assembly of the Coach reply: no repeated fact, grouped measures, no pile of reserves,
prescription wording from its real provenance, median-duration comparison. Deterministic, no LLM."""

import copy

import pytest

import coach_evidence_guard as guard
from test_coach_c408d_partial_validation import RAW_1210, _ctx as _ctx_1210

RACE = {"assessment_status": "indeterminate", "planned_date": "2026-09-13", "recording_timing":
        "recording_time_unknown", "recorded_at": "2026-09-13T19:01:00+00:00", "prescribed_workout_type": "race"}
SIMILAR_QUESTION = "Compare cette séance à mes sorties précédentes."


def _ctx_1309(language="fr", prescription=RACE):
    """13/09/2026: 21.27 km, 122 min, 5:43/km, HR 160; similar-distance delta -71 s/km on 4 runs; median 56 min."""
    ctx = _ctx_1210(language, v3=False, similar=True)
    ctx["workout_detail"].update({"date": "2026-09-13", "start_time": "2026-09-13",
                                  "distance_km": 21.27, "duration_minutes": 122.0, "avg_hr": 160.0,
                                  "avg_pace_display": "5:43"})
    frame = ctx["session_coaching_frame"]
    contract = frame["evidence_contract"]
    contract["measured_facts"] = {"distance_km": 21.27, "duration_minutes": 122, "avg_hr_bpm": 160,
                                  "avg_pace": "5:43"}
    contract["validated_comparisons"] = [
        {"metric": "pace_and_hr_vs_similar_distance_sessions", "activity_count": 4, "pace_sample_count": 4,
         "pace_difference_display": "-1:11/km"},
        {"metric": "session_duration_vs_habitual_median_duration", "ratio": 2.18, "reference_count": 33,
         "session_duration_minutes": 122.0, "habitual_duration_minutes": 56.0,
         "habitual_definition": "median of earlier sessions"}]
    ctx["workout_detail"]["analysis"] = {"comparison": {"similar": {
        "available": True, "sample_count": 4, "pace_sample_count": 4, "pace_difference_display": "-1:11/km"}}}
    frame["session_intent"]["recorded_historical_prescription"] = copy.deepcopy(prescription)
    return ctx


def _resolve(text, ctx, language="fr", question=None):
    return guard.resolve_chat_reply(text, ctx, language, question)


SIM_NATURAL = ("Par rapport à tes quatre sorties précédentes de distance similaire, tu as été nettement plus "
               "rapide, de plus d'une minute par kilomètre en moyenne.")
SIM_FIGURE = "Par rapport à tes 4 sorties précédentes de distance similaire, ton allure est de 71 s/km plus rapide."
BAD = "Tu étais sous le LT1 pendant toute la sortie."


# ------------------------------------------------------------------ 1. no repeated fact

def test_natural_llm_comparison_is_kept_and_not_restated_by_the_contract():
    ctx = _ctx_1309()
    out = _resolve(f"Tu as couru 21,27 km. {SIM_NATURAL} {BAD}", ctx)
    print("\n[1]", out["response_source"], "|", out["text"])
    assert out["response_source"] == "llm_reply_partially_validated"
    assert SIM_NATURAL in out["text"] and "71 s/km" not in out["text"]
    assert out["text"].count("distance similaire") == 1


def test_two_llm_formulations_of_the_same_fact_keep_one():
    ctx = _ctx_1309()
    out = _resolve(f"{SIM_FIGURE} {SIM_NATURAL} {BAD}", ctx)
    assert out["response_source"] == "llm_reply_partially_validated"
    assert out["text"].count("distance similaire") == 1


def test_contract_fallback_never_states_the_comparison_twice():
    out = _resolve(BAD, _ctx_1309())
    assert out["text"].count("distance similaire") == 1


def test_distinct_populations_are_both_kept():
    ctx = _ctx_1210(v3=True, similar=True)
    text = ("Par rapport à tes 3 sorties précédentes de distance similaire, ton allure est de 25 s/km plus lente. "
            "À FC comparable, ton allure est de 8,4 s/km plus lente que sur 12 séances antérieures. " + BAD)
    out = _resolve(text, ctx)
    assert out["response_source"] == "llm_reply_partially_validated"
    assert "distance similaire" in out["text"] and "FC comparable" in out["text"]


def test_similar_looking_sentences_about_different_values_are_not_deduplicated():
    ctx = _ctx_1210(v3=True, similar=True)
    text = ("Par rapport à tes 3 sorties précédentes de distance similaire, ton allure est de 25 s/km plus lente. "
            "À FC comparable, ton allure est de 8,4 s/km plus lente que sur 12 séances antérieures. " + BAD)
    assert _resolve(text, ctx)["text"].count("s/km") == 2


@pytest.mark.parametrize("sentence,passed", [
    (SIM_NATURAL, True),
    (SIM_NATURAL.replace("plus d'une minute", "environ 70 secondes").replace("environ 70 secondes",
                                                                           "plus de deux minutes"), False),
    (SIM_NATURAL.replace("plus d'une minute", "moins d'une minute"), False),
    (SIM_NATURAL.replace("plus rapide", "plus lent"), False),
    ("Tu as été nettement plus rapide, de plus d'une minute par kilomètre.", False),
])
def test_minute_magnitudes_must_match_the_contract_delta(sentence, passed):
    assert guard.verify_chat_reply(f"Tu as couru 21,27 km. {sentence}", _ctx_1309(), "fr")["passed"] is passed


# ------------------------------------------------------------------ 2. grouped measures

def test_1210_measures_are_one_natural_sentence():
    text = guard.build_contract_fallback(_ctx_1210(v3=False, similar=False), "fr")
    assert text.startswith("Tu as couru 9,33 km en 68 minutes, à 7:21/km, avec une FC moyenne de 127 bpm.")
    assert "en chiffres" not in text


def test_1309_measures_use_hours_and_minutes():
    text = guard.build_contract_fallback(_ctx_1309(), "fr")
    assert text.startswith("Tu as couru 21,27 km en 2h02, à 5:43/km, avec une FC moyenne de 160 bpm.")


@pytest.mark.parametrize("language,start", [("en", "You ran 21.27 km in 2h02, at 5:43/km, with an average HR of 160 bpm."),
                                            ("es", "Has corrido 21,27 km en 2h02, a 5:43/km, con una FC media de 160 bpm.")])
def test_measures_in_en_es_pass_the_guard(language, start):
    ctx = _ctx_1309(language)
    text = guard.build_contract_fallback(ctx, language)
    assert text.startswith(start)
    assert guard.verify_chat_reply(text, ctx, language)["passed"] is True


def test_absent_measure_is_never_completed():
    ctx = _ctx_1309()
    ctx["session_coaching_frame"]["evidence_contract"]["measured_facts"].pop("avg_hr_bpm")
    ctx["session_coaching_frame"]["evidence_contract"]["measured_facts"].pop("avg_pace")
    text = guard.build_contract_fallback(ctx, "fr")
    assert text.startswith("Tu as couru 21,27 km en 2h02.") and "bpm" not in text and "/km" not in text.split(".")[0]
    ctx["session_coaching_frame"]["evidence_contract"]["measured_facts"] = {"avg_hr_bpm": 160}
    assert guard.build_contract_fallback(ctx, "fr").startswith("Ta FC moyenne était de 160 bpm.")


def test_measures_stated_by_a_kept_llm_sentence_are_not_repeated():
    ctx = _ctx_1309()
    out = _resolve(f"Tu as couru 21,27 km en 2h02, à 5:43/km. {BAD}", ctx)
    assert out["response_source"] == "llm_reply_partially_validated"
    assert "Tu as couru 21,27 km en 2h02, à 5:43/km." in out["text"]
    assert out["text"].count("21,27") == 1 and out["text"].count("5:43") == 1
    assert out["text"].startswith("Ta FC moyenne était de 160 bpm.")


def test_exact_llm_reply_is_returned_unchanged():
    ctx = _ctx_1309()
    text = ("Tu as parcouru 21,27 km en 2h02, à 5:43/km, avec une FC moyenne de 160 bpm. "
            "Le contexte disponible reste limité.")
    out = _resolve(text, ctx)
    assert out["response_source"] == "llm_reply_checked" and out["text"] == text


def test_composition_is_deterministic_and_does_not_mutate_the_context():
    ctx = _ctx_1210()
    before = copy.deepcopy(ctx)
    first, second = _resolve(RAW_1210, ctx)["text"], _resolve(RAW_1210, ctx)["text"]
    assert first == second and ctx == before


# ------------------------------------------------------------------ 3. reserves

def test_1210_keeps_the_structure_limit_without_adding_the_physiological_one():
    ctx = _ctx_1210()
    out = _resolve(RAW_1210, ctx, question="Peux-tu analyser cette séance ?")
    print("\n[3]", out["response_source"], "|", out["text"])
    assert out["response_source"] == "llm_reply_partially_validated"
    assert "structure ou les fractions" in out["text"]
    assert "seuil personnel" not in out["text"]
    assert guard.verify_chat_reply(out["text"], ctx, "fr")["passed"] is True


def test_the_limit_the_question_is_about_is_added_even_after_another_one():
    out = _resolve(RAW_1210, _ctx_1210(), question="Quelle était l'intensité de cette séance ?")
    assert "structure ou les fractions" in out["text"]
    assert out["text"].count("seuil personnel") == 1


def test_an_equivalent_limit_is_not_repeated():
    said = "L'intensité physiologique ne peut pas être déterminée sans seuil."
    out = _resolve(f"{said} Tu as couru 21,27 km. {BAD}", _ctx_1309(), question="Quelle intensité ?")
    assert out["text"].count("intensité physiologique") + out["text"].count("Intensité physiologique") == 1
    assert "seuil personnel" not in out["text"]


def test_a_reply_made_only_of_reserves_falls_back_to_the_facts():
    text = "L'absence de détails sur la structure limite l'analyse. Aucune progression n'est établie."
    ctx = _ctx_1309()
    out = _resolve(text + " " + BAD, ctx)
    assert out["text"].startswith("Tu as couru 21,27 km")


def test_the_guard_still_rejects_a_physiological_claim():
    ctx = _ctx_1210()
    for claim in ("Ton intensité physiologique était basse.", "Tu étais sous le LT1 pendant toute la sortie."):
        assert guard.verify_chat_reply(f"Tu as couru 9,33 km. {claim}", ctx, "fr")["passed"] is False


# ------------------------------------------------------------------ 4. prescription

def test_race_is_translated_and_the_known_record_is_not_called_unknown():
    text = guard.build_contract_fallback(_ctx_1309(), "fr", "Quelle était la prescription du jour ?")
    sentence = next(s for s in text.split(". ") if "prescription" in s)
    print("\n[4]", sentence)
    assert "(compétition)" in sentence and "race" not in sentence
    assert "inconnue" not in sentence and "19:01" not in text and "recorded_at" not in text
    assert "avant ou après la séance" in sentence


def test_unknown_recording_time_is_stated_only_when_there_is_no_timestamp():
    ctx = _ctx_1309(prescription={**RACE, "recorded_at": None})
    text = guard.build_contract_fallback(ctx, "fr", "Quelle était la prescription du jour ?")
    assert "l'heure de son enregistrement est inconnue" in text


def test_prescription_is_omitted_when_the_question_does_not_need_it():
    ctx = _ctx_1309()
    assert "prescription" not in guard.build_contract_fallback(ctx, "fr", "Comment était mon allure ?")
    assert "prescription" in guard.build_contract_fallback(ctx, "fr")  # no question: unchanged behaviour


@pytest.mark.parametrize("language,word", [("fr", "compétition"), ("en", "race"), ("es", "competición")])
def test_race_label_per_language(language, word):
    ctx = _ctx_1309(language)
    text = guard.build_contract_fallback(ctx, language)
    assert f"({word})" in text and guard.verify_chat_reply(text, ctx, language)["passed"] is True


def test_unmapped_prescription_type_never_leaks_a_technical_name():
    ctx = _ctx_1309(prescription={**RACE, "prescribed_workout_type": "weird_internal_code"})
    assert "weird_internal_code" not in guard.build_contract_fallback(ctx, "fr")


# ------------------------------------------------------------------ 5. median duration

@pytest.mark.parametrize("sentence,passed", [
    ("122 minutes contre une médiane de 56 minutes.", True),
    ("122 min contre une médiane de 56 min.", True),
    ("Une durée médiane de 56 minutes sur 33 séances précédentes.", True),
    ("122 minutes contre une moyenne de 56 minutes.", False),
    ("122 km contre une médiane de 56 km.", False),
    ("122 minutes contre une médiane de 57 minutes.", False),
    ("122 minutes contre une médiane de 56 minutes sur 12 séances précédentes.", False),
    ("Tu as couru 122 minutes, soit 56 minutes de plus.", False),
])
def test_median_duration_comparison(sentence, passed):
    text = f"Tu as couru 21,27 km. {sentence} Le contexte disponible reste limité."
    assert guard.verify_chat_reply(text, _ctx_1309(), "fr")["passed"] is passed


def test_median_is_not_proven_without_the_v3_ratio():
    ctx = _ctx_1309()
    ctx["session_coaching_frame"]["evidence_contract"]["validated_comparisons"].pop()
    text = "Tu as couru 21,27 km. 122 minutes contre une médiane de 56 minutes. Le contexte disponible reste limité."
    assert guard.verify_chat_reply(text, ctx, "fr")["passed"] is False


def test_other_statistics_are_not_opened():
    for sentence in ("Ta durée maximale était de 56 minutes.", "Ton quartile de durée est de 56 minutes."):
        text = f"Tu as couru 21,27 km. {sentence} Le contexte disponible reste limité."
        assert guard.verify_chat_reply(text, _ctx_1309(), "fr")["passed"] is False
