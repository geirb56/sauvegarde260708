"""PR137 — Daily Runtime Migration V2 — Test Suite.

Tests cover:
    A. REST planned → KEEP
    B. Readiness UNAVAILABLE → no automatic penalty
    C. Good readiness → KEEP, no increase
    D. Readiness requiring downgrade → conforms to #133
    E. SHORTEN factor = 0.70 exact
    F. Adapted duration never exceeds original
    G. Adapted distance never exceeds original
    H. allow_intensity=False → no intensity added
    I. No MOVE action
    J. No INCREASE action
    K–N. Helper conversion functions
    O–W. Architecture guardrails and monotonicity sweep

Run from the backend directory:
    python -m pytest tests/test_daily_runtime_pr137.py -q
"""

from __future__ import annotations

import sys
from datetime import date
from pathlib import Path
from typing import Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training_v2.daily_adaptation import (
    SHORTEN_FACTOR,
    DailyAdaptationAction,
    build_daily_adaptation,
)
from training_v2.readiness import ReadinessConfidence, ReadinessResult
from training_v2.readiness_decision import ReadinessBand, build_readiness_decision
from training_v2.readiness_sufficiency import SufficiencyLevel
from training_v2.training_load import TrainingLoadSnapshot
from training_v2.workout_generator import WorkoutPrescription
from training_v2.daily_runtime_helpers import (
    WORKOUT_TYPE_TO_INTENSITY_CLASS,
    BAND_TO_RECOMMENDATION,
    parse_duration_minutes,
    runtime_session_to_prescription,
    prescription_to_runtime_session,
)

_SERVER_PATH = Path(__file__).resolve().parents[1] / "server.py"
REF = date(2026, 8, 17)


# ─────────────────────────────────────────────────────────────────────────────
# Fixtures / factories
# ─────────────────────────────────────────────────────────────────────────────

def _wp(workout_type, *, distance_km=None, duration_minutes=None, day="monday"):
    intensity = WORKOUT_TYPE_TO_INTENSITY_CLASS.get(workout_type, "low")
    return WorkoutPrescription(
        day=day,
        workout_type=workout_type,
        intensity_class=intensity,
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        reason_codes=("PLAN_V2",),
    )


def _readiness(score, *, sufficiency_level=SufficiencyLevel.SUFFICIENT,
               confidence=ReadinessConfidence.NORMAL):
    if score is None and sufficiency_level == SufficiencyLevel.INSUFFICIENT:
        return ReadinessResult(
            score=None, confidence=ReadinessConfidence.NONE,
            sufficiency_level=SufficiencyLevel.INSUFFICIENT, reasons=()
        )
    return ReadinessResult(
        score=score, confidence=confidence,
        sufficiency_level=sufficiency_level, reasons=()
    )


def _load(status, *, acwr=1.0):
    return TrainingLoadSnapshot(
        acute_load=300.0, chronic_load=300.0, acwr=acwr,
        status=status, atl=300.0, ctl=300.0, tsb=0.0,
    )


# ─────────────────────────────────────────────────────────────────────────────
# A. REST planned → KEEP
# ─────────────────────────────────────────────────────────────────────────────

def test_A_rest_planned_keeps():
    workout = _wp("rest")
    readiness = _readiness(20.0)
    decision = build_readiness_decision(readiness)
    result = build_daily_adaptation(
        workout=workout, readiness_decision=decision,
        training_load=None, recent_response=None,
    )
    assert result.action == DailyAdaptationAction.KEEP
    assert result.adapted_workout.workout_type == "rest"
    assert "PLANNED_REST_DAY" in result.reason_codes


# ─────────────────────────────────────────────────────────────────────────────
# B. Readiness UNAVAILABLE → no automatic REST
# ─────────────────────────────────────────────────────────────────────────────

def test_B_readiness_unavailable_no_auto_rest():
    workout = _wp("easy", duration_minutes=40)
    readiness = _readiness(None, sufficiency_level=SufficiencyLevel.INSUFFICIENT)
    decision = build_readiness_decision(readiness)
    assert decision.band == ReadinessBand.UNAVAILABLE
    result = build_daily_adaptation(
        workout=workout, readiness_decision=decision,
        training_load=None, recent_response=None,
    )
    assert result.action != DailyAdaptationAction.REST
    assert result.adapted_workout.workout_type != "rest"


