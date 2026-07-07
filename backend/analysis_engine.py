"""
CardioCoach Analysis Engine
100% Backend, Deterministic, No LLM Dependencies
Privacy-first - No data leaves the infrastructure

DATA PRIORITY RULE (MANDATORY)
1. IF heart rate data available: Physiological analysis PRIORITY
2. IF NO heart rate: STRUCTURAL analysis only (NEVER fatigue/zones/overload)
"""

import random
from typing import Dict, List, Optional
from datetime import datetime, timezone


# ============================================================
# TEXT TEMPLATES - ENGLISH (varied, human coach tone)
# ============================================================

# --- COACH SUMMARY (1 short sentence) ---
SUMMARY_TEMPLATES_WITH_HR = {
    "easy": [
        "Controlled session with intensity well managed from start to finish.",
        "Comfortable workout designed to build volume without pushing hard.",
        "Easy run well executed, perfect for active recovery.",
        "Measured effort, exactly what's needed to build the base.",
    ],
    "moderate": [
        "Balanced session with well-dosed effort.",
        "Run properly managed, neither too easy nor too hard.",
        "Moderate training that builds fitness progressively.",
        "Solid workout, good balance between effort and recovery.",
    ],
    "hard": [
        "Sustained session, more demanding than your usual runs.",
        "Denser session than average, with real cardio engagement.",
        "Sustained effort today, the body worked hard.",
        "Demanding run that challenges the system well.",
    ],
    "very_hard": [
        "Very intense session, close to your limits.",
        "Big effort delivered, the body will need rest.",
        "High-intensity training, recover well after this.",
        "Really pushed hard today, you went all out.",
    ],
}

SUMMARY_TEMPLATES_WITHOUT_HR = {
    "short": [
        "Short run but useful to maintain rhythm.",
        "Brief session, sometimes that's what's needed.",
        "Quick efficient workout.",
    ],
    "medium": [
        "Decent volume this session.",
        "Standard training, good for consistency.",
        "Classic run on the log.",
    ],
    "long": [
        "Nice long run to develop endurance.",
        "Solid volume today, good foundation work.",
        "Long session completed, building the engine.",
    ],
}

# --- SESSION EXECUTION ---
EXECUTION_TEMPLATES_WITH_HR = [
    "Your heart rate stayed mostly in {zones_dominantes} zones, corresponding to {qualificatif} effort.",
    "Intensity was {qualificatif} with {pct_principal}% of time in zone {zone_principale}.",
    "Effort distribution: {pct_z1_z2}% in easy zones, {pct_z3}% in tempo, {pct_z4_z5}% in high zones.",
    "Average HR of {fc_moy} bpm, mostly in {zones_dominantes}.",
]

EXECUTION_TEMPLATES_WITH_HR_HARD = [
    "Significant presence in high zones ({pct_z4_z5}%) shows a clearly pushed session.",
    "Lots of time in Z4-Z5, intensity was there.",
    "Effort climbed high with {pct_z4_z5}% of time above threshold.",
]

EXECUTION_TEMPLATES_WITH_HR_EASY = [
    "Effort stayed in low zones, perfect for base endurance.",
    "Intensity well controlled with {pct_z1_z2}% in easy zones.",
    "HR under control throughout the session.",
]

EXECUTION_TEMPLATES_WITHOUT_HR = [
    "The session is consistent in duration and pace.",
    "Pace varies little, showing good execution consistency.",
    "{distance_km} km covered in {duree} ({allure_moy}/km average).",
    "Run of {distance_km} km at {allure_moy}/km, duration {duree}.",
]

# --- WHAT IT MEANS (coach reading) ---
MEANING_TEMPLATES_WITH_HR = {
    "aerobic": [
        "This session clearly stimulates aerobic endurance.",
        "You worked on the base, that's fundamental for progress.",
        "Easy zone effort develops the cardiovascular system gently.",
    ],
    "threshold": [
        "This session works the threshold, it's demanding but effective.",
        "Sustained effort improves your ability to hold pace.",
        "You challenged the lactate system, that drives progress.",
    ],
    "mixed": [
        "The effort was varied, good for versatility.",
        "You alternated zones, interesting for the body.",
        "Mixed session that stimulates multiple energy systems.",
    ],
    "overload": [
        "This type of effort increases the overall weekly load.",
        "Demanding session that creates a strong stimulus for progress.",
        "The body was well challenged, it will adapt if you recover.",
    ],
}

