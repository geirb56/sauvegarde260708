"""PR07 — RunnerProfile: pure deterministic runner profile for V2.

RunnerProfile centralises durable or semi-durable runner characteristics built
from explicit inputs only:
  - TrainingHistory
  - TrainingLoadSnapshot
  - GarminCapabilities
  - user_profile
  - physiological_metrics

Scope limits
------------
- This module does NOT decide readiness, fatigue, overload, or return-to-run.
- The experience_level describes observed history depth only.  It does NOT
  claim to measure the runner's true athletic level.
- No fallback weekly volume is invented.
- No physiological estimate is manufactured.

Run from the backend directory
------------------------------
    python -m pytest tests/test_runner_profile_pr07.py -q
"""

from __future__ import annotations

import math
from datetime import date
from typing import Any, Dict, Iterable, List, Optional

from pydantic import BaseModel, ConfigDict

from garmin.data_layer import GarminCapabilities
from training_v2.training_history import TrainingHistory, TrainingWindow
from training_v2.training_load import TrainingLoadSnapshot

_ROUND = 2
_VALID_DISCIPLINES = {"road", "trail", "treadmill", "mixed", "unknown"}
_DISCIPLINE_MAP = {
    "road": "road",
    "running": "road",
    "road_running": "road",
    "route": "road",
    "trail": "trail",
    "trail_running": "trail",
    "treadmill": "treadmill",
    "treadmill_running": "treadmill",
    "mixed": "mixed",
    "hybrid": "mixed",
    "multi": "mixed",
    "unknown": "unknown",
}


class RunnerProfile(BaseModel):
    """Immutable runner profile for V2 consumers."""

    model_config = ConfigDict(frozen=True)

    reference_date: date

    age: Optional[int]
    sex: Optional[str]

    primary_discipline: Optional[str]
    experience_level: str

    typical_weekly_km: Optional[float]
    typical_weekly_hours: Optional[float]
    typical_runs_per_week: Optional[float]
    typical_long_run_km: Optional[float]
    typical_speed_kmh: Optional[float]

    available_history_days: int
    profile_confidence: str

    vo2max: Optional[float]
    vma_kmh: Optional[float]
    max_hr: Optional[int]
    resting_hr: Optional[int]

    has_hrv: bool
    has_vo2max: bool
    has_training_readiness: bool
    has_power: bool
    has_running_dynamics: bool

    preferred_days_per_week: Optional[int]
    max_days_per_week: Optional[int]
    preferred_long_run_day: Optional[str]

    injury_constraints: List[str]
    availability_constraints: List[str]