def test_B_none_readiness_no_auto_rest():
    workout = _wp("easy", duration_minutes=40)
    result = build_daily_adaptation(
        workout=workout, readiness_decision=None,
        training_load=None, recent_response=None,
    )
    assert result.action != DailyAdaptationAction.REST
    assert result.adapted_workout.workout_type != "rest"


# ─────────────────────────────────────────────────────────────────────────────
# C. Good readiness → KEEP, no increase
# ─────────────────────────────────────────────────────────────────────────────

def test_C_good_readiness_keep():
    workout = _wp("easy", distance_km=10.0, duration_minutes=50)
    decision = build_readiness_decision(_readiness(80.0))
    assert decision.band == ReadinessBand.FAVORABLE
    result = build_daily_adaptation(
        workout=workout, readiness_decision=decision,
        training_load=None, recent_response=None,
    )
    assert result.action == DailyAdaptationAction.KEEP
    assert result.adapted_workout.workout_type == "easy"
    assert (result.adapted_workout.distance_km or 0.0) <= (workout.distance_km or 0.0)
    assert (result.adapted_workout.duration_minutes or 0) <= (workout.duration_minutes or 0)


def test_C_good_readiness_no_quality_upgrade():
    workout = _wp("easy", duration_minutes=45)
    decision = build_readiness_decision(_readiness(95.0))
    result = build_daily_adaptation(
        workout=workout, readiness_decision=decision,
        training_load=None, recent_response=None,
    )
    assert result.adapted_workout.workout_type not in ("quality", "steady")


# ─────────────────────────────────────────────────────────────────────────────
# D. Readiness requiring downgrade → conforms to #133
# ─────────────────────────────────────────────────────────────────────────────

def test_D_very_low_readiness_rest():
    workout = _wp("quality", duration_minutes=60)
    decision = build_readiness_decision(_readiness(30.0))
    assert decision.band == ReadinessBand.VERY_LOW
    result = build_daily_adaptation(
        workout=workout, readiness_decision=decision,
        training_load=None, recent_response=None,
    )
    assert result.action == DailyAdaptationAction.REST


def test_D_low_readiness_quality_downgrade():
    workout = _wp("quality", duration_minutes=55)
    decision = build_readiness_decision(_readiness(45.0))
    assert decision.band == ReadinessBand.LOW
    result = build_daily_adaptation(
        workout=workout, readiness_decision=decision,
        training_load=None, recent_response=None,
    )
    assert result.action == DailyAdaptationAction.EASY_DOWNGRADE
    assert result.adapted_workout.intensity_class == "low"


# ─────────────────────────────────────────────────────────────────────────────
# E. SHORTEN factor = 0.70 exact
# ─────────────────────────────────────────────────────────────────────────────

def test_E_shorten_factor_exact():
    assert SHORTEN_FACTOR == pytest.approx(0.70)
    workout = _wp("easy", distance_km=10.0, duration_minutes=60)
    decision = build_readiness_decision(_readiness(45.0))
    result = build_daily_adaptation(
        workout=workout, readiness_decision=decision,
        training_load=None, recent_response=None,
    )
    assert result.action == DailyAdaptationAction.SHORTEN
    assert result.adapted_workout.distance_km == pytest.approx(round(10.0 * SHORTEN_FACTOR, 1))
    assert result.adapted_workout.duration_minutes == max(1, int(round(60 * SHORTEN_FACTOR)))


# ─────────────────────────────────────────────────────────────────────────────
# F. Adapted duration never exceeds original
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("workout_type,score", [
    ("easy", 30.0), ("quality", 45.0), ("long_easy", 45.0), ("easy", 45.0),
])
def test_F_adapted_duration_never_exceeds_original(workout_type, score):
    workout = _wp(workout_type, duration_minutes=60)
    decision = build_readiness_decision(_readiness(score))
    result = build_daily_adaptation(
        workout=workout, readiness_decision=decision,
        training_load=None, recent_response=None,
    )
    assert (result.adapted_workout.duration_minutes or 0) <= (workout.duration_minutes or 0)


