from __future__ import annotations

from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Dict, List, Optional

from pydantic import BaseModel


SUPPORTED_LANGUAGES = {"en", "fr", "es"}


class AnalysisText(BaseModel):
    code: str
    text: str


class WorkoutAnalysisSignal(BaseModel):
    available: bool
    code: Optional[str] = None
    text: Optional[str] = None
    reason_unavailable: Optional[str] = None


class WorkoutAnalysisWorkout(BaseModel):
    id: str
    name: str
    date: str
    type: str


class WorkoutAnalysisSignals(BaseModel):
    intensity: WorkoutAnalysisSignal
    volume: WorkoutAnalysisSignal
    session_type: WorkoutAnalysisSignal


class WorkoutAnalysisPhysiology(BaseModel):
    available: bool
    avg_hr: Optional[int] = None
    max_hr: Optional[int] = None
    zone_distribution: Optional[Dict[str, float]] = None
    hr_drift: Optional[float] = None
    reason_unavailable: Optional[str] = None


class WorkoutAnalysisPacing(BaseModel):
    available: bool
    average_pace_min_km: Optional[float] = None
    average_speed_kmh: Optional[float] = None
    fastest_split_min_km: Optional[float] = None
    slowest_split_min_km: Optional[float] = None
    pace_drop_min_km: Optional[float] = None
    negative_split: Optional[bool] = None
    consistency_score: Optional[float] = None
    variability: Optional[float] = None
    reason_unavailable: Optional[str] = None


class WorkoutAnalysisComparisonMetric(BaseModel):
    current: Optional[float] = None
    baseline: Optional[float] = None
    difference: Optional[float] = None
    percent_change: Optional[float] = None


class WorkoutAnalysisComparison(BaseModel):
    available: bool
    baseline_period_days: int
    baseline_sample_count: int
    distance_km: Optional[WorkoutAnalysisComparisonMetric] = None
    duration_minutes: Optional[WorkoutAnalysisComparisonMetric] = None
    avg_heart_rate: Optional[WorkoutAnalysisComparisonMetric] = None
    avg_pace_min_km: Optional[WorkoutAnalysisComparisonMetric] = None
    avg_speed_kmh: Optional[WorkoutAnalysisComparisonMetric] = None
    reason_unavailable: Optional[str] = None


class WorkoutAnalysisEvidence(BaseModel):
    has_heart_rate: bool
    has_hr_zones: bool
    has_splits: bool
    has_baseline: bool
    has_cadence: bool
    has_elevation: bool


class WorkoutAnalysisV2Response(BaseModel):
    version: str = "v2"
    workout: WorkoutAnalysisWorkout
    summary: AnalysisText
    signals: WorkoutAnalysisSignals
    physiology: WorkoutAnalysisPhysiology
    pacing: WorkoutAnalysisPacing
    comparison: WorkoutAnalysisComparison
    meaning: AnalysisText
    advice: AnalysisText
    evidence: WorkoutAnalysisEvidence


def _lang(language: str) -> str:
    normalized = (language or "en").lower()
    return normalized if normalized in SUPPORTED_LANGUAGES else "en"


