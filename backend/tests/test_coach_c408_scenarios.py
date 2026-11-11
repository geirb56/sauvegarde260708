"""C408 — five sports scenarios built with the REAL Workout Analysis V2 / Intelligence V3 engines.

Fixtures are synthetic. The LLM is never called: these tests verify what reaches the model
(facts, provenance, absence of invented data) against an expectation grid defined here, before any
model call. They do NOT demonstrate the quality of a real LLM answer (see the C408 report).
"""

import json
from copy import deepcopy
from unittest.mock import AsyncMock, patch

import pytest

from coach_context_v2 import _normalize_workout_detail, build_llm_coach_context, build_session_coaching_frame
from test_coach_c393_fallback_quota import _owned_workout, _post
from test_coach_contract_unified import _FakeDB, _analyze_environment, _trial_access
from test_workout_intelligence_v3 import (
    OUTDOOR, WIV3PhysiologicalProfile, WIV3PrescriptionContext, _analyze, _phase, _snapshot, _w,
    build_workout_analysis_v2,
)
import llm_coach
import server

DAY = "2026-05-10"
HRS = [128, 132, 136, 140, 144, 148, 152, 156, 134, 150]


def _history():
    return [_w(f"h{i}", f"2026-03-{i * 2 + 1:02d}", hr=hr, pace=round(6.2 - 0.01 * (hr - 128), 2))
            for i, hr in enumerate(HRS)]


def _prescription(with_snapshot):
    snapshots = [_snapshot(DAY, served=DAY)] if with_snapshot else []
    return WIV3PrescriptionContext(local_date=DAY, snapshots=snapshots)


def _build(current, history, *, phases=None, prescription=None, goal=True):
    """Real V2 + V3 -> real LLM projection -> frame."""
    types = {item["id"]: OUTDOOR for item in [current, *history]}
    v2 = build_workout_analysis_v2(current, history, "en", phases, activity_types=types)
    intelligence = _analyze(current, history, phases=phases, profile=WIV3PhysiologicalProfile(),
                            prescription=prescription or _prescription(False))
    raw = {"workout_detail": _normalize_workout_detail(current, v2).model_dump(mode="json"),
           "reference_date": "2026-05-11"}
    if goal:
        raw["goal"] = {"objective": "10k", "goal_type": "10K"}
    context = build_llm_coach_context(raw)
    dumped = intelligence.model_dump(mode="json")
    frame = build_session_coaching_frame(context, goal_declared=goal, intelligence=dumped)
    return context, frame, dumped


def _numbers(value, out=None):
    out = set() if out is None else out
    if isinstance(value, bool):
        return out
    if isinstance(value, (int, float)):
        out.add(round(float(value), 4))
    elif isinstance(value, dict):
        for item in value.values():
            _numbers(item, out)
    elif isinstance(value, list):
        for item in value:
            _numbers(item, out)
    return out


def _texts(frame):
    return json.dumps(frame, ensure_ascii=False).lower()


# ---- A: easy run under control -------------------------------------------------------------

def test_scenario_a_easy_run_is_relatively_low_without_invented_problem():
    context, frame, _ = _build(_w("cur", DAY, hr=133, pace=6.3), _history())
    v3 = frame["v3_assessment"]
    assert v3["classification"]["probable_type"] == "easy_run_probable"
    assert v3["classification"]["relative_effort"]["relative_position"] == "low"
    assert v3["classification"]["relative_effort"]["reference_count"] == 10
    assert frame["session_intent"]["recorded_historical_prescription"] == "none_recorded_for_session_date"
    assert frame["session_intent"]["intent_status"] == "probable_type_from_observed_classification_not_a_prescription"
    assert "deviation" not in _texts(frame)
    assert not any(word in _texts(frame) for word in ("rest ", "repos", "recover more"))
    assert v3["intensity"]["position_vs_declared_thresholds"] == "unknown"  # no invented zone
    assert context["workout_detail"]["avg_hr"] == 133.0


# ---- B: probably too intense for the prescribed easy run ------------------------------------

