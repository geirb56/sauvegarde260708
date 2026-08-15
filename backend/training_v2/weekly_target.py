"""PR130 — WeeklyTarget V2: pure deterministic weekly training prescription layer.

Design rules
------------
- PURE: no MongoDB, no Garmin, no Terra, no LLM, no cache, no global state.
- reference_date must be supplied explicitly by the caller.
- datetime.now() and date.today() are NEVER called inside this module.
- No import of training_engine.

Responsibility
--------------
WeeklyTarget answers ONE question:

    "What training load can this runner reasonably be prescribed this week?"

It produces a WEEKLY TARGET (total volume or total duration).
It does NOT produce:
  - individual session structures  → WorkoutGenerator #131
  - long run km                    → WorkoutGenerator #131
  - paces / zones / intervals      → WorkoutGenerator #131
  - rounding between sessions      → WorkoutGenerator #131
  - readiness-based daily modulation → DailyAdaptation #133

Reprise engine (PR77 non-regression contract)
----------------------------------------------
The V2 implementation preserves all PR77 protection principles:

  1. deep_reprise is duration-based (no km prescription).
  2. A formerly-trained runner is distinguishable from a true beginner/unknown
     via prior_running_window (observed data only, never invented).
  3. Progression depends on activity actually tolerated, not the calendar.
  4. partial_reprise stays easy-only (allow_intensity=False).
  5. reprise_exit: volume HELD, intensity may resume ONLY when a reliable
     volume baseline exists — NEVER both grow simultaneously, and NEVER
     intensity without an exploitable baseline (UNKNOWN BASELINE → NO INTENSITY RETURN).
  6. Brutal overload is damped: a spike week does not become the new baseline.
  7. S1 → S2 → S3 does not collapse.

Calibration
-----------
All numeric calibration constants are centralised here and clearly labelled
"calibration V1, recalibrable" — they are product decisions, not physiological laws.

Prior fitness thresholds:
  PRIOR_TRAINED_KM_FLOOR = 15.0   km/week equivalent (lower bound of "trained")
  PRIOR_TRAINED_KM_TOP   = 40.0   km/week equivalent (upper bound for interpolation)

Deep reprise weekly durations (minutes) — calibration V1, recalibrable:
  DEEP_REPRISE_WEEKLY_MINUTES_FLOOR   = 105  (true beginner / unknown; = sum [30,35,40])
  DEEP_REPRISE_WEEKLY_MINUTES_TRAINED = 135  (former trained runner; = sum [35,45,55])

  The actual weekly target is linearly interpolated between FLOOR and TRAINED
  based on prior_weekly_km_equivalent.

Reprise progression multiplier:
  REPRISE_PROGRESSION_FACTOR = 1.12  (+12 %/tolerated active week, PR77 value, capped at +60 %)

Normal progression:
  NORMAL_MAX_PROGRESSION = 1.10  (+10 % max per week, calibration V1)

Phase volume multipliers (V2 phases only — deload / intensification phases
from the legacy are not in V2):
  base          = 1.00
  build         = 1.00
  specific      = 1.00
  taper         = 0.50
  race          = 0.30
  consolidation = 0.85

Target sessions:
  Uses preferred_days_per_week → max_days_per_week → typical_runs_per_week.
  In no_history / deep_reprise: capped at REPRISE_MAX_SESSIONS (3) to preserve
  PR77 "simple comeback" principle.

Protections reserved for #131
------------------------------
  - Long run cap / proportionality (→ WorkoutGenerator).
  - Easy-only session enforcement (→ WorkoutGenerator: allow_intensity=False is the signal).
  - Run/walk in deep_reprise (→ WorkoutGenerator).
  - Rounding drift correction (→ WorkoutGenerator).
  - NO_ROUNDING_DRIFT: sum(sessions) must equal weekly target exactly.

Migration matrix (legacy → V2)
--------------------------------
  classify_training_state       → TrainingState V2 (already migrated)
  resolve_chronic_base          → WeeklyTarget._resolve_base / RunnerProfile.typical_weekly_km
  apply_resume_guard            → WeeklyTarget._apply_resume_guard (migrated here)
  resolve_reprise_plan          → WeeklyTarget.build_weekly_target
  reprise_deep_durations        → WeeklyTarget (weekly total); WorkoutGenerator #131 (per-session split)
  reprise_durations             → WeeklyTarget (weekly progression); WorkoutGenerator #131
  build_reprise_week_structure  → WorkoutGenerator #131
  compute_long_run_km           → WorkoutGenerator #131
  cap_long_run_for_low_volume   → WorkoutGenerator #131
  rounding residual correction  → WorkoutGenerator #131
  recovery_red_flag             → NOT migrated here; future DailyAdaptation / Readiness if needed
  DEFAULT_WEEKLY_KM             → REMOVED CONCEPTUALLY — no fictitious floor in V2
  GOAL minimum weekly volume    → NOT migrated as hard floor — goal does not invent a baseline
"""

