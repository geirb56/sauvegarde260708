"""LEGACY PERFORMANCE COMPATIBILITY helpers only.

This module intentionally contains PERFORMANCE ESTIMATION ONLY:
- VMA estimation
- VO2max derivation from VMA
- pace / pace-zone formatting

This module exists only to preserve legacy runtime compatibility behavior.
It is NOT the canonical V2 physiological source of truth.
It does NOT decide training structure, readiness, periodization, adaptation,
or canonical physiology. Inputs are normalized primitive facts only; no
Mongo/Garmin access occurs here. Invalid or non-positive compatibility inputs
are treated as unusable facts and ignored.
"""

from __future__ import annotations

from typing import Mapping, Optional, Sequence


DEFAULT_COMPATIBILITY_VMA_KMH = 12.0
_PACE_MIN_PER_KM_MIN = 3.0
_PACE_MIN_PER_KM_MAX = 10.0
_FAST_EFFORT_PACE_MAX_MIN_PER_KM = 5.5
_MIN_VMA_EFFORT_DURATION_MINUTES = 6.0


def _to_positive_float(value) -> Optional[float]:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    if parsed <= 0:
        return None
    return parsed


def compute_vo2max_from_vma(vma_kmh: Optional[float]) -> Optional[float]:
    vma = _to_positive_float(vma_kmh)
    if vma is None:
        return None
    return round(vma * 3.5, 1)


def vma_pace(vma_kmh: float, pct: float) -> str:
    """Target pace 'MM:SS' per km at a given fraction of VMA."""
    vma = _to_positive_float(vma_kmh)
    speed = (vma or 0) * pct
    if speed <= 0:
        return "--:--"
    pace_min = 60.0 / speed
    minutes = int(pace_min)
    seconds = int(round((pace_min - minutes) * 60))
    if seconds >= 60:
        minutes += 1
        seconds -= 60
    return f"{minutes}:{seconds:02d}"


def vma_pace_range(vma_kmh: float, pct_low: float, pct_high: float) -> str:
    """Pace range 'slow-fast' between two %VMA."""
    return f"{vma_pace(vma_kmh, pct_low)}-{vma_pace(vma_kmh, pct_high)}"


def build_legacy_pace_zones(estimated_vma: float) -> dict:
    """Return the legacy runtime/display pace zones derived from VMA."""

    def _legacy_compat_pace(vma_pct: float) -> str:
        speed = max(0.1, estimated_vma * vma_pct)
        pace = 60.0 / speed
        minutes = int(pace)
        seconds = int((pace % 1) * 60)
        return f"{minutes}:{seconds:02d}"

    return {
        "z1": f"{_legacy_compat_pace(0.65)}-{_legacy_compat_pace(0.70)}",
        "z2": f"{_legacy_compat_pace(0.75)}-{_legacy_compat_pace(0.80)}",
        "z3": f"{_legacy_compat_pace(0.82)}-{_legacy_compat_pace(0.87)}",
        "z4": f"{_legacy_compat_pace(0.88)}-{_legacy_compat_pace(0.93)}",
        "z5": f"{_legacy_compat_pace(0.95)}-{_legacy_compat_pace(1.00)}",
        "marathon": f"{_legacy_compat_pace(0.78)}-{_legacy_compat_pace(0.82)}",
        "semi": f"{_legacy_compat_pace(0.82)}-{_legacy_compat_pace(0.85)}",
    }


def estimate_legacy_vma_from_normalized_runs(
    runs: Sequence[Mapping[str, object]],
) -> tuple[float, str, str]:
    """Legacy VMA estimation preserved exactly for compatibility.

    Each run is expected to expose:
    - ``distance_km``: positive float
    - ``duration_minutes``: positive float

    Missing/invalid values are skipped. ``None`` is never coerced to ``0``.
    If no usable pace sample exists, the legacy default VMA 12.0 km/h is kept.
    """
    paces: list[float] = []
    vma_efforts: list[dict] = []

    for run in runs:
        distance_km = _to_positive_float(run.get("distance_km"))
        duration_minutes = _to_positive_float(run.get("duration_minutes"))
        if distance_km is None or duration_minutes is None:
            continue

        pace = duration_minutes / distance_km
        if not (_PACE_MIN_PER_KM_MIN < pace < _PACE_MIN_PER_KM_MAX):
            continue

        paces.append(pace)
        if (
            duration_minutes >= _MIN_VMA_EFFORT_DURATION_MINUTES
            and pace < _FAST_EFFORT_PACE_MAX_MIN_PER_KM
        ):
            vma_efforts.append(
                {
                    "speed_kmh": 60.0 / pace,
                    "duration_minutes": duration_minutes,
                }
            )

    if paces:
        avg_pace = sum(paces) / len(paces)
        if vma_efforts:
            best_effort = max(vma_efforts, key=lambda effort: effort["speed_kmh"])
            if best_effort["duration_minutes"] >= 20:
                estimated_vma = best_effort["speed_kmh"] / 0.85
            elif best_effort["duration_minutes"] >= 12:
                estimated_vma = best_effort["speed_kmh"] / 0.90
            else:
                estimated_vma = best_effort["speed_kmh"] / 0.95
            vma_method = "effort"
        else:
            estimated_vma = (60.0 / avg_pace) / 0.70
            vma_method = "average"
    else:
        estimated_vma = DEFAULT_COMPATIBILITY_VMA_KMH
        vma_method = "default"

    vma_confidence = {
        "effort": "high",
        "average": "low",
        "default": "low",
    }.get(vma_method, "low")
    return round(estimated_vma, 1), vma_method, vma_confidence


def build_legacy_performance_compatibility(
    runs: Sequence[Mapping[str, object]],
) -> tuple[float, float, str, str, dict]:
    """Legacy runtime compatibility bundle: VMA, VO2max, method, confidence, paces."""
    estimated_vma, vma_method, vma_confidence = estimate_legacy_vma_from_normalized_runs(runs)
    vo2max = compute_vo2max_from_vma(estimated_vma)
    return (
        estimated_vma,
        vo2max if vo2max is not None else round(estimated_vma * 3.5, 1),
        vma_method,
        vma_confidence,
        build_legacy_pace_zones(estimated_vma),
    )


__all__ = [
    "DEFAULT_COMPATIBILITY_VMA_KMH",
    "compute_vo2max_from_vma",
    "vma_pace",
    "vma_pace_range",
    "build_legacy_pace_zones",
    "estimate_legacy_vma_from_normalized_runs",
    "build_legacy_performance_compatibility",
]