MEANING_TEMPLATES_WITHOUT_HR = [
    "This session mainly increases your training volume.",
    "It fits as a structural run in your week.",
    "That's accumulated time on legs, it counts.",
    "Run that contributes to training consistency.",
]

# --- RECOVERY ---
RECOVERY_TEMPLATES_WITH_HR = {
    "needs_rest": [
        "Given the intensity, active recovery or an easy day is recommended.",
        "The load of this session deserves to be absorbed before another hard effort.",
        "After this effort, a rest day or very easy run tomorrow would be ideal.",
        "Give your body time to absorb this session before pushing hard again.",
    ],
    "light_recovery": [
        "An easy run tomorrow will help recovery.",
        "Active recovery advised: very light jog or rest.",
        "No hard session tomorrow, the body needs to adapt.",
    ],
    "ready": [
        "You can continue tomorrow if you feel good.",
        "The effort was manageable, you have margin to continue.",
        "Good management, you can go again without issue.",
    ],
}

RECOVERY_TEMPLATES_WITHOUT_HR = [
    "Standard recovery is sufficient if sensations remain good.",
    "Listen to your body to adjust the next session.",
    "No particular recommendation, adapt based on how you feel.",
]

# --- COACH ADVICE (MANDATORY, 1 actionable sentence) ---
ADVICE_TEMPLATES = {
    "reduce_intensity": [
        "For your next session, aim for lower intensity to balance the load.",
        "Lower the overall intensity a bit, you're pushing hard.",
        "Favor easy runs this week.",
    ],
    "maintain": [
        "Keep it up, consistency pays off in the long run.",
        "Maintain this training rhythm, it's the key to progress.",
        "You're on the right track, stay consistent.",
    ],
    "space_sessions": [
        "Keep this type of session, but space it out more in the week.",
        "Allow more recovery between hard sessions.",
    ],
    "add_easy": [
        "Add an easy 30-40 min run in zone 2 this week.",
        "Plan a relaxed run to balance the intensity.",
    ],
    "add_intensity": [
        "You could add a more intense session this week.",
        "A tempo or short interval session would be beneficial.",
    ],
    "shorten": [
        "If you repeat this format, slightly reduce the duration.",
        "Same effort but a bit shorter next time.",
    ],
}

# --- WEEKLY SUMMARY ---
WEEKLY_SUMMARY_TEMPLATES = [
    "Week overall well managed, with progressive load increase.",
    "Dense week, marked by efforts more sustained than usual.",
    "Balanced week, no notable excess.",
    "Good training week with {nb_seances} sessions and {volume_km} km.",
    "Solid week: {nb_seances} runs for a total of {volume_km} km.",
]

WEEKLY_SUMMARY_LIGHT = [
    "Light week with {nb_seances} session(s) and {volume_km} km.",
    "Reduced volume this week, sometimes necessary.",
    "Quiet week training-wise.",
]

WEEKLY_SUMMARY_INTENSE = [
    "Intensity-oriented week with lots of time in high zones.",
    "Intensity was there this week.",
    "Demanding week, the body was well challenged.",
]

WEEKLY_READING_TEMPLATES = {
    "balanced": [
        "The easy/hard effort distribution is good. You're building a solid base.",
        "Good balance between endurance and intensity this week.",
        "Training is well dosed, keep it up.",
    ],
    "too_intense": [
        "The increase in volume combined with higher intensity requires vigilance.",
        "Intensity dominates, fatigue risk increases. More Z2 needed.",
        "Lots of time in high zones ({pct_z4_z5}%). Add more easy runs.",
    ],
    "too_easy": [
        "Mainly in easy zone. Good for the base, but some intensity would help.",
        "Quiet week, you can afford a more intense session.",
    ],
    "good_continuity": [
        "The week shows good continuity, no major break.",
        "Good session flow, that's what drives progress.",
    ],
}

WEEKLY_ADVICE_TEMPLATES = {
    "reduce": [
        "Lighten the intensity slightly on upcoming runs.",
        "Lower the pace a few days to absorb the load.",
    ],
    "maintain_reduce_hard": [
        "Keep the volume but reduce hard sessions.",
        "Continue on this volume, favoring easy runs.",
    ],
    "maintain": [
        "Continue at this pace, it's effective.",
        "Keep this momentum for next week.",
    ],
    "add_volume": [
        "You can add an extra run next week.",
        "Slightly increase volume if you feel fresh.",
    ],
    "add_intensity": [
        "A more intense session would be beneficial.",
        "Add some pace: tempo or intervals.",
    ],
    "recover": [
        "Recovery week advised.",
        "Lower volume and intensity for a few days.",
    ],
}


