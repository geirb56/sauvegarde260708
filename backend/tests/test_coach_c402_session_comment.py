"""C402 — selected context and claim-level guard for the automatic session comment.

All cases are SYNTHETIC (the C401 corpus no longer exists). No LLM is called: these tests
check deterministic code, not the quality or truthfulness of real model output.
"""

import copy
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest
from fastapi import HTTPException

import coach_session_comment as csc
from test_coach_c400_session_comment import _ctx
from test_coach_context_v2 import _Collection, _FakeDB, _USER_ID, _performance, _readiness_decision, \
    _training_load, _training_paces
import server
from training_v2.plan_goal import GoalType

HISTORY = [
    {"date": "2026-01-08T07:00:00", "type": "run", "distance_km": 8.0, "duration_minutes": 48.0,
     "avg_pace_display": "6:00/km", "avg_heart_rate": 150.0, "name": "Free title"},
    {"date": "2026-01-05T07:00:00", "type": "run", "distance_km": 12.0, "duration_minutes": 70.0,
     "avg_pace_display": "5:50/km", "avg_heart_rate": 155.0},
    {"date": "2026-01-02T07:00:00", "type": "run", "distance_km": 5.0, "duration_minutes": 30.0},
]


def _llm_context():
    ctx = _ctx(similar_comparison_available=True)
    ctx["selected_workout_history_cutoff"] = "2026-01-10T07:30:00+00:00"
    ctx["recent_workouts"] = copy.deepcopy(HISTORY)
    ctx["recent_workouts_coverage"] = {"window_days": 90, "truncated": False, "included_count": 3}
    ctx["goal"] = {"objective": "Free event name", "goal_type": "MARATHON", "race_date": None}
    ctx["training_state"] = {"phase": "build", "current_week": 7}
    ctx["current_training_context"] = {"stats_7d": {"km": 30.0}}
    ctx["workout_detail"]["name"] = "Free title"
    ctx["workout_detail"]["analysis"]["comparison"]["similar"].update(
        {"comparable": False, "pace_difference_sec_per_km": -18})
    ctx["workout_detail"]["analysis"]["comparison"]["distance_km"] = {"percent_change": 37.0}
    return ctx


def _selected(**override):
    ctx = _llm_context()
    ctx.update(override)
    return csc.build_comment_context(ctx)


def _ok(text, ctx=None, lang="en"):
    return csc.validate_session_comment(text, ctx or _selected(), lang)


# ------------------------------------------------------------------ context selection

def test_selected_context_has_five_labelled_categories_and_drops_current_state():
    ctx = _selected()
    assert {"workout_detail", "history_as_of_session", "runner_profile", "declared_goal",
            "reliable_physiology"} <= set(ctx)
    for dropped in ("training_state", "current_training_context", "readiness", "today", "goal", "recent_workouts"):
        assert dropped not in ctx
    assert "name" not in ctx["workout_detail"]
    assert all("name" not in s and "id" not in s for s in ctx["history_as_of_session"]["sessions"])
    assert ctx["history_as_of_session"]["trend"] == "not_established"


def test_declared_goal_is_current_and_never_proves_session_purpose():
    goal = _selected()["declared_goal"]
    assert goal["goal_type"] == "MARATHON" and goal["status"] == "current_declared_goal"
    assert goal["historical_goal_status"] == "unknown" and goal["is_race_goal"] is True
    assert "race_date" not in goal and "objective" not in goal  # free text / unreliable fields are not forwarded


def test_missing_goal_is_omitted_not_defaulted():
    ctx = _llm_context()
    ctx.pop("goal")
    assert "declared_goal" not in csc.build_comment_context(ctx)


def test_maintenance_is_not_a_race_goal():
    ctx = _llm_context()
    ctx["goal"]["goal_type"] = "MAINTENANCE"
    assert csc.build_comment_context(ctx)["declared_goal"]["is_race_goal"] is False


def test_profile_has_no_invented_experience_and_needs_enough_history():
    profile = _selected()["runner_profile"]
    assert profile["experience"] == "not_provided"
    assert profile["observed_training"] == {"sessions_count": 3, "total_km": 25.0, "avg_km_per_session": 8.3}
    few = _llm_context()
    few["recent_workouts"] = few["recent_workouts"][:2]
    assert "observed_training" not in csc.build_comment_context(few)["runner_profile"]
    truncated = _llm_context()
    truncated["recent_workouts_coverage"]["truncated"] = True
    assert "observed_training" not in csc.build_comment_context(truncated)["runner_profile"]


