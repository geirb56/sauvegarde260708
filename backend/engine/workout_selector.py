"""
Workout Selector — pure deterministic workout recommendation.

Selects today's workout type, duration, and intensity based on readiness
and ACWR.

No FastAPI, no I/O — only pure computation.
"""

from __future__ import annotations

# Readiness threshold above which high-intensity training is recommended.
HIGH_READINESS_THRESHOLD = 75
# Readiness threshold above which moderate-intensity training is recommended.
MODERATE_READINESS_THRESHOLD = 50
# Maximum safe ACWR before overtraining risk is flagged.
MAX_SAFE_ACWR = 1.3


def select_workout(readiness: float, acwr: float) -> dict:
    """Return a workout recommendation for today.

    Parameters
    ----------
    readiness:
        Readiness score in [0, 100].
    acwr:
        Acute:Chronic Workload Ratio.

    Returns
    -------
    dict with keys:
        ``type``      – "interval" | "tempo" | "recovery"
        ``duration``  – recommended duration in minutes
        ``intensity`` – "low" | "moderate" | "high"
    """
    if readiness > HIGH_READINESS_THRESHOLD and acwr < MAX_SAFE_ACWR:
        workout_type = "interval"
        duration = 45
        intensity = "high"
    elif MODERATE_READINESS_THRESHOLD <= readiness <= HIGH_READINESS_THRESHOLD:
        workout_type = "tempo"
        duration = 40
        intensity = "moderate"
    else:
        workout_type = "recovery"
        duration = 30
        intensity = "low"

    return {
        "type": workout_type,
        "duration": duration,
        "intensity": intensity,
    }
