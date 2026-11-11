"""C420 — the observed lap pattern reaches the Coach LLM context (chat and automatic comment).

SYNTHETIC laps shaped like the reported 05/11 session; no LLM, Garmin or Mongo call.
"""

import json
from datetime import date, datetime, timezone
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

import coach_session_comment as csc
import server
from coach_context_v2 import build_observed_lap_pattern_context
from test_coach_context_v2 import _Collection, _FakeDB, _USER_ID, _performance, _readiness_decision, \
    _training_load, _training_paces
from test_garmin_lap_pattern_c420 import SHAPE_0511, build
from training_v2.plan_goal import GoalType
from workout_intelligence_v3_service import load_scoped_workout_coach_evidence

WORKOUT_ID = "garmin-1"


async def _context(shape, builder):
    workout, activity = build(shape, hr=lambda i: 130 + i * 2)
    workout.update(user_id=_USER_ID, date="2026-11-05T09:00:00Z", name="Free title")
    activity.update(user_id=_USER_ID, source="garmin")
    db = _FakeDB()
    db.workouts = _Collection([workout])
    db.garmin_activities = _Collection([activity])
    goal = SimpleNamespace(goal_type="MARATHON", mapped_goal=GoalType.marathon, cycle_start=date(2026, 9, 1),
                           race_date=date(2027, 2, 1), target_time_sec=12600, target_distance_km=None,
                           user_goal_doc=None)
    acts = [SimpleNamespace(activity_type="running", start_time=datetime(2026, 11, 5, 9, tzinfo=timezone.utc),
                            distance_m=9640.0)]
    patches = [
        patch("server._resolve_canonical_reference_date", return_value=date(2026, 11, 6)),
        patch("server._resolve_goal_v2", AsyncMock(return_value=goal)),
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
        selected, analysis = await server.load_scoped_workout_analysis_v2(
            db=db, user_id=_USER_ID, workout_id=WORKOUT_ID, language="en")
        return await builder(
            user={"id": _USER_ID}, language="en", workout=selected, workout_analysis=analysis,
            workout_id=WORKOUT_ID, now_utc=datetime(2026, 11, 6, tzinfo=timezone.utc))
    finally:
        for p in patches:
            p.stop()
        server.db = previous_db


@pytest.mark.asyncio
async def test_comment_context_contains_the_observed_0511_pattern():
    ctx, _ = await _context(SHAPE_0511, server._build_coach_comment_context)
    pattern = ctx["observed_lap_pattern"]
    assert pattern["status"] == "pattern_observed"
    assert pattern["pattern"]["repetition_count"] == 7
    assert pattern["pattern"]["fast_segments"]["typical_duration_s"] == 60
    assert pattern["probable_warmup"] and pattern["probable_cooldown"]
    assert "not a recorded phase" in pattern["probable_warmup"]["basis"]
    assert "programmed recoveries" in pattern["rule"]
    # lap pattern sits before the whole-session aggregates in the payload
    assert list(ctx).index("observed_lap_pattern") < list(ctx).index("history_as_of_session")
    json.dumps(ctx)  # prompt-serialisable


@pytest.mark.asyncio
async def test_chat_context_also_contains_the_pattern():
    ctx, _ = await _context(
        SHAPE_0511, lambda **kw: server._build_coach_llm_context(workout_analysis_allowed=True, **kw))
    assert ctx["observed_lap_pattern"]["pattern"]["repetition_count"] == 7


@pytest.mark.asyncio
async def test_continuous_session_context_has_no_invented_pattern():
    ctx, _ = await _context([(1800, 340), (1500, 335)], server._build_coach_comment_context)
    lap = ctx.get("observed_lap_pattern")
    assert lap is None or (lap["status"] != "pattern_observed" and "pattern" not in lap)
    assert "observed_lap_pattern" not in json.dumps(ctx.get("session_coaching_frame", {}))


@pytest.mark.asyncio
async def test_v3_carries_the_pattern_as_inference_without_changing_classification():
    workout, activity = build(SHAPE_0511)
    workout.update(user_id=_USER_ID, date="2026-11-05T09:00:00Z")
    activity.update(user_id=_USER_ID)
    db = _FakeDB()
    db.workouts, db.garmin_activities = _Collection([workout]), _Collection([activity])
    _, intelligence = await load_scoped_workout_coach_evidence(
        db=db, user_id=_USER_ID, workout_id=WORKOUT_ID, language="en")
    assert intelligence.observed_lap_pattern["pattern"]["repetition_count"] == 7
    assert intelligence.session_classification.type == "unknown"  # no certain classification is derived


def test_pattern_context_never_relayed_when_not_observed_and_never_mutates_input():
    unknown = {"observed_lap_pattern": {"schema": "garmin_lap_pattern_v1", "status": "unknown",
                                        "reason": "too_few_laps", "lap_count": 2, "anomalies": []}}
    out = build_observed_lap_pattern_context(unknown)
    assert out["status"] == "unknown" and "pattern" not in out and "do not invent" in out["rule"]
    assert "rule" not in unknown["observed_lap_pattern"]
    assert build_observed_lap_pattern_context({}) is None
    assert build_observed_lap_pattern_context({"observed_lap_pattern": {"schema": "other"}}) is None


@pytest.mark.asyncio
async def test_pattern_figures_ground_a_comment_citing_them():
    ctx, _ = await _context(SHAPE_0511, server._build_coach_comment_context)
    ok, reasons = csc.validate_session_comment(
        "Your laps show 7 fast efforts of 60 seconds at about 3:50 per km, alternating with slower laps.",
        ctx, "en")
    assert ok, reasons
