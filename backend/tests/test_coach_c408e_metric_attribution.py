"""C408-E — every figure of a Coach reply is attributed to its own metric and population, also on direct acceptance."""

import copy

import pytest

import coach_evidence_guard as guard
import coach_context_v2 as cc2
import workout_analysis_v2 as wa2
from test_coach_c408d_partial_validation import RAW_1210, _ctx


def _spec_ctx(language="fr"):
    """Spec populations: similar distance 5 sessions (+25), comparable HR 3 sessions (+8.4), relative HR 31."""
    ctx = _ctx(language)
    similar = ctx["session_coaching_frame"]["evidence_contract"]["validated_comparisons"][0]
    similar["pace_sample_count"] = 5
    ctx["workout_detail"]["analysis"]["comparison"]["similar"]["pace_sample_count"] = 5
    sub = ctx["session_coaching_frame"]["v3_assessment"]["historical_comparison"]["provenance"]["sub_populations"]
    sub["pace_at_comparable_hr"]["activity_count"] = 3
    return ctx


# C403 refuses a one-sentence reply (length) and an un-framed comparison value: replies are
# wrapped in a measured sentence, and the distance sentence carries an explicit comparison cue.
PREFIX = "Tu as couru 9,33 km en 68 min. "


def _resolve(text, language="fr", ctx=None):
    return guard.resolve_chat_reply(text, ctx or _spec_ctx(language), language)


@pytest.mark.parametrize("text,accepted", [
    ("À FC comparable, ton allure est de 25 s/km plus lente.", False),
    ("À FC comparable, ton allure est de 8,4 s/km plus lente.", True),
    ("À FC comparable, ton allure est de 8,4 s/km plus lente sur 5 séances.", False),
    ("À FC comparable, ton allure est de 8,4 s/km plus lente sur 3 séances.", True),
    ("Sur les sorties de distance similaire, ton allure est de 25 s/km plus lente que d'habitude.", True),
    ("Sur les sorties de distance similaire, ton allure est de 8,4 s/km plus lente que d'habitude.", False),
    ("Ta FC moyenne est de 25 bpm.", False),
    ("Ta FC moyenne est de 127 bpm.", True),
    ("Ta FC moyenne est de 127 bpm sur 31 séances.", False),
    ("À FC comparable, ton allure est de 8,4 plus lente.", False),
    ("À FC comparable, ton allure est de 8,4 s/km plus rapide.", False),
])
def test_direct_acceptance_applies_metric_and_population_attribution(text, accepted):
    reply = PREFIX + text
    out = _resolve(reply)
    assert (out["response_source"] == "llm_reply_checked") is accepted
    if accepted:
        assert out["text"] == reply
    else:
        assert out["text"] != reply and guard.verify_chat_reply(out["text"], _spec_ctx(), "fr")["passed"]


@pytest.mark.parametrize("text,accepted", [
    ("À FC comparable, ton allure est de 25 s/km plus lente.", False),
    ("À FC comparable, ton allure est de 8,4 s/km plus lente sur 5 séances.", False),
    ("À FC comparable, ton allure est de 8,4 s/km plus lente sur 3 séances.", True),
    ("Sur les sorties de distance similaire, ton allure est de 25 s/km plus lente.", True),
    ("Sur les sorties de distance similaire, ton allure est de 8,4 s/km plus lente.", False),
    ("Ta FC moyenne est de 25 bpm.", False),
    ("Ta FC moyenne est de 127 bpm.", True),
])
def test_exact_sentences_at_the_contract_layer(text, accepted):
    assert ("figure_not_attributed" not in guard.check_contract_claims(text, _spec_ctx())) is accepted


@pytest.mark.parametrize("language,good,bad", [
    ("fr", "À FC comparable, ton allure est de 8,4 s/km plus lente sur 3 séances.",
     "À FC comparable, ton allure est de 25 s/km plus lente."),
    ("en", "At comparable HR, your pace is 8.4 s/km slower over 3 sessions.",
     "At comparable HR, your pace is 25 s/km slower."),
    ("es", "Con FC comparable, tu ritmo es 8,4 s/km más lento en 3 sesiones.",
     "Con FC comparable, tu ritmo es 25 s/km más lento."),
])
def test_same_protection_in_fr_en_es(language, good, bad):
    ctx = _spec_ctx(language)
    assert guard.verify_chat_reply(good, ctx, language)["passed"] is True
    rejected = guard.verify_chat_reply(bad, ctx, language)
    assert rejected["passed"] is False and "figure_not_attributed" in rejected["rejected_checks"]
    assert guard.resolve_chat_reply(bad, ctx, language)["response_source"] != "llm_reply_checked"


def test_same_value_legitimately_used_by_two_metrics():
    ctx = _spec_ctx()
    ctx["session_coaching_frame"]["v3_assessment"]["historical_comparison"]["pace_difference_sec_per_km_at_comparable_hr"] = 25.0
    ctx["session_coaching_frame"]["evidence_contract"]["validated_comparisons"][1]["values"][
        "pace_difference_at_comparable_hr"]["value"] = 25.0
    text = (PREFIX + "À FC comparable, ton allure est de 25 s/km plus lente sur 3 séances. "
            "Par rapport à 5 sorties de distance similaire, ton allure est de 25 s/km plus lente.")
    assert _resolve(text, ctx=ctx)["text"] == text


