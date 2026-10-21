"""C352 — read-only loader for Workout Intelligence V3.

Reads only: ``workouts``, ``garmin_activities`` (cached phases / precise type /
local start time) and ``training_prescription_snapshots``. No write, no Garmin
or GCCLI call, no clock. Workout Analysis V2 is reused unchanged as the
source of session structure, phases and the existing similar comparison.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from garmin.domain_adapter import garmin_local_start_time
from training_v2.prescription_snapshot import PrescriptionSnapshot
from workout_analysis_v2 import (
    SIMILAR_HISTORY_WINDOW_DAYS,
    build_workout_analysis_v2,
    workout_analysis_candidate_date_bounds,
)
from workout_analysis_v2_service import (
    _cached_activity_phases,
    _extract_garmin_external_id,
    _fetch_garmin_activity,
    _historical_garmin_sources,
    _is_garmin_workout,
    _reliable_activity_type,
    enrich_workout_from_garmin_activity,
)
from workout_intelligence_v3 import build_workout_intelligence_v3, extract_workout_intelligence_input
from workout_intelligence_v3_models import (
    WIV3PhysiologicalProfile,
    WIV3PrescriptionContext,
    WorkoutIntelligenceV3,
)

logger = logging.getLogger(__name__)

HISTORY_FETCH_LIMIT = 200  # same bound as the Workout Analysis V2 loader


async def _historical_snapshots(db: Any, user_id: str, local_date: Optional[str]) -> list[PrescriptionSnapshot]:
    if local_date is None or not hasattr(db, "training_prescription_snapshots"):
        return []
    try:
        docs = await db.training_prescription_snapshots.find(
            {"user_id": user_id, "planned_date": local_date}, {"_id": 0},
        ).to_list(length=10)
    except Exception:
        logger.warning("Prescription snapshots unavailable for user_id=%s", user_id)
        return []
    snapshots = []
    for doc in docs or []:
        try:
            snapshots.append(PrescriptionSnapshot(**doc))
        except Exception:
            continue
    return snapshots


async def load_scoped_workout_intelligence_v3(
    *, db: Any, user_id: str, workout_id: str, language: str,
) -> Optional[tuple[dict[str, Any], Optional[WorkoutIntelligenceV3]]]:
    workout = await db.workouts.find_one({"id": workout_id, "user_id": user_id}, {"_id": 0})
    if workout is None:
        return None

    phases = None
    current_type = None
    local_date = None
    if _is_garmin_workout(workout):
        ext_id = _extract_garmin_external_id(workout)
        if ext_id:
            activity_doc = await _fetch_garmin_activity(db, user_id, ext_id)
            if activity_doc:
                workout = enrich_workout_from_garmin_activity(workout, activity_doc)
                phases = _cached_activity_phases(activity_doc)
                current_type = _reliable_activity_type(activity_doc)
                local_start = garmin_local_start_time(activity_doc)
                local_date = local_start[:10] if local_start and len(local_start) >= 10 else None

    try:
        lower_bound, upper_bound = workout_analysis_candidate_date_bounds(
            workout.get("date", ""), days=SIMILAR_HISTORY_WINDOW_DAYS,
        )
        historical_workouts = await (
            db.workouts.find(
                {
                    "user_id": user_id,
                    "type": workout.get("type"),
                    "date": {"$gte": lower_bound, "$lt": upper_bound},
                },
                {"_id": 0},
            )
            .sort("date", -1)
            .to_list(length=HISTORY_FETCH_LIMIT)
        )
        # Superset of the V2 similar selection: V2 only reads its own ids.
        historical_phases, activity_types = await _historical_garmin_sources(db, user_id, historical_workouts)
        if current_type:
            activity_types[str(workout.get("id") or "")] = current_type
        v2_analysis = build_workout_analysis_v2(
            workout=workout,
            historical_workouts=historical_workouts,
            language=language,
            phases=phases,
            historical_phases=historical_phases,
            activity_types=activity_types,
        )
        same_day = sum(
            1 for item in historical_workouts
            if local_date is not None and str(item.get("date") or "")[:10] == local_date
            and str(item.get("id") or "") != str(workout.get("id") or "")
        )
        prescription = WIV3PrescriptionContext(
            local_date=local_date,
            snapshots=await _historical_snapshots(db, user_id, local_date),
            same_day_session_count=1 + same_day,
        )
        data = extract_workout_intelligence_input(
            workout,
            historical_workouts,
            v2_analysis=v2_analysis,
            activity_types=activity_types,
            historical_phases=historical_phases,
            # No personal LT1/LT2 is persisted in RunIndex today (documented blocker).
            profile=WIV3PhysiologicalProfile(lt_source_status="not_persisted"),
            prescription=prescription,
        )
        intelligence = build_workout_intelligence_v3(data, language)
    except Exception:
        logger.exception("Workout Intelligence V3 unavailable for workout_id=%s", workout_id)
        intelligence = None
    return workout, intelligence