from __future__ import annotations

from datetime import date
from typing import Optional

from pydantic import BaseModel, ConfigDict

from .plan_goal import PlanGoal
from .periodization import PeriodizationSnapshot, PeriodizationPhase
from .runner_profile import RunnerProfile
from .training_history import TrainingHistory
from .training_state import TrainingState

# ---------------------------------------------------------------------------
# Calibration constants — V1, recalibrable
# ---------------------------------------------------------------------------

# Prior fitness thresholds (km/week equivalent from prior_running_window).
PRIOR_TRAINED_KM_FLOOR: float = 15.0
"""Below this weekly km equivalent, the runner is treated as beginner/unknown."""

PRIOR_TRAINED_KM_TOP: float = 40.0
"""At or above this weekly km equivalent, the runner is treated as fully trained."""

# Deep reprise weekly target (total minutes for the week) — calibration V1.
# Source: PR77 REPRISE_DEEP_SESSION_MINUTES = [30, 35, 40] → sum = 105 → ~90 conservative
#         PR77 REPRISE_DEEP_SESSION_MINUTES_TRAINED = [35, 45, 55] → sum = 135
# Using sum of session arrays as weekly totals, matching PR77 runtime constants.
DEEP_REPRISE_WEEKLY_MINUTES_FLOOR: int = 105
"""Weekly duration target (min) for deep_reprise — true beginner / unknown.
Corresponds to sum of PR77 REPRISE_DEEP_SESSION_MINUTES = [30, 35, 40].
Calibration V1, recalibrable."""
DEEP_REPRISE_WEEKLY_MINUTES_TRAINED: int = 135
"""Weekly duration target (min) for deep_reprise — former trained runner.
Corresponds to sum of PR77 REPRISE_DEEP_SESSION_MINUTES_TRAINED = [35, 45, 55].
Calibration V1, recalibrable."""

# Reprise progression multiplier per tolerated active week.
REPRISE_PROGRESSION_FACTOR: float = 1.12
"""Weekly duration grows by +12 % per already-completed active week (PR77 value).
Calibration V1, recalibrable. Capped at REPRISE_PROGRESSION_CAP."""

REPRISE_PROGRESSION_CAP: float = 1.60
"""Maximum cumulative growth factor relative to the deep-reprise baseline (+60 %)."""

REPRISE_PROGRESSION_FACTOR_PER_WEEK: float = REPRISE_PROGRESSION_FACTOR - 1.0
"""Incremental growth per active week (= 0.12 from PR77). Derived from REPRISE_PROGRESSION_FACTOR."""

# Normal weekly progression cap.
NORMAL_MAX_PROGRESSION: float = 1.10
"""Maximum weekly volume increase for normal state (+10 %). Calibration V1."""

# Phase volume multipliers (V2 phases only).
PHASE_VOLUME_MULTIPLIERS: dict[str, float] = {
    "base": 1.00,
    "build": 1.00,
    "specific": 1.00,
    "taper": 0.50,
    "race": 0.30,
    "consolidation": 0.85,
}
"""Phase multipliers applied to the weekly target (V2 phases).
deload / intensification phases from the legacy are not in V2.
Calibration V1, recalibrable.
Invariant enforced: taper < build/specific."""

# Session count caps.
REPRISE_MAX_SESSIONS: int = 3
"""Maximum sessions prescribed in no_history / deep_reprise (PR77 principle: simple comeback)."""

# Resume guard: if the last week was a spike, don't amplify it further.
RESUME_GUARD_RATIO: float = 1.05
"""When recent weekly km > chronic baseline, cap the increase to +5 % of chronic."""

