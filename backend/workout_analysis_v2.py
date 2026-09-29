from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Dict, List, Optional

from pydantic import BaseModel


SUPPORTED_LANGUAGES = {"en", "fr", "es"}
HISTORY_WINDOW_DAYS = 90
HISTORY_CANDIDATE_LIMIT = 200
COMPARISON_SAMPLE_LIMIT = 3
MIN_COMPARISON_SAMPLE = 2
SIMILAR_DISTANCE_TOLERANCE = 0.30

_OBSERVATION_LABELS = {
    "en": {
        "distance": "distance: {value} km",
        "duration": "duration: {value} min",
        "pace": "average pace: {value}/km",
        "speed": "average speed: {value} km/h",
        "avg_hr": "average HR: {value} bpm",
        "max_hr": "maximum HR: {value} bpm",
        "fastest_split": "fastest split: {value}/km",
        "slowest_split": "slowest split: {value}/km",
        "pace_drop": "recorded pace drop: {value} min/km",
        "consistency": "pacing consistency score: {value}/100",
        "variability": "pace variability: {value} min/km",
        "hr_drift": "recorded HR drift: {value} bpm",
        "cadence": "average cadence: {value} spm",
        "elevation": "elevation gain: {value} m",
        "negative_split": "a negative split was recorded",
    },
    "fr": {
        "distance": "distance : {value} km",
        "duration": "durée : {value} min",
        "pace": "allure moyenne : {value}/km",
        "speed": "vitesse moyenne : {value} km/h",
        "avg_hr": "FC moyenne : {value} bpm",
        "max_hr": "FC maximale : {value} bpm",
        "fastest_split": "fraction la plus rapide : {value}/km",
        "slowest_split": "fraction la plus lente : {value}/km",
        "pace_drop": "baisse d’allure enregistrée : {value} min/km",
        "consistency": "score de régularité de l’allure : {value}/100",
        "variability": "variabilité de l’allure : {value} min/km",
        "hr_drift": "dérive cardiaque enregistrée : {value} bpm",
        "cadence": "cadence moyenne : {value} pas/min",
        "elevation": "dénivelé positif : {value} m",
        "negative_split": "un negative split a été enregistré",
    },
    "es": {
        "distance": "distancia: {value} km",
        "duration": "duración: {value} min",
        "pace": "ritmo medio: {value}/km",
        "speed": "velocidad media: {value} km/h",
        "avg_hr": "FC media: {value} bpm",
        "max_hr": "FC máxima: {value} bpm",
        "fastest_split": "fracción más rápida: {value}/km",
        "slowest_split": "fracción más lenta: {value}/km",
        "pace_drop": "descenso de ritmo registrado: {value} min/km",
        "consistency": "puntuación de regularidad del ritmo: {value}/100",
        "variability": "variabilidad del ritmo: {value} min/km",
        "hr_drift": "deriva cardíaca registrada: {value} bpm",
        "cadence": "cadencia media: {value} pasos/min",
        "elevation": "desnivel positivo: {value} m",
        "negative_split": "se registró un negative split",
    },
}

_COMPARISON_TEXT = {
    "en": "Among {count} selected prior comparable sessions (maximum {limit}) in the last {days} days (distance within ±30%), {metric}; this is a comparison, not evidence by itself of progression.",
    "fr": "Parmi {count} séances antérieures comparables retenues (maximum {limit}) sur les {days} derniers jours (distance à ±30 %), {metric} ; cette comparaison ne suffit pas à établir une progression.",
    "es": "Entre {count} sesiones anteriores comparables seleccionadas (máximo {limit}) de los últimos {days} días (distancia dentro de ±30 %), {metric}; esta comparación por sí sola no demuestra una progresión.",
}

_COMPARISON_UNAVAILABLE = {
    "en": {
        "none": "No prior same-sport sessions within ±30% of this distance in the last {days} days.",
        "insufficient": "Only {count} prior comparable session was found in the last {days} days; at least {minimum} are needed for a baseline.",
    },
    "fr": {
        "none": "Aucune séance antérieure du même sport et à ±30 % de cette distance sur les {days} derniers jours.",
        "insufficient": "Une seule séance antérieure comparable a été trouvée sur les {days} derniers jours ; au moins {minimum} sont nécessaires pour établir une référence.",
    },
    "es": {
        "none": "No hay sesiones anteriores del mismo deporte y dentro de ±30 % de esta distancia en los últimos {days} días.",
        "insufficient": "Solo se encontró una sesión comparable en los últimos {days} días; se necesitan al menos {minimum} para establecer una referencia.",
    },
}