# ─────────────────────────────────────────────────────────────────────────────
# G. Adapted distance never exceeds original
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("workout_type,score", [
    ("easy", 30.0), ("quality", 45.0), ("long_easy", 45.0),
])
def test_G_adapted_distance_never_exceeds_original(workout_type, score):
    workout = _wp(workout_type, distance_km=12.0, duration_minutes=60)
    decision = build_readiness_decision(_readiness(score))
    result = build_daily_adaptation(
        workout=workout, readiness_decision=decision,
        training_load=None, recent_response=None,
    )
    assert (result.adapted_workout.distance_km or 0.0) <= (workout.distance_km or 0.0)


# ─────────────────────────────────────────────────────────────────────────────
# H. allow_intensity=False → no intensity added
# ─────────────────────────────────────────────────────────────────────────────

def test_H_no_intensity_added():
    workout = _wp("easy", duration_minutes=40)
    decision = build_readiness_decision(_readiness(85.0))
    result = build_daily_adaptation(
        workout=workout, readiness_decision=decision,
        training_load=None, recent_response=None,
    )
    assert result.adapted_workout.workout_type not in ("quality", "steady")
    assert result.adapted_workout.intensity_class not in ("high", "moderate")


# ─────────────────────────────────────────────────────────────────────────────
# I. No MOVE action
# ─────────────────────────────────────────────────────────────────────────────

def test_I_no_move_action():
    assert "MOVE" not in {a.value for a in DailyAdaptationAction}


# ─────────────────────────────────────────────────────────────────────────────
# J. No INCREASE action
# ─────────────────────────────────────────────────────────────────────────────

def test_J_no_increase_action():
    action_values = {a.value for a in DailyAdaptationAction}
    forbidden = {"INCREASE", "UPGRADE", "HARDEN", "CATCH_UP"}
    assert action_values.isdisjoint(forbidden)


# ─────────────────────────────────────────────────────────────────────────────
# K–N. Helper conversion functions
# ─────────────────────────────────────────────────────────────────────────────

def test_K_runtime_to_prescription_endurance():
    p = runtime_session_to_prescription(
        {"day": "monday", "type": "endurance", "duration": "45min", "distance_km": 8.0}
    )
    assert p.workout_type == "easy"
    assert p.intensity_class == "low"
    assert p.duration_minutes == 45
    assert p.distance_km == pytest.approx(8.0)


def test_L_runtime_to_prescription_rest():
    p = runtime_session_to_prescription(
        {"day": "sunday", "type": "rest", "duration": "0min", "distance_km": 0}
    )
    assert p.workout_type == "rest"
    assert p.distance_km is None
    assert p.duration_minutes is None


def test_M_prescription_to_runtime_roundtrip():
    original = _wp("easy", distance_km=10.0, duration_minutes=50)
    runtime = prescription_to_runtime_session(original)
    assert runtime["type"] == "endurance"
    assert runtime["intensity"] == "easy"
    assert runtime["duration"] == "50min"
    assert runtime["distance_km"] == pytest.approx(10.0)


def test_N_runtime_to_prescription_threshold():
    p = runtime_session_to_prescription(
        {"day": "wednesday", "type": "threshold", "duration": "55min", "distance_km": 12.0}
    )
    assert p.workout_type == "quality"
    assert p.intensity_class == "high"


# ─────────────────────────────────────────────────────────────────────────────
# O. Architecture guard: no numeric readiness thresholds in server endpoint
# ─────────────────────────────────────────────────────────────────────────────

def test_O_no_score_thresholds_in_server_endpoint():
    import re as _re
    server_src = _SERVER_PATH.read_text()
    start = server_src.find("async def get_today_adaptive_session")
    end = server_src.find("\n@api_router.", start + 1)
    assert start != -1
    endpoint_body = server_src[start:end] if end != -1 else server_src[start:]
    score_comparisons = _re.findall(r"(?:score|readiness)\s*[<>]=?\s*\d+", endpoint_body)
    assert not score_comparisons, f"Numeric score thresholds in endpoint: {score_comparisons}"


