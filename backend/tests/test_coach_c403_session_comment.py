"""C403 — regression tests for the post-merge audit of the C402 selection and claim guard.

All cases are SYNTHETIC and deterministic: no LLM is called, so they prove nothing about the
quality of real model output.
"""

import copy

import pytest

import coach_context_v2
import coach_session_comment as csc
from test_coach_c402_session_comment import HISTORY, _hist, _llm_context, _selected


def _ok(text, ctx=None, lang="en"):
    return csc.validate_session_comment(text, ctx or _selected(), lang)


def _gap_context(pace_display="-0:18/km", distance_pct=2.0):
    """Comparison facts in the shape the shared context really produces (display strings)."""
    ctx = _llm_context()
    comparison = ctx["workout_detail"]["analysis"]["comparison"]
    comparison["similar"].pop("pace_difference_sec_per_km", None)
    comparison["similar"]["pace_difference_display"] = pace_display
    comparison["distance_km"] = {"percent_change": distance_pct}
    return csc.build_comment_context(ctx)


# ---------------------------------------------------------------- A1 same-day history

def _dated_context(selected_date, selected_start, sessions):
    ctx = _llm_context()
    ctx["workout_detail"]["date"] = selected_date
    ctx["workout_detail"]["start_time"] = selected_start
    ctx["recent_workouts"] = sessions
    return csc.build_comment_context(ctx)


def _dates(selected):
    return [s["date"] for s in selected["history_as_of_session"]["sessions"]]


SAME_DAY = [
    {"date": "2026-01-10T18:00:00", "type": "run", "distance_km": 9.0},
    {"date": "2026-01-10", "type": "run", "distance_km": 7.0},
    {"date": "2026-01-09T20:00:00", "type": "run", "distance_km": 6.0},
]


def test_date_only_selected_session_excludes_every_same_day_session():
    selected = _dated_context("2026-01-10", None, SAME_DAY)
    assert _dates(selected) == ["2026-01-09T20:00:00"]


def test_timestamped_selected_session_keeps_only_provably_earlier_same_day_sessions():
    sessions = SAME_DAY + [{"date": "2026-01-10T06:00:00", "type": "run", "distance_km": 5.0}]
    selected = _dated_context("2026-01-10", "2026-01-10T07:30:00", sessions)
    assert _dates(selected) == ["2026-01-10T06:00:00", "2026-01-09T20:00:00"]


def test_undated_or_unparseable_sessions_are_never_history():
    sessions = [{"type": "run", "distance_km": 4.0}, {"date": "not-a-date", "distance_km": 3.0}] + SAME_DAY[2:]
    assert _dates(_dated_context("2026-01-10", None, sessions)) == ["2026-01-09T20:00:00"]


def test_same_day_session_cannot_be_cited_as_earlier():
    selected = _dated_context("2026-01-10", None, SAME_DAY)
    ok, r = _ok("Before this run you ran 9 km at 5:10 per km, then this 10 km at 5:32 per km.", selected)
    assert not ok and "ungrounded_number" in r


# ---------------------------------------------------------------- A2 missing distances

def _distances(distances):
    sessions = [{"date": f"2026-01-0{i + 1}T07:00:00", "type": "run", **({"distance_km": d} if d else
                                                                          {"duration_minutes": 30.0})}
                for i, d in enumerate(distances)]
    return _dated_context("2026-01-10", "2026-01-10T07:30:00", sessions)["runner_profile"]


def test_average_distance_never_counts_an_unknown_distance_as_zero():
    observed = _distances([10.0, None, 6.0, 8.0])["observed_training"]
    assert observed == {"sessions_count": 4, "sessions_with_distance_count": 3,
                        "total_km": 24.0, "avg_km_per_session": 8.0}


def test_all_distances_known_keeps_the_previous_shape():
    assert _distances([10.0, 6.0, 8.0])["observed_training"] == {
        "sessions_count": 3, "total_km": 24.0, "avg_km_per_session": 8.0}


def test_no_habit_figure_when_too_few_sessions_record_a_distance():
    assert _distances([10.0, None, None, 6.0])["observed_training"] == {"sessions_count": 4}


# ---------------------------------------------------------------- A3 goal names

