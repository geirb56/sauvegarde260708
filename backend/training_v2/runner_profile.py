"""PR07 — RunnerProfile: pure deterministic athlete profile layer for V2.

Design rules
------------
- PURE: no MongoDB, no Garmin calls, no API calls, no LLM, no cache,
  no global mutable state, no environment variables.
- reference_date must be supplied explicitly by the caller — datetime.now()
  is NEVER called inside this module.
- RunnerProfile centralises durable or semi-durable athlete characteristics.
  It does NOT decide resumption / fatigue / overload / readiness states.

Source priority
---------------
- Personal / constraint fields:
    declared user_profile value if valid, else absence / empty list.
- Training metrics:
    observed TrainingHistory value (30d first, 90d fallback only when needed),
    else explicit declared user_profile value, else None.
- Physiology:
    observed physiological_metrics value if valid, else declared value if
    explicitly provided, else None.

History semantics
-----------------
experience_level describes the DEPTH of observable history in RunIndex.
It does NOT claim to measure the runner's true sporting level.

  unknown      : 0 day of usable history
  beginner     : 1 to 29 days
  developing   : 30 to 89 days
  established  : 90 to 364 days
  experienced  : 365+ days

profile_confidence describes how much exploitable profile data is available.
Declared data alone can only produce "low", never "medium" or "high".
"""

from __future__ import annotations

from datetime import date
from typing import Any, Callable, Mapping, Optional

from pydantic import BaseModel, ConfigDict

from .domain_capabilities import DomainCapabilities
from .training_history import TrainingHistory, TrainingWindow
from .training_load import TrainingLoadSnapshot

_ROUND = 2

_DISCIPLINE_ALIASES = {
    "road": "road",
    "running": "road",
    "run": "road",
    "road_running": "road",
    "route": "road",
    "trail": "trail",
    "trail_running": "trail",
    "treadmill": "treadmill",
    "treadmill_running": "treadmill",
    "tapis": "treadmill",
    "mixed": "mixed",
    "multi": "mixed",
    "multisport": "mixed",
    "unknown": "unknown",
}


class RunnerProfile(BaseModel):
    """Immutable runner profile built from declared and observed data."""

    model_config = ConfigDict(frozen=True)

    reference_date: date

    age: Optional[int]
    sex: Optional[str]

    primary_discipline: str
    experience_level: str

    typical_weekly_km: Optional[float]
    typical_weekly_km_is_observed: bool
    """True when typical_weekly_km is derived from observed history windows.

    False when typical_weekly_km comes exclusively from the user's declared
    profile (``user_profile["typical_weekly_km"]`` / ``"weekly_km"``).
    False also when typical_weekly_km is None.

    This flag MUST be used instead of ``available_history_days > 0`` whenever
    a caller needs a *history-backed* baseline — the mere existence of history
    does not guarantee that ``typical_weekly_km`` was drawn from it.
    """
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

    injury_constraints: list[str]
    availability_constraints: list[str]


