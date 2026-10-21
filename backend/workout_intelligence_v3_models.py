"""C352 — Workout Intelligence V3: explicit input and output contracts.

Pure Pydantic models, no I/O. The engine lives in ``workout_intelligence_v3``
and the read-only loader in ``workout_intelligence_v3_service``.
"""

from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

from training_v2.prescription_snapshot import PrescriptionSnapshot

Confidence = Literal["high", "medium", "low", "none"]
ThresholdSource = Literal[
    "lab_test", "field_test", "device_estimate", "user_declared", "generic_formula", "unknown",
]
StructureStatus = Literal["continuous_recorded", "intervals", "other", "unknown"]


# ── Inputs ───────────────────────────────────────────────────────────────────


class WIV3CurrentSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    date: str
    sport: str
    activity_type: Optional[str] = None
    """Precise Garmin type key (e.g. ``treadmill_running``); never inferred from a name."""
    distance_km: Optional[float] = None
    duration_minutes: Optional[float] = None
    avg_pace_min_km: Optional[float] = None
    avg_hr: Optional[float] = None
    max_hr: Optional[float] = None
    elevation_gain_m: Optional[float] = None
    competition: Optional[bool] = None
    has_splits: bool = False
    structure: StructureStatus = "unknown"
    """V2 ``signals.session_structure`` code (``continuous`` → ``continuous_recorded``)."""
    effort_count: int = 0
    recovery_count: int = 0
    effort_regularity_available: bool = False
    effort_avg_hr: Optional[float] = None
    has_warmup_or_cooldown: bool = False


class WIV3ThresholdEstimate(BaseModel):
    model_config = ConfigDict(frozen=True)

    value_bpm: Optional[float] = None
    source: ThresholdSource = "unknown"
    estimated_on: Optional[str] = None
    confidence: Literal["high", "medium", "low", "unknown"] = "unknown"


class WIV3FcMax(BaseModel):
    """Declared physiological FCmax only (never derived from age or observations)."""

    model_config = ConfigDict(frozen=True)

    value_bpm: Optional[float] = None
    source: Literal["user_declared", "unavailable"] = "unavailable"
    declared_on: Optional[str] = None
    provenance: Optional[str] = None
    """Path of the canonical field the value was read from."""


class WIV3ObservedMaxHr(BaseModel):
    """Highest credible HR observed in strictly-prior activities.

    A recorded maximum is a lower bound of the physiological FCmax: it is
    never presented or used as a certain FCmax.
    """

    model_config = ConfigDict(frozen=True)

    value_bpm: Optional[float] = None
    source: Literal["garmin_activities_strictly_prior", "unavailable"] = "unavailable"
    kind: Literal["observed_maximum_lower_bound"] = "observed_maximum_lower_bound"
    observation_count: int = 0


SourceKind = Literal[
    "personal_declared", "personal_measured", "personal_device_estimate", "observed",
    "generic", "pace_based_not_hr", "unverified", "unavailable",
]


class WIV3PhysiologicalSource(BaseModel):
    """Audit row: what a physiological source really provides to V3."""

    model_config = ConfigDict(frozen=True)

    data: Literal[
        "fcmax_declared", "observed_max_hr", "lt1", "lt2",
        "training_v2_zones", "workout_hr_zone_distribution",
    ]
    source: str
    unit: str
    available: bool
    """Value actually supplied to V3 (not a claim of Mongo persistence)."""
    usable_by_v3: bool
    kind: SourceKind
    valid_from: Optional[str] = None
    reason: str


class WIV3PhysiologicalProfile(BaseModel):
    model_config = ConfigDict(frozen=True)

    fcmax: WIV3FcMax = Field(default_factory=WIV3FcMax)
    observed_max_hr: Optional[WIV3ObservedMaxHr] = None
    """``None`` → computed by the extraction from strictly-prior history."""
    lt1: Optional[WIV3ThresholdEstimate] = None
    lt2: Optional[WIV3ThresholdEstimate] = None
    lt_source_status: Literal["provided", "not_persisted"] = "not_persisted"
    """``not_persisted``: RunIndex stores no personal LT1/LT2 today (documented blocker)."""
    sources: List[WIV3PhysiologicalSource] = Field(default_factory=list)


class WIV3HistoricalSession(BaseModel):
    model_config = ConfigDict(frozen=True)

    id: str
    date: str
    sport: str
    activity_type: Optional[str] = None
    distance_km: Optional[float] = None
    duration_minutes: Optional[float] = None
    avg_pace_min_km: Optional[float] = None
    avg_hr: Optional[float] = None
    max_hr: Optional[float] = None
    competition: Optional[bool] = None
    structure: StructureStatus = "unknown"