def _parse_workout_date(raw: str) -> datetime:
    value = (raw or "").strip()
    if not value:
        raise ValueError("Workout date is required")

    normalized = value.replace("Z", "+00:00")
    parsed: datetime
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError:
        parsed = datetime.fromisoformat(normalized.split("T")[0])

    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _template(language: str, key: str, **params) -> str:
    lang = _lang(language)
    templates = {
        "en": {
            "summary.high_with_hr": "High-intensity session with strong cardiovascular demand.",
            "summary.moderate_with_hr": "Moderate aerobic session with controlled cardiovascular load.",
            "summary.easy_with_hr": "Easy cardiovascular session with controlled effort.",
            "summary.long_structural": "Long-duration session completed.",
            "summary.short_structural": "Short-duration session completed.",
            "summary.standard_structural": "Standard-duration session completed.",
            "signal.intensity.low": "Low intensity",
            "signal.intensity.moderate": "Moderate intensity",
            "signal.intensity.high": "High intensity",
            "signal.intensity.very_high": "Very high intensity",
            "signal.volume.below_recent": "Below recent volume",
            "signal.volume.usual_recent": "Close to recent volume",
            "signal.volume.above_recent": "Above recent volume",
            "signal.volume.short_volume": "Short session volume",
            "signal.volume.medium_volume": "Moderate session volume",
            "signal.volume.long_volume": "Long session volume",
            "signal.session_type.easy": "Easy session",
            "signal.session_type.standard": "Standard session",
            "signal.session_type.hard": "Hard session",
            "signal.session_type.long": "Long session",
            "signal.session_type.short": "Short session",
            "meaning.with_hr_easy": "Heart-rate evidence points to a controlled aerobic session rather than a high-stress effort.",
            "meaning.with_hr_moderate": "Heart-rate evidence points to a balanced aerobic load with meaningful work but no clear overload signal.",
            "meaning.with_hr_high": "Heart-rate evidence points to a demanding session with substantial cardiovascular stress.",
            "meaning.hr_without_intensity_with_pacing": "Heart-rate facts are available, but intensity classification is unavailable without trustworthy zone evidence, so this session is interpreted structurally.",
            "meaning.hr_without_intensity_no_pacing": "Heart-rate facts are available, but intensity classification is unavailable without trustworthy zone evidence, so only structural volume can be interpreted.",
            "meaning.no_hr_with_pacing": "The workout can be described structurally from pace and volume, but not physiologically because heart-rate evidence is missing.",
            "meaning.no_hr_no_pacing": "The workout can be described structurally from duration and distance, but not physiologically because heart-rate evidence is missing.",
            "advice.recover_after_hard": "Keep the next session easy unless new evidence supports another hard effort.",
            "advice.maintain_easy": "You can continue with normal aerobic training if overall fatigue signs remain stable elsewhere.",
            "advice.build_progressively": "Progress volume gradually and use heart-rate evidence on future sessions before drawing stronger conclusions.",
            "advice.hr_without_intensity": "Use individualized heart-rate zones on future sessions before treating raw heart-rate values as intensity evidence.",
            "advice.no_hr": "Use heart-rate recording on future sessions if you want physiological interpretation, and avoid over-interpreting this workout.",
            "unavailable.hr": "Heart-rate evidence is unavailable.",
            "unavailable.intensity": "Intensity classification is unavailable without individualized physiological evidence.",
            "unavailable.pacing": "Pacing evidence is unavailable.",
            "unavailable.baseline": "No prior same-type workouts in the last {days} days.",
        },
        "fr": {
            "summary.high_with_hr": "Séance intense avec une forte demande cardiovasculaire.",
            "summary.moderate_with_hr": "Séance aérobie modérée avec une charge cardiovasculaire contrôlée.",
            "summary.easy_with_hr": "Séance facile avec un effort cardiovasculaire maîtrisé.",
            "summary.long_structural": "Séance longue réalisée.",
            "summary.short_structural": "Séance courte réalisée.",
            "summary.standard_structural": "Séance de durée standard réalisée.",
            "signal.intensity.low": "Intensité basse",
            "signal.intensity.moderate": "Intensité modérée",
            "signal.intensity.high": "Intensité élevée",
            "signal.intensity.very_high": "Intensité très élevée",
            "signal.volume.below_recent": "Volume inférieur au récent",
            "signal.volume.usual_recent": "Volume proche du récent",
            "signal.volume.above_recent": "Volume supérieur au récent",
            "signal.volume.short_volume": "Volume de séance court",
            "signal.volume.medium_volume": "Volume de séance modéré",
            "signal.volume.long_volume": "Volume de séance long",
            "signal.session_type.easy": "Séance facile",
            "signal.session_type.standard": "Séance standard",
            "signal.session_type.hard": "Séance intense",
            "signal.session_type.long": "Séance longue",
            "signal.session_type.short": "Séance courte",
            "meaning.with_hr_easy": "Les données cardiaques indiquent une séance aérobie contrôlée plutôt qu'un effort très contraignant.",
            "meaning.with_hr_moderate": "Les données cardiaques indiquent une charge aérobie équilibrée sans signe clair de surcharge.",
            "meaning.with_hr_high": "Les données cardiaques indiquent une séance exigeante avec un stress cardiovasculaire marqué.",
            "meaning.hr_without_intensity_with_pacing": "Des données cardiaques existent, mais l'intensité ne peut pas être classée sans zones fiables; la séance est donc interprétée de façon structurelle.",
            "meaning.hr_without_intensity_no_pacing": "Des données cardiaques existent, mais l'intensité ne peut pas être classée sans zones fiables; seul le volume structurel peut être interprété.",
            "meaning.no_hr_with_pacing": "La séance peut être décrite sur le plan structurel grâce à l'allure et au volume, mais pas sur le plan physiologique faute de données cardiaques.",
            "meaning.no_hr_no_pacing": "La séance peut être décrite sur le plan structurel grâce à la durée et à la distance, mais pas sur le plan physiologique faute de données cardiaques.",
            "advice.recover_after_hard": "Garde la prochaine séance facile sauf si de nouvelles données justifient un autre effort intense.",
            "advice.maintain_easy": "Tu peux poursuivre l'entraînement aérobie normal si les autres signes de fatigue restent stables.",
            "advice.build_progressively": "Fais progresser le volume progressivement et appuie-toi sur la fréquence cardiaque lors des prochaines séances avant d'en tirer des conclusions plus fortes.",
            "advice.hr_without_intensity": "Utilise des zones cardiaques individualisées lors des prochaines séances avant d'interpréter la fréquence cardiaque brute comme une preuve d'intensité.",
            "advice.no_hr": "Enregistre la fréquence cardiaque lors des prochaines séances si tu veux une lecture physiologique, et évite de sur-interpréter cette séance.",
            "unavailable.hr": "Les données cardiaques sont indisponibles.",
            "unavailable.intensity": "La classification d'intensité est indisponible sans preuve physiologique individualisée.",
            "unavailable.pacing": "Les données d'allure sont indisponibles.",
            "unavailable.baseline": "Aucune séance antérieure du même type sur les {days} derniers jours.",
        },
        "es": {
            "summary.high_with_hr": "Sesión intensa con una alta demanda cardiovascular.",
            "summary.moderate_with_hr": "Sesión aeróbica moderada con una carga cardiovascular controlada.",
            "summary.easy_with_hr": "Sesión fácil con un esfuerzo cardiovascular controlado.",
            "summary.long_structural": "Sesión larga completada.",
            "summary.short_structural": "Sesión corta completada.",
            "summary.standard_structural": "Sesión de duración estándar completada.",
            "signal.intensity.low": "Intensidad baja",
            "signal.intensity.moderate": "Intensidad moderada",
            "signal.intensity.high": "Intensidad alta",
            "signal.intensity.very_high": "Intensidad muy alta",
            "signal.volume.below_recent": "Volumen por debajo de lo reciente",
            "signal.volume.usual_recent": "Volumen cercano a lo reciente",
            "signal.volume.above_recent": "Volumen por encima de lo reciente",
            "signal.volume.short_volume": "Volumen de sesión corto",
            "signal.volume.medium_volume": "Volumen de sesión moderado",
            "signal.volume.long_volume": "Volumen de sesión largo",
            "signal.session_type.easy": "Sesión fácil",
            "signal.session_type.standard": "Sesión estándar",
            "signal.session_type.hard": "Sesión intensa",
            "signal.session_type.long": "Sesión larga",
            "signal.session_type.short": "Sesión corta",
            "meaning.with_hr_easy": "La evidencia de frecuencia cardíaca apunta a una sesión aeróbica controlada, no a un esfuerzo de alto estrés.",
            "meaning.with_hr_moderate": "La evidencia de frecuencia cardíaca apunta a una carga aeróbica equilibrada sin una señal clara de sobrecarga.",
            "meaning.with_hr_high": "La evidencia de frecuencia cardíaca apunta a una sesión exigente con un estrés cardiovascular importante.",
            "meaning.hr_without_intensity_with_pacing": "Hay datos de frecuencia cardíaca, pero la intensidad no puede clasificarse sin evidencia fiable de zonas, así que la sesión se interpreta de forma estructural.",
            "meaning.hr_without_intensity_no_pacing": "Hay datos de frecuencia cardíaca, pero la intensidad no puede clasificarse sin evidencia fiable de zonas, así que solo puede interpretarse el volumen estructural.",
            "meaning.no_hr_with_pacing": "La sesión puede describirse de forma estructural con ritmo y volumen, pero no fisiológicamente porque faltan datos de frecuencia cardíaca.",
            "meaning.no_hr_no_pacing": "La sesión puede describirse de forma estructural con duración y distancia, pero no fisiológicamente porque faltan datos de frecuencia cardíaca.",
            "advice.recover_after_hard": "Mantén la próxima sesión fácil salvo que nueva evidencia justifique otro esfuerzo intenso.",
            "advice.maintain_easy": "Puedes continuar con el entrenamiento aeróbico normal si el resto de señales de fatiga siguen estables.",
            "advice.build_progressively": "Aumenta el volumen de forma progresiva y usa datos de frecuencia cardíaca en futuras sesiones antes de sacar conclusiones más fuertes.",
            "advice.hr_without_intensity": "Usa zonas de frecuencia cardíaca individualizadas en futuras sesiones antes de tratar la frecuencia cardíaca bruta como evidencia de intensidad.",
            "advice.no_hr": "Registra la frecuencia cardíaca en futuras sesiones si quieres interpretación fisiológica y evita sobreinterpretar esta sesión.",
            "unavailable.hr": "No hay datos de frecuencia cardíaca disponibles.",
            "unavailable.intensity": "La clasificación de intensidad no está disponible sin evidencia fisiológica individualizada.",
            "unavailable.pacing": "No hay datos de ritmo disponibles.",
            "unavailable.baseline": "No hay sesiones previas del mismo tipo en los últimos {days} días.",
        },
    }
    return templates[lang][key].format(**params)