def test_physiology_block_grants_nothing_beyond_permissions():
    physio = _selected()["reliable_physiology"]
    assert physio == {"intensity_interpretation_allowed": False, "lt1_lt2_vo2max_fcmax": "not_provided"}


# ------------------------------------------------------------------ number handling

def test_exact_seconds_gap_from_context_is_accepted():
    ok, r = _ok("Compared with similar runs you were 18 seconds per km faster, over 10 km at 5:32 per km.")
    assert ok, r


def test_history_figures_are_accepted_only_as_history():
    assert _ok("Your last run was 8 km at 6:00 per km, so this 10 km run at 5:32 per km was longer than usual.")[0]
    ok, r = _ok("You ran 8 km at 6:00 per km today and kept the same steady rhythm all along that session.")
    assert not ok and "comparison_value_as_session" in r


def test_history_numbers_absent_from_context_are_rejected():
    ok, r = _ok("Last time you ran 9 km at 6:10 per km, so today's 10 km at 5:32 per km was a bit longer.")
    assert not ok and "ungrounded_number" in r


def test_history_wording_without_history_is_not_available():
    ctx = _llm_context()
    ctx["recent_workouts"] = []
    ok, r = _ok("This was longer than usual, with 10 km at 5:32 per km and a steady pace.",
                csc.build_comment_context({**ctx, "selected_workout_permissions":
                                           {**ctx["selected_workout_permissions"], "similar_comparison_available": False}}))
    assert not ok and "comparison_not_available" in r


@pytest.mark.parametrize("text", [
    "You slowed down only once, near the end, after 10 km at 5:32 per km of steady running today.",
    "Tu as ralenti une fois seulement, vers la fin de ta sortie de 10 km à 5:32 par km aujourd'hui.",
])
def test_once_idiom_is_not_a_measured_number(text):
    lang = "fr" if text.startswith("Tu") else "en"
    assert _ok(text, lang=lang)[0]


def test_number_words_are_verified_not_blanket_rejected():
    assert _ok("You ran ten km at 5:32 per km and the pace stayed steady for the whole run today.")[0]
    ok, r = _ok("You ran nine km at 5:32 per km and the pace stayed steady for the whole run today.")
    assert not ok and "ungrounded_number" in r


# ------------------------------------------------------------------ qualitative claims

@pytest.mark.parametrize("text,reason", [
    ("You are clearly getting stronger and you are in better shape than a few weeks ago on this run.", "progress_claim"),
    ("Consistency is paying off and you are on the right track after this 10 km at 5:32 per km.", "progress_claim"),
    ("This long run built your endurance nicely and your stamina is higher now after 10 km today.", "endurance_claim"),
    ("This was a very effective session for your preparation, with 10 km at 5:32 per km today.", "effectiveness_not_allowed"),
    ("C'était une séance très utile pour ta préparation, avec 10 km à 5:32 par km aujourd'hui.", "effectiveness_not_allowed"),
    ("The session was a success: 10 km at 5:32 per km, and you nailed it from start to finish today.", "success_claim"),
    ("Séance réussie, tu as parfaitement tenu ton rythme de 5:32 par km sur 10 km aujourd'hui.", "success_claim"),
    ("You stayed in your comfort zone for the whole run, 10 km at 5:32 per km today, and it was easy.", "intensity_not_allowed"),
])
def test_qualitative_conclusions_are_rejected(text, reason):
    lang = "fr" if text.startswith(("C'était", "Séance")) else "en"
    ok, reasons = _ok(text, lang=lang)
    assert not ok and reason in reasons, reasons


def test_goal_context_allowed_but_no_design_or_wrong_goal_claims():
    assert _ok("Your current goal is a marathon, so a steady 10 km at 5:32 per km is generally useful for you.")[0]
    ok, r = _ok("This 10 km at 5:32 per km was designed specifically for your marathon goal and your next race.")
    assert not ok and "goal_design_claim" in r
    ok, r = _ok("For your half marathon goal, a steady 10 km at 5:32 per km is generally a useful run today.")
    assert not ok and "goal_mismatch" in r


