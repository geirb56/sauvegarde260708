"""PR167 — Native V2 response models for GET /training/v2/week.

Design rules
------------
- PURE Pydantic models: no business logic, no DB, no computation.
- None != 0: optional fields that are unknown stay None.
- Language-neutral: no labels, no colours, no emoji, no formatting.
- Fields mirror native V2 domain objects (WeeklyTarget, WorkoutPrescription,
  WeeklyPlan, PlanGoal, TrainingState) without any adapter transformation.
- estimated_tss: not yet migrated in WorkoutPrescription V1 — omitted here.
"""

from __future__ import annotations

from datetime import date
from typing import List, Optional

from pydantic import BaseModel, ConfigDict, Field


class WeekV2GoalResponse(BaseModel):
    """Snapshot of the user's training goal for this week."""

    model_config = ConfigDict(frozen=True)

    goal_type: str
    """e.g. "MARATHON", "SEMI", "10K"."""

    race_date: Optional[str] = None
    """ISO-8601 race date string, or None if not set."""

    target_time_seconds: Optional[int] = None
    """Target finish time in seconds, or None if not set."""


class WeekV2StateResponse(BaseModel):
    """Snapshot of the runner's training state for this week."""

    model_config = ConfigDict(frozen=True)

    continuity_state: str
    """no_history | deep_reprise | partial_reprise | reprise_exit | normal."""

    allow_intensity: bool
    """When False: easy / recovery sessions only."""


class WeekV2TargetResponse(BaseModel):
    """Weekly training target — native V2 prescription."""

    model_config = ConfigDict(frozen=True)

    target_basis: str
    """"distance" | "duration"."""

    target_km: Optional[float] = None
    """Weekly distance target in km. None when target_basis == "duration"."""

    target_duration_minutes: Optional[int] = None
    """Weekly duration target in minutes. None when target_basis == "distance"."""

    session_count: int
    """Recommended number of running sessions."""

    confidence: str
    """none | low | medium | high."""


class WeekV2ActualResponse(BaseModel):
    """PR232A — Real Garmin evidence (PR230 boundary), for ONE activity.

    Represents a single real Garmin activity — never fabricated, never a
    calendar guess, never None -> 0 coerced. This same model is reused for
    two distinct positions in the week payload:
    - ``WeekV2SessionResponse.actual``: the activity matched/attributed to
      that specific prescribed session (when ``matching_status`` indicates
      a match).
    - ``WeekV2PlanResponse.unmatched_actuals``: a real Garmin activity from
      the current week that could not be attributed to any prescribed
      session (``matching_status == unmatched_actual``).
    """

    model_config = ConfigDict(frozen=True)

    activity_id: Optional[str] = None
    distance_km: Optional[float] = None
    duration_minutes: Optional[float] = None
    pace_min_per_km: Optional[float] = None
    activity_type: Optional[str] = None
    start_time: Optional[str] = None
    """ISO-8601 local start datetime, when known."""


class WeekV2PaceRangeResponse(BaseModel):
    """PR232 — display pace range for one session, min/km, metric.

    The frontend converts to the user's unit system (km↔mi, /km↔/mile);
    the API always transports metric min/km, never a pre-localised string.
    """

    model_config = ConfigDict(frozen=True)

    lower_min_per_km: float
    upper_min_per_km: float


