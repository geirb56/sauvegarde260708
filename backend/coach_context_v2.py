from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field

from config.training_goals import GOAL_CONFIG
from training_v2.performance_model import (
    CURVE_NULL_CONFIDENCE_EXTRAPOLATION_RATIO,
    PerformanceEstimate,
)
from training_v2.periodization import build_periodization
from training_v2.plan_goal import PlanGoal, build_plan_goal
from training_v2.readiness_decision import ReadinessDecision
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
    current_week: int
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

    day: str
    planned_date: Optional[str] = None
    prescription_id: Optional[str] = None
    prescription_source: str
    workout_type: Optional[str] = None
    intensity_class: Optional[str] = None
    distance_km: Optional[float] = None
    duration_minutes: Optional[int] = None
    reason_codes: list[str] = Field(default_factory=list)
    matching_status: Optional[str] = None
    adherence_status: Optional[str] = None
    execution_status: Optional[str] = None
    structured_status: Optional[str] = None
    session_modified_from_planned: Optional[bool] = None
    structured: Optional[dict[str, Any]] = None


class CoachTodayContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    status: str
    date: Optional[str] = None
    day: Optional[str] = None
    prescription_id: Optional[str] = None
    prescription_source: str
    planned_session: Optional[dict[str, Any]] = None
    served_prescription: Optional[dict[str, Any]] = None
    session_modified_from_planned: Optional[bool] = None
    adaptation_applied: Optional[bool] = None
    adaptation_action: Optional[str] = None
    adaptation_reason: Optional[str] = None
    reason_codes: list[str] = Field(default_factory=list)
    structured_workout: Optional[dict[str, Any]] = None
    structured_status: Optional[str] = None


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
    stats_28d: CoachActivityStats
    weekly_target: CoachWeeklyTargetContext
    weekly_reconciliation: CoachWeeklyReconciliationContext
    current_week_sessions: list[CoachWeekSessionContext] = Field(default_factory=list)
    today: CoachTodayContext
    readiness: CoachReadinessContext
    training_load: CoachTrainingLoadContext
    training_paces: CoachTrainingPacesContext
    performance: CoachPerformanceContext
    workout_detail: Optional[CoachWorkoutDetail] = None


def _activity_date(activity: Any) -> Optional[date]:
    start_time = getattr(activity, "start_time", None)
    if isinstance(start_time, datetime):
        return start_time.date()
    if isinstance(start_time, date):
        return start_time
    if isinstance(start_time, str):
        try:
            return datetime.fromisoformat(start_time.replace("Z", "+00:00")).date()
        except ValueError:
            return None
    return None


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


def _count_recent_stats(
    activities: list[Any],
    *,
    reference_date: date,
    days: int,
) -> CoachActivityStats:
    start_date = reference_date - timedelta(days=days - 1)
    km_total = 0.0
    sessions = 0
    for activity in activities:
        if (getattr(activity, "activity_type", None) or "").strip().lower() != "running":
            continue
        activity_date = _activity_date(activity)
        if activity_date is None or activity_date < start_date or activity_date > reference_date:
            continue
        km_total += (getattr(activity, "distance_m", None) or 0.0) / 1000.0
        sessions += 1
    return CoachActivityStats(km=round(km_total, 1), sessions=sessions)


