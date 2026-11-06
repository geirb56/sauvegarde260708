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