@pytest.mark.parametrize("goal,text,lang,expected", [
    ("MARATHON", "Your goal is the ultramarathon, so a 10 km run is relevant context for it.", "en", False),
    ("MARATHON", "Your goal is the ultra marathon, so a 10 km run is relevant context for it.", "en", False),
    ("MARATHON", "Ton objectif est le demi-marathon, cette sortie de 10 km reste pertinente pour lui.", "fr", False),
    ("MARATHON", "Tu objetivo es la media maratón, esta salida de 10 km sigue siendo relevante para él.", "es", False),
    ("MARATHON", "Your goal is the marathon, so a 10 km run is relevant context for it in general.", "en", True),
    ("ULTRA", "Your goal is the ultra marathon, so a 10 km run is relevant context for it in general.", "en", True),
    ("ULTRA", "Ton objectif est l'ultra-marathon, cette sortie de 10 km reste pertinente pour lui.", "fr", True),
    ("ULTRA", "Tu objetivo es el ultra maratón, esta salida de 10 km sigue siendo relevante para él.", "es", True),
    ("ULTRA", "Your goal is the marathon, so a 10 km run is relevant context for it in general.", "en", False),
    ("SEMI", "Tu objetivo es la media maratón, esta salida de 10 km sigue siendo relevante para él.", "es", True),
    ("HALF_MARATHON", "Ton objectif est le demi-marathon, cette sortie de 10 km reste pertinente pour lui.", "fr", True),
    ("HALF_MARATHON", "Your goal is the marathon, so a 10 km run is relevant context for it in general.", "en", False),
    ("5K", "Your goal is the 5k, so a 10 km run is relevant context for it in general.", "en", True),
    ("10K", "Your goal is the 5k, so a 10 km run is relevant context for it in general.", "en", False),
])
def test_goal_names_are_matched_to_the_declared_goal(goal, text, lang, expected):
    ok, reasons = _ok(text, _selected(goal={"goal_type": goal}), lang)
    assert ok is expected, reasons
    assert expected or "goal_mismatch" in reasons


# ---------------------------------------------------------------- A4 tomorrow / morning

@pytest.mark.parametrize("text,lang", [
    ("Mañana descansa y recupera bien después de estos 10 km a 5:32 por km en esta salida.", "es"),
    ("Mañana toca una salida suave después de estos 10 km a 5:32 por km en esta salida.", "es"),
    ("Demain matin tu devrais courir 8 km tranquillement après ces 10 km à 5:32 par km aujourd'hui.", "fr"),
    ("Tomorrow morning you should rest after this run of 10 km at 5:32 per km for the whole session.", "en"),
])
def test_tomorrow_prescriptions_stay_rejected(text, lang):
    ok, reasons = _ok(text, lang=lang)
    assert not ok and "prescription" in reasons


@pytest.mark.parametrize("text,lang", [
    ("Esta mañana corriste 10 km a 5:32 por km, con un ritmo estable durante toda la salida.", "es"),
    ("Corriste por la mañana 10 km a 5:32 por km, con un ritmo estable durante toda la salida.", "es"),
    ("Tu as couru 10 km ce matin, avec une allure de 5:32 par km sur toute la durée de la séance.", "fr"),
    ("You ran 10 km this morning at 5:32 per km, in a steady manner over the whole of this run.", "en"),
])
def test_descriptive_morning_is_not_a_prescription(text, lang):
    ok, reasons = _ok(text, lang=lang)
    assert ok, reasons


# ---------------------------------------------------------------- A5 pace gaps and units

@pytest.mark.parametrize("path_key,value,expected", [
    ("pace_difference_display", "-0:18/km", {"pace"}),
    ("pace_difference_display", "+0:10/km", {"pace"}),
    ("pace_difference_display", "-0:09/km", set()),
    ("pace_difference_sec_per_km", -18, {"pace"}),
    ("pace_difference_sec_per_km", 9, set()),
    ("pace_difference_min_km", -0.3, {"pace"}),
    ("pace_difference_min_km", 0.1, set()),
    ("pace_difference_min_km", 0.17, {"pace"}),
])
def test_pace_gap_threshold_uses_seconds_per_km_for_every_representation(path_key, value, expected):
    assert csc._material_gaps([(("comparison", "similar", path_key), value)]) == expected


def test_percent_gaps_are_attached_to_their_own_metric():
    facts = [(("comparison", "distance_km", "percent_change"), 12.0),
             (("comparison", "duration_minutes", "percent_change"), -3.0),
             (("comparison", "avg_heart_rate", "percent_change"), -10.0)]
    assert csc._material_gaps(facts) == {"distance", "heart_rate"}


def test_real_projection_of_a_pace_gap_is_detected():
    projected = coach_context_v2._project_paces_for_llm(
        {"comparison": {"similar": {"pace_difference_min_km": -0.3}}})
    _, compared = csc.split_session_facts({"workout_detail": {"analysis": projected}})
    assert csc._significant_gaps(compared)