def test_goal_words_without_declared_goal_are_rejected():
    ctx = _llm_context()
    ctx.pop("goal")
    ok, r = _ok("For your marathon goal, a steady 10 km at 5:32 per km is a useful run today.",
                csc.build_comment_context(ctx))
    assert not ok and "context_as_session_fact" in r


def test_minimized_material_gap_is_rejected_exact_gap_accepted():
    ok, r = _ok("Compared with similar runs your pace was barely different, 5:32 against 5:50 over 10 km.")
    assert not ok and "minimized_gap" in r
    assert _ok("Compared with similar runs you were 18 seconds per km faster, 5:32 against 5:50 over 10 km.")[0]


# ------------------------------------------------------------------ false positives fixed

@pytest.mark.parametrize("text,lang", [
    ("Le plus dur est derrière toi : 10 km à 5:32 par km, avec un rythme régulier du début à la fin de la sortie.", "fr"),
    ("Cette semaine, tu as couru 10 km à 5:32 par km avec un rythme régulier tout au long de la sortie.", "fr"),
    ("Je ne peux pas dire si c'était facile ou dur, car 10 km à 5:32 par km ne donnent pas l'intensité réelle.", "fr"),
    ("Hay 4 esfuerzos y 3 recuperaciones en esta salida de 10 km, con un ritmo regular de 5:32 por km hoy.", "es"),
    ("Por la mañana corriste 10 km a 5:32 por km, con un ritmo regular de principio a fin en esta salida.", "es"),
    ("The 4 efforts and 3 recoveries in this 10 km run at 5:32 per km were the main feature of the session.", "en"),
])
def test_common_expressions_and_cautious_wording_are_not_rejected(text, lang):
    ok, r = _ok(text, lang=lang)
    assert ok, r


@pytest.mark.parametrize("text", [
    "This was a recovery run at an easy pace, 10 km at 5:32 per km, and the effort stayed low today.",
    "You ran 10 km at 5:32 per km in a hard session today and the effort was intense throughout the run.",
])
def test_real_intensity_labels_remain_rejected(text):
    ok, r = _ok(text)
    assert not ok and "intensity_not_allowed" in r


def test_physiology_terms_remain_rejected():
    ok, r = _ok("You ran 10 km at 5:32 per km, just below your LT1 threshold, over the whole session today.")
    assert not ok and "unsupported_physiology" in r


# ------------------------------------------------------------------ route context

async def _build(goal_error: bool):
    db = _FakeDB()
    db.workouts = _Collection([
        {"id": "w-selected", "user_id": _USER_ID, "date": "2026-09-12T09:00:00Z", "name": "Free title",
         "type": "run", "distance_km": 12.0, "duration_minutes": 60.0, "avg_heart_rate": 155},
        {"id": "w-hist-1", "user_id": _USER_ID, "date": "2026-09-05T09:00:00Z", "name": "Earlier",
         "type": "run", "distance_km": 11.5, "duration_minutes": 58.0, "avg_heart_rate": 152},
    ])
    goal = SimpleNamespace(goal_type="MARATHON", mapped_goal=GoalType.marathon, cycle_start=date(2026, 8, 1),
                           race_date=date(2026, 11, 1), target_time_sec=12600, target_distance_km=None,
                           user_goal_doc=None)
    resolver = (AsyncMock(side_effect=HTTPException(status_code=400, detail="No training goal defined."))
                if goal_error else AsyncMock(return_value=goal))
    acts = [SimpleNamespace(activity_type="running", start_time=datetime(2026, 9, 16, 6, tzinfo=timezone.utc),
                            distance_m=12000.0)]
    patches = [
        patch("server._resolve_canonical_reference_date", return_value=date(2026, 9, 16)),
        patch("server._resolve_goal_v2", resolver),
        patch("server.mongo_garmin_activities_to_domain", side_effect=lambda d: acts if d else []),
        patch("server.build_training_load", return_value=_training_load()),
        patch("server.build_readiness_v2_from_garmin_data", return_value=None),
        patch("server.build_readiness_decision", return_value=_readiness_decision()),
        patch("server.predict_races", return_value=_performance()),
        patch("server.load_canonical_training_paces", AsyncMock(return_value=_training_paces())),
        patch("coach_context_v2.training_paces_to_api_dict", return_value={"paces": {}}),
    ]
    previous_db = server.db
    server.db = db
    for p in patches:
        p.start()
    try:
        workout, analysis = await server.load_scoped_workout_analysis_v2(
            db=db, user_id=_USER_ID, workout_id="w-selected", language="en")
        return await server._build_coach_comment_context(
            user={"id": _USER_ID}, language="en", workout=workout, workout_analysis=analysis,
            workout_id="w-selected", now_utc=datetime(2026, 9, 16, tzinfo=timezone.utc))
    finally:
        for p in patches:
            p.stop()
        server.db = previous_db


