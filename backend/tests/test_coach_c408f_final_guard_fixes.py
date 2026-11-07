"""C408-F — last guard fixes: durations in h/min, V3 duration ratio, relative effort wording.

Synthetic contexts only (the contract is built by the production builders); no LLM, no Garmin, no DB.
"""

import copy

import pytest

import coach_context_v2 as ccv2
import coach_evidence_guard as guard
import coach_session_comment as csc
from test_coach_c402_session_comment import _llm_context

DIST, DURATION, HABITUAL, COUNT = 21.27, 122.0, 56.0, 12
SENTENCE_END = " Le contexte disponible reste limité."


def _intel(*, ratio=2.18, count=COUNT, kind="long_run_probable", tier="individual_history", position="low",
           relative="used", easy_diagnosis=False, with_ratio=True,
           habitual=HABITUAL):
    evidence = {"duration_minutes": DURATION, "habitual_duration_minutes": habitual,
                "duration_ratio": ratio, "history_count": float(count)} if with_ratio else {}
    return {
        "session_classification": {
            "type": kind, "decision_tier": tier, "confidence": "low", "evidence": evidence,
            "relative_effort": (
                {"status": "used", "relative_position": position, "current_hr_bpm": 127, "reference_count": 31,
                 "hr_q1_bpm": 140, "hr_median_bpm": 145, "hr_q3_bpm": 150,
                 "period_start": "2026-04-20", "period_end": "2026-10-05",
                 "criteria": {"window_days": 180, "duration_ratio_min": 0.5, "duration_ratio_max": 2.0}}
                if relative == "used" else {"status": "insufficient_references"})},
        "intensity_assessment": {"position": "unknown"},
        "historical_comparison": {"status": "insufficient"},
        "coach_assessment": {"diagnosis": {"code": "diagnosis.easy_run_relative", "text": "x"}
                             if easy_diagnosis else None},
    }


def _ctx(language="fr", **kwargs):
    ctx = _llm_context()
    ctx["workout_detail"].update({"distance_km": DIST, "duration_minutes": DURATION, "avg_hr": 127})
    ctx["selected_workout_permissions"]["similar_comparison_available"] = False
    ctx["workout_detail"]["analysis"]["comparison"] = {}
    ctx["recent_workouts_coverage"]["included_count"] = len(ctx["recent_workouts"])
    intel = _intel(**kwargs)
    v3 = ccv2._compact_v3_assessment(intel)
    ctx["session_coaching_frame"] = {
        "v3_assessment": v3,
        "evidence_contract": ccv2.build_evidence_contract(ctx["workout_detail"], {}, v3, None, intel),
    }
    ctx["language"] = language
    return csc.build_session_chat_context(ctx)


def _passes(text, ctx=None, language="fr"):
    return guard.verify_chat_reply(text, ctx or _ctx(language), language)


# ------------------------------------------------------------------ P0 — durations in hours/minutes

@pytest.mark.parametrize("duration", ["2h02", "2 h 02", "2 h 2 min", "2h02min", "2 heures 2 minutes",
                                      "2 heures et 2 minutes", "2,03 h", "122 min", "122 minutes"])
def test_equivalent_representations_of_122_minutes_are_accepted(duration):
    verdict = _passes(f"Tu as couru 21,27 km en {duration}." + SENTENCE_END)
    assert verdict["passed"] is True, verdict


@pytest.mark.parametrize("duration", ["2h12", "2 h 12", "2 h 12 min", "132 min", "2h", "1h02", "2 heures 12 minutes"])
def test_wrong_durations_are_rejected_even_with_a_correct_distance(duration):
    verdict = _passes(f"Tu as couru 21,27 km en {duration}." + SENTENCE_END)
    assert verdict["passed"] is False, duration
    assert guard.resolve_chat_reply(f"Tu as couru 21,27 km en {duration}." + SENTENCE_END,
                                    _ctx(), "fr")["response_source"] != "llm_reply_checked"


@pytest.mark.parametrize("sentence", ["Tu as couru 21,72 km en 2h02.", "Tu as couru 12,27 km en 122 min.",
                                      "Tu as couru 20 km en 2h02."])
def test_correct_duration_with_a_wrong_distance_is_rejected(sentence):
    assert _passes(sentence + SENTENCE_END)["passed"] is False


