from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from statistics import mean
from typing import Dict, List, Optional

from pydantic import BaseModel, Field


SUPPORTED_LANGUAGES = {"en", "fr", "es"}

# Baseline window kept identical to the V2 contract (comparison.baseline_period_days).
BASELINE_PERIOD_DAYS = 14

# Bounded historical search restored from the legacy retrieve_similar_workouts()
# capability, without restoring rag_engine.py itself.
SIMILAR_HISTORY_WINDOW_DAYS = 180
SIMILAR_DISTANCE_TOLERANCE_PCT = 30.0
SIMILAR_MAX_RESULTS = 5
SIMILAR_MIN_COMPARABLE_SAMPLE = 2

# Explicit metadata keys that may carry a real training/competition distinction.
# Nothing is ever inferred from the session name or from its distance.
_RACE_METADATA_KEYS = ("is_race", "race", "event_type", "workout_type", "activity_category")
_RACE_METADATA_VALUES = {"race", "competition", "event", "compétition", "carrera"}
_TRAINING_METADATA_VALUES = {"training", "workout", "entrainement", "entraînement", "entrenamiento"}


class AnalysisText(BaseModel):
    code: str
    text: str


class WorkoutAnalysisAdvice(AnalysisText):
    available: bool = False


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


class WorkoutAnalysisSimilarReference(BaseModel):
    available: bool
    comparable: bool = False
    sample_count: int = 0
    period_days: int = SIMILAR_HISTORY_WINDOW_DAYS
    distance_tolerance_pct: float = SIMILAR_DISTANCE_TOLERANCE_PCT
    min_comparable_sample: int = SIMILAR_MIN_COMPARABLE_SAMPLE
    workout_ids: List[str] = []
    avg_distance_km: Optional[float] = None
    avg_pace_min_km: Optional[float] = None
    avg_heart_rate: Optional[float] = None
    distance_sample_count: int = 0
    pace_sample_count: int = 0
    pace_avg_distance_km: Optional[float] = None
    hr_sample_count: int = 0
    pace_difference_min_km: Optional[float] = None
    heart_rate_difference_bpm: Optional[float] = None
    limitations: List[str] = []
    reason_unavailable: Optional[str] = None


class WorkoutAnalysisComparison(BaseModel):
    available: bool
    baseline_period_days: int
    baseline_sample_count: int
    distance_km: Optional[WorkoutAnalysisComparisonMetric] = None
    duration_minutes: Optional[WorkoutAnalysisComparisonMetric] = None
    avg_heart_rate: Optional[WorkoutAnalysisComparisonMetric] = None
    avg_pace_min_km: Optional[WorkoutAnalysisComparisonMetric] = None
    avg_speed_kmh: Optional[WorkoutAnalysisComparisonMetric] = None
    similar: Optional[WorkoutAnalysisSimilarReference] = None
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
    advice: WorkoutAnalysisAdvice
    evidence: WorkoutAnalysisEvidence
    limitations: List[AnalysisText] = Field(default_factory=list)


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