_ADVICE_TEXT = {
    "en": {
        "comparison": "Use the comparison with {count} similar-distance sessions as context only; it does not establish a training progression.",
        "splits": "Use the recorded split pattern ({fastest}–{slowest}/km) to describe execution; it does not establish physiological intensity.",
        "hr": "Treat the recorded heart-rate values ({avg_hr} bpm average{max_hr}) as observations; this analysis does not assign an intensity zone.",
        "structure": "Use the recorded distance and duration as the available session evidence; missing measures remain unknown.",
        "none": "Only limited session data are available, so no further interpretation is supported.",
    },
    "fr": {
        "comparison": "Utilise la comparaison avec {count} séances de distance similaire comme contexte uniquement ; elle n’établit pas une progression d’entraînement.",
        "splits": "Utilise les fractions enregistrées ({fastest}–{slowest}/km) pour décrire l’exécution ; elles ne déterminent pas l’intensité physiologique.",
        "hr": "Considère la fréquence cardiaque enregistrée (moyenne : {avg_hr} bpm{max_hr}) comme une observation ; cette analyse n’attribue pas de zone d’intensité.",
        "structure": "Appuie-toi sur la distance et la durée enregistrées ; les mesures absentes restent inconnues.",
        "none": "Les données disponibles sont limitées et ne permettent pas d’interprétation supplémentaire.",
    },
    "es": {
        "comparison": "Usa la comparación con {count} sesiones de distancia similar solo como contexto; no demuestra una progresión de entrenamiento.",
        "splits": "Usa las fracciones registradas ({fastest}–{slowest}/km) para describir la ejecución; no determinan la intensidad fisiológica.",
        "hr": "Considera los valores de frecuencia cardíaca registrados (media: {avg_hr} bpm{max_hr}) como observaciones; este análisis no asigna una zona de intensidad.",
        "structure": "Usa la distancia y duración registradas como evidencia disponible; las medidas ausentes siguen siendo desconocidas.",
        "none": "Los datos disponibles son limitados y no permiten una interpretación adicional.",
    },
}


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


def workout_analysis_candidate_date_bounds(workout_date: str, days: int = HISTORY_WINDOW_DAYS) -> tuple[str, str]:
    current_date = _parse_workout_date(workout_date)
    cutoff_date = (current_date - timedelta(days=days)).date().isoformat()
    upper_bound = current_date.date().isoformat()
    return cutoff_date, upper_bound


def workout_analysis_candidate_distance_bounds(distance_km: object) -> Optional[tuple[float, float]]:
    distance = _finite_number(distance_km)
    if distance is None or distance <= 0:
        return None
    return (
        distance * (1 - SIMILAR_DISTANCE_TOLERANCE),
        distance * (1 + SIMILAR_DISTANCE_TOLERANCE),
    )


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
    numeric = _finite_number(value)
    if numeric is None:
        return None
    return round(numeric, digits)


def _finite_number(value: object) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    try:
        numeric = float(value)
    except (TypeError, ValueError):
        return None
    return numeric if math.isfinite(numeric) else None


def _positive_number(value: object) -> Optional[float]:
    numeric = _finite_number(value)
    return numeric if numeric is not None and numeric > 0 else None


def _workout_average_pace(workout: dict) -> Optional[float]:
    recorded_pace = _positive_number(workout.get("avg_pace_min_km"))
    if recorded_pace is not None:
        return recorded_pace
    if workout.get("type") != "run":
        return None
    distance = _positive_number(workout.get("distance_km"))
    duration = _positive_number(workout.get("duration_minutes"))
    if distance is None or duration is None:
        return None
    return duration / distance


def _format_number(value: float, digits: int, language: str) -> str:
    formatted = f"{value:.{digits}f}"
    if digits:
        formatted = formatted.rstrip("0").rstrip(".")
    if _lang(language) in {"fr", "es"}:
        formatted = formatted.replace(".", ",")
    return formatted