def test_minutes_per_km_gap_grounds_seconds_not_the_raw_minutes():
    pools = csc._build_pools([(("comparison", "similar", "pace_difference_min_km"), -0.3)])
    assert 18 in pools["delta"] and 0.3 not in pools["delta"]
    absolute = csc._build_pools([(("avg_pace_min_km",), 5.5)])
    assert not absolute["delta"]


def test_pace_gap_figure_in_seconds_is_citable_from_the_display_string():
    ctx = _gap_context("-0:18/km")
    ok, r = _ok("Compared with similar sessions, this 10 km at 5:32 per km was 18 s/km faster.", ctx)
    assert ok, r


# ---------------------------------------------------------------- A7 minimizer

def test_minimizer_on_a_material_pace_gap_is_rejected():
    ok, r = _ok("This 10 km was slightly faster than similar sessions, by 18 s/km, at 5:32 per km.", _gap_context())
    assert not ok and "minimized_gap" in r


def test_minimizer_on_a_small_other_metric_is_accepted_despite_a_material_pace_gap():
    ok, r = _ok("The distance was slightly longer than similar sessions, at 10 km on this run today.",
                _gap_context("-0:18/km", distance_pct=2.0))
    assert ok, r


def test_minimizer_clause_is_attached_to_its_own_metric():
    text = "The distance was slightly longer than similar sessions, but the pace was faster by 18 s/km."
    ok, r = _ok(text, _gap_context("-0:18/km", 2.0))
    assert ok, r
    ok, r = _ok("The pace was slightly faster than similar sessions, but the distance was longer by 37 %.",
                _gap_context("-0:18/km", 37.0))
    assert not ok and "minimized_gap" in r


def test_minimizer_on_a_small_gap_is_accepted_and_without_metric_stays_conservative():
    ok, r = _ok("The pace was slightly faster than similar sessions on this 10 km at 5:32 per km.",
                _gap_context("-0:04/km", 2.0))
    assert ok, r
    ok, r = _ok("This run was only a little different from similar sessions, on 10 km at 5:32 per km.", _gap_context())
    assert not ok and "minimized_gap" in r


# ---------------------------------------------------------------- A6 abstentions

@pytest.mark.parametrize("text,lang", [
    ("Cette séance ne permet pas de conclure à une progression, même avec 10 km à 5:32 par km aujourd'hui.", "fr"),
    ("Cette séance n'a pas montré de progression, malgré ces 10 km à 5:32 par km sur toute la séance.", "fr"),
    ("Les données ne démontrent pas un gain d'endurance après ces 10 km à 5:32 par km dans cette séance.", "fr"),
    ("On ne peut pas déterminer l'intensité physiologique à partir de ces seules données, 10 km à 5:32 par km.", "fr"),
    ("These data do not show an improvement in endurance after 10 km at 5:32 per km in this session.", "en"),
    ("This session does not show how you are progressing, only 10 km at 5:32 per km during this run.", "en"),
    ("We cannot determine the intensity of this run from these data alone, only 10 km at 5:32 per km.", "en"),
    ("Los datos no demuestran una mejora de la resistencia tras estos 10 km a 5:32 por km en la salida.", "es"),
    ("No se puede determinar la intensidad fisiológica con estos datos, solo 10 km a 5:32 por km hoy.", "es"),
])
def test_prudent_abstention_wording_is_accepted(text, lang):
    ok, reasons = _ok(text, lang=lang)
    assert ok, reasons


@pytest.mark.parametrize("text,lang", [
    ("Cette séance n'a pas montré de progression, mais tu as fait 10 km avec une endurance meilleure.", "fr"),
    ("These data do not show it was hard, but your endurance improved on these 10 km at 5:32 per km.", "en"),
    ("You did not struggle: your endurance improved on these 10 km at 5:32 per km during this run.", "en"),
    ("No es posible negar que progresaste en esta salida de 10 km a 5:32 por km hoy mismo.", "es"),
    ("Has progresado mucho en esta salida de 10 km a 5:32 por km, con un ritmo estable.", "es"),
    ("Hay un progreso claro en esta salida de 10 km a 5:32 por km, con un ritmo estable.", "es"),
    ("The session does not cover much distance, and it built your endurance over 10 km at 5:32 per km.", "en"),
])
def test_positive_claims_are_not_authorized_by_a_negation_elsewhere(text, lang):
    ok, reasons = _ok(text, lang=lang)
    assert not ok and any(r in reasons for r in ("progress_claim", "endurance_claim")), reasons