@pytest.mark.asyncio
async def test_route_context_is_selected_and_goal_is_current_declared():
    ctx, _ = await _build(goal_error=False)
    assert ctx["declared_goal"]["goal_type"] == "MARATHON"
    assert ctx["workout_detail"]["id"] == "w-selected" and "name" not in ctx["workout_detail"]
    for dropped in ("training_state", "readiness", "training_load", "performance", "today", "weekly_target",
                    "current_training_context", "goal"):
        assert dropped not in ctx


@pytest.mark.asyncio
async def test_route_context_without_declared_goal_still_builds_and_has_no_goal():
    ctx, _ = await _build(goal_error=True)
    assert "workout_detail" in ctx and "declared_goal" not in ctx


# ------------------------------------------------------------------ C402 follow-up: history attribution

def _hist(sessions=None, truncated=False, comparison=False):
    ctx = _llm_context()
    ctx["selected_workout_permissions"]["similar_comparison_available"] = comparison
    if sessions is not None:
        ctx["recent_workouts"] = sessions
    ctx["recent_workouts_coverage"]["truncated"] = truncated
    return csc.build_comment_context(ctx)


NEAR = [
    {"date": "2026-01-08T07:00:00", "type": "run", "distance_km": 8.0, "avg_pace_display": "6:00/km"},
    {"date": "2026-01-06T07:00:00", "type": "run", "distance_km": 8.1, "avg_pace_display": "5:40/km"},
    {"date": "2026-01-03T07:00:00", "type": "run", "distance_km": 12.0, "avg_pace_display": "5:50/km"},
]


def test_history_value_attributed_to_the_right_session_is_accepted():
    ok, r = _ok("This 10 km at 5:32 per km was faster than your earlier run of 8 km at 6:00 per km.", _hist())
    assert ok, r
    ok, r = _ok("This 10 km at 5:32 per km was faster than your earlier run of 12 km at 5:50 per km.", _hist())
    assert ok, r


def test_exact_value_attributed_to_another_session_is_rejected():
    ok, r = _ok("This 10 km at 5:32 per km was faster than your earlier run of 8 km at 5:50 per km.", _hist())
    assert not ok and "history_misattribution" in r
    ok, r = _ok("This 10 km at 5:32 per km was slower than your earlier run of 12 km at 6:00 per km.", _hist())
    assert not ok and "history_misattribution" in r


def test_value_absent_from_history_is_rejected():
    ok, r = _ok("This 10 km at 5:32 per km was faster than your earlier run of 9 km at 6:00 per km.", _hist())
    assert not ok and "ungrounded_number" in r


def test_close_sessions_are_attributed_correctly():
    hist = _hist(NEAR)
    assert _ok("This 10 km at 5:32 per km was faster than your earlier run of 8.1 km at 5:40 per km.", hist)[0]
    assert _ok("This 10 km at 5:32 per km was faster than your earlier run of 8.0 km at 6:00 per km.", hist)[0]
    ok, r = _ok("This 10 km at 5:32 per km was faster than your earlier run of 8.0 km at 5:40 per km.", hist)
    assert not ok and "history_misattribution" in r


def test_two_prior_sessions_in_one_sentence_are_rejected_not_guessed():
    ok, r = _ok("This 10 km at 5:32 per km was faster than 8 km at 6:00 per km and than 12 km at 5:50 per km.", _hist())
    assert not ok and "history_misattribution" in r


def test_c388_baseline_value_cannot_be_pinned_on_a_prior_session():
    ctx = _llm_context()  # similar comparison available, baseline 5:50 (aggregate), history 8 km at 6:00
    selected = csc.build_comment_context(ctx)
    assert _ok("Compared with similar runs, your pace was 18 seconds per km faster, 5:32 against 5:50.", selected)[0]
    ok, r = _ok("This 10 km at 5:32 per km was faster than your earlier run of 8 km at 5:50 per km.", selected)
    assert not ok and "history_misattribution" in r