def test_scenario_b_high_relative_effort_against_a_recorded_easy_prescription():
    context, frame, dumped = _build(_w("cur", DAY, hr=158, pace=5.3), _history(),
                                    prescription=_prescription(True))
    recorded = frame["session_intent"]["recorded_historical_prescription"]
    assert recorded["prescribed_workout_type"] == "easy" and recorded["planned_date"] == DAY
    assert frame["session_intent"]["intent_status"] == "recorded_historical_prescription"
    relative = frame["v3_assessment"]["classification"]["relative_effort"]
    assert relative["relative_position"] == "high" and relative["hr_q3_bpm"] < relative["current_hr_bpm"]
    evidence = " ".join(item["text"] for item in frame["v3_assessment"]["coach_assessment"]["evidence"])
    assert "158" in evidence and "upper part" in evidence
    # The engine itself judges the type confidence too low for a "deviation": the frame must not upgrade it.
    assert recorded["assessment_status"] == dumped["prescription_assessment"]["status"] == "indeterminate"
    assert "observed_type_confidence_too_low" in recorded["reasons"]
    assert any("not physiological" in limitation["text"].lower() or "relative to your own history" in limitation["text"]
               for limitation in frame["v3_assessment"]["coach_assessment"]["limitations"])


# ---- C: irregular intervals -------------------------------------------------------------------

def _interval_phases(durations):
    rows = [("warmup", 600, None, 130)]
    for index, duration in enumerate(durations):
        rows += [("effort", duration, 800, 172 + index), ("recovery", 120, None, 140)]
    rows.append(("cooldown", 600, None, 130))
    return [_phase(i, *row) for i, row in enumerate(rows)]


def test_scenario_c_irregular_efforts_reach_the_llm_via_v2_regularity_not_duplicated():
    irregular = _interval_phases([175, 200, 168, 215, 172])
    context, frame, _ = _build(_w("cur", DAY, hr=160, pace=5.2, duration=45, continuous=False), _history(),
                               phases=irregular)
    assert frame["v3_assessment"]["classification"]["probable_type"] == "intervals"
    assert frame["data_available"]["structured_phases"] is True
    regularity = context["workout_detail"]["analysis"]["phase_analysis"]["effort_regularity"]
    assert regularity["available"] and regularity["effort_count"] == 5
    assert regularity["pace_dispersion_sec_per_km"] is not None
    assert "effort_regularity" not in json.dumps(frame)  # single source: workout_detail.analysis

    regular = _build(_w("cur", DAY, hr=160, pace=5.2, duration=45, continuous=False), _history(),
                     phases=_interval_phases([180] * 5))[0]
    regular_dispersion = regular["workout_detail"]["analysis"]["phase_analysis"]["effort_regularity"][
        "pace_dispersion_sec_per_km"]
    assert regularity["pace_dispersion_sec_per_km"] > regular_dispersion  # data distinguish the two sessions


# ---- D: incomplete data ----------------------------------------------------------------------

def test_scenario_d_incomplete_session_limits_conclusions_and_invents_nothing():
    current = _w("cur", DAY, hr=None, pace=None, duration=40, distance=6.0, max_hr=None)
    context, frame, dumped = _build(current, [], goal=False)
    assert {"avg_hr", "pace", "structured_phases", "km_splits"} <= set(frame["missing_data"])
    v3 = frame["v3_assessment"]
    assert v3["classification"]["probable_type"] == "unknown"
    assert v3["classification"]["relative_effort"] == {"status": "not_applicable"}
    assert "hr_missing" in v3["intensity"]["limitations"]
    assert frame["session_intent"]["intent_status"] == "unknown"
    assert frame["athlete_goal_declared"] is False
    assert context["workout_detail"].get("avg_hr") is None
    assert "pace_difference_sec_per_km_at_comparable_hr" not in v3["historical_comparison"]
    assert _numbers(v3) <= _numbers(dumped)


def test_frame_numbers_always_come_from_the_v3_result_and_inputs_are_not_mutated():
    for current, extra in (
        (_w("cur", DAY, hr=133, pace=6.3), {}),
        (_w("cur", DAY, hr=158, pace=5.3), {"prescription": _prescription(True)}),
    ):
        context, _, dumped = _build(current, _history(), **extra)
        before_context, before_dumped = deepcopy(context), deepcopy(dumped)
        frame = build_session_coaching_frame(context, intelligence=dumped)
        assert _numbers(frame["v3_assessment"]) <= _numbers(dumped)
        assert context == before_context and dumped == before_dumped