# ============================================================
# UTILITY FUNCTIONS
# ============================================================

def has_hr_data(workout: dict) -> bool:
    """Check if workout has meaningful HR data"""
    zones = workout.get("effort_zone_distribution", {})
    avg_hr = workout.get("avg_heart_rate")
    
    # Must have either valid zones OR avg HR
    if zones and any(v and v > 0 for v in zones.values()):
        return True
    if avg_hr and avg_hr > 50:  # Basic sanity check
        return True
    return False


def calculate_intensity_from_zones(zones: dict) -> str:
    """
    Determine intensity level from HR zones using spec rules:
    - >70% in Z1-Z2 → easy
    - >30% in Z3 → moderate/sustained
    - >15% in Z4-Z5 → hard
    """
    if not zones:
        return None
    
    z1 = zones.get("z1", 0) or 0
    z2 = zones.get("z2", 0) or 0
    z3 = zones.get("z3", 0) or 0
    z4 = zones.get("z4", 0) or 0
    z5 = zones.get("z5", 0) or 0
    
    z1_z2 = z1 + z2
    z4_z5 = z4 + z5
    
    # Apply rules from spec
    if z4_z5 >= 40:
        return "very_hard"
    elif z4_z5 >= 15:
        return "hard"
    elif z3 >= 30:
        return "moderate"
    elif z1_z2 >= 70:
        return "easy"
    else:
        return "moderate"


def get_dominant_zones_label(zones: dict) -> str:
    """Get human-readable label for dominant zones"""
    if not zones:
        return "moderate"

    z1_z2 = (zones.get("z1", 0) or 0) + (zones.get("z2", 0) or 0)
    z3 = zones.get("z3", 0) or 0
    z4_z5 = (zones.get("z4", 0) or 0) + (zones.get("z5", 0) or 0)

    if z1_z2 >= 60:
        return "Z1-Z2 (easy)"
    elif z4_z5 >= 40:
        return "Z4-Z5 (high)"
    elif z3 >= 40:
        return "Z3 (tempo)"
    elif z4_z5 >= 20:
        return "Z3-Z4 (sustained)"
    else:
        return "intermediate"


def get_intensity_qualifier(intensity: str) -> str:
    """Get English qualifier for intensity level"""
    qualifiers = {
        "easy": "easy",
        "moderate": "moderate",
        "hard": "sustained",
        "very_hard": "very intense"
    }
    return qualifiers.get(intensity, "moderate")


def calculate_session_type_structural(distance_km: float, duration_min: int) -> str:
    """Determine session type based on volume only (no HR)"""
    if duration_min >= 90 or distance_km >= 15:
        return "long"
    elif duration_min <= 25 or distance_km <= 4:
        return "short"
    return "medium"


def format_duration(minutes: int) -> str:
    """Format duration as Xh XXmin"""
    if not minutes:
        return "0min"
    hours = minutes // 60
    mins = minutes % 60
    if hours > 0:
        return f"{hours}h{mins:02d}" if mins > 0 else f"{hours}h"
    return f"{mins}min"


def format_pace(pace_min_km: float) -> str:
    """Format pace as X:XX/km"""
    if not pace_min_km:
        return "-"
    total_seconds = round(pace_min_km * 60)
    mins = total_seconds // 60
    secs = total_seconds % 60
    return f"{mins}:{secs:02d}"


def pick(templates: list) -> str:
    """Select a random template from a list"""
    return random.choice(templates)


# ============================================================
# SESSION ANALYSIS GENERATOR
# ============================================================

