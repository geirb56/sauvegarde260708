from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from training_v2.performance_model import (
    CURVE_NULL_CONFIDENCE_EXTRAPOLATION_RATIO,
    PerformanceEstimate,
)
from training_v2.periodization import build_periodization
from training_v2.plan_goal import PlanGoal, build_plan_goal
from training_v2.readiness_decision import ReadinessDecision
from training_v2.training_cycle_response import build_cycle_calendar_response
from training_v2.training_history import build_training_history
from training_v2.training_load import TrainingLoadSnapshot
from training_v2.training_paces import TrainingPaces, training_paces_to_api_dict


class CoachWorkoutDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: Optional[str] = None
    distance_km: Optional[float] = None
    duration_minutes: Optional[float] = None
    avg_hr: Optional[float] = None
    max_hr: Optional[float] = None
    zones: Optional[dict[str, Any]] = None
    km_splits: list[Any] = Field(default_factory=list)


class CoachActivityStats(BaseModel):
    model_config = ConfigDict(frozen=True)

    km: float
    sessions: int


class CoachGoalContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    objective: str
    goal_type: str
    race_date: Optional[str] = None
    target_time_seconds: Optional[int] = None
    target_distance_km: Optional[float] = None


class CoachTrainingStateContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    phase: Optional[str] = None
    current_week: Optional[int] = None
    total_weeks: int
    continuity_state: Optional[str] = None
    allow_intensity: Optional[bool] = None


class CoachWeeklyTargetContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    target_basis: str
    target_km: Optional[float] = None
    target_duration_minutes: Optional[int] = None
    session_count: int
    confidence: str


class CoachWeeklyReconciliationContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: Optional[str] = None
    reason_codes: list[str] = Field(default_factory=list)


class CoachWeekSessionContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical: dict[str, Any]
    prescription_source: str


class CoachTodayContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    canonical: dict[str, Any]
    prescription_source: str


class CoachReadinessContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    band: str
    score: Optional[float] = None
    confidence: str
    sufficiency_level: str
    reason_codes: list[str] = Field(default_factory=list)
    data_source: str


class CoachTrainingLoadContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    acute_load_7d: float
    load_28d: float
    chronic_weekly_load: float
    acwr: Optional[float] = None
    status: str
    confidence: str
    is_available: bool
    has_sufficient_history: bool
    load_change_percent: Optional[float] = None


class CoachTrainingPacesContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    is_available: bool
    confidence: str
    data: dict[str, Any]


class CoachPerformancePredictionContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    distance: str
    predicted_time: Optional[str] = None
    predicted_pace: Optional[str] = None
    confidence: str
    extrapolation_ratio: Optional[float] = None
    is_strong_extrapolation: Optional[bool] = None


class CoachPerformanceContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    has_data: bool
    predictions: list[CoachPerformancePredictionContext] = Field(default_factory=list)


class CoachContextV2(BaseModel):
    model_config = ConfigDict(frozen=True)

    version: str = "coach_context_v2"
    language: str
    reference_date: str
    goal: CoachGoalContext
    training_state: CoachTrainingStateContext
    stats_7d: CoachActivityStats
    stats_30d: CoachActivityStats
    weekly_target: CoachWeeklyTargetContext
    weekly_reconciliation: CoachWeeklyReconciliationContext
    current_week_sessions: list[CoachWeekSessionContext] = Field(default_factory=list)
    today: CoachTodayContext
    readiness: CoachReadinessContext
    training_load: CoachTrainingLoadContext
    training_paces: CoachTrainingPacesContext
    performance: CoachPerformanceContext
    workout_detail: Optional[CoachWorkoutDetail] = None


def _parse_iso_date(value: Any) -> Optional[date]:
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    if isinstance(value, str):
        try:
            return datetime.fromisoformat(value.replace("Z", "+00:00")).date()
        except ValueError:
            try:
                return date.fromisoformat(value)
            except ValueError:
                return None
    return None


def _build_plan_goal(resolved_goal: Any) -> PlanGoal:
    return build_plan_goal(
        goal_type=resolved_goal.mapped_goal,
        race_date=resolved_goal.race_date,
        target_distance_km=resolved_goal.target_distance_km,
        target_time_seconds=resolved_goal.target_time_sec,
        created_from="user",
    )


def _build_cycle_response(*, resolved_goal: Any, reference_date: date):
    plan_goal = _build_plan_goal(resolved_goal)
    if plan_goal.race_date is not None:
        return build_cycle_calendar_response(
            plan_goal=plan_goal,
            reference_date=reference_date,
            race_plan_start_date=resolved_goal.cycle_start,
            target_time_seconds=resolved_goal.target_time_sec,
        )
    return build_cycle_calendar_response(
        plan_goal=plan_goal,
        reference_date=reference_date,
        cycle_anchor_date=resolved_goal.cycle_start,
        target_time_seconds=resolved_goal.target_time_sec,
    )


