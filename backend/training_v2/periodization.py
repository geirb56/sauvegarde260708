"""PR06 — Periodization: pure deterministic periodization layer for RunIndex V2.

Design rules
------------
- PURE: no MongoDB, no Garmin calls, no API calls, no LLM, no cache,
  no global mutable state, no datetime.now(), no date.today().
- All dates must be injected by the caller.
- Periodization describes WHERE the runner stands in their training cycle.
- Periodization does NOT decide volume, sessions, workouts, pace, or intensity.
- No imports from training_engine, training_load_engine, llm_coach,
  coach_service.

Principle
---------
"Periodization décrit le calendrier d'entraînement.
 Elle ne décide pas encore de la charge ni des séances."

Modes
-----
  race_calendar : PlanGoal.race_date is set and goal_type in {5k, 10k,
                  half_marathon, marathon, ultra}.
  continuous    : maintenance, or any race goal without a race_date.

Phases — race_calendar
-----------------------
  base | build | specific | taper | race

Phases — continuous (cycling)
------------------------------
  base | build | consolidation

Taper durations (weeks) — CENTRALISED HERE
-------------------------------------------
  5k             → 1
  10k            → 1
  half_marathon  → 2
  marathon       → 2
  ultra          → 2

Pre-taper proportions — CENTRALISED HERE
-----------------------------------------
  base      = 30 %
  build     = 40 %
  specific  = 30 %

Continuous cycle — CENTRALISED HERE
-------------------------------------
  total = 12 weeks
  base  = 4 weeks
  build = 5 weeks
  consolidation = 3 weeks

Phase computation (race_calendar)
-----------------------------------
  Phase boundaries are calculated from race_plan_start_date to race_date.
  race_plan_start_date is injected by the caller — never invented internally.
  If not provided, reference_date is used (= "plan starts today" semantics).

  Proportions are applied to total pre-taper days:
    pre_taper_days = (race_date - plan_start_date).days - taper_days
    base_days      = floor(pre_taper_days × 0.30)
    build_days     = floor(pre_taper_days × 0.40)
    specific_days  = pre_taper_days − base_days − build_days

  Phase schedule (absolute dates, no day lost, no day double-counted):
    [plan_start, plan_start + base_days - 1]           → base
    [plan_start + base_days, ... + build_days - 1]     → build
    [plan_start + base_days + build_days, ...]          → specific
    [race_date - taper_days, race_date - 1]            → taper
    [race_date]                                         → race

  Short preparations are handled by dropping phases from the start
  (furthest from the race first).

Reason codes (stable, language-neutral)
----------------------------------------
  RACE_CALENDAR
  CONTINUOUS_CYCLE
  PHASE_BASE
  PHASE_BUILD
  PHASE_SPECIFIC
  PHASE_TAPER
  PHASE_RACE
  PHASE_CONSOLIDATION
  RACE_DATE_PASSED
  SHORT_PREPARATION
  NO_RACE_DATE
  MAINTENANCE_GOAL
"""

from __future__ import annotations

import math
from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .plan_goal import GoalType, PlanGoal
from .training_state import TrainingState

# ---------------------------------------------------------------------------
# Constants — single source of truth
# ---------------------------------------------------------------------------

# Taper duration in whole weeks, by race goal type.
TAPER_WEEKS: dict[GoalType, int] = {
    GoalType.five_k: 1,
    GoalType.ten_k: 1,
    GoalType.half_marathon: 2,
    GoalType.marathon: 2,
    GoalType.ultra: 2,
}

# Proportions (must sum to 1.0) applied to the pre-taper window.
PRE_TAPER_PROPORTIONS: dict[str, float] = {
    "base": 0.30,
    "build": 0.40,
    "specific": 0.30,
}

# Continuous cycle lengths in weeks.
CONTINUOUS_CYCLE_LENGTH_WEEKS: int = 12
CONTINUOUS_BASE_WEEKS: int = 4
CONTINUOUS_BUILD_WEEKS: int = 5
CONTINUOUS_CONSOLIDATION_WEEKS: int = 3  # = 12 - 4 - 5

