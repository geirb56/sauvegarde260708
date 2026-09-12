"""PR131 — WorkoutGenerator V2: pure deterministic weekly plan builder.

Design rules
------------
- PURE: no MongoDB, no Garmin, no Terra, no LLM, no cache, no global state.
- reference_date must be supplied explicitly by the caller.
- datetime.now() and date.today() are NEVER called inside this module.
- No import of training_engine.
- No import of llm_coach.

Responsibility
--------------
WorkoutGenerator answers ONE question:

    "How should I distribute this week's training target into concrete sessions?"

It does NOT:
  - recalculate the weekly volume target      → WeeklyTarget (#130)
  - apply readiness-based daily modulation    → DailyAdaptation (#133)
  - decide on specific intervals / thresholds → performance.py / thresholds.py
  - compute LT1 / LT2 zones                  → thresholds.py (future)
  - assign heart-rate ranges                 → thresholds.py (future)
  - assign paces                             → thresholds.py / performance.py (future)

Session intensity vocabulary
-----------------------------
rest        — no running, full day off
recovery    — very easy running, active recovery
easy        — easy aerobic (base endurance)
steady      — comfortably steady, upper-easy
quality     — structurally hard / workout session (tempo, threshold, intervals)
              The exact nature is NOT decided here.  One quality max per week (V1).
long_easy   — long run at easy/steady effort
race        — canonical race-day event slot (not training load, never renamed from another type)

Intensity rules (V1)
---------------------
  allow_intensity == False  →  every running session is easy / recovery / long_easy
                                no quality, no steady

  allow_intensity == True   →  at most ONE quality session per week (V1 calibration)
                                one long_easy
                                rest easy / recovery / steady fill

Long run calibration (V1)
--------------------------
All coefficients are centralised here, clearly labelled "calibration V1, recalibrable".

  LONG_RUN_FRACTION      = 0.35  (35 % of weekly target as starting point)
  LONG_RUN_MIN_FRACTION  = 0.20  (floor: never less than 20 % of weekly km)
  LONG_RUN_MAX_FRACTION  = 0.45  (ceiling: never more than 45 % of weekly km)

  Goal-based fractional adjustments (additive to LONG_RUN_FRACTION):
    5k / 10k       : −0.05   (long run is less dominant for speed goals)
    half_marathon  :  0.00   (neutral)
    marathon       : +0.05   (long run is more important)
    ultra          : +0.08
    maintenance    :  0.00

  Absolute cap per goal (km):
    5k             :  8 km
    10k            : 12 km
    half_marathon  : 18 km
    marathon       : 28 km
    ultra          : 35 km
    maintenance    : 15 km

  This cap is applied ONLY when weekly target is high enough to produce a
  disproportionate long run.  For low weekly volumes the fraction cap
  (LONG_RUN_MAX_FRACTION) is the binding constraint, preventing artificially
  large long runs in early / reprise weeks.

No-rounding-drift contract
---------------------------
  distance target  → sum(training session.distance_km) == weekly_target.target_km  (± 0.1 km tolerance)
  duration target  → sum(training session.duration_minutes) == weekly_target.target_duration_minutes

  `race` is an event, not training load, and is therefore EXCLUDED from these
  aggregates. Residual arrondi is applied to the largest training session.

Migration matrix (legacy → V2)
--------------------------------
  generate_cycle_week structure      → build_weekly_plan (V2 general dispatcher)
  build_session                      → _make_prescription (V2 session factory)
  build_reprise_week_structure       → _build_reprise_structure (V2 reprise branch)
  reprise_deep_durations             → WeeklyTarget #130 for total; _split_durations here
  reprise_durations                  → WeeklyTarget #130 for total; _split_durations here
  compute_long_run_km                → _compute_long_run_km (V2 proportional)
  cap_long_run_for_low_volume        → _compute_long_run_km (fraction cap)
  rounding residual correction       → _correct_rounding_drift
  hardcoded HR ranges                → NOT MIGRATED
  hardcoded pace fallbacks           → NOT MIGRATED
  estimated_tss per km               → NOT MIGRATED
  LLM focus/advice                   → NOT MIGRATED (stays in llm_coach as explanation layer)
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .periodization import PeriodizationPhase, PeriodizationSnapshot
from .plan_goal import (
    DISTANCE_10K_KM,
    DISTANCE_5K_KM,
    DISTANCE_HALF_MARATHON_KM,
    DISTANCE_MARATHON_KM,
    GoalType,
    PlanGoal,
)
from .runner_profile import RunnerProfile
from .weekly_target import WeeklyTarget

# ---------------------------------------------------------------------------
# Calibration constants — V1, recalibrable
# ---------------------------------------------------------------------------

# Long run fraction of weekly target (distance basis).
LONG_RUN_FRACTION: float = 0.35
"""Base fraction of weekly km to assign to the long run. Calibration V1."""

LONG_RUN_MIN_FRACTION: float = 0.20
"""Minimum long run as fraction of weekly km. Calibration V1."""

LONG_RUN_MAX_FRACTION: float = 0.45
"""Maximum long run as fraction of weekly km (low-volume protection). Calibration V1."""

# Goal-specific adjustments to LONG_RUN_FRACTION (additive).
_LONG_RUN_GOAL_ADJUST: dict[str, float] = {
    "5k": -0.05,
    "10k": -0.05,
    "half_marathon": 0.00,
    "marathon": +0.05,
    "ultra": +0.08,
    "maintenance": 0.00,
}

# Absolute long run caps per goal (km) — applies only when volume is large.
_LONG_RUN_ABS_CAP: dict[str, float] = {
    "5k": 8.0,
    "10k": 12.0,
    "half_marathon": 18.0,
    "marathon": 28.0,
    "ultra": 35.0,
    "maintenance": 15.0,
}

# Default week skeleton by number of running sessions.
# Format: list of (day_name, session_type) — rest days are explicit.
# Day names follow ISO weekday convention for readability; they may be overridden
# by RunnerProfile constraints in V2.  "quality" slots become "easy" when
# allow_intensity=False.
_WEEK_SKELETONS: dict[int, list[tuple[str, str]]] = {
    1: [
        ("monday", "rest"),
        ("tuesday", "rest"),
        ("wednesday", "rest"),
        ("thursday", "rest"),
        ("friday", "rest"),
        ("saturday", "rest"),
        ("sunday", "long_easy"),
    ],
    2: [
        ("monday", "rest"),
        ("tuesday", "easy"),
        ("wednesday", "rest"),
        ("thursday", "rest"),
        ("friday", "rest"),
        ("saturday", "rest"),
        ("sunday", "long_easy"),
    ],
    3: [
        ("monday", "rest"),
        ("tuesday", "easy"),
        ("wednesday", "rest"),
        ("thursday", "quality"),
        ("friday", "rest"),
        ("saturday", "rest"),
        ("sunday", "long_easy"),
    ],
    4: [
        ("monday", "rest"),
        ("tuesday", "easy"),
        ("wednesday", "rest"),
        ("thursday", "quality"),
        ("friday", "rest"),
        ("saturday", "easy"),
        ("sunday", "long_easy"),
    ],
    5: [
        ("monday", "recovery"),
        ("tuesday", "easy"),
        ("wednesday", "quality"),
        ("thursday", "rest"),
        ("friday", "easy"),
        ("saturday", "rest"),
        ("sunday", "long_easy"),
    ],
    6: [
        ("monday", "recovery"),
        ("tuesday", "easy"),
        ("wednesday", "quality"),
        ("thursday", "recovery"),
        ("friday", "rest"),
        ("saturday", "easy"),
        ("sunday", "long_easy"),
    ],
}

# Relative distance weights per session type for proportional distance allocation.
_SESSION_DISTANCE_WEIGHTS: dict[str, float] = {
    "recovery": 0.70,
    "easy": 1.00,
    "steady": 1.10,
    "quality": 1.00,
    "long_easy": 0.0,  # handled separately
    "race": 0.0,
    "rest": 0.0,
}

# Relative duration weights per session type for proportional duration allocation.
_SESSION_DURATION_WEIGHTS: dict[str, float] = {
    "recovery": 0.65,
    "easy": 1.00,
    "steady": 1.10,
    "quality": 1.10,
    "long_easy": 0.0,  # handled separately
    "race": 0.0,
    "rest": 0.0,
}

# Long run fraction of total duration when target_basis == "duration".
LONG_RUN_DURATION_FRACTION: float = 0.35
"""Fraction of total weekly minutes assigned to the long_easy session. Calibration V1."""

LONG_RUN_DURATION_MIN_FRACTION: float = 0.25
"""Minimum long_easy as fraction of total weekly minutes. Calibration V1."""

LONG_RUN_DURATION_MAX_FRACTION: float = 0.45
"""Maximum long_easy as fraction of total weekly minutes. Calibration V1."""

# deep_reprise duration split fractions (sorted ascending: short, mid, long).
# The TOTAL comes from WeeklyTarget; we just split it here.
_DEEP_REPRISE_SPLIT: tuple[float, float, float] = (0.27, 0.33, 0.40)
"""Proportional split for deep_reprise duration across 3 sessions (ascending).
Matches PR77 session arrays: [30,35,40] → approx 0.29/0.33/0.38 and
[35,45,55] → approx 0.26/0.33/0.41. Calibration V1."""

# Race week: reduce running to 2 easy sessions only (conservative default).
_RACE_WEEK_SESSIONS: int = 2

# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class WorkoutPrescription(BaseModel):
    """Immutable prescription for a single training session.

    Does NOT include:
      - heart rate zones     (→ thresholds.py, future)
      - specific paces       (→ performance.py, future)
      - specific intervals   (→ thresholds.py, future)
    """

    model_config = ConfigDict(frozen=True)

    day: str
    """Day of week name, e.g. 'monday'."""

    workout_type: str
    """Session category: rest | recovery | easy | steady | quality | long_easy | race."""

    intensity_class: str
    """Broad intensity bucket: rest | low | moderate | high | event."""

    distance_km: Optional[float]
    """Distance in km, or None when target_basis is duration and no pace available."""

    duration_minutes: Optional[int]
    """Duration in minutes, or None when target_basis is distance and no pace available."""

    reason_codes: tuple[str, ...]
    """Deterministic language-neutral reason codes for this session."""


class WeeklyPlan(BaseModel):
    """Immutable weekly training plan produced by WorkoutGenerator.

    The sum of TRAINING session distances (when target_basis == "distance")
    equals
    weekly_target.target_km exactly (± 0.1 km), unless an explicit reduction
    reason code removes sessions and their volume from the served week.

    The sum of TRAINING session durations (when target_basis == "duration")
    equals
    weekly_target.target_duration_minutes exactly, unless an explicit reduction
    reason code removes sessions and their duration from the served week.
    """

    model_config = ConfigDict(frozen=True)

    reference_date: date

    target_basis: str
    """Mirrors WeeklyTarget.target_basis: "distance" | "duration"."""

    planned_km: Optional[float]
    """Sum of TRAINING session distances only. None when target_basis == "duration"."""

    planned_duration_minutes: Optional[int]
    """Sum of session durations. None when target_basis == "distance"."""

    session_count: int
    """Number of TRAINING sessions (excludes rest and race)."""

    sessions: tuple[WorkoutPrescription, ...]
    """All seven sessions (running + rest), ordered Monday→Sunday."""

    allow_intensity: bool
    """Mirrors WeeklyTarget.allow_intensity."""

    reason_codes: tuple[str, ...]
    """Diagnostic reason codes for the plan as a whole."""


# ---------------------------------------------------------------------------
# Intensity class helper
# ---------------------------------------------------------------------------

_INTENSITY_CLASS: dict[str, str] = {
    "rest": "rest",
    "recovery": "low",
    "easy": "low",
    "steady": "moderate",
    "quality": "high",
    "long_easy": "low",
    "race": "event",
}


def _intensity_class(workout_type: str) -> str:
    return _INTENSITY_CLASS.get(workout_type, "low")


def _is_training_workout_type(workout_type: str) -> bool:
    return workout_type not in {"rest", "race"}


def _is_training_session(session: WorkoutPrescription) -> bool:
    return _is_training_workout_type(session.workout_type)


def _resolve_target_time_profile(
    plan_goal: PlanGoal,
    *,
    target_capability_time_seconds: Optional[int],
) -> Optional[str]:
    """Classify target-time ambition using equivalent capability time on target distance."""
    if (
        plan_goal.target_time_seconds is None
        or plan_goal.target_time_seconds <= 0
        or target_capability_time_seconds is None
        or target_capability_time_seconds <= 0
    ):
        return None
    if plan_goal.target_time_seconds <= int(target_capability_time_seconds * 0.97):
        return "aggressive"
    if plan_goal.target_time_seconds >= int(target_capability_time_seconds * 1.03):
        return "conservative"
    return None


def _apply_target_time_modulation(
    skeleton: list[tuple[str, str]],
    *,
    target_time_profile: Optional[str],
    allow_intensity: bool,
) -> tuple[list[tuple[str, str]], Optional[str]]:
    # Intentionally conservative: adjust at most one slot per week so target_time
    # influences composition without overriding continuity/phase protection logic.
    if target_time_profile is None or not allow_intensity:
        return skeleton, None

    adjusted = list(skeleton)
    if target_time_profile == "aggressive":
        for idx, (day, slot_type) in enumerate(adjusted):
            if slot_type in ("easy", "recovery"):
                adjusted[idx] = (day, "steady")
                return adjusted, "target_time_profile_aggressive"
    elif target_time_profile == "conservative":
        for idx, (day, slot_type) in enumerate(adjusted):
            if slot_type == "quality":
                adjusted[idx] = (day, "steady")
                return adjusted, "target_time_profile_conservative"
    return skeleton, None


# ---------------------------------------------------------------------------
# Long run computation
# ---------------------------------------------------------------------------

def _compute_long_run_km(
    target_km: float,
    goal_type: str,
) -> float:
    """Compute proportional long run distance for a distance-based week.

    The long run is a fraction of the weekly target, bounded by:
      - LONG_RUN_MIN_FRACTION (floor)
      - LONG_RUN_MAX_FRACTION (ceiling — low volume protection)
      - goal-specific absolute cap (only binding at high volumes)

    No hardcoded goal minimum floors (e.g. 16 km for semi, 28 km for marathon).
    A 20 km weekly target with marathon goal yields ~7 km long run, not 28 km.

    Calibration V1, recalibrable.
    """
    adjust = _LONG_RUN_GOAL_ADJUST.get(goal_type, 0.0)
    fraction = max(
        LONG_RUN_MIN_FRACTION,
        min(LONG_RUN_MAX_FRACTION, LONG_RUN_FRACTION + adjust),
    )
    long_run = round(target_km * fraction, 1)
    # Absolute goal cap — only applied when the fraction itself would exceed it,
    # i.e. only at high weekly volumes.  This prevents marathon runners from
    # getting 40 km long runs while preserving proportionality at low volumes.
    abs_cap = _LONG_RUN_ABS_CAP.get(goal_type, 18.0)
    long_run = min(long_run, abs_cap)
    # Ensure long run never exceeds total weekly target.
    long_run = min(long_run, target_km)
    return round(long_run, 1)


def _compute_long_run_duration(
    total_minutes: int,
    goal_type: str,
) -> int:
    """Compute long_easy session duration (minutes) for a duration-based week."""
    adjust = _LONG_RUN_GOAL_ADJUST.get(goal_type, 0.0)
    fraction = max(
        LONG_RUN_DURATION_MIN_FRACTION,
        min(LONG_RUN_DURATION_MAX_FRACTION, LONG_RUN_DURATION_FRACTION + adjust),
    )
    raw = total_minutes * fraction
    return max(1, int(round(raw)))


# ---------------------------------------------------------------------------
# Duration split helpers (reprise)
# ---------------------------------------------------------------------------

def _split_durations(total_minutes: int, n: int = 3) -> list[int]:
    """Split ``total_minutes`` into ``n`` session durations using the reprise
    proportional split (ascending order: short → mid → long).

    The residual is assigned to the longest session so the sum is exact.
    Calibration V1 (uses _DEEP_REPRISE_SPLIT for n==3, equal split otherwise).
    """
    if n <= 0:
        return []
    if n == 3:
        split = list(_DEEP_REPRISE_SPLIT)
    else:
        unit = 1.0 / n
        split = sorted([unit] * n)
    durations = [max(1, int(total_minutes * s)) for s in split]
    residual = total_minutes - sum(durations)
    durations[-1] += residual  # add to longest session
    return durations


# ---------------------------------------------------------------------------
# Rounding drift correction
# ---------------------------------------------------------------------------

def _correct_rounding_drift_distance(
    sessions: list[WorkoutPrescription],
    target_km: float,
) -> list[WorkoutPrescription]:
    """Adjust the largest training session so sum(distance_km) == target_km.

    Operates on a mutable list; returns a list of rebuilt immutable objects.
    Contract: input sessions already have distance_km rounded to 0.1 km.
    """
    training_sessions = [s for s in sessions if _is_training_session(s) and s.distance_km is not None]
    if not training_sessions:
        return sessions

    current_total = round(sum(s.distance_km for s in training_sessions), 1)
    residual = round(target_km - current_total, 1)
    if abs(residual) < 0.05:  # within acceptable precision
        return sessions

    biggest = max(training_sessions, key=lambda s: s.distance_km)
    new_km = round(biggest.distance_km + residual, 1)

    result = []
    for s in sessions:
        if s is biggest:
            result.append(s.model_copy(update={"distance_km": max(0.1, new_km)}))
        else:
            result.append(s)
    return result


def _correct_rounding_drift_duration(
    sessions: list[WorkoutPrescription],
    target_minutes: int,
) -> list[WorkoutPrescription]:
    """Adjust the largest training session so sum(duration_minutes) == target_minutes."""
    training_sessions = [s for s in sessions if _is_training_session(s) and s.duration_minutes is not None]
    if not training_sessions:
        return sessions

    current_total = sum(s.duration_minutes for s in training_sessions)
    residual = target_minutes - current_total
    if residual == 0:
        return sessions

    biggest = max(training_sessions, key=lambda s: s.duration_minutes)
    new_min = biggest.duration_minutes + residual

    result = []
    for s in sessions:
        if s is biggest:
            result.append(s.model_copy(update={"duration_minutes": max(1, new_min)}))
        else:
            result.append(s)
    return result


def _build_placeholder_skeleton(session_types: list[str]) -> list[tuple[str, str]]:
    return [(f"slot_{index}", workout_type) for index, workout_type in enumerate(session_types)]


def _build_intended_normal_training_sessions(
    *,
    weekly_target: WeeklyTarget,
    session_types: list[str],
    goal_type: str,
    allow_intensity: bool,
) -> list[WorkoutPrescription]:
    skeleton = _build_placeholder_skeleton(session_types)
    if weekly_target.target_basis == "distance" and weekly_target.target_km is not None:
        return _correct_rounding_drift_distance(
            _build_distance_sessions(
                skeleton=skeleton,
                target_km=weekly_target.target_km,
                goal_type=goal_type,
                allow_intensity=allow_intensity,
                base_reason_codes=(),
            ),
            weekly_target.target_km,
        )
    if weekly_target.target_basis == "duration" and weekly_target.target_duration_minutes is not None:
        return _correct_rounding_drift_duration(
            _build_duration_sessions(
                skeleton=skeleton,
                total_minutes=weekly_target.target_duration_minutes,
                goal_type=goal_type,
                allow_intensity=allow_intensity,
                base_reason_codes=(),
            ),
            weekly_target.target_duration_minutes,
        )
    return []


def _build_intended_reprise_training_sessions(
    *,
    weekly_target: WeeklyTarget,
    n_sessions: int,
    allow_run_walk: bool,
    base_reason_codes: tuple[str, ...],
) -> list[WorkoutPrescription]:
    if n_sessions <= 0:
        return []
    if weekly_target.target_basis == "duration" and weekly_target.target_duration_minutes is not None:
        durations = _split_durations(weekly_target.target_duration_minutes, n_sessions)
        min_dur = min(durations) if durations else 0
        run_walk_code = ("run_walk_allowed",) if allow_run_walk else ()
        return [
            _make_running_session(
                day=f"slot_{index}",
                workout_type="recovery" if duration == min_dur else "easy",
                duration_minutes=duration,
                reason_codes=base_reason_codes + run_walk_code,
            )
            for index, duration in enumerate(durations)
        ]

    target_km = weekly_target.target_km or 0.0
    splits_map: dict[int, list[float]] = {
        1: [1.0],
        2: [0.40, 0.60],
        3: [0.28, 0.32, 0.40],
        4: [0.20, 0.25, 0.25, 0.30],
    }
    splits = splits_map.get(n_sessions, splits_map.get(min(n_sessions, 4), [1.0]))
    distances = sorted(round(target_km * split, 1) for split in splits)
    sessions = [
        _make_running_session(
            day=f"slot_{index}",
            workout_type="recovery" if distance == distances[0] else "easy",
            distance_km=distance,
            reason_codes=base_reason_codes,
        )
        for index, distance in enumerate(distances)
    ]
    return _correct_rounding_drift_distance(sessions, target_km)


def _reduce_to_race_week_calendar(
    *,
    intended_training_sessions: list[WorkoutPrescription],
    runner_profile: RunnerProfile,
    race_week: _RaceWeekConfig,
) -> tuple[list[WorkoutPrescription], list[str]]:
    constrained_training_sessions, guard_codes = _build_race_week_training_sessions(
        intended_training_sessions=intended_training_sessions,
        race_week=race_week,
    )
    skeleton, extra_codes = _assign_days(
        [session.workout_type for session in constrained_training_sessions],
        runner_profile,
        allowed_training_days=list(race_week.allowed_training_days_before_race),
        reserved_day_to_type={race_week.race_day: "race"},
        capacity_reason_code="RACE_WEEK_CALENDAR_LIMITED",
    )
    active_slots = [(day, workout_type) for day, workout_type in skeleton if _is_training_workout_type(workout_type)]
    remaining_sessions = list(constrained_training_sessions[:len(active_slots)])
    day_to_session: dict[str, WorkoutPrescription] = {}
    for day, workout_type in active_slots:
        match_index = next(
            index for index, session in enumerate(remaining_sessions) if session.workout_type == workout_type
        )
        matched = remaining_sessions.pop(match_index)
        day_to_session[day] = matched.model_copy(update={"day": day})

    result: list[WorkoutPrescription] = []
    for day in _ALL_DAYS:
        if day == race_week.race_day:
            result.append(_make_race(day, distance_km=race_week.race_distance_km))
        elif day == race_week.race_eve_day:
            result.append(_make_rest(day, reason_codes=("RACE_EVE_REST_RESERVED",)))
        elif day in day_to_session:
            result.append(day_to_session[day])
        else:
            result.append(_make_rest(day))
    return result, _merge_reason_codes(guard_codes, extra_codes)


# ---------------------------------------------------------------------------
# Day slot assignment
# ---------------------------------------------------------------------------

_ALL_DAYS = ("monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday")
_DAY_ORDER: dict[str, int] = {d: i for i, d in enumerate(_ALL_DAYS)}


@dataclass(frozen=True)
class _RaceWeekConfig:
    race_date: date
    race_day: str
    race_distance_km: Optional[float]
    training_days_before_race: tuple[str, ...]
    allowed_training_days_before_race: tuple[str, ...]
    race_eve_day: Optional[str]
    max_pre_race_training_sessions: int


@dataclass(frozen=True)
class _CrossWeekRaceEveConfig:
    race_date: date
    race_eve_day: str


def _resolve_race_distance_km(plan_goal: PlanGoal) -> Optional[float]:
    goal_type = plan_goal.goal_type.value if hasattr(plan_goal.goal_type, "value") else str(plan_goal.goal_type)
    if plan_goal.target_distance_km is not None:
        return plan_goal.target_distance_km
    return {
        GoalType.five_k.value: DISTANCE_5K_KM,
        GoalType.ten_k.value: DISTANCE_10K_KM,
        GoalType.half_marathon.value: DISTANCE_HALF_MARATHON_KM,
        GoalType.marathon.value: DISTANCE_MARATHON_KM,
    }.get(goal_type)


def _resolve_race_week_config(
    *,
    plan_goal: PlanGoal,
    reference_date: date,
) -> Optional[_RaceWeekConfig]:
    race_date = plan_goal.race_date
    if race_date is None:
        return None

    week_start = reference_date - timedelta(days=reference_date.weekday())
    week_end = week_start + timedelta(days=6)
    if not (week_start <= race_date <= week_end):
        return None

    race_day = _ALL_DAYS[race_date.weekday()]
    race_eve_day = _ALL_DAYS[race_date.weekday() - 1] if race_date.weekday() > 0 else None
    training_days_before_race = tuple(
        day for day in _ALL_DAYS if _DAY_ORDER[day] < _DAY_ORDER[race_day]
    )
    allowed_training_days_before_race = tuple(
        day for day in training_days_before_race if day != race_eve_day
    )
    return _RaceWeekConfig(
        race_date=race_date,
        race_day=race_day,
        race_distance_km=_resolve_race_distance_km(plan_goal),
        training_days_before_race=training_days_before_race,
        allowed_training_days_before_race=allowed_training_days_before_race,
        race_eve_day=race_eve_day,
        max_pre_race_training_sessions=min(
            _RACE_WEEK_SESSIONS,
            len(allowed_training_days_before_race),
        ),
    )


def _resolve_cross_week_race_eve_config(
    *,
    plan_goal: PlanGoal,
    reference_date: date,
) -> Optional[_CrossWeekRaceEveConfig]:
    race_date = plan_goal.race_date
    if race_date is None:
        return None

    week_start = reference_date - timedelta(days=reference_date.weekday())
    week_end = week_start + timedelta(days=6)
    if race_date != week_end + timedelta(days=1):
        return None

    return _CrossWeekRaceEveConfig(
        race_date=race_date,
        race_eve_day="sunday",
    )


def _get_skeleton(n: int) -> list[tuple[str, str]]:
    """Return the week skeleton for ``n`` running sessions (clamped to 1–6)."""
    clamped = min(6, max(1, n))
    return _WEEK_SKELETONS[clamped]


def _select_evenly(candidates: list[str], n: int) -> list[str]:
    """Select ``n`` evenly spaced elements from ``candidates`` (preserving order).

    Deterministic: same inputs always produce the same output.
    When n >= len(candidates), returns all candidates.
    When n == 1, returns the last element (preferred end-of-week placement).
    """
    if n <= 0:
        return []
    if n >= len(candidates):
        return list(candidates)
    if n == 1:
        return [candidates[-1]]
    step_f = (len(candidates) - 1) / (n - 1)
    raw_indices = [int(round(i * step_f)) for i in range(n)]
    seen: set[int] = set()
    dedup: list[int] = []
    for idx in raw_indices:
        adj = idx
        while adj in seen and adj < len(candidates) - 1:
            adj += 1
        if adj not in seen:
            seen.add(adj)
            dedup.append(adj)
    if len(dedup) < n:
        for i in range(len(candidates)):
            if i not in seen:
                seen.add(i)
                dedup.append(i)
            if len(dedup) >= n:
                break
    return [candidates[i] for i in sorted(dedup[:n])]


def _merge_reason_codes(*groups: list[str] | tuple[str, ...]) -> list[str]:
    merged: list[str] = []
    for group in groups:
        for code in group:
            if code not in merged:
                merged.append(code)
    return merged


def _constrain_race_week_training_session(session: WorkoutPrescription) -> WorkoutPrescription:
    constrained_type = session.workout_type if session.workout_type in {"easy", "recovery"} else "easy"
    if constrained_type == session.workout_type:
        return session
    return session.model_copy(
        update={
            "workout_type": constrained_type,
            "intensity_class": _intensity_class(constrained_type),
            "reason_codes": _merge_reason_codes(
                session.reason_codes,
                ("RACE_WEEK_PRE_EVENT_GUARD",),
            ),
        }
    )


def _build_race_week_training_sessions(
    *,
    intended_training_sessions: list[WorkoutPrescription],
    race_week: _RaceWeekConfig,
) -> tuple[list[WorkoutPrescription], list[str]]:
    constrained = [
        _constrain_race_week_training_session(session)
        for session in intended_training_sessions
    ]
    kept = constrained[:race_week.max_pre_race_training_sessions]
    codes = ["RACE_WEEK_PRE_EVENT_GUARD"]
    if race_week.race_eve_day is not None:
        codes.append("RACE_EVE_REST_RESERVED")
    if len(constrained) > len(kept):
        codes.extend(["RACE_WEEK_SESSION_CAP", "RACE_WEEK_CALENDAR_LIMITED"])
    return kept, codes


def _apply_cross_week_race_eve_guard(
    *,
    sessions: list[WorkoutPrescription],
    cross_week_race_eve: Optional[_CrossWeekRaceEveConfig],
) -> tuple[list[WorkoutPrescription], list[str]]:
    if cross_week_race_eve is None:
        return sessions, []

    guarded_sessions: list[WorkoutPrescription] = []
    changed = False
    for session in sessions:
        if session.day == cross_week_race_eve.race_eve_day:
            guarded_sessions.append(
                _make_rest(cross_week_race_eve.race_eve_day, reason_codes=("RACE_EVE_REST_RESERVED",))
            )
            changed = True
        else:
            guarded_sessions.append(session)

    return guarded_sessions, (["RACE_EVE_REST_RESERVED"] if changed else [])


def _assign_days(
    session_slots: list[str],  # ordered session types to fill (no rest)
    runner_profile: RunnerProfile,
    *,
    allowed_training_days: Optional[list[str]] = None,
    reserved_day_to_type: Optional[dict[str, str]] = None,
    capacity_reason_code: str = "SCHEDULE_CONSTRAINT_LIMITED",
) -> tuple[list[tuple[str, str]], list[str]]:
    """Assign session types to days, respecting RunnerProfile constraints.

    Returns ([(day, workout_type), ...] for all 7 days, extra_reason_codes).

    Strategy
    --------
    1. Treat availability_constraints items that exactly match a day name
       (monday…sunday) as unavailable days.  All 7 days minus those form
       the candidate pool — max_days_per_week does NOT reduce this pool.
    2. Apply max_days_per_week as a CAP on the SESSION COUNT (n) only.
    3. Select ``n`` days from the full candidate pool with maximum even spacing.
    4. Honour preferred_long_run_day: if set, available, and the week contains
       a long_easy session, pin long_easy to that day and distribute the
       remaining sessions evenly.
    5. Avoid placing quality on the calendar day immediately before long_easy
       when another arrangement is possible.
    6. If constraints make it impossible to fit all sessions, emit
       SCHEDULE_CONSTRAINT_LIMITED and use the best available days.
    """
    n = len(session_slots)
    extra_reason_codes: list[str] = []
    reserved_day_to_type = {
        str(day).strip().lower(): str(workout_type).strip().lower()
        for day, workout_type in (reserved_day_to_type or {}).items()
        if str(day).strip().lower() in set(_ALL_DAYS)
    }
    reserved_days = set(reserved_day_to_type)

    # --- parse unavailable days (V1 contract: exact day-name match only) ----
    unavailable: set[str] = {
        c.lower() for c in runner_profile.availability_constraints
        if c.lower() in set(_ALL_DAYS)
    }

    # --- full candidate pool (7 days minus unavailable) ---------------------
    # max_days_per_week does NOT reduce this pool; it caps n instead.
    allowed_training_day_set = (
        {
            d.strip().lower()
            for d in allowed_training_days
            if isinstance(d, str) and d.strip().lower() in set(_ALL_DAYS)
        }
        if allowed_training_days is not None
        else None
    )
    candidates: list[str] = [
        d for d in _ALL_DAYS
        if d not in unavailable
        and d not in reserved_days
        and (allowed_training_day_set is None or d in allowed_training_day_set)
    ]

    # --- max_days_per_week: cap on SESSION COUNT, not on candidate days -----
    max_days = runner_profile.max_days_per_week
    if max_days is not None and n > max_days:
        n = max_days
        session_slots = list(session_slots[:n])

    # --- check feasibility --------------------------------------------------
    if n > len(candidates):
        extra_reason_codes.append(capacity_reason_code)
        n = len(candidates)
        session_slots = list(session_slots[:n])

    if n == 0:
        return [(d, reserved_day_to_type.get(d, "rest")) for d in _ALL_DAYS], extra_reason_codes

    # --- preferred_long_run_day ---------------------------------------------
    # If the week contains long_easy and the runner has a valid preferred day
    # that is not unavailable, pin long_easy to that day.
    has_long_easy = "long_easy" in session_slots
    pref_long_day: Optional[str] = None
    if has_long_easy and runner_profile.preferred_long_run_day:
        pref = runner_profile.preferred_long_run_day.strip().lower()
        if pref in candidates:
            pref_long_day = pref

    # --- select n days ------------------------------------------------------
    if n >= len(candidates):
        selected: list[str] = list(candidates)
    elif pref_long_day is not None:
        # Pin pref_long_day; select n-1 others evenly from remaining candidates.
        remaining = [d for d in candidates if d != pref_long_day]
        others = _select_evenly(remaining, n - 1)
        selected = sorted(others + [pref_long_day], key=lambda d: _DAY_ORDER[d])
    else:
        selected = _select_evenly(candidates, n)

    # --- determine long_easy day --------------------------------------------
    long_easy_day: Optional[str] = None
    if has_long_easy:
        long_easy_day = pref_long_day if pref_long_day is not None else selected[-1]

    # --- build non-long slot assignment -------------------------------------
    non_long_days = [d for d in selected if d != long_easy_day]
    non_long_slots: list[str] = [s for s in session_slots if s != "long_easy"]

    # Quality adjacency rule: avoid quality on the calendar day immediately
    # before long_easy_day when another arrangement is possible.
    if long_easy_day is not None and len(non_long_days) >= 2 and "quality" in non_long_slots:
        long_pos = _DAY_ORDER[long_easy_day]
        days_before_long = [d for d in non_long_days if _DAY_ORDER[d] < long_pos]
        if days_before_long:
            adjacent_day = max(days_before_long, key=lambda d: _DAY_ORDER[d])
            adj_idx = non_long_days.index(adjacent_day)
            if non_long_slots[adj_idx] == "quality":
                for i in range(len(non_long_slots)):
                    if i != adj_idx and non_long_slots[i] not in ("quality", "long_easy"):
                        non_long_slots[i], non_long_slots[adj_idx] = (
                            non_long_slots[adj_idx],
                            non_long_slots[i],
                        )
                        break

    # --- build final day-to-type mapping ------------------------------------
    day_to_type: dict[str, str] = {}
    if long_easy_day is not None:
        day_to_type[long_easy_day] = "long_easy"
    for day, slot in zip(non_long_days, non_long_slots):
        day_to_type[day] = slot

    result: list[tuple[str, str]] = [
        (d, reserved_day_to_type.get(d, day_to_type.get(d, "rest"))) for d in _ALL_DAYS
    ]
    return result, extra_reason_codes


def _order_session_slots(slots: list[str]) -> list[str]:
    """Order session types for day assignment (legacy helper, kept for reference).

    Rules (applied in order):
    1. long_easy is placed last (furthest in the week — typically Sunday).
    2. quality is not placed immediately before long_easy when another
       position is available (avoids quality→long_easy back-to-back).

    Note: _assign_days implements the canonical ordering logic directly.
    This function is retained for use in potential future callers.
    """
    if not slots:
        return slots

    # Put long_easy at end.
    if "long_easy" in slots:
        slots.remove("long_easy")
        slots.append("long_easy")

    # If quality would be second-to-last (immediately before long_easy), move it
    # to an earlier position when a non-quality/non-long_easy slot exists there.
    if len(slots) >= 3 and slots[-2] == "quality":
        for i in range(len(slots) - 2):
            if slots[i] not in ("quality", "long_easy"):
                slots[i], slots[-2] = slots[-2], slots[i]
                break

    return slots


# ---------------------------------------------------------------------------
# Session factory
# ---------------------------------------------------------------------------

def _make_rest(day: str, reason_codes: tuple[str, ...] = ()) -> WorkoutPrescription:
    return WorkoutPrescription(
        day=day,
        workout_type="rest",
        intensity_class="rest",
        distance_km=None,
        duration_minutes=None,
        reason_codes=reason_codes,
    )


def _make_race(
    day: str,
    *,
    distance_km: Optional[float],
    reason_codes: tuple[str, ...] = ("RACE_DAY_RESERVED",),
) -> WorkoutPrescription:
    return WorkoutPrescription(
        day=day,
        workout_type="race",
        intensity_class="event",
        distance_km=distance_km,
        duration_minutes=None,
        reason_codes=reason_codes,
    )


def _make_running_session(
    day: str,
    workout_type: str,
    distance_km: Optional[float] = None,
    duration_minutes: Optional[int] = None,
    reason_codes: tuple[str, ...] = (),
) -> WorkoutPrescription:
    return WorkoutPrescription(
        day=day,
        workout_type=workout_type,
        intensity_class=_intensity_class(workout_type),
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        reason_codes=reason_codes,
    )


# ---------------------------------------------------------------------------
# Structure resolvers (by continuity state)
# ---------------------------------------------------------------------------

def _apply_intensity_rule(workout_type: str, allow_intensity: bool, quality_used: bool) -> tuple[str, bool]:
    """Downgrade a quality slot to easy if intensity is not allowed or already used.
    Returns (resolved_type, quality_used_updated)."""
    if workout_type in ("quality", "steady") and not allow_intensity:
        return "easy", quality_used
    if workout_type == "quality" and allow_intensity:
        if quality_used:
            return "easy", quality_used
        return "quality", True
    return workout_type, quality_used


def _build_distance_sessions(
    skeleton: list[tuple[str, str]],
    target_km: float,
    goal_type: str,
    allow_intensity: bool,
    base_reason_codes: tuple[str, ...],
    race_distance_km: Optional[float] = None,
) -> list[WorkoutPrescription]:
    """Build sessions for a distance-based week from a skeleton."""
    long_run_km = _compute_long_run_km(target_km, goal_type)
    running_slots = [(d, t) for d, t in skeleton if _is_training_workout_type(t)]
    has_long = any(t == "long_easy" for _, t in running_slots)
    long_km = long_run_km if has_long else 0.0
    remaining_km = max(0.0, target_km - long_km)

    work_slots = [(d, t) for d, t in running_slots if t != "long_easy"]
    weight_sum = sum(_SESSION_DISTANCE_WEIGHTS.get(t, 1.0) for _, t in work_slots) or 1.0

    quality_used = False
    sessions: list[WorkoutPrescription] = []

    for day, slot_type in skeleton:
        if slot_type == "rest":
            sessions.append(_make_rest(day))
            continue
        if slot_type == "race":
            sessions.append(_make_race(day, distance_km=race_distance_km))
            continue

        resolved, quality_used = _apply_intensity_rule(slot_type, allow_intensity, quality_used)

        if resolved == "long_easy":
            km = round(long_km, 1)
            sessions.append(_make_running_session(
                day, "long_easy",
                distance_km=km,
                reason_codes=base_reason_codes,
            ))
        else:
            w = _SESSION_DISTANCE_WEIGHTS.get(resolved, 1.0)
            km = round(remaining_km * (w / weight_sum), 1)
            sessions.append(_make_running_session(
                day, resolved,
                distance_km=km,
                reason_codes=base_reason_codes,
            ))

    return sessions


def _build_duration_sessions(
    skeleton: list[tuple[str, str]],
    total_minutes: int,
    goal_type: str,
    allow_intensity: bool,
    base_reason_codes: tuple[str, ...],
    race_distance_km: Optional[float] = None,
) -> list[WorkoutPrescription]:
    """Build sessions for a duration-based week from a skeleton."""
    long_run_minutes = _compute_long_run_duration(total_minutes, goal_type)
    running_slots = [(d, t) for d, t in skeleton if _is_training_workout_type(t)]
    has_long = any(t == "long_easy" for _, t in running_slots)
    long_min = long_run_minutes if has_long else 0
    remaining_min = max(0, total_minutes - long_min)

    work_slots = [(d, t) for d, t in running_slots if t != "long_easy"]
    weight_sum = sum(_SESSION_DURATION_WEIGHTS.get(t, 1.0) for _, t in work_slots) or 1.0

    quality_used = False
    sessions: list[WorkoutPrescription] = []

    for day, slot_type in skeleton:
        if slot_type == "rest":
            sessions.append(_make_rest(day))
            continue
        if slot_type == "race":
            sessions.append(_make_race(day, distance_km=race_distance_km))
            continue

        resolved, quality_used = _apply_intensity_rule(slot_type, allow_intensity, quality_used)

        if resolved == "long_easy":
            sessions.append(_make_running_session(
                day, "long_easy",
                duration_minutes=long_min,
                reason_codes=base_reason_codes,
            ))
        else:
            w = _SESSION_DURATION_WEIGHTS.get(resolved, 1.0)
            mins = max(1, int(round(remaining_min * (w / weight_sum))))
            sessions.append(_make_running_session(
                day, resolved,
                duration_minutes=mins,
                reason_codes=base_reason_codes,
            ))

    return sessions


def _build_reprise_sessions_duration(
    total_minutes: int,
    n_sessions: int,
    allow_run_walk: bool,
    base_reason_codes: tuple[str, ...],
    runner_profile: RunnerProfile,
    race_week: Optional[_RaceWeekConfig] = None,
) -> tuple[list[WorkoutPrescription], list[str]]:
    """Build a reprise (deep_reprise / partial_reprise) duration-based week.

    - easy-only (recovery / easy)
    - run/walk noted in reason_codes when allow_run_walk=True
    - day placement delegates to _assign_days() so that availability_constraints
      and max_days_per_week are respected for ALL reprise branches
    - no quality, no long_easy distinction (all sessions are "easy" or "recovery")

    Returns (sessions, extra_reason_codes).
    """
    # Cap at domain maximum for reprise (4 sessions).
    n = min(n_sessions, 4)

    # Delegate day selection to the common scheduler.
    # Reprise sessions are all "easy" from a scheduling perspective.
    slots = ["easy"] * n
    if race_week is not None:
        skeleton, extra_codes = _assign_days(
            slots,
            runner_profile,
            allowed_training_days=list(race_week.training_days_before_race),
            reserved_day_to_type={race_week.race_day: "race"},
            capacity_reason_code="RACE_WEEK_CALENDAR_LIMITED",
        )
    else:
        skeleton, extra_codes = _assign_days(slots, runner_profile)
    active_days = [d for d, t in skeleton if _is_training_workout_type(t)]
    actual_n = len(active_days)  # may be < n if constraints further reduced it

    # Split durations using the actual session count after constraint application.
    durations = _split_durations(total_minutes, actual_n)
    durations_sorted = sorted(durations)  # ascending: shorter sessions earlier in week

    # Map day → duration (short durations to early days, longest to last)
    day_to_dur = dict(zip(active_days, durations_sorted))

    run_walk_code = ("run_walk_allowed",) if allow_run_walk else ()
    min_dur = min(durations_sorted) if durations_sorted else 0

    sessions: list[WorkoutPrescription] = []
    skeleton_map = dict(skeleton)
    for day in _ALL_DAYS:
        if skeleton_map.get(day) == "race":
            sessions.append(_make_race(day, distance_km=race_week.race_distance_km if race_week else None))
        elif day not in day_to_dur:
            sessions.append(_make_rest(day))
        else:
            dur = day_to_dur[day]
            sessions.append(_make_running_session(
                day, "recovery" if dur == min_dur else "easy",
                duration_minutes=dur,
                reason_codes=base_reason_codes + run_walk_code,
            ))

    return sessions, extra_codes


def _build_reprise_sessions_distance(
    target_km: float,
    n_sessions: int,
    base_reason_codes: tuple[str, ...],
    runner_profile: RunnerProfile,
    race_week: Optional[_RaceWeekConfig] = None,
) -> tuple[list[WorkoutPrescription], list[str]]:
    """Build a partial_reprise distance-based week: easy-only, no quality.

    Day placement delegates to _assign_days() so that availability_constraints
    and max_days_per_week are respected for ALL reprise branches.

    Returns (sessions, extra_reason_codes).
    """
    splits_map: dict[int, list[float]] = {
        1: [1.0],
        2: [0.40, 0.60],
        3: [0.28, 0.32, 0.40],
        4: [0.20, 0.25, 0.25, 0.30],
    }
    # Cap at domain maximum for reprise (4 sessions).
    n = min(n_sessions, 4)

    # Delegate day selection to the common scheduler.
    slots = ["easy"] * n
    if race_week is not None:
        skeleton, extra_codes = _assign_days(
            slots,
            runner_profile,
            allowed_training_days=list(race_week.training_days_before_race),
            reserved_day_to_type={race_week.race_day: "race"},
            capacity_reason_code="RACE_WEEK_CALENDAR_LIMITED",
        )
    else:
        skeleton, extra_codes = _assign_days(slots, runner_profile)
    active_days = [d for d, t in skeleton if _is_training_workout_type(t)]
    actual_n = len(active_days)  # may be < n if constraints further reduced it

    splits = splits_map.get(actual_n, splits_map.get(min(actual_n, 4), [1.0]))

    # Distances sorted ascending, assigned to days in week order (ascending)
    distances_sorted = sorted(round(target_km * s, 1) for s in splits)
    day_to_km = dict(zip(active_days, distances_sorted))
    min_km = min(distances_sorted) if distances_sorted else 0.0

    sessions: list[WorkoutPrescription] = []
    skeleton_map = dict(skeleton)
    for day in _ALL_DAYS:
        if skeleton_map.get(day) == "race":
            sessions.append(_make_race(day, distance_km=race_week.race_distance_km if race_week else None))
        elif day not in day_to_km:
            sessions.append(_make_rest(day))
        else:
            km = day_to_km[day]
            sessions.append(_make_running_session(
                day, "recovery" if km == min_km else "easy",
                distance_km=km,
                reason_codes=base_reason_codes,
            ))

    return sessions, extra_codes


# ---------------------------------------------------------------------------
# Phase modulation
# ---------------------------------------------------------------------------

def _apply_phase_modulation(
    skeleton: list[tuple[str, str]],
    phase: PeriodizationPhase,
    allow_intensity: bool,
) -> list[tuple[str, str]]:
    """Apply lightweight structural modulation based on periodization phase.

    WeeklyTarget has already modulated the VOLUME.  Here we only modulate
    the SESSION COMPOSITION (types), not the total.
    """
    if phase in (PeriodizationPhase.taper, PeriodizationPhase.consolidation):
        # Downgrade quality to easy during taper/consolidation
        return [
            (d, "easy" if t == "quality" else t)
            for d, t in skeleton
        ]
    if phase == PeriodizationPhase.race:
        # Conservative: 2-session easy week regardless of incoming session count.
        return _WEEK_SKELETONS[_RACE_WEEK_SESSIONS]
    return skeleton


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

def build_weekly_plan(
    *,
    weekly_target: WeeklyTarget,
    runner_profile: RunnerProfile,
    plan_goal: PlanGoal,
    periodization: PeriodizationSnapshot,
    reference_date: date,
    target_capability_time_seconds: Optional[int] = None,
) -> WeeklyPlan:
    """Build an immutable WeeklyPlan from explicit V2 inputs.

    Parameters
    ----------
    weekly_target:
        Immutable weekly training prescription from WeeklyTarget V2 (#130).
    runner_profile:
        Immutable runner profile from RunnerProfile V2 (PR07).
    plan_goal:
        Immutable plan goal from PlanGoal V2 (PR05).
    periodization:
        Immutable periodization snapshot from Periodization V2 (PR06).
    reference_date:
        The Monday of the week being planned (supplied explicitly; never today()).

    Returns
    -------
    WeeklyPlan
        Immutable weekly plan.  session_count == weekly_target.target_sessions
        (unless an explicit reason code explains a deviation).
    """
    # --- basic parameters ---------------------------------------------------
    target_basis = weekly_target.target_basis
    allow_intensity = weekly_target.allow_intensity
    n_sessions = weekly_target.target_sessions
    continuity = weekly_target.continuity_state
    goal_type = plan_goal.goal_type.value if hasattr(plan_goal.goal_type, "value") else str(plan_goal.goal_type)
    phase = periodization.phase
    race_week = _resolve_race_week_config(plan_goal=plan_goal, reference_date=reference_date)
    cross_week_race_eve = _resolve_cross_week_race_eve_config(
        plan_goal=plan_goal,
        reference_date=reference_date,
    )

    reason_codes: list[str] = list(weekly_target.reason_codes)
    if race_week is not None:
        reason_codes.append("RACE_DAY_RESERVED")
    target_time_profile = _resolve_target_time_profile(
        plan_goal,
        target_capability_time_seconds=target_capability_time_seconds,
    )

    # --- route by continuity state -----------------------------------------
    if continuity in ("no_history", "deep_reprise"):
        sessions, reason_codes = _route_reprise_deep(
            weekly_target, n_sessions, allow_intensity, goal_type, reason_codes, runner_profile, race_week
        )

    elif continuity == "partial_reprise":
        sessions, reason_codes = _route_partial_reprise(
            weekly_target, n_sessions, goal_type, reason_codes, runner_profile, race_week
        )

    else:
        # reprise_exit or normal
        skeleton = _get_skeleton(n_sessions)
        skeleton = _apply_phase_modulation(skeleton, phase, allow_intensity)
        if (
            target_basis == "distance"
            and continuity == "normal"
            and phase in (PeriodizationPhase.base, PeriodizationPhase.build, PeriodizationPhase.specific)
        ):
            skeleton, target_time_reason = _apply_target_time_modulation(
                skeleton,
                target_time_profile=target_time_profile,
                allow_intensity=allow_intensity,
            )
            if target_time_reason:
                reason_codes.append(target_time_reason)
        session_types = [t for _, t in skeleton if t != "rest"]
        if race_week is not None:
            intended_training_sessions = _build_intended_normal_training_sessions(
                weekly_target=weekly_target,
                session_types=session_types,
                goal_type=goal_type,
                allow_intensity=allow_intensity,
            )
            sessions, constraint_codes = _reduce_to_race_week_calendar(
                intended_training_sessions=intended_training_sessions,
                runner_profile=runner_profile,
                race_week=race_week,
            )
            reason_codes = list(reason_codes) + constraint_codes
        else:
            skeleton, constraint_codes = _assign_days(session_types, runner_profile)
            reason_codes = list(reason_codes) + constraint_codes
            sessions, reason_codes = _route_normal(
                weekly_target, skeleton, goal_type, allow_intensity, reason_codes, phase,
                race_distance_km=None,
            )

    sessions, cross_week_codes = _apply_cross_week_race_eve_guard(
        sessions=sessions,
        cross_week_race_eve=cross_week_race_eve,
    )
    reason_codes = _merge_reason_codes(reason_codes, cross_week_codes)

    # --- ensure immutability of session list --------------------------------
    immutable_sessions = tuple(sessions)

    # --- compute plan totals ------------------------------------------------
    training_sessions = [s for s in immutable_sessions if _is_training_session(s)]
    session_count = len(training_sessions)

    if target_basis == "distance":
        planned_km = round(
            sum(s.distance_km for s in training_sessions if s.distance_km is not None), 1
        )
        planned_duration_minutes = None
    else:
        planned_km = None
        planned_duration_minutes = sum(
            s.duration_minutes for s in training_sessions if s.duration_minutes is not None
        )

    return WeeklyPlan(
        reference_date=reference_date,
        target_basis=target_basis,
        planned_km=planned_km,
        planned_duration_minutes=planned_duration_minutes,
        session_count=session_count,
        sessions=immutable_sessions,
        allow_intensity=allow_intensity,
        reason_codes=tuple(reason_codes),
    )


# ---------------------------------------------------------------------------
# Routing helpers
# ---------------------------------------------------------------------------

def _route_reprise_deep(
    weekly_target: WeeklyTarget,
    n_sessions: int,
    allow_intensity: bool,
    goal_type: str,
    reason_codes: list[str],
    runner_profile: RunnerProfile,
    race_week: Optional[_RaceWeekConfig] = None,
) -> tuple[list[WorkoutPrescription], list[str]]:
    """Route for deep_reprise / no_history: duration-based, easy-only, run/walk allowed."""
    reason_codes = list(reason_codes)
    reason_codes.append("generator_route_deep_reprise")

    if weekly_target.target_basis == "duration" and weekly_target.target_duration_minutes:
        total_minutes = weekly_target.target_duration_minutes
        capped_sessions = min(n_sessions, 3)
        if race_week is not None:
            intended_training_sessions = _build_intended_reprise_training_sessions(
                weekly_target=weekly_target,
                n_sessions=capped_sessions,
                allow_run_walk=True,
                base_reason_codes=("reprise_easy_only",),
            )
            sessions, constraint_codes = _reduce_to_race_week_calendar(
                intended_training_sessions=intended_training_sessions,
                runner_profile=runner_profile,
                race_week=race_week,
            )
        else:
            sessions, constraint_codes = _build_reprise_sessions_duration(
                total_minutes=total_minutes,
                n_sessions=capped_sessions,
                allow_run_walk=True,
                base_reason_codes=("reprise_easy_only",),
                runner_profile=runner_profile,
                race_week=None,
            )
            sessions = _correct_rounding_drift_duration(sessions, total_minutes)
        reason_codes = reason_codes + constraint_codes
    else:
        # Fallback: distance-based easy-only (no_history with distance target)
        target_km = weekly_target.target_km or 0.0
        capped_sessions = min(n_sessions, 3)
        if race_week is not None:
            intended_training_sessions = _build_intended_reprise_training_sessions(
                weekly_target=weekly_target,
                n_sessions=capped_sessions,
                allow_run_walk=False,
                base_reason_codes=("reprise_easy_only",),
            )
            sessions, constraint_codes = _reduce_to_race_week_calendar(
                intended_training_sessions=intended_training_sessions,
                runner_profile=runner_profile,
                race_week=race_week,
            )
        else:
            sessions, constraint_codes = _build_reprise_sessions_distance(
                target_km=target_km,
                n_sessions=capped_sessions,
                base_reason_codes=("reprise_easy_only",),
                runner_profile=runner_profile,
                race_week=None,
            )
            sessions = _correct_rounding_drift_distance(sessions, target_km)
        reason_codes = reason_codes + constraint_codes

    return sessions, reason_codes


def _route_partial_reprise(
    weekly_target: WeeklyTarget,
    n_sessions: int,
    goal_type: str,
    reason_codes: list[str],
    runner_profile: RunnerProfile,
    race_week: Optional[_RaceWeekConfig] = None,
) -> tuple[list[WorkoutPrescription], list[str]]:
    """Route for partial_reprise: easy-only, distance or duration."""
    reason_codes = list(reason_codes)
    reason_codes.append("generator_route_partial_reprise")

    if weekly_target.target_basis == "duration" and weekly_target.target_duration_minutes:
        total_minutes = weekly_target.target_duration_minutes
        capped_sessions = min(n_sessions, 4)
        if race_week is not None:
            intended_training_sessions = _build_intended_reprise_training_sessions(
                weekly_target=weekly_target,
                n_sessions=capped_sessions,
                allow_run_walk=False,
                base_reason_codes=("reprise_easy_only",),
            )
            sessions, constraint_codes = _reduce_to_race_week_calendar(
                intended_training_sessions=intended_training_sessions,
                runner_profile=runner_profile,
                race_week=race_week,
            )
        else:
            sessions, constraint_codes = _build_reprise_sessions_duration(
                total_minutes=total_minutes,
                n_sessions=capped_sessions,
                allow_run_walk=False,
                base_reason_codes=("reprise_easy_only",),
                runner_profile=runner_profile,
                race_week=None,
            )
            sessions = _correct_rounding_drift_duration(sessions, total_minutes)
        reason_codes = reason_codes + constraint_codes
    else:
        target_km = weekly_target.target_km or 0.0
        capped_sessions = min(n_sessions, 4)
        if race_week is not None:
            intended_training_sessions = _build_intended_reprise_training_sessions(
                weekly_target=weekly_target,
                n_sessions=capped_sessions,
                allow_run_walk=False,
                base_reason_codes=("reprise_easy_only",),
            )
            sessions, constraint_codes = _reduce_to_race_week_calendar(
                intended_training_sessions=intended_training_sessions,
                runner_profile=runner_profile,
                race_week=race_week,
            )
        else:
            sessions, constraint_codes = _build_reprise_sessions_distance(
                target_km=target_km,
                n_sessions=capped_sessions,
                base_reason_codes=("reprise_easy_only",),
                runner_profile=runner_profile,
                race_week=None,
            )
            sessions = _correct_rounding_drift_distance(sessions, target_km)
        reason_codes = reason_codes + constraint_codes

    return sessions, reason_codes


def _route_normal(
    weekly_target: WeeklyTarget,
    skeleton: list[tuple[str, str]],
    goal_type: str,
    allow_intensity: bool,
    reason_codes: list[str],
    phase: PeriodizationPhase,
    race_distance_km: Optional[float] = None,
) -> tuple[list[WorkoutPrescription], list[str]]:
    """Route for reprise_exit / normal weeks."""
    reason_codes = list(reason_codes)
    reason_codes.append("generator_route_normal")

    if phase == PeriodizationPhase.race:
        reason_codes.append("race_week_conservative")

    if weekly_target.target_basis == "distance" and weekly_target.target_km is not None:
        target_km = weekly_target.target_km
        sessions = _build_distance_sessions(
            skeleton=skeleton,
            target_km=target_km,
            goal_type=goal_type,
            allow_intensity=allow_intensity,
            base_reason_codes=(),
            race_distance_km=race_distance_km,
        )
        sessions = _correct_rounding_drift_distance(sessions, target_km)

    elif weekly_target.target_basis == "duration" and weekly_target.target_duration_minutes is not None:
        total_minutes = weekly_target.target_duration_minutes
        sessions = _build_duration_sessions(
            skeleton=skeleton,
            total_minutes=total_minutes,
            goal_type=goal_type,
            allow_intensity=allow_intensity,
            base_reason_codes=(),
            race_distance_km=race_distance_km,
        )
        sessions = _correct_rounding_drift_duration(sessions, total_minutes)
    else:
        # No target available — return rest week with reason code
        reason_codes.append("no_target_available_rest_week")
        sessions = [_make_rest(d) for d in _ALL_DAYS]

    return sessions, reason_codes


# ---------------------------------------------------------------------------
# Public exports
# ---------------------------------------------------------------------------

__all__ = [
    "WorkoutPrescription",
    "WeeklyPlan",
    "build_weekly_plan",
    # Calibration constants (testable)
    "LONG_RUN_FRACTION",
    "LONG_RUN_MIN_FRACTION",
    "LONG_RUN_MAX_FRACTION",
    "LONG_RUN_DURATION_FRACTION",
]