def _dict_or_empty(value: Optional[dict]) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _first_present(data: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in data:
            return data[key]
    return None


def _as_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        result = float(value)
    elif isinstance(value, str):
        stripped = value.strip()
        if not stripped:
            return None
        try:
            result = float(stripped)
        except ValueError:
            return None
    else:
        return None
    if not math.isfinite(result):
        return None
    return result


def _as_positive_float(value: Any) -> Optional[float]:
    result = _as_float(value)
    if result is None or result <= 0:
        return None
    return result


def _as_int_in_range(value: Any, *, minimum: int, maximum: int) -> Optional[int]:
    result = _as_float(value)
    if result is None or not result.is_integer():
        return None
    int_result = int(result)
    if int_result < minimum or int_result > maximum:
        return None
    return int_result


def _normalise_text(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    stripped = value.strip()
    if not stripped:
        return None
    return stripped.lower()


def _normalise_discipline(value: Any) -> str:
    normalised = _normalise_text(value)
    if normalised is None:
        return "unknown"
    return _DISCIPLINE_MAP.get(normalised, "unknown")


def _normalise_constraints(value: Any) -> List[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items: Iterable[Any] = [value]
    elif isinstance(value, list):
        items = value
    else:
        return []
    result: List[str] = []
    for item in items:
        if not isinstance(item, str):
            continue
        stripped = item.strip()
        if stripped:
            result.append(stripped)
    return result


def _history_metric_window(training_history: TrainingHistory, field: str) -> Optional[TrainingWindow]:
    window_30d = training_history.window_30d
    value_30d = getattr(window_30d, field)
    if value_30d not in (None, 0, 0.0):
        return window_30d

    if training_history.available_history_days >= 90:
        window_90d = training_history.window_90d
        value_90d = getattr(window_90d, field)
        if value_90d not in (None, 0, 0.0):
            return window_90d

    return None


def _weekly_from_window(window: TrainingWindow, field: str) -> Optional[float]:
    value = getattr(window, field)
    if value in (None, 0, 0.0):
        return None
    weekly = float(value) * 7.0 / float(window.days)
    return round(weekly, _ROUND)


def _experience_level(available_history_days: int) -> str:
    if available_history_days <= 0:
        return "unknown"
    if available_history_days < 30:
        return "beginner"
    if available_history_days < 90:
        return "developing"
    if available_history_days < 365:
        return "established"
    return "experienced"


def _profile_confidence(available_history_days: int) -> str:
    if available_history_days <= 0:
        return "none"
    if available_history_days < 30:
        return "low"
    if available_history_days < 90:
        return "medium"
    return "high"


def build_runner_profile(
    *,
    training_history: TrainingHistory,
    training_load: TrainingLoadSnapshot,
    user_profile: Optional[dict] = None,
    garmin_capabilities: Optional[GarminCapabilities] = None,
    physiological_metrics: Optional[dict] = None,
    reference_date: date,
) -> RunnerProfile:
    """Build a deterministic RunnerProfile from explicit inputs only.

    ``training_load`` is injected explicitly even though PR07 does not yet
    derive profile fields from ACWR/readiness-like concepts.  Keeping it in the
    signature makes the future dependency explicit without introducing side
    effects or hidden lookups.
    """
    del training_load

    user = _dict_or_empty(user_profile)
    physio = _dict_or_empty(physiological_metrics)
    caps = garmin_capabilities or GarminCapabilities()

    available_history_days = max(int(training_history.available_history_days), 0)

    age = _as_int_in_range(_first_present(user, "age"), minimum=10, maximum=100)
    sex = _normalise_text(_first_present(user, "sex", "gender"))
    primary_discipline = _normalise_discipline(
        _first_present(user, "primary_discipline", "discipline", "sport", "running_discipline")
    )

    preferred_days_per_week = _as_int_in_range(
        _first_present(user, "preferred_days_per_week", "desired_days_per_week", "target_days_per_week"),
        minimum=1,
        maximum=7,
    )
    max_days_per_week = _as_int_in_range(
        _first_present(user, "max_days_per_week"),
        minimum=1,
        maximum=7,
    )
    if (
        preferred_days_per_week is not None
        and max_days_per_week is not None
        and preferred_days_per_week > max_days_per_week
    ):
        preferred_days_per_week = None

    preferred_long_run_day = _normalise_text(
        _first_present(user, "preferred_long_run_day", "long_run_day")
    )
    injury_constraints = _normalise_constraints(
        _first_present(user, "injury_constraints")
    )
    availability_constraints = _normalise_constraints(
        _first_present(user, "availability_constraints")
    )

    observed_weekly_window = (
        training_history.window_30d if available_history_days >= 30 else None
    )
    observed_support_window = _history_metric_window(training_history, "distance_km")

    typical_weekly_km = (
        _weekly_from_window(observed_weekly_window, "distance_km")
        if observed_weekly_window is not None
        else None
    )
    if typical_weekly_km is None and observed_support_window is not None and observed_support_window.days == 90:
        typical_weekly_km = _weekly_from_window(observed_support_window, "distance_km")
    if typical_weekly_km is None:
        typical_weekly_km = _as_positive_float(
            _first_present(user, "typical_weekly_km", "weekly_km", "weekly_distance_km")
        )

    typical_weekly_hours = (
        _weekly_from_window(observed_weekly_window, "duration_hours")
        if observed_weekly_window is not None
        else None
    )
    if typical_weekly_hours is None and available_history_days >= 90:
        typical_weekly_hours = _weekly_from_window(training_history.window_90d, "duration_hours")
    if typical_weekly_hours is None:
        typical_weekly_hours = _as_positive_float(
            _first_present(user, "typical_weekly_hours", "weekly_hours")
        )

    typical_runs_per_week = (
        _weekly_from_window(observed_weekly_window, "activity_count")
        if observed_weekly_window is not None
        else None
    )
    if typical_runs_per_week is None and available_history_days >= 90:
        typical_runs_per_week = _weekly_from_window(training_history.window_90d, "activity_count")
    if typical_runs_per_week is None:
        typical_runs_per_week = _as_positive_float(
            _first_present(user, "typical_runs_per_week", "runs_per_week", "weekly_runs")
        )

    long_run_window = _history_metric_window(training_history, "longest_run_km")
    typical_long_run_km = (
        getattr(long_run_window, "longest_run_km")
        if long_run_window is not None
        else None
    )
    if typical_long_run_km is None:
        typical_long_run_km = _as_positive_float(
            _first_present(user, "typical_long_run_km", "long_run_km")
        )
    if typical_long_run_km is not None:
        typical_long_run_km = round(typical_long_run_km, _ROUND)

    speed_window = _history_metric_window(training_history, "average_speed_kmh")
    typical_speed_kmh = (
        getattr(speed_window, "average_speed_kmh")
        if speed_window is not None
        else None
    )
    if typical_speed_kmh is None:
        typical_speed_kmh = _as_positive_float(
            _first_present(user, "typical_speed_kmh", "average_speed_kmh")
        )
    if typical_speed_kmh is not None:
        typical_speed_kmh = round(typical_speed_kmh, _ROUND)

    vo2max = _as_positive_float(_first_present(physio, "vo2max"))
    if vo2max is not None:
        vo2max = round(vo2max, _ROUND)

    vma_kmh = _as_positive_float(_first_present(physio, "vma_kmh", "vma"))
    if vma_kmh is not None:
        vma_kmh = round(vma_kmh, _ROUND)

    max_hr = _as_int_in_range(
        _first_present(physio, "max_hr", "max_heart_rate", "maxHeartRate"),
        minimum=1,
        maximum=300,
    )
    if max_hr is None:
        max_hr = _as_int_in_range(
            _first_present(user, "max_hr", "declared_max_hr", "max_heart_rate"),
            minimum=1,
            maximum=300,
        )

    resting_hr = _as_int_in_range(
        _first_present(physio, "resting_hr", "resting_heart_rate", "restingHeartRate"),
        minimum=1,
        maximum=300,
    )

    return RunnerProfile(
        reference_date=reference_date,
        age=age,
        sex=sex,
        primary_discipline=primary_discipline,
        experience_level=_experience_level(available_history_days),
        typical_weekly_km=typical_weekly_km,
        typical_weekly_hours=typical_weekly_hours,
        typical_runs_per_week=typical_runs_per_week,
        typical_long_run_km=typical_long_run_km,
        typical_speed_kmh=typical_speed_kmh,
        available_history_days=available_history_days,
        profile_confidence=_profile_confidence(available_history_days),
        vo2max=vo2max,
        vma_kmh=vma_kmh,
        max_hr=max_hr,
        resting_hr=resting_hr,
        has_hrv=caps.has_hrv,
        has_vo2max=caps.has_vo2max,
        has_training_readiness=caps.has_training_readiness,
        has_power=caps.has_power,
        has_running_dynamics=caps.has_running_dynamics,
        preferred_days_per_week=preferred_days_per_week,
        max_days_per_week=max_days_per_week,
        preferred_long_run_day=preferred_long_run_day,
        injury_constraints=injury_constraints,
        availability_constraints=availability_constraints,
    )