def generate_session_analysis(workout: dict, baseline: dict = None, language: str = "en") -> dict:
    """
    Generate complete session analysis following mandatory structure.
    HR PRIORITY: If HR data available → physiological analysis
    OTHERWISE: Structural analysis only (NEVER fatigue/zones/overload)
    """
    
    # Extract workout data
    distance_km = workout.get("distance_km", 0) or 0
    duration_min = workout.get("duration_minutes", 0) or 0
    avg_pace = workout.get("avg_pace_min_km")
    avg_hr = workout.get("avg_heart_rate")
    zones = workout.get("effort_zone_distribution", {})
    cadence = workout.get("avg_cadence_spm")
    workout_type = workout.get("type", "run")
    
    # Determine if we have HR data
    hr_available = has_hr_data(workout)
    
    # Calculate zone percentages
    z1_z2 = (zones.get("z1", 0) or 0) + (zones.get("z2", 0) or 0)
    z3 = zones.get("z3", 0) or 0
    z4_z5 = (zones.get("z4", 0) or 0) + (zones.get("z5", 0) or 0)
    
    # Build placeholders for templates
    placeholders = {
        "distance_km": round(distance_km, 1),
        "duree": format_duration(duration_min),
        "allure_moy": format_pace(avg_pace) if avg_pace else "-",
        "fc_moy": avg_hr or "-",
        "cadence": cadence or "-",
        "pct_z1_z2": round(z1_z2),
        "pct_z3": round(z3),
        "pct_z4_z5": round(z4_z5),
        "zones_dominantes": get_dominant_zones_label(zones),
        "pct_principal": max(z1_z2, z3, z4_z5),
        "zone_principale": "Z1-Z2" if z1_z2 >= max(z3, z4_z5) else ("Z4-Z5" if z4_z5 >= z3 else "Z3"),
    }
    
    # ============================================
    # MODE 1: WITH HR DATA (physiological analysis)
    # ============================================
    if hr_available:
        intensity = calculate_intensity_from_zones(zones)
        placeholders["qualificatif"] = get_intensity_qualifier(intensity)

        # 1. COACH SUMMARY
        summary = pick(SUMMARY_TEMPLATES_WITH_HR.get(intensity, SUMMARY_TEMPLATES_WITH_HR["moderate"]))

        # 2. EXECUTION
        if intensity in ["hard", "very_hard"]:
            execution = pick(EXECUTION_TEMPLATES_WITH_HR_HARD).format(**placeholders)
        elif intensity == "easy":
            execution = pick(EXECUTION_TEMPLATES_WITH_HR_EASY).format(**placeholders)
        else:
            execution = pick(EXECUTION_TEMPLATES_WITH_HR).format(**placeholders)

        # 3. WHAT IT MEANS
        if z1_z2 >= 70:
            meaning = pick(MEANING_TEMPLATES_WITH_HR["aerobic"])
        elif z4_z5 >= 25:
            meaning = pick(MEANING_TEMPLATES_WITH_HR["threshold"])
        elif z4_z5 >= 15 or duration_min >= 60:
            meaning = pick(MEANING_TEMPLATES_WITH_HR["overload"])
        else:
            meaning = pick(MEANING_TEMPLATES_WITH_HR["mixed"])

        # 4. RECOVERY
        if intensity == "very_hard" or (intensity == "hard" and duration_min >= 60):
            recovery = pick(RECOVERY_TEMPLATES_WITH_HR["needs_rest"])
        elif intensity == "hard":
            recovery = pick(RECOVERY_TEMPLATES_WITH_HR["light_recovery"])
        else:
            recovery = pick(RECOVERY_TEMPLATES_WITH_HR["ready"])

        # 5. COACH ADVICE
        if intensity == "very_hard":
            advice = pick(ADVICE_TEMPLATES["reduce_intensity"])
        elif intensity == "hard" and z1_z2 < 30:
            advice = pick(ADVICE_TEMPLATES["space_sessions"])
        elif intensity == "easy" and z4_z5 < 5:
            advice = pick(ADVICE_TEMPLATES["add_intensity"])
        elif duration_min >= 90:
            advice = pick(ADVICE_TEMPLATES["shorten"])
        else:
            advice = pick(ADVICE_TEMPLATES["maintain"])

    # ============================================
    # MODE 2: WITHOUT HR (structural analysis ONLY)
    # ============================================
    else:
        session_type = calculate_session_type_structural(distance_km, duration_min)

        # 1. COACH SUMMARY
        summary = pick(SUMMARY_TEMPLATES_WITHOUT_HR.get(session_type, SUMMARY_TEMPLATES_WITHOUT_HR["medium"]))

        # 2. EXECUTION
        execution = pick(EXECUTION_TEMPLATES_WITHOUT_HR).format(**placeholders)

        # 3. WHAT IT MEANS
        meaning = pick(MEANING_TEMPLATES_WITHOUT_HR)

        # 4. RECOVERY (without talking about fatigue/load)
        recovery = pick(RECOVERY_TEMPLATES_WITHOUT_HR)

        # 5. COACH ADVICE
        if duration_min >= 90:
            advice = pick(ADVICE_TEMPLATES["shorten"])
        elif duration_min <= 25:
            advice = pick(ADVICE_TEMPLATES["add_easy"])
        else:
            advice = pick(ADVICE_TEMPLATES["maintain"])
        
        intensity = None
    
    return {
        "summary": summary,
        "execution": execution,
        "meaning": meaning,
        "recovery": recovery,
        "advice": advice,
        "metrics": {
            "intensity_level": intensity,
            "session_type": calculate_session_type_structural(distance_km, duration_min),
            "has_hr_data": hr_available,
            "zones": {
                "easy": round(z1_z2),
                "moderate": round(z3),
                "hard": round(z4_z5)
            } if hr_available else None
        }
    }


