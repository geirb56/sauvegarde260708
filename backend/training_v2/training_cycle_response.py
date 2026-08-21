"""PR175 — Native V2 cycle calendar response for GET /training/v2/cycle.

Design rules
------------
- PURE: no MongoDB, no Garmin calls, no API calls, no LLM, no cache,
  no global mutable state, no datetime.now(), no date.today().
- All dates injected by the caller.
- No imports from training_engine, llm_coach, generate_cycle_week,
  full-cycle legacy.
- No WeeklyTarget, no session prescription, no future volume targets.
- Uses only PlanGoal V2 and Periodization V2 as calendar authority.

Principle
---------
"Le cycle V2 décrit le calendrier. Il ne prescrit pas les semaines futures."

Modes
-----
  race_calendar : PlanGoal has race_date + race goal_type.
  continuous    : maintenance or any goal without race_date (12-week cycling).

Weeks array
-----------
Each entry: week_number, start_date, end_date, phase, is_current.
No volume fields (target_km, target_duration_minutes, session_count,
sessions, long_run, estimated_tss, intensity, pace, zones).

current_week
------------
Global 1-based position in the complete cycle (not phase-local cycle_week).
Example: 4 base weeks + week 2 of build → current_week = 6.

Status
------
  upcoming  : reference_date < cycle start
  active    : cycle start ≤ reference_date ≤ cycle end
  completed : reference_date > cycle end
"""

from __future__ import annotations

import math
from datetime import date, timedelta
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from .periodization import (
    CONTINUOUS_BASE_WEEKS,
    CONTINUOUS_BUILD_WEEKS,
    CONTINUOUS_CONSOLIDATION_WEEKS,
    CONTINUOUS_CYCLE_LENGTH_WEEKS,
    TAPER_WEEKS,
    PeriodizationPhase,
    _build_race_phase_schedule,
)
from .plan_goal import GoalType, PlanGoal

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_RACE_GOALS: frozenset[GoalType] = frozenset(
    {
        GoalType.five_k,
        GoalType.ten_k,
        GoalType.half_marathon,
        GoalType.marathon,
        GoalType.ultra,
    }
)

_DAYS_PER_WEEK = 7


# ---------------------------------------------------------------------------
# Response models
# ---------------------------------------------------------------------------


class CycleGoalResponse(BaseModel):
    """Snapshot of the user's goal for this cycle."""

    model_config = ConfigDict(frozen=True)

    goal_type: str
    target_distance_km: Optional[float] = None
    race_date: Optional[str] = None
    target_time_seconds: Optional[int] = None


class CycleMetaResponse(BaseModel):
    """High-level cycle metadata."""

    model_config = ConfigDict(frozen=True)

    mode: str
    """race_calendar | continuous."""

    status: str
    """upcoming | active | completed."""

    start_date: str
    """ISO-8601 cycle start date."""

    end_date: str
    """ISO-8601 cycle end date."""

    current_week: Optional[int]
    """1-based global week position in the cycle; None when cycle is completed or upcoming."""

    total_weeks: int
    """Total number of weeks in the cycle."""

    days_to_race: Optional[int]
    """Days to race if race is upcoming or today; None otherwise."""


class WeekCalendarEntry(BaseModel):
    """One week slot in the training cycle calendar."""

    model_config = ConfigDict(frozen=True)

    week_number: int
    """1-based position in the cycle."""

    start_date: str
    """ISO-8601 first day of this week."""

    end_date: str
    """ISO-8601 last day of this week (may be < 7 days for the final partial week)."""

    phase: str
    """base | build | specific | taper | race | consolidation."""

    is_current: bool
    """True for the single week that contains reference_date (active cycle only)."""


class TrainingCycleV2Response(BaseModel):
    """Top-level response for GET /training/v2/cycle."""

    model_config = ConfigDict(frozen=True)

    reference_date: str
    """ISO-8601 anchor date used for this construction."""

    goal: CycleGoalResponse
    cycle: CycleMetaResponse
    weeks: List[WeekCalendarEntry]


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _add_days(d: date, days: int) -> date:
    return d + timedelta(days=days)