def _format_pace(value: Optional[float]) -> Optional[str]:
    if value is None or value <= 0:
        return None
    total_seconds = round(value * 60)
    minutes, seconds = divmod(total_seconds, 60)
    return f"{minutes}:{seconds:02d}"


def _observation(language: str, key: str, value: object, digits: int = 1) -> Optional[str]:
    numeric = _finite_number(value)
    if numeric is None:
        return None
    text = _OBSERVATION_LABELS[_lang(language)][key]
    return text.format(value=_format_number(numeric, digits, language))


def _pace_observation(language: str, key: str, value: Optional[float]) -> Optional[str]:
    pace = _format_pace(value)
    if pace is None:
        return None
    return _OBSERVATION_LABELS[_lang(language)][key].format(value=pace)


def _safe_avg(values: List[Optional[float]]) -> Optional[float]:
    valid = [numeric for value in values if (numeric := _finite_number(value)) is not None]
    return _safe_round(sum(valid) / len(valid), 2) if valid else None


def _comparison_metric(current: Optional[float], baseline: Optional[float], digits: int = 2) -> Optional[WorkoutAnalysisComparisonMetric]:
    current_value = _finite_number(current)
    baseline_value = _finite_number(baseline)
    if current_value is None or baseline_value is None:
        return None
    difference = current_value - baseline_value
    percent_change = (difference / baseline_value * 100) if baseline_value else None
    return WorkoutAnalysisComparisonMetric(
        current=_safe_round(current_value, digits),
        baseline=_safe_round(baseline_value, digits),
        difference=_safe_round(difference, digits),
        percent_change=_safe_round(percent_change, 1) if percent_change is not None else None,
    )


def _extract_split_paces(workout: dict) -> List[float]:
    paces: List[float] = []
    for split in workout.get("km_splits") or []:
        if not isinstance(split, dict):
            continue
        pace = split.get("pace_min_km")
        numeric = _positive_number(pace)
        if numeric is not None:
            paces.append(numeric)
    return paces


def _build_baseline(
    workouts: List[dict],
    current_workout: dict,
    days: int = HISTORY_WINDOW_DAYS,
) -> dict:
    current_date = _parse_workout_date(current_workout.get("date", ""))
    cutoff_date = current_date - timedelta(days=days)
    current_type = current_workout.get("type")
    if not isinstance(current_type, str) or not current_type.strip():
        return {"period_days": days, "sample_count": 0, "workouts": []}
    distance_bounds = workout_analysis_candidate_distance_bounds(current_workout.get("distance_km"))
    if distance_bounds is None:
        return {"period_days": days, "sample_count": 0, "workouts": []}
    min_distance, max_distance = distance_bounds
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
        distance = _positive_number(workout.get("distance_km"))
        if (
            cutoff_date <= workout_date < current_date
            and distance is not None
            and min_distance <= distance <= max_distance
        ):
            prior_same_type.append(workout)

    prior_same_type.sort(key=lambda workout: _parse_workout_date(workout["date"]), reverse=True)
    prior_same_type = prior_same_type[:COMPARISON_SAMPLE_LIMIT]
    sample_count = len(prior_same_type)
    if sample_count < MIN_COMPARISON_SAMPLE:
        return {
            "period_days": days,
            "sample_count": sample_count,
            "workouts": prior_same_type,
        }

    def comparable_average(field: str) -> Optional[float]:
        if field == "avg_pace_min_km":
            values = [_workout_average_pace(workout) for workout in prior_same_type]
        else:
            values = [_finite_number(workout.get(field)) for workout in prior_same_type]
        valid = [value for value in values if value is not None]
        return _safe_avg(valid) if len(valid) >= MIN_COMPARISON_SAMPLE else None

    return {
        "period_days": days,
        "sample_count": sample_count,
        "workouts": prior_same_type,
        "avg_distance_km": comparable_average("distance_km"),
        "avg_duration_minutes": comparable_average("duration_minutes"),
        "avg_heart_rate": comparable_average("avg_heart_rate"),
        "avg_pace_min_km": comparable_average("avg_pace_min_km"),
        "avg_speed_kmh": comparable_average("avg_speed_kmh"),
    }