# ============================================================
# WEEKLY REVIEW GENERATOR
# ============================================================

def generate_weekly_review(
    workouts: List[dict],
    previous_week_workouts: List[dict] = None,
    user_goal: dict = None,
    language: str = "en"
) -> dict:
    """
    Generate weekly review ("Week Summary") following mandatory 6-block structure.
    """

    if not workouts:
        return {
            "summary": "No sessions this week.",
            "meaning": "A complete rest week, sometimes necessary.",
            "recovery": "You're probably well rested.",
            "advice": "Resume gently with an easy run.",
            "metrics": {"total_sessions": 0, "total_km": 0, "total_duration_min": 0}
        }
    
    # Calculate weekly metrics
    nb_seances = len(workouts)
    volume_km = round(sum(w.get("distance_km", 0) or 0 for w in workouts), 1)
    total_duration = sum(w.get("duration_minutes", 0) or 0 for w in workouts)
    
    # Check if we have HR data for the week
    workouts_with_hr = [w for w in workouts if has_hr_data(w)]
    hr_available = len(workouts_with_hr) >= len(workouts) * 0.5  # At least 50% with HR
    
    # Calculate average zones if HR available
    zone_totals = {"z1": 0, "z2": 0, "z3": 0, "z4": 0, "z5": 0}
    zone_count = 0
    
    for w in workouts_with_hr:
        zones = w.get("effort_zone_distribution", {})
        if zones:
            for z in ["z1", "z2", "z3", "z4", "z5"]:
                zone_totals[z] += zones.get(z, 0) or 0
            zone_count += 1
    
    avg_zones = {z: round(v / zone_count) if zone_count > 0 else 0 for z, v in zone_totals.items()}
    z1_z2 = avg_zones["z1"] + avg_zones["z2"]
    z4_z5 = avg_zones["z4"] + avg_zones["z5"]
    
    # Compare to previous week
    prev_volume = sum(w.get("distance_km", 0) or 0 for w in previous_week_workouts) if previous_week_workouts else 0
    volume_change = round(((volume_km - prev_volume) / prev_volume * 100) if prev_volume > 0 else 0)
    
    placeholders = {
        "nb_seances": nb_seances,
        "volume_km": volume_km,
        "duree_totale": format_duration(total_duration),
        "pct_z1_z2": round(z1_z2),
        "pct_z4_z5": round(z4_z5),
    }
    
    # ========================================
    # 1. COACH SUMMARY (1 sentence)
    # ========================================
    if volume_km < 15 or nb_seances <= 1:
        summary = pick(WEEKLY_SUMMARY_LIGHT).format(**placeholders)
    elif hr_available and z4_z5 >= 30:
        summary = pick(WEEKLY_SUMMARY_INTENSE)
    else:
        summary = pick(WEEKLY_SUMMARY_TEMPLATES).format(**placeholders)

    # ========================================
    # 2. KEY SIGNALS (built in signals dict)
    # ========================================
    signals = {
        "volume": "low" if volume_km < 20 else ("high" if volume_km > 50 else "moderate"),
        "regularity": "stable" if nb_seances >= 3 else "variable"
    }

    # ONLY add intensity if HR available
    if hr_available:
        signals["intensity"] = "high" if z4_z5 >= 30 else ("low" if z1_z2 >= 75 else "moderate")

    # ========================================
    # 3. ESSENTIAL NUMBERS (in metrics)
    # ========================================
    metrics = {
        "total_sessions": nb_seances,
        "total_km": volume_km,
        "total_duration_min": total_duration,
        "volume_change_pct": volume_change
    }

    if hr_available:
        metrics["avg_zones"] = avg_zones

    # ========================================
    # 4. COACH READING (2 sentences max)
    # ========================================
    if hr_available:
        if z4_z5 >= 35:
            meaning = pick(WEEKLY_READING_TEMPLATES["too_intense"]).format(**placeholders)
        elif z1_z2 >= 80 and z4_z5 < 10:
            meaning = pick(WEEKLY_READING_TEMPLATES["too_easy"])
        else:
            meaning = pick(WEEKLY_READING_TEMPLATES["balanced"])
    else:
        meaning = pick(WEEKLY_READING_TEMPLATES["good_continuity"])

    # ========================================
    # 5. RECOMMENDATIONS (MANDATORY)
    # ========================================
    if hr_available and z4_z5 >= 35:
        advice = pick(WEEKLY_ADVICE_TEMPLATES["reduce"])
    elif hr_available and z4_z5 >= 25 and volume_km > 40:
        advice = pick(WEEKLY_ADVICE_TEMPLATES["maintain_reduce_hard"])
    elif hr_available and z1_z2 >= 85 and z4_z5 < 10:
        advice = pick(WEEKLY_ADVICE_TEMPLATES["add_intensity"])
    elif volume_km < 20 and nb_seances < 3:
        advice = pick(WEEKLY_ADVICE_TEMPLATES["add_volume"])
    elif volume_km > 60:
        advice = pick(WEEKLY_ADVICE_TEMPLATES["recover"])
    else:
        advice = pick(WEEKLY_ADVICE_TEMPLATES["maintain"])

    # Add goal context if present
    if user_goal and user_goal.get("event_name"):
        try:
            event_date = datetime.fromisoformat(user_goal["event_date"]).date()
            today = datetime.now(timezone.utc).date()
            days_until = (event_date - today).days
            if days_until and days_until > 0:
                advice += f" Goal {user_goal['event_name']} in {days_until} days."
        except:
            pass

    # ========================================
    # 6. Recovery suggestion
    # ========================================
    if hr_available and z4_z5 >= 30:
        recovery = pick(RECOVERY_TEMPLATES_WITH_HR["needs_rest"])
    elif volume_km > 50:
        recovery = pick(RECOVERY_TEMPLATES_WITH_HR["light_recovery"])
    else:
        recovery = pick(RECOVERY_TEMPLATES_WITH_HR["ready"])

    return {
        "summary": summary,
        "meaning": meaning,
        "recovery": recovery,
        "advice": advice,
        "metrics": metrics,
        "signals": [
            {
                "key": "load",
                "label": "Volume",
                "status": "up" if volume_change > 15 else "down" if volume_change < -15 else "stable",
                "value": f"{volume_change:+d}%" if volume_change != 0 else "="
            },
            {
                "key": "intensity",
                "label": "Intensity",
                "status": signals.get("intensity", "N/A"),
                "value": f"{z4_z5}% Z4-Z5" if hr_available else "N/A"
            },
            {
                "key": "consistency",
                "label": "Consistency",
                "status": "high" if nb_seances >= 4 else "moderate" if nb_seances >= 2 else "low",
                "value": f"{nb_seances} sessions"
            }
        ]
    }


