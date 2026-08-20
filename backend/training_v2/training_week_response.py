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


class WeekV2SessionResponse(BaseModel):
    """Single training session — native V2 prescription fields."""

    model_config = ConfigDict(frozen=True)

    day: str
    """Day of week, e.g. 'monday'."""

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


class TrainingWeekV2Response(BaseModel):
    """Top-level response for GET /training/v2/week.

    Contains all V2 native objects required to render TrainingPlanV2.
    No legacy adapter applied. No field coercion (None stays None).
    """

    model_config = ConfigDict(frozen=True)

    reference_date: str
    """ISO-8601 anchor date used for this construction."""

    goal: WeekV2GoalResponse
    state: WeekV2StateResponse
    weekly_target: WeekV2TargetResponse
    week: WeekV2PlanResponse


__all__ = [
    "TrainingWeekV2Response",
    "WeekV2GoalResponse",
    "WeekV2StateResponse",
    "WeekV2TargetResponse",
    "WeekV2SessionResponse",
    "WeekV2PlanResponse",
]