def _build_pacing(workout: dict, language: str) -> WorkoutAnalysisPacing:
    avg_pace = _workout_average_pace(workout)
    avg_speed = _positive_number(workout.get("avg_speed_kmh"))
    split_analysis = workout.get("split_analysis")
    split_analysis = split_analysis if isinstance(split_analysis, dict) else {}
    pace_stats = workout.get("pace_stats")
    pace_stats = pace_stats if isinstance(pace_stats, dict) else {}
    split_paces = _extract_split_paces(workout)

    fastest_split = _positive_number(split_analysis.get("fastest_split_pace"))
    slowest_split = _positive_number(split_analysis.get("slowest_split_pace"))
    if fastest_split is None and split_paces:
        fastest_split = min(split_paces)
    if slowest_split is None and split_paces:
        slowest_split = max(split_paces)

    pace_drop = _finite_number(split_analysis.get("pace_drop"))
    variability = _finite_number(pace_stats.get("pace_variability"))
    if variability is not None and variability < 0:
        variability = None
    consistency = _finite_number(split_analysis.get("consistency_score"))
    if consistency is not None and not 0 <= consistency <= 100:
        consistency = None
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
        negative_split=(
            split_analysis.get("negative_split")
            if isinstance(split_analysis.get("negative_split"), bool)
            else None
        ),
        consistency_score=_safe_round(consistency, 1),
        variability=_safe_round(variability, 3),
        reason_unavailable=None if available else _template(language, "unavailable.pacing"),
    )


def _normalize_zone_distribution(raw_zones: dict | None) -> Optional[Dict[str, float]]:
    if not isinstance(raw_zones, dict):
        return None

    normalized: Dict[str, float] = {}
    for key in ("z1", "z2", "z3", "z4", "z5"):
        value = raw_zones.get(key)
        if value is None:
            continue
        try:
            numeric = float(value)
        except (TypeError, ValueError):
            continue
        if not math.isfinite(numeric) or numeric < 0 or numeric > 100:
            continue
        normalized[key] = numeric

    return normalized or None


def _build_physiology(workout: dict, language: str) -> WorkoutAnalysisPhysiology:
    hr_analysis = workout.get("hr_analysis")
    hr_analysis = hr_analysis if isinstance(hr_analysis, dict) else {}
    avg_hr_value = _positive_number(workout.get("avg_heart_rate"))
    max_hr_value = _positive_number(workout.get("max_heart_rate"))
    avg_hr = int(round(avg_hr_value)) if avg_hr_value is not None else None
    max_hr = int(round(max_hr_value)) if max_hr_value is not None else None
    zone_distribution = _normalize_zone_distribution(workout.get("effort_zone_distribution"))
    hr_drift = _finite_number(hr_analysis.get("hr_drift"))
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


def _structural_size_code(workout: dict) -> str:
    duration = _positive_number(workout.get("duration_minutes"))
    distance = _positive_number(workout.get("distance_km"))
    workout_type = (workout.get("type") or "").lower()

    if workout_type == "run":
        if (duration is not None and duration >= 90) or (distance is not None and distance >= 15):
            return "long"
        if (duration is not None and duration <= 25) or (distance is not None and distance <= 4):
            return "short"
        return "standard"

    if duration is not None and duration >= 90:
        return "long"
    if duration is not None and duration <= 25:
        return "short"
    return "standard"


def _volume_code(workout: dict, comparison: WorkoutAnalysisComparison) -> str:
    if comparison.available and comparison.distance_km and comparison.distance_km.percent_change is not None:
        pct = comparison.distance_km.percent_change
        if pct >= 15:
            return "above_recent"
        if pct <= -15:
            return "below_recent"
        return "usual_recent"

    structural_size = _structural_size_code(workout)
    if structural_size == "long":
        return "long_volume"
    if structural_size == "short":
        return "short_volume"
    return "medium_volume"