def test_validated_c388_comparison_is_preserved_with_history_present():
    selected = csc.build_comment_context(_llm_context())
    ok, r = _ok("Compared with similar runs you were 18 seconds per km faster over 10 km, 5:32 against 5:50.", selected)
    assert ok, r


def test_session_date_clock_time_is_not_a_history_pace():
    sessions = [dict(HISTORY[0], date="2026-01-08T07:05:00")]
    ok, r = _ok("This 10 km at 5:32 per km was faster than your earlier run, 7:05 per km, on the same loop.",
                _hist(sessions))
    assert not ok and "ungrounded_pace_or_time" in r


def test_history_date_is_not_matched_so_no_correspondence_is_invented():
    # C403: a date is accepted only when it is a prior session's own date (see C403 tests);
    # a date that matches no session is still an invented correspondence.
    ok, r = _ok("On 9 January you ran 8 km at 6:00 per km, and this 10 km at 5:32 per km was faster.", _hist())
    assert not ok and "ungrounded_date" in r


def test_insufficient_history_gives_no_habit_figure_or_progress():
    two = _hist(HISTORY[:2])
    assert "observed_training" not in two["runner_profile"]
    ok, r = _ok("You usually run 25 km over a few runs, so this 10 km at 5:32 per km was typical for you.", two)
    assert not ok and "ungrounded_number" in r
    ok, r = _ok("You improved compared with your earlier run of 8 km at 6:00 per km, over this 10 km at 5:32 per km.", two)
    assert not ok and "progress_claim" in r


def test_truncated_history_gives_no_aggregate_figure():
    truncated = _hist(truncated=True)
    assert "observed_training" not in truncated["runner_profile"] and truncated["history_as_of_session"]["truncated"]
    ok, r = _ok("You usually run about 8.3 km per session, so this 10 km at 5:32 per km was longer than usual.", truncated)
    assert not ok and "ungrounded_number" in r
    assert _ok("You usually run about 8.3 km per session, so this 10 km at 5:32 per km was longer than usual.",
               _hist())[0]


# ------------------------------------------------------------------ C402 follow-up: goal provenance

def test_goal_provenance_is_current_only_and_history_unknown():
    goal = _selected()["declared_goal"]
    assert goal["status"] == "current_declared_goal" and goal["historical_goal_status"] == "unknown"
    assert "known_at_session_date" not in goal


@pytest.mark.parametrize("text,lang", [
    ("At the time your goal was already the marathon, and this 10 km at 5:32 per km was steady.", "en"),
    ("À l'époque ton objectif était déjà le marathon, et ces 10 km à 5:32 par km étaient réguliers.", "fr"),
    ("Entonces tu objetivo ya era el maratón, y estos 10 km a 5:32 por km fueron regulares y fluidos.", "es"),
])
def test_goal_placed_in_the_past_is_rejected(text, lang):
    ok, r = _ok(text, lang=lang)
    assert not ok and "goal_history_claim" in r, r


def test_current_goal_differing_from_a_claimed_previous_goal_is_rejected():
    ok, r = _ok("Your previous goal was the 10K, and this steady 10 km at 5:32 per km was useful for it.")
    assert not ok and ("goal_mismatch" in r or "goal_history_claim" in r)


def test_absent_goal_cannot_be_stated_as_declared():
    ctx = _llm_context()
    ctx.pop("goal")
    selected = csc.build_comment_context(ctx)
    assert "declared_goal" not in selected
    ok, r = _ok("You declared the marathon as your goal, and this steady 10 km at 5:32 per km fits it.", selected)
    assert not ok and "context_as_session_fact" in r


def test_default_goal_is_never_forwarded_as_declared():
    ctx = _llm_context()
    ctx["goal"]["goal_type"] = "SOMETHING_DEFAULT"
    assert "declared_goal" not in csc.build_comment_context(ctx)
    ctx["goal"]["goal_type"] = ""
    assert "declared_goal" not in csc.build_comment_context(ctx)


def test_maintenance_goal_cannot_be_turned_into_a_race_goal():
    ctx = _llm_context()
    ctx["goal"]["goal_type"] = "MAINTENANCE"
    selected = csc.build_comment_context(ctx)
    ok, r = _ok("For your marathon goal, a steady 10 km at 5:32 per km is generally a useful run today.", selected)
    assert not ok and "goal_mismatch" in r
