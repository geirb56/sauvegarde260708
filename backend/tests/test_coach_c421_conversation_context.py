"""C421 — conversational Coach context rebuilt for the chat (prompt untouched).

SYNTHETIC fixtures built with the real Workout Analysis V2 / Intelligence V3 engines and the C420
lap detector; no LLM, Garmin or Mongo call. They check what reaches the chat LLM, not answer quality.
"""

import copy
import json

import pytest

import coach_session_comment as csc
import server
from coach_context_v2 import build_observed_lap_pattern_context
from garmin_laps_analysis import detect_lap_pattern
from test_coach_c408_scenarios import DAY, _build, _history, _interval_phases, _w
from test_coach_c420_lap_pattern import _context
from test_garmin_lap_pattern_c420 import build

# 05/11 as C420B reads it: 4 warm-up laps, 4 x (60 s fast / 60 s slow), 5 cool-down laps. Never 7.
SHAPE_0511_FOUR = (
    [(360, 360)] * 4 + [(60, 230), (60, 390)] * 4
    + [(360, 360), (288, 360), (180, 360), (108, 360), (60, 400)]
)


def _tokens(value) -> int:
    return len(json.dumps(value, ensure_ascii=False, separators=(",", ":"))) // 4


def _chat_input(*, phases=None, history=None, goal=True, language="en", lap_pattern=None, prescription=None,
                current=None):
    current = current or _w("cur", DAY, hr=160, pace=5.2, duration=45, continuous=False)
    context, frame, _ = _build(current, _history() if history is None else history, phases=phases,
                                goal=goal, prescription=prescription)
    context["language"] = language
    context["workout_detail"]["id"] = "cur"
    context["session_coaching_frame"] = frame
    context["coach_workout_analysis_allowed"] = True
    if lap_pattern is not None:
        context["observed_lap_pattern"] = lap_pattern
    return context


def _pattern(shape=SHAPE_0511_FOUR):
    workout, activity = build(shape, hr=lambda i: 130 + i * 2)
    return build_observed_lap_pattern_context({"observed_lap_pattern": detect_lap_pattern(workout, activity)})


def _codes(items):
    return [item["code"] for item in items]


# ------------------------------------------------------------------ structure: recorded vs inferred

def test_recorded_garmin_phases_outrank_the_inferred_pattern():
    ctx = _chat_input(phases=_interval_phases([175, 200, 168, 215]), lap_pattern=_pattern())
    out = csc.build_conversation_context(ctx)
    assert out["recorded_structure"]["status"] == "recorded_by_garmin"
    assert [p["type"] for p in out["recorded_structure"]["phases"]].count("effort") == 4
    assert out["inferred_structure"] == {"status": "not_used_recorded_structure_available"}
    assert "fast_slow_alternation" not in json.dumps(out)


def test_inferred_pattern_alone_is_labelled_inferred_never_recorded():
    out = csc.build_conversation_context(_chat_input(lap_pattern=_pattern()))
    assert out["recorded_structure"] == {"status": "none_recorded"}
    inferred = out["inferred_structure"]
    assert inferred["status"] == "pattern_observed" and inferred["source"] == "inferred_from_garmin_laps"
    assert "never a recorded phase" in inferred["rule"]


def test_0511_pattern_carries_its_four_detected_repetitions_and_never_seven():
    out = csc.build_conversation_context(_chat_input(lap_pattern=_pattern()))
    inferred = out["inferred_structure"]
    assert inferred["repetition_count"] == 4
    assert len(inferred["fast"]["repetitions"]) == len(inferred["slow"]["repetitions"]) == 4
    assert [r["n"] for r in inferred["fast"]["repetitions"]] == [1, 2, 3, 4]
    assert inferred["fast"]["typical_pace"] == "3:50/km" and inferred["fast"]["avg_hr_change_first_to_last_bpm"] == 12
    assert inferred["warmup_probable"]["lap_count"] == 4 and inferred["cooldown_probable"]["lap_count"] == 5
    dumped = json.dumps(out)
    assert '"repetition_count": 7' not in dumped and '"n":7' not in dumped.replace(" ", "")