def workout_analysis_candidate_date_bounds(workout_date: str, days: int = SIMILAR_HISTORY_WINDOW_DAYS) -> tuple[str, str]:
    current_date = _parse_workout_date(workout_date)
    cutoff_date = (current_date - timedelta(days=days)).date().isoformat()
    upper_bound = (current_date.date() + timedelta(days=1)).isoformat()
    return cutoff_date, upper_bound


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
            "signal.volume.below_recent": "Distance below the recent average",
            "signal.volume.usual_recent": "Distance close to the recent average",
            "signal.volume.above_recent": "Distance above the recent average",
            "signal.volume.short_volume": "Short session volume",
            "signal.volume.medium_volume": "Moderate session volume",
            "signal.volume.long_volume": "Long session volume",
            "signal.session_type.easy": "Easy session",
            "signal.session_type.standard": "Standard session",
            "signal.session_type.hard": "Hard session",
            "signal.session_type.long": "Long session",
            "signal.session_type.short": "Short session",
            "meaning.with_hr_easy": "The reliable zone evidence indicates low intensity.",
            "meaning.with_hr_moderate": "The reliable zone evidence indicates moderate intensity.",
            "meaning.with_hr_high": "The reliable zone evidence indicates high intensity.",
            "meaning.hr_without_intensity_with_pacing": "Pacing and cardiac data are recorded. Physiological intensity cannot be reliably determined.",
            "meaning.hr_without_intensity_no_pacing": "Cardiac data are recorded. Physiological intensity cannot be reliably determined.",
            "meaning.no_hr_with_pacing": "Pacing data describe the session, but do not establish its physiological intensity.",
            "meaning.no_hr_no_pacing": "The available data do not support a meaningful interpretation of this session.",
            "meaning.pace_change": "The recorded splits show a marked pace change during this session.",
            "meaning.negative_split": "The recorded splits show a faster second half.",
            "meaning.consistent_pacing": "The recorded pacing is regular.",
            "meaning.hr_drift": "Heart-rate drift is recorded, without an established cause.",
            "meaning.intensity_unavailable": "Physiological intensity cannot be reliably determined.",
            "advice.unavailable": "No usable coaching observation is available from these data.",
            "limitations.intensity": "Individualized zone evidence is missing or unverified; physiological intensity is unavailable.",
            "limitations.heart_rate": "No cardiac data are available.",
            "limitations.splits": "No kilometre splits or split analysis are available; pace distribution cannot be described.",
            "limitations.baseline": "No recent same-type baseline is available.",
            "limitations.baseline_descriptive": "The recent baseline is descriptive only; session distances or natures may differ.",
            "limitations.comparability": "Historical comparability is not established; differences are not evidence of progress.",
            "limitations.no_comparable_reference": "No earlier session of comparable distance is available.",
            "limitations.sample_too_small": "Too few similar sessions are available for a reliable comparison.",
            "limitations.pace_sample_too_small": "Too few similar sessions have usable pacing data.",
            "limitations.hr_sample_too_small": "Too few similar sessions have usable heart-rate data.",
            "limitations.session_nature_unknown": "The training-versus-race nature is not recorded; comparability remains limited.",
            "advice.high_intensity_observation": "The zone evidence places this session in the demanding range; what follows it is determined by Training Today/Week, not by this analysis.",
            "advice.low_intensity_observation": "The zone evidence places this session in the controlled aerobic range; what follows it is determined by Training Today/Week, not by this analysis.",
            "advice.hr_without_intensity": "Limit of this analysis: without individualized heart-rate zones, the recorded heart-rate values cannot be read as intensity evidence.",
            "advice.no_hr": "Limit of this analysis: no heart-rate data was recorded, so no physiological reading of this session is possible.",
            "unavailable.hr": "Heart-rate evidence is unavailable.",
            "unavailable.intensity": "Intensity classification is unavailable without individualized physiological evidence.",
            "unavailable.pacing": "Pacing evidence is unavailable.",
            "unavailable.baseline": "No prior same-type workouts in the last {days} days.",
            "fact.distance_duration": "You covered {distance} km in {duration}.",
            "fact.distance_duration_pace": "You covered {distance} km in {duration} at {pace}.",
            "fact.distance_duration_speed": "You covered {distance} km in {duration} at {speed} km/h.",
            "fact.duration_only": "{duration} of recorded activity.",
            "fact.hr_avg": "Your average heart rate was {avg_hr} bpm.",
            "fact.hr_avg_max": "Your average heart rate was {avg_hr} bpm (peak {max_hr} bpm).",
            "fact.hr_max_only": "Your peak heart rate was {max_hr} bpm.",
            "fact.splits_range": "Kilometre splits ran from {fastest} to {slowest} ({count} splits recorded).",
            "fact.pace_drop": "Recorded pace drop of {drop} across the session.",
            "fact.negative_split": "The recorded split data confirms a negative split.",
            "fact.consistency": "Split consistency score: {score}/100.",
            "fact.variability": "Recorded pace variability: {variability}.",
            "fact.hr_drift": "Heart-rate drift measured at {drift} bpm between the start and the end; this measurement alone does not establish its cause.",
            "fact.elevation": "Elevation gain: {elevation} m.",
            "fact.cadence": "Average cadence: {cadence} spm, reported as recorded and not compared with any universal target.",
            "fact.baseline_distance": "Distance is {delta} ({percent}) against the raw {count}-session average of the last {days} days ({baseline} km); that average may include sessions of different distances or natures and is not a performance comparison.",
            "fact.similar_pace": "Across {count} earlier session(s) of comparable distance carrying a usable pace (±{tolerance}% over {days} days, average {avg_distance} km), average pace was {baseline}; this session is {delta}.",
            "fact.similar_pace_coverage_small": "That pace average rests on {count} of the {total} earlier session(s) found, below the {minimum} this analysis requires before reading the pace gap as anything more than a raw difference.",
            "fact.similar_hr": "Average heart rate across {count} earlier session(s) of comparable distance carrying a usable heart rate was {baseline} bpm; this session is {delta} bpm.",
            "fact.similar_hr_coverage_small": "That heart-rate average rests on {count} of the {total} earlier session(s) found, below the {minimum} this analysis requires before reading the heart-rate gap as anything more than a raw difference.",
            "fact.similar_sample_small": "Only {count} earlier session(s) of comparable distance were found, below the {minimum} this analysis requires before any difference is read as more than a raw gap.",
            "fact.similar_unavailable": "No earlier session of comparable distance (±{tolerance}%) was found within {days} days, so no historical comparison is available.",
            "fact.similar_nature_unknown": "The training-versus-race nature of these sessions is not recorded, so their comparability stays limited and the difference above is a raw gap, not a performance conclusion.",
            "advice.even_pacing": "The recorded pace change is a useful data point to compare with future sessions of similar distance.",
            "advice.negative_split_confirmed": "A negative split is observed on this session; this profile can serve as a comparison point with similar sessions.",
            "advice.maintain_consistency": "Pace regularity was high on this session, which makes it a clear reference point when comparing sessions of similar distance.",
            "advice.monitor_hr_drift": "The measured heart-rate drift is a data point to compare across comparable sessions; this analysis does not establish its cause.",
            "advice.recover_after_long": "This session is structurally classified as long; recovery and what follows remain determined by Training Today/Week.",
            "advice.complement.record_splits": "Limit of this analysis: no kilometre splits are recorded for this session, so its pace distribution cannot be described.",
            "advice.complement.build_history": "Limit of this analysis: no earlier session of comparable distance is available as a reference point.",
            "advice.complement.use_hr": "Limit of this analysis: no heart-rate data accompanies these facts.",
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
            "signal.volume.below_recent": "Distance inférieure à la moyenne récente",
            "signal.volume.usual_recent": "Distance proche de la moyenne récente",
            "signal.volume.above_recent": "Distance supérieure à la moyenne récente",
            "signal.volume.short_volume": "Volume de séance court",
            "signal.volume.medium_volume": "Volume de séance modéré",
            "signal.volume.long_volume": "Volume de séance long",
            "signal.session_type.easy": "Séance facile",
            "signal.session_type.standard": "Séance standard",
            "signal.session_type.hard": "Séance intense",
            "signal.session_type.long": "Séance longue",
            "signal.session_type.short": "Séance courte",
            "meaning.with_hr_easy": "Les zones fiables indiquent une intensité basse.",
            "meaning.with_hr_moderate": "Les zones fiables indiquent une intensité modérée.",
            "meaning.with_hr_high": "Les zones fiables indiquent une intensité élevée.",
            "meaning.hr_without_intensity_with_pacing": "Des données d'allure et cardiaques sont enregistrées. L'intensité physiologique ne peut pas être déterminée de manière fiable.",
            "meaning.hr_without_intensity_no_pacing": "Des données cardiaques sont enregistrées. L'intensité physiologique ne peut pas être déterminée de manière fiable.",
            "meaning.no_hr_with_pacing": "Les données d'allure décrivent la séance, mais ne permettent pas d'établir son intensité physiologique.",
            "meaning.no_hr_no_pacing": "Les données disponibles ne permettent pas une interprétation significative de cette séance.",
            "meaning.pace_change": "Les fractions enregistrées montrent une variation marquée de l'allure pendant cette séance.",
            "meaning.negative_split": "Les fractions enregistrées montrent une seconde moitié plus rapide.",
            "meaning.consistent_pacing": "L'allure enregistrée est régulière.",
            "meaning.hr_drift": "Une dérive cardiaque est enregistrée, sans cause établie.",
            "meaning.intensity_unavailable": "L'intensité physiologique ne peut pas être déterminée de manière fiable.",
            "advice.unavailable": "Aucune observation coach exploitable n'est disponible avec ces données.",
            "limitations.intensity": "Les zones individualisées sont absentes ou non vérifiées ; l'intensité physiologique est indisponible.",
            "limitations.heart_rate": "Aucune donnée cardiaque n'est disponible.",
            "limitations.splits": "Aucune fraction kilométrique ni analyse des fractions n'est disponible ; la répartition de l'allure ne peut pas être décrite.",
            "limitations.baseline": "Aucune référence récente de même type n'est disponible.",
            "limitations.baseline_descriptive": "La référence récente est seulement descriptive ; les distances ou la nature des séances peuvent différer.",
            "limitations.comparability": "La comparabilité historique n'est pas établie ; les écarts ne démontrent pas une progression.",
            "limitations.no_comparable_reference": "Aucune séance antérieure de distance comparable n'est disponible.",
            "limitations.sample_too_small": "Trop peu de séances similaires sont disponibles pour une comparaison fiable.",
            "limitations.pace_sample_too_small": "Trop peu de séances similaires disposent de données d'allure exploitables.",
            "limitations.hr_sample_too_small": "Trop peu de séances similaires disposent de données cardiaques exploitables.",
            "limitations.session_nature_unknown": "La nature entraînement ou compétition n'est pas renseignée ; la comparabilité reste limitée.",
            "advice.high_intensity_observation": "Les zones placent cette séance dans la plage exigeante ; ce qui suit est déterminé par Training Today/Week, pas par cette analyse.",
            "advice.low_intensity_observation": "Les zones placent cette séance dans la plage aérobie contrôlée ; ce qui suit est déterminé par Training Today/Week, pas par cette analyse.",
            "advice.hr_without_intensity": "Limite de cette analyse : sans zones cardiaques individualisées, les valeurs de fréquence cardiaque enregistrées ne peuvent pas être lues comme une preuve d'intensité.",
            "advice.no_hr": "Limite de cette analyse : aucune donnée cardiaque n'a été enregistrée, donc aucune lecture physiologique de cette séance n'est possible.",
            "unavailable.hr": "Les données cardiaques sont indisponibles.",
            "unavailable.intensity": "La classification d'intensité est indisponible sans preuve physiologique individualisée.",
            "unavailable.pacing": "Les données d'allure sont indisponibles.",
            "unavailable.baseline": "Aucune séance antérieure du même type sur les {days} derniers jours.",
            "fact.distance_duration": "Tu as parcouru {distance} km en {duration}.",
            "fact.distance_duration_pace": "Tu as parcouru {distance} km en {duration} à {pace}.",
            "fact.distance_duration_speed": "Tu as parcouru {distance} km en {duration} à {speed} km/h.",
            "fact.duration_only": "{duration} d'activité enregistrée.",
            "fact.hr_avg": "Ta fréquence cardiaque moyenne était de {avg_hr} bpm.",
            "fact.hr_avg_max": "Ta fréquence cardiaque moyenne était de {avg_hr} bpm (max {max_hr} bpm).",
            "fact.hr_max_only": "Ta fréquence cardiaque maximale était de {max_hr} bpm.",
            "fact.splits_range": "Les fractions kilométriques vont de {fastest} à {slowest} ({count} fractions enregistrées).",
            "fact.pace_drop": "Perte d'allure enregistrée de {drop} sur la séance.",
            "fact.negative_split": "Les fractions enregistrées confirment un negative split.",
            "fact.consistency": "Score de régularité des fractions : {score}/100.",
            "fact.variability": "Variabilité d'allure enregistrée : {variability}.",
            "fact.hr_drift": "Dérive cardiaque mesurée à {drift} bpm entre le début et la fin ; cette mesure seule n'en établit pas la cause.",
            "fact.elevation": "Dénivelé positif : {elevation} m.",
            "fact.cadence": "Cadence moyenne : {cadence} ppm, rapportée telle qu'enregistrée et sans référence à une cadence universelle.",
            "fact.baseline_distance": "La distance est {delta} ({percent}) par rapport à la moyenne brute des {count} séances des {days} derniers jours ({baseline} km) ; cette moyenne peut inclure des séances de distances ou de nature différentes et ne constitue pas une comparaison de performance.",
            "fact.similar_pace": "Sur {count} séance(s) antérieure(s) de distance comparable disposant d'une allure exploitable (±{tolerance} % sur {days} jours, moyenne {avg_distance} km), l'allure moyenne était de {baseline} ; cette séance est {delta}.",
            "fact.similar_pace_coverage_small": "Cette moyenne d'allure repose sur {count} des {total} séance(s) antérieure(s) trouvée(s), soit moins que les {minimum} exigées par cette analyse avant de lire l'écart d'allure autrement que comme une différence brute.",
            "fact.similar_hr": "Sur {count} séance(s) antérieure(s) de distance comparable disposant d'une FC exploitable, la fréquence cardiaque moyenne était de {baseline} bpm ; cette séance est {delta} bpm.",
            "fact.similar_hr_coverage_small": "Cette moyenne de FC repose sur {count} des {total} séance(s) antérieure(s) trouvée(s), soit moins que les {minimum} exigées par cette analyse avant de lire l'écart de FC autrement que comme une différence brute.",
            "fact.similar_sample_small": "Seulement {count} séance(s) antérieure(s) de distance comparable trouvée(s), soit moins que les {minimum} exigées par cette analyse avant de lire une différence autrement que comme un écart brut.",
            "fact.similar_unavailable": "Aucune séance antérieure de distance comparable (±{tolerance} %) n'a été trouvée sur {days} jours ; la comparaison historique est donc indisponible.",
            "fact.similar_nature_unknown": "La nature entraînement ou compétition de ces séances n'est pas enregistrée ; leur comparabilité reste donc limitée et l'écart ci-dessus est un écart brut, pas une conclusion de performance.",
            "advice.even_pacing": "La variation d'allure observée est un point utile à comparer avec les prochaines séances de distance similaire.",
            "advice.negative_split_confirmed": "Un negative split est observé sur cette séance ; ce profil peut servir de point de comparaison avec des séances similaires.",
            "advice.maintain_consistency": "La régularité d'allure a été élevée sur cette séance, ce qui en fait un point de repère net pour comparer des séances de distance similaire.",
            "advice.monitor_hr_drift": "La dérive cardiaque mesurée est une donnée à comparer entre séances comparables ; cette analyse n'en établit pas la cause.",
            "advice.recover_after_long": "Cette séance est classée structurellement comme longue ; la récupération ou ce qui suit reste déterminé par Training Today/Week.",
            "advice.complement.record_splits": "Limite de cette analyse : aucune fraction kilométrique n'est enregistrée pour cette séance, sa répartition d'allure ne peut donc pas être décrite.",
            "advice.complement.build_history": "Limite de cette analyse : aucune séance antérieure de distance comparable n'est disponible comme point de repère.",
            "advice.complement.use_hr": "Limite de cette analyse : aucune donnée cardiaque n'accompagne ces faits.",
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
            "signal.volume.below_recent": "Distancia por debajo de la media reciente",
            "signal.volume.usual_recent": "Distancia cercana a la media reciente",
            "signal.volume.above_recent": "Distancia por encima de la media reciente",
            "signal.volume.short_volume": "Volumen de sesión corto",
            "signal.volume.medium_volume": "Volumen de sesión moderado",
            "signal.volume.long_volume": "Volumen de sesión largo",
            "signal.session_type.easy": "Sesión fácil",
            "signal.session_type.standard": "Sesión estándar",
            "signal.session_type.hard": "Sesión intensa",
            "signal.session_type.long": "Sesión larga",
            "signal.session_type.short": "Sesión corta",
            "meaning.with_hr_easy": "Las zonas fiables indican una intensidad baja.",
            "meaning.with_hr_moderate": "Las zonas fiables indican una intensidad moderada.",
            "meaning.with_hr_high": "Las zonas fiables indican una intensidad alta.",
            "meaning.hr_without_intensity_with_pacing": "Hay datos de ritmo y cardíacos registrados. La intensidad fisiológica no puede determinarse de forma fiable.",
            "meaning.hr_without_intensity_no_pacing": "Hay datos cardíacos registrados. La intensidad fisiológica no puede determinarse de forma fiable.",
            "meaning.no_hr_with_pacing": "Los datos de ritmo describen la sesión, pero no permiten establecer su intensidad fisiológica.",
            "meaning.no_hr_no_pacing": "Los datos disponibles no permiten una interpretación significativa de esta sesión.",
            "meaning.pace_change": "Los parciales registrados muestran un cambio marcado de ritmo durante esta sesión.",
            "meaning.negative_split": "Los parciales registrados muestran una segunda mitad más rápida.",
            "meaning.consistent_pacing": "El ritmo registrado es regular.",
            "meaning.hr_drift": "Se registra una deriva cardíaca, sin una causa establecida.",
            "meaning.intensity_unavailable": "La intensidad fisiológica no puede determinarse de forma fiable.",
            "advice.unavailable": "No hay una observación útil de coaching disponible con estos datos.",
            "limitations.intensity": "Las zonas individualizadas faltan o no están verificadas; la intensidad fisiológica no está disponible.",
            "limitations.heart_rate": "No hay datos cardíacos disponibles.",
            "limitations.splits": "No hay parciales kilométricos ni análisis de parciales disponibles; no puede describirse la distribución del ritmo.",
            "limitations.baseline": "No hay una referencia reciente del mismo tipo disponible.",
            "limitations.baseline_descriptive": "La referencia reciente es solo descriptiva; las distancias o la naturaleza de las sesiones pueden diferir.",
            "limitations.comparability": "La comparabilidad histórica no está establecida; las diferencias no demuestran progreso.",
            "limitations.no_comparable_reference": "No hay una sesión anterior de distancia comparable disponible.",
            "limitations.sample_too_small": "Hay muy pocas sesiones similares para una comparación fiable.",
            "limitations.pace_sample_too_small": "Muy pocas sesiones similares tienen datos de ritmo utilizables.",
            "limitations.hr_sample_too_small": "Muy pocas sesiones similares tienen datos cardíacos utilizables.",
            "limitations.session_nature_unknown": "No se registra si se trata de entrenamiento o competición; la comparabilidad sigue siendo limitada.",
            "advice.high_intensity_observation": "Las zonas sitúan esta sesión en el rango exigente; lo que venga después lo determina Training Today/Week, no este análisis.",
            "advice.low_intensity_observation": "Las zonas sitúan esta sesión en el rango aeróbico controlado; lo que venga después lo determina Training Today/Week, no este análisis.",
            "advice.hr_without_intensity": "Límite de este análisis: sin zonas de frecuencia cardíaca individualizadas, los valores registrados no pueden leerse como evidencia de intensidad.",
            "advice.no_hr": "Límite de este análisis: no se registró ningún dato de frecuencia cardíaca, así que no es posible ninguna lectura fisiológica de esta sesión.",
            "unavailable.hr": "No hay datos de frecuencia cardíaca disponibles.",
            "unavailable.intensity": "La clasificación de intensidad no está disponible sin evidencia fisiológica individualizada.",
            "unavailable.pacing": "No hay datos de ritmo disponibles.",
            "unavailable.baseline": "No hay sesiones previas del mismo tipo en los últimos {days} días.",
            "fact.distance_duration": "Recorriste {distance} km en {duration}.",
            "fact.distance_duration_pace": "Recorriste {distance} km en {duration} a {pace}.",
            "fact.distance_duration_speed": "Recorriste {distance} km en {duration} a {speed} km/h.",
            "fact.duration_only": "{duration} de actividad registrada.",
            "fact.hr_avg": "Tu frecuencia cardíaca media fue de {avg_hr} bpm.",
            "fact.hr_avg_max": "Tu frecuencia cardíaca media fue de {avg_hr} bpm (máxima {max_hr} bpm).",
            "fact.hr_max_only": "Tu frecuencia cardíaca máxima fue de {max_hr} bpm.",
            "fact.splits_range": "Los parciales por kilómetro van de {fastest} a {slowest} ({count} parciales registrados).",
            "fact.pace_drop": "Pérdida de ritmo registrada de {drop} en la sesión.",
            "fact.negative_split": "Los parciales registrados confirman un negative split.",
            "fact.consistency": "Puntuación de regularidad de los parciales: {score}/100.",
            "fact.variability": "Variabilidad de ritmo registrada: {variability}.",
            "fact.hr_drift": "Deriva cardíaca medida en {drift} bpm entre el inicio y el final; esta medición por sí sola no establece su causa.",
            "fact.elevation": "Desnivel positivo: {elevation} m.",
            "fact.cadence": "Cadencia media: {cadence} ppm, indicada tal como se registró y sin referencia a una cadencia universal.",
            "fact.baseline_distance": "La distancia es {delta} ({percent}) frente a la media bruta de las {count} sesiones de los últimos {days} días ({baseline} km); esa media puede incluir sesiones de distancias o naturalezas diferentes y no constituye una comparación de rendimiento.",
            "fact.similar_pace": "En {count} sesión(es) anterior(es) de distancia comparable con un ritmo utilizable (±{tolerance} % en {days} días, media {avg_distance} km), el ritmo medio fue {baseline}; esta sesión es {delta}.",
            "fact.similar_pace_coverage_small": "Esa media de ritmo se apoya en {count} de las {total} sesión(es) anterior(es) encontradas, por debajo de las {minimum} que exige este análisis antes de leer la diferencia de ritmo como algo más que una brecha bruta.",
            "fact.similar_hr": "En {count} sesión(es) anterior(es) de distancia comparable con una frecuencia cardíaca utilizable, la frecuencia cardíaca media fue {baseline} bpm; esta sesión es {delta} bpm.",
            "fact.similar_hr_coverage_small": "Esa media de frecuencia cardíaca se apoya en {count} de las {total} sesión(es) anterior(es) encontradas, por debajo de las {minimum} que exige este análisis antes de leer la diferencia de frecuencia cardíaca como algo más que una brecha bruta.",
            "fact.similar_sample_small": "Solo se encontraron {count} sesión(es) anterior(es) de distancia comparable, por debajo de las {minimum} que exige este análisis antes de leer una diferencia como algo más que una brecha bruta.",
            "fact.similar_unavailable": "No se encontró ninguna sesión anterior de distancia comparable (±{tolerance} %) en {days} días, así que no hay comparación histórica disponible.",
            "fact.similar_nature_unknown": "La naturaleza de entrenamiento o competición de estas sesiones no está registrada; su comparabilidad sigue siendo limitada y la diferencia anterior es una brecha bruta, no una conclusión de rendimiento.",
            "advice.even_pacing": "El cambio de ritmo observado es un dato útil para comparar con las próximas sesiones de distancia similar.",
            "advice.negative_split_confirmed": "Se observa un negative split en esta sesión; este perfil puede servir como punto de comparación con sesiones similares.",
            "advice.maintain_consistency": "La regularidad de ritmo fue alta en esta sesión, lo que la convierte en un punto de referencia claro para comparar sesiones de distancia similar.",
            "advice.monitor_hr_drift": "La deriva cardíaca medida es un dato para comparar entre sesiones comparables; este análisis no establece su causa.",
            "advice.recover_after_long": "Esta sesión se clasifica estructuralmente como larga; la recuperación o lo que venga después sigue determinada por Training Today/Week.",
            "advice.complement.record_splits": "Límite de este análisis: no hay parciales por kilómetro registrados para esta sesión, así que no se puede describir su distribución de ritmo.",
            "advice.complement.build_history": "Límite de este análisis: no hay ninguna sesión anterior de distancia comparable disponible como punto de referencia.",
            "advice.complement.use_hr": "Límite de este análisis: ningún dato de frecuencia cardíaca acompaña a estos hechos.",
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


