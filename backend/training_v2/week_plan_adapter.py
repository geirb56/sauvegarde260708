"""PR165 — WeeklyPlan V2 → legacy JSON adapter.

Design rules
------------
- PURE display/formatting only: no prescription, no recalculation.
- All distances/durations come from WeeklyPlan V2 sessions.
- Workout type mapping is DISPLAY-ONLY: rename V2 labels to legacy API labels.
- details is a simple text string — no invented HR ranges, no invented paces.
- estimated_tss: None for active sessions, 0 for rest (unchanged doctrine).
- total_tss: None.

FORBIDDEN in this module
------------------------
- compute_target_km
- reprise_durations
- compute_long_run_km
- apply_resume_guard
- Any re-calculation of distance or duration
- Any re-selection of workout type
"""

from __future__ import annotations

from typing import Optional

from .workout_generator import WeeklyPlan, WeeklyTarget

# ---------------------------------------------------------------------------
# Display-only type mapping: V2 workout_type → legacy API type label
# ---------------------------------------------------------------------------
# This mapping is DISPLAY-ONLY.  It does NOT change the physiological nature
# of the session — it only adapts V2 vocabulary to the legacy frontend contract.
#
# V2          → Legacy API
# rest        → rest
# recovery    → recovery
# easy        → endurance        (easy aerobic = endurance fondamentale)
# steady      → endurance        (comfortably steady, still aerobic — no tempo label invented)
# quality     → tempo            (generic hard session — most neutral label; no threshold invented)
# long_easy   → long_run         (long easy run)
#
# If steady/quality mapping changes in future, update this table and the
# RUNINDEX_PR165_REPORT.md mapping table — nowhere else.
_WORKOUT_TYPE_DISPLAY_MAP: dict[str, str] = {
    "rest": "rest",
    "recovery": "recovery",
    "easy": "endurance",
    "steady": "endurance",
    "quality": "tempo",
    "long_easy": "long_run",
}

# ---------------------------------------------------------------------------
# Display-only intensity mapping: V2 intensity_class → legacy API intensity
# ---------------------------------------------------------------------------
_INTENSITY_DISPLAY_MAP: dict[str, str] = {
    "rest": "rest",
    "low": "easy",
    "moderate": "moderate",
    "high": "hard",
}


def _display_type(workout_type: str) -> str:
    """Map V2 workout_type to legacy API type label (display only)."""
    return _WORKOUT_TYPE_DISPLAY_MAP.get(workout_type, workout_type)


def _display_intensity(intensity_class: str) -> str:
    """Map V2 intensity_class to legacy API intensity label (display only)."""
    return _INTENSITY_DISPLAY_MAP.get(intensity_class, intensity_class)


def _build_details(
    workout_type: str,
    duration_minutes: Optional[int],
    distance_km: Optional[float],
    target_basis: str,
) -> str:
    """Build a simple, honest details string.

    RULES:
    - Never invent HR ranges (120-135 / 135-150 / etc.) from static defaults.
    - Never invent paces.
    - Display duration and/or distance that are already known from V2.
    """
    display = _display_type(workout_type)

    if workout_type == "rest":
        return "Récupération complète"

    parts: list[str] = []

    # Duration part
    if duration_minutes is not None and duration_minutes > 0:
        parts.append(f"{duration_minutes} min")
    elif target_basis == "distance" and distance_km is not None:
        # No duration available for distance-based weeks — omit
        pass

    # Distance part (only for distance-based or when available)
    if distance_km is not None and distance_km > 0:
        parts.append(f"{distance_km:.1f} km")

    # Session label
    label_map = {
        "rest": "repos",
        "recovery": "récupération active",
        "easy": "endurance facile",
        "steady": "endurance soutenue",
        "quality": "travail spécifique",
        "long_easy": "sortie longue facile",
    }
    label = label_map.get(workout_type, display)
    parts.append(label)

    return " • ".join(parts) if parts else display


