"""C415 — question-aware contract fallback of the Evidence Guard (deterministic, no model call)."""
import copy
import re

import pytest

import coach_evidence_guard as guard
from test_coach_c408c_evidence_contract import _context

QUESTION = {
    "fr": "Pourquoi mon troisième effort était-il plus rapide ? Peut-on en déduire une amélioration de ma forme ?",
    "en": "Why was my third effort faster? Can we conclude my fitness has improved?",
    "es": "¿Por qué mi tercer esfuerzo fue más rápido? ¿Se puede deducir una mejora de mi forma?",
}
EXPECTED = {
    "fr": "Le troisième effort était le plus rapide, à 4:31/km. Les données montrent cette différence, mais pas "
          "sa cause certaine. Une seule répétition plus rapide ne suffit pas à démontrer une amélioration de ta forme.",
    "en": "The third effort was the fastest, at 4:31/km. The data shows this difference, but not its definite cause. "
          "A single faster repetition is not enough to show that your fitness has improved.",
    "es": "El tercer esfuerzo fue el más rápido, a 4:31/km. Los datos muestran esa diferencia, pero no su causa "
          "segura. Una sola repetición más rápida no basta para demostrar una mejora de tu forma.",
}
REJECTED = "Ton troisième effort montre clairement que ta forme s'est améliorée et que ton VO2max progresse."


def _ctx(paces=(("1", "4:42"), ("2", "4:40"), ("3", "4:31")), expected=3):
    ctx = copy.deepcopy(_context())
    contract = ctx["session_coaching_frame"]["evidence_contract"]
    contract["measured_facts"].pop("recorded_effort_structure", None)
    if expected:
        contract["measured_facts"]["recorded_effort_structure"] = {"effort_count": expected, "effort_duration_s": 240}
    contract["measured_facts"]["recorded_effort_paces"] = [
        {"effort_number": int(n), "value": v} for n, v in paces]
    contract["not_demonstrated"].update({
        "progress_not_demonstrated": "x", "physiological_intensity_undetermined": "x"})
    return ctx


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_rejected_reply_gets_a_fallback_that_answers_the_question(language):
    out = guard.resolve_chat_reply(REJECTED, _ctx(), language, question=QUESTION[language])
    assert out["response_source"] == "contract_fallback" and out["passed"] is False
    assert out["text"] == EXPECTED[language]


def test_fallback_never_adds_a_figure_or_claim_outside_the_contract():
    text = guard.build_contract_fallback(_ctx(), "fr", QUESTION["fr"])
    assert set(re.findall(r"\d+:\d{2}", text)) == {"4:31"}
    assert "VO2" not in text and "Tu as couru" not in text


def test_effort_in_the_middle_is_stated_plainly_without_a_cause_or_ranking():
    ctx = _ctx((("1", "4:30"), ("2", "4:40"), ("3", "4:50")))
    text = guard.build_contract_fallback(ctx, "fr", "Mon deuxième effort était-il ainsi ?")
    assert text == "Le deuxième effort était à 4:40/km."


def test_slowest_effort_is_not_called_faster():
    ctx = _ctx((("1", "4:30"), ("2", "4:40"), ("3", "4:50")))
    text = guard.build_contract_fallback(ctx, "fr", "Mon troisième effort : une amélioration de ma forme ?")
    assert text.startswith("Le troisième effort était le plus lent, à 4:50/km.")
    assert "plus rapide" not in text and "Une seule répétition ne suffit pas" in text


@pytest.mark.parametrize("language,asked", [("fr", "Mon 7e effort ?"), ("en", "How was my 7th rep?"),
                                            ("es", "¿Y mi séptimo esfuerzo?")])
def test_unrecorded_effort_is_not_invented(language, asked):
    text = guard.build_contract_fallback(_ctx(), language, "Mon 7e effort ? " if language == "fr" else asked)
    assert not re.search(r"\d+:\d{2}", text)


def test_progress_limit_is_only_stated_when_the_contract_declares_it():
    ctx = _ctx()
    del ctx["session_coaching_frame"]["evidence_contract"]["not_demonstrated"]["progress_not_demonstrated"]
    text = guard.build_contract_fallback(ctx, "fr", QUESTION["fr"])
    assert "amélioration" not in text and text.startswith("Le troisième effort était le plus rapide")


@pytest.mark.parametrize("language,question,expected,absent", [
    ("fr", "Est-ce que je progresse ?", "Aucune progression n'est établie.", "Tu as couru"),
    ("en", "Am I improving?", "No progress is established.", "You ran"),
    ("es", "¿Estoy mejorando?", "No se establece ningún progreso.", "Has corrido"),
    ("fr", "Comment était mon intensité ?", "Sans seuil personnel enregistré", "Tu as couru"),
    ("en", "Was the intensity hard?", "Without a recorded personal threshold", "You ran"),
    ("es", "¿Qué intensidad tuvo?", "Sin un umbral personal registrado", "Has corrido"),
    ("fr", "Dois-je récupérer plus ?", "Ta récupération n'est pas mesurée", "Aucune progression"),
    ("en", "How is my recovery?", "Your recovery isn't measured", "No progress"),
    ("es", "¿Cómo va mi recuperación?", "Tu recuperación no se mide", "No se establece"),
])
def test_topic_fallbacks_answer_the_topic_in_each_language(language, question, expected, absent):
    text = guard.build_contract_fallback(_ctx(), language, question)
    assert expected in text and absent not in text