def _current_week_index(
    *,
    reference_date: date,
    cycle_start: date,
    total_weeks: int,
) -> int:
    cycle_start_dt = datetime(
        cycle_start.year,
        cycle_start.month,
        cycle_start.day,
        tzinfo=timezone.utc,
    )
    reference_dt = datetime(
        reference_date.year,
        reference_date.month,
        reference_date.day,
        tzinfo=timezone.utc,
    )
    if reference_dt < cycle_start_dt:
        return 0
    return min(((reference_dt - cycle_start_dt).days // 7) + 1, total_weeks + 1)


def _build_plan_goal(resolved_goal: Any) -> PlanGoal:
    return build_plan_goal(
        goal_type=resolved_goal.mapped_goal,
        race_date=resolved_goal.race_date,
        target_distance_km=resolved_goal.target_distance_km,
        target_time_seconds=resolved_goal.target_time_sec,
        created_from="user",
    )


def _phase_value(*, resolved_goal: Any, reference_date: date) -> str:
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
) -> tuple[dict[str, str], dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    week_start = reference_date - timedelta(days=reference_date.weekday())
    week_end = week_start + timedelta(days=6)

    snapshot_docs = await db.training_prescription_snapshots.find(
        {
            "user_id": user_id,
            "planned_date": {"$gte": week_start.isoformat(), "$lte": week_end.isoformat()},
        },
        {"_id": 0, "prescription_id": 1},
    ).to_list(1000)
    memory_docs = await db.training_planned_prescription_memory.find(
        {
            "user_id": user_id,
            "planned_date": {"$gte": week_start.isoformat(), "$lte": week_end.isoformat()},
        },
        {"_id": 0, "prescription_id": 1},
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

    snapshot_by_id = {
        doc["prescription_id"]: doc
        for doc in snapshot_docs
        if isinstance(doc.get("prescription_id"), str)
    }
    memory_by_id = {
        doc["prescription_id"]: doc
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
    return sources, snapshot_by_id, memory_by_id


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


def _snapshot_prescription(snapshot_doc: Optional[dict[str, Any]]) -> Optional[dict[str, Any]]:
    if not snapshot_doc:
        return None
    return {
        "day": snapshot_doc.get("day"),
        "workout_type": snapshot_doc.get("workout_type"),
        "intensity_class": snapshot_doc.get("intensity_class"),
        "distance_km": snapshot_doc.get("distance_km"),
        "duration_minutes": snapshot_doc.get("duration_minutes"),
        "reason_codes": list(snapshot_doc.get("reason_codes") or []),
    }


def _session_view_from_authority(
    session: dict[str, Any],
    *,
    source: str,
    snapshot_doc: Optional[dict[str, Any]],
    memory_doc: Optional[dict[str, Any]],
) -> dict[str, Any]:
    authority = snapshot_doc if source == "served_snapshot" else memory_doc if source == "planned_memory" else None
    if authority is None:
        return dict(session)

    merged = dict(session)
    merged["workout_type"] = authority.get("workout_type")
    merged["intensity_class"] = authority.get("intensity_class")
    merged["distance_km"] = authority.get("distance_km")
    merged["duration_minutes"] = authority.get("duration_minutes")
    merged["reason_codes"] = list(authority.get("reason_codes") or [])
    merged["structured"] = authority.get("structured")
    if source == "served_snapshot":
        merged["session_modified_from_planned"] = authority.get("modified_from_planned")
        merged["structured_status"] = "served_snapshot"
    elif source == "planned_memory":
        merged["structured_status"] = "planned_memory"
    return merged


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
    total_weeks = GOAL_CONFIG[resolved_goal.goal_type]["cycle_weeks"]
    week_sessions = list(((week_payload.get("week") or {}).get("sessions") or []))
    sources_by_id, snapshot_by_id, memory_by_id = await _week_prescription_authorities(
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
            day=str(materialized_session.get("day")),
            planned_date=materialized_session.get("planned_date"),
            prescription_id=materialized_session.get("prescription_id"),
            prescription_source=source,
            workout_type=materialized_session.get("workout_type"),
            intensity_class=materialized_session.get("intensity_class"),
            distance_km=materialized_session.get("distance_km"),
            duration_minutes=materialized_session.get("duration_minutes"),
            reason_codes=list(materialized_session.get("reason_codes") or []),
            matching_status=materialized_session.get("matching_status"),
            adherence_status=materialized_session.get("adherence_status"),
            execution_status=materialized_session.get("execution_status"),
            structured_status=materialized_session.get("structured_status"),
            session_modified_from_planned=materialized_session.get("session_modified_from_planned"),
            structured=materialized_session.get("structured"),
        )
        for session in week_sessions
        for source in [sources_by_id.get(session.get("prescription_id"), "live_planned")]
        for materialized_session in [_session_view_from_authority(
            session,
            source=source,
            snapshot_doc=snapshot_by_id.get(session.get("prescription_id")),
            memory_doc=memory_by_id.get(session.get("prescription_id")),
        )]
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
            phase=_phase_value(resolved_goal=resolved_goal, reference_date=reference_date),
            current_week=_current_week_index(
                reference_date=reference_date,
                cycle_start=resolved_goal.cycle_start,
                total_weeks=total_weeks,
            ),
            total_weeks=total_weeks,
            continuity_state=(week_payload.get("state") or {}).get("continuity_state"),
            allow_intensity=(week_payload.get("state") or {}).get("allow_intensity"),
        ),
        stats_7d=_count_recent_stats(domain_activities_90, reference_date=reference_date, days=7),
        stats_28d=_count_recent_stats(domain_activities_90, reference_date=reference_date, days=28),
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
            status=str(today_payload.get("status") or "success"),
            date=today_payload.get("date"),
            day=today_payload.get("day"),
            prescription_id=today_payload.get("prescription_id"),
            prescription_source=today_source,
            planned_session=today_payload.get("planned_session"),
            served_prescription=(
                _snapshot_prescription(today_snapshot)
                if today_snapshot is not None
                else today_payload.get("served_prescription")
            ),
            session_modified_from_planned=(
                today_snapshot.get("modified_from_planned")
                if today_snapshot is not None
                else today_payload.get("session_modified_from_planned")
            ),
            adaptation_applied=(
                (today_snapshot.get("adaptation_action") not in (None, "KEEP"))
                if today_snapshot is not None
                else today_payload.get("adaptation_applied")
            ),
            adaptation_action=(
                today_snapshot.get("adaptation_action")
                if today_snapshot is not None
                else today_payload.get("adaptation_action")
            ),
            adaptation_reason=(
                ", ".join(today_snapshot.get("adaptation_reason_codes") or [])
                if today_snapshot is not None
                else today_payload.get("adaptation_reason")
            ),
            reason_codes=(
                list(today_snapshot.get("reason_codes") or [])
                if today_snapshot is not None
                else list(today_payload.get("reason_codes") or [])
            ),
            structured_workout=(
                today_snapshot.get("structured")
                if today_snapshot is not None
                else today_payload.get("structured_workout")
            ),
            structured_status=("today_served" if today_snapshot is not None else today_payload.get("structured_status")),
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