def _safe_round(value: Optional[float], digits: int = 2) -> Optional[float]:
    if value is None:
        return None
    return round(float(value), digits)


def _safe_avg(values: List[Optional[float]]) -> Optional[float]:
    valid = [float(value) for value in values if value is not None]
    return _safe_round(sum(valid) / len(valid), 2) if valid else None


def _comparison_metric(current: Optional[float], baseline: Optional[float], digits: int = 2) -> Optional[WorkoutAnalysisComparisonMetric]:
    if current is None or baseline is None:
        return None
    difference = current - baseline
    percent_change = (difference / baseline * 100) if baseline else None
    return WorkoutAnalysisComparisonMetric(
        current=_safe_round(current, digits),
        baseline=_safe_round(baseline, digits),
        difference=_safe_round(difference, digits),
        percent_change=_safe_round(percent_change, 1) if percent_change is not None else None,
    )


def _extract_split_paces(workout: dict) -> List[float]:
    paces: List[float] = []
    for split in workout.get("km_splits") or []:
        pace = split.get("pace_min_km")
        if pace is not None:
            paces.append(float(pace))
    return paces


def _build_baseline(workouts: List[dict], current_workout: dict, days: int = 14) -> dict:
    current_date = _parse_workout_date(current_workout.get("date", ""))
    cutoff_date = current_date - timedelta(days=days)
    current_type = current_workout.get("type")

    prior_same_type = []
    for workout in workouts:
        if workout.get("type") != current_type or workout.get("id") == current_workout.get("id"):
            continue
        raw_date = workout.get("date")
        if not raw_date:
            continue
        try:
            workout_date = _parse_workout_date(raw_date)
        except ValueError:
            continue
        if cutoff_date <= workout_date < current_date:
            prior_same_type.append(workout)

    if not prior_same_type:
        return {
            "period_days": days,
            "sample_count": 0,
            "workouts": [],
        }

    return {
        "period_days": days,
        "sample_count": len(prior_same_type),
        "workouts": prior_same_type,
        "avg_distance_km": _safe_avg([workout.get("distance_km") for workout in prior_same_type]),
        "avg_duration_minutes": _safe_avg([workout.get("duration_minutes") for workout in prior_same_type]),
        "avg_heart_rate": _safe_avg([workout.get("avg_heart_rate") for workout in prior_same_type]),
        "avg_pace_min_km": _safe_avg([workout.get("avg_pace_min_km") for workout in prior_same_type]),
        "avg_speed_kmh": _safe_avg([workout.get("avg_speed_kmh") for workout in prior_same_type]),
    }


