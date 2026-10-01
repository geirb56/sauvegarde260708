from __future__ import annotations

import math
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
from workout_analysis_v2 import (
    SIMILAR_HISTORY_WINDOW_DAYS as WORKOUT_ANALYSIS_HISTORY_WINDOW_DAYS,
    WorkoutAnalysisV2Response,
    build_workout_analysis_v2,
    workout_analysis_candidate_date_bounds,
)

COACH_RECENT_WORKOUTS_WINDOW_DAYS = 30
COACH_RECENT_WORKOUTS_MAX_COUNT = 30


class CoachRecentWorkout(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    date: str
    type: str
    name: Optional[str] = None
    distance_km: Optional[float] = None
    duration_minutes: Optional[float] = None
    avg_pace_min_km: Optional[float] = None
    avg_speed_kmh: Optional[float] = None
    avg_heart_rate: Optional[float] = None
    max_heart_rate: Optional[float] = None
    elevation_gain_m: Optional[float] = None


class CoachWorkoutDetail(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    name: Optional[str] = None
    date: Optional[str] = None
    type: Optional[str] = None
    distance_km: Optional[float] = None
    duration_minutes: Optional[float] = None
    avg_hr: Optional[float] = None
    max_hr: Optional[float] = None
    avg_heart_rate: Optional[int] = None
    max_heart_rate: Optional[int] = None
    avg_pace_min_km: Optional[float] = None
    avg_speed_kmh: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    zones: Optional[dict[str, Any]] = None
    km_splits: list[Any] = Field(default_factory=list)
    analysis: Optional[WorkoutAnalysisV2Response] = None


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
    recent_workouts: list[CoachRecentWorkout] = Field(default_factory=list)
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


def _safe_distance_km(workout: dict[str, Any]) -> Optional[float]:
    raw_km = workout.get("distance_km")
    if raw_km is not None and not isinstance(raw_km, bool):
        try:
            val = float(raw_km)
            if math.isfinite(val) and val > 0:
                return round(val, 2)
        except (ValueError, TypeError):
            pass
    raw_m = workout.get("distance")
    if raw_m is not None and not isinstance(raw_m, bool):
        try:
            val = float(raw_m)
            if math.isfinite(val) and val > 0:
                return round(val / 1000.0 if val >= 1000 else val, 2)
        except (ValueError, TypeError):
            pass
    return None


def _safe_duration_minutes(workout: dict[str, Any]) -> Optional[float]:
    moving_time = workout.get("moving_time")
    if moving_time is not None and not isinstance(moving_time, bool):
        try:
            val = float(moving_time)
            if math.isfinite(val) and val > 0:
                return round(val / 60.0, 1)
        except (ValueError, TypeError):
            pass
    raw_dur = workout.get("duration_minutes")
    if raw_dur is not None and not isinstance(raw_dur, bool):
        try:
            val = float(raw_dur)
            if math.isfinite(val) and val > 0:
                return round(val, 1)
        except (ValueError, TypeError):
            pass
    return None


def _safe_hr(val: Any) -> Optional[float]:
    if val is None or isinstance(val, bool):
        return None
    try:
        f = float(val)
        return round(f, 1) if math.isfinite(f) and f > 0 else None
    except (ValueError, TypeError):
        return None


def _safe_pace_min_km(workout: dict[str, Any]) -> Optional[float]:
    raw_pace = workout.get("avg_pace_min_km")
    if raw_pace is not None and not isinstance(raw_pace, bool):
        try:
            val = float(raw_pace)
            if math.isfinite(val) and val > 0:
                return round(val, 2)
        except (ValueError, TypeError):
            pass
    return None


def _safe_speed_kmh(workout: dict[str, Any]) -> Optional[float]:
    raw_speed = workout.get("avg_speed_kmh")
    if raw_speed is not None and not isinstance(raw_speed, bool):
        try:
            val = float(raw_speed)
            if math.isfinite(val) and val > 0:
                return round(val, 2)
        except (ValueError, TypeError):
            pass
    return None


def _safe_elevation(val: Any) -> Optional[float]:
    if val is None or isinstance(val, bool):
        return None
    try:
        f = float(val)
        return round(f, 1) if math.isfinite(f) and f >= 0 else None
    except (ValueError, TypeError):
        return None


def _is_valid_recent_workout(
    workout: dict[str, Any],
    reference_date: date,
    window_days: int = COACH_RECENT_WORKOUTS_WINDOW_DAYS,
) -> bool:
    raw_date = workout.get("date")
    if not raw_date:
        return False
    workout_date = _parse_iso_date(raw_date)
    if workout_date is None:
        return False
    if workout_date > reference_date:
        return False
    cutoff = reference_date - timedelta(days=window_days)
    if workout_date < cutoff:
        return False
    return True


def _normalize_recent_workout(workout: dict[str, Any]) -> CoachRecentWorkout:
    avg_hr = _safe_hr(workout.get("avg_heart_rate", workout.get("average_heartrate")))
    max_hr = _safe_hr(workout.get("max_heart_rate", workout.get("max_heartrate")))
    return CoachRecentWorkout(
        id=str(workout.get("id") or ""),
        date=str(workout.get("date") or ""),
        type=str(workout.get("type") or "workout"),
        name=workout.get("name") if workout.get("name") is not None else None,
        distance_km=_safe_distance_km(workout),
        duration_minutes=_safe_duration_minutes(workout),
        avg_pace_min_km=_safe_pace_min_km(workout),
        avg_speed_kmh=_safe_speed_kmh(workout),
        avg_heart_rate=avg_hr,
        max_heart_rate=max_hr,
        elevation_gain_m=_safe_elevation(workout.get("elevation_gain_m")),
    )


def _normalize_workout_detail(
    workout: Optional[dict[str, Any]],
    analysis: Optional[WorkoutAnalysisV2Response] = None,
) -> Optional[CoachWorkoutDetail]:
    if not workout:
        return None

    duration_minutes = _safe_duration_minutes(workout)
    distance_km = _safe_distance_km(workout)
    raw_avg_hr = workout.get("avg_heart_rate")
    if raw_avg_hr is None:
        raw_avg_hr = workout.get("average_heartrate")
    if raw_avg_hr is None:
        raw_avg_hr = workout.get("avg_hr")
    avg_hr = _safe_hr(raw_avg_hr)

    raw_max_hr = workout.get("max_heart_rate")
    if raw_max_hr is None:
        raw_max_hr = workout.get("max_heartrate")
    if raw_max_hr is None:
        raw_max_hr = workout.get("max_hr")
    max_hr = _safe_hr(raw_max_hr)

    avg_pace = _safe_pace_min_km(workout)
    avg_speed = _safe_speed_kmh(workout)
    elevation = _safe_elevation(workout.get("elevation_gain_m") or workout.get("total_elevation_gain_m"))

    return CoachWorkoutDetail(
        id=str(workout.get("id")),
        name=workout.get("name"),
        date=str(workout.get("date")) if workout.get("date") is not None else None,
        type=str(workout.get("type")) if workout.get("type") is not None else None,
        distance_km=distance_km,
        duration_minutes=duration_minutes,
        avg_hr=float(avg_hr) if avg_hr is not None else None,
        max_hr=float(max_hr) if max_hr is not None else None,
        avg_heart_rate=avg_hr,
        max_heart_rate=max_hr,
        avg_pace_min_km=avg_pace,
        avg_speed_kmh=avg_speed,
        elevation_gain_m=elevation,
        zones=workout.get("effort_zone_distribution"),
        km_splits=list(workout.get("km_splits") or [])[:5],
        analysis=analysis,
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
    workout_analysis: Optional[WorkoutAnalysisV2Response] = None,
    recent_workouts: Optional[list[CoachRecentWorkout]] = None,
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

    if recent_workouts is None and db is not None and hasattr(db, "workouts"):
        lower_bound = (reference_date - timedelta(days=COACH_RECENT_WORKOUTS_WINDOW_DAYS)).isoformat()
        upper_bound = (reference_date + timedelta(days=1)).isoformat()
        cursor = db.workouts.find(
            {
                "user_id": user_id,
                "date": {"$gte": lower_bound, "$lt": upper_bound},
            },
            {"_id": 0},
        )
        if hasattr(cursor, "sort"):
            cursor = cursor.sort("date", -1)
        if hasattr(cursor, "limit"):
            cursor = cursor.limit(COACH_RECENT_WORKOUTS_MAX_COUNT)
        workout_docs = await cursor.to_list(COACH_RECENT_WORKOUTS_MAX_COUNT)
        recent_workouts = [
            _normalize_recent_workout(doc)
            for doc in workout_docs
            if _is_valid_recent_workout(doc, reference_date)
        ]
    elif recent_workouts is None:
        recent_workouts = []

    if workout is not None and workout_analysis is None and db is not None and hasattr(db, "workouts"):
        try:
            lower_bound, upper_bound = workout_analysis_candidate_date_bounds(
                workout.get("date", ""), days=WORKOUT_ANALYSIS_HISTORY_WINDOW_DAYS
            )
            historical_cursor = db.workouts.find(
                {
                    "user_id": user_id,
                    "type": workout.get("type"),
                    "date": {"$gte": lower_bound, "$lt": upper_bound},
                },
                {"_id": 0},
            )
            if hasattr(historical_cursor, "sort"):
                historical_cursor = historical_cursor.sort("date", -1)
            historical = await historical_cursor.to_list(length=200)
            workout_analysis = build_workout_analysis_v2(
                workout=workout,
                historical_workouts=historical,
                language=language,
            )
        except Exception:
            workout_analysis = None

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
        recent_workouts=recent_workouts,
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
        workout_detail=_normalize_workout_detail(workout, workout_analysis),
    )


__all__ = [
    "COACH_RECENT_WORKOUTS_MAX_COUNT",
    "COACH_RECENT_WORKOUTS_WINDOW_DAYS",
    "CoachContextV2",
    "CoachRecentWorkout",
    "CoachWorkoutDetail",
    "build_coach_context_v2",
]
