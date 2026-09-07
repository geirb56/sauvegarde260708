"""PR234 — StructuredWorkoutPrescriptionEngine.

Design rules
------------
- PURE: no MongoDB, no Garmin, no HTTP, no LLM, no random, no clock calls.
- Consumes existing V2 contracts only:
    WorkoutPrescription (WorkoutGenerator, #131)
    PlanGoal            (#05)
    PeriodizationSnapshot (Periodization)
    TrainingPaces        (Training Paces V2, #194)
- Does NOT recalculate weekly volume, periodization phase, WeeklyTarget or
  Training Paces. It CONSUMES their outputs deterministically.
- Does NOT introduce a second/competing planner. It is a pure post-processing
  layer over a single already-decided ``WorkoutPrescription``.

Responsibility
--------------
StructuredWorkoutPrescriptionEngine answers ONE question:

    "Given one already-decided session (workout_type + total volume), what
    explicit, executable structure (warmup / work / recovery / cooldown)
    should this session have — if, and only if, that structure can be
    determined from real inputs?"

Pipeline placement (documented decision — see RUNINDEX_PR234_REPORT.md §4)
---------------------------------------------------------------------------
Conceptual pipeline::

    WorkoutGenerator (weekly, per-day WorkoutPrescription)
        -> DailyAdaptation (TODAY ONLY: KEEP / EASY_DOWNGRADE / SHORTEN / REST)
        -> StructuredWorkoutPrescriptionEngine (THIS MODULE)
        -> StructuredWorkoutPrescription (executable structure)

StructuredWorkoutPrescriptionEngine is invoked with whatever
``WorkoutPrescription`` is FINAL for the day being rendered:
  - for TODAY: the ``adapted_workout`` returned by
    ``daily_adaptation.build_daily_adaptation`` (never the raw planned one).
  - for any other day of the week (no DailyAdaptation applies — see
    ``today_prescription.py`` docstring: "DailyAdaptation is Today-only"):
    the raw ``WorkoutPrescription`` from the reconciled ``WeeklyPlan``.

Rationale — this order (adaptation BEFORE structuring), never the reverse:
  1. Determinism: structuring is a pure function of (workout_type, total
     volume, goal, phase, paces). Feeding it the FINAL prescription means a
     given final state always produces the same structure, regardless of
     which adaptation path produced it.
  2. No stale structure after adaptation: structuring the RAW plan first and
     then trying to adapt a *structure* (shrink warmup/work/cooldown blocks
     in place) would require DailyAdaptation to understand and rewrite
     per-step structure — duplicating this engine's logic inside
     DailyAdaptation and risking steps that no longer match the (adapted)
     parent totals. By structuring AFTER adaptation, the parent totals
     handed to this engine are ALWAYS the ones actually served, so steps
     are constructed to match them from the start. There is never an
     "adapted parent / stale steps" combination (see §13 and Test set
     M/N/O/P in the test suite).
  3. Snapshot compatibility (#235): once a day is frozen (see
     ``prescription_snapshot.py``), the FINAL WorkoutPrescription for that
     day never changes again, so calling this engine against it is
     idempotent and safe to persist as part of a future snapshot.

This module does NOT decide when to call itself, and does NOT modify
``daily_adaptation.py`` or ``today_prescription.py``. Wiring this engine
into a specific server endpoint / API response is left to a follow-up PR
(kept out of scope here — see RUNINDEX_PR234_REPORT.md §"Limites connues").

Contract — None != 0
---------------------
A field that cannot be determined from real inputs is set to ``None``,
never to an invented default (0, an arbitrary pace, an arbitrary rep count).

Volume invariant — no hidden recovery
--------------------------------------
Recovery between repetitions is modelled as metadata EMBEDDED in the
enclosing ``work`` step (``StructuredWorkoutStep.recovery``), never as a
sibling step with its own distance. Recovery is deliberately time-only
(a jog/rest duration calibration constant — see ``_RECOVERY_SECONDS`` —
labelled PRODUCT CALIBRATION V1, not physiological law) and its distance is
therefore unknown. Consequently:
  - the sum of step distances (warmup + work×reps + cooldown) is
    *by construction* exactly equal to the parent's ``total_distance_km``
    for distance-based prescriptions (``distance_closes_total=True``);
    recovery contributes 0 additional km because it is never a distance
    component.
  - the sum of step durations similarly closes duration-based totals
    exactly (recovery duration IS counted here, because it is a real
    elapsed-time cost within a duration-based session).
  - when a total cannot be closed (e.g. duration for a distance-based
    session, because point-pace durations are only derived from single
    valued zones — never from a pace *range*), the corresponding
    ``*_closes_total`` flag is explicitly ``False`` and
    ``*_invariant_applicable`` records whether the check was meaningful at
    all. The gap is never hidden.

Training Paces — consumption only
-----------------------------------
This module never recomputes VDOT or Daniels fractions. It reads
``TrainingPaces`` (easy/marathon/threshold/interval/repetition) and maps a
structural zone to the matching field. If Training Paces is insufficient,
the semantic zone (e.g. "E", "T") is still recorded (it IS known — it's a
property of the *session type*), but no numeric pace value is invented:
``pace_min_per_km`` / ``pace_min_per_km_min`` / ``pace_min_per_km_max`` stay
``None`` and reason code ``PACE_UNAVAILABLE`` is added.

Target time
-----------
This module does NOT compute a target pace from ``PlanGoal.target_time_seconds``.
Target-time ambition is already folded into WorkoutGenerator/Training Paces
upstream; this engine only ever consumes Training Paces zones.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Tuple

from pydantic import BaseModel, ConfigDict

from .periodization import PeriodizationPhase, PeriodizationSnapshot
from .plan_goal import GoalType, PlanGoal
from .training_paces import PaceRange, PaceValue, TrainingPaces
from .workout_generator import WorkoutPrescription

# ---------------------------------------------------------------------------
# Calibration constants — V1, recalibrable, NOT physiological law
# ---------------------------------------------------------------------------

# Warmup / cooldown reservation (distance basis, metres).
WARMUP_FRACTION: float = 0.15
WARMUP_MIN_M: float = 800.0
WARMUP_MAX_M: float = 3000.0
COOLDOWN_FRACTION: float = 0.10
COOLDOWN_MIN_M: float = 600.0
COOLDOWN_MAX_M: float = 2000.0

# Warmup / cooldown reservation (duration basis, seconds).
WARMUP_FRACTION_DURATION: float = 0.20
WARMUP_MIN_S: float = 480.0    # 8 min
WARMUP_MAX_S: float = 900.0    # 15 min
COOLDOWN_FRACTION_DURATION: float = 0.12
COOLDOWN_MIN_S: float = 300.0  # 5 min
COOLDOWN_MAX_S: float = 600.0  # 10 min

# Never reserve more than this fraction of total volume to warmup+cooldown
# combined — the work block must always retain a meaningful share.
_MAX_WARMUP_COOLDOWN_SHARE: float = 0.60

# Repetition target size per quality kind (distance basis, metres per rep).
_REP_TARGET_M: dict[str, float] = {
    "threshold_intervals": 1500.0,
    "vo2_intervals": 800.0,
}
# Repetition target size per quality kind (duration basis, seconds per rep).
_REP_TARGET_S: dict[str, float] = {
    "threshold_intervals": 360.0,
    "vo2_intervals": 180.0,
}
_REP_MIN: dict[str, int] = {"threshold_intervals": 2, "vo2_intervals": 4}
_REP_MAX: dict[str, int] = {"threshold_intervals": 5, "vo2_intervals": 8}

# Sanity floor for a single repetition once rep_min/rep_max clamping and
# rounding have been applied. If the volume is so small that clamping to
# rep_min would produce a degenerate (unrealistically short) rep, the
# engine falls back to a single continuous work block (VOLUME_LIMITED)
# instead of presenting a fake interval structure.
_MIN_PER_REP_M: dict[str, float] = {"threshold_intervals": 600.0, "vo2_intervals": 300.0}
_MIN_PER_REP_S: dict[str, int] = {"threshold_intervals": 120, "vo2_intervals": 45}

# Recovery jog duration between repetitions, seconds. PRODUCT CALIBRATION V1.
_RECOVERY_SECONDS: dict[str, int] = {
    "threshold_intervals": 90,
    "vo2_intervals": 120,
    "race_specific_steady": 60,
}

# Minimum work volume required before splitting into repetitions at all;
# below this, fall back to a single continuous work block (VOLUME_LIMITED).
_MIN_WORK_M_FOR_INTERVALS: float = 900.0
_MIN_WORK_S_FOR_INTERVALS: float = 360.0


# ---------------------------------------------------------------------------
# Enums
# ---------------------------------------------------------------------------


class StructuredStepType(str, Enum):
    """Step kinds required by the contract (problem statement §4).

    V1 emission note: `recovery` and `rest` are part of the closed contract
    but are never emitted as a standalone step in V1. Recovery is always
    embedded as metadata inside the owning `work` step's `recovery` field
    (never a sibling step — see §9/module docstring on the volume
    invariant); a rest day short-circuits to an empty `steps` tuple on the
    `StructuredWorkoutPrescription` rather than a single `rest`-typed step.
    Both members are kept on the enum so the contract stays forward
    compatible (e.g. a future multi-block race_specific_steady split that
    needs a standalone recovery step) without a breaking schema change.
    """

    warmup = "warmup"
    work = "work"
    recovery = "recovery"
    cooldown = "cooldown"
    continuous = "continuous"
    rest = "rest"


class QualityKind(str, Enum):
    """Closed, testable set of quality-session structures (V1 library)."""

    tempo_continuous = "tempo_continuous"
    threshold_intervals = "threshold_intervals"
    vo2_intervals = "vo2_intervals"
    race_specific_steady = "race_specific_steady"


_QUALITY_REASON: dict[QualityKind, str] = {
    QualityKind.tempo_continuous: "QUALITY_TEMPO_SELECTED",
    QualityKind.threshold_intervals: "QUALITY_THRESHOLD_SELECTED",
    QualityKind.vo2_intervals: "QUALITY_VO2_SELECTED",
    QualityKind.race_specific_steady: "QUALITY_RACE_SPECIFIC_SELECTED",
}

_ZONE_FOR_KIND: dict[QualityKind, str] = {
    QualityKind.tempo_continuous: "T",
    QualityKind.threshold_intervals: "T",
    QualityKind.vo2_intervals: "I",
    # race_specific_steady resolved per-goal — see _race_specific_zone
}

_GOAL_CODE: dict[GoalType, str] = {
    GoalType.maintenance: "GOAL_MAINTENANCE",
    GoalType.five_k: "GOAL_5K",
    GoalType.ten_k: "GOAL_10K",
    GoalType.half_marathon: "GOAL_HALF_MARATHON",
    GoalType.marathon: "GOAL_MARATHON",
    GoalType.ultra: "GOAL_ULTRA",
}

_PHASE_CODE: dict[PeriodizationPhase, str] = {
    PeriodizationPhase.base: "PHASE_BASE",
    PeriodizationPhase.build: "PHASE_BUILD",
    PeriodizationPhase.specific: "PHASE_SPECIFIC",
    PeriodizationPhase.taper: "PHASE_TAPER",
    PeriodizationPhase.race: "PHASE_RACE",
    PeriodizationPhase.consolidation: "PHASE_CONSOLIDATION",
}

# Phases in which no hard/incoherent quality structure may be introduced.
_CONSERVATIVE_PHASES: frozenset[PeriodizationPhase] = frozenset(
    {
        PeriodizationPhase.taper,
        PeriodizationPhase.race,
        PeriodizationPhase.consolidation,
    }
)

_CONTINUOUS_WORKOUT_TYPES: frozenset[str] = frozenset(
    {"easy", "recovery", "long_easy", "steady"}
)


# ---------------------------------------------------------------------------
# Output models
# ---------------------------------------------------------------------------


class StructuredWorkoutRecovery(BaseModel):
    """Recovery embedded within a repeated ``work`` step.

    Deliberately time-only: distance is never claimed because it cannot be
    known precisely (depends on an un-modelled jog pace). Never a sibling
    step — see module docstring "Volume invariant".
    """

    model_config = ConfigDict(frozen=True)

    kind: str
    """"jog" | "rest"."""

    duration_seconds: Optional[int]
    distance_m: Optional[float] = None
    """Always None in V1 — recovery distance is never fabricated."""


class StructuredWorkoutStep(BaseModel):
    """One structural component of a StructuredWorkoutPrescription.

    ``distance_m`` / ``duration_seconds`` are PER-REPETITION values;
    multiply by ``repetitions`` to obtain the step's total contribution.
    """

    model_config = ConfigDict(frozen=True)

    step_type: StructuredStepType
    repetitions: int = 1
    distance_m: Optional[float] = None
    duration_seconds: Optional[int] = None
    recovery: Optional[StructuredWorkoutRecovery] = None

    pace_zone: Optional[str] = None
    """Semantic Training Paces zone: "E" | "M" | "T" | "I" | "R" | None."""

    pace_min_per_km: Optional[float] = None
    """Single-value pace (M / T / R zones), only if Training Paces provided it."""

    pace_min_per_km_min: Optional[float] = None
    """Range lower bound / faster edge (E / I zones)."""

    pace_min_per_km_max: Optional[float] = None
    """Range upper bound / slower edge (E / I zones)."""

    reason_codes: Tuple[str, ...] = ()


class StructuredWorkoutPrescription(BaseModel):
    """Canonical, serializable, executable structure for one session.

    Snapshot-ready (#235): every field is a plain, sanitized value — no
    references to mutable objects, no un-resolved lazy computation.
    """

    model_config = ConfigDict(frozen=True)

    workout_type: str
    target_basis: str
    """"distance" | "duration" | "none" (rest day)."""

    total_distance_km: Optional[float]
    """Mirrors the parent WorkoutPrescription.distance_km. NEVER recomputed."""

    total_duration_minutes: Optional[int]
    """Mirrors the parent WorkoutPrescription.duration_minutes. NEVER recomputed."""

    steps: Tuple[StructuredWorkoutStep, ...]

    steps_distance_km_sum: Optional[float]
    """Sum of step distances (None if any distance-relevant step is unknown)."""

    steps_duration_seconds_sum: Optional[int]
    """Sum of step durations (None if any duration-relevant step is unknown)."""

    distance_invariant_applicable: bool
    """True only when target_basis == "distance" and total_distance_km is set."""

    distance_closes_total: bool
    """True iff steps_distance_km_sum == total_distance_km (± rounding tolerance).
    Meaningless (defaults True, vacuous) when not applicable — never claim a
    false positive: check distance_invariant_applicable first."""

    duration_invariant_applicable: bool
    """True only when target_basis == "duration" and total_duration_minutes is set."""

    duration_closes_total: bool
    """True iff steps_duration_seconds_sum == total_duration_minutes*60
    (± rounding tolerance). See distance_closes_total for the vacuous-case note."""

    reason_codes: Tuple[str, ...]


# ---------------------------------------------------------------------------
# Internal helpers — rounding / reservation
# ---------------------------------------------------------------------------


def _reserve_warmup_cooldown(
    total: float,
    *,
    warmup_fraction: float,
    warmup_min: float,
    warmup_max: float,
    cooldown_fraction: float,
    cooldown_min: float,
    cooldown_max: float,
) -> tuple[float, float]:
    """Deterministically reserve warmup/cooldown, absorbing edge cases.

    Never negative. Never exceeds _MAX_WARMUP_COOLDOWN_SHARE of total.
    """
    if total <= 0:
        return 0.0, 0.0

    warmup = min(max(total * warmup_fraction, warmup_min), warmup_max)
    cooldown = min(max(total * cooldown_fraction, cooldown_min), cooldown_max)

    cap = total * _MAX_WARMUP_COOLDOWN_SHARE
    if warmup + cooldown > cap:
        if warmup + cooldown > 0:
            scale = cap / (warmup + cooldown)
            warmup *= scale
            cooldown *= scale
        else:
            warmup, cooldown = 0.0, 0.0

    warmup = max(0.0, min(warmup, total))
    cooldown = max(0.0, min(cooldown, max(0.0, total - warmup)))
    return warmup, cooldown


def _split_reps_distance(work_m: float, per_rep_target_m: float, rep_min: int, rep_max: int) -> tuple[int, float, float]:
    """Return (reps, per_rep_m, drift_m) splitting work_m evenly across reps.

    drift_m is the rounding residual to be absorbed by the last rep so that
    reps * per_rep_m + drift_m == work_m exactly.
    """
    if work_m <= 0:
        return 0, 0.0, 0.0
    reps = round(work_m / per_rep_target_m)
    reps = max(rep_min, min(rep_max, reps))
    reps = max(1, reps)
    per_rep_m = int(work_m // reps)
    drift_m = work_m - (per_rep_m * reps)
    return reps, float(per_rep_m), float(drift_m)


def _split_reps_duration(
    work_s: float, per_rep_target_s: float, rep_min: int, rep_max: int, recovery_s: int
) -> tuple[int, int, int]:
    """Split work_s into (reps, per_rep_s, drift_s) INCLUDING recovery time
    in the budget, so that reps*(per_rep_s + recovery_s) + drift_s == work_s
    exactly. Recovery is a real elapsed-time cost for duration-based
    sessions and must never push the total beyond the parent budget (§9/§10).
    """
    if work_s <= 0:
        return 0, 0, 0
    reps = round(work_s / (per_rep_target_s + recovery_s))
    reps = max(rep_min, min(rep_max, reps))
    reps = max(1, reps)
    work_budget_s = max(0.0, work_s - reps * recovery_s)
    per_rep_s = int(work_budget_s // reps)
    drift_s = int(work_s - (per_rep_s * reps + reps * recovery_s))
    return reps, per_rep_s, drift_s


# ---------------------------------------------------------------------------
# Internal helpers — Training Paces consumption
# ---------------------------------------------------------------------------


def _pace_fields_for_zone(
    zone: Optional[str], training_paces: Optional[TrainingPaces]
) -> tuple[Optional[float], Optional[float], Optional[float], list[str]]:
    """Return (single, range_min, range_max, reason_codes) for a zone.

    Never fabricates a value: if Training Paces is insufficient or the zone
    field is None, all numeric fields stay None and PACE_UNAVAILABLE is added.
    """
    if zone is None:
        return None, None, None, []

    if (
        training_paces is None
        or training_paces.confidence == "insufficient"
    ):
        return None, None, None, ["PACE_UNAVAILABLE"]

    field_map = {
        "E": training_paces.easy,
        "M": training_paces.marathon,
        "T": training_paces.threshold,
        "I": training_paces.interval,
        "R": training_paces.repetition,
    }
    value = field_map.get(zone)
    if value is None:
        return None, None, None, ["PACE_UNAVAILABLE"]

    if isinstance(value, PaceRange):
        return None, value.lower.min_per_km, value.upper.min_per_km, [f"PACE_{zone}_AVAILABLE"]
    if isinstance(value, PaceValue):
        return value.min_per_km, None, None, [f"PACE_{zone}_AVAILABLE"]
    return None, None, None, ["PACE_UNAVAILABLE"]


def _single_pace_seconds_per_km(zone: Optional[str], training_paces: Optional[TrainingPaces]) -> Optional[float]:
    """Return the SINGLE-value pace (seconds/km) for zone, or None.

    Only defined for single-valued zones (M/T/R). Never derived from a
    range (E/I) — a range has no canonical point estimate.
    """
    if zone not in ("M", "T", "R") or training_paces is None:
        return None
    if training_paces.confidence == "insufficient":
        return None
    field_map = {"M": training_paces.marathon, "T": training_paces.threshold, "R": training_paces.repetition}
    value = field_map.get(zone)
    if not isinstance(value, PaceValue):
        return None
    return value.min_per_km * 60.0


def _race_specific_zone(goal_type: GoalType) -> str:
    return "M" if goal_type == GoalType.marathon else "T"


# ---------------------------------------------------------------------------
# Quality kind selection — goal-aware + phase-aware
# ---------------------------------------------------------------------------


def _select_quality_kind(goal_type: GoalType, phase: PeriodizationPhase) -> tuple[QualityKind, list[str]]:
    """Deterministically select the quality structure.

    Table (documented in RUNINDEX_PR234_REPORT.md §goal-aware / §phase-aware):
      - maintenance                 -> always tempo_continuous (conservative,
                                        no race-specific work without reason).
      - taper / race / consolidation-> always tempo_continuous, regardless of
                                        goal (never a hard/incoherent session
                                        close to a race; controlled comeback).
      - base                        -> tempo_continuous, except 5k -> threshold
                                        (5k benefits from earlier fast-work
                                        exposure; other goals stay conservative
                                        in base).
      - build                       -> threshold_intervals for 10k/half/
                                        marathon/ultra (broad aerobic-anaerobic
                                        development); vo2_intervals for 5k
                                        (more specific fast work possible).
      - specific                    -> race_specific_steady for 10k/half/
                                        marathon/ultra (aligned to goal);
                                        vo2_intervals for 5k (specific fast
                                        work); tempo_continuous for maintenance.

    Ultra NEVER receives vo2_intervals in this table by construction — see
    the defensive assertion below (durability/endurance priority, no VO2
    intervals injected artificially, per problem statement §7/§8).
    """
    reasons: list[str] = []

    if goal_type == GoalType.maintenance:
        kind = QualityKind.tempo_continuous
    elif phase in _CONSERVATIVE_PHASES:
        kind = QualityKind.tempo_continuous
        if phase == PeriodizationPhase.taper:
            reasons.append("TAPER_REDUCED")
    elif phase == PeriodizationPhase.base:
        kind = QualityKind.threshold_intervals if goal_type == GoalType.five_k else QualityKind.tempo_continuous
    elif phase == PeriodizationPhase.build:
        kind = QualityKind.vo2_intervals if goal_type == GoalType.five_k else QualityKind.threshold_intervals
    elif phase == PeriodizationPhase.specific:
        if goal_type == GoalType.five_k:
            kind = QualityKind.vo2_intervals
        else:
            kind = QualityKind.race_specific_steady
    else:
        kind = QualityKind.tempo_continuous

    # Defensive invariant — never allow VO2 intervals for ultra (§7/§8).
    if goal_type == GoalType.ultra and kind == QualityKind.vo2_intervals:
        kind = QualityKind.threshold_intervals

    reasons.append(_QUALITY_REASON[kind])
    return kind, reasons


# ---------------------------------------------------------------------------
# Continuous engine (easy / recovery / long_easy / steady)
# ---------------------------------------------------------------------------


def _build_continuous_steps(workout: WorkoutPrescription) -> tuple[str, Tuple[StructuredWorkoutStep, ...], list[str]]:
    """Build the (target_basis, steps, reason_codes) for a continuous session."""
    zone = "E"
    reason_codes: list[str] = [f"CONTINUOUS_{workout.workout_type.upper()}"]

    if workout.distance_km is not None:
        target_basis = "distance"
        distance_m: Optional[float] = round(workout.distance_km * 1000.0, 1)
        duration_s: Optional[float] = None
    elif workout.duration_minutes is not None:
        target_basis = "duration"
        distance_m = None
        duration_s = float(workout.duration_minutes * 60)
    else:
        # Insufficient data — fallback: generic continuous, no volume known.
        target_basis = "none"
        distance_m = None
        duration_s = None
        reason_codes.append("STRUCTURE_UNAVAILABLE")

    # Zone E is a PaceRange — never derive a single-value duration from it
    # (see module docstring: no point estimate from a range).
    step = StructuredWorkoutStep(
        step_type=StructuredStepType.continuous,
        repetitions=1,
        distance_m=distance_m,
        duration_seconds=int(duration_s) if duration_s is not None else None,
        pace_zone=zone,
        reason_codes=tuple(reason_codes),
    )
    return target_basis, (step,), reason_codes


# ---------------------------------------------------------------------------
# Quality engine
# ---------------------------------------------------------------------------


def _reserved_edge_step(
    step_type: StructuredStepType,
    *,
    basis: str,
    value: float,
    reason_code: str,
) -> StructuredWorkoutStep:
    """Build a warmup/cooldown step reserving `value` in the given basis.

    `basis` is "distance" (metres) or "duration" (seconds). A reservation of
    0 renders as None on the corresponding field (never a fake zero-size
    step) per §10 ("no invented zero unless semantically necessary").
    """
    if basis == "distance":
        distance_m = value if value > 0 else None
        duration_seconds = None
    else:
        duration_seconds = int(round(value)) if value > 0 else None
        distance_m = None
    return StructuredWorkoutStep(
        step_type=step_type,
        distance_m=distance_m,
        duration_seconds=duration_seconds,
        pace_zone="E",
        reason_codes=(reason_code,),
    )


def _build_quality_steps(
    workout: WorkoutPrescription,
    *,
    plan_goal: PlanGoal,
    periodization: PeriodizationSnapshot,
) -> tuple[str, Tuple[StructuredWorkoutStep, ...], list[str]]:
    kind, kind_reasons = _select_quality_kind(plan_goal.goal_type, periodization.phase)
    reason_codes: list[str] = list(kind_reasons)
    reason_codes.append(_GOAL_CODE[plan_goal.goal_type])
    reason_codes.append(_PHASE_CODE[periodization.phase])

    if kind == QualityKind.race_specific_steady:
        zone = _race_specific_zone(plan_goal.goal_type)
    else:
        zone = _ZONE_FOR_KIND[kind]

    if workout.distance_km is not None:
        target_basis = "distance"
        total_m = round(workout.distance_km * 1000.0, 1)
        warmup_m, cooldown_m = _reserve_warmup_cooldown(
            total_m,
            warmup_fraction=WARMUP_FRACTION,
            warmup_min=WARMUP_MIN_M,
            warmup_max=WARMUP_MAX_M,
            cooldown_fraction=COOLDOWN_FRACTION,
            cooldown_min=COOLDOWN_MIN_M,
            cooldown_max=COOLDOWN_MAX_M,
        )
        work_m = max(0.0, total_m - warmup_m - cooldown_m)

        steps: list[StructuredWorkoutStep] = []
        steps.append(
            _reserved_edge_step(
                StructuredStepType.warmup, basis="distance", value=warmup_m, reason_code="WARMUP_RESERVED"
            )
        )

        reps, per_rep_m, drift_m = 0, 0.0, 0.0
        if kind in (QualityKind.threshold_intervals, QualityKind.vo2_intervals) and work_m >= _MIN_WORK_M_FOR_INTERVALS:
            reps, per_rep_m, drift_m = _split_reps_distance(
                work_m, _REP_TARGET_M[kind.value], _REP_MIN[kind.value], _REP_MAX[kind.value]
            )
            if per_rep_m < _MIN_PER_REP_M[kind.value]:
                # Clamping to rep_min still produced a degenerate (too
                # short) rep for this volume: never present a fake interval
                # structure — fall back to continuous work instead (§6/§10).
                reps, per_rep_m, drift_m = 0, 0.0, 0.0

        if reps > 0:
            recovery_s = _RECOVERY_SECONDS[kind.value]
            # Rounding drift (§10): reps * per_rep_m is an even, deterministic
            # split; any residual (< per-rep granularity) is absorbed by the
            # cooldown reservation below so that the parent total is closed
            # exactly without an uneven/arbitrary "longer last rep".
            steps.append(
                StructuredWorkoutStep(
                    step_type=StructuredStepType.work,
                    repetitions=reps,
                    distance_m=per_rep_m,
                    recovery=StructuredWorkoutRecovery(kind="jog", duration_seconds=recovery_s),
                    pace_zone=zone,
                    reason_codes=tuple(reason_codes),
                )
            )
            cooldown_m = cooldown_m + drift_m
        else:
            if kind in (QualityKind.threshold_intervals, QualityKind.vo2_intervals):
                reason_codes.append("VOLUME_LIMITED")
            steps.append(
                StructuredWorkoutStep(
                    step_type=StructuredStepType.work,
                    repetitions=1,
                    distance_m=work_m if work_m > 0 else None,
                    pace_zone=zone,
                    reason_codes=tuple(reason_codes),
                )
            )

        steps.append(
            _reserved_edge_step(
                StructuredStepType.cooldown, basis="distance", value=cooldown_m, reason_code="COOLDOWN_RESERVED"
            )
        )

    elif workout.duration_minutes is not None:
        target_basis = "duration"
        total_s_exact = workout.duration_minutes * 60  # exact int budget
        warmup_s_raw, cooldown_s_raw = _reserve_warmup_cooldown(
            float(total_s_exact),
            warmup_fraction=WARMUP_FRACTION_DURATION,
            warmup_min=WARMUP_MIN_S,
            warmup_max=WARMUP_MAX_S,
            cooldown_fraction=COOLDOWN_FRACTION_DURATION,
            cooldown_min=COOLDOWN_MIN_S,
            cooldown_max=COOLDOWN_MAX_S,
        )
        # §10 rounding/reste: warmup is rounded first (deterministically);
        # the remainder (work + cooldown) is derived as an EXACT integer so
        # that warmup + work(+recovery) + cooldown == total_s_exact always,
        # with cooldown absorbing the final rounding residual (never work,
        # never warmup, never a hidden gap).
        warmup_s_int = max(0, min(int(round(warmup_s_raw)), total_s_exact))
        work_s_for_calc = max(0.0, float(total_s_exact) - warmup_s_int - cooldown_s_raw)

        steps = []
        steps.append(
            _reserved_edge_step(
                StructuredStepType.warmup, basis="duration", value=warmup_s_int, reason_code="WARMUP_RESERVED"
            )
        )

        if (
            kind in (QualityKind.threshold_intervals, QualityKind.vo2_intervals)
            and work_s_for_calc >= _MIN_WORK_S_FOR_INTERVALS
        ):
            recovery_s = _RECOVERY_SECONDS[kind.value]
            reps, per_rep_s, _drift_s = _split_reps_duration(
                work_s_for_calc, _REP_TARGET_S[kind.value], _REP_MIN[kind.value], _REP_MAX[kind.value], recovery_s
            )
            if per_rep_s < _MIN_PER_REP_S[kind.value]:
                # Same degenerate-rep guard as the distance branch (§6/§10):
                # never present a fake interval structure for a too-short rep.
                reps, per_rep_s, recovery_s = 0, 0, 0
        else:
            reps, per_rep_s, recovery_s = 0, 0, 0

        if reps > 0 and per_rep_s > 0:
            steps.append(
                StructuredWorkoutStep(
                    step_type=StructuredStepType.work,
                    repetitions=reps,
                    duration_seconds=per_rep_s,
                    recovery=StructuredWorkoutRecovery(kind="jog", duration_seconds=recovery_s),
                    pace_zone=zone,
                    reason_codes=tuple(reason_codes),
                )
            )
            cooldown_s_int = total_s_exact - warmup_s_int - reps * (per_rep_s + recovery_s)
        else:
            if kind in (QualityKind.threshold_intervals, QualityKind.vo2_intervals):
                reason_codes.append("VOLUME_LIMITED")
            work_s_int = int(round(work_s_for_calc))
            steps.append(
                StructuredWorkoutStep(
                    step_type=StructuredStepType.work,
                    repetitions=1,
                    duration_seconds=work_s_int if work_s_int > 0 else None,
                    pace_zone=zone,
                    reason_codes=tuple(reason_codes),
                )
            )
            cooldown_s_int = total_s_exact - warmup_s_int - work_s_int

        # Never a negative reservation (§10) — any negative residual (only
        # possible from adversarial rounding at the very small-volume edge)
        # collapses cooldown to 0 rather than lying about the total.
        cooldown_s_int = max(0, cooldown_s_int)

        steps.append(
            _reserved_edge_step(
                StructuredStepType.cooldown, basis="duration", value=cooldown_s_int, reason_code="COOLDOWN_RESERVED"
            )
        )
    else:
        target_basis = "none"
        reason_codes.append("STRUCTURE_UNAVAILABLE")
        steps = [
            StructuredWorkoutStep(
                step_type=StructuredStepType.continuous,
                pace_zone=zone,
                reason_codes=tuple(reason_codes),
            )
        ]

    return target_basis, tuple(steps), reason_codes


# ---------------------------------------------------------------------------
# Finalization — pace attachment + invariant computation
# ---------------------------------------------------------------------------

_DISTANCE_TOLERANCE_KM: float = 0.01
_DURATION_TOLERANCE_S: float = 1.0


def _attach_paces(
    steps: Tuple[StructuredWorkoutStep, ...], training_paces: Optional[TrainingPaces]
) -> Tuple[StructuredWorkoutStep, ...]:
    updated: list[StructuredWorkoutStep] = []
    for step in steps:
        zone = step.pace_zone
        single, rmin, rmax, pace_reasons = _pace_fields_for_zone(zone, training_paces)

        duration_seconds = step.duration_seconds
        if (
            duration_seconds is None
            and step.distance_m is not None
            and zone in ("M", "T", "R")
        ):
            spk = _single_pace_seconds_per_km(zone, training_paces)
            if spk is not None:
                duration_seconds = int(round((step.distance_m / 1000.0) * spk))

        updated.append(
            step.model_copy(
                update={
                    "pace_min_per_km": single,
                    "pace_min_per_km_min": rmin,
                    "pace_min_per_km_max": rmax,
                    "duration_seconds": duration_seconds,
                    "reason_codes": tuple(dict.fromkeys(step.reason_codes + tuple(pace_reasons))),
                }
            )
        )
    return tuple(updated)


def _sum_optional(values: list[Optional[float]]) -> Optional[float]:
    if any(v is None for v in values):
        return None
    return sum(values)


def _finalize(
    *,
    workout: WorkoutPrescription,
    target_basis: str,
    steps: Tuple[StructuredWorkoutStep, ...],
    reason_codes: list[str],
    training_paces: Optional[TrainingPaces],
) -> StructuredWorkoutPrescription:
    steps = _attach_paces(steps, training_paces)

    distance_terms: list[Optional[float]] = []
    duration_terms: list[Optional[float]] = []
    for step in steps:
        if step.step_type == StructuredStepType.rest:
            continue
        distance_terms.append(step.distance_m * step.repetitions if step.distance_m is not None else None)
        if step.duration_seconds is not None:
            work_duration = step.duration_seconds * step.repetitions
            recovery_duration = (
                step.recovery.duration_seconds * step.repetitions
                if step.recovery is not None and step.recovery.duration_seconds is not None
                else 0
            )
            duration_terms.append(work_duration + recovery_duration)
        else:
            duration_terms.append(None)

    steps_distance_m_sum = _sum_optional(distance_terms)
    steps_distance_km_sum = round(steps_distance_m_sum / 1000.0, 3) if steps_distance_m_sum is not None else None
    steps_duration_seconds_sum = _sum_optional(duration_terms)
    steps_duration_seconds_sum_int = (
        int(round(steps_duration_seconds_sum)) if steps_duration_seconds_sum is not None else None
    )

    distance_invariant_applicable = target_basis == "distance" and workout.distance_km is not None
    duration_invariant_applicable = target_basis == "duration" and workout.duration_minutes is not None

    distance_closes_total = True
    if distance_invariant_applicable:
        distance_closes_total = (
            steps_distance_km_sum is not None
            and abs(steps_distance_km_sum - workout.distance_km) <= _DISTANCE_TOLERANCE_KM
        )

    duration_closes_total = True
    if duration_invariant_applicable:
        expected_s = workout.duration_minutes * 60
        duration_closes_total = (
            steps_duration_seconds_sum_int is not None
            and abs(steps_duration_seconds_sum_int - expected_s) <= _DURATION_TOLERANCE_S
        )

    all_reason_codes = list(reason_codes)
    for step in steps:
        all_reason_codes.extend(step.reason_codes)

    return StructuredWorkoutPrescription(
        workout_type=workout.workout_type,
        target_basis=target_basis,
        total_distance_km=workout.distance_km,
        total_duration_minutes=workout.duration_minutes,
        steps=steps,
        steps_distance_km_sum=steps_distance_km_sum,
        steps_duration_seconds_sum=steps_duration_seconds_sum_int,
        distance_invariant_applicable=distance_invariant_applicable,
        distance_closes_total=distance_closes_total,
        duration_invariant_applicable=duration_invariant_applicable,
        duration_closes_total=duration_closes_total,
        reason_codes=tuple(dict.fromkeys(all_reason_codes)),
    )


# ---------------------------------------------------------------------------
# Public entry point — StructuredWorkoutPrescriptionEngine
# ---------------------------------------------------------------------------


def _empty_prescription(
    *,
    workout_type: str,
    total_distance_km: Optional[float],
    total_duration_minutes: Optional[int],
    reason_codes: Tuple[str, ...],
) -> StructuredWorkoutPrescription:
    """Build a structure-free prescription (no steps, invariants trivially satisfied).

    Shared by the REST short-circuit and the unknown-workout_type fallback
    so both empty-structure paths stay in lockstep if the schema changes.
    """
    return StructuredWorkoutPrescription(
        workout_type=workout_type,
        target_basis="none",
        total_distance_km=total_distance_km,
        total_duration_minutes=total_duration_minutes,
        steps=(),
        steps_distance_km_sum=None,
        steps_duration_seconds_sum=None,
        distance_invariant_applicable=False,
        distance_closes_total=True,
        duration_invariant_applicable=False,
        duration_closes_total=True,
        reason_codes=reason_codes,
    )


def build_structured_workout_prescription(
    *,
    workout: WorkoutPrescription,
    plan_goal: PlanGoal,
    periodization: PeriodizationSnapshot,
    training_paces: Optional[TrainingPaces] = None,
) -> StructuredWorkoutPrescription:
    """Build the canonical structured, executable prescription for one session.

    ``workout`` MUST be the FINAL WorkoutPrescription for the day being
    rendered (post-DailyAdaptation for TODAY; raw WeeklyPlan session for any
    other day — see module docstring "Pipeline placement").
    """
    if workout.workout_type == "rest":
        return _empty_prescription(
            workout_type="rest",
            total_distance_km=None,
            total_duration_minutes=None,
            reason_codes=("PLANNED_REST_DAY",),
        )

    if workout.workout_type in _CONTINUOUS_WORKOUT_TYPES:
        target_basis, steps, reason_codes = _build_continuous_steps(workout)
        return _finalize(
            workout=workout,
            target_basis=target_basis,
            steps=steps,
            reason_codes=reason_codes,
            training_paces=training_paces,
        )

    if workout.workout_type == "quality":
        target_basis, steps, reason_codes = _build_quality_steps(
            workout, plan_goal=plan_goal, periodization=periodization
        )
        return _finalize(
            workout=workout,
            target_basis=target_basis,
            steps=steps,
            reason_codes=reason_codes,
            training_paces=training_paces,
        )

    # Unknown / unsupported workout_type — never invent structure.
    return _empty_prescription(
        workout_type=workout.workout_type,
        total_distance_km=workout.distance_km,
        total_duration_minutes=workout.duration_minutes,
        reason_codes=("STRUCTURE_UNAVAILABLE",),
    )


__all__ = [
    "StructuredStepType",
    "QualityKind",
    "StructuredWorkoutRecovery",
    "StructuredWorkoutStep",
    "StructuredWorkoutPrescription",
    "build_structured_workout_prescription",
]