def _session_type_code(workout: dict, intensity_code: Optional[str]) -> str:
    if intensity_code in {"high", "very_high"}:
        return "hard"
    if intensity_code == "low":
        return "easy"
    return _structural_size_code(workout)


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
    baseline = _build_baseline(workouts, workout, days=HISTORY_WINDOW_DAYS)
    sample_count = baseline["sample_count"]
    available = sample_count >= MIN_COMPARISON_SAMPLE
    return WorkoutAnalysisComparison(
        available=available,
        baseline_period_days=baseline["period_days"],
        baseline_sample_count=sample_count,
        distance_km=_comparison_metric(workout.get("distance_km"), baseline.get("avg_distance_km")),
        duration_minutes=_comparison_metric(workout.get("duration_minutes"), baseline.get("avg_duration_minutes")),
        avg_heart_rate=_comparison_metric(workout.get("avg_heart_rate"), baseline.get("avg_heart_rate")),
        avg_pace_min_km=_comparison_metric(_workout_average_pace(workout), baseline.get("avg_pace_min_km"), digits=3),
        avg_speed_kmh=_comparison_metric(workout.get("avg_speed_kmh"), baseline.get("avg_speed_kmh")),
        reason_unavailable=None,
    )


def _localized_comparison(workout: dict, workouts: List[dict], language: str) -> WorkoutAnalysisComparison:
    comparison = _build_comparison(workout, workouts)
    if comparison.baseline_sample_count < MIN_COMPARISON_SAMPLE:
        lang = _lang(language)
        reason_key = "insufficient" if comparison.baseline_sample_count else "none"
        comparison.reason_unavailable = _COMPARISON_UNAVAILABLE[lang][reason_key].format(
            count=comparison.baseline_sample_count,
            days=comparison.baseline_period_days,
            minimum=MIN_COMPARISON_SAMPLE,
        )
    return comparison


def _build_summary(
    workout: dict,
    pacing: WorkoutAnalysisPacing,
    physiology: WorkoutAnalysisPhysiology,
    signals: WorkoutAnalysisSignals,
    language: str,
) -> AnalysisText:
    key = {
        "long": "summary.long_structural",
        "short": "summary.short_structural",
    }.get(signals.session_type.code, "summary.standard_structural")
    facts = [
        _observation(language, "distance", workout.get("distance_km"), digits=2),
        _observation(language, "duration", workout.get("duration_minutes"), digits=0),
        _pace_observation(language, "pace", pacing.average_pace_min_km),
        _observation(language, "speed", pacing.average_speed_kmh, digits=2),
        _observation(language, "avg_hr", physiology.avg_hr, digits=0),
        _observation(language, "max_hr", physiology.max_hr, digits=0),
    ]
    details = "; ".join(fact for fact in facts if fact)
    text = _template(language, key)
    return AnalysisText(code=key, text=f"{text} {details}".strip())


def _comparison_observation(comparison: WorkoutAnalysisComparison, language: str) -> Optional[str]:
    if not comparison.available:
        return None
    labels = {
        "en": {
            "pace": "average pace",
            "speed": "average speed",
            "hr": "average HR",
            "distance": "distance",
            "duration": "duration",
            "reference": "reference average",
        },
        "fr": {
            "pace": "allure moyenne",
            "speed": "vitesse moyenne",
            "hr": "FC moyenne",
            "distance": "distance",
            "duration": "durée",
            "reference": "moyenne de référence",
        },
        "es": {
            "pace": "ritmo medio",
            "speed": "velocidad media",
            "hr": "FC media",
            "distance": "distancia",
            "duration": "duración",
            "reference": "promedio de referencia",
        },
    }[_lang(language)]
    metrics = (
        ("pace", comparison.avg_pace_min_km, True, "/km"),
        ("speed", comparison.avg_speed_kmh, False, " km/h"),
        ("hr", comparison.avg_heart_rate, False, " bpm"),
        ("distance", comparison.distance_km, False, " km"),
        ("duration", comparison.duration_minutes, False, " min"),
    )
    details = []
    for label_key, metric, is_pace, suffix in metrics:
        if metric is None:
            continue
        if is_pace:
            current = _format_pace(metric.current)
            baseline = _format_pace(metric.baseline)
        else:
            current = _format_number(metric.current, 1, language) if metric.current is not None else None
            baseline = _format_number(metric.baseline, 1, language) if metric.baseline is not None else None
        if current is not None and baseline is not None:
            details.append(f"{labels[label_key]}: {current}{suffix} ({labels['reference']} {baseline}{suffix})")
    if not details:
        return None
    return _COMPARISON_TEXT[_lang(language)].format(
        count=comparison.baseline_sample_count,
        limit=COMPARISON_SAMPLE_LIMIT,
        days=comparison.baseline_period_days,
        metric="; ".join(details),
    )