# Partial reprise: minimum duration target if no baseline available.
PARTIAL_REPRISE_FALLBACK_WEEKLY_MINUTES: int = 120
"""Weekly duration fallback for partial_reprise when no distance baseline is available."""

# Partial reprise distance progression when baseline is available.
PARTIAL_REPRISE_DISTANCE_FACTOR: float = 1.10
"""Prudent progression factor for partial_reprise with an observable baseline."""

# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


class WeeklyTarget(BaseModel):
    """Immutable weekly training prescription.

    Answers: "What training load can this runner be prescribed this week?"

    Does NOT prescribe:
      - individual session structure
      - long run km
      - pace / zone / workout type
      - intervals
    These belong to WorkoutGenerator (#131).
    """

    model_config = ConfigDict(frozen=True)

    reference_date: date

    target_basis: str
    """How the target is expressed: "duration" | "distance"."""

    target_km: Optional[float]
    """Total weekly distance target (km). None when target_basis == "duration"."""

    target_duration_minutes: Optional[int]
    """Total weekly duration target (minutes). None when target_basis == "distance"."""

    target_sessions: int
    """Recommended number of running sessions this week."""

    allow_intensity: bool
    """When False: easy / recovery sessions only (WorkoutGenerator must honour this)."""

    confidence: str
    """Overall confidence in this prescription: "none" | "low" | "medium" | "high"."""

    continuity_state: str
    """Explicit continuity state from TrainingState.

    Values: no_history | deep_reprise | partial_reprise | reprise_exit | normal

    This is the single source of truth for WorkoutGenerator routing.
    WorkoutGenerator MUST use this field directly and MUST NOT derive the
    continuity state by inspecting reason_codes.

    Architectural decision (permanent):
      reason_codes are diagnostic / explanatory artefacts only.
      They MUST NOT be used as a hidden business-state transport.
    """

    reason_codes: tuple[str, ...]
    """Deterministic, language-neutral diagnostic codes."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _phase_multiplier(phase: PeriodizationPhase) -> float:
    """Return the volume multiplier for the current periodization phase."""
    return PHASE_VOLUME_MULTIPLIERS.get(phase.value, 1.00)


def _clamp_sessions(
    runner_profile: RunnerProfile,
    continuity_state: str,
) -> int:
    """Return the target session count, respecting constraints."""
    # Priority: preferred_days_per_week > max_days_per_week > typical_runs_per_week
    base: Optional[float] = (
        runner_profile.preferred_days_per_week
        or runner_profile.max_days_per_week
        or runner_profile.typical_runs_per_week
    )
    sessions = int(round(base)) if base is not None else 3

    # In no_history / deep_reprise: cap to REPRISE_MAX_SESSIONS (PR77 principle).
    if continuity_state in ("no_history", "deep_reprise"):
        sessions = min(sessions, REPRISE_MAX_SESSIONS)

    # Never zero sessions.
    sessions = max(1, sessions)

    # Never exceed max_days_per_week if set.
    if runner_profile.max_days_per_week is not None:
        sessions = min(sessions, runner_profile.max_days_per_week)

    return sessions


def _prior_weekly_km(training_history: TrainingHistory) -> float:
    """Return the prior weekly km equivalent from the pre-stop window.

    Returns 0.0 if no prior running activity was observed.
    This value is ONLY from observed activities — never invented.
    """
    pw = training_history.prior_running_window
    if not pw.has_activity:
        return 0.0
    return pw.weekly_km_equivalent


def _interpolate_deep_reprise_minutes(prior_km: float) -> int:
    """Interpolate weekly duration target between FLOOR and TRAINED.

    - prior_km <= PRIOR_TRAINED_KM_FLOOR  → FLOOR
    - prior_km >= PRIOR_TRAINED_KM_TOP    → TRAINED
    - in between: linear interpolation

    This preserves the PR77 distinction between beginner/unknown and
    former trained runner, using ONLY observed prior_running_window data.
    """
    if prior_km <= PRIOR_TRAINED_KM_FLOOR:
        return DEEP_REPRISE_WEEKLY_MINUTES_FLOOR
    if prior_km >= PRIOR_TRAINED_KM_TOP:
        return DEEP_REPRISE_WEEKLY_MINUTES_TRAINED
    frac = (prior_km - PRIOR_TRAINED_KM_FLOOR) / (PRIOR_TRAINED_KM_TOP - PRIOR_TRAINED_KM_FLOOR)
    interpolated = DEEP_REPRISE_WEEKLY_MINUTES_FLOOR + frac * (
        DEEP_REPRISE_WEEKLY_MINUTES_TRAINED - DEEP_REPRISE_WEEKLY_MINUTES_FLOOR
    )
    return int(round(interpolated))


def _active_weeks_from_28d(training_history: TrainingHistory) -> int:
    """Return the number of truly active weeks in the last 28 days.

    Uses ``weekly_distance_buckets_28d`` to count weeks with non-zero running
    distance — no approximation needed.  Bounded [0, 4].
    """
    return sum(1 for km in training_history.weekly_distance_buckets_28d if km > 0)


def _apply_resume_guard(
    proposed_km: float,
    recent_7d_km: float,
    chronic_base_km: float,
) -> float:
    """Cap the weekly target if recent volume spiked above chronic base.

    If the most recent 7-day km is well above the chronic base (a spike),
    we do not use the spike as the new baseline for progression.
    Instead: cap the target at chronic_base * NORMAL_MAX_PROGRESSION.

    This preserves PR77's "abrupt overload is damped" protection.

    Guard only activates when chronic_base is substantial (>= 5 km/week).
    When history is very sparse, the apparent "spike" is just normal comeback
    running against a diluted 30d average — not a genuine overload.
    """
    if chronic_base_km <= 0:
        return proposed_km
    # Only guard against genuine spikes: chronic must be ≥ 5 km/week.
    _GUARD_MIN_CHRONIC = 5.0
    if chronic_base_km < _GUARD_MIN_CHRONIC:
        return proposed_km
    if recent_7d_km > chronic_base_km * 1.30:
        # Spike detected: build from chronic, not from the spike.
        return min(proposed_km, chronic_base_km * NORMAL_MAX_PROGRESSION)
    return proposed_km


def _recent_weekly_km(training_history: TrainingHistory) -> Optional[float]:
    """Return the recent 7-day km if any activity was recorded."""
    w7 = training_history.window_7d
    if w7.activity_count > 0 and w7.distance_km > 0:
        return w7.distance_km
    return None


def _chronic_base_km(runner_profile: RunnerProfile, training_history: TrainingHistory) -> Optional[float]:
    """Return the chronic baseline km using the active-weeks principle from PR77.

    Priority:
    1. Mean of truly active weeks from ``weekly_distance_buckets_28d``
       (non-zero buckets only — the exact PR77 principle without approximation).
    2. runner_profile.typical_weekly_km when is_observed=True (for the case
       where 28d is empty but RunnerProfile has a derived value from 90d fallback).
    3. None.

    Why active_weeks instead of calendar weeks:
       An athlete who ran 3 sessions last week but nothing before has a real
       weekly base of ~10 km — not 10/4 = 2.5 km (which is what dividing by
       the full 4-week window would give).

    active_weeks: count of non-zero distance buckets in weekly_distance_buckets_28d
    (exact, no approximation).  Bounded below at 1 when distance is present.
    """
    buckets = training_history.weekly_distance_buckets_28d
    active_buckets = [km for km in buckets if km > 0]
    if active_buckets:
        return sum(active_buckets) / float(len(active_buckets))

    # 28d window empty: fall back to RunnerProfile (may be from 90d window).
    if runner_profile.typical_weekly_km_is_observed and runner_profile.typical_weekly_km is not None:
        return runner_profile.typical_weekly_km

    return None


# ---------------------------------------------------------------------------
# State-specific target builders
# ---------------------------------------------------------------------------


def _target_no_history(
    runner_profile: RunnerProfile,
    training_history: TrainingHistory,
    periodization: PeriodizationSnapshot,
    reason_codes: list[str],
) -> tuple[str, Optional[float], Optional[int]]:
    """Build target for no_history state.

    Returns (target_basis, target_km, target_duration_minutes).
    """
    reason_codes.append("NO_HISTORY_DURATION_BASED")
    # No prior data at all: use the most conservative duration calibration.
    # Phase modulation is ignored for no_history (always floor).
    minutes = DEEP_REPRISE_WEEKLY_MINUTES_FLOOR
    return "duration", None, minutes


def _target_deep_reprise(
    runner_profile: RunnerProfile,
    training_history: TrainingHistory,
    periodization: PeriodizationSnapshot,
    reason_codes: list[str],
) -> tuple[str, Optional[float], Optional[int]]:
    """Build target for deep_reprise state.

    Distinguishes former trained runner from beginner/unknown using
    prior_running_window (observed data only).
    """
    prior_km = _prior_weekly_km(training_history)
    minutes = _interpolate_deep_reprise_minutes(prior_km)

    if prior_km > PRIOR_TRAINED_KM_FLOOR:
        reason_codes.append("DEEP_REPRISE_PRIOR_TRAINED")
    else:
        reason_codes.append("DEEP_REPRISE_PRIOR_UNKNOWN")

    # Active weeks so far in the comeback (0 for first week back).
    active_weeks = _active_weeks_from_28d(training_history)
    if active_weeks > 0:
        factor = min(REPRISE_PROGRESSION_CAP, 1.0 + REPRISE_PROGRESSION_FACTOR_PER_WEEK * active_weeks)
        minutes = int(round(minutes * factor))
        reason_codes.append("DEEP_REPRISE_PROGRESSING")

    return "duration", None, minutes


def _target_partial_reprise(
    runner_profile: RunnerProfile,
    training_history: TrainingHistory,
    periodization: PeriodizationSnapshot,
    reason_codes: list[str],
) -> tuple[str, Optional[float], Optional[int]]:
    """Build target for partial_reprise state."""
    chronic = _chronic_base_km(runner_profile, training_history)
    recent = _recent_weekly_km(training_history)

    if chronic is not None and chronic > 0 and recent is not None and recent > 0:
        # Distance-based with prudent progression from actual recent volume.
        # Use recent (not chronic) as starting point to avoid overreaching.
        base = min(recent, chronic)
        proposed = base * PARTIAL_REPRISE_DISTANCE_FACTOR
        proposed = _apply_resume_guard(proposed, recent, chronic)
        proposed = proposed * _phase_multiplier(periodization.phase)
        target_km = round(proposed, 1)
        reason_codes.append("PARTIAL_REPRISE_DISTANCE_BASED")
        return "distance", target_km, None
    else:
        # No reliable baseline: duration-based fallback.
        minutes = PARTIAL_REPRISE_FALLBACK_WEEKLY_MINUTES
        reason_codes.append("PARTIAL_REPRISE_DURATION_FALLBACK")
        return "duration", None, minutes


def _target_reprise_exit(
    runner_profile: RunnerProfile,
    training_history: TrainingHistory,
    periodization: PeriodizationSnapshot,
    reason_codes: list[str],
) -> tuple[str, Optional[float], Optional[int]]:
    """Build target for reprise_exit state.

    Volume HOLD: do not increase volume when intensity resumes.
    Returns ("distance", km, None) when a baseline is exploitable, or
    ("duration", None, minutes) when no baseline exists.
    The caller must derive allow_intensity from the returned target_basis:
    True only when target_basis == "distance".
    """
    chronic = _chronic_base_km(runner_profile, training_history)
    recent = _recent_weekly_km(training_history)

    if chronic is not None and chronic > 0:
        # HOLD: apply phase multiplier to chronic base, no progression.
        target_km = round(chronic * _phase_multiplier(periodization.phase), 1)
        reason_codes.append("REPRISE_EXIT_VOLUME_HOLD")
        return "distance", target_km, None
    elif recent is not None and recent > 0:
        # No chronic observable: hold at recent level.
        target_km = round(recent * _phase_multiplier(periodization.phase), 1)
        reason_codes.append("REPRISE_EXIT_HOLD_RECENT")
        return "distance", target_km, None
    else:
        # No baseline available: duration-based fallback, no invented km floor.
        reason_codes.append("REPRISE_EXIT_HOLD_FALLBACK")
        return "duration", None, PARTIAL_REPRISE_FALLBACK_WEEKLY_MINUTES


def _target_normal(
    runner_profile: RunnerProfile,
    training_history: TrainingHistory,
    plan_goal: PlanGoal,
    periodization: PeriodizationSnapshot,
    reason_codes: list[str],
) -> tuple[str, Optional[float], Optional[int]]:
    """Build target for normal state."""
    chronic = _chronic_base_km(runner_profile, training_history)
    recent = _recent_weekly_km(training_history)

    if chronic is None or chronic <= 0:
        # No reliable baseline: cannot invent a floor.
        # Use recent if available, else duration fallback.
        if recent is not None and recent > 0:
            chronic = recent
            reason_codes.append("NORMAL_BASELINE_FROM_RECENT")
        else:
            reason_codes.append("NORMAL_NO_BASELINE_DURATION_FALLBACK")
            return "duration", None, PARTIAL_REPRISE_FALLBACK_WEEKLY_MINUTES

    # Progression from chronic base.
    proposed = chronic * NORMAL_MAX_PROGRESSION

    # Apply resume guard against spikes.
    if recent is not None:
        proposed = _apply_resume_guard(proposed, recent, chronic)

    # Apply phase multiplier.
    proposed = proposed * _phase_multiplier(periodization.phase)

    target_km = round(proposed, 1)
    reason_codes.append("NORMAL_DISTANCE_BASED")
    return "distance", target_km, None

# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def build_weekly_target(
    *,
    runner_profile: RunnerProfile,
    training_history: TrainingHistory,
    training_state: TrainingState,
    plan_goal: PlanGoal,
    periodization: PeriodizationSnapshot,
    reference_date: date,
) -> WeeklyTarget:
    """Build an immutable WeeklyTarget from explicit V2 inputs.

    Pure function: no I/O, no Mongo, no Garmin, no Terra, no LLM,
    no cache, no datetime.now(), no date.today(), no training_engine import.

    Parameters
    ----------
    runner_profile:
        Athlete profile combining observed and declared data.
    training_history:
        Observed running history windows including prior_running_window.
    training_state:
        Current two-axis training state (continuity + load).
    plan_goal:
        Athlete's training goal (intent only, not a volume floor).
    periodization:
        Current periodization phase snapshot.
    reference_date:
        Anchor date — must be supplied explicitly by the caller.
    """
    reason_codes: list[str] = []
    continuity = training_state.continuity_state

    # ── Volume target ──────────────────────────────────────────────────────
    if continuity == "no_history":
        target_basis, target_km, target_minutes = _target_no_history(
            runner_profile, training_history, periodization, reason_codes
        )

    elif continuity == "deep_reprise":
        target_basis, target_km, target_minutes = _target_deep_reprise(
            runner_profile, training_history, periodization, reason_codes
        )

    elif continuity == "partial_reprise":
        target_basis, target_km, target_minutes = _target_partial_reprise(
            runner_profile, training_history, periodization, reason_codes
        )

    elif continuity == "reprise_exit":
        target_basis, target_km, target_minutes = _target_reprise_exit(
            runner_profile, training_history, periodization, reason_codes
        )

    else:  # normal
        target_basis, target_km, target_minutes = _target_normal(
            runner_profile, training_history, plan_goal, periodization, reason_codes
        )

    # ── Intensity ──────────────────────────────────────────────────────────
    # Intensity is forbidden in all reprise states except reprise_exit.
    # For reprise_exit: intensity may return ONLY when a reliable volume baseline
    # exists (target_basis == "distance"). Without a baseline, a duration fallback
    # is prescribed and intensity is withheld (UNKNOWN BASELINE → NO INTENSITY RETURN).
    if continuity in ("no_history", "deep_reprise", "partial_reprise"):
        allow_intensity = False
    elif continuity == "reprise_exit":
        if target_basis == "distance":
            # Baseline exploitable: volume HOLD + intensity resumes.
            allow_intensity = True
            reason_codes.append("REPRISE_EXIT_INTENSITY_RETURNS")
        else:
            # No exploitable baseline: duration fallback + intensity withheld.
            allow_intensity = False
            reason_codes.append("REPRISE_EXIT_INTENSITY_WITHHELD_NO_BASELINE")
    else:  # normal
        allow_intensity = True

    # ── Sessions ──────────────────────────────────────────────────────────
    target_sessions = _clamp_sessions(runner_profile, continuity)

    # ── Confidence ────────────────────────────────────────────────────────
    confidence = training_state.overall_confidence

    return WeeklyTarget(
        reference_date=reference_date,
        target_basis=target_basis,
        target_km=target_km,
        target_duration_minutes=target_minutes,
        target_sessions=target_sessions,
        allow_intensity=allow_intensity,
        confidence=confidence,
        continuity_state=continuity,
        reason_codes=tuple(reason_codes),
    )


__all__ = ["WeeklyTarget", "build_weekly_target"]