class WIV3PrescriptionContext(BaseModel):
    model_config = ConfigDict(frozen=True)

    local_date: Optional[str] = None
    """Garmin-local calendar date of the session; ``None`` when not provable."""
    snapshots: List[PrescriptionSnapshot] = Field(default_factory=list)
    same_day_session_count: int = 1


class WIV3V2Reference(BaseModel):
    """Read-only echo of Workout Analysis V2 ``comparison.similar``."""

    model_config = ConfigDict(frozen=True)

    available: bool = False
    sample_count: int = 0
    workout_ids: List[str] = Field(default_factory=list)
    pace_comparability: Optional[str] = None
    hr_comparability: Optional[str] = None
    limitations: List[str] = Field(default_factory=list)
    source_path: str = "comparison.similar"


class WorkoutIntelligenceV3Input(BaseModel):
    model_config = ConfigDict(frozen=True)

    session: WIV3CurrentSession
    profile: WIV3PhysiologicalProfile = Field(default_factory=WIV3PhysiologicalProfile)
    history: List[WIV3HistoricalSession] = Field(default_factory=list)
    v2_reference: WIV3V2Reference = Field(default_factory=WIV3V2Reference)
    prescription: WIV3PrescriptionContext = Field(default_factory=WIV3PrescriptionContext)


# ── Outputs ──────────────────────────────────────────────────────────────────


class WIV3ThresholdUsed(BaseModel):
    value_bpm: float
    source: str
    estimated_on: str
    confidence: str


class WIV3IntensityAssessment(BaseModel):
    position: Literal["below_LT1", "between_LT1_LT2", "above_LT2", "unknown"] = "unknown"
    hr_used_bpm: Optional[float] = None
    hr_metric: Literal["session_average_hr"] = "session_average_hr"
    session_max_hr_bpm: Optional[float] = None
    lt1: Optional[WIV3ThresholdUsed] = None
    lt2: Optional[WIV3ThresholdUsed] = None
    fcmax_bpm: Optional[float] = None
    """Declared FCmax only; an observed maximum is reported separately."""
    fcmax_source: Literal["user_declared", "unavailable"] = "unavailable"
    observed_max_hr_bpm: Optional[float] = None
    observed_max_hr_observation_count: int = 0
    physiological_sources: List[WIV3PhysiologicalSource] = Field(default_factory=list)
    rejected_thresholds: Dict[str, str] = Field(default_factory=dict)
    confidence: Confidence = "none"
    limitations: List[str] = Field(default_factory=list)
    source_paths: List[str] = Field(default_factory=list)


class WIV3RelativeEffortReference(BaseModel):
    """Level C evidence: the session's average HR within the athlete's own
    distribution of comparable earlier sessions.

    A RELATIVE position only: it never establishes a physiological zone and
    never stands in for LT1/LT2.
    """

    status: Literal[
        "not_evaluated", "used", "insufficient_references", "no_separation",
        "out_of_reference_range", "incoherent_hr_pace", "not_applicable",
    ] = "not_evaluated"
    relative_position: Optional[Literal["low", "intermediate", "high"]] = None
    current_hr_bpm: Optional[float] = None
    current_pace_min_km: Optional[float] = None
    reference_count: int = 0
    workout_ids: List[str] = Field(default_factory=list)
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    hr_min_bpm: Optional[float] = None
    hr_q1_bpm: Optional[float] = None
    hr_median_bpm: Optional[float] = None
    hr_q3_bpm: Optional[float] = None
    hr_max_bpm: Optional[float] = None
    hr_iqr_bpm: Optional[float] = None
    pace_q1_min_km: Optional[float] = None
    pace_q3_min_km: Optional[float] = None
    exclusions: Dict[str, int] = Field(default_factory=dict)
    criteria: Dict[str, float] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)


class WIV3SessionClassification(BaseModel):
    type: Literal[
        "easy_run_probable", "steady_run_probable", "tempo_probable",
        "intervals", "long_run_probable", "unknown",
    ] = "unknown"
    decision_tier: Literal[
        "garmin_phases", "personal_thresholds", "individual_history", "insufficient_data",
    ] = "insufficient_data"
    """Highest evidence level of the hierarchy that decided the type."""
    confidence: Confidence = "none"
    evidence: Dict[str, float] = Field(default_factory=dict)
    rules: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    source_paths: List[str] = Field(default_factory=list)
    relative_effort: WIV3RelativeEffortReference = Field(default_factory=WIV3RelativeEffortReference)