def _build_pacing(workout: dict, language: str) -> WorkoutAnalysisPacing:
    avg_pace = workout.get("avg_pace_min_km")
    avg_speed = workout.get("avg_speed_kmh")
    split_analysis = workout.get("split_analysis") or {}
    pace_stats = workout.get("pace_stats") or {}
    split_paces = _extract_split_paces(workout)

    fastest_split = split_analysis.get("fastest_split_pace")
    slowest_split = split_analysis.get("slowest_split_pace")
    if fastest_split is None and split_paces:
        fastest_split = min(split_paces)
    if slowest_split is None and split_paces:
        slowest_split = max(split_paces)

    pace_drop = split_analysis.get("pace_drop")
    variability = pace_stats.get("pace_variability")
    consistency = split_analysis.get("consistency_score")
    if consistency is None and split_paces:
        avg_split = mean(split_paces)
        max_dev = max(abs(pace - avg_split) for pace in split_paces)
        consistency = max(0.0, min(100.0, 100.0 - (max_dev / avg_split * 100.0))) if avg_split else None

    available = any(value is not None for value in [avg_pace, avg_speed, fastest_split, slowest_split, pace_drop, variability, consistency])
    return WorkoutAnalysisPacing(
        available=available,
        average_pace_min_km=_safe_round(avg_pace, 3),
        average_speed_kmh=_safe_round(avg_speed, 2),
        fastest_split_min_km=_safe_round(fastest_split, 3),
        slowest_split_min_km=_safe_round(slowest_split, 3),
        pace_drop_min_km=_safe_round(pace_drop, 3),
        negative_split=split_analysis.get("negative_split"),
        consistency_score=_safe_round(consistency, 1),
        variability=_safe_round(variability, 3),
        reason_unavailable=None if available else _template(language, "unavailable.pacing"),
    )


