"""
CardioCoach - Training Engine

Periodization engine and training load management.
Calculations based on:
- ACWR (Acute:Chronic Workload Ratio)
- TSB (Training Stress Balance)
- Preparation phases (Build, Intensification, Taper, Race)

Usage:
    from training_engine import (
        build_training_context,
        determine_phase,
        determine_target_load,
        compute_acwr
    )
"""

import datetime
from typing import Dict, Optional, List


# ============================================================
# CONFIGURATION BY GOAL
# ============================================================

GOAL_CONFIG = {
    "5K": {
        "cycle_weeks": 6,
        "long_run_ratio": 0.25,
        "intensity_pct": 20,
        "description": "5 kilometers"
    },
    "10K": {
        "cycle_weeks": 8,
        "long_run_ratio": 0.30,
        "intensity_pct": 18,
        "description": "10 kilometers"
    },
    "SEMI": {
        "cycle_weeks": 12,
        "long_run_ratio": 0.35,
        "intensity_pct": 15,
        "description": "Half-marathon"
    },
    "MARATHON": {
        "cycle_weeks": 16,
        "long_run_ratio": 0.40,
        "intensity_pct": 12,
        "description": "Marathon"
    },
    "ULTRA": {
        "cycle_weeks": 20,
        "long_run_ratio": 0.45,
        "intensity_pct": 10,
        "description": "Ultra-trail"
    }
}


# ============================================================
# WEEKLY VOLUME — SINGLE SOURCE OF TRUTH
# Shared by the detailed week plan (llm_coach.generate_cycle_week /
# coach_service._deterministic_plan) AND the full-cycle overview
# (server.py /training/full-cycle) so the displayed target_km always
# matches the sum of the generated sessions.
# ============================================================

# Recommended weekly volume bounds (km/week) and long-run bounds per goal
VOLUME_GOAL_CONFIG = {
    "5K": {"min": 15, "max": 45, "sessions": 3, "long_min": 8, "long_max": 10},
    "10K": {"min": 20, "max": 60, "sessions": 3, "long_min": 10, "long_max": 14},
    "SEMI": {"min": 30, "max": 80, "sessions": 4, "long_min": 16, "long_max": 18},
    "MARATHON": {"min": 40, "max": 120, "sessions": 4, "long_min": 28, "long_max": 32},
    "ULTRA": {"min": 50, "max": 150, "sessions": 5, "long_min": 35, "long_max": 45},
}

# Volume modulation per training phase
PHASE_VOLUME_MULTIPLIERS = {"build": 1.0, "deload": 0.7, "intensification": 1.05, "taper": 0.5, "race": 0.3}


def compute_target_km(current_weekly_km: float, goal: str, phase: str) -> int:
    """Single source of truth for weekly target volume (km).

    current_weekly_km: athlete's recent average weekly volume (km_28 / 4)
    goal: 5K / 10K / SEMI / MARATHON / ULTRA
    phase: build / deload / intensification / taper / race
    """
    config = VOLUME_GOAL_CONFIG.get(goal, VOLUME_GOAL_CONFIG["SEMI"])
    volume_min = max(current_weekly_km, config["min"])
    base = max(volume_min, min(config["max"], round(current_weekly_km * 1.07)))
    return round(base * PHASE_VOLUME_MULTIPLIERS.get(phase, 1.0))


def compute_long_run_km(target_km: float, goal: str) -> int:
    """Long-run distance derived from target volume, bounded by goal limits."""
    config = VOLUME_GOAL_CONFIG.get(goal, VOLUME_GOAL_CONFIG["SEMI"])
    span = config["max"] - config["min"]
    ratio = (target_km - config["min"]) / span if span > 0 else 0.5
    ratio = max(0.0, min(1.0, ratio))
    long_run = round(config["long_min"] + ratio * (config["long_max"] - config["long_min"]))
    return max(config["long_min"], min(config["long_max"], long_run))


# ============================================================
# PACE FROM VMA — SINGLE SOURCE OF TRUTH
# All displayed target paces are derived from the estimated VMA:
#   speed (km/h) = VMA * pct   ·   pace (min/km) = 60 / speed
# %VMA reference: 60 recovery(Z1) · 65 active recovery · 70 very easy ·
#   75 base endurance · 80 hard endurance (top Z2) · 85-90 threshold/tempo ·
#   95-100 long intervals · 100-105 short intervals.
# ============================================================

