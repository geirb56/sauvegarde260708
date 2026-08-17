from __future__ import annotations

from .workout_generator import WeeklyPlan


_TYPE_MAP = {
    "rest": "rest",
    "recovery": "recovery",
    "easy": "endurance",
    "steady": "tempo",
    "quality": "threshold",
    "long_easy": "long_run",
}

_INTENSITY_MAP = {
    "rest": "rest",
    "low": "easy",
    "moderate": "moderate",
    "high": "hard",
}

_PHASE_INFO = {
    "base": {"description": "Base aérobie", "advice": "Construire la régularité."},
    "build": {"description": "Montée en charge", "advice": "Progression contrôlée."},
    "specific": {"description": "Spécifique objectif", "advice": "Séances orientées objectif."},
    "taper": {"description": "Affûtage", "advice": "Réduire le volume, garder la fraîcheur."},
    "race": {"description": "Semaine course", "advice": "Prioriser récupération et exécution."},
    "consolidation": {"description": "Consolidation", "advice": "Stabiliser les acquis."},
}


def build_runtime_phase_info(phase: str) -> dict:
    return _PHASE_INFO.get(phase, {"description": phase, "advice": ""})


def adapt_weekly_plan_to_runtime_payload(
    *,
    weekly_plan: WeeklyPlan,
    phase: str,
    continuity_state: str,
    paces: dict,
) -> dict:
    sessions = []
    for session in weekly_plan.sessions:
        session_type = _TYPE_MAP.get(session.workout_type, session.workout_type)
        if session.duration_minutes is not None:
            duration = f"{session.duration_minutes}min"
        elif session.workout_type == "rest":
            duration = "0min"
        else:
            duration = "N/A"
        details_parts = []
        if session.distance_km is not None:
            details_parts.append(f"{round(session.distance_km, 1)} km")
        easy_pace = paces.get("z1")
        quality_pace = paces.get("z3")
        if session.workout_type in ("easy", "recovery", "long_easy") and easy_pace:
            details_parts.append(f"allure {easy_pace}")
        elif session.workout_type in ("steady", "quality") and quality_pace:
            details_parts.append(f"allure {quality_pace}")
        details = " • ".join([p for p in details_parts if p]) or "Séance planifiée"
        sessions.append(
            {
                "day": session.day,
                "type": session_type,
                "duration": duration,
                "details": details,
                "intensity": _INTENSITY_MAP.get(session.intensity_class, "easy"),
                # Compatibility-only placeholder: V2 runtime migration keeps the key
                # without reintroducing legacy physiological scoring logic.
                "estimated_tss": 0,
                "distance_km": session.distance_km if session.distance_km is not None else 0,
            }
        )

    return {
        "focus": phase,
        "planned_load": None,
        "weekly_km": weekly_plan.planned_km,
        "weekly_minutes": weekly_plan.planned_duration_minutes,
        "reprise": continuity_state in ("deep_reprise", "partial_reprise", "reprise_exit"),
        "sessions": sessions,
        "total_tss": 0,
        "advice": build_runtime_phase_info(phase).get("advice", ""),
    }