def test_observed_max_hr_is_never_presented_as_physiological():
    _, frame, _ = _build(_w("cur", DAY, hr=140, pace=6.0, max_hr=181), _history())
    intensity = frame["v3_assessment"]["intensity"]
    assert intensity["session_max_hr_bpm"] == 181.0
    assert "not the athlete's physiological max hr" in intensity["session_max_hr_meaning"].lower()
    assert intensity["declared_fcmax_available"] is False


def test_trend_and_engine_advice_are_not_transmitted():
    _, frame, dumped = _build(_w("cur", DAY, hr=158, pace=5.3), _history(), prescription=_prescription(True))
    assert "performance_trend" not in frame["v3_assessment"]
    assert "advice" not in frame["v3_assessment"]["coach_assessment"]


def test_context_reaches_the_prompt_json_with_the_selected_workout():
    context, frame, _ = _build(_w("cur", DAY, hr=133, pace=6.3), _history())
    context["session_coaching_frame"] = frame
    call = AsyncMock(return_value=("ok", True, {}))
    with patch.object(llm_coach, "_call_gpt", call):
        import asyncio
        asyncio.run(llm_coach.enrich_chat_response("Analyse cette séance.", context, [], "u"))
    prompt = call.await_args.args[1]
    payload = json.loads(prompt.split("DONNÉES RUNINDEX (JSON):\n", 1)[1].split("\n\n", 1)[0])
    assert payload["session_coaching_frame"]["workout_id"] == "cur"
    assert payload["session_coaching_frame"]["v3_assessment"]["classification"]["probable_type"] == "easy_run_probable"
    assert "MODE:" not in prompt


# ---- E: analysis then two follow-ups on the same workout ---------------------------------------

pytestmark_async = pytest.mark.asyncio


class _SessionPayload:
    def __init__(self, goal):
        self.goal = goal

    def model_dump(self, mode="json"):
        data = {"workout_detail": {"id": "w1", "date": DAY, "type": "run", "avg_hr": 133.0}}
        if self.goal:
            data["goal"] = {"objective": "10k", "goal_type": "10K"}
        return data


async def _three_turns(goal):
    fake_db = _FakeDB()
    questions = ["Analyse cette séance.", "Et ma fréquence cardiaque ?", "Est-ce cohérent avec mon objectif 10 km ?"]
    contexts, histories = [], []
    with (
        _analyze_environment(fake_db, _trial_access),
        _owned_workout(fake_db),
        patch("server.build_coach_context_v2", AsyncMock(return_value=_SessionPayload(goal))),
    ):
        llm = server.llm_coach.enrich_chat_response
        for question in questions:
            response = await _post({"message": question, "workout_id": "w1", "language": "fr"})
            assert response.status_code == 200
            contexts.append(llm.await_args.kwargs["context"])
            histories.append(llm.await_args.kwargs["conversation_history"])
        calls = llm.await_count
    return fake_db, contexts, histories, calls


@pytest.mark.asyncio
async def test_scenario_e_same_workout_on_three_turns_with_one_llm_call_each():
    fake_db, contexts, histories, calls = await _three_turns(goal=True)
    assert calls == 3
    assert all("workout_id" not in c["session_coaching_frame"] for c in contexts)  # C408-C
    assert contexts[0]["session_coaching_frame"] == contexts[2]["session_coaching_frame"]  # no factual drift
    assert [len(h) for h in histories] == [0, 2, 4]
    assert histories[2][0]["content"] == "Analyse cette séance."
    assert {d["workout_id"] for d in fake_db.conversations._docs} == {"w1"}
    assert all(c["session_coaching_frame"]["athlete_goal_declared"] is True for c in contexts)


@pytest.mark.asyncio
async def test_scenario_e_goal_is_referenced_only_when_known():
    _, contexts, _, _ = await _three_turns(goal=False)
    assert all(c["session_coaching_frame"]["athlete_goal_declared"] is False for c in contexts)
    assert all("goal" not in c for c in contexts)