def vma_pace(vma_kmh: float, pct: float) -> str:
    """Target pace 'MM:SS' per km at a given fraction of VMA."""
    speed = (vma_kmh or 0) * pct
    if speed <= 0:
        return "--:--"
    pace_min = 60.0 / speed
    m = int(pace_min)
    s = int(round((pace_min - m) * 60))
    if s >= 60:
        m += 1
        s -= 60
    return f"{m}:{s:02d}"


def vma_pace_range(vma_kmh: float, pct_low: float, pct_high: float) -> str:
    """Pace range 'slow-fast' between two %VMA (pct_low < pct_high => slower shown first)."""
    return f"{vma_pace(vma_kmh, pct_low)}-{vma_pace(vma_kmh, pct_high)}"


def adapt_session_to_readiness(planned_session: Dict, recommendation: str,
                               recommendation_color: str, run_readiness: Optional[float],
                               vma: Optional[float]):
    """Adapt today's planned session to the Run Readiness recommendation.

    Run Readiness is the SOURCE OF TRUTH: an EASY RUN / REST recommendation can
    NEVER leave the session unchanged (except a planned Rest day). Target paces
    are recomputed from the estimated VMA.

    Returns (adaptive_session: dict, adaptation_applied: bool, adaptation_reason: str).
    """
    import re
    adaptive = dict(planned_session)
    applied = False
    reason = ""

    rec_upper = (recommendation or "").upper().replace(" ", "")
    session_type = (planned_session.get("type") or "").lower()
    is_rest_type = session_type in ("rest", "repos") or planned_session.get("intensity") == "rest"
    original_distance = planned_session.get("distance_km", 0) or 0
    original_tss = planned_session.get("estimated_tss", 0) or 0
    _dm = re.match(r"(\d+)", str(planned_session.get("duration", "0min")))
    original_mins = int(_dm.group(1)) if _dm else 0

    def dist_from(pct_mid, minutes):
        if vma and minutes:
            return round((vma * pct_mid) * (minutes / 60.0), 1)
        return None

    if is_rest_type:
        # A planned rest day stays a rest day regardless of recommendation.
        return adaptive, applied, reason

    if rec_upper == "REST" or recommendation_color == "red":
        if run_readiness is not None and run_readiness < 40:
            # High fatigue -> complete rest, no pace displayed.
            applied = True
            reason = "Fatigue importante - repos complet recommandé"
            adaptive.update({
                "type": "Rest", "intensity": "rest", "duration": "0min",
                "distance_km": 0, "estimated_tss": 0,
                "details": "Repos complet • Récupération totale (aucune allure)",
            })
        else:
            # Moderate fatigue -> active recovery 20-30 min @ 60-65% VMA, Z1.
            applied = True
            reason = "Fatigue modérée - séance convertie en récupération active"
            rec_mins = 25
            dist = dist_from(0.625, rec_mins) or round(original_distance * 0.4, 1)
            pace = vma_pace_range(vma, 0.60, 0.65) if vma else None
            adaptive.update({
                "type": "Recovery", "intensity": "recovery", "duration": f"{rec_mins}min",
                "distance_km": dist, "estimated_tss": int(original_tss * 0.4),
                "details": (f"{dist} km • {pace}/km • HR < 130 bpm • Zone 1 (60-65% VMA)"
                            if pace else f"{dist} km • Allure très facile • HR < 130 bpm • Zone 1"),
            })
        return adaptive, applied, reason

    if rec_upper in ("EASYRUN", "EASY") or recommendation_color == "yellow":
        # EASY RUN — always eases the session (even a planned Endurance run).
        # Pace target 65-70% VMA, duration -15%.
        applied = True
        new_mins = int(original_mins * 0.85) if original_mins else 0
        pace = vma_pace_range(vma, 0.65, 0.70) if vma else None
        hard = any(x in session_type for x in ["interval", "threshold", "tempo", "fartlek", "fractionn", "seuil"])
        dist = dist_from(0.675, new_mins) or round(original_distance * (0.8 if hard else 0.85), 1)
        reason = ("Easy run recommandé - séance dure convertie en endurance facile"
                  if hard else "Easy run recommandé - endurance ralentie (65-70% VMA)")
        adaptive.update({
            "type": "Endurance", "intensity": "easy",
            "duration": f"{new_mins}min" if new_mins else planned_session.get("duration", "0min"),
            "distance_km": dist, "estimated_tss": int(original_tss * 0.75),
            "details": (f"{dist} km • {pace}/km • HR 130-145 bpm • Zone 2 (65-70% VMA)"
                        if pace else f"{dist} km • Allure facile • HR 130-145 bpm • Zone 2"),
        })
        return adaptive, applied, reason

    # RUN HARD (green): no adaptation, keep planned session (paces/HR unchanged).
    return adaptive, applied, reason