def adapt_weekly_plan_to_legacy(
    weekly_plan: WeeklyPlan,
    weekly_target: WeeklyTarget,
    phase: str,
) -> dict:
    """Convert a WeeklyPlan V2 to the legacy /training/week-plan JSON contract.

    This is the ONLY function in the week-plan pipeline that may produce
    display-oriented transformations.  It MUST NOT:
    - recalculate distances or durations
    - change workout types beyond the display mapping table
    - call compute_target_km, reprise_durations, compute_long_run_km,
      apply_resume_guard, or any prescription function

    Parameters
    ----------
    weekly_plan : WeeklyPlan V2 (source of truth for sessions).
    weekly_target : WeeklyTarget V2 (source of truth for target metadata).
    phase : current training phase string (display/focus text only).

    Returns
    -------
    Legacy plan dict compatible with the /training/week-plan JSON contract.
    """
    sessions = []
    for s in weekly_plan.sessions:
        is_rest = s.workout_type == "rest"
        # duration: rest days always "0min"; active sessions use V2 value or "0min" if absent.
        if is_rest:
            dur_str = "0min"
        elif s.duration_minutes is not None and s.duration_minutes > 0:
            dur_str = f"{s.duration_minutes}min"
        else:
            dur_str = "0min"
        session = {
            "day": s.day,
            "type": _display_type(s.workout_type),
            "duration": dur_str,
            "details": _build_details(
                s.workout_type,
                s.duration_minutes,
                s.distance_km,
                weekly_plan.target_basis,
            ),
            "intensity": _display_intensity(s.intensity_class),
            "estimated_tss": 0 if is_rest else None,
            "distance_km": s.distance_km if not is_rest else 0,
        }
        sessions.append(session)

    # Focus text — display only, based on phase
    focus_texts = {
        "build": "Volume en endurance fondamentale",
        "deload": "Récupération active — réduction du volume",
        "intensification": "Travail spécifique — seuil et tempo",
        "taper": "Affûtage — maintien intensité, réduction volume",
        "race": "Semaine de course — fraîcheur maximale",
    }
    focus = focus_texts.get(phase, "Construction aérobie")

    # is_reprise: deep_reprise or partial_reprise continuity states
    is_reprise = weekly_target.continuity_state in ("deep_reprise", "partial_reprise")

    plan = {
        "focus": focus,
        "planned_load": None,
        "weekly_km": weekly_plan.planned_km,
        "weekly_minutes": weekly_plan.planned_duration_minutes,
        "target_basis": weekly_plan.target_basis,
        "reprise": is_reprise,
        "sessions": sessions,
        "total_tss": None,
        "advice": _build_advice(weekly_target, weekly_plan, phase),
    }

    return plan


def _build_advice(weekly_target: WeeklyTarget, weekly_plan: WeeklyPlan, phase: str) -> str:
    """Build a simple advice string from V2 data — no invented physiology."""
    state = weekly_target.continuity_state
    basis = weekly_target.target_basis

    if state == "deep_reprise":
        mins = weekly_plan.planned_duration_minutes or 0
        return (
            f"Reprise progressive : ~{mins} min faciles cette semaine. "
            "On augmente la durée progressivement ; l'intensité viendra plus tard."
        )
    if state == "partial_reprise":
        if basis == "duration":
            mins = weekly_plan.planned_duration_minutes or 0
            return f"Reprise partielle : ~{mins} min d'entraînement cette semaine."
        else:
            km = weekly_plan.planned_km or 0
            return f"Reprise partielle : ~{km:.1f} km cette semaine."

    if basis == "duration":
        mins = weekly_plan.planned_duration_minutes or 0
        return f"Semaine {phase} : ~{mins} min d'entraînement planifiées."
    else:
        km = weekly_plan.planned_km or 0
        return f"Semaine {phase} : ~{km:.1f} km planifiés."