assert (
    CONTINUOUS_BASE_WEEKS + CONTINUOUS_BUILD_WEEKS + CONTINUOUS_CONSOLIDATION_WEEKS
    == CONTINUOUS_CYCLE_LENGTH_WEEKS
), "Continuous cycle lengths must sum to CONTINUOUS_CYCLE_LENGTH_WEEKS"

# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class PeriodizationPhase(str, Enum):
    base = "base"
    build = "build"
    specific = "specific"
    taper = "taper"
    race = "race"
    consolidation = "consolidation"


class PeriodizationMode(str, Enum):
    race_calendar = "race_calendar"
    continuous = "continuous"


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


class PeriodizationSnapshot(BaseModel):
    """Immutable snapshot of the runner's position in their training cycle."""

    model_config = ConfigDict(frozen=True)

    reference_date: date

    phase: PeriodizationPhase
    mode: PeriodizationMode

    weeks_to_race: Optional[float]

    phase_start_date: Optional[date]
    phase_end_date: Optional[date]

    cycle_week: Optional[int]          # 1-based position in current phase
    cycle_length_weeks: Optional[int]  # total weeks in current phase

    reason_codes: tuple[str, ...]      # immutable sequence


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

_DAYS_PER_WEEK: float = 7.0


def _days_to_weeks(days: int) -> float:
    """Convert whole days to fractional weeks."""
    return days / _DAYS_PER_WEEK


def _add_days(d: date, days: int) -> date:
    return date.fromordinal(d.toordinal() + days)


# ---------------------------------------------------------------------------
# Pre-taper phase schedule (deterministic, no lost days)
# ---------------------------------------------------------------------------

def _build_race_phase_schedule(
    plan_start: date,
    race_date: date,
    taper_weeks: int,
) -> list[tuple[PeriodizationPhase, date, date]]:
    """Return an ordered list of (phase, start, end) covering plan_start..race_date.

    The taper has a fixed duration.  The remainder is split proportionally
    among base / build / specific with floor-rounding; specific absorbs
    the remainder so no day is lost.

    Short preparations: if there are fewer days than the full schedule,
    phases closest to the race take priority (race > taper > specific >
    build > base).

    Returns list ordered base → build → specific → taper → race.
    """
    total_days = (race_date - plan_start).days   # ≥ 0 guaranteed by caller

    taper_days = taper_weeks * 7
    # Clamp taper to total_days (can't taper beyond what's available)
    actual_taper_days = min(taper_days, total_days)
    pre_taper_days = max(0, total_days - actual_taper_days)

    # Proportional split for the pre-taper window.
    base_days = math.floor(pre_taper_days * PRE_TAPER_PROPORTIONS["base"])
    build_days = math.floor(pre_taper_days * PRE_TAPER_PROPORTIONS["build"])
    specific_days = pre_taper_days - base_days - build_days  # exact remainder

    # Build raw phase (phase, length_days) in priority order from race.
    raw: list[tuple[PeriodizationPhase, int]] = [
        (PeriodizationPhase.base, base_days),
        (PeriodizationPhase.build, build_days),
        (PeriodizationPhase.specific, specific_days),
        (PeriodizationPhase.taper, actual_taper_days),
    ]

    result: list[tuple[PeriodizationPhase, date, date]] = []
    cursor = plan_start
    for phase, days in raw:
        if days <= 0:
            continue
        ph_start = cursor
        ph_end = _add_days(cursor, days - 1)
        result.append((phase, ph_start, ph_end))
        cursor = _add_days(ph_end, 1)

    # Race phase = the race_date itself (always appended last)
    result.append((PeriodizationPhase.race, race_date, race_date))

    return result


# ---------------------------------------------------------------------------
# Race-calendar mode
# ---------------------------------------------------------------------------