def test_duration_alone_sentence_and_checked_against_the_source():
    assert _passes("La séance a duré 2h02." + SENTENCE_END)["passed"] is True
    assert _passes("La séance a duré 2h12." + SENTENCE_END)["passed"] is False


@pytest.mark.parametrize("language,good,bad", [
    ("fr", "Tu as couru 21,27 km en 2 h 02.", "Tu as couru 21,27 km en 2 h 12."),
    ("en", "You ran 21.27 km in 2h02.", "You ran 21.27 km in 2h12."),
    ("en", "You ran 21.27 km in 2 hours 2 minutes.", "You ran 21.27 km in 2 hours 12 minutes."),
    ("es", "En la salida has corrido 21,27 km en 2 h 02.", "En la salida has corrido 21,27 km en 2 h 12."),
    ("es", "En la salida has corrido 21,27 km en 2 horas 2 minutos.", "En la salida has corrido 21,27 km en 2 horas 12 minutos."),
])
def test_durations_in_fr_en_es(language, good, bad):
    ctx = _ctx(language)
    tail = {"fr": SENTENCE_END, "en": " The available context remains limited.",
            "es": " El contexto disponible sigue siendo limitado."}[language]
    assert guard.verify_chat_reply(good + tail, ctx, language)["passed"] is True
    assert guard.verify_chat_reply(bad + tail, ctx, language)["passed"] is False


def test_source_values_are_not_modified():
    ctx = _ctx()
    before = copy.deepcopy(ctx)
    guard.resolve_chat_reply("Tu as couru 21,27 km en 2h12." + SENTENCE_END, ctx, "fr")
    assert ctx == before
    assert ctx["session_coaching_frame"]["evidence_contract"]["measured_facts"]["duration_minutes"] == 122.0


def test_long_run_replay_with_21_27_km_and_122_minutes_keeps_the_exact_sentences():
    ctx = _ctx()
    text = ("Tu as couru 21,27 km en 2h02. La séance a duré 122 min. "
            "Tu étais sous le LT1 pendant toute la sortie.")
    out = guard.resolve_chat_reply(text, ctx, "fr")
    print("\n[long run]", out["response_source"], "|", out["text"])
    assert out["response_source"] == "llm_reply_partially_validated"
    assert "Tu as couru 21,27 km en 2h02." in out["text"] and "La séance a duré 122 min." in out["text"]
    assert "LT1" not in out["text"]
    assert guard.verify_chat_reply(out["text"], ctx, "fr")["passed"] is True


# ------------------------------------------------------------------ P1 — duration vs habitual duration

def test_ratio_provenance_is_exposed_by_v3_and_the_contract_with_its_population():
    ctx = _ctx()
    frame = ctx["session_coaching_frame"]
    entry = next(e for e in frame["evidence_contract"]["validated_comparisons"]
                 if e["metric"] == "session_duration_vs_habitual_median_duration")
    assert entry["ratio"] == 2.18 and entry["reference_count"] == COUNT
    assert entry["habitual_duration_minutes"] == HABITUAL and "median" in entry["habitual_definition"]
    assert frame["v3_assessment"]["classification"]["duration_vs_habitual"]["ratio"] == 2.18


def test_no_ratio_when_v3_did_not_produce_one():
    for kwargs in ({"kind": "easy_run_probable"}, {"with_ratio": False}, {"count": 4}):
        frame = _ctx(**kwargs)["session_coaching_frame"]
        assert not [e for e in frame["evidence_contract"]["validated_comparisons"]
                    if "duration" in e["metric"]], kwargs