def test_whole_session_averages_are_dropped_when_a_structure_describes_the_session():
    plain = csc.build_conversation_context(_chat_input(current=_w("cur", DAY, hr=150, pace=5.5, continuous=True)))
    structured = csc.build_conversation_context(_chat_input(lap_pattern=_pattern()))
    assert "avg_pace" in plain["session"] and "avg_hr_bpm" in plain["session"]
    assert "avg_pace" not in structured["session"] and "avg_hr_bpm" not in structured["session"]
    assert structured["session"]["distance_km"] and structured["session"]["duration_minutes"]


def test_unobserved_pattern_is_relayed_as_status_only():
    unknown = build_observed_lap_pattern_context({"observed_lap_pattern": {
        "schema": "garmin_lap_pattern_v1", "status": "unknown", "reason": "too_few_laps", "lap_count": 2,
        "anomalies": []}})
    out = csc.build_conversation_context(_chat_input(lap_pattern=unknown))
    assert out["inferred_structure"]["status"] == "no_pattern_established"
    assert "repetition_count" not in out["inferred_structure"]


# ------------------------------------------------------------------ limitations

def test_every_uncertainty_is_stated_once_and_cuts_the_size():
    ctx = _chat_input(lap_pattern=_pattern())
    ctx["validated_workout_observations"] = {
        "headline": "H", "analysis": "A", "interpretation": "I",
        "limitations": ["Prescription conformity remains indeterminate.", "Session averages cannot confirm a zone."]}
    out = csc.build_conversation_context(ctx)
    topics = _codes(out["material_limitations"])
    assert len(topics) == len(set(topics))
    texts = [item["text"] for item in out["material_limitations"]]
    assert len(texts) == len(set(texts))
    dumped = json.dumps(out)
    for repeated in ("average_hr_is_not_time_in_zone", "personal_thresholds_not_persisted", "limit.no_thresholds",
                     "Prescription conformity remains indeterminate", "Individualized zone evidence"):
        assert repeated not in dumped
    assert "not_demonstrated" not in dumped and "evidence_contract" not in dumped
    assert _tokens(out) < _tokens(csc.build_session_chat_context(ctx)) / 2


def test_limits_that_cannot_change_a_conclusion_are_dropped_and_the_others_kept():
    out = csc.build_conversation_context(_chat_input(history=[], current=_w("cur", DAY, hr=None, pace=None,
                                                                            duration=40, distance=6.0, max_hr=None)))
    topics = _codes(out["material_limitations"])
    assert "no_validated_comparison" in topics and "hr_unusable" in topics
    structured = csc.build_conversation_context(_chat_input(lap_pattern=_pattern()))
    assert "structure_unknown" not in _codes(structured["material_limitations"])
    assert "hr_unusable" not in _codes(structured["material_limitations"])  # heart rates are listed per repetition


def test_a_comparison_makes_the_no_history_limit_disappear():
    out = csc.build_conversation_context(_chat_input())
    assert out["validated_comparisons"]
    assert "no_validated_comparison" not in _codes(out["material_limitations"])


# ------------------------------------------------------------------ permissions

def test_scientific_permissions_are_kept_verbatim_and_never_widened():
    ctx = _chat_input(lap_pattern=_pattern())
    original = copy.deepcopy(ctx["selected_workout_permissions"])
    out = csc.build_conversation_context(ctx)
    permissions = out["scientific_permissions"]["selected_workout_permissions"]
    assert permissions == original
    assert permissions["progress_regression_allowed"] is False
    assert permissions["intensity_interpretation_allowed"] is False
    assert out["scientific_permissions"]["physiological_references"] == "not_provided"
    assert "recovery_state" in out["scientific_permissions"]["not_measured"]
    assert out["allowed_conclusions"] == [] or all(
        "progress" not in json.dumps(item).lower() for item in out["allowed_conclusions"])