def _build_physiology(workout: dict, language: str) -> WorkoutAnalysisPhysiology:
    hr_analysis = workout.get("hr_analysis") or {}
    avg_hr = workout.get("avg_heart_rate")
    max_hr = workout.get("max_heart_rate")
    zones = workout.get("effort_zone_distribution") or {}
    zone_distribution = {key: float(value) for key, value in zones.items() if value is not None} or None
    hr_drift = hr_analysis.get("hr_drift")
    available = any(value is not None for value in [avg_hr, max_hr, hr_drift]) or bool(zone_distribution)

    return WorkoutAnalysisPhysiology(
        available=available,
        avg_hr=avg_hr,
        max_hr=max_hr,
        zone_distribution=zone_distribution,
        hr_drift=_safe_round(hr_drift, 2),
        reason_unavailable=None if available else _template(language, "unavailable.hr"),
    )


def _available_signal(language: str, key: str, code: str) -> WorkoutAnalysisSignal:
    return WorkoutAnalysisSignal(
        available=True,
        code=code,
        text=_template(language, f"{key}.{code}"),
        reason_unavailable=None,
    )


def _unavailable_signal(reason: str) -> WorkoutAnalysisSignal:
    return WorkoutAnalysisSignal(
        available=False,
        code=None,
        text=None,
        reason_unavailable=reason,
    )