@pytest.mark.parametrize("ratio,sentence,accepted", [
    (2.18, "La séance a duré plus de deux fois ta durée habituelle.", True),
    (2.18, "La séance a duré plus de 2 fois ta durée habituelle.", True),
    (2.18, "La séance a duré 2,18 fois ta durée habituelle.", True),
    (2.18, "La séance a duré plus du double de ta durée habituelle.", True),
    (2.18, "La séance a duré au moins deux fois ta durée habituelle.", True),
    (2.18, "La séance a duré environ deux fois ta durée habituelle.", True),
    (2.18, "La séance a duré moins de trois fois ta durée habituelle.", True),
    (2.18, "La séance a duré trois fois ta durée habituelle.", False),
    (2.18, "La séance a duré plus de trois fois ta durée habituelle.", False),
    (2.18, "La séance a duré deux fois ta durée habituelle.", False),
    (2.18, "La séance a duré 2,5 fois ta durée habituelle.", False),
    (2.18, "La séance a duré environ trois fois ta durée habituelle.", False),
    (2.18, "La séance a duré le double de ta durée habituelle.", False),
    (1.8, "La séance a duré plus de deux fois ta durée habituelle.", False),
    (1.8, "La séance a duré plus de 1,5 fois ta durée habituelle.", True),
    (2.0, "La séance a duré plus de deux fois ta durée habituelle.", False),
    (2.18, "La séance a duré plus de deux fois ta durée.", False),  # no habitual reference named
    (2.18, "La séance a duré plus de deux fois ta durée moyenne.", False),  # other statistic than the median
])
def test_duration_multiples_must_be_compatible_with_the_ratio(ratio, sentence, accepted):
    ctx = _ctx(ratio=ratio)
    habitual_ok = ratio == 2.18 or ratio == 1.8 or ratio == 2.0
    assert habitual_ok
    # the ratio must stay consistent with the measured duration: build it from the same 122 min session
    if abs(ratio - DURATION / HABITUAL) > 0.011:
        frame = ctx["session_coaching_frame"]
        entry = next(e for e in frame["evidence_contract"]["validated_comparisons"]
                     if e["metric"] == "session_duration_vs_habitual_median_duration")
        entry["habitual_duration_minutes"] = round(DURATION / ratio, 4)
    out = guard.verify_chat_reply(sentence + SENTENCE_END, ctx, "fr")
    assert out["passed"] is accepted, out


def test_inconsistent_ratio_is_never_used():
    ctx = _ctx()
    entry = next(e for e in ctx["session_coaching_frame"]["evidence_contract"]["validated_comparisons"]
                 if e["metric"] == "session_duration_vs_habitual_median_duration")
    entry["ratio"] = 3.4  # not session / habitual
    out = guard.verify_chat_reply("La séance a duré plus de deux fois ta durée habituelle." + SENTENCE_END,
                                  ctx, "fr")
    assert out["passed"] is False and "duration_ratio_not_established" in out["rejected_checks"]


@pytest.mark.parametrize("kwargs", [{"with_ratio": False}, {"count": 4}, {"kind": "easy_run_probable"}])
def test_absent_ratio_or_unknown_population_rejects_the_claim(kwargs):
    out = guard.verify_chat_reply("La séance a duré plus de deux fois ta durée habituelle." + SENTENCE_END,
                                  _ctx(**kwargs), "fr")
    assert out["passed"] is False and "duration_ratio_not_established" in out["rejected_checks"]


def test_a_pace_or_hr_comparison_never_supplies_a_duration_ratio():
    ctx = _ctx(with_ratio=False)
    comparison = ctx["session_coaching_frame"]["v3_assessment"]["historical_comparison"]
    comparison.update({"status": "available", "comparability": "strong", "reference_count": 4,
                       "pace_difference_sec_per_km_at_comparable_hr": 2.18, "duration_ratio": 2.18,
                       "hr_difference_bpm_at_comparable_pace": 2.18})
    ctx["session_coaching_frame"]["v3_assessment"]["classification"]["relative_effort"]["duration_ratio"] = 2.18
    for text in ("La séance a duré plus de deux fois ta durée habituelle.",
                 "À FC comparable, la séance a duré plus de deux fois ta durée habituelle."):
        out = guard.verify_chat_reply(text + SENTENCE_END, ctx, "fr")
        assert out["passed"] is False, text


def test_duration_multiple_cannot_be_applied_to_pace_or_hr_inside_the_same_clause():
    ctx = _ctx()
    for text in ("Ton allure a duré plus de deux fois ta durée habituelle.",
                 "Ta FC était plus de deux fois ta durée habituelle."):
        assert guard.verify_chat_reply(text + SENTENCE_END, ctx, "fr")["passed"] is False


def test_duration_multiple_with_the_wrong_population_is_rejected():
    ctx = _ctx()
    good = "La séance a duré plus de deux fois ta durée habituelle, médiane de tes 12 séances précédentes."
    bad = "La séance a duré plus de deux fois ta durée habituelle, médiane de tes 31 séances précédentes."
    assert guard.verify_chat_reply(good + SENTENCE_END, ctx, "fr")["passed"] is True
    assert guard.verify_chat_reply(bad + SENTENCE_END, ctx, "fr")["passed"] is False


