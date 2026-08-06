"""PR07 — RunnerProfile V2: pure deterministic immutable business profile."""

from __future__ import annotations

from datetime import date
from typing import Any, Optional

from pydantic import BaseModel, ConfigDict

from garmin.data_layer import GarminCapabilities
from training_v2.training_history import TrainingHistory, TrainingWindow
from training_v2.training_load import TrainingLoadSnapshot


class RunnerProfile(BaseModel):
    """Immutable runner profile snapshot built from explicit and observed inputs."""

    model_config = ConfigDict(frozen=True)

    reference_date: date

    typical_weekly_km: Optional[float]
    typical_weekly_hours: Optional[float]
    typical_runs_per_week: Optional[float]

    typical_long_run_km: Optional[float]
    typical_speed_kmh: Optional[float]

    primary_discipline: Optional[str]
    preferred_days_per_week: Optional[int]
    max_days_per_week: Optional[int]

    max_hr: Optional[int]
    injury_constraints: Any = None
    availability_constraints: Any = None

    experience_level: str
    profile_confidence: str

    training_load_confidence: str
    has_any_advanced_garmin_metric: bool


def _is_positive_number(value: Any) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0


def _is_non_empty_value(value: Any) -> bool:
    if value is None:
        return False
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        return value > 0
    if isinstance(value, str):
        return value.strip() != ""
    if isinstance(value, (list, tuple, set, dict)):
        return len(value) > 0
    return True


def _read_value(source: Any, *keys: str) -> Any:
    if source is None:
        return None
    for key in keys:
        if isinstance(source, dict):
            if key in source:
                value = source.get(key)
                if value is not None:
                    return value
        else:
            if hasattr(source, key):
                value = getattr(source, key)
                if value is not None:
                    return value
    return None


def _weekly_metric_from_history(
    window_30d: TrainingWindow,
    window_90d: TrainingWindow,
    available_history_days: int,
    metric: str,
) -> Optional[float]:
    value_30d = getattr(window_30d, metric)
    if _is_positive_number(value_30d):
        return float(value_30d) * 7.0 / 30.0

    if available_history_days >= 90:
        value_90d = getattr(window_90d, metric)
        if _is_positive_number(value_90d):
            return float(value_90d) * 7.0 / 90.0

    return None


def _window_metric_from_history(
    window_30d: TrainingWindow,
    window_90d: TrainingWindow,
    available_history_days: int,
    metric: str,
) -> Optional[float]:
    value_30d = getattr(window_30d, metric)
    if _is_positive_number(value_30d):
        return float(value_30d)

    if available_history_days >= 90:
        value_90d = getattr(window_90d, metric)
        if _is_positive_number(value_90d):
            return float(value_90d)

    return None


def _experience_level(history_days: int) -> str:
    if history_days <= 0:
        return "unknown"
    if history_days <= 29:
        return "beginner"
    if history_days <= 89:
        return "developing"
    if history_days <= 364:
        return "established"
    return "experienced"


def _has_exploitable_declared_data(user_profile: Any, physiological_metrics: Any) -> bool:
    declared_fields = [
        _read_value(user_profile, "typical_weekly_km", "weekly_km"),
        _read_value(user_profile, "typical_weekly_hours", "weekly_hours"),
        _read_value(user_profile, "typical_runs_per_week", "weekly_runs_per_week"),
        _read_value(user_profile, "typical_long_run_km", "long_run_km"),
        _read_value(user_profile, "typical_speed_kmh", "speed_kmh"),
        _read_value(user_profile, "discipline"),
        _read_value(user_profile, "preferred_days_per_week"),
        _read_value(user_profile, "max_days_per_week"),
        _read_value(user_profile, "max_hr"),
        _read_value(physiological_metrics, "max_hr"),
        _read_value(user_profile, "injury_constraints"),
        _read_value(user_profile, "availability_constraints"),
    ]
    return any(_is_non_empty_value(v) for v in declared_fields)


def _profile_confidence(history_days: int, has_declared_data: bool) -> str:
    if history_days >= 90:
        return "high"
    if history_days >= 30:
        return "medium"
    if history_days >= 1:
        return "low"
    if has_declared_data:
        return "low"
    return "none"