def _phase_for_date(
    d: date,
    schedule: list[tuple[PeriodizationPhase, date, date]],
) -> str:
    """Return the phase name for a given date from a race phase schedule."""
    for ph, ph_start, ph_end in schedule:
        if ph_start <= d <= ph_end:
            return ph.value
    # Fallback: return the phase of the nearest boundary.
    if schedule:
        return schedule[-1][0].value
    return PeriodizationPhase.base.value  # pragma: no cover


def _build_race_calendar_weeks(
    plan_start: date,
    race_date: date,
    reference_date: date,
    taper_weeks: int,
) -> tuple[list[WeekCalendarEntry], int]:
    """Build week entries for race_calendar mode.

    Returns (weeks, current_week_number).
    current_week_number is 0 if reference_date is outside the cycle range.
    """
    schedule = _build_race_phase_schedule(plan_start, race_date, taper_weeks)

    total_days = (race_date - plan_start).days  # 0 for same-day
    # Minimum 1 week (race day scenario)
    total_weeks = max(1, math.ceil((total_days + 1) / _DAYS_PER_WEEK))

    weeks: list[WeekCalendarEntry] = []
    current_week_number = 0
    cursor = plan_start

    for i in range(total_weeks):
        wk_start = cursor
        wk_end = _add_days(wk_start, _DAYS_PER_WEEK - 1)
        if wk_end > race_date:
            wk_end = race_date

        # Phase: use wk_end so the week containing race_date gets phase "race".
        phase_str = _phase_for_date(wk_end, schedule)
        is_current = wk_start <= reference_date <= wk_end

        if is_current:
            current_week_number = i + 1

        weeks.append(
            WeekCalendarEntry(
                week_number=i + 1,
                start_date=wk_start.isoformat(),
                end_date=wk_end.isoformat(),
                phase=phase_str,
                is_current=is_current,
            )
        )
        cursor = _add_days(wk_start, _DAYS_PER_WEEK)

    return weeks, current_week_number