def test_pace_and_hr_multiples_are_unchanged_by_the_duration_ratio():
    ctx = _ctx()
    out = guard.verify_chat_reply("Ton allure était deux fois plus lente." + SENTENCE_END, ctx, "fr")
    assert out["passed"] is False  # still refused by the existing C403 number check


@pytest.mark.parametrize("language,good,bad", [
    ("fr", "La séance a duré plus de deux fois ta durée habituelle.",
     "La séance a duré trois fois ta durée habituelle."),
    ("en", "The session lasted more than twice your usual duration.",
     "The session lasted three times your usual duration."),
    ("en", "The session lasted more than two times your usual duration.",
     "The session lasted more than three times your usual duration."),
    ("es", "La sesión duró más de dos veces tu duración habitual.",
     "La sesión duró tres veces tu duración habitual."),
])
def test_duration_ratio_in_fr_en_es(language, good, bad):
    ctx = _ctx(language)
    tail = {"fr": SENTENCE_END, "en": " The available context remains limited.",
            "es": " El contexto disponible sigue siendo limitado."}[language]
    assert guard.verify_chat_reply(good + tail, ctx, language)["passed"] is True
    assert guard.verify_chat_reply(bad + tail, ctx, language)["passed"] is False


def test_ratio_sentence_survives_repair_and_is_not_duplicated():
    ctx = _ctx()
    text = ("Tu as couru 21,27 km en 2h02. La séance a duré plus de deux fois ta durée habituelle. "
            "Tu étais sous le LT1 pendant toute la sortie.")
    out = guard.resolve_chat_reply(text, ctx, "fr")
    print("\n[ratio repair]", out["response_source"], "|", out["text"])
    assert out["response_source"] == "llm_reply_partially_validated"
    assert "plus de deux fois ta durée habituelle" in out["text"]
    assert "LT1" not in out["text"] and out["text"].count("fois") == 1
    assert guard.verify_chat_reply(out["text"], ctx, "fr")["passed"] is True


def test_ratio_is_restored_from_the_contract_when_its_sentence_is_removed():
    ctx = _ctx()
    text = "Tu as couru 21,27 km en 2h02. La séance a duré trois fois ta durée habituelle."
    out = guard.resolve_chat_reply(text, ctx, "fr")
    assert "trois fois" not in out["text"] and "2,18 fois ta durée habituelle" in out["text"]
    assert "12 séances" in out["text"]
    assert guard.verify_chat_reply(out["text"], ctx, "fr")["passed"] is True


# ------------------------------------------------------------------ P2 — relative effort wording
EASY = "Ce footing est relativement facile par rapport à tes efforts habituels."
CAUTIOUS = "Ta fréquence cardiaque était relativement basse par rapport à tes séances comparables."


def _hr_only_ctx():
    """V3 only places the average HR in the athlete's own history: no explicit 'relatively easy' conclusion."""
    return _ctx(kind="unknown", tier="insufficient_data", with_ratio=False)


def _explicit_ctx():
    """V3 itself concludes easy_run_probable from the personal history (diagnosis.easy_run_relative)."""
    return _ctx(kind="easy_run_probable", tier="individual_history", easy_diagnosis=True, with_ratio=False)


def test_decision_hr_position_alone_keeps_the_easy_effort_rejection():
    ctx = _hr_only_ctx()
    assert "relative_hr_is_not_easy_effort" in ctx["session_coaching_frame"]["evidence_contract"]["not_demonstrated"]
    out = guard.verify_chat_reply(EASY + SENTENCE_END, ctx, "fr")
    assert out["passed"] is False and "intensity_not_allowed" in out["rejected_checks"]


def test_decision_hr_position_alone_accepts_the_cautious_relative_wording():
    assert guard.verify_chat_reply(CAUTIOUS + SENTENCE_END, _hr_only_ctx(), "fr")["passed"] is True


def test_cautious_wording_requires_the_position_to_be_established_and_low():
    assert _passes(CAUTIOUS + SENTENCE_END, _ctx(relative="insufficient", with_ratio=False))["passed"] is False
    high = _ctx(position="high", with_ratio=False)
    assert "hr_position_contradicts_v3" in guard.verify_chat_reply(CAUTIOUS + SENTENCE_END, high, "fr")[
        "rejected_checks"]