class WIV3PaceAtComparableHr(BaseModel):
    reference_count: int = 0
    workout_ids: List[str] = Field(default_factory=list)
    hr_tolerance_bpm: float
    reference_pace_min_km: Optional[float] = None
    reference_hr_bpm: Optional[float] = None
    current_pace_min_km: Optional[float] = None
    pace_difference_sec_per_km: Optional[float] = None


class WIV3HrAtComparablePace(BaseModel):
    reference_count: int = 0
    workout_ids: List[str] = Field(default_factory=list)
    pace_tolerance_sec_per_km: float
    reference_hr_bpm: Optional[float] = None
    reference_pace_min_km: Optional[float] = None
    current_hr_bpm: Optional[float] = None
    hr_difference_bpm: Optional[float] = None


class WIV3HistoricalComparison(BaseModel):
    status: Literal["available", "insufficient", "not_applicable"] = "insufficient"
    comparability: Literal["strong", "moderate", "low", "insufficient"] = "insufficient"
    candidate_count: int = 0
    reference_count: int = 0
    window_days: int
    period_start: Optional[str] = None
    period_end: Optional[str] = None
    pace_at_comparable_hr: WIV3PaceAtComparableHr
    hr_at_comparable_pace: WIV3HrAtComparablePace
    v2_similar_reference: WIV3V2Reference
    exclusion_reasons: Dict[str, int] = Field(default_factory=dict)
    limitations: List[str] = Field(default_factory=list)
    source_paths: List[str] = Field(default_factory=list)


class WIV3TrendSensitivity(BaseModel):
    hr_tolerance_bpm: float
    margin_sec_per_km: float
    status: str


class WIV3PerformanceTrend(BaseModel):
    status: Literal["probable_improvement", "stable", "possible_decline", "insufficient_data"] = "insufficient_data"
    confidence: Confidence = "none"
    observation_count: int = 0
    span_days: Optional[int] = None
    earlier_median_pace_min_km: Optional[float] = None
    later_median_pace_min_km: Optional[float] = None
    median_change_sec_per_km: Optional[float] = None
    variation_confirmed: bool = False
    observed_variation_sec_per_km: Optional[float] = None
    """Current session vs comparable references: an observation, not a trend."""
    criteria: Dict[str, float] = Field(default_factory=dict)
    sensitivity: List[WIV3TrendSensitivity] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)
    source_paths: List[str] = Field(default_factory=list)


class WIV3PrescriptionAssessment(BaseModel):
    status: Literal["consistent", "deviation", "unavailable", "indeterminate"] = "unavailable"
    prescription_id: Optional[str] = None
    planned_date: Optional[str] = None
    prescribed_workout_type: Optional[str] = None
    prescribed_intensity_class: Optional[str] = None
    prescribed_distance_km: Optional[float] = None
    prescribed_duration_minutes: Optional[int] = None
    observed_classification: Optional[str] = None
    reasons: List[str] = Field(default_factory=list)
    source_paths: List[str] = Field(default_factory=list)


class WIV3CoachItem(BaseModel):
    code: str
    text: str
    evidence: Dict[str, float] = Field(default_factory=dict)
    source_paths: List[str] = Field(default_factory=list)


class WIV3CoachAssessment(BaseModel):
    language: Literal["fr", "en", "es"] = "en"
    diagnosis: WIV3CoachItem
    evidence: List[WIV3CoachItem] = Field(default_factory=list, max_length=3)
    limitations: List[WIV3CoachItem] = Field(default_factory=list)
    advice: Optional[WIV3CoachItem] = None


class WorkoutIntelligenceV3(BaseModel):
    version: Literal["v3"] = "v3"
    workout_id: str
    analyzed_date: str
    data_used: List[str] = Field(default_factory=list)
    intensity_assessment: WIV3IntensityAssessment
    session_classification: WIV3SessionClassification
    historical_comparison: WIV3HistoricalComparison
    performance_trend: WIV3PerformanceTrend
    prescription_assessment: WIV3PrescriptionAssessment
    coach_assessment: WIV3CoachAssessment


class WorkoutIntelligenceV3Response(BaseModel):
    """Additive API envelope; Workout Analysis V2 contract is unchanged."""

    workout_id: str
    workout_intelligence_v3: WorkoutIntelligenceV3
