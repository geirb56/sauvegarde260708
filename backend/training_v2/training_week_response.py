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


class WeekV2SessionResponse(BaseModel):
    """Single training session — native V2 prescription + factual execution.

    PR232A: planned (prescription) and actual (PR230 Garmin boundary) are
    both exposed. matching_status / adherence_status are never fabricated
    here — they mirror training_v2.performed_workout verbatim.
    """

    model_config = ConfigDict(frozen=True)

    day: str
    """Day of week, e.g. 'monday'."""

    prescription_id: Optional[str] = None
    """C235 (corrective audit) — the SAME canonical prescription_id
    (``week_execution.prescription_id_for``) exposed by ``/training/today``
    for the current day, so Today and Week can be verified to describe the
    exact same served prescription. Never a new/artificial identifier.
    Additive field — ``None`` only if the caller never computed one."""

    session_modified_from_planned: Optional[bool] = None
    """C235 (final correction) — the SAME field name/value
    ``/training/today`` exposes as ``session_modified_from_planned`` for the
    exact same day: the WINNING snapshot's own frozen
    ``modified_from_planned`` fact. NEVER recomputed here by comparing
    against the CURRENT live plan — ``PrescriptionSnapshot.
    modified_from_planned`` is the sole authority, describing a fact frozen
    at serve time that must never change retroactively. ``None`` (never
    coerced to ``False``) when no trustworthy snapshot fact is available:
    ``execution_status == "prescription_unavailable"``, or a legacy
    (pre-C231) snapshot predating this field. Additive field."""

    planned_date: Optional[str] = None
    """PR232A — ISO-8601 date this session is scheduled for."""

    workout_type: Optional[str] = None
    """rest | recovery | easy | steady | quality | long_easy | race. C231 (round 2)
    — None when ``execution_status == "prescription_unavailable"``: this
    day's real historical prescription was never frozen/served, so its
    recomputed-today workout type is not presented as historical fact."""

    intensity_class: Optional[str] = None
    """rest | low | moderate | high | event. None under the same
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

    structured: Optional[dict] = None
    """C234 — StructuredWorkoutPrescriptionEngine output for this session
    (``StructuredWorkoutPrescription.model_dump(mode="json")``), built from
    the EFFECTIVE FINAL prescription. Additive field, never breaking #233's
    existing contract. None when the engine was not wired for this session
    (e.g. ``execution_status == "prescription_unavailable"``, or the
    workout_type is not yet supported by the engine), OR (C234 final
    corrective audit) when ``structured_status ==
    "historical_unavailable"`` — see below."""

    structured_status: Optional[str] = None
    """C234 (final corrective audit) — machine-readable reason for
    ``structured``'s value: ``"today_served"`` | ``"future_live"`` |
    ``"historical_unavailable"`` | ``"prescription_unavailable"`` | None
    (structuring not requested). Mirrors
    ``training_v2.week_execution.SessionExecution.structured_status``
    verbatim. Additive, machine-readable only — no UX/marketing wording, no
    i18n (out of scope here)."""


class WeekV2PlanResponse(BaseModel):
    """Weekly plan — aggregate + individual sessions."""

    model_config = ConfigDict(frozen=True)

    planned_km: Optional[float] = None
    """Sum of TRAINING session distances only; race distance is excluded."""

    planned_duration_minutes: Optional[int] = None
    """Sum of session durations. None when target_basis == "distance"."""

    session_count: int
    """Number of TRAINING sessions (excludes rest and race)."""

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