# ---------------------------------------------------------------- A8 goal relevance

def test_general_relevance_is_allowed_but_not_effectiveness_progress_or_past_intent():
    ok, r = _ok("This long run is relevant context for your current marathon goal, though it does not show "
                "how you are progressing.")
    assert ok, r
    ok, r = _ok("A steady 10 km at 5:32 per km is generally relevant to a marathon goal, not proof of progress.")
    assert ok, r
    for text, reason, lang in [
        ("This session is perfect for your marathon goal and your marathon preparation, over 10 km.", "effectiveness_not_allowed", "en"),
        ("Your marathon training is paying off after this 10 km run at 5:32 per km in this session.", "progress_claim", "en"),
        ("You were already training for the marathon on that day, during this run of 10 km at 5:32 per km.", "goal_history_claim", "en"),
        ("Tu préparais déjà le marathon pendant cette sortie de 10 km à 5:32 par km, sur toute la séance.", "goal_history_claim", "fr"),
    ]:
        ok, r = _ok(text, lang=lang)
        assert not ok and reason in r, (text, r)


# ---------------------------------------------------------------- A9 comparison permission

def test_history_alone_does_not_open_a_similar_sessions_or_usual_comparison():
    ctx = _hist()  # similar_comparison_available False, history present
    for text in ["This 10 km run at 5:32 per km was faster than your similar sessions, on a steady day.",
                 "This 10 km run at 5:32 per km was faster than usual, on a steady day."]:
        ok, r = _ok(text, ctx)
        assert not ok and "comparison_not_available" in r, (text, r)


def test_similar_sessions_comparison_needs_and_gets_the_c388_permission():
    ok, r = _ok("This 10 km run at 5:32 per km was faster than your similar sessions, on a steady day.",
                _hist(comparison=True))
    assert ok, r


def test_exact_prior_session_juxtaposition_stays_available_from_history():
    ok, r = _ok("This 10 km at 5:32 per km was faster than your earlier run of 8 km at 6:00 per km.", _hist())
    assert ok, r


def test_history_description_needs_no_comparison_permission():
    ok, r = _ok("Your previous run covered 8 km at 6:00 per km, before this run of 10 km at 5:32 per km.", _hist())
    assert ok, r


# ---------------------------------------------------------------- A10 historical values and dates

@pytest.mark.parametrize("text", [
    "On 8 January you ran 8 km at 6:00 per km in an earlier session, before this one.",
    "On 5 January you ran 12 km at 5:50 per km in an earlier session, before this one.",
    "Before this run you ran 8 km on 8 January, at an average pace of 6:00 per km.",
    "The 8 km run at 6:00 per km was in your history, before this one.",
    "On 2026-01-08 you ran 8 km in an earlier session, before this one.",
])
def test_exact_dated_history_is_accepted_without_comparison_vocabulary(text):
    ok, r = _ok(text, _hist())
    assert ok, r


@pytest.mark.parametrize("text,reason", [
    ("On 8 January you ran 12 km at 6:00 per km in an earlier session, before this one.", "history_misattribution"),
    ("On 5 January you ran 8 km at 6:00 per km in an earlier session, before this one.", "history_misattribution"),
    ("On 9 January you ran 8 km at 6:00 per km in an earlier session, before this one.", "ungrounded_date"),
    ("On 8 January you ran 10 km at 5:32 per km in an earlier session, before this one.", "history_misattribution"),
    ("On 8 January you ran 9 km at 6:00 per km in an earlier session, before this one.", "ungrounded_number"),
    ("On 8 and 5 January you ran 8 km in earlier sessions, before this one.", "history_misattribution"),
    ("Your last run had 8 km at 5:50 per km, before this one.", "history_misattribution"),
])
def test_wrong_history_attribution_is_rejected(text, reason):
    ok, r = _ok(text, _hist())
    assert not ok and reason in r, r


def test_a_history_date_with_no_history_is_rejected_and_a_month_alone_is_not_a_date():
    ok, r = _ok("On 8 January you ran 8 km at 6:00 per km in an earlier session.", _hist(sessions=[]))
    assert not ok and "ungrounded_date" in r
    assert _ok("In January you ran 8 km at 6:00 per km in an earlier session, before this one.", _hist())[0]


