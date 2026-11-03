"""Weekly volume engine V2 — deterministic trajectory and remaining budget.

PURE: no I/O, no clock, no global state.

Four distinct quantities (never conflated):

1. ``reference_km``         demonstrated volume, from COMPLETED calendar weeks.
2. ``trajectory_target_km`` plan volume for this week = reference × (1 + rate).
3. ``load_cap_km``          admissible ceiling for this week.
4. ``prescribed_km``        min(trajectory, cap) × phase multiplier.

Formulas (calibration V1, recalibrable)::

    capped_i      = min(km_i, 1.15 × median(active weeks))
    reference_km  = mean of the ceil(n/2) largest capped_i   (n >= 3 active weeks)
    rate          = clamp((peak/reference)^(1/build_weeks) - 1, 0, 0.08)   race date
                  = 0.03 while reference < peak                          no date
                  = 0                                                    maintenance,
                                                  reference >= peak, <= 2 sessions
    trajectory    = reference × (1 + rate)
    load_cap      = min(1.10 × reference, max(reference, 1.10 × last_completed_week))
    prescribed    = round(min(trajectory, load_cap) × phase_multiplier, 1)

Per-goal peaks are calibration parameters, NOT minimums: a runner below the
peak is never lifted to it, and a runner above it is held, not reduced.
No reference (fewer than 3 active completed weeks) → ``None``; the caller keeps
its legacy, observed-only behaviour and no km is invented.

The remaining budget lives in ``weekly_budget`` (it depends on the generator).
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Optional, Sequence


# ---------------------------------------------------------------------------
# Calibration constants — V1, recalibrable, NOT minimums
# ---------------------------------------------------------------------------

GOAL_PEAK_WEEKLY_KM: dict[str, float] = {
    "5k": 40.0,
    "10k": 50.0,
    "half_marathon": 65.0,
    "marathon": 85.0,
    "ultra": 100.0,
}
MIN_ACTIVE_COMPLETED_WEEKS: int = 3
SPIKE_CAP_FACTOR: float = 1.15
MAX_WEEKLY_RATE: float = 0.08
CONTINUOUS_WEEKLY_RATE: float = 0.03
SPECIFIC_PHASE_MAX_RATE: float = 0.03
MIN_SESSIONS_FOR_GROWTH: int = 3
LOAD_CAP_FACTOR: float = 1.10


@dataclass(frozen=True)
class VolumeTrajectory:
    reference_km: float
    trajectory_target_km: float
    load_cap_km: float
    prescribed_km: float
    weekly_rate: float
    reason_codes: tuple[str, ...]


def _median(values: Sequence[float]) -> float:
    ordered = sorted(values)
    mid = len(ordered) // 2
    return ordered[mid] if len(ordered) % 2 else (ordered[mid - 1] + ordered[mid]) / 2.0


def compute_reference_km(completed_week_km: Sequence[float]) -> Optional[float]:
    """Demonstrated weekly volume, robust to one light or one spike week."""
    active = [km for km in completed_week_km if km > 0]
    if len(active) < MIN_ACTIVE_COMPLETED_WEEKS:
        return None
    ceiling = SPIKE_CAP_FACTOR * _median(active)
    capped = sorted((min(km, ceiling) for km in active), reverse=True)
    top = capped[: math.ceil(len(capped) / 2)]
    return sum(top) / len(top)


def build_volume_trajectory(
    *,
    completed_week_km: Sequence[float],
    goal_type: str,
    weeks_to_race: Optional[float],
    taper_weeks: int,
    phase_multiplier: float,
    phase: str,
    target_sessions: int,
) -> Optional[VolumeTrajectory]:
    """Deterministic weekly trajectory, or None when history is insufficient."""
    reference = compute_reference_km(completed_week_km)
    if reference is None:
        return None

    codes: list[str] = ["VOLUME_TRAJECTORY"]
    peak = GOAL_PEAK_WEEKLY_KM.get(goal_type)
    rate = 0.0
    if peak is None:
        codes.append("TRAJECTORY_MAINTENANCE_HOLD")
    elif reference >= peak:
        codes.append("TRAJECTORY_AT_GOAL_PEAK_HOLD")
    elif weeks_to_race is not None and weeks_to_race > 0:
        build_weeks = max(1.0, weeks_to_race - taper_weeks)
        rate = (peak / reference) ** (1.0 / build_weeks) - 1.0
        rate = min(max(rate, 0.0), MAX_WEEKLY_RATE)
        if phase == "specific":
            rate = min(rate, SPECIFIC_PHASE_MAX_RATE)
        codes.append("TRAJECTORY_RACE_CALENDAR")
    else:
        rate = CONTINUOUS_WEEKLY_RATE
        codes.append("TRAJECTORY_CONTINUOUS")

    if rate > 0 and target_sessions < MIN_SESSIONS_FOR_GROWTH:
        rate = 0.0
        codes.append("TRAJECTORY_FREQUENCY_HOLD")

    trajectory = reference * (1.0 + rate)

    last_week = completed_week_km[0] if completed_week_km else 0.0
    load_cap = min(
        LOAD_CAP_FACTOR * reference,
        max(reference, LOAD_CAP_FACTOR * last_week),
    )
    if trajectory > load_cap:
        codes.append("TRAJECTORY_LOAD_CAPPED")
    if 0 < last_week < reference * 0.85:
        codes.append("TRAJECTORY_LIGHT_WEEK_IGNORED")

    prescribed = round(min(trajectory, load_cap) * phase_multiplier, 1)
    return VolumeTrajectory(
        reference_km=round(reference, 1),
        trajectory_target_km=round(trajectory, 1),
        load_cap_km=round(load_cap, 1),
        prescribed_km=prescribed,
        weekly_rate=round(rate, 4),
        reason_codes=tuple(codes),
    )


__all__ = [
    "GOAL_PEAK_WEEKLY_KM",
    "VolumeTrajectory",
    "build_volume_trajectory",
    "compute_reference_km",
]