def _has_trusted_zone_provenance(workout: dict) -> bool:
    return False


def _intensity_code(workout: dict, physiology: WorkoutAnalysisPhysiology) -> Optional[str]:
    if not physiology.zone_distribution or not _has_trusted_zone_provenance(workout):
        return None

    hard = (physiology.zone_distribution.get("z4", 0) or 0) + (physiology.zone_distribution.get("z5", 0) or 0)
    easy = (physiology.zone_distribution.get("z1", 0) or 0) + (physiology.zone_distribution.get("z2", 0) or 0)
    if hard >= 35:
        return "very_high"
    if hard >= 20:
        return "high"
    if easy >= 70:
        return "low"
    return "moderate"


def _volume_code(workout: dict, comparison: WorkoutAnalysisComparison) -> str:
    if comparison.available and comparison.distance_km and comparison.distance_km.percent_change is not None:
        pct = comparison.distance_km.percent_change
        if pct >= 15:
            return "above_recent"
        if pct <= -15:
            return "below_recent"
        return "usual_recent"

    duration = workout.get("duration_minutes") or 0
    distance = workout.get("distance_km") or 0
    if duration >= 90 or distance >= 15:
        return "long_volume"
    if duration <= 25 or distance <= 4:
        return "short_volume"
    return "medium_volume"


def _session_type_code(workout: dict, intensity_code: Optional[str]) -> str:
    duration = workout.get("duration_minutes") or 0
    distance = workout.get("distance_km") or 0
    if duration >= 90 or distance >= 15:
        return "long"
    if duration <= 25 or distance <= 4:
        return "short"
    if intensity_code in {"high", "very_high"}:
        return "hard"
    if intensity_code == "low":
        return "easy"
    return "standard"


def _build_signals(workout: dict, comparison: WorkoutAnalysisComparison, physiology: WorkoutAnalysisPhysiology, language: str) -> WorkoutAnalysisSignals:
    intensity_code = _intensity_code(workout, physiology)
    intensity = (
        _available_signal(language, "signal.intensity", intensity_code)
        if intensity_code
        else _unavailable_signal(_template(language, "unavailable.intensity"))
    )
    volume_code = _volume_code(workout, comparison)
    session_type_code = _session_type_code(workout, intensity.code)
    return WorkoutAnalysisSignals(
        intensity=intensity,
        volume=_available_signal(language, "signal.volume", volume_code),
        session_type=_available_signal(language, "signal.session_type", session_type_code),
    )


def _build_comparison(workout: dict, workouts: List[dict]) -> WorkoutAnalysisComparison:
    baseline = _build_baseline(workouts, workout, days=14)
    sample_count = baseline["sample_count"]
    available = sample_count > 0
    return WorkoutAnalysisComparison(
        available=available,
        baseline_period_days=baseline["period_days"],
        baseline_sample_count=sample_count,
        distance_km=_comparison_metric(workout.get("distance_km"), baseline.get("avg_distance_km")),
        duration_minutes=_comparison_metric(workout.get("duration_minutes"), baseline.get("avg_duration_minutes")),
        avg_heart_rate=_comparison_metric(workout.get("avg_heart_rate"), baseline.get("avg_heart_rate")),
        avg_pace_min_km=_comparison_metric(workout.get("avg_pace_min_km"), baseline.get("avg_pace_min_km"), digits=3),
        avg_speed_kmh=_comparison_metric(workout.get("avg_speed_kmh"), baseline.get("avg_speed_kmh")),
        reason_unavailable=None if available else _template("en", "unavailable.baseline", days=baseline["period_days"]),
    )