def _clean_str(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    cleaned = value.strip()
    return cleaned or None


def _parse_float(value: Any) -> Optional[float]:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        cleaned = value.strip().replace(",", ".")
        if not cleaned:
            return None
        try:
            return float(cleaned)
        except ValueError:
            return None
    return None


def _parse_positive_float(value: Any) -> Optional[float]:
    number = _parse_float(value)
    if number is None or number <= 0:
        return None
    return number


def _parse_int_like(value: Any) -> Optional[int]:
    number = _parse_float(value)
    if number is None or not number.is_integer():
        return None
    return int(number)


def _parse_age(value: Any) -> Optional[int]:
    age = _parse_int_like(value)
    if age is None or age < 10 or age > 100:
        return None
    return age


def _parse_days_per_week(value: Any) -> Optional[int]:
    days = _parse_int_like(value)
    if days is None or days < 1 or days > 7:
        return None
    return days


def _parse_hr(value: Any) -> Optional[int]:
    hr = _parse_int_like(value)
    if hr is None or hr <= 0:
        return None
    return hr


def _round_optional(value: Optional[float]) -> Optional[float]:
    if value is None:
        return None
    return round(value, _ROUND)


def _normalize_discipline(value: Any) -> str:
    cleaned = _clean_str(value)
    if cleaned is None:
        return "unknown"
    return _DISCIPLINE_ALIASES.get(cleaned.lower(), "unknown")


def _normalize_string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        items = [value]
    elif isinstance(value, (list, tuple, set)):
        items = list(value)
    else:
        return []

    normalized: list[str] = []
    for item in items:
        cleaned = _clean_str(item)
        if cleaned is not None:
            normalized.append(cleaned)
    return normalized


def _first_valid_number(
    source: Optional[Mapping[str, Any]],
    parser: Callable[[Any], Optional[float | int]],
    *keys: str,
) -> Optional[float | int]:
    if not isinstance(source, Mapping):
        return None
    for key in keys:
        if key not in source:
            continue
        parsed = parser(source.get(key))
        if parsed is not None:
            return parsed
    return None


def _first_valid_string(source: Optional[Mapping[str, Any]], *keys: str) -> Optional[str]:
    if not isinstance(source, Mapping):
        return None
    for key in keys:
        if key not in source:
            continue
        cleaned = _clean_str(source.get(key))
        if cleaned is not None:
            return cleaned
    return None


def _window_value(
    training_history: TrainingHistory,
    available_history_days: int,
    extractor: Callable[[TrainingWindow], Any],
    parser: Callable[[Any], Optional[float]],
) -> tuple[Optional[float], Optional[int]]:
    parsed_30d = parser(extractor(training_history.window_30d))
    if parsed_30d is not None:
        return parsed_30d, training_history.window_30d.days

    if available_history_days >= 90:
        parsed_90d = parser(extractor(training_history.window_90d))
        if parsed_90d is not None:
            return parsed_90d, training_history.window_90d.days
    return None, None


def _history_metric_or_declared(
    training_history: TrainingHistory,
    available_history_days: int,
    extractor: Callable[[TrainingWindow], Any],
    declared_value: Any,
    parser: Callable[[Any], Optional[float]],
    observed_transform: Optional[Callable[[float, int], float]] = None,
) -> tuple[Optional[float], bool]:
    """Return (value, is_observed).

    ``is_observed`` is True when the value was derived from an observed history
    window (30d or 90d), False when it falls back to the declared value.
    """
    observed, window_days = _window_value(training_history, available_history_days, extractor, parser)
    if observed is not None:
        return (
            _round_optional(
                observed_transform(observed, window_days or 30)
                if observed_transform is not None
                else observed
            ),
            True,
        )
    declared = parser(declared_value)
    if declared is None:
        return None, False
    return _round_optional(declared), False


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


def _profile_confidence(available_history_days: int, has_usable_profile_data: bool) -> str:
    if available_history_days >= 90:
        return "high"
    if available_history_days >= 30:
        return "medium"
    if available_history_days > 0:
        return "low"
    return "low" if has_usable_profile_data else "none"


def build_runner_profile(
    *,
    training_history: TrainingHistory,
    training_load: TrainingLoadSnapshot,
    user_profile: Optional[dict] = None,
    capabilities: Optional[DomainCapabilities] = None,
    physiological_metrics: Optional[dict] = None,
    reference_date: date,
) -> RunnerProfile:
    """Build an immutable RunnerProfile from explicit declared/observed inputs.

    ``training_load`` is injected explicitly for interface stability, but PR07
    intentionally does not derive any fatigue, reprise, overload, or readiness
    decision from it.
    """

    profile = user_profile if isinstance(user_profile, Mapping) else {}
    physiology = physiological_metrics if isinstance(physiological_metrics, Mapping) else {}
    capabilities = capabilities or DomainCapabilities()

    age = _first_valid_number(profile, _parse_age, "age")
    sex = _first_valid_string(profile, "sex", "gender")
    primary_discipline = _normalize_discipline(
        _first_valid_string(profile, "discipline", "primary_discipline", "sport", "sport_type")
    )

    preferred_days_per_week = _first_valid_number(
        profile,
        _parse_days_per_week,
        "preferred_days_per_week",
        "days_per_week",
        "desired_days_per_week",
    )
    max_days_per_week = _first_valid_number(
        profile,
        _parse_days_per_week,
        "max_days_per_week",
    )
    if (
        preferred_days_per_week is not None
        and max_days_per_week is not None
        and preferred_days_per_week > max_days_per_week
    ):
        preferred_days_per_week = None

    preferred_long_run_day = _first_valid_string(profile, "preferred_long_run_day", "long_run_day")
    injury_constraints = _normalize_string_list(profile.get("injury_constraints"))
    availability_constraints = _normalize_string_list(profile.get("availability_constraints"))
    available_history_days = max(0, int(training_history.available_history_days or 0))

    typical_weekly_km, typical_weekly_km_is_observed = _history_metric_or_declared(
        training_history,
        available_history_days,
        lambda window: window.distance_km,
        _first_valid_number(profile, _parse_positive_float, "typical_weekly_km", "weekly_km"),
        _parse_positive_float,
        lambda value, window_days: value * 7.0 / float(window_days),
    )
    typical_weekly_hours, _ = _history_metric_or_declared(
        training_history,
        available_history_days,
        lambda window: window.duration_hours,
        _first_valid_number(profile, _parse_positive_float, "typical_weekly_hours", "weekly_hours"),
        _parse_positive_float,
        lambda value, window_days: value * 7.0 / float(window_days),
    )
    typical_runs_per_week, _ = _history_metric_or_declared(
        training_history,
        available_history_days,
        lambda window: window.activity_count,
        _first_valid_number(profile, _parse_positive_float, "typical_runs_per_week", "runs_per_week"),
        _parse_positive_float,
        lambda value, window_days: value * 7.0 / float(window_days),
    )
    typical_long_run_km, _ = _history_metric_or_declared(
        training_history,
        available_history_days,
        lambda window: window.longest_run_km,
        _first_valid_number(profile, _parse_positive_float, "typical_long_run_km", "long_run_km"),
        _parse_positive_float,
    )
    typical_speed_kmh, _ = _history_metric_or_declared(
        training_history,
        available_history_days,
        lambda window: window.average_speed_kmh,
        _first_valid_number(profile, _parse_positive_float, "typical_speed_kmh", "average_speed_kmh"),
        _parse_positive_float,
    )

    vo2max = _first_valid_number(physiology, _parse_positive_float, "vo2max")
    if vo2max is None:
        vo2max = _first_valid_number(profile, _parse_positive_float, "vo2max")

    vma_kmh = _first_valid_number(physiology, _parse_positive_float, "vma_kmh", "vma")
    if vma_kmh is None:
        vma_kmh = _first_valid_number(profile, _parse_positive_float, "vma_kmh", "vma")

    max_hr = _first_valid_number(physiology, _parse_hr, "max_hr", "max_heart_rate")
    if max_hr is None:
        max_hr = _first_valid_number(profile, _parse_hr, "max_hr", "max_heart_rate")

    resting_hr = _first_valid_number(physiology, _parse_hr, "resting_hr", "resting_heart_rate")
    if resting_hr is None:
        resting_hr = _first_valid_number(profile, _parse_hr, "resting_hr", "resting_heart_rate")

    has_usable_profile_data = any(
        value is not None
        for value in (
            age,
            sex,
            preferred_days_per_week,
            max_days_per_week,
            preferred_long_run_day,
            typical_weekly_km,
            typical_weekly_hours,
            typical_runs_per_week,
            typical_long_run_km,
            typical_speed_kmh,
            vo2max,
            vma_kmh,
            max_hr,
            resting_hr,
        )
    ) or bool(
        injury_constraints
        or availability_constraints
        or primary_discipline != "unknown"
        or capabilities.has_hrv
        or capabilities.has_vo2max
        or capabilities.has_training_readiness
        or capabilities.has_power
        or capabilities.has_running_dynamics
    )

    return RunnerProfile(
        reference_date=reference_date,
        age=age,
        sex=sex.lower() if sex is not None else None,
        primary_discipline=primary_discipline,
        experience_level=_experience_level(available_history_days),
        typical_weekly_km=typical_weekly_km,
        typical_weekly_km_is_observed=typical_weekly_km_is_observed,
        typical_weekly_hours=typical_weekly_hours,
        typical_runs_per_week=typical_runs_per_week,
        typical_long_run_km=typical_long_run_km,
        typical_speed_kmh=typical_speed_kmh,
        available_history_days=available_history_days,
        profile_confidence=_profile_confidence(available_history_days, has_usable_profile_data),
        vo2max=_round_optional(vo2max),
        vma_kmh=_round_optional(vma_kmh),
        max_hr=max_hr,
        resting_hr=resting_hr,
        has_hrv=capabilities.has_hrv,
        has_vo2max=capabilities.has_vo2max,
        has_training_readiness=capabilities.has_training_readiness,
        has_power=capabilities.has_power,
        has_running_dynamics=capabilities.has_running_dynamics,
        preferred_days_per_week=preferred_days_per_week,
        max_days_per_week=max_days_per_week,
        preferred_long_run_day=preferred_long_run_day,
        injury_constraints=injury_constraints,
        availability_constraints=availability_constraints,
    )


__all__ = ["RunnerProfile", "build_runner_profile"]