def _build_meaning(
    workout: dict,
    physiology: WorkoutAnalysisPhysiology,
    pacing: WorkoutAnalysisPacing,
    signals: WorkoutAnalysisSignals,
    comparison: WorkoutAnalysisComparison,
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

    code = (
        "meaning.hr_without_intensity_with_pacing"
        if physiology.available and pacing.available
        else "meaning.hr_without_intensity_no_pacing"
        if physiology.available
        else "meaning.no_hr_with_pacing"
        if pacing.available
        else "meaning.no_hr_no_pacing"
    )
    facts = [
        _observation(language, "avg_hr", physiology.avg_hr, digits=0),
        _observation(language, "max_hr", physiology.max_hr, digits=0),
        _pace_observation(language, "fastest_split", pacing.fastest_split_min_km),
        _pace_observation(language, "slowest_split", pacing.slowest_split_min_km),
        _observation(language, "pace_drop", pacing.pace_drop_min_km, digits=3),
        _observation(language, "consistency", pacing.consistency_score, digits=1),
        _observation(language, "variability", pacing.variability, digits=3),
        _observation(language, "hr_drift", physiology.hr_drift, digits=1),
        _observation(language, "cadence", _positive_number(workout.get("avg_cadence_spm")), digits=0),
    ]
    elevation_gain = _finite_number(workout.get("elevation_gain_m"))
    if elevation_gain is not None and elevation_gain >= 0:
        facts.append(_observation(language, "elevation", elevation_gain, digits=0))
    if pacing.negative_split is True:
        facts.append(_OBSERVATION_LABELS[_lang(language)]["negative_split"])
    comparison_fact = _comparison_observation(comparison, language)
    if comparison_fact:
        facts.append(comparison_fact)
    detail = "; ".join(fact for fact in facts if fact)
    intro = {
        "en": "Recorded session observations:",
        "fr": "Observations enregistrées de la séance :",
        "es": "Observaciones registradas de la sesión:",
    }[_lang(language)]
    fallback = {
        "en": "No split-based, heart-rate, or comparable-history observations are available.",
        "fr": "Aucune observation exploitable sur les fractions, la fréquence cardiaque ou l’historique comparable n’est disponible.",
        "es": "No hay observaciones disponibles sobre fracciones, frecuencia cardíaca o historial comparable.",
    }[_lang(language)]
    return AnalysisText(code=code, text=f"{intro} {detail}" if detail else fallback)


def _build_advice(
    workout: dict,
    physiology: WorkoutAnalysisPhysiology,
    pacing: WorkoutAnalysisPacing,
    comparison: WorkoutAnalysisComparison,
    language: str,
) -> AnalysisText:
    lang = _lang(language)
    if comparison.available:
        advice_key = "comparison"
        params = {"count": comparison.baseline_sample_count}
    elif pacing.fastest_split_min_km is not None and pacing.slowest_split_min_km is not None:
        advice_key = "splits"
        params = {
            "fastest": _format_pace(pacing.fastest_split_min_km),
            "slowest": _format_pace(pacing.slowest_split_min_km),
        }
    elif physiology.avg_hr is not None:
        advice_key = "hr"
        max_hr_text = f", maximum {physiology.max_hr}" if physiology.max_hr is not None else ""
        params = {"avg_hr": physiology.avg_hr, "max_hr": max_hr_text}
    elif _positive_number(workout.get("distance_km")) is not None or _positive_number(workout.get("duration_minutes")) is not None:
        advice_key = "structure"
        params = {}
    else:
        advice_key = "none"
        params = {}
    code = "advice.hr_without_intensity" if physiology.available else "advice.no_hr"
    return AnalysisText(code=code, text=_ADVICE_TEXT[lang][advice_key].format(**params))


def build_workout_analysis_v2(workout: dict, historical_workouts: List[dict], language: str = "en") -> WorkoutAnalysisV2Response:
    comparison = _localized_comparison(workout, historical_workouts, language)
    physiology = _build_physiology(workout, language)
    pacing = _build_pacing(workout, language)
    signals = _build_signals(workout, comparison, physiology, language)
    summary = _build_summary(workout, pacing, physiology, signals, language)
    meaning = _build_meaning(workout, physiology, pacing, signals, comparison, language)
    advice = _build_advice(workout, physiology, pacing, comparison, language)
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