def build_runner_profile(
    training_history: TrainingHistory,
    training_load_snapshot: TrainingLoadSnapshot,
    garmin_capabilities: GarminCapabilities,
    user_profile: Any,
    physiological_metrics: Any,
    reference_date: date,
) -> RunnerProfile:
    """Build RunnerProfile from observed history and explicit user declarations."""

    history_days = int(training_history.available_history_days or 0)

    weekly_km = _weekly_metric_from_history(
        training_history.window_30d,
        training_history.window_90d,
        history_days,
        "distance_km",
    )
    if weekly_km is None:
        declared_weekly_km = _read_value(user_profile, "typical_weekly_km", "weekly_km")
        weekly_km = float(declared_weekly_km) if _is_positive_number(declared_weekly_km) else None

    weekly_hours = _weekly_metric_from_history(
        training_history.window_30d,
        training_history.window_90d,
        history_days,
        "duration_hours",
    )
    if weekly_hours is None:
        declared_weekly_hours = _read_value(user_profile, "typical_weekly_hours", "weekly_hours")
        weekly_hours = float(declared_weekly_hours) if _is_positive_number(declared_weekly_hours) else None

    runs_per_week = _weekly_metric_from_history(
        training_history.window_30d,
        training_history.window_90d,
        history_days,
        "activity_count",
    )
    if runs_per_week is None:
        declared_runs = _read_value(user_profile, "typical_runs_per_week", "weekly_runs_per_week")
        runs_per_week = float(declared_runs) if _is_positive_number(declared_runs) else None

    long_run_km = _window_metric_from_history(
        training_history.window_30d,
        training_history.window_90d,
        history_days,
        "longest_run_km",
    )
    if long_run_km is None:
        declared_long_run = _read_value(user_profile, "typical_long_run_km", "long_run_km")
        long_run_km = float(declared_long_run) if _is_positive_number(declared_long_run) else None

    speed_kmh = _window_metric_from_history(
        training_history.window_30d,
        training_history.window_90d,
        history_days,
        "average_speed_kmh",
    )
    if speed_kmh is None:
        declared_speed = _read_value(user_profile, "typical_speed_kmh", "speed_kmh")
        speed_kmh = float(declared_speed) if _is_positive_number(declared_speed) else None

    primary_discipline = _read_value(user_profile, "discipline")
    preferred_days_per_week = _read_value(user_profile, "preferred_days_per_week")
    max_days_per_week = _read_value(user_profile, "max_days_per_week")
    max_hr_raw = _read_value(user_profile, "max_hr")
    if not _is_positive_number(max_hr_raw):
        max_hr_raw = _read_value(physiological_metrics, "max_hr")
    max_hr = int(max_hr_raw) if _is_positive_number(max_hr_raw) else None

    injury_constraints = _read_value(user_profile, "injury_constraints")
    availability_constraints = _read_value(user_profile, "availability_constraints")

    has_declared_data = _has_exploitable_declared_data(user_profile, physiological_metrics)

    has_any_advanced_garmin_metric = any(
        [
            garmin_capabilities.has_hrv,
            garmin_capabilities.has_vo2max,
            garmin_capabilities.has_training_readiness,
            garmin_capabilities.has_training_status,
            garmin_capabilities.has_body_battery,
            garmin_capabilities.has_stress,
            garmin_capabilities.has_running_dynamics,
            garmin_capabilities.has_power,
            garmin_capabilities.has_race_predictions,
        ]
    )

    return RunnerProfile(
        reference_date=reference_date,
        typical_weekly_km=round(weekly_km, 2) if weekly_km is not None else None,
        typical_weekly_hours=round(weekly_hours, 2) if weekly_hours is not None else None,
        typical_runs_per_week=round(runs_per_week, 2) if runs_per_week is not None else None,
        typical_long_run_km=round(long_run_km, 2) if long_run_km is not None else None,
        typical_speed_kmh=round(speed_kmh, 2) if speed_kmh is not None else None,
        primary_discipline=primary_discipline if isinstance(primary_discipline, str) and primary_discipline.strip() else None,
        preferred_days_per_week=int(preferred_days_per_week) if _is_positive_number(preferred_days_per_week) else None,
        max_days_per_week=int(max_days_per_week) if _is_positive_number(max_days_per_week) else None,
        max_hr=max_hr,
        injury_constraints=injury_constraints,
        availability_constraints=availability_constraints,
        experience_level=_experience_level(history_days),
        profile_confidence=_profile_confidence(history_days, has_declared_data),
        training_load_confidence=training_load_snapshot.confidence,
        has_any_advanced_garmin_metric=has_any_advanced_garmin_metric,
    )