def test_two_history_sessions_on_the_same_date_are_told_apart_by_their_values():
    sessions = [dict(HISTORY[0], date="2026-01-08T07:00:00"),
                {"date": "2026-01-08T18:00:00", "type": "run", "distance_km": 4.0, "avg_pace_display": "6:30/km"},
                HISTORY[1], HISTORY[2]]
    ctx = _hist(sessions)
    assert _ok("On 8 January you ran 4 km at 6:30 per km in an earlier session, before this one.", ctx)[0]
    ok, r = _ok("On 8 January you ran 4 km at 6:00 per km in an earlier session, before this one.", ctx)
    assert not ok and "history_misattribution" in r


def test_history_selection_is_not_mutated():
    ctx = _llm_context()
    snapshot = copy.deepcopy(ctx)
    csc.build_comment_context(ctx)
    assert ctx == snapshot


# ------------------------------------------- arbitrage: direct descriptive historical comparison

_DESC = "This 10 km at 5:32 per km compares with 8 km at 6:00 per km on 8 January"


def _day(sessions, start, comparison=False):
    ctx = _llm_context()
    ctx["selected_workout_permissions"]["similar_comparison_available"] = comparison
    ctx["workout_detail"]["date"] = "2026-01-10"
    ctx["workout_detail"]["start_time"] = start
    ctx["recent_workouts"] = sessions
    return csc.build_comment_context(ctx)


def _rejected(text, ctx, reason, lang="en"):
    ok, reasons = csc.validate_session_comment(text, ctx, lang)
    assert not ok and reason in reasons, reasons


@pytest.mark.parametrize("lang,text", [
    ("en", _DESC + "."),
    ("fr", "Cette sortie affiche 10 km à 5:32/km, contre 8 km à 6:00/km lors de ta sortie du 8 janvier."),
    ("es", "Esta salida muestra 10 km a 5:32/km, frente a 8 km a 6:00/km en tu salida del 8 de enero."),
])
def test_exact_descriptive_history_comparison_is_accepted_without_c388_permission(lang, text):
    ok, reasons = csc.validate_session_comment(text, _hist(), lang)
    assert ok, reasons


@pytest.mark.parametrize("text", [
    "This 10 km at 5:32 per km compares with 8 km at 5:50 per km on 8 January.",
    "This 10 km at 5:32 per km compares with 12 km at 6:00 per km on 8 January.",
])
def test_history_value_attributed_to_the_wrong_session_is_rejected(text):
    _rejected(text, _hist(), "history_misattribution")


def test_comparison_with_a_later_session_is_rejected():
    later = [{"date": "2026-01-12T07:00:00", "type": "run", "distance_km": 8.0, "avg_pace_display": "6:00/km"}]
    ok, _ = _ok(_DESC.replace("on 8 January", "") + ".", _hist(sessions=later))
    assert not ok


def test_same_day_comparison_needs_proven_anteriority():
    text = "This 10 km at 5:32 per km compares with your earlier run of 8 km at 6:00 per km."
    date_only = [{"date": "2026-01-10", "type": "run", "distance_km": 8.0, "avg_pace_display": "6:00/km"}]
    proven = [{"date": "2026-01-10T06:00:00", "type": "run", "distance_km": 8.0, "avg_pace_display": "6:00/km"}]
    later = [{"date": "2026-01-10T09:00:00", "type": "run", "distance_km": 8.0, "avg_pace_display": "6:00/km"}]
    assert not _ok(text, _day(date_only, None))[0]
    assert not _ok(text, _day(later, "2026-01-10T07:30:00"))[0]
    assert _ok(text, _day(proven, "2026-01-10T07:30:00"))[0]


@pytest.mark.parametrize("lang,text", [
    ("en", "You ran faster than usual."),
    ("fr", "Tu cours plus vite que d'habitude."),
    ("en", "This is faster than your similar sessions."),
    ("es", "Vas más rápido que tus sesiones similares."),
])
def test_statistical_comparisons_stay_rejected_without_c388_permission(lang, text):
    _rejected(text, _hist(), "comparison_not_available", lang)


@pytest.mark.parametrize("lang,tail,reason", [
    ("en", ", so you are progressing", "progress_claim"),
    ("en", ", so you are more efficient at equal heart rate", "efficiency_not_allowed"),
    ("en", ", which shows your training works", "effectiveness_not_allowed"),
    ("en", ", showing a higher intensity for your body", "intensity_not_allowed"),
])
def test_exact_history_comparison_never_carries_a_conclusion(lang, tail, reason):
    _rejected(_DESC + tail + ".", _hist(), reason, lang)