def test_question_without_a_focus_keeps_the_complete_fallback():
    assert guard.build_contract_fallback(_ctx(), "fr", "Analyse ma séance.").startswith("Tu as couru 10 km")


def test_partial_repair_restores_only_the_asked_topic():
    ctx = _ctx()
    reply = "Ta FC moyenne est de 127 bpm. Tu as clairement progressé et ton VO2max augmente."
    out = guard.resolve_chat_reply(reply, ctx, "fr", question="Est-ce que je progresse ?")
    assert not out["passed"] and "VO2" not in (out["text"] or "")
    assert "Tu as couru" not in (out["text"] or "")


# ---- C415 review fixes: safe ranking and "why" answers ----
def _text(ctx, language, question):
    return guard.build_contract_fallback(ctx, language, question)


def test_complete_data_allows_fastest_and_slowest():
    assert _text(_ctx(), "fr", "Mon troisième effort ?").startswith("Le troisième effort était le plus rapide, à 4:31/km.")
    slow = _ctx((("1", "4:30"), ("2", "4:40"), ("3", "4:50")))
    assert _text(slow, "fr", "Mon troisième effort ?").startswith("Le troisième effort était le plus lent, à 4:50/km.")


@pytest.mark.parametrize("language,fragment", [
    ("fr", "parmi les répétitions dont l'allure est enregistrée"),
    ("en", "among the repetitions with a recorded pace"),
    ("es", "entre las repeticiones con ritmo registrado")])
def test_missing_pace_never_yields_an_unqualified_ranking(language, fragment):
    ctx = _ctx((("1", "4:42"), ("3", "4:31")), expected=3)  # effort 2 has no recorded pace
    text = _text(ctx, language, {"fr": "Mon troisième effort ?", "en": "My third effort?", "es": "¿Mi tercer esfuerzo?"}[language])
    assert fragment in text and "4:31/km" in text and "4:42" not in text


def test_unknown_total_is_treated_as_incomplete():
    text = _text(_ctx(expected=None), "fr", "Mon troisième effort ?")
    assert "parmi les répétitions dont l'allure est enregistrée" in text


def test_tied_efforts_get_no_unique_rank():
    ctx = _ctx((("1", "4:31"), ("2", "4:40"), ("3", "4:31")))
    for effort in ("premier", "troisième"):
        text = _text(ctx, "fr", f"Mon {effort} effort ?")
        assert "plus rapide" not in text and "plus lent" not in text and "4:31/km" in text


def test_middle_effort_has_no_ranking():
    text = _text(_ctx((("1", "4:30"), ("2", "4:40"), ("3", "4:50"))), "fr", "Mon deuxième effort ?")
    assert text == "Le deuxième effort était à 4:40/km."


def test_single_recorded_pace_states_only_the_known_pace():
    text = _text(_ctx((("2", "4:40"),)), "fr", "Mon deuxième effort ?")
    assert text == "Le deuxième effort était à 4:40/km."


@pytest.mark.parametrize("language,question,expected", [
    ("fr", "Pourquoi mon deuxième effort était-il différent ?",
     "Le deuxième effort était à 4:40/km. Les données montrent son allure, mais ne suffisent pas à expliquer pourquoi elle diffère des autres."),
    ("en", "Why was my second effort different?",
     "The second effort was at 4:40/km. The data shows its pace, but is not enough to explain why it differs from the others."),
    ("es", "¿Por qué mi segundo esfuerzo fue diferente?",
     "El segundo esfuerzo fue a 4:40/km. Los datos muestran su ritmo, pero no bastan para explicar por qué difiere de los demás."),
])
def test_why_question_without_demonstrated_cause_says_so(language, question, expected):
    ctx = _ctx((("1", "4:30"), ("2", "4:40"), ("3", "4:50")))
    assert _text(ctx, language, question) == expected
    assert not any(w in expected for w in ("fatigue", "fatigu", "cansanc", "VO2"))


def test_why_question_on_a_pace_that_was_not_recorded_does_not_invent_it():
    text = _text(_ctx((("1", "4:42"), ("3", "4:31"))), "fr", "Pourquoi mon deuxième effort était-il différent ?")
    assert text == "Je n'ai pas l'allure enregistrée de cet effort."


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_rejected_reply_with_incomplete_paces_falls_back_without_a_second_call(language):
    ctx = _ctx((("1", "4:42"), ("3", "4:31")))
    out = guard.resolve_chat_reply(REJECTED, ctx, language, question=QUESTION[language])
    assert out["response_source"] == "contract_fallback" and out["passed"] is False
    assert {"fr": "parmi les répétitions", "en": "among the repetitions", "es": "entre las repeticiones"}[language] in out["text"]
    assert set(re.findall(r"\d+:\d{2}", out["text"])) == {"4:31"}