def test_decision_relative_easy_is_accepted_only_with_an_explicit_v3_conclusion():
    ctx = _explicit_ctx()
    assert ctx["session_coaching_frame"]["v3_assessment"]["classification"]["probable_type"] == "easy_run_probable"
    assert guard.verify_chat_reply(EASY + SENTENCE_END, ctx, "fr")["passed"] is True
    assert guard.verify_chat_reply("Footing relativement facile par rapport à tes séances précédentes." + SENTENCE_END,
                                   ctx, "fr")["passed"] is True


@pytest.mark.parametrize("variant", [
    {"easy_diagnosis": False},                     # no explicit diagnosis code
    {"tier": "personal_thresholds"},               # not an individual-history conclusion
    {"kind": "steady_run_probable"},               # another conclusion
    {"position": "high"},                          # position is not low
    {"relative": "insufficient"},                  # no usable population
])
def test_relative_easy_stays_rejected_when_any_v3_condition_is_missing(variant):
    kwargs = {"kind": "easy_run_probable", "tier": "individual_history", "easy_diagnosis": True,
              "with_ratio": False, **variant}
    assert guard.verify_chat_reply(EASY + SENTENCE_END, _ctx(**kwargs), "fr")["passed"] is False


@pytest.mark.parametrize("sentence", [
    "Ce footing est facile.",                                           # not relative
    "Ce footing est relativement facile.",                              # relative to nothing
    "Ce footing est facile par rapport à tes efforts habituels.",       # relative marker without "relativement"
    "Ce footing est sous le LT1, relativement facile par rapport à tes efforts habituels.",
    "Ce footing est en zone d'endurance, relativement facile par rapport à tes efforts habituels.",
    "Ce footing relativement facile par rapport à tes efforts habituels te permet de bien récupérer.",
    "Ce footing relativement facile par rapport à tes efforts habituels est une séance de récupération.",
    "Ce footing relativement facile et très intense par rapport à tes efforts habituels.",
])
def test_physiological_or_unframed_easy_claims_are_never_authorised(sentence):
    out = guard.verify_chat_reply(sentence + SENTENCE_END, _explicit_ctx(), "fr")
    assert out["passed"] is False, sentence


def test_relative_easy_in_en_and_es():
    ctx_en, ctx_es = _explicit_ctx(), _explicit_ctx()
    assert guard.verify_chat_reply("This run was relatively easy compared with your usual efforts. "
                                   "The available context remains limited.", ctx_en, "en")["passed"] is True
    assert guard.verify_chat_reply("This run was easy compared with your usual efforts. "
                                   "The available context remains limited.", ctx_en, "en")["passed"] is False
    assert guard.verify_chat_reply("Esta salida fue relativamente fácil respecto a tus esfuerzos habituales. "
                                   "El contexto disponible sigue siendo limitado.", ctx_es, "es")["passed"] is True


def test_no_lt1_lt2_or_recovery_is_deduced_from_a_historical_ranking():
    ctx = _explicit_ctx()
    for text in ("Ta FC est relativement basse, donc tu es sous le LT1.",
                 "Ta FC relativement basse par rapport à tes séances confirme une zone d'endurance.",
                 "Ta FC relativement basse montre que tu as bien récupéré."):
        assert guard.verify_chat_reply(text + SENTENCE_END, ctx, "fr")["passed"] is False, text


def test_proven_relative_sentence_is_kept_by_the_repair():
    ctx = _explicit_ctx()
    easy = "Cette sortie était relativement facile par rapport à tes efforts habituels."
    text = "Tu as couru 21,27 km en 2h02. " + easy + " Tu étais sous le LT1 pendant toute la sortie."
    out = guard.resolve_chat_reply(text, ctx, "fr")
    assert out["response_source"] == "llm_reply_partially_validated"
    assert easy in out["text"] and "LT1" not in out["text"]


# ------------------------------------------------------------------ P3 — natural, non-repetitive repair

def test_repair_keeps_exact_sentences_and_does_not_repeat_the_same_limit():
    ctx = _explicit_ctx()
    text = ("Tu as couru 21,27 km en 2h02. " + CAUTIOUS + " Ta FC prouve que tu es en zone 2. "
            "L'intensité physiologique ne peut pas être déterminée.")
    out = guard.resolve_chat_reply(text, ctx, "fr")
    print("\n[P3]", out["response_source"], "|", out["text"])
    assert out["response_source"] == "llm_reply_partially_validated"
    assert "Tu as couru 21,27 km en 2h02." in out["text"] and CAUTIOUS in out["text"]
    assert "zone 2" not in out["text"]
    assert out["text"].count("intensité physiologique") <= 1