def _compute_race_calendar(
    plan_goal: PlanGoal,
    reference_date: date,
    plan_start: date,
) -> PeriodizationSnapshot:
    race_date: date = plan_goal.race_date  # type: ignore[assignment]
    taper_weeks = TAPER_WEEKS[plan_goal.goal_type]
    taper_days = taper_weeks * 7

    reason_codes: list[str] = ["RACE_CALENDAR"]

    # --- Race passed ---
    if reference_date > race_date:
        return PeriodizationSnapshot(
            reference_date=reference_date,
            phase=PeriodizationPhase.consolidation,
            mode=PeriodizationMode.continuous,
            weeks_to_race=None,
            phase_start_date=None,
            phase_end_date=None,
            cycle_week=None,
            cycle_length_weeks=None,
            reason_codes=("RACE_DATE_PASSED", "CONTINUOUS_CYCLE", "PHASE_CONSOLIDATION"),
        )

    days_to_race = (race_date - reference_date).days
    weeks_to_race = round(days_to_race / _DAYS_PER_WEEK, 4)

    # --- Race day ---
    if days_to_race == 0:
        return PeriodizationSnapshot(
            reference_date=reference_date,
            phase=PeriodizationPhase.race,
            mode=PeriodizationMode.race_calendar,
            weeks_to_race=0.0,
            phase_start_date=race_date,
            phase_end_date=race_date,
            cycle_week=1,
            cycle_length_weeks=1,
            reason_codes=("RACE_CALENDAR", "PHASE_RACE"),
        )

    # Build absolute phase schedule from plan_start
    schedule = _build_race_phase_schedule(plan_start, race_date, taper_weeks)

    # Find which phase contains reference_date
    current: Optional[tuple[PeriodizationPhase, date, date]] = None
    for ph, ph_start, ph_end in schedule:
        if ph == PeriodizationPhase.race:
            continue  # race_date handled above
        if ph_start <= reference_date <= ph_end:
            current = (ph, ph_start, ph_end)
            break

    if current is None:
        # reference_date is before plan_start (edge case) → treat as base start
        # or after last non-race phase → should not happen, but fall back to taper
        # Find taper entry or last non-race phase
        for ph, ph_start, ph_end in reversed(schedule):
            if ph != PeriodizationPhase.race:
                current = (ph, ph_start, ph_end)
                break
        if current is None:
            current = schedule[0][:3] if schedule else (PeriodizationPhase.base, plan_start, plan_start)

    phase, ph_start, ph_end = current
    phase_days = (ph_end - ph_start).days + 1
    day_in_phase = (reference_date - ph_start).days  # 0-based
    cycle_week = day_in_phase // 7 + 1
    cycle_length_weeks = max(1, math.ceil(phase_days / 7))

    reason_codes.append(f"PHASE_{phase.value.upper()}")

    if days_to_race < taper_days + 7:
        reason_codes.append("SHORT_PREPARATION")

    return PeriodizationSnapshot(
        reference_date=reference_date,
        phase=phase,
        mode=PeriodizationMode.race_calendar,
        weeks_to_race=weeks_to_race,
        phase_start_date=ph_start,
        phase_end_date=ph_end,
        cycle_week=cycle_week,
        cycle_length_weeks=cycle_length_weeks,
        reason_codes=tuple(reason_codes),
    )


# ---------------------------------------------------------------------------
# Continuous mode
# ---------------------------------------------------------------------------

