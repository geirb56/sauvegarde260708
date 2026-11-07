"""C408-F — the eight review comments of PR #397, one deterministic test group each.

Each group states the metric and population the sentence is checked against and the rejection or
acceptance reason. Synthetic contexts only; no LLM, no Garmin, no DB.
"""

import pytest

import coach_evidence_guard as guard
from test_coach_c408f_final_guard_fixes import (SENTENCE_END, _ctx, _explicit_ctx, _passes)

EN_END = " The available context remains limited."
ES_END = " El contexto disponible sigue siendo limitado."


def _verdict(text, ctx, language="fr"):
    return guard.verify_chat_reply(text, ctx, language)


# 1 — "2 heures 2 secondes" is 120 min + 2 s, never 122 min. Metric: session duration (122 min).
@pytest.mark.parametrize("language,text,end,accepted", [
    ("fr", "Tu as couru 21,27 km en 2 heures 2 minutes.", SENTENCE_END, True),
    ("fr", "Tu as couru 21,27 km en 2 heures 2 secondes.", SENTENCE_END, False),
    ("fr", "Tu as couru 21,27 km en 2h02.", SENTENCE_END, True),
    ("fr", "Tu as couru 21,27 km en 2h12.", SENTENCE_END, False),
    ("en", "You ran 21.27 km in 2 hours 2 minutes.", EN_END, True),
    ("en", "You ran 21.27 km in 2 hours 2 seconds.", EN_END, False),
    ("es", "En la salida has corrido 21,27 km en 2 horas 2 minutos.", ES_END, True),
    ("es", "En la salida has corrido 21,27 km en 2 horas 2 segundos.", ES_END, False),
])
def test_1_seconds_are_never_read_as_minutes(language, text, end, accepted):
    verdict = _verdict(text + end, _ctx(language), language)
    assert verdict["passed"] is accepted, verdict


def test_1_duration_sentence_without_distance():
    assert _passes("La séance a duré 2 heures 2 secondes." + SENTENCE_END)["passed"] is False
    assert _passes("La séance a duré 2 heures 2 minutes." + SENTENCE_END)["passed"] is True


# 2 — the multiple is attached to the metric it qualifies. Metric: duration ratio 2.18 (12 sessions).
@pytest.mark.parametrize("sentence,accepted", [
    ("La séance a duré plus de deux fois ta durée habituelle.", True),
    ("Tu as couru plus de deux fois ta distance habituelle.", False),
    ("Tu as couru plus de deux fois ta distance habituelle lors de cette longue sortie.", False),
    ("Tu as couru plus de deux fois ton allure habituelle.", False),
    ("Ta FC était plus de deux fois ta FC habituelle lors de cette longue durée.", False),
])
def test_2_a_duration_proof_never_authorises_distance_pace_or_hr(sentence, accepted):
    assert _passes(sentence + SENTENCE_END)["passed"] is accepted


# 3 — V3 compares to the MEDIAN of earlier sessions; the arithmetic mean is another statistic.
@pytest.mark.parametrize("language,sentence,end,accepted", [
    ("fr", "La séance a duré plus de deux fois ta durée habituelle.", SENTENCE_END, True),
    ("fr", "La séance a duré plus de deux fois ta durée médiane habituelle.", SENTENCE_END, True),
    ("fr", "La séance a duré plus de deux fois ta durée moyenne habituelle.", SENTENCE_END, False),
    ("en", "The session lasted more than twice your usual duration.", EN_END, True),
    ("en", "The session lasted more than twice your average duration.", EN_END, False),
    ("es", "La sesión duró más del doble de tu duración media.", ES_END, False),
    ("es", "La sesión duró más del doble de tu duración habitual.", ES_END, True),
])
def test_3_median_is_never_the_mean(language, sentence, end, accepted):
    assert _verdict(sentence + end, _ctx(language), language)["passed"] is accepted


# 4 — relative-easy counts are checked against the population of the relative-effort diagnosis (31).
@pytest.mark.parametrize("sentence,accepted", [
    ("Cette sortie était relativement facile par rapport à tes 31 séances de référence.", True),
    ("Cette sortie était relativement facile par rapport à tes efforts habituels.", True),
    ("Cette sortie était relativement facile par rapport à tes 3 dernières séances.", False),
    ("Cette sortie était relativement facile par rapport à tes 12 séances précédentes.", False),
])
def test_4_relative_easy_uses_the_relative_effort_population(sentence, accepted):
    ctx = _explicit_ctx()
    assert guard.verify_chat_reply(sentence + SENTENCE_END, ctx, "fr")["passed"] is accepted