def _build_continuous_weeks(
    cycle_start: date,
    reference_date: date,
) -> tuple[list[WeekCalendarEntry], int]:
    """Build week entries for continuous mode (12 weeks: 4 base / 5 build / 3 consolidation).

    Returns (weeks, current_week_number).
    """
    # Phase boundaries by week number (1-based)
    _PHASE_BY_WEEK: list[str] = (
        [PeriodizationPhase.base.value] * CONTINUOUS_BASE_WEEKS
        + [PeriodizationPhase.build.value] * CONTINUOUS_BUILD_WEEKS
        + [PeriodizationPhase.consolidation.value] * CONTINUOUS_CONSOLIDATION_WEEKS
    )

    weeks: list[WeekCalendarEntry] = []
    current_week_number = 0

    for i in range(CONTINUOUS_CYCLE_LENGTH_WEEKS):
        wk_start = _add_days(cycle_start, i * _DAYS_PER_WEEK)
        wk_end = _add_days(wk_start, _DAYS_PER_WEEK - 1)
        phase_str = _PHASE_BY_WEEK[i]
        is_current = wk_start <= reference_date <= wk_end

        if is_current:
            current_week_number = i + 1

        weeks.append(
            WeekCalendarEntry(
                week_number=i + 1,
                start_date=wk_start.isoformat(),
                end_date=wk_end.isoformat(),
                phase=phase_str,
                is_current=is_current,
            )
        )

    return weeks, current_week_number


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def build_cycle_calendar_response(
    plan_goal: PlanGoal,
    reference_date: date,
    *,
    cycle_anchor_date: Optional[date] = None,
    race_plan_start_date: Optional[date] = None,
    target_time_seconds: Optional[int] = None,
) -> TrainingCycleV2Response:
    """Build a deterministic TrainingCycleV2Response.

    Parameters
    ----------
    plan_goal:
        The runner's current goal (PlanGoal V2).
    reference_date:
        The anchor date — injected by the caller, never inferred.
    cycle_anchor_date:
        Required for continuous mode.  The cycle repeats from this date.
    race_plan_start_date:
        Required for race_calendar mode (future or past race).
        The start of the training plan for this race.
    target_time_seconds:
        Optional target time in seconds; passed through to the goal response.

    Returns
    -------
    TrainingCycleV2Response
        Immutable, deterministic response.  No session prescription.
        No volume targets.  No future WeeklyTarget.
    """
    is_race_calendar = (
        plan_goal.race_date is not None and plan_goal.goal_type in _RACE_GOALS
    )

    # ── Goal response ─────────────────────────────────────────────────────
    goal_response = CycleGoalResponse(
        goal_type=plan_goal.goal_type.value,
        target_distance_km=plan_goal.target_distance_km,
        race_date=plan_goal.race_date.isoformat() if plan_goal.race_date else None,
        target_time_seconds=target_time_seconds,
    )

    # ── Race calendar mode ────────────────────────────────────────────────
    if is_race_calendar:
        race_date: date = plan_goal.race_date  # type: ignore[assignment]

        if race_plan_start_date is None:
            raise ValueError(
                "race_plan_start_date is required for race_calendar mode "
                f"(race_date={race_date}, reference_date={reference_date})."
            )

        plan_start = race_plan_start_date
        taper_weeks = TAPER_WEEKS[plan_goal.goal_type]

        weeks, current_week_number = _build_race_calendar_weeks(
            plan_start, race_date, reference_date, taper_weeks
        )
        total_weeks = len(weeks)

        # Cycle boundaries
        cycle_start = plan_start
        cycle_end = race_date

        # Status
        if reference_date < cycle_start:
            status = "upcoming"
            current_week: Optional[int] = None
        elif reference_date > cycle_end:
            status = "completed"
            current_week = None
        else:
            status = "active"
            current_week = current_week_number if current_week_number > 0 else None

        # days_to_race: positive integer for future/today, null for past
        days_to_race: Optional[int]
        if reference_date <= race_date:
            days_to_race = (race_date - reference_date).days
        else:
            days_to_race = None

        # Ensure no is_current for non-active cycles
        if status != "active":
            weeks = [
                WeekCalendarEntry(
                    week_number=w.week_number,
                    start_date=w.start_date,
                    end_date=w.end_date,
                    phase=w.phase,
                    is_current=False,
                )
                for w in weeks
            ]

        cycle_meta = CycleMetaResponse(
            mode="race_calendar",
            status=status,
            start_date=cycle_start.isoformat(),
            end_date=cycle_end.isoformat(),
            current_week=current_week,
            total_weeks=total_weeks,
            days_to_race=days_to_race,
        )

        return TrainingCycleV2Response(
            reference_date=reference_date.isoformat(),
            goal=goal_response,
            cycle=cycle_meta,
            weeks=weeks,
        )

    # ── Continuous mode ───────────────────────────────────────────────────
    if cycle_anchor_date is None:
        raise ValueError(
            "cycle_anchor_date is required for continuous mode "
            f"(reference_date={reference_date}). Never invent an anchor internally."
        )

    # Reconstruct cycle_start: most recent anchor multiple before reference_date
    cycle_total_days = CONTINUOUS_CYCLE_LENGTH_WEEKS * _DAYS_PER_WEEK  # 84
    days_since_anchor = (reference_date - cycle_anchor_date).days
    position_in_cycle = days_since_anchor % cycle_total_days
    cycle_start_cont = reference_date - timedelta(days=position_in_cycle)
    cycle_end_cont = _add_days(cycle_start_cont, cycle_total_days - 1)

    weeks_cont, current_week_number_cont = _build_continuous_weeks(
        cycle_start_cont, reference_date
    )

    # Continuous is always active for reference_date within the computed cycle.
    current_week_cont: Optional[int] = (
        current_week_number_cont if current_week_number_cont > 0 else None
    )

    cycle_meta_cont = CycleMetaResponse(
        mode="continuous",
        status="active",
        start_date=cycle_start_cont.isoformat(),
        end_date=cycle_end_cont.isoformat(),
        current_week=current_week_cont,
        total_weeks=CONTINUOUS_CYCLE_LENGTH_WEEKS,
        days_to_race=None,
    )

    return TrainingCycleV2Response(
        reference_date=reference_date.isoformat(),
        goal=goal_response,
        cycle=cycle_meta_cont,
        weeks=weeks_cont,
    )


__all__ = [
    "CycleGoalResponse",
    "CycleMetaResponse",
    "WeekCalendarEntry",
    "TrainingCycleV2Response",
    "build_cycle_calendar_response",
]