def _compute_continuous(
    plan_goal: PlanGoal,
    reference_date: date,
    cycle_anchor_date: date,
) -> PeriodizationSnapshot:
    """Compute a continuous cycling snapshot.

    The cycle repeats: base (4w) → build (5w) → consolidation (3w) → ...

    cycle_anchor_date is the explicit origin for determinism.
    """
    reason_codes: list[str] = ["CONTINUOUS_CYCLE"]

    if plan_goal.goal_type == GoalType.maintenance:
        reason_codes.append("MAINTENANCE_GOAL")
    elif plan_goal.race_date is None:
        reason_codes.append("NO_RACE_DATE")

    days_since_anchor = (reference_date - cycle_anchor_date).days

    # Handle anchor in the future (be robust)
    if days_since_anchor < 0:
        days_since_anchor = (-days_since_anchor) % (CONTINUOUS_CYCLE_LENGTH_WEEKS * 7)

    cycle_total_days = CONTINUOUS_CYCLE_LENGTH_WEEKS * 7
    position_in_cycle = days_since_anchor % cycle_total_days

    # Cumulative boundaries (in days)
    base_end = CONTINUOUS_BASE_WEEKS * 7            # 28
    build_end = base_end + CONTINUOUS_BUILD_WEEKS * 7  # 63
    # consolidation: 63..83 (12*7=84, last day index = 83)

    if position_in_cycle < base_end:
        phase = PeriodizationPhase.base
        phase_day = position_in_cycle
        phase_length_days = CONTINUOUS_BASE_WEEKS * 7
        reason_codes.append("PHASE_BASE")
    elif position_in_cycle < build_end:
        phase = PeriodizationPhase.build
        phase_day = position_in_cycle - base_end
        phase_length_days = CONTINUOUS_BUILD_WEEKS * 7
        reason_codes.append("PHASE_BUILD")
    else:
        phase = PeriodizationPhase.consolidation
        phase_day = position_in_cycle - build_end
        phase_length_days = CONTINUOUS_CONSOLIDATION_WEEKS * 7
        reason_codes.append("PHASE_CONSOLIDATION")

    cycle_week = phase_day // 7 + 1
    cycle_length_weeks = phase_length_days // 7

    # Compute phase start/end absolute dates
    # Cycle starts at the most recent multiple of cycle_total_days from anchor
    cycle_start = _add_days(cycle_anchor_date, days_since_anchor - position_in_cycle)
    if position_in_cycle < base_end:
        phase_start = cycle_start
        phase_end = _add_days(cycle_start, base_end - 1)
    elif position_in_cycle < build_end:
        phase_start = _add_days(cycle_start, base_end)
        phase_end = _add_days(cycle_start, build_end - 1)
    else:
        phase_start = _add_days(cycle_start, build_end)
        phase_end = _add_days(cycle_start, cycle_total_days - 1)

    return PeriodizationSnapshot(
        reference_date=reference_date,
        phase=phase,
        mode=PeriodizationMode.continuous,
        weeks_to_race=None,
        phase_start_date=phase_start,
        phase_end_date=phase_end,
        cycle_week=cycle_week,
        cycle_length_weeks=cycle_length_weeks,
        reason_codes=tuple(reason_codes),
    )


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def build_periodization(
    plan_goal: PlanGoal,
    reference_date: date,
    *,
    training_state: Optional[TrainingState] = None,
    cycle_anchor_date: Optional[date] = None,
    race_plan_start_date: Optional[date] = None,
) -> PeriodizationSnapshot:
    """Compute a deterministic PeriodizationSnapshot.

    Parameters
    ----------
    plan_goal:
        The runner's current goal (from PR05).
    reference_date:
        The date for which the snapshot is computed. Must be supplied by
        the caller — never inferred from datetime.now() or date.today().
    training_state:
        Optional TrainingState (from PR04).  It is accepted but NEVER used
        to modify the calendar phase.  Continuity / load state belong to
        the prescription layer (PR07+).
    cycle_anchor_date:
        Required when mode is continuous.  The explicit origin of the
        repeating cycle.  Never invented internally.
    race_plan_start_date:
        Optional start date for race_calendar mode.  When provided, phase
        boundaries are computed from this date to race_date.  When absent,
        reference_date is used as the plan start ("plan starts today").
        Must be <= reference_date <= race_date to be meaningful.

    Returns
    -------
    PeriodizationSnapshot
        Immutable snapshot.
    """
    _race_goals = {
        GoalType.five_k,
        GoalType.ten_k,
        GoalType.half_marathon,
        GoalType.marathon,
        GoalType.ultra,
    }

    has_race_date = (
        plan_goal.race_date is not None
        and plan_goal.goal_type in _race_goals
    )

    if has_race_date:
        plan_start = race_plan_start_date if race_plan_start_date is not None else reference_date
        return _compute_race_calendar(plan_goal, reference_date, plan_start)

    # Continuous mode: cycle_anchor_date must be provided.
    if cycle_anchor_date is None:
        raise ValueError(
            "cycle_anchor_date is required when mode=continuous "
            "(plan_goal has no race_date).  Never invent an anchor date internally."
        )

    return _compute_continuous(plan_goal, reference_date, cycle_anchor_date)