@pytest.mark.parametrize("lang,text,reason", [
    ("fr", "Tu progresses par rapport à tes séances précédentes.", "progress_claim"),
    ("fr", "Tu es désormais plus efficace à fréquence cardiaque égale.", "efficiency_not_allowed"),
    ("fr", "Cette séance montre que ton entraînement fonctionne.", "effectiveness_not_allowed"),
    ("es", "Esta sesión muestra que tu entrenamiento funciona.", "effectiveness_not_allowed"),
    ("en", "This session shows your training is working.", "effectiveness_not_allowed"),
])
def test_progress_efficiency_and_effectiveness_conclusions_are_rejected(lang, text, reason):
    _rejected(text, _hist(), reason, lang)


def test_c388_authorised_similar_comparison_is_preserved():
    ok, reasons = _ok("This 10 km at 5:32 per km was faster than your similar sessions.", _hist(comparison=True))
    assert ok, reasons


def test_insufficient_history_rejects_without_inventing_a_session():
    ok, reasons = _ok(_DESC + ".", _hist(sessions=[]))
    assert not ok and "ungrounded_date" in reasons


# ------------------------------------------------ review round: seven Copilot alerts on PR #390

def _rejects(text, ctx, reason, lang="en"):
    ok, reasons = csc.validate_session_comment(text, ctx, lang)
    assert not ok and reason in reasons, reasons


def _accepts(text, ctx, lang="en"):
    ok, reasons = csc.validate_session_comment(text, ctx, lang)
    assert ok, reasons


# 1. timestamps and time zones

def _tz_dates(selected_at, sessions):
    return _dates(_dated_context(selected_at[:10], selected_at, [
        {"date": d, "type": "run", "distance_km": 5.0} for d in sessions]))


def test_exact_instants_decide_across_time_zones():
    # 00:30+02:00 on the 11th is 22:30Z on the 10th: earlier than 23:00Z although the date is later.
    kept = _tz_dates("2026-01-10T23:00:00Z", ["2026-01-11T00:30:00+02:00", "2026-01-10T23:30:00Z"])
    assert kept == ["2026-01-11T00:30:00+02:00"]


def test_exact_instants_exclude_a_later_session_with_an_earlier_calendar_date():
    # 2026-01-10T23:30:00-05:00 is 04:30Z on the 11th: later than 2026-01-11T01:00:00Z.
    assert _tz_dates("2026-01-11T01:00:00Z", ["2026-01-10T23:30:00-05:00"]) == []


def test_naive_and_aware_timestamps_never_raise_and_naive_is_not_utc():
    # C408-C: a naive Garmin local time is not UTC; the order must hold for every real UTC offset.
    kept = _tz_dates("2026-01-10T12:00:00+00:00", ["2026-01-10T11:00:00", "2026-01-10T13:00:00",
                                                    "2026-01-09T20:00:00+05:00", "2026-01-08T11:00:00"])
    assert kept == ["2026-01-09T20:00:00+05:00", "2026-01-08T11:00:00"]
    assert set(_tz_dates("2026-01-10T12:00:00", ["2026-01-10T11:00:00Z", "2026-01-10T12:30:00+01:00",
                                                  "2026-01-08T13:30:00+01:00"])) \
        == {"2026-01-08T13:30:00+01:00"}


def test_equal_calendar_dates_remain_no_proof_when_one_side_is_date_only():
    assert _tz_dates("2026-01-10T12:00:00Z", ["2026-01-10", "2026-01-09"]) == ["2026-01-09"]
    selected = _dated_context("2026-01-10", None, [{"date": "2026-01-10T01:00:00+02:00", "type": "run",
                                                    "distance_km": 5.0}])
    assert _dates(selected) == []


# 2. counters are not distances

_FOUR = [{"date": f"2026-01-0{i}T07:00:00", "type": "run", "distance_km": (5.0 + i if i < 4 else None)}
         for i in range(1, 5)]


def test_session_tally_is_a_count_not_a_distance():
    ctx = _hist(sessions=_FOUR)
    assert ctx["runner_profile"]["observed_training"]["sessions_with_distance_count"] == 3
    _accepts("Your history holds 3 sessions with a recorded distance, so the average rests on those only.", ctx)
    for text in ("You covered 3 km on one of your earlier runs, which this long outing of 10 km repeats.",
                 "You covered 3,000 m on one of your earlier runs, which this long outing of 10 km repeats.",
                 "You covered 3 000 m on one of your earlier runs, which this long outing of 10 km repeats."):
        ok, reasons = _ok(text, ctx)
        assert not ok and "ungrounded_number" in reasons, text