def _build_phase_value(*, resolved_goal: Any, reference_date: date) -> str:
    plan_goal = _build_plan_goal(resolved_goal)
    if plan_goal.race_date is not None:
        return build_periodization(
            plan_goal=plan_goal,
            reference_date=reference_date,
            race_plan_start_date=resolved_goal.cycle_start,
        ).phase.value
    return build_periodization(
        plan_goal=plan_goal,
        reference_date=reference_date,
        cycle_anchor_date=resolved_goal.cycle_start,
    ).phase.value


async def _week_prescription_authorities(
    *,
    db: Any,
    user_id: str,
    week_sessions: list[dict[str, Any]],
    reference_date: date,
) -> dict[str, str]:
    week_start = reference_date - timedelta(days=reference_date.weekday())
    week_end = week_start + timedelta(days=6)

    snapshot_docs = await db.training_prescription_snapshots.find(
        {
            "user_id": user_id,
            "planned_date": {"$gte": week_start.isoformat(), "$lte": week_end.isoformat()},
        },
        {"_id": 0},
    ).to_list(1000)
    memory_docs = await db.training_planned_prescription_memory.find(
        {
            "user_id": user_id,
            "planned_date": {"$gte": week_start.isoformat(), "$lte": week_end.isoformat()},
        },
        {"_id": 0},
    ).to_list(1000)

    snapshot_ids = {
        doc.get("prescription_id")
        for doc in snapshot_docs
        if isinstance(doc.get("prescription_id"), str)
    }
    memory_ids = {
        doc.get("prescription_id")
        for doc in memory_docs
        if isinstance(doc.get("prescription_id"), str)
    }

    sources: dict[str, str] = {}
    for session in week_sessions:
        prescription_id = session.get("prescription_id")
        if not isinstance(prescription_id, str):
            continue
        planned_date = _parse_iso_date(session.get("planned_date"))
        if prescription_id in snapshot_ids:
            sources[prescription_id] = "served_snapshot"
        elif (
            prescription_id in memory_ids
            and planned_date is not None
            and planned_date < reference_date
        ):
            sources[prescription_id] = "planned_memory"
        elif session.get("execution_status") == "prescription_unavailable":
            sources[prescription_id] = "unavailable"
        elif planned_date is not None and planned_date >= reference_date:
            sources[prescription_id] = "live_planned"
        else:
            sources[prescription_id] = "unavailable"
    return sources


async def _today_snapshot_doc(
    *,
    db: Any,
    user_id: str,
    today_payload: dict[str, Any],
) -> Optional[dict[str, Any]]:
    prescription_id = today_payload.get("prescription_id")
    if not isinstance(prescription_id, str):
        return None
    return await db.training_prescription_snapshots.find_one(
        {"user_id": user_id, "prescription_id": prescription_id},
        {"_id": 0},
    )


def _normalize_workout_detail(workout: Optional[dict[str, Any]]) -> Optional[CoachWorkoutDetail]:
    if not workout:
        return None

    duration_minutes: Optional[float] = None
    moving_time = workout.get("moving_time")
    if isinstance(moving_time, (int, float)) and not isinstance(moving_time, bool) and moving_time > 0:
        duration_minutes = float(moving_time) / 60.0
    else:
        raw_duration = workout.get("duration_minutes")
        if isinstance(raw_duration, (int, float)) and not isinstance(raw_duration, bool):
            duration_minutes = float(raw_duration)

    distance_km: Optional[float] = None
    raw_distance_km = workout.get("distance_km")
    if isinstance(raw_distance_km, (int, float)) and not isinstance(raw_distance_km, bool):
        distance_km = float(raw_distance_km)
    else:
        raw_distance = workout.get("distance")
        if isinstance(raw_distance, (int, float)) and not isinstance(raw_distance, bool):
            distance_km = float(raw_distance) / 1000.0 if raw_distance >= 1000 else float(raw_distance)

    return CoachWorkoutDetail(
        id=str(workout.get("id")),
        name=workout.get("name"),
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        avg_hr=workout.get("average_heartrate", workout.get("avg_heart_rate")),
        max_hr=workout.get("max_heartrate", workout.get("max_heart_rate")),
        zones=workout.get("effort_zone_distribution"),
        km_splits=list(workout.get("km_splits") or [])[:5],
    )


