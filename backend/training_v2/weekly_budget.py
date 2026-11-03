"""Weekly budget V2 — remaining km and adaptation of future sessions.

PURE: no I/O, no clock.  Budget (indicative upper bound, never an obligation)::

    actual_weekly_km    = sum of unique running distances, local calendar week
                          (plan-associated AND free runs; duplicates excluded)
    remaining_budget_km = max(0, planned_weekly_km - actual_weekly_km)

Future sessions (strictly after the reference date) can only be reduced, never
increased: a missed session is never made up.  Today and past days are never
modified, so served snapshots stay authoritative.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Optional, Sequence

from .domain_activity import DomainActivity
from .training_history import activities_in_week
from .workout_generator import WeeklyPlan, WorkoutPrescription, _make_rest

MIN_SESSION_KM: float = 3.0
INTENSE_VIGOROUS_MINUTES: float = 10.0

_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass(frozen=True)
class WeeklyVolumeBudget:
    planned_weekly_km: Optional[float]
    actual_weekly_km: float
    remaining_budget_km: Optional[float]
    reason_codes: tuple[str, ...] = ()


def compute_remaining_budget(
    planned_weekly_km: Optional[float], actual_weekly_km: float
) -> Optional[float]:
    if planned_weekly_km is None:
        return None
    return round(max(0.0, planned_weekly_km - actual_weekly_km), 1)


def _is_quality(session: WorkoutPrescription) -> bool:
    return session.workout_type == "quality"


def _is_running_session(session: WorkoutPrescription) -> bool:
    return session.workout_type not in ("rest", "race") and session.distance_km is not None


def apply_weekly_budget(
    weekly_plan: WeeklyPlan,
    activities: Sequence[object],
    reference_date: date,
) -> tuple[WeeklyPlan, WeeklyVolumeBudget]:
    """Adapt sessions strictly after ``reference_date`` to the remaining budget.

    Never touches today or past days (served snapshots stay authoritative),
    never increases a session, never marks a free run as a completed
    specific session.  Distance-based plans only.
    """
    week_acts: list[DomainActivity] = activities_in_week(activities, reference_date)
    actual_km = round(sum(float(a.distance_m) for a in week_acts) / 1000.0, 2)

    if weekly_plan.target_basis != "distance" or weekly_plan.planned_km is None:
        return weekly_plan, WeeklyVolumeBudget(None, actual_km, None, ("BUDGET_NOT_DISTANCE_BASED",))

    remaining = compute_remaining_budget(weekly_plan.planned_km, actual_km)
    codes: list[str] = []
    today_idx = reference_date.weekday()
    sessions = list(weekly_plan.sessions)
    index_of = {s.day.lower(): i for i, s in enumerate(sessions)}

    def day_idx(session: WorkoutPrescription) -> int:
        return _DAYS.index(session.day.lower()) if session.day.lower() in _DAYS else -1

    # 1. Quality is never duplicated by an unplanned intense run.
    intense = sum(
        1 for a in week_acts if (a.vigorous_intensity_minutes or 0.0) >= INTENSE_VIGOROUS_MINUTES
    )
    planned_quality_so_far = sum(
        1 for s in sessions if _is_quality(s) and 0 <= day_idx(s) <= today_idx
    )
    extra_intense = max(0, intense - planned_quality_so_far)
    if extra_intense and weekly_plan.allow_intensity:
        for i, s in enumerate(sessions):
            if extra_intense and _is_quality(s) and day_idx(s) > today_idx:
                sessions[i] = s.model_copy(update={
                    "workout_type": "easy",
                    "intensity_class": "low",
                    "reason_codes": (*s.reason_codes, "QUALITY_NOT_DUPLICATED_AFTER_INTENSE_RUN"),
                })
                extra_intense -= 1
                codes.append("QUALITY_NOT_DUPLICATED_AFTER_INTENSE_RUN")

    # 2. Future sessions fit the remaining budget (reduce only).
    today_session = sessions[index_of[reference_date.strftime("%A").lower()]] if (
        reference_date.strftime("%A").lower() in index_of
    ) else None
    today_pending_km = 0.0
    ran_today = any(
        str(a.start_time)[:10] == reference_date.isoformat() for a in week_acts
    )
    if today_session is not None and _is_running_session(today_session) and not ran_today:
        today_pending_km = float(today_session.distance_km or 0.0)
    allowed_future = max(0.0, (remaining or 0.0) - today_pending_km)

    future = [i for i, s in enumerate(sessions) if day_idx(s) > today_idx and _is_running_session(s)]
    active = list(future)
    while active:
        total = sum(float(sessions[i].distance_km) for i in active)
        if total <= allowed_future + 1e-9:
            break
        factor = allowed_future / total
        scaled = {i: round(float(sessions[i].distance_km) * factor, 1) for i in active}
        too_small = [i for i in active if scaled[i] < MIN_SESSION_KM]
        if too_small:
            drop = min(too_small, key=lambda i: (float(sessions[i].distance_km), -i))
            sessions[drop] = _make_rest(sessions[drop].day, ("WEEKLY_BUDGET_SESSION_DROPPED",))
            active.remove(drop)
            codes.append("WEEKLY_BUDGET_SESSION_DROPPED")
            continue
        for i, km in scaled.items():
            sessions[i] = sessions[i].model_copy(update={
                "distance_km": km,
                "reason_codes": (*sessions[i].reason_codes, "WEEKLY_BUDGET_APPLIED"),
            })
        codes.append("WEEKLY_BUDGET_APPLIED")
        break

    if not codes:
        return weekly_plan, WeeklyVolumeBudget(weekly_plan.planned_km, actual_km, remaining)

    training = [s for s in sessions if s.workout_type not in ("rest", "race")]
    new_plan = weekly_plan.model_copy(update={
        "sessions": tuple(sessions),
        "planned_km": round(sum(float(s.distance_km or 0.0) for s in training), 1),
        "session_count": len(training),
    })
    return new_plan, WeeklyVolumeBudget(
        weekly_plan.planned_km, actual_km, remaining, tuple(dict.fromkeys(codes))
    )


__all__ = [
    "WeeklyVolumeBudget",
    "apply_weekly_budget",
    "compute_remaining_budget",
]