def test_real_historical_distances_and_known_distance_average_are_still_grounded():
    ctx = _hist(sessions=_FOUR)
    _accepts("Your sessions with a known distance usually cover 7.0 km, "
             "so this run of 10 km at 5:32 per km was longer than usual.", ctx)


# 3. past progressive describes the run, not the goal

@pytest.mark.parametrize("lang,text", [
    ("en", "You were running at 5:32 per km over 10 km, which is generally relevant to your current marathon goal."),
    ("fr", "Tu courais à 5:32/km sur 10 km, ce qui est généralement pertinent pour ton objectif marathon actuel."),
    ("es", "Corrías a 5:32/km durante 10 km, lo que es generalmente relevante para tu objetivo actual de maratón."),
])
def test_past_description_of_the_run_with_current_goal_relevance_is_accepted(lang, text):
    _accepts(text, _hist(), lang)


@pytest.mark.parametrize("lang,text", [
    ("en", "You were already preparing for your marathon that day."),
    ("en", "You were training for the marathon on this run of 10 km at 5:32 per km."),
    ("en", "At the time you were targeting a marathon."),
    ("en", "Your marathon goal was already set on this run of 10 km at 5:32 per km."),
    ("fr", "Tu préparais déjà ton marathon à l'époque."),
    ("fr", "Ton objectif marathon était déjà fixé ce jour-là."),
    ("es", "Ya preparabas tu maratón en esa época."),
    ("es", "Tu objetivo de maratón ya existía ese día."),
])
def test_unproven_historical_goal_intent_stays_rejected(lang, text):
    _rejects(text, _hist(), "goal_history_claim", lang)


# 4. a negation must bear on the conclusion, not refuse its denial

@pytest.mark.parametrize("lang,text", [
    ("en", "We cannot conclude that your endurance improved over this run of 10 km at 5:32 per km."),
    ("en", "This session does not demonstrate progress over this run of 10 km at 5:32 per km."),
    ("en", "These data cannot show that you are progressing on this run of 10 km."),
    ("fr", "On ne peut pas conclure que ton endurance s'est améliorée sur cette sortie de 10 km."),
    ("fr", "Cette séance de 10 km à 5:32/km ne permet pas de conclure à une progression."),
    ("es", "No se puede concluir que tu resistencia mejoró en esta salida de 10 km."),
    ("es", "Esta salida de 10 km a 5:32/km no demuestra una progresión."),
])
def test_genuine_abstentions_about_progress_are_accepted(lang, text):
    _accepts(text, _hist(), lang)


@pytest.mark.parametrize("lang,text", [
    ("en", "We cannot deny that your endurance improved over this run of 10 km at 5:32 per km."),
    ("en", "We cannot deny your progress over this run of 10 km at 5:32 per km."),
    ("en", "It is impossible not to see your progress over this run of 10 km at 5:32 per km."),
    ("en", "This session does not fail to show your progress over this run of 10 km at 5:32 per km."),
    ("fr", "On ne peut nier que ton endurance s'est améliorée sur cette sortie de 10 km à 5:32/km."),
    ("es", "No se puede negar que has progresado en esta salida de 10 km a 5:32/km."),
])
def test_a_negation_never_authorises_the_positive_claim(lang, text):
    ok, reasons = csc.validate_session_comment(text, _hist(), lang)
    assert not ok and ({"progress_claim", "endurance_claim"} & set(reasons)), reasons


@pytest.mark.parametrize("lang,text", [
    ("en", "We cannot determine the intensity from this data, but you have clearly progressed over this run of 10 km."),
    ("fr", "On ne peut pas déterminer l'intensité, mais tu as clairement progressé sur cette sortie de 10 km."),
    ("es", "No se puede determinar la intensidad, pero has progresado claramente en esta salida de 10 km."),
])
def test_an_abstention_about_another_subject_does_not_open_a_progress_claim(lang, text):
    _rejects(text, _hist(), "progress_claim", lang)


# 5. a date keeps its values even next to comparing wording

def test_values_next_to_a_historical_date_must_belong_to_that_session_despite_comparison_wording():
    ctx = _hist(comparison=True)
    for text in (
            "On 8 January you ran 10 km at 5:32 per km, compared with similar sessions.",
            "On 8 January, you ran 10 km at 5:32 per km, compared with similar sessions.",
            "Compared with similar sessions, on 8 January you ran 10 km at 5:32 per km.",
            "On 8 January you ran 10 km at 6:00 per km, compared with this 8 km at 5:32 per km.",
            "This 8 km at 5:32 per km compares with 10 km at 6:00 per km on 8 January."):
        _rejects(text, ctx, "history_misattribution")