async def build_coach_context_v2(
    *,
    db: Any,
    user_id: str,
    language: str,
    reference_date: date,
    resolved_goal: Any,
    domain_activities_90: list[Any],
    week_payload: dict[str, Any],
    today_payload: dict[str, Any],
    training_load: TrainingLoadSnapshot,
    readiness_decision: ReadinessDecision,
    readiness_data_source: str,
    training_paces: TrainingPaces,
    performance: PerformanceEstimate,
    workout: Optional[dict[str, Any]] = None,
) -> CoachContextV2:
    cycle_response = _build_cycle_response(
        resolved_goal=resolved_goal,
        reference_date=reference_date,
    )
    training_history = build_training_history(domain_activities_90, reference_date)
    week_sessions = list(((week_payload.get("week") or {}).get("sessions") or []))
    sources_by_id = await _week_prescription_authorities(
        db=db,
        user_id=user_id,
        week_sessions=week_sessions,
        reference_date=reference_date,
    )

    today_snapshot = await _today_snapshot_doc(
        db=db,
        user_id=user_id,
        today_payload=today_payload,
    )
    today_source = (
        "served_snapshot"
        if today_snapshot is not None
        else "live_planned" if str(today_payload.get("status") or "success") == "success"
        else "unavailable"
    )

    current_week_sessions = [
        CoachWeekSessionContext(
            canonical=dict(session),
            prescription_source=source,
        )
        for session in week_sessions
        for source in [sources_by_id.get(session.get("prescription_id"), "live_planned")]
    ]

    training_paces_payload = training_paces_to_api_dict(training_paces)
    predictions = [
        CoachPerformancePredictionContext(
            distance=prediction.distance_label,
            predicted_time=prediction.predicted_time_str,
            predicted_pace=prediction.predicted_pace_str,
            confidence=prediction.confidence,
            extrapolation_ratio=prediction.extrapolation_ratio,
            is_strong_extrapolation=(
                prediction.extrapolation_ratio is not None
                and prediction.extrapolation_ratio > CURVE_NULL_CONFIDENCE_EXTRAPOLATION_RATIO
            ),
        )
        for prediction in performance.predictions
    ]

    return CoachContextV2(
        language=language,
        reference_date=reference_date.isoformat(),
        goal=CoachGoalContext(
            objective=((resolved_goal.user_goal_doc or {}).get("event_name") or resolved_goal.goal_type),
            goal_type=((week_payload.get("goal") or {}).get("goal_type") or resolved_goal.goal_type),
            race_date=(week_payload.get("goal") or {}).get("race_date"),
            target_time_seconds=(week_payload.get("goal") or {}).get("target_time_seconds"),
            target_distance_km=resolved_goal.target_distance_km,
        ),
        training_state=CoachTrainingStateContext(
            phase=_build_phase_value(resolved_goal=resolved_goal, reference_date=reference_date),
            current_week=cycle_response.cycle.current_week,
            total_weeks=cycle_response.cycle.total_weeks,
            continuity_state=(week_payload.get("state") or {}).get("continuity_state"),
            allow_intensity=(week_payload.get("state") or {}).get("allow_intensity"),
        ),
        stats_7d=CoachActivityStats(
            km=training_history.window_7d.distance_km,
            sessions=training_history.window_7d.activity_count,
        ),
        stats_30d=CoachActivityStats(
            km=training_history.window_30d.distance_km,
            sessions=training_history.window_30d.activity_count,
        ),
        weekly_target=CoachWeeklyTargetContext(
            target_basis=((week_payload.get("weekly_target") or {}).get("target_basis") or "distance"),
            target_km=(week_payload.get("weekly_target") or {}).get("target_km"),
            target_duration_minutes=(week_payload.get("weekly_target") or {}).get("target_duration_minutes"),
            session_count=int(((week_payload.get("weekly_target") or {}).get("session_count") or 0)),
            confidence=((week_payload.get("weekly_target") or {}).get("confidence") or "none"),
        ),
        weekly_reconciliation=CoachWeeklyReconciliationContext(
            action=week_payload.get("reconciliation_action"),
            reason_codes=list(week_payload.get("reconciliation_reason_codes") or []),
        ),
        current_week_sessions=current_week_sessions,
        today=CoachTodayContext(
            canonical=dict(today_payload),
            prescription_source=today_source,
        ),
        readiness=CoachReadinessContext(
            band=readiness_decision.band.value,
            score=readiness_decision.score,
            confidence=readiness_decision.confidence.value,
            sufficiency_level=readiness_decision.sufficiency_level.value,
            reason_codes=list(readiness_decision.reason_codes),
            data_source=readiness_data_source,
        ),
        training_load=CoachTrainingLoadContext(
            acute_load_7d=training_load.acute_load_7d,
            load_28d=training_load.load_28d,
            chronic_weekly_load=training_load.chronic_weekly_load,
            acwr=training_load.acwr,
            status=training_load.status,
            confidence=training_load.confidence,
            is_available=training_load.is_available,
            has_sufficient_history=training_load.has_sufficient_history,
            load_change_percent=training_load.load_change_percent,
        ),
        training_paces=CoachTrainingPacesContext(
            is_available=training_paces.confidence != "INSUFFICIENT",
            confidence=training_paces.confidence,
            data=training_paces_payload,
        ),
        performance=CoachPerformanceContext(
            has_data=performance.has_data,
            predictions=predictions,
        ),
        workout_detail=_normalize_workout_detail(workout),
    )


__all__ = ["CoachContextV2", "build_coach_context_v2"]