class WeekV2SessionResponse(BaseModel):
    """Single training session — native V2 prescription + factual execution.

    PR232A: planned (prescription) and actual (PR230 Garmin boundary) are
    both exposed. matching_status / adherence_status are never fabricated
    here — they mirror training_v2.performed_workout verbatim.
    """

    model_config = ConfigDict(frozen=True)

    day: str
    """Day of week, e.g. 'monday'."""

    planned_date: Optional[str] = None
    """PR232A — ISO-8601 date this session is scheduled for."""

    workout_type: Optional[str] = None
    """rest | recovery | easy | steady | quality | long_easy. C231 (round 2)
    — None when ``execution_status == "prescription_unavailable"``: this
    day's real historical prescription was never frozen/served, so its
    recomputed-today workout type is not presented as historical fact."""

    intensity_class: Optional[str] = None
    """rest | low | moderate | high. None under the same
    ``prescription_unavailable`` condition as ``workout_type`` above."""

    distance_km: Optional[float] = None
    """Distance in km. None for duration-based / rest sessions, and for a
    ``prescription_unavailable`` day (C231 round 2 — never a fabricated
    historical value)."""

    duration_minutes: Optional[int] = None
    """Duration in minutes. None for distance-based active sessions, and for
    a ``prescription_unavailable`` day (C231 round 2 — same as above)."""

    estimated_tss: Optional[float] = None
    """Training Stress Score. None for active sessions (not yet computed).
    0 for rest sessions per TSS doctrine."""

    reason_codes: List[str]
    """Deterministic language-neutral diagnostic codes."""

    matching_status: Optional[str] = None
    """PR232A — planned | matched | missed | ambiguous | unmatched_actual
    (training_v2.performed_workout, PR230's own enum verbatim). None when
    ``execution_status`` is set instead (PR230 was never consulted for this
    day — see ``execution_status``)."""

    adherence_status: Optional[str] = None
    """PR232A — factual adherence diagnostic from PR230. Never fabricated
    (no DONE/MISSED invented outside the PR230 engine). None under the same
    condition as ``matching_status`` above."""

    actual: Optional[WeekV2ActualResponse] = None
    """PR232A — real Garmin evidence for this session, or None."""

    execution_status: Optional[str] = None
    """C231 (round 2) — bridge/API-level fact, deliberately NOT a PR230
    ``MatchingStatus``/``AdherenceStatus`` value: "prescription_unavailable"
    when this day's real historical prescription was never frozen/served
    while it was current (``planned_date < reference_date`` and no snapshot
    exists) — the real Garmin activity for that day, if any, still surfaces
    via ``WeekV2PlanResponse.unmatched_actuals``, never fabricated here.
    None for a normal, PR230-backed session."""

    primary_pace: Optional[WeekV2PaceRangeResponse] = None
    """C232 (correction) — the single generic pace ZONE applicable to the
    WHOLE session (see training_v2.session_structure.resolve_session_pace_zone
    for exactly which workout_types get one and why). None for rest,
    prescription_unavailable, "quality" (exact nature not decided by the
    Training Engine), "steady" (not in the Daniels vocabulary), or when
    paces confidence is INSUFFICIENT. NEVER a fabricated interval/segment
    structure — see RUNINDEX_PR232_REPORT.md, "prescription canonique vs
    présentation".

    C232 (correction round 2, item 4) — ALSO None for any session whose
    ``planned_date <= reference_date`` (today or the past): such a session's
    effective prescription is a FROZEN ``PrescriptionSnapshot``, which does
    not persist a pace zone, so it is never reconstructed from TODAY's live
    TrainingPaces (that would let a past session retroactively acquire a
    pace it never had while it was current — see prescription_snapshot.py).
    A pace zone is resolved only for a still-strictly-future session."""


class WeekV2PlanResponse(BaseModel):
    """Weekly plan — aggregate + individual sessions."""

    model_config = ConfigDict(frozen=True)

    planned_km: Optional[float] = None
    """Sum of session distances. None when target_basis == "duration"."""

    planned_duration_minutes: Optional[int] = None
    """Sum of session durations. None when target_basis == "distance"."""

    session_count: int
    """Number of running sessions (excludes rest days)."""

    sessions: List[WeekV2SessionResponse]
    """All sessions ordered Monday→Sunday."""

    unmatched_actuals: List[WeekV2ActualResponse] = Field(default_factory=list)
    """PR232A — real Garmin activities of this week that could not be
    attributed to any prescription. Never dropped."""


class TrainingWeekV2Response(BaseModel):
    """Top-level response for GET /training/v2/week.

    Contains all V2 native objects required to render TrainingPlanV2.
    No legacy adapter applied. No field coercion (None stays None).

    PR228: reconciliation field added — exposes WeeklyReconciliation audit.
    """

    model_config = ConfigDict(frozen=True)

    reference_date: str
    """ISO-8601 anchor date used for this construction."""

    goal: WeekV2GoalResponse
    state: WeekV2StateResponse
    weekly_target: WeekV2TargetResponse
    week: WeekV2PlanResponse

    reconciliation_action: Optional[str] = None
    """PR228 — WeeklyReconciliation action: KEEP | REDUCE_VOLUME | REDUCE_FREQUENCY | REDUCE_BOTH."""

    reconciliation_reason_codes: Optional[List[str]] = None
    """PR228 — Language-neutral diagnostic codes from WeeklyReconciliation."""


__all__ = [
    "TrainingWeekV2Response",
    "WeekV2GoalResponse",
    "WeekV2StateResponse",
    "WeekV2TargetResponse",
    "WeekV2SessionResponse",
    "WeekV2ActualResponse",
    "WeekV2PlanResponse",
]
