"""Weekly budget V2 — remaining km and adaptation of future sessions.

PURE: no I/O, no clock.  Budget (indicative upper bound, never an obligation)::

    actual_weekly_km    = sum of unique running distances, local calendar week
                          (plan-associated AND free runs; duplicates excluded)
    remaining_budget_km = max(0, planned_weekly_km - actual_weekly_km)

``planned_weekly_km`` is the INITIAL plan volume and is never rewritten by the
adaptation; ``adapted_remaining_km`` is the new total of the sessions still to
run after adaptation.  Sessions can only be reduced, never increased: a
missed session is never made up.  Today's session is adapted too while it is
neither served nor run (a reduction never reverts when a future day becomes
today); past days and frozen (served snapshot) sessions are never modified.  Frozen future sessions still consume
budget; when they alone exceed it, only the mutable sessions are adapted and
``WEEKLY_BUDGET_EXCEEDED_BY_FROZEN_SESSIONS`` is raised — the cap is then not
guaranteed.

Intensity: no physiological classification and no new threshold.  Three
evidence states are kept apart: ``confirmed`` (the caller supplied reliable
execution evidence for an unplanned demanding run), ``present_unverified``
(Garmin vigorous minutes alone, never a proof), ``unknown`` / ``none_known``.
Only a CONFIRMED unplanned demanding run can remove a future, mutable planned
quality session, and only so that demanding sessions done + still planned never
exceed the planned quality count of the week.  A planned quality session that
was not run is not counted as done.  Quality is never added, frozen sessions
and today are never modified; when duplication cannot be avoided because the
excess session is frozen or is today's, ``QUALITY_DUPLICATION_NOT_ADAPTABLE``
is reported.  The canonical pipeline currently has no reliable confirmation
source, so it reports ``INTENSITY_CONFIRMATION_UNAVAILABLE`` instead of acting.

C399 — minimum distance: an ordinary session reduced by the adaptation keeps at
least ``MIN_ORDINARY_SESSION_KM`` (4.0 km) or is replaced by an explicit rest.
When the budget cannot hold every session at that minimum, the least useful ones
(plain easy before quality before long run, then shorter, then later day) are
removed; kept sessions are served in priority order, never above their planned
distance, and freed volume is never redistributed.  Exempt: explicit reprise
continuity states (``short_sessions_allowed``) and frozen sessions.  Duration-based
plans are not converted to km (no adaptation).  Sessions no adaptation touched are
left as generated.

Structured sessions are regenerated from the final ``distance_km`` by the
structured-workout builder at serve time; after scaling each session is
validated with that same builder and downgraded (quality → easy) or dropped
when its blocks could not close the new total.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, replace
from datetime import date, timedelta
from typing import Collection, Mapping, Optional, Sequence

from .domain_activity import DomainActivity
from .periodization import PeriodizationSnapshot
from .plan_goal import PlanGoal
from .structured_workout import build_structured_workout_prescription
from .training_history import activities_in_week, activity_calendar_date
from .workout_generator import (
    MIN_ORDINARY_SESSION_KM,
    WeeklyPlan,
    WorkoutPrescription,
    _make_rest,
    short_sessions_allowed,
)

# Legacy floor, kept ONLY for explicit reprise states where short sessions are
# deliberate (see ``short_sessions_allowed``).  Ordinary weeks use
# ``MIN_ORDINARY_SESSION_KM`` (C399).
MIN_SESSION_KM: float = 3.0
INTENSE_VIGOROUS_MINUTES: float = 10.0

INTENSITY_NONE_KNOWN = "none_known"
INTENSITY_CONFIRMED = "confirmed"
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
    reference_weekday: Optional[int] = None
    ran_today: bool = False

    def with_final_sessions(self, final_sessions: Sequence[WorkoutPrescription]) -> "WeeklyVolumeBudget":
        """Recompute ``adapted_remaining_km`` from the sessions really exposed.

        ``remaining_budget_km`` (theoretical) is left untouched.  Same
        selection rule as the budget: today (not run yet) and later days.
        """
        if self.reference_weekday is None or self.adapted_remaining_km is None:
            return self
        total = sum(
            float(s.distance_km)
            for s in final_sessions
            if _is_running_session(s)
            and (
                _day_idx(s) > self.reference_weekday
                or (_day_idx(s) == self.reference_weekday and not self.ran_today)
            )
        )
        return replace(self, adapted_remaining_km=round(total, 1))

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


def _with_code(codes: Sequence[str], code: str) -> tuple[str, ...]:
    return tuple(dict.fromkeys((*codes, code)))


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


def _unplanned_demanding_days(
    week_acts: Sequence[DomainActivity],
    sessions: Sequence[WorkoutPrescription],
    confirmed_days: Collection[date],
) -> tuple[set[date], set[date]]:
    """(confirmed, unverified) days of unplanned runs with intensity evidence."""
    planned_quality_days = {_day_idx(s) for s in sessions if s.workout_type == "quality"}
    confirmed: set[date] = set()
    unverified: set[date] = set()
    for act in week_acts:
        day = activity_calendar_date(act)
        if day is None or day.weekday() in planned_quality_days:
            continue
        if day in confirmed_days:
            confirmed.add(day)
        elif (act.vigorous_intensity_minutes or 0.0) >= INTENSE_VIGOROUS_MINUTES:
            unverified.add(day)
    return confirmed, unverified


def _intensity_state(
    week_acts: Sequence[DomainActivity], confirmed: set[date], unverified: set[date]
) -> str:
    if confirmed:
        return INTENSITY_CONFIRMED
    if unverified:
        return INTENSITY_UNVERIFIED
    if week_acts and all(a.vigorous_intensity_minutes is None for a in week_acts):
        return INTENSITY_UNKNOWN
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
        "reason_codes": _with_code(session.reason_codes, "WEEKLY_BUDGET_APPLIED"),
    })
    if _structure_is_coherent(scaled, plan_goal, periodization):
        return scaled, None
    if session.workout_type == "quality":
        easy = scaled.model_copy(update={
            "workout_type": "easy",
            "intensity_class": "low",
            "reason_codes": _with_code(scaled.reason_codes, "QUALITY_DOWNGRADED_STRUCTURE_INCOHERENT"),
        })
        if _structure_is_coherent(easy, plan_goal, periodization):
            return easy, "QUALITY_DOWNGRADED_STRUCTURE_INCOHERENT"
    return _make_rest(session.day, ("WEEKLY_BUDGET_SESSION_DROPPED",)), "WEEKLY_BUDGET_SESSION_DROPPED"


def _limit_quality_duplication(
    sessions: list[WorkoutPrescription],
    week_acts: Sequence[DomainActivity],
    frozen: Mapping[str, WorkoutPrescription],
    today_idx: int,
    confirmed_off_plan: int,
    codes: list[str],
) -> None:
    """Downgrade surplus FUTURE mutable quality so demanding sessions never exceed the plan."""
    run_days = {d.weekday() for d in (activity_calendar_date(a) for a in week_acts) if d}
    planned_total = sum(1 for s in sessions if s.workout_type == "quality")
    done_planned = sum(
        1 for s in sessions
        if s.workout_type == "quality" and 0 <= _day_idx(s) <= today_idx and _day_idx(s) in run_days
    )
    pending = [
        i for i, s in enumerate(sessions)
        if s.workout_type == "quality"
        and (_day_idx(s) > today_idx or (_day_idx(s) == today_idx and _day_idx(s) not in run_days))
    ]
    allowed = max(0, planned_total - done_planned - confirmed_off_plan)
    excess = len(pending) - allowed
    if excess <= 0:
        return
    for i in sorted(pending, key=lambda i: -_day_idx(sessions[i])):
        if excess <= 0:
            break
        s = sessions[i]
        if _day_idx(s) <= today_idx or s.day.lower() in frozen:
            continue
        sessions[i] = s.model_copy(update={
            "workout_type": "easy",
            "intensity_class": "low",
            "reason_codes": (*s.reason_codes, "QUALITY_NOT_DUPLICATED_AFTER_CONFIRMED_INTENSE_RUN"),
        })
        codes.append("QUALITY_NOT_DUPLICATED_AFTER_CONFIRMED_INTENSE_RUN")
        excess -= 1
    if excess > 0:
        codes.append("QUALITY_DUPLICATION_NOT_ADAPTABLE")


@dataclass(frozen=True)
class _View:
    sessions: list
    codes: list
    evidence: str
    actual_km: float
    remaining: Optional[float]
    ran_today: bool
    today_idx: int


def _is_adaptable(
    session: WorkoutPrescription, today_idx: int, ran_today: bool, frozen: Mapping[str, WorkoutPrescription]
) -> bool:
    """Not served (no snapshot) and not yet run: future day, or today before any run."""
    idx = _day_idx(session)
    return (
        _is_running_session(session)
        and session.day.lower() not in frozen
        and (idx > today_idx or (idx == today_idx and not ran_today))
    )


def _budget_view(
    weekly_plan: WeeklyPlan,
    activities: Sequence[object],
    reference_date: date,
    frozen: Mapping[str, WorkoutPrescription],
    plan_goal: Optional[PlanGoal],
    periodization: Optional[PeriodizationSnapshot],
    confirmed_intense_days: Collection[date],
    short_exempt: bool = False,
) -> _View:
    week_acts: list[DomainActivity] = activities_in_week(activities, reference_date)
    actual_km = round(sum(float(a.distance_m) for a in week_acts) / 1000.0, 2)

    sessions = [frozen.get(s.day.lower(), s) for s in weekly_plan.sessions]
    confirmed_days, unverified_days = _unplanned_demanding_days(
        week_acts, sessions, set(confirmed_intense_days)
    )
    evidence = _intensity_state(week_acts, confirmed_days, unverified_days)
    planned_km = weekly_plan.planned_km
    remaining = compute_remaining_budget(planned_km, actual_km)
    codes: list[str] = []
    if evidence == INTENSITY_UNVERIFIED:
        codes.append("UNPLANNED_INTENSITY_EVIDENCE_UNVERIFIED")
        codes.append("INTENSITY_CONFIRMATION_UNAVAILABLE")
    today_idx = reference_date.weekday()
    ran_today = any(activity_calendar_date(a) == reference_date for a in week_acts)

    # A served (frozen) session of today that is not run yet still reserves budget.
    reserved_km = 0.0
    for s in sessions:
        if (
            _day_idx(s) == today_idx and _is_running_session(s) and not ran_today
            and s.day.lower() in frozen
        ):
            reserved_km += float(s.distance_km or 0.0)

    if confirmed_days:
        _limit_quality_duplication(
            sessions, week_acts, frozen, today_idx, len(confirmed_days), codes
        )

    mutable = [i for i, s in enumerate(sessions) if _is_adaptable(s, today_idx, ran_today, frozen)]
    frozen_future_km = sum(
        float(s.distance_km or 0.0)
        for s in sessions
        if _day_idx(s) > today_idx and _is_running_session(s) and s.day.lower() in frozen
    )
    headroom = (remaining or 0.0) - reserved_km - frozen_future_km
    if headroom < 0 and mutable:
        codes.append("WEEKLY_BUDGET_EXCEEDED_BY_FROZEN_SESSIONS")
    allowed_future = max(0.0, headroom)

    if short_exempt:
        _scale_legacy(sessions, mutable, allowed_future, plan_goal, periodization, codes)
    else:
        _arbitrate_ordinary(sessions, mutable, allowed_future, plan_goal, periodization, codes)
    return _View(sessions, codes, evidence, actual_km, remaining, ran_today, today_idx)


def _floor_tenth(value: float) -> float:
    return math.floor(value * 10 + 1e-9) / 10


def _scale_legacy(
    sessions: list,
    mutable: Sequence[int],
    allowed: float,
    plan_goal: Optional[PlanGoal],
    periodization: Optional[PeriodizationSnapshot],
    codes: list[str],
) -> None:
    """Proportional reduction, only for explicit reprise states (short sessions are deliberate)."""
    active = list(mutable)
    while active:
        total = sum(float(sessions[i].distance_km) for i in active)
        if total <= allowed + 1e-9:
            break
        factor = allowed / total
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


# Higher = kept first.  Long run and quality are the sessions a reduced week
# still needs; plain easy/steady runs go first, then recovery-typed fillers.
_KEEP_PRIORITY = {"long_easy": 3, "quality": 2, "steady": 1, "easy": 1, "recovery": 0}


def _keep_key(session: WorkoutPrescription, idx: int) -> tuple:
    return (_KEEP_PRIORITY.get(session.workout_type, 1), float(session.distance_km), -idx)


def _arbitrate_ordinary(
    sessions: list,
    mutable: Sequence[int],
    allowed: float,
    plan_goal: Optional[PlanGoal],
    periodization: Optional[PeriodizationSnapshot],
    codes: list[str],
) -> None:
    """Fewer sessions instead of many short ones (C399).

    When the mutable sessions fit the budget nothing changes.  Otherwise the
    least useful sessions are removed until every kept one can reach
    ``MIN_ORDINARY_SESSION_KM``; kept sessions are then served in priority
    order (each up to its own planned distance, never above it) so the others
    keep at least the minimum.  Freed volume is never redistributed upward.
    """
    originals = {i: sessions[i] for i in mutable}
    if sum(float(s.distance_km) for s in originals.values()) <= allowed + 1e-9:
        return

    def drop(i: int) -> None:
        sessions[i] = _make_rest(
            originals[i].day, ("WEEKLY_BUDGET_SESSION_DROPPED", "ORDINARY_SESSION_MIN_KM_NOT_MET")
        )
        codes.extend(["WEEKLY_BUDGET_SESSION_DROPPED", "ORDINARY_SESSION_MIN_KM_NOT_MET"])

    keep = [i for i in mutable if float(originals[i].distance_km) >= MIN_ORDINARY_SESSION_KM - 1e-9]
    for i in mutable:
        if i not in keep:
            drop(i)

    while keep:
        order = sorted(keep, key=lambda i: _keep_key(originals[i], i), reverse=True)
        if MIN_ORDINARY_SESSION_KM * len(order) > allowed + 1e-9:
            drop(order[-1])
            keep.remove(order[-1])
            continue
        km: dict[int, float] = {}
        left = allowed
        for pos, i in enumerate(order):
            reserve = MIN_ORDINARY_SESSION_KM * (len(order) - pos - 1)
            km[i] = _floor_tenth(min(float(originals[i].distance_km), left - reserve))
            left -= km[i]

        fitted: dict[int, WorkoutPrescription] = {}
        extras: list[str] = []
        failed: Optional[int] = None
        for i in order:
            original = originals[i]
            if km[i] >= float(original.distance_km) - 1e-9:
                fitted[i] = original
                continue
            session, extra = _fit_session(original, km[i], plan_goal, periodization)
            if session.workout_type == "rest":
                failed = i
                break
            fitted[i] = session
            if extra:
                extras.append(extra)
        if failed is not None:
            drop(failed)
            keep.remove(failed)
            continue

        longest_other = lambda i: max((km[j] for j in keep if j != i), default=0.0)
        for i, session in list(fitted.items()):
            if (
                session.workout_type == "long_easy"
                and km[i] < float(originals[i].distance_km) - 1e-9
                and km[i] < longest_other(i) - 1e-9
            ):
                easy = session.model_copy(update={
                    "workout_type": "easy",
                    "intensity_class": "low",
                    "reason_codes": _with_code(session.reason_codes, "LONG_RUN_DOWNGRADED_TO_EASY"),
                })
                if _structure_is_coherent(easy, plan_goal, periodization):
                    fitted[i] = easy
                    extras.append("LONG_RUN_DOWNGRADED_TO_EASY")
                else:
                    drop(i)
                    keep.remove(i)
                    fitted = {}
                    break
        if not fitted and keep:
            continue
        for i, session in fitted.items():
            sessions[i] = session
        codes.extend(extras)
        if any(sessions[i] is not originals[i] for i in fitted):
            codes.append("WEEKLY_BUDGET_APPLIED")
        break


def _session_km(session: WorkoutPrescription) -> float:
    return float(session.distance_km or 0.0) if _is_running_session(session) else 0.0


def apply_weekly_budget(
    weekly_plan: WeeklyPlan,
    activities: Sequence[object],
    reference_date: date,
    *,
    frozen_sessions: Optional[Mapping[str, WorkoutPrescription]] = None,
    plan_goal: Optional[PlanGoal] = None,
    periodization: Optional[PeriodizationSnapshot] = None,
    confirmed_intense_days: Collection[date] = (),
    continuity_state: Optional[str] = None,
) -> tuple[WeeklyPlan, WeeklyVolumeBudget]:
    """Adapt not-yet-served sessions from ``reference_date`` on to the remaining budget.

    Session states (the same rule for Today and Week):

    A. future, not served      -> adapted, reduce-only;
    B. today, not served/run   -> adapted exactly like A (never re-grows because
       the reference date moved: a reduction decided on an earlier day of the
       week is retained, see below);
    C. today, already served   -> frozen snapshot, never modified, reserves budget;
    D. past day / frozen       -> never modified.

    ``frozen_sessions`` maps a day name to an authoritative served prescription;
    it replaces the live session for that day, is never modified and is counted
    in the budget.  Distance-based plans only.

    Retention: the budget is also evaluated as it stood on each earlier day of
    the week (same activities restricted to that day, and only the snapshots of
    that day or earlier: a snapshot served later did not exist then and must not
    reopen budget already removed); a session keeps the
    smallest distance any of those views prescribed (distance only: a type
    change decided on an earlier day is not carried over).  Missed kilometres are
    therefore never recovered when a later day frees budget, and nothing is
    read from or written to storage.
    """
    frozen = {k.lower(): v for k, v in (frozen_sessions or {}).items()}
    short_exempt = short_sessions_allowed(continuity_state)
    view = _budget_view(
        weekly_plan, activities, reference_date, frozen, plan_goal, periodization,
        confirmed_intense_days, short_exempt,
    )
    evidence = view.evidence
    actual_km = view.actual_km

    if weekly_plan.target_basis != "distance" or weekly_plan.planned_km is None:
        return weekly_plan, WeeklyVolumeBudget(
            None, actual_km, None, ("BUDGET_NOT_DISTANCE_BASED",), None, evidence
        )

    planned_km = weekly_plan.planned_km
    remaining = view.remaining
    sessions = view.sessions
    codes = list(view.codes)
    today_idx = view.today_idx

    week_start = reference_date - timedelta(days=today_idx)
    for offset in range(today_idx):
        # A snapshot only exists from its own day on: replaying day D must not see
        # snapshots of later days (they would restore kilometres removed on D).
        frozen_then = {d: p for d, p in frozen.items() if d in _DAYS and _DAYS.index(d) <= offset}
        earlier = _budget_view(
            weekly_plan, activities, week_start + timedelta(days=offset), frozen_then,
            plan_goal, periodization, confirmed_intense_days, short_exempt,
        )
        for i, current in enumerate(sessions):
            if not _is_adaptable(current, today_idx, view.ran_today, frozen):
                continue
            retained_km = _session_km(earlier.sessions[i])
            if retained_km >= _session_km(current) - 1e-9:
                continue
            # Only the distance reduction is carried over, never a type change.
            if retained_km <= 0.0:
                sessions[i] = _make_rest(current.day, ("WEEKLY_BUDGET_SESSION_DROPPED",))
            else:
                sessions[i], extra = _fit_session(current, retained_km, plan_goal, periodization)
                if extra:
                    codes.append(extra)
            codes.append("WEEKLY_BUDGET_REDUCTION_RETAINED")

    changed = [s for s, o in zip(sessions, weekly_plan.sessions) if s != o]
    remaining_sessions = [
        s for s in sessions
        if _is_running_session(s)
        and (_day_idx(s) > today_idx or (_day_idx(s) == today_idx and not view.ran_today))
    ]
    adapted_remaining = round(sum(float(s.distance_km) for s in remaining_sessions), 1)
    unique_codes = tuple(dict.fromkeys(codes))

    if not changed:
        return weekly_plan, WeeklyVolumeBudget(
            planned_km, actual_km, remaining, unique_codes, adapted_remaining, evidence,
            today_idx, view.ran_today,
        )

    training = [s for s in sessions if s.workout_type not in ("rest", "race")]
    new_plan = weekly_plan.model_copy(update={
        "sessions": tuple(sessions),
        "planned_km": round(sum(float(s.distance_km or 0.0) for s in training), 1),
        "session_count": len(training),
    })
    return new_plan, WeeklyVolumeBudget(
        planned_km, actual_km, remaining, unique_codes, adapted_remaining, evidence,
        today_idx, view.ran_today,
    )


__all__ = [
    "INTENSITY_CONFIRMED",
    "INTENSITY_NONE_KNOWN",
    "INTENSITY_UNKNOWN",
    "INTENSITY_UNVERIFIED",
    "WeeklyVolumeBudget",
    "apply_weekly_budget",
    "compute_remaining_budget",
]