def test_an_explicit_permission_flows_through_unchanged():
    ctx = _chat_input()
    ctx["selected_workout_permissions"]["intensity_interpretation_allowed"] = True
    out = csc.build_conversation_context(ctx)
    assert out["scientific_permissions"]["selected_workout_permissions"]["intensity_interpretation_allowed"] is True


# ------------------------------------------------------------------ prescription and comparisons

def _frame_with_prescription(ctx, **recorded):
    ctx["session_coaching_frame"]["session_intent"]["recorded_historical_prescription"] = {
        "assessment_status": "indeterminate", "planned_date": DAY, "recorded_at": DAY,
        "prescribed_workout_type": "easy", "prescribed_distance_km": 8.0, **recorded}
    return ctx


@pytest.mark.parametrize("timing,usable", [("recorded_before_session", True), ("recorded_after_session", False),
                                           ("recording_time_unknown", False)])
def test_historical_prescription_is_used_only_when_recorded_before_the_session(timing, usable):
    ctx = _frame_with_prescription(_chat_input(), recording_timing=timing)
    prescription = csc.build_conversation_context(ctx)["athlete_context"]["recorded_prescription"]
    if usable:
        assert prescription["status"] == "recorded_before_session"
        assert prescription["prescribed_workout_type"] == "easy" and prescription["conformity"] == "indeterminate"
    else:
        assert prescription["status"] == "none_usable" and "prescribed_workout_type" not in prescription
        assert "prescribed_distance_km" not in json.dumps(prescription)


def test_current_plan_is_never_offered_as_the_session_prescription():
    ctx = _chat_input()
    ctx["training_state"] = {"phase": "build"}
    ctx["today"] = {"workout_type": "tempo"}
    ctx["current_training_context"] = {"week": 3}
    dumped = json.dumps(csc.build_conversation_context(ctx))
    for current in ("training_state", "tempo", "current_training_context"):
        assert current not in dumped
    assert csc.build_conversation_context(ctx)["athlete_context"]["recorded_prescription"]["status"] == "none_usable"


def test_validated_comparisons_keep_their_population_and_provenance():
    ctx = _chat_input()
    frame = ctx["session_coaching_frame"]
    frame["v3_assessment"]["classification"]["relative_effort"] = {
        "status": "used", "relative_position": "high", "current_hr_bpm": 160, "reference_count": 9,
        "hr_q1_bpm": 140, "hr_median_bpm": 145, "hr_q3_bpm": 150, "period_start": "2026-03-01",
        "period_end": "2026-05-01",
        "provenance": {"reference_population": "earlier sessions admitted by V3", "activity_count": 9,
                       "period_start": "2026-03-01", "period_end": "2026-05-01", "confidence": "moderate",
                       "selection_criteria": {"window_days": 180, "distance_is_a_selection_criterion": False},
                       "known_limits": ["terrain_weather_not_controlled"]}}
    frame["evidence_contract"]["validated_comparisons"].append(
        {"metric": "average_hr_relative_position", "source_path": "x", "provenance": "relative_effort.provenance"})
    out = csc.build_conversation_context(ctx)
    relative = next(c for c in out["validated_comparisons"] if c["metric"] == "average_hr_relative_position")
    assert relative["provenance"]["activity_count"] == 9 and relative["provenance"]["window_days"] == 180
    assert relative["provenance"]["period_start"] == "2026-03-01" and relative["session_avg_hr_bpm"] == 160
    similar = next(c for c in out["validated_comparisons"] if c["metric"].startswith("pace_and_hr_vs_similar"))
    assert similar["activity_count"] and "reference_population" in similar
    assert "comparison_conditions" in _codes(out["material_limitations"])


def test_no_progress_is_derived_from_a_single_session():
    out = csc.build_conversation_context(_chat_input())
    assert out["scientific_permissions"]["selected_workout_permissions"]["progress_regression_allowed"] is False
    assert "no trend established" in out["athlete_context"]["history_before_session"]["note"]
    declared = out["athlete_context"]["declared_goal"]
    assert declared["status"] == "current_declared_goal" and declared["valid_at_session_date"] == "unknown"


