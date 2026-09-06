"""PR137 — Daily runtime helpers: WorkoutPrescription ↔ runtime session dict.

These pure functions bridge the runtime session dict format (produced by
adapt_weekly_plan_to_runtime_payload) and the WorkoutPrescription V2 contract
required by build_daily_adaptation.

Design rules
------------
- PURE: no DB, no HTTP, no LLM, no cache, no global mutable state.
- None ≠ 0: distance_km=0 and duration_minutes=0 are treated as absent.
- No readiness thresholds defined here.  ReadinessDecision is the single
  translation layer.
"""

from __future__ import annotations

import re
from typing import Optional

from .readiness_decision import ReadinessBand
from .workout_generator import WorkoutPrescription

# ---------------------------------------------------------------------------
# Type mappings (inverse of training_v2/runtime_plan_adapter._TYPE_MAP)
# ---------------------------------------------------------------------------

RUNTIME_TYPE_TO_WORKOUT_TYPE: dict = {
    "rest": "rest",
    "recovery": "recovery",
    "endurance": "easy",
    "tempo": "steady",
    "threshold": "quality",
    "long_run": "long_easy",
}

WORKOUT_TYPE_TO_INTENSITY_CLASS: dict = {
    "rest": "rest",
    "recovery": "low",
    "easy": "low",
    "steady": "moderate",
    "quality": "high",
    "long_easy": "low",
}

WORKOUT_TYPE_TO_RUNTIME_TYPE: dict = {
    "rest": "rest",
    "recovery": "recovery",
    "easy": "endurance",
    "steady": "tempo",
    "quality": "threshold",
    "long_easy": "long_run",
}

INTENSITY_CLASS_TO_RUNTIME: dict = {
    "rest": "rest",
    "low": "easy",
    "moderate": "moderate",
    "high": "hard",
}

# Canonical recommendation string + color derived from ReadinessBand (legacy compat).
# Direction: V2 ReadinessDecision → compatibility adapter.  Never legacy → V2.
BAND_TO_RECOMMENDATION: dict = {
    ReadinessBand.FAVORABLE: ("RUN HARD", "green"),
    ReadinessBand.CAUTION: ("EASY RUN", "yellow"),
    ReadinessBand.LOW: ("EASY RUN", "yellow"),
    ReadinessBand.VERY_LOW: ("REST", "red"),
    ReadinessBand.UNAVAILABLE: ("UNAVAILABLE", "gray"),
}


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def parse_duration_minutes(duration_str: Optional[str]) -> Optional[int]:
    """Parse '30min' → 30.  '0min' / None / '' → None (treat 0 as absent)."""
    if not duration_str:
        return None
    m = re.match(r"(\d+)", str(duration_str))
    if not m:
        return None
    val = int(m.group(1))
    return val if val > 0 else None


def runtime_session_to_prescription(session: dict) -> WorkoutPrescription:
    """Convert a runtime session dict (plan V2 payload) to WorkoutPrescription.

    Inverse of adapt_weekly_plan_to_runtime_payload so that build_daily_adaptation
    receives a proper V2 contract object.
    None ≠ 0: distance_km == 0 is treated as absent.
    """
    runtime_type = (session.get("type") or "rest").lower()
    workout_type = RUNTIME_TYPE_TO_WORKOUT_TYPE.get(runtime_type, "rest")
    intensity_class = WORKOUT_TYPE_TO_INTENSITY_CLASS.get(workout_type, "low")

    raw_distance = session.get("distance_km")
    distance_km: Optional[float] = float(raw_distance) if raw_distance else None
    if distance_km == 0.0:
        distance_km = None

    duration_minutes = parse_duration_minutes(session.get("duration"))
    day = (session.get("day") or "monday").lower()

    return WorkoutPrescription(
        day=day,
        workout_type=workout_type,
        intensity_class=intensity_class,
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        reason_codes=("PLAN_V2",),
    )


def _step_to_runtime_dict(step) -> dict:
    """C232 (correction, round 7) — serialize ONE WorkoutStep verbatim, the
    same shape as server.py's `_step_response` (WeekV2WorkoutStepResponse),
    so Today and Week transport the identical structural contract."""
    pace_range = (
        {
            "lower_min_per_km": step.pace_range.lower_min_per_km,
            "upper_min_per_km": step.pace_range.upper_min_per_km,
        }
        if step.pace_range is not None
        else None
    )
    return {
        "kind": step.kind,
        "repetitions": step.repetitions,
        "distance_km": step.distance_km,
        "duration_minutes": step.duration_minutes,
        "pace_zone": step.pace_zone,
        "pace_range": pace_range,
    }


def prescription_to_runtime_session(prescription: WorkoutPrescription) -> dict:
    """Convert a WorkoutPrescription to runtime session dict format (frontend compat).

    None ≡ '0min' contract: duration_minutes=None is emitted as '0min' (canonical
    runtime sentinel for rest / no-duration sessions), and parse_duration_minutes
    converts '0min' back to None.  The round-trip None → '0min' → None is
    intentionally symmetric.  Callers must not infer a meaningful duration from '0min'.

    C232 (correction, round 7 — BLOCKER FIX): the legacy keys below
    ("type"/"duration"/"intensity"/"distance_km"/"estimated_tss") are kept
    UNCHANGED for backward compatibility (Dashboard.jsx still reads them).
    New CANONICAL keys are added ADDITIVELY so /training/today serves
    EXACTLY the same prescription contract as /training/v2/week:
    ``workout_type`` (raw, undecorated — never the runtime-mapped "type"),
    ``duration_minutes`` (raw numeric, never a "55min" string), and
    ``steps`` (verbatim, never fabricated). ``primary_pace`` is always
    ``None`` here: Today's own day is never "strictly future" relative to
    itself, so — exactly like /training/v2/week's freeze rule — no live
    pace is ever resolved for it; a real numeric pace can only ever come
    from a frozen step's ``pace_range`` inside ``steps`` above.
    """
    runtime_type = WORKOUT_TYPE_TO_RUNTIME_TYPE.get(prescription.workout_type, prescription.workout_type)
    runtime_intensity = INTENSITY_CLASS_TO_RUNTIME.get(prescription.intensity_class, "easy")
    duration_str = (
        f"{prescription.duration_minutes}min"
        if prescription.duration_minutes is not None
        else "0min"
    )
    return {
        "day": prescription.day,
        "type": runtime_type,
        "duration": duration_str,
        "intensity": runtime_intensity,
        "distance_km": prescription.distance_km if prescription.distance_km is not None else 0,
        "estimated_tss": None,
        # Canonical fields (C232 correction, round 7) — same contract as Week.
        "workout_type": prescription.workout_type,
        "duration_minutes": prescription.duration_minutes,
        "steps": [_step_to_runtime_dict(step) for step in prescription.steps],
        "primary_pace": None,
    }


__all__ = [
    "RUNTIME_TYPE_TO_WORKOUT_TYPE",
    "WORKOUT_TYPE_TO_INTENSITY_CLASS",
    "WORKOUT_TYPE_TO_RUNTIME_TYPE",
    "INTENSITY_CLASS_TO_RUNTIME",
    "BAND_TO_RECOMMENDATION",
    "parse_duration_minutes",
    "runtime_session_to_prescription",
    "prescription_to_runtime_session",
]