# Safety thresholds
ACWR_SAFE_MIN = 0.8
ACWR_SAFE_MAX = 1.3
ACWR_DANGER = 1.5
TSB_FATIGUE_THRESHOLD = -20
TSB_FRESH_THRESHOLD = 10


# ============================================================
# BASE CALCULATIONS
# ============================================================

def compute_week_number(start_date: datetime.date) -> int:
    """Calculates the week number since the start of the cycle."""
    today = datetime.date.today()
    delta_days = (today - start_date).days
    return max(1, delta_days // 7 + 1)


def compute_acwr(load_7: float, load_28: float) -> float:
    """
    Calculates the ACWR (Acute:Chronic Workload Ratio).

    - < 0.8: Under-training
    - 0.8-1.3: Optimal zone
    - 1.3-1.5: Risk zone
    - > 1.5: Injury danger
    """
    if load_28 == 0:
        return 1.0
    chronic_avg = load_28 / 4  # Average over 4 weeks
    return round(load_7 / chronic_avg, 2)


def compute_tsb(ctl: float, atl: float) -> float:
    """
    Calculates the TSB (Training Stress Balance).
    TSB = CTL - ATL

    - Negative: Accumulated fatigue
    - Positive: Freshness
    - Ideal for race: +5 to +15
    """
    return round(ctl - atl, 1)


def compute_monotony(daily_loads: List[float]) -> float:
    """
    Calculates training monotony.
    Monotony = Mean / Standard Deviation

    - < 1.5: Good variety
    - > 2.0: Too monotonous (overtraining risk)
    """
    if not daily_loads or len(daily_loads) < 2:
        return 0

    avg = sum(daily_loads) / len(daily_loads)
    variance = sum((x - avg) ** 2 for x in daily_loads) / len(daily_loads)
    std = variance ** 0.5

    if std == 0:
        return 0
    return round(avg / std, 2)


def compute_strain(weekly_load: float, monotony: float) -> float:
    """
    Calculates training strain.
    Strain = Load × Monotony

    Indicator of overall stress on the body.
    """
    return round(weekly_load * monotony, 0)


# ============================================================
# PREPARATION PHASES
# ============================================================

def determine_phase(week: int, total_weeks: int) -> str:
    """
    Determines the preparation phase based on the week.

    Phases:
    - build: Base building (60% of cycle)
    - deload: Recovery week (mid-cycle)
    - intensification: Intensity increase
    - taper: Pre-race taper (last 2 weeks)
    - race: Race week
    """
    if week >= total_weeks:
        return "race"

    if week >= total_weeks - 2:
        return "taper"

    # Deload week in the middle
    if week == total_weeks // 2:
        return "deload"

    # Deload week every 4 weeks
    if week > 4 and week % 4 == 0:
        return "deload"

    if week < total_weeks * 0.6:
        return "build"

    return "intensification"


def get_phase_description(phase: str, lang: str = "en") -> Dict:
    """Return phase description and advice in the requested language."""
    phases_en = {
        "build": {
            "name": "Build",
            "description": "Aerobic base development phase",
            "focus": "Volume in fundamental endurance (Z1-Z2)",
            "intensity_pct": 15,
            "advice": "Prioritise long runs at comfortable pace"
        },
        "deload": {
            "name": "Recovery",
            "description": "Unload week to absorb training",
            "focus": "Reduce volume by 20-30%",
            "intensity_pct": 10,
            "advice": "Short easy runs, stretching, sleep"
        },
        "intensification": {
            "name": "Intensification",
            "description": "Race-pace specific phase",
            "focus": "Quality sessions (tempo, threshold, intervals)",
            "intensity_pct": 25,
            "advice": "Include sessions at race pace"
        },
        "taper": {
            "name": "Taper",
            "description": "Progressive reduction before race",
            "focus": "Maintain intensity, reduce volume",
            "intensity_pct": 20,
            "advice": "Keep some speed work, rest up"
        },
        "race": {
            "name": "Race",
            "description": "Race week",
            "focus": "Maximum freshness",
            "intensity_pct": 0,
            "advice": "Light run before, trust your training"
        }
    }
    phases_fr = {
        "build": {
            "name": "Construction",
            "description": "Phase de développement de la base aérobie",
            "focus": "Volume en endurance fondamentale (Z1-Z2)",
            "intensity_pct": 15,
            "advice": "Privilégie les sorties longues à allure confortable"
        },
        "deload": {
            "name": "Récupération",
            "description": "Semaine de décharge pour assimiler le travail",
            "focus": "Réduction du volume de 20-30%",
            "intensity_pct": 10,
            "advice": "Sorties courtes et faciles, étirements, sommeil"
        },
        "intensification": {
            "name": "Intensification",
            "description": "Phase de travail spécifique à l'allure cible",
            "focus": "Séances de qualité (tempo, seuil, fractionné)",
            "intensity_pct": 25,
            "advice": "Intègre des séances à allure course"
        },
        "taper": {
            "name": "Affûtage",
            "description": "Réduction progressive avant la course",
            "focus": "Maintien de l'intensité, baisse du volume",
            "intensity_pct": 20,
            "advice": "Garde quelques rappels de vitesse, repose-toi"
        },
        "race": {
            "name": "Course",
            "description": "Semaine de compétition",
            "focus": "Fraîcheur maximale",
            "intensity_pct": 0,
            "advice": "Footing léger avant, confiance en ton travail"
        }
    }
    phases = phases_en if lang == "en" else phases_fr
    return phases.get(phase, phases["build"])


# ============================================================
# LOAD ADJUSTMENT
# ============================================================

def adjust_load_by_fatigue(base_load: float, tsb: float, acwr: float) -> float:
    """
    Adjusts recommended load based on fatigue.

    Rules:
    - ACWR > 1.3: Reduce by 15%
    - TSB < -20: Reduce by 10%
    - TSB > +10: Increase by 5%
    """
    adjusted = base_load

    # ACWR too high = injury risk
    if acwr > ACWR_DANGER:
        adjusted *= 0.70  # Strong reduction
    elif acwr > ACWR_SAFE_MAX:
        adjusted *= 0.85

    # Very negative TSB = accumulated fatigue
    if tsb < TSB_FATIGUE_THRESHOLD:
        adjusted *= 0.90

    # Positive TSB = freshness, can push a bit
    elif tsb > TSB_FRESH_THRESHOLD:
        adjusted *= 1.05

    return adjusted


def determine_target_load(context: Dict, phase: str) -> int:
    """
    Determines the target load for the week.

    Args:
        context: Fitness data (ctl, atl, tsb, acwr)
        phase: Current phase of the cycle

    Returns:
        Target load in load units (TSS/TRIMP)
    """
    ctl = context.get("ctl", 40)
    base = ctl

    # Phase multipliers
    phase_multipliers = {
        "build": 1.05,
        "deload": 0.75,
        "intensification": 1.10,
        "taper": 0.65,
        "race": 0.30
    }

    multiplier = phase_multipliers.get(phase, 1.0)
    base *= multiplier

    # Adjust based on fatigue
    adjusted = adjust_load_by_fatigue(
        base,
        context.get("tsb", 0),
        context.get("acwr", 1.0)
    )

    return int(adjusted)


def determine_target_km(context: Dict, phase: str, goal: str = "10K") -> float:
    """
    Determines the target mileage for the week.
    """
    weekly_km = context.get("weekly_km", 30)

    phase_multipliers = {
        "build": 1.05,
        "deload": 0.75,
        "intensification": 1.0,
        "taper": 0.60,
        "race": 0.25
    }

    multiplier = phase_multipliers.get(phase, 1.0)
    target = weekly_km * multiplier

    # ACWR adjustment
    acwr = context.get("acwr", 1.0)
    if acwr > ACWR_SAFE_MAX:
        target *= 0.85

    return round(target, 1)


# ============================================================
# CONTEXT BUILDING
# ============================================================

def build_training_context(
    fitness_data: Dict,
    weekly_km: float,
    daily_loads: List[float] = None
) -> Dict:
    """
    Builds the complete training context.

    Args:
        fitness_data: Fitness data (ctl, atl, load_7, load_28)
        weekly_km: Average weekly mileage
        daily_loads: Daily loads (for monotony)

    Returns:
        Complete context for recommendations
    """
    load_7 = fitness_data.get("load_7", 300)
    load_28 = fitness_data.get("load_28", 1200)
    ctl = fitness_data.get("ctl", 40)
    atl = fitness_data.get("atl", 45)

    acwr = compute_acwr(load_7, load_28)
    tsb = compute_tsb(ctl, atl)

    context = {
        "ctl": ctl,
        "atl": atl,
        "tsb": tsb,
        "acwr": acwr,
        "weekly_km": weekly_km,
        "load_7": load_7,
        "load_28": load_28
    }

    # Add monotony if data available
    if daily_loads:
        context["monotony"] = compute_monotony(daily_loads)
        context["strain"] = compute_strain(load_7, context["monotony"])

    # Risk assessment
    context["risk_level"] = evaluate_risk(acwr, tsb)

    return context


def evaluate_risk(acwr: float, tsb: float) -> str:
    """
    Evaluates the risk level of injury/overtraining.

    Returns:
        "low", "moderate", "high", "critical"
    """
    if acwr > ACWR_DANGER or tsb < -30:
        return "critical"

    if acwr > ACWR_SAFE_MAX or tsb < TSB_FATIGUE_THRESHOLD:
        return "high"

    if acwr < ACWR_SAFE_MIN:
        return "low"  # Under-training

    if tsb < -10:
        return "moderate"

    return "low"


# ============================================================
# RECOMMENDATIONS
# ============================================================

def generate_week_recommendation(
    context: Dict,
    phase: str,
    goal: str = "10K"
) -> Dict:
    """
    Generates recommendations for the week.
    """
    goal_config = GOAL_CONFIG.get(goal, GOAL_CONFIG["10K"])
    phase_info = get_phase_description(phase)

    target_load = determine_target_load(context, phase)
    target_km = determine_target_km(context, phase, goal)

    # Recommended distribution
    long_run_km = round(target_km * goal_config["long_run_ratio"], 1)
    easy_km = round(target_km * (1 - goal_config["long_run_ratio"] - goal_config["intensity_pct"]/100), 1)
    intensity_km = round(target_km * goal_config["intensity_pct"] / 100, 1)

    return {
        "phase": phase,
        "phase_info": phase_info,
        "target_load": target_load,
        "target_km": target_km,
        "distribution": {
            "long_run_km": long_run_km,
            "easy_km": easy_km,
            "intensity_km": intensity_km
        },
        "risk_level": context.get("risk_level", "low"),
        "acwr": context.get("acwr", 1.0),
        "tsb": context.get("tsb", 0),
        "advice": phase_info.get("advice", "")
    }


# ============================================================
# EXPORTS
# ============================================================

__all__ = [
    "GOAL_CONFIG",
    "VOLUME_GOAL_CONFIG",
    "PHASE_VOLUME_MULTIPLIERS",
    "compute_target_km",
    "compute_long_run_km",
    "vma_pace",
    "vma_pace_range",
    "adapt_session_to_readiness",
    "compute_week_number",
    "compute_acwr",
    "compute_tsb",
    "compute_monotony",
    "compute_strain",
    "determine_phase",
    "get_phase_description",
    "adjust_load_by_fatigue",
    "determine_target_load",
    "determine_target_km",
    "build_training_context",
    "evaluate_risk",
    "generate_week_recommendation"
]