# ------------------------------------------------------------------ side effects, languages, users

def test_inputs_and_other_contexts_are_untouched():
    ctx = _chat_input(lap_pattern=_pattern())
    before = copy.deepcopy(ctx)
    comment_before = csc.build_comment_context(ctx)
    legacy_before = csc.build_session_chat_context(ctx)
    csc.build_conversation_context(ctx)
    assert ctx == before
    assert csc.build_comment_context(ctx) == comment_before  # C400 unchanged
    assert csc.build_session_chat_context(ctx) == legacy_before
    assert "session_coaching_frame" in legacy_before and "evidence_contract" in json.dumps(legacy_before)


def test_comparison_turn_context_is_not_affected():
    turn = {"contract": {"kind": "two_sessions", "allowed_interpretations": []}, "focus": None, "text": "x"}
    context = csc.build_comparison_chat_context(turn, "fr")
    assert "recorded_structure" not in context and context["comparison_contract"]["kind"] == "two_sessions"


@pytest.mark.parametrize("language", ["fr", "en", "es"])
def test_language_is_relayed_and_localized_texts_are_kept(language):
    ctx = _chat_input(language=language, phases=_interval_phases([175, 200, 168, 215]))
    out = csc.build_conversation_context(ctx)
    assert out["language"] == language
    assert out["key_observations"] and all(item["text"] for item in out["key_observations"])
    source = [i["text"] for i in ctx["workout_detail"]["analysis"]["session_synthesis"]["supporting"]
              + [ctx["workout_detail"]["analysis"]["session_synthesis"]["primary"]]]
    assert any(item["text"] in source for item in out["key_observations"])


def test_no_identifier_or_other_user_data_reaches_the_context():
    ctx = _chat_input(lap_pattern=_pattern())
    ctx["workout_detail"].update(garmin_activity_id="9988776655", user_id="user-b")
    ctx["recent_workouts"] = [{"date": "2000-01-01T07:00:00", "type": "run", "distance_km": 5.0,
                               "user_id": "user-b", "garmin_activity_id": "777"}]
    dumped = json.dumps(csc.build_conversation_context(ctx), default=str)
    for leaked in ("9988776655", "user-b", "777", '"id":"cur"'):
        assert leaked not in dumped.replace(" ", "")


def test_without_a_selected_workout_only_access_and_language_remain():
    out = csc.build_conversation_context({"language": "es", "coach_workout_analysis_allowed": True})
    assert out == {"language": "es", "coach_workout_analysis_allowed": True}


# ------------------------------------------------------------------ server wiring (Premium gate)

@pytest.mark.asyncio
async def test_selected_workout_chat_uses_the_conversational_context_for_the_0511_session():
    ctx, _ = await _context(
        SHAPE_0511_FOUR, lambda **kw: server._build_coach_llm_context(workout_analysis_allowed=True, **kw))
    assert ctx["inferred_structure"]["repetition_count"] == 4
    assert {"session", "recorded_structure", "inferred_structure", "key_observations", "validated_comparisons",
            "athlete_context", "allowed_conclusions", "material_limitations",
            "scientific_permissions"} <= set(ctx)
    assert ctx["coach_workout_analysis_allowed"] is True
    json.dumps(ctx)


@pytest.mark.asyncio
async def test_chat_without_workout_analysis_access_never_gets_a_session_context(monkeypatch):
    general = {"coach_workout_analysis_allowed": False, "training_state": {"phase": "build"}}

    async def assembled(**kwargs):
        return general, None

    def forbidden(_):
        raise AssertionError("conversation context built without workout analysis access")

    monkeypatch.setattr(server, "_assemble_coach_llm_context", assembled)
    monkeypatch.setattr(csc, "build_conversation_context", forbidden)
    ctx, _ = await server._build_coach_llm_context(
        user={"id": "u"}, language="en", workout=None, workout_analysis=None,
        workout_analysis_allowed=False, workout_id="w1", now_utc=None)
    assert ctx is general