def test_sentence_with_several_figures_must_have_all_of_them_attributed():
    ok = PREFIX + "Par rapport à 5 sorties de distance similaire, ton allure est de 25 s/km plus lente."
    bad = PREFIX + "Par rapport à 3 sorties de distance similaire, ton allure est de 25 s/km plus lente."
    assert _resolve(ok)["response_source"] == "llm_reply_checked"
    assert _resolve(bad)["response_source"] != "llm_reply_checked"


def test_comparison_without_its_own_population_is_never_accepted():
    ctx = _spec_ctx()
    ctx["session_coaching_frame"]["v3_assessment"]["historical_comparison"]["provenance"]["sub_populations"] = {}
    text = PREFIX + "À FC comparable, ton allure est de 8,4 s/km plus lente."
    assert _resolve(text, ctx=ctx)["response_source"] != "llm_reply_checked"


def test_mixed_reply_keeps_proven_sentences_and_restores_missing_facts():
    text = (PREFIX + "À FC comparable, ton allure est de 25 s/km plus lente. "
            "Par rapport à 5 sorties de distance similaire, ton allure est de 25 s/km plus lente.")
    out = _resolve(text)
    assert out["response_source"] == "llm_reply_partially_validated"
    assert "Tu as couru 9,33 km en 68 min." in out["text"]
    assert "8,4 s/km" in out["text"]  # restored from the contract with its own population
    assert "À FC comparable, ton allure est de 25" not in out["text"]
    assert out["text"].count("25 s/km") == 1


def test_natural_sentences_without_figures_are_not_rejected_by_the_attribution_check():
    text = "C'était une sortie régulière, bien menée. Le contexte disponible reste limité."
    verdict = guard.verify_chat_reply(text, _spec_ctx(), "fr")
    assert "figure_not_attributed" not in verdict["rejected_checks"]


def test_natural_sentence_survives_next_to_a_removed_one():
    text = ("Tu as couru 9,33 km en 68 min. Ta FC moyenne est de 25 bpm. "
            "Le contexte disponible reste limité pour aller plus loin.")
    out = _resolve(text)
    assert out["response_source"] == "llm_reply_partially_validated"
    assert "Le contexte disponible reste limité pour aller plus loin." in out["text"]
    assert "25 bpm" not in out["text"]


def test_context_is_not_mutated_by_resolution():
    ctx = _spec_ctx()
    before = copy.deepcopy(ctx)
    _resolve("À FC comparable, ton allure est de 25 s/km plus lente.", ctx=ctx)
    assert ctx == before


def test_replay_1210_final_text():
    ctx = _spec_ctx()
    out = guard.resolve_chat_reply(RAW_1210, ctx, "fr")
    text = out["text"]
    print("\n" + text)
    assert out["response_source"] != "llm_reply_checked"
    for needed in ("9,33 km", "68 min", "7:21/km", "127 bpm", "31 séances"):
        assert needed in text
    assert "8,4 s/km plus lente" in text and "3 séances" in text and "5 sorties" in text and "25 secondes plus lentement" in text
    assert "facile" not in text and "confirme" not in text
    assert guard.verify_chat_reply(text, ctx, "fr")["passed"] is True


def test_relative_easy_claim_stays_rejected_but_cautious_relative_wording_is_accepted():
    ctx = _spec_ctx()
    assert "relative_hr_is_not_easy_effort" in ctx["session_coaching_frame"]["evidence_contract"]["not_demonstrated"]
    assert guard.verify_chat_reply("Ce footing relativement facile par rapport à tes efforts habituels.",
                                   ctx, "fr")["passed"] is False
    cautious = "Ta FC moyenne se situe dans la partie basse de tes 31 séances de référence."
    assert guard.verify_chat_reply(cautious, ctx, "fr")["passed"] is True


def test_pace_display_rounds_to_nearest_second_consistently():
    # 7.342 min/km = 440.52 s -> 7:21 (the 2-decimal context value 7.34 gave 7:20)
    assert wa2._fmt_pace(7.342) == "7:21/km" and cc2._format_pace_min_km(7.342) == "7:21/km"
    assert wa2._fmt_pace(7.34) == "7:20/km"
    assert wa2._fmt_pace(7.5083334) == cc2._format_pace_min_km(7.5083334) == "7:31/km"
    assert wa2._fmt_pace(7.0083334) == "7:01/km"  # 420.5 s rounds half up
    assert wa2._fmt_pace_delta(0.2) == cc2._format_pace_delta_min_km(0.2) == "+0:12/km"


def test_detail_display_uses_unrounded_source_without_changing_values():
    detail = cc2._normalize_workout_detail({"id": "w", "date": "2026-10-12", "avg_pace_min_km": 7.342}, None)
    assert detail.avg_pace_display == "7:21/km" and detail.avg_pace_min_km == 7.34
    assert cc2._project_paces_for_llm(detail.model_dump())["avg_pace_display"] == "7:21/km"