# ============================================================
# DASHBOARD INSIGHT GENERATOR
# ============================================================

def generate_dashboard_insight(
    week_stats: dict,
    month_stats: dict,
    recovery_score: int = None,
    language: str = "en"
) -> str:
    """Generate single dashboard insight sentence without LLM"""

    sessions = week_stats.get("sessions", 0)
    volume = week_stats.get("volume_km", 0)

    if sessions == 0:
        return pick([
            "No sessions yet this week, time to get moving.",
            "Blank week so far, an easy run would be perfect.",
            "No activity this week, body is rested.",
        ])
    elif sessions == 1:
        return pick([
            "One session this week, good start. Keep the momentum.",
            "First run done, add an easy session.",
            "Week started with one session logged.",
        ])
    elif volume > 40:
        return pick([
            "Good load this week, remember to recover well.",
            "Solid volume, body is working hard.",
            "Big week underway, listen to your body.",
        ])
    elif recovery_score and recovery_score < 50:
        return pick([
            "Recovery decent, favor an easy session.",
            "Body a bit tired, no pushing hard today.",
            "Recovery ongoing, take it easy.",
        ])
    else:
        return pick([
            "Training in progress, keep it up.",
            "Good momentum this week, maintain the rhythm.",
            "You're progressing well, stay consistent.",
        ])
