"""Weekly budget V2 — remaining km and adaptation of future sessions.

PURE: no I/O, no clock.  Budget (indicative upper bound, never an obligation)::

    actual_weekly_km    = sum of unique running distances, local calendar week
                          (plan-associated AND free runs; duplicates excluded)
    remaining_budget_km = max(0, planned_weekly_km - actual_weekly_km)

``planned_weekly_km`` is the INITIAL plan volume and is never rewritten by the
adaptation; ``adapted_remaining_km`` is the new total of the sessions still to
run after adaptation.  Future sessions can only be reduced, never increased: a
missed session is never made up.  Today, past days and frozen (served
snapshot) sessions are never modified.  Frozen future sessions still consume
budget; when they alone exceed it, only the mutable sessions are adapted and
``WEEKLY_BUDGET_EXCEEDED_BY_FROZEN_SESSIONS`` is raised — the cap is then not
guaranteed.

Intensity: no physiological classification is attempted.  Vigorous minutes
reported by Garmin on an unplanned run are exposed as an explicit, unverified
evidence state; they never remove a planned quality session and quality is
never added.

Structured sessions are regenerated from the final ``distance_km`` by the
structured-workout builder at serve time; after scaling each session is
validated with that same builder and downgraded (quality → easy) or dropped
when its blocks could not close the new total.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Mapping, Optional, Sequence

from .domain_activity import DomainActivity
from .periodization import PeriodizationSnapshot
from .plan_goal import PlanGoal
from .structured_workout import build_structured_workout_prescription
from .training_history import activities_in_week, activity_calendar_date
from .workout_generator import WeeklyPlan, WorkoutPrescription, _make_rest

MIN_SESSION_KM: float = 3.0
INTENSE_VIGOROUS_MINUTES: float = 10.0

INTENSITY_NONE_KNOWN = "none_known"
INTENSITY_UNVERIFIED = "present_unverified"
INTENSITY_UNKNOWN = "unknown"

_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")


@dataclass(frozen=True)
class WeeklyVolumeBudget:
    planned_weekly_km: Optional[float]
    actual_weekly_km: float
    remaining_budget_km: Optional[float]
    reason_codes: tuple[str, ...] = ()
    adapted_remaining_km: Optional[float] = None
    unplanned_intensity_evidence: str = INTENSITY_NONE_KNOWN

    def to_response(self) -> dict:
        """Additive, JSON-safe block shared by Today and Week."""
        return {
            "planned_weekly_km": self.planned_weekly_km,
            "actual_weekly_km": self.actual_weekly_km,
            "remaining_budget_km": self.remaining_budget_km,
            "adapted_remaining_km": self.adapted_remaining_km,
            "volume_reason_codes": list(self.reason_codes),
            "unplanned_intensity_evidence": self.unplanned_intensity_evidence,
        }


def compute_remaining_budget(
    planned_weekly_km: Optional[float], actual_weekly_km: float
) -> Optional[float]:
    if planned_weekly_km is None:
        return None
    return round(max(0.0, planned_weekly_km - actual_weekly_km), 1)


def _is_running_session(session: WorkoutPrescription) -> bool:
    return session.workout_type not in ("rest", "race") and session.distance_km is not None


def _day_idx(session: WorkoutPrescription) -> int:
    day = session.day.lower()
    return _DAYS.index(day) if day in _DAYS else -1


def _structure_is_coherent(
    session: WorkoutPrescription,
    plan_goal: Optional[PlanGoal],
    periodization: Optional[PeriodizationSnapshot],
) -> bool:
    """True when the structured blocks follow the session distance.

    ``DISTANCE_TOTAL_MIXED_BASIS`` (timed recoveries) is an explicit contract
    state that makes no total claim, so it is coherent; only an applicable
    invariant that does not close is a contradiction.
    """
    if plan_goal is None or periodization is None:
        return True
    try:
        structured = build_structured_workout_prescription(
            workout=session, plan_goal=plan_goal, periodization=periodization
        )
    except Exception:
        return False
    if not structured.distance_invariant_applicable:
        return True
    return bool(structured.distance_closes_total)


def _intensity_evidence(
    week_acts: Sequence[DomainActivity],
    sessions: Sequence[WorkoutPrescription],
) -> str:
    if not week_acts:
        return INTENSITY_NONE_KNOWN
    if all(a.vigorous_intensity_minutes is None for a in week_acts):
        return INTENSITY_UNKNOWN
    planned_quality_days = {
        _day_idx(s) for s in sessions if s.workout_type == "quality"
    }
    for act in week_acts:
        day = activity_calendar_date(act)
        if (
            (act.vigorous_intensity_minutes or 0.0) >= INTENSE_VIGOROUS_MINUTES
            and day is not None
            and day.weekday() not in planned_quality_days
        ):
            return INTENSITY_UNVERIFIED
    return INTENSITY_NONE_KNOWN


def _fit_session(
    session: WorkoutPrescription,
    km: float,
    plan_goal: Optional[PlanGoal],
    periodization: Optional[PeriodizationSnapshot],
) -> tuple[WorkoutPrescription, Optional[str]]:
    """Scale one session; keep it coherent or downgrade it, never leave blocks stale."""
    scaled = session.model_copy(update={
        "distance_km": km,
        "reason_codes": (*session.reason_codes, "WEEKLY_BUDGET_APPLIED"),
    })
    if _structure_is_coherent(scaled, plan_goal, periodization):
        return scaled, None
    if session.workout_type == "quality":
        easy = scaled.model_copy(update={
            "workout_type": "easy",
            "intensity_class": "low",
            "reason_codes": (*scaled.reason_codes, "QUALITY_DOWNGRADED_STRUCTURE_INCOHERENT"),
        })
        if _structure_is_coherent(easy, plan_goal, periodization):
            return easy, "QUALITY_DOWNGRADED_STRUCTURE_INCOHERENT"
    return _make_rest(session.day, ("WEEKLY_BUDGET_SESSION_DROPPED",)), "WEEKLY_BUDGET_SESSION_DROPPED"


def apply_weekly_budget(
    weekly_plan: WeeklyPlan,
    activities: Sequence[object],
    reference_date: date,
    *,
    frozen_sessions: Optional[Mapping[str, WorkoutPrescription]] = None,
    plan_goal: Optional[PlanGoal] = None,
    periodization: Optional[PeriodizationSnapshot] = None,
) -> tuple[WeeklyPlan, WeeklyVolumeBudget]:
    """Adapt sessions strictly after ``reference_date`` to the remaining budget.

    ``frozen_sessions`` maps a day name to an authoritative served prescription;
    it replaces the live session for that day, is never modified and is counted
    in the budget.  Distance-based plans only.
    """
    week_acts: list[DomainActivity] = activities_in_week(activities, reference_date)
    actual_km = round(sum(float(a.distance_m) for a in week_acts) / 1000.0, 2)
    frozen = {k.lower(): v for k, v in (frozen_sessions or {}).items()}

    sessions = [frozen.get(s.day.lower(), s) for s in weekly_plan.sessions]
    evidence = _intensity_evidence(week_acts, sessions)

    if weekly_plan.target_basis != "distance" or weekly_plan.planned_km is None:
        return weekly_plan, WeeklyVolumeBudget(
            None, actual_km, None, ("BUDGET_NOT_DISTANCE_BASED",), None, evidence
        )

    planned_km = weekly_plan.planned_km
    remaining = compute_remaining_budget(planned_km, actual_km)
    codes: list[str] = []
    if evidence == INTENSITY_UNVERIFIED:
        codes.append("UNPLANNED_INTENSITY_EVIDENCE_UNVERIFIED")
    today_idx = reference_date.weekday()

    ran_today = any(activity_calendar_date(a) == reference_date for a in week_acts)
    today_pending_km = 0.0
    for s in sessions:
        if _day_idx(s) == today_idx and _is_running_session(s) and not ran_today:
            today_pending_km = float(s.distance_km or 0.0)

    mutable = [
        i for i, s in enumerate(sessions)
        if _day_idx(s) > today_idx and _is_running_session(s) and s.day.lower() not in frozen
    ]
    frozen_future_km = sum(
        float(s.distance_km or 0.0)
        for s in sessions
        if _day_idx(s) > today_idx and _is_running_session(s) and s.day.lower() in frozen
    )
    headroom = (remaining or 0.0) - today_pending_km - frozen_future_km
    if headroom < 0 and mutable:
        codes.append("WEEKLY_BUDGET_EXCEEDED_BY_FROZEN_SESSIONS")
    allowed_future = max(0.0, headroom)

    active = list(mutable)
    while active:
        total = sum(float(sessions[i].distance_km) for i in active)
        if total <= allowed_future + 1e-9:
            break
        factor = allowed_future / total
        scaled_km = {i: round(float(sessions[i].distance_km) * factor, 1) for i in active}
        too_small = [i for i in active if scaled_km[i] < MIN_SESSION_KM]
        if too_small:
            drop = min(too_small, key=lambda i: (float(sessions[i].distance_km), -i))
            sessions[drop] = _make_rest(sessions[drop].day, ("WEEKLY_BUDGET_SESSION_DROPPED",))
            active.remove(drop)
            codes.append("WEEKLY_BUDGET_SESSION_DROPPED")
            continue
        for i, km in scaled_km.items():
            fitted, extra = _fit_session(sessions[i], km, plan_goal, periodization)
            sessions[i] = fitted
            if extra:
                codes.append(extra)
        codes.append("WEEKLY_BUDGET_APPLIED")
        break

    changed = [s for s, o in zip(sessions, weekly_plan.sessions) if s != o]
    remaining_sessions = [
        s for s in sessions
        if _is_running_session(s)
        and (_day_idx(s) > today_idx or (_day_idx(s) == today_idx and not ran_today))
    ]
    adapted_remaining = round(sum(float(s.distance_km) for s in remaining_sessions), 1)
    unique_codes = tuple(dict.fromkeys(codes))

    if not changed:
        return weekly_plan, WeeklyVolumeBudget(
            planned_km, actual_km, remaining, unique_codes, adapted_remaining, evidence
        )

    training = [s for s in sessions if s.workout_type not in ("rest", "race")]
    new_plan = weekly_plan.model_copy(update={
        "sessions": tuple(sessions),
        "planned_km": round(sum(float(s.distance_km or 0.0) for s in training), 1),
        "session_count": len(training),
    })
    return new_plan, WeeklyVolumeBudget(
        planned_km, actual_km, remaining, unique_codes, adapted_remaining, evidence
    )


__all__ = [
    "INTENSITY_NONE_KNOWN",
    "INTENSITY_UNKNOWN",
    "INTENSITY_UNVERIFIED",
    "WeeklyVolumeBudget",
    "apply_weekly_budget",
    "compute_remaining_budget",
]