def _localized_comparison(workout: dict, workouts: List[dict], language: str) -> WorkoutAnalysisComparison:
    comparison = _build_comparison(workout, workouts)
    if not comparison.available:
        comparison.reason_unavailable = _template(language, "unavailable.baseline", days=comparison.baseline_period_days)
    return comparison


def _build_summary(signals: WorkoutAnalysisSignals, language: str) -> AnalysisText:
    if signals.intensity.available and signals.intensity.code:
        key = {
            "very_high": "summary.high_with_hr",
            "high": "summary.high_with_hr",
            "moderate": "summary.moderate_with_hr",
            "low": "summary.easy_with_hr",
        }[signals.intensity.code]
        return AnalysisText(code=key, text=_template(language, key))

    key = {
        "long": "summary.long_structural",
        "short": "summary.short_structural",
    }.get(signals.session_type.code, "summary.standard_structural")
    return AnalysisText(code=key, text=_template(language, key))


def _build_meaning(
    physiology: WorkoutAnalysisPhysiology,
    pacing: WorkoutAnalysisPacing,
    signals: WorkoutAnalysisSignals,
    language: str,
) -> AnalysisText:
    if signals.intensity.available and signals.intensity.code:
        if signals.intensity.code in {"high", "very_high"}:
            code = "meaning.with_hr_high"
        elif signals.intensity.code == "low":
            code = "meaning.with_hr_easy"
        else:
            code = "meaning.with_hr_moderate"
        return AnalysisText(code=code, text=_template(language, code))

    if physiology.available:
        code = "meaning.hr_without_intensity_with_pacing" if pacing.available else "meaning.hr_without_intensity_no_pacing"
        return AnalysisText(code=code, text=_template(language, code))

    code = "meaning.no_hr_with_pacing" if pacing.available else "meaning.no_hr_no_pacing"
    return AnalysisText(code=code, text=_template(language, code))


def _build_advice(physiology: WorkoutAnalysisPhysiology, signals: WorkoutAnalysisSignals, language: str) -> AnalysisText:
    if signals.intensity.available and signals.intensity.code in {"high", "very_high"}:
        code = "advice.recover_after_hard"
    elif signals.intensity.available and signals.intensity.code == "low":
        code = "advice.maintain_easy"
    elif physiology.available:
        code = "advice.hr_without_intensity"
    else:
        code = "advice.no_hr"
    return AnalysisText(code=code, text=_template(language, code))


def build_workout_analysis_v2(workout: dict, historical_workouts: List[dict], language: str = "en") -> WorkoutAnalysisV2Response:
    comparison = _localized_comparison(workout, historical_workouts, language)
    physiology = _build_physiology(workout, language)
    pacing = _build_pacing(workout, language)
    signals = _build_signals(workout, comparison, physiology, language)
    summary = _build_summary(signals, language)
    meaning = _build_meaning(physiology, pacing, signals, language)
    advice = _build_advice(physiology, signals, language)
    evidence = WorkoutAnalysisEvidence(
        has_heart_rate=physiology.available,
        has_hr_zones=bool(physiology.zone_distribution),
        has_splits=bool((workout.get("km_splits") or []) or (workout.get("split_analysis") or {})),
        has_baseline=comparison.available,
        has_cadence=workout.get("avg_cadence_spm") is not None or bool(workout.get("cadence_analysis")),
        has_elevation=workout.get("elevation_gain_m") is not None or bool(workout.get("elevation_analysis")),
    )
    return WorkoutAnalysisV2Response(
        workout=WorkoutAnalysisWorkout(
            id=workout.get("id", ""),
            name=workout.get("name", ""),
            date=workout.get("date", ""),
            type=workout.get("type", ""),
        ),
        summary=summary,
        signals=signals,
        physiology=physiology,
        pacing=pacing,
        comparison=comparison,
        meaning=meaning,
        advice=advice,
        evidence=evidence,
    )
