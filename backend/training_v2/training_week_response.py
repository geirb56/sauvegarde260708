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

from pydantic import BaseModel, ConfigDict


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
    """PR232A — Real Garmin evidence for a session (PR230 boundary).

    Never fabricated: this model is only populated from a matched/modified
    real activity. No calendar fallback, no None -> 0 coercion.
    """

    model_config = ConfigDict(frozen=True)

    activity_id: Optional[str] = None
    distance_km: Optional[float] = None
    duration_minutes: Optional[float] = None
    pace_min_per_km: Optional[float] = None
    activity_type: Optional[str] = None
    start_time: Optional[str] = None
    """ISO-8601 local start datetime, when known."""


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

    workout_type: str
    """rest | recovery | easy | steady | quality | long_easy."""

    intensity_class: str
    """rest | low | moderate | high."""

    distance_km: Optional[float] = None
    """Distance in km, or None for duration-based / rest sessions."""

    duration_minutes: Optional[int] = None
    """Duration in minutes, or None for distance-based active sessions."""

    estimated_tss: Optional[float] = None
    """Training Stress Score. None for active sessions (not yet computed).
    0 for rest sessions per TSS doctrine."""

    reason_codes: List[str]
    """Deterministic language-neutral diagnostic codes."""

    matching_status: Optional[str] = None
    """PR232A — planned | matched | missed | ambiguous (training_v2.performed_workout).
    None only when execution data could not be resolved for this session."""

    adherence_status: Optional[str] = None
    """PR232A — factual adherence diagnostic from PR230. Never fabricated
    (no DONE/MISSED invented outside the PR230 engine)."""

    actual: Optional[WeekV2ActualResponse] = None
    """PR232A — real Garmin evidence for this session, or None."""


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

    unmatched_actuals: List[WeekV2ActualResponse] = []
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