def test_4_relative_easy_never_implies_a_zone_lt1_or_recovery():
    ctx = _explicit_ctx()
    for sentence in ("Cette sortie était relativement facile par rapport à tes 31 séances de référence, "
                     "donc dans ta zone d'endurance.",
                     "Cette sortie était relativement facile par rapport à tes efforts habituels : tu étais "
                     "sous le LT1."):
        assert guard.verify_chat_reply(sentence + SENTENCE_END, ctx, "fr")["passed"] is False


# 5 — "presque/almost/casi" means just BELOW the target (tolerance 0.25); "environ" is symmetric (0.5).
@pytest.mark.parametrize("ratio,sentence,accepted", [
    (2.18, "La séance a duré plus de deux fois ta durée habituelle.", True),
    (2.18, "La séance a duré environ deux fois ta durée habituelle.", True),
    (2.18, "La séance a duré presque deux fois ta durée habituelle.", False),
    (1.95, "La séance a duré presque deux fois ta durée habituelle.", True),
    (1.95, "La séance a duré environ deux fois ta durée habituelle.", True),
    (1.95, "La séance a duré plus de deux fois ta durée habituelle.", False),
    (1.6, "La séance a duré presque deux fois ta durée habituelle.", False),
])
def test_5_almost_requires_a_value_just_below_the_target(ratio, sentence, accepted):
    assert _passes(sentence + SENTENCE_END, _ctx(ratio=ratio, habitual=round(122 / ratio, 2)))["passed"] is accepted


@pytest.mark.parametrize("language,sentence,end", [
    ("en", "The session lasted almost twice your usual duration.", EN_END),
    ("en", "The session lasted nearly twice your usual duration.", EN_END),
    ("es", "La sesión duró casi dos veces tu duración habitual.", ES_END),
])
def test_5_almost_is_rejected_for_2_18_in_en_and_es(language, sentence, end):
    assert _verdict(sentence + end, _ctx(language), language)["passed"] is False


# 6 — the duration ratio does not depend on HR references (relative effort: insufficient_references).
@pytest.mark.parametrize("language,sentence,end", [
    ("fr", "La séance a duré plus de deux fois ta durée habituelle.", SENTENCE_END),
    ("en", "The session lasted more than twice your usual duration.", EN_END),
    ("es", "La sesión duró más del doble de tu duración habitual.", ES_END),
])
def test_6_duration_ratio_is_independent_of_hr_references(language, sentence, end):
    ctx = _ctx(language, relative="insufficient")
    verdict = _verdict(sentence + end, ctx, language)
    assert verdict["passed"] is True, verdict


def test_6_an_unavailable_hr_comparison_is_still_rejected():
    ctx = _ctx(relative="insufficient")
    assert _passes("Ta FC est dans la partie basse de tes 31 séances de référence." + SENTENCE_END, ctx)[
        "passed"] is False
    assert _passes("À FC comparable, ton allure est de 8 s/km plus lente que sur 3 séances." + SENTENCE_END,
                   ctx)["passed"] is False


# 7 — the fallback never says "zone" for a historical position and passes its own guard.
@pytest.mark.parametrize("language", ["fr", "en", "es"])
@pytest.mark.parametrize("position", ["low", "intermediate", "high"])
def test_7_fallback_accepted_by_its_own_guard_for_every_position(language, position):
    ctx = _ctx(language, position=position)
    text = guard.build_contract_fallback(ctx, language)
    assert text and guard.verify_chat_reply(text, ctx, language)["passed"] is True, text
    assert "zone intermédiaire" not in text and "zona intermedia" not in text


def test_7_french_intermediate_wording():
    text = guard.build_contract_fallback(_ctx(position="intermediate"), "fr")
    assert "dans la partie intermédiaire de tes 31 séances de référence" in text


# 8 — a kept figure-free relative-HR sentence is a covered fact: stated once.
def test_8_relative_hr_observation_is_kept_once_and_lt1_removed():
    ctx = _ctx(with_ratio=False)
    text = ("Ta fréquence cardiaque était relativement basse par rapport à tes séances comparables. "
            "Tu étais sous le LT1 pendant toute la sortie.")
    out = guard.resolve_chat_reply(text, ctx, "fr")
    assert out["response_source"] == "llm_reply_partially_validated", out
    assert "relativement basse par rapport à tes séances comparables" in out["text"]
    assert "LT1" not in out["text"]
    assert out["text"].count("partie basse") + out["text"].count("relativement basse") == 1
    assert out["text"].lower().count("physiologique") <= 1
    assert guard.verify_chat_reply(out["text"], ctx, "fr")["passed"] is True