# ─────────────────────────────────────────────────────────────────────────────
# P–R. Recommendation mapping
# ─────────────────────────────────────────────────────────────────────────────

def test_P_band_to_recommendation_complete():
    for band in ReadinessBand:
        assert band in BAND_TO_RECOMMENDATION


def test_Q_unavailable_maps_gray():
    rec, color = BAND_TO_RECOMMENDATION[ReadinessBand.UNAVAILABLE]
    assert rec == "UNAVAILABLE"
    assert color == "gray"


def test_R_favorable_maps_green():
    rec, color = BAND_TO_RECOMMENDATION[ReadinessBand.FAVORABLE]
    assert rec == "RUN HARD"
    assert color == "green"


# ─────────────────────────────────────────────────────────────────────────────
# S. No fatigue_ratio/fatigue_status/fatigue_physio in payload
# ─────────────────────────────────────────────────────────────────────────────

def test_S_no_legacy_fatigue_fields():
    server_src = _SERVER_PATH.read_text()
    start = server_src.find("async def get_today_adaptive_session")
    end = server_src.find("\n@api_router.", start + 1)
    assert start != -1
    body = server_src[start:end] if end != -1 else server_src[start:]
    # Check that these keys are not used as actual dict keys in the payload
    for field in ("fatigue_ratio", "fatigue_status", "fatigue_physio"):
        # A dict key would appear as "field": or 'field':
        assert f'"{field}"' not in body and f"'{field}'" not in body, \
            f"Legacy key '{field}' found in endpoint payload"


# ─────────────────────────────────────────────────────────────────────────────
# T. No adapt_session_to_readiness call in endpoint
# ─────────────────────────────────────────────────────────────────────────────

def test_T_no_legacy_adapt_call():
    server_src = _SERVER_PATH.read_text()
    start = server_src.find("async def get_today_adaptive_session")
    end = server_src.find("\n@api_router.", start + 1)
    assert start != -1
    body = server_src[start:end] if end != -1 else server_src[start:]
    assert "adapt_session_to_readiness" not in body


# ─────────────────────────────────────────────────────────────────────────────
# U. ReadinessDecision routing (None ≠ 0 doctrine)
# ─────────────────────────────────────────────────────────────────────────────

def test_U_none_readiness_gives_unavailable():
    decision = build_readiness_decision(None)
    assert decision.band == ReadinessBand.UNAVAILABLE
    assert decision.score is None


def test_U_insufficient_gives_unavailable_not_very_low():
    readiness = _readiness(None, sufficiency_level=SufficiencyLevel.INSUFFICIENT)
    decision = build_readiness_decision(readiness)
    assert decision.band == ReadinessBand.UNAVAILABLE
    assert decision.band != ReadinessBand.VERY_LOW


# ─────────────────────────────────────────────────────────────────────────────
# V. parse_duration_minutes
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("s,expected", [
    ("30min", 30), ("0min", None), ("0", None),
    (None, None), ("", None), ("75min", 75),
])
def test_V_parse_duration(s, expected):
    assert parse_duration_minutes(s) == expected


# ─────────────────────────────────────────────────────────────────────────────
# W. Monotonicity sweep
# ─────────────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("score,workout_type", [
    (20.0, "quality"), (45.0, "easy"), (60.0, "long_easy"),
    (80.0, "easy"), (90.0, "quality"), (None, "easy"),
])
def test_W_monotonicity_sweep(score, workout_type):
    workout = _wp(workout_type, distance_km=12.0, duration_minutes=60)
    readiness = _readiness(
        score,
        sufficiency_level=(SufficiencyLevel.INSUFFICIENT if score is None else SufficiencyLevel.SUFFICIENT),
    )
    decision = build_readiness_decision(readiness)
    result = build_daily_adaptation(
        workout=workout, readiness_decision=decision,
        training_load=None, recent_response=None,
    )
    assert (result.adapted_workout.distance_km or 0.0) <= (workout.distance_km or 0.0)
    assert (result.adapted_workout.duration_minutes or 0) <= (workout.duration_minutes or 0)