def _valid_positive_number(value) -> bool:
    """A metric is usable only when it is a finite, strictly positive real number.

    This deliberately rejects None, bool, NaN, +/-inf, zero and negatives, and
    deliberately applies no physiological calibration (no HR floor/ceiling, no
    pace bounds): this analysis eliminates impossible values, it does not invent
    thresholds.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return False
    return math.isfinite(float(value)) and float(value) > 0


def _usable_metric(workout: dict, key: str) -> Optional[float]:
    value = workout.get(key)
    return float(value) if _valid_positive_number(value) else None


def _fmt_number(value: float, digits: int = 2) -> str:
    text = f"{float(value):.{digits}f}"
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return text or "0"


def _fmt_distance(distance_km: Optional[float]) -> Optional[str]:
    if distance_km is None:
        return None
    return _fmt_number(distance_km, 2)


def _fmt_duration(duration_minutes: Optional[float]) -> Optional[str]:
    if duration_minutes is None:
        return None
    total_minutes = int(round(float(duration_minutes)))
    if total_minutes >= 60:
        return f"{total_minutes // 60}h{total_minutes % 60:02d}"
    return f"{total_minutes} min"


def _fmt_pace(pace_min_km: Optional[float]) -> Optional[str]:
    if pace_min_km is None or pace_min_km <= 0:
        return None
    total_seconds = int(round(float(pace_min_km) * 60))
    return f"{total_seconds // 60}:{total_seconds % 60:02d}/km"


def _fmt_pace_delta(delta_min_km: Optional[float]) -> Optional[str]:
    if delta_min_km is None:
        return None
    total_seconds = int(round(abs(float(delta_min_km)) * 60))
    sign = "+" if delta_min_km > 0 else ("-" if delta_min_km < 0 else "+")
    return f"{sign}{total_seconds // 60}:{total_seconds % 60:02d}/km"


def _fmt_signed(value: Optional[float], digits: int = 2) -> Optional[str]:
    if value is None:
        return None
    return f"{'+' if value >= 0 else '-'}{_fmt_number(abs(value), digits)}"


def _fmt_signed_percent(value: Optional[float]) -> Optional[str]:
    if value is None:
        return None
    return f"{'+' if value >= 0 else '-'}{_fmt_number(abs(value), 1)}%"


def _join_sentences(sentences: List[Optional[str]]) -> str:
    return " ".join(sentence for sentence in sentences if sentence)


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


def _build_baseline(workouts: List[dict], current_workout: dict, days: int = BASELINE_PERIOD_DAYS) -> dict:
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


def _competition_flag(workout: dict) -> Optional[bool]:
    """Return True/False only when real metadata states it, None otherwise.

    Nothing is ever inferred from the session name or from its distance.
    """
    for key in _RACE_METADATA_KEYS:
        value = workout.get(key)
        if value is None:
            continue
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in _RACE_METADATA_VALUES:
                return True
            if normalized in _TRAINING_METADATA_VALUES:
                return False
    return None


def retrieve_similar_workouts(
    current_workout: dict,
    candidate_workouts: List[dict],
    *,
    window_days: int = SIMILAR_HISTORY_WINDOW_DAYS,
    tolerance_pct: float = SIMILAR_DISTANCE_TOLERANCE_PCT,
    limit: int = SIMILAR_MAX_RESULTS,
) -> List[dict]:
    """Bounded historical retrieval restored from the legacy RAG capability.

    Same user scope is guaranteed by the caller's query. Only the same sport,
    strictly earlier sessions and comparable distances are retained.
    """
    current_distance = current_workout.get("distance_km")
    if not _valid_positive_number(current_distance):
        return []

    try:
        current_date = _parse_workout_date(current_workout.get("date", ""))
    except ValueError:
        return []

    current_type = (current_workout.get("type") or "").lower()
    cutoff = current_date - timedelta(days=window_days)
    tolerance = float(current_distance) * (tolerance_pct / 100.0)
    current_competition = _competition_flag(current_workout)

    matches: List[dict] = []
    for candidate in candidate_workouts:
        if candidate.get("id") == current_workout.get("id"):
            continue
        if (candidate.get("type") or "").lower() != current_type:
            continue
        candidate_distance = candidate.get("distance_km")
        if not _valid_positive_number(candidate_distance):
            continue
        try:
            candidate_date = _parse_workout_date(candidate.get("date", ""))
        except ValueError:
            continue
        if not (cutoff <= candidate_date < current_date):
            continue
        if abs(float(candidate_distance) - float(current_distance)) > tolerance:
            continue
        candidate_competition = _competition_flag(candidate)
        if (
            current_competition is not None
            and candidate_competition is not None
            and candidate_competition != current_competition
        ):
            continue
        matches.append(candidate)

    matches.sort(key=lambda item: (item.get("date", ""), item.get("id", "")), reverse=True)
    return matches[:limit]


def _build_similar_reference(
    workout: dict,
    candidate_workouts: List[dict],
    language: str,
) -> WorkoutAnalysisSimilarReference:
    matches = retrieve_similar_workouts(workout, candidate_workouts)
    if not matches:
        return WorkoutAnalysisSimilarReference(
            available=False,
            comparable=False,
            sample_count=0,
            limitations=["no_comparable_reference"],
            reason_unavailable=_template(
                language,
                "fact.similar_unavailable",
                tolerance=_fmt_number(SIMILAR_DISTANCE_TOLERANCE_PCT, 0),
                days=SIMILAR_HISTORY_WINDOW_DAYS,
            ),
        )

    # Each metric gets its own population of matches. Every number quoted about a
    # metric — its average, its sample count and, for pace, the average distance of
    # the sessions it rests on — comes from that same subset, so a sentence can never
    # mix two different populations.
    pace_matches = [match for match in matches if _valid_positive_number(match.get("avg_pace_min_km"))]
    hr_matches = [match for match in matches if _valid_positive_number(match.get("avg_heart_rate"))]
    distance_matches = [match for match in matches if _valid_positive_number(match.get("distance_km"))]

    pace_values = [float(match["avg_pace_min_km"]) for match in pace_matches]
    hr_values = [float(match["avg_heart_rate"]) for match in hr_matches]
    distance_values = [float(match["distance_km"]) for match in distance_matches]

    avg_pace = _safe_avg(pace_values)
    avg_hr = _safe_avg(hr_values)
    avg_distance = _safe_avg(distance_values)
    # Distance average of the pace population only — never reused for anything else.
    pace_avg_distance = _safe_avg(
        [float(match["distance_km"]) for match in pace_matches if _valid_positive_number(match.get("distance_km"))]
    )

    current_pace = _usable_metric(workout, "avg_pace_min_km")
    current_hr = _usable_metric(workout, "avg_heart_rate")
    pace_difference = (
        _safe_round(current_pace - avg_pace, 3)
        if current_pace is not None and avg_pace is not None
        else None
    )
    hr_difference = (
        _safe_round(current_hr - avg_hr, 1)
        if current_hr is not None and avg_hr is not None
        else None
    )

    limitations: List[str] = []
    if len(matches) < SIMILAR_MIN_COMPARABLE_SAMPLE:
        limitations.append("sample_too_small")
    if len(pace_values) < SIMILAR_MIN_COMPARABLE_SAMPLE:
        limitations.append("pace_sample_too_small")
    if len(hr_values) < SIMILAR_MIN_COMPARABLE_SAMPLE:
        limitations.append("hr_sample_too_small")
    if _competition_flag(workout) is None or any(_competition_flag(match) is None for match in matches):
        limitations.append("session_nature_unknown")
    # P2: comparable stays False as soon as any limitation is recorded. An unknown
    # training/race nature is not enough to assert strong comparability; the factual
    # distance/pace gap is still exposed alongside the explicit limitation.
    comparable = not limitations

    return WorkoutAnalysisSimilarReference(
        available=True,
        comparable=comparable,
        sample_count=len(matches),
        workout_ids=[str(match.get("id", "")) for match in matches],
        avg_distance_km=avg_distance,
        avg_pace_min_km=avg_pace,
        avg_heart_rate=avg_hr,
        distance_sample_count=len(distance_values),
        pace_sample_count=len(pace_values),
        pace_avg_distance_km=pace_avg_distance,
        hr_sample_count=len(hr_values),
        pace_difference_min_km=pace_difference,
        heart_rate_difference_bpm=hr_difference,
        limitations=limitations,
        reason_unavailable=None,
    )


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
    hr_analysis = workout.get("hr_analysis") or {}
    avg_hr = workout.get("avg_heart_rate")
    max_hr = workout.get("max_heart_rate")
    zone_distribution = _normalize_zone_distribution(workout.get("effort_zone_distribution"))
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


def _structural_size_code(workout: dict) -> str:
    duration = workout.get("duration_minutes") or 0
    distance = workout.get("distance_km") or 0
    workout_type = (workout.get("type") or "").lower()

    if workout_type == "run":
        if duration >= 90 or distance >= 15:
            return "long"
        if duration <= 25 or distance <= 4:
            return "short"
        return "standard"

    if duration >= 90:
        return "long"
    if duration <= 25:
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
    baseline = _build_baseline(workouts, workout, days=BASELINE_PERIOD_DAYS)
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
    comparison.similar = _build_similar_reference(workout, workouts, language)
    return comparison


def _structural_observations(workout: dict, physiology: WorkoutAnalysisPhysiology, pacing: WorkoutAnalysisPacing, language: str) -> List[str]:
    """Factual, session-specific observations that do not depend on intensity classification."""
    sentences: List[str] = []

    distance = _fmt_distance(workout.get("distance_km"))
    duration = _fmt_duration(workout.get("duration_minutes"))
    pace = _fmt_pace(pacing.average_pace_min_km)
    speed = pacing.average_speed_kmh

    if distance and duration and pace:
        sentences.append(_template(language, "fact.distance_duration_pace", distance=distance, duration=duration, pace=pace))
    elif distance and duration and speed is not None:
        sentences.append(
            _template(language, "fact.distance_duration_speed", distance=distance, duration=duration, speed=_fmt_number(speed, 1))
        )
    elif distance and duration:
        sentences.append(_template(language, "fact.distance_duration", distance=distance, duration=duration))
    elif duration:
        sentences.append(_template(language, "fact.duration_only", duration=duration))

    if physiology.avg_hr is not None and physiology.max_hr is not None:
        sentences.append(_template(language, "fact.hr_avg_max", avg_hr=physiology.avg_hr, max_hr=physiology.max_hr))
    elif physiology.avg_hr is not None:
        sentences.append(_template(language, "fact.hr_avg", avg_hr=physiology.avg_hr))
    elif physiology.max_hr is not None:
        sentences.append(_template(language, "fact.hr_max_only", max_hr=physiology.max_hr))

    return sentences


def _pacing_observations(workout: dict, pacing: WorkoutAnalysisPacing, language: str) -> List[str]:
    sentences: List[str] = []
    fastest = _fmt_pace(pacing.fastest_split_min_km)
    slowest = _fmt_pace(pacing.slowest_split_min_km)
    split_count = len(workout.get("km_splits") or [])
    if fastest and slowest and split_count:
        sentences.append(_template(language, "fact.splits_range", fastest=fastest, slowest=slowest, count=split_count))

    if pacing.negative_split is True:
        sentences.append(_template(language, "fact.negative_split"))

    if pacing.pace_drop_min_km is not None:
        drop = _fmt_pace(abs(pacing.pace_drop_min_km))
        if drop:
            sentences.append(_template(language, "fact.pace_drop", drop=drop))

    if pacing.consistency_score is not None:
        sentences.append(_template(language, "fact.consistency", score=_fmt_number(pacing.consistency_score, 1)))
    elif pacing.variability is not None:
        sentences.append(_template(language, "fact.variability", variability=_fmt_number(pacing.variability, 3)))

    return sentences


def _physiology_observations(physiology: WorkoutAnalysisPhysiology, language: str) -> List[str]:
    if physiology.hr_drift is None:
        return []
    return [_template(language, "fact.hr_drift", drift=_fmt_number(physiology.hr_drift, 1))]


def _terrain_observations(workout: dict, language: str) -> List[str]:
    sentences: List[str] = []
    elevation = workout.get("elevation_gain_m")
    if elevation is not None:
        sentences.append(_template(language, "fact.elevation", elevation=_fmt_number(elevation, 0)))
    cadence = workout.get("avg_cadence_spm")
    if cadence is not None:
        sentences.append(_template(language, "fact.cadence", cadence=_fmt_number(cadence, 0)))
    return sentences


def _comparison_observations(comparison: WorkoutAnalysisComparison, language: str) -> List[str]:
    sentences: List[str] = []
    count = comparison.baseline_sample_count
    if comparison.available and count > 0:
        distance = comparison.distance_km
        if distance and distance.difference is not None and distance.percent_change is not None:
            sentences.append(
                _template(
                    language,
                    "fact.baseline_distance",
                    delta=f"{_fmt_signed(distance.difference, 2)} km",
                    percent=_fmt_signed_percent(distance.percent_change),
                    count=count,
                    days=comparison.baseline_period_days,
                    baseline=_fmt_number(distance.baseline or 0, 2),
                )
            )
        # P1-2: the generic 14-day baseline mixes sessions of different distances and
        # natures. Its pace and heart-rate deltas stay in the serialized contract for
        # compatibility but are deliberately NOT verbalized here: only comparison.similar
        # backs an interpreted pace/heart-rate comparison.

    similar = comparison.similar
    if similar is None:
        return sentences

    if not similar.available:
        if similar.reason_unavailable:
            sentences.append(similar.reason_unavailable)
        return sentences

    if similar.avg_pace_min_km is not None and similar.pace_difference_min_km is not None:
        # Every number in this sentence — count, pace average and average distance —
        # comes from the pace subset only. similar.avg_distance_km covers all matches
        # and is deliberately NOT used here.
        sentences.append(
            _template(
                language,
                "fact.similar_pace",
                count=similar.pace_sample_count,
                tolerance=_fmt_number(similar.distance_tolerance_pct, 0),
                days=similar.period_days,
                avg_distance=_fmt_number(similar.pace_avg_distance_km or 0, 2),
                baseline=_fmt_pace(similar.avg_pace_min_km),
                delta=_fmt_pace_delta(similar.pace_difference_min_km),
            )
        )
        if "pace_sample_too_small" in similar.limitations:
            sentences.append(
                _template(
                    language,
                    "fact.similar_pace_coverage_small",
                    count=similar.pace_sample_count,
                    total=similar.sample_count,
                    minimum=similar.min_comparable_sample,
                )
            )
    if similar.avg_heart_rate is not None and similar.heart_rate_difference_bpm is not None:
        # The heart-rate average rests on hr_sample_count sessions, never on the total.
        sentences.append(
            _template(
                language,
                "fact.similar_hr",
                count=similar.hr_sample_count,
                baseline=_fmt_number(similar.avg_heart_rate, 1),
                delta=_fmt_signed(similar.heart_rate_difference_bpm, 1),
            )
        )
        if "hr_sample_too_small" in similar.limitations:
            sentences.append(
                _template(
                    language,
                    "fact.similar_hr_coverage_small",
                    count=similar.hr_sample_count,
                    total=similar.sample_count,
                    minimum=similar.min_comparable_sample,
                )
            )
    if "sample_too_small" in similar.limitations:
        sentences.append(
            _template(
                language,
                "fact.similar_sample_small",
                count=similar.sample_count,
                minimum=similar.min_comparable_sample,
            )
        )
    if "session_nature_unknown" in similar.limitations:
        sentences.append(_template(language, "fact.similar_nature_unknown"))

    return sentences


def _build_summary(
    workout: dict,
    physiology: WorkoutAnalysisPhysiology,
    pacing: WorkoutAnalysisPacing,
    signals: WorkoutAnalysisSignals,
    language: str,
) -> AnalysisText:
    if signals.intensity.available and signals.intensity.code:
        key = {
            "very_high": "summary.high_with_hr",
            "high": "summary.high_with_hr",
            "moderate": "summary.moderate_with_hr",
            "low": "summary.easy_with_hr",
        }[signals.intensity.code]
    else:
        key = {
            "long": "summary.long_structural",
            "short": "summary.short_structural",
        }.get(signals.session_type.code, "summary.standard_structural")

    observations = _structural_observations(workout, physiology, pacing, language)
    if signals.intensity.available:
        sentences = [_template(language, key)] + observations
    else:
        sentences = observations or [_template(language, key)]
    text = _join_sentences(sentences)
    return AnalysisText(code=key, text=text)


def _build_meaning(
    workout: dict,
    physiology: WorkoutAnalysisPhysiology,
    pacing: WorkoutAnalysisPacing,
    comparison: WorkoutAnalysisComparison,
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
    elif physiology.available:
        code = "meaning.hr_without_intensity_with_pacing" if pacing.available else "meaning.hr_without_intensity_no_pacing"
    else:
        code = "meaning.no_hr_with_pacing" if pacing.available else "meaning.no_hr_no_pacing"

    if not signals.intensity.available:
        observed_code = {
            "advice.even_pacing": "meaning.pace_change",
            "advice.negative_split_confirmed": "meaning.negative_split",
            "advice.maintain_consistency": "meaning.consistent_pacing",
            "advice.monitor_hr_drift": "meaning.hr_drift",
        }.get(_advice_primary_code(physiology, pacing, signals))
        if observed_code:
            return AnalysisText(
                code=observed_code,
                text=_join_sentences([
                    _template(language, observed_code),
                    _template(language, "meaning.intensity_unavailable"),
                ]),
            )
    return AnalysisText(code=code, text=_template(language, code))


def _advice_primary_code(
    physiology: WorkoutAnalysisPhysiology,
    pacing: WorkoutAnalysisPacing,
    signals: WorkoutAnalysisSignals,
) -> str:
    if signals.intensity.available and signals.intensity.code in {"high", "very_high"}:
        return "advice.high_intensity_observation"
    if signals.intensity.available and signals.intensity.code == "low":
        return "advice.low_intensity_observation"
    if pacing.pace_drop_min_km is not None and abs(pacing.pace_drop_min_km) >= 0.4:
        return "advice.even_pacing"
    if pacing.negative_split is True:
        return "advice.negative_split_confirmed"
    if pacing.consistency_score is not None and pacing.consistency_score >= 90:
        return "advice.maintain_consistency"
    if physiology.hr_drift is not None and abs(physiology.hr_drift) >= 8:
        return "advice.monitor_hr_drift"
    if signals.session_type.code == "long":
        return "advice.recover_after_long"
    if physiology.available:
        return "advice.hr_without_intensity"
    return "advice.no_hr"


def _build_advice(
    workout: dict,
    physiology: WorkoutAnalysisPhysiology,
    pacing: WorkoutAnalysisPacing,
    comparison: WorkoutAnalysisComparison,
    signals: WorkoutAnalysisSignals,
    language: str,
) -> WorkoutAnalysisAdvice:
    code = _advice_primary_code(physiology, pacing, signals)
    available = code not in {"advice.hr_without_intensity", "advice.no_hr"}
    return WorkoutAnalysisAdvice(
        code=code,
        text=_template(language, code if available else "advice.unavailable"),
        available=available,
    )


def _build_limitations(
    workout: dict,
    signals: WorkoutAnalysisSignals,
    comparison: WorkoutAnalysisComparison,
    evidence: WorkoutAnalysisEvidence,
    language: str,
) -> List[AnalysisText]:
    codes: List[str] = []
    if not signals.intensity.available:
        codes.append("intensity")
    if not evidence.has_heart_rate:
        codes.append("heart_rate")
    if not evidence.has_splits:
        codes.append("splits")
    codes.append("baseline_descriptive" if comparison.available else "baseline")
    similar = comparison.similar
    if similar is not None:
        if not similar.comparable:
            codes.append("comparability")
        codes.extend(similar.limitations)
    if _competition_flag(workout) is None:
        codes.append("session_nature_unknown")
    return [
        AnalysisText(code=f"limitations.{code}", text=_template(language, f"limitations.{code}"))
        for code in dict.fromkeys(codes)
    ]


def build_workout_analysis_v2(workout: dict, historical_workouts: List[dict], language: str = "en") -> WorkoutAnalysisV2Response:
    comparison = _localized_comparison(workout, historical_workouts, language)
    physiology = _build_physiology(workout, language)
    pacing = _build_pacing(workout, language)
    signals = _build_signals(workout, comparison, physiology, language)
    summary = _build_summary(workout, physiology, pacing, signals, language)
    meaning = _build_meaning(workout, physiology, pacing, comparison, signals, language)
    advice = _build_advice(workout, physiology, pacing, comparison, signals, language)
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
        limitations=_build_limitations(workout, signals, comparison, evidence, language),
    )