@pytest.mark.parametrize("lang,text", [
    ("en", "This 10 km at 5:32 per km compares with 8 km at 6:00 per km on 8 January."),
    ("en", "On 8 January you ran 8 km at 6:00 per km, compared with this 10 km at 5:32 per km."),
    ("en", "On 8 January, you ran 8 km at 6:00 per km, compared with this 10 km at 5:32 per km."),
    ("fr", "Cette sortie affiche 10 km à 5:32/km, contre 8 km à 6:00/km lors de ta sortie du 8 janvier."),
    ("es", "Esta salida muestra 10 km a 5:32/km, frente a 8 km a 6:00/km en tu salida del 8 de enero."),
])
def test_correct_current_versus_dated_prior_comparisons_are_preserved(lang, text):
    for permission in (False, True):
        _accepts(text, _hist(comparison=permission), lang)


def test_two_different_dates_in_one_segment_are_ambiguous_and_rejected():
    ok, reasons = _ok("On 8 January or 5 January you ran 8 km at 6:00 per km, compared with this run.", _hist())
    assert not ok and "history_misattribution" in reasons


# 6. a date is not a measurement

def test_a_date_alone_never_opens_a_performance_comparison():
    ctx = _hist()
    for text in ("Your run was faster than usual, and your previous run was on 8 January.",
                 "Your previous run was on 8 January; this run was faster than usual.",
                 "Your run was slower than your earlier one, dated 8 January."):
        _rejects(text, ctx, "comparison_not_available")


def test_a_date_with_its_measurement_still_anchors_the_comparison_and_plain_history_stays_allowed():
    _accepts("This 10 km at 5:32 per km was faster than your earlier run of 8 km at 6:00 per km on 8 January.", _hist())
    _accepts("Your previous run was on 8 January and covered 8 km at 6:00 per km.", _hist())
    _accepts("Your previous run was on 8 January, a date given here for context only.", _hist())
    _accepts("Your run was faster than usual, and your previous run was on 8 January.", _hist(comparison=True))


# 7. an explicit metric name outranks an ambiguous adjective

def _gaps(distance=2.0, duration=20.0, heart_rate=None, pace=None):
    ctx = _llm_context()
    comparison = ctx["workout_detail"]["analysis"]["comparison"]
    comparison["similar"].pop("pace_difference_sec_per_km", None)
    if pace:
        comparison["similar"]["pace_difference_display"] = pace
    comparison["distance_km"] = {"percent_change": distance}
    comparison["duration_minutes"] = {"percent_change": duration}
    if heart_rate is not None:
        comparison["heart_rate"] = {"percent_change": heart_rate}
    return csc.build_comment_context(ctx)


@pytest.mark.parametrize("lang,text", [
    ("en", "The distance was slightly longer than similar sessions, at 10 km on this run today."),
    ("fr", "La distance était légèrement plus longue que les séances similaires, soit 10 km aujourd'hui."),
    ("es", "La distancia fue ligeramente más larga que las sesiones similares, con 10 km hoy."),
])
def test_small_distance_gap_is_not_rejected_for_an_unrelated_duration_gap(lang, text):
    _accepts(text, _gaps(), lang)


@pytest.mark.parametrize("lang,text", [
    ("en", "The duration was slightly longer than similar sessions."),
    ("fr", "La durée était légèrement plus longue que les séances similaires."),
    ("es", "La duración fue ligeramente más larga que las sesiones similares."),
    ("en", "The distance was slightly longer than similar sessions."),
    ("en", "The run was slightly longer than similar sessions."),
])
def test_minimizing_a_material_gap_or_an_ambiguous_metric_stays_rejected(lang, text):
    ctx = _gaps(distance=20.0 if text.startswith("The distance") else 2.0)
    _rejects(text, ctx, "minimized_gap", lang)


def test_heart_rate_and_pace_are_tied_to_their_own_clause():
    ctx = _gaps(distance=2.0, duration=2.0, heart_rate=15.0, pace="-0:18/km")
    _accepts("The distance was barely longer than similar sessions, at 10 km on this run today.", ctx)
    _rejects("The heart rate was slightly higher than similar sessions.", ctx, "minimized_gap")
    _rejects("The pace was slightly faster than similar sessions.", ctx, "minimized_gap")
    _accepts("The distance was slightly longer than similar sessions, but the pace was clearly faster.", ctx)
    _rejects("La fréquence cardiaque était légèrement plus haute que les séances similaires.", ctx, "minimized_gap", "fr")
