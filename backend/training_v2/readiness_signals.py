"""R1.6 — Readiness Signals: pure deterministic signal layer for RunIndex V2.

Design rules
------------
- PURE: no MongoDB, no provider-specific calls, no API calls, no LLM, no cache,
  no global mutable state, no environment variables, no datetime.now().
- No Readiness score, no 0–100 numeric output.
- No fallback neutral values: absent data stays absent (returns None).
- No Garmin / Strava / Terra / provider dependency.
- All results are deterministic and fully reproducible for identical inputs.

Functions
---------
    compute_rhr_deviation(...)   → Optional[float]
    compute_hrv_deviation(...)   → Optional[float]
    extract_sleep_signal(...)    → Optional[float]
    extract_load_signal(...)     → Optional[ReadinessLoadSignal]

Run from the backend directory
-------------------------------
    python -m pytest tests/test_training_v2_readiness_signals.py -q
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from training_v2.readiness_sufficiency import PhysioSignal, SleepRecord
from training_v2.training_load import TrainingLoadSnapshot

# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


class ReadinessLoadSignal(BaseModel):
    """Provider-neutral load signal for R2.

    Values are copied directly from TrainingLoadSnapshot; no recalculation.

    acute_load_7d       : total load (minutes) over the last 7 days.
    chronic_weekly_load : average weekly load over the last 28 days.
    load_change_percent : week-on-week load change (%); None when unavailable.
    acwr                : Acute:Chronic Workload Ratio; None when unavailable.
    """

    model_config = ConfigDict(frozen=True)

    acute_load_7d: float
    chronic_weekly_load: float
    load_change_percent: Optional[float]
    acwr: Optional[float]


# ---------------------------------------------------------------------------
# Public functions
# ---------------------------------------------------------------------------


def compute_rhr_deviation(rhr: Optional[PhysioSignal]) -> Optional[float]:
    """Return rhr_delta_bpm = recent_rhr − baseline_rhr.

    Returns None when:
    - ``rhr`` is None (signal entirely absent)
    - ``rhr.recent_value`` is None (no recent measurement)
    - ``rhr.baseline`` is None (no baseline)
    - ``rhr.baseline.value`` is None (baseline not yet computed)
    """
    if rhr is None:
        return None
    if rhr.recent_value is None:
        return None
    if rhr.baseline is None:
        return None
    if rhr.baseline.value is None:
        return None
    return rhr.recent_value - rhr.baseline.value


def compute_hrv_deviation(hrv: Optional[PhysioSignal]) -> Optional[float]:
    """Return hrv_delta_pct = (recent_hrv − baseline_hrv) / baseline_hrv × 100.

    Returns None when:
    - ``hrv`` is None (signal entirely absent)
    - ``hrv.recent_value`` is None (no recent measurement)
    - ``hrv.baseline`` is None (no baseline)
    - ``hrv.baseline.value`` is None (baseline not yet computed)
    - ``hrv.baseline.value`` <= 0 (division by zero / invalid baseline)
    """
    if hrv is None:
        return None
    if hrv.recent_value is None:
        return None
    if hrv.baseline is None:
        return None
    if hrv.baseline.value is None:
        return None
    if hrv.baseline.value <= 0:
        return None
    return (hrv.recent_value - hrv.baseline.value) / hrv.baseline.value * 100.0


def extract_sleep_signal(sleep: Optional[SleepRecord]) -> Optional[float]:
    """Return SleepRecord.duration_hours, or None when unavailable.

    Only ``duration_hours`` is used for R1.6.  The provider ``score`` field is
    deliberately ignored — its scale is not yet sufficiently normalised to
    serve as a provider-neutral business input.

    Returns None when:
    - ``sleep`` is None (no recent sleep record)
    - ``sleep.duration_hours`` is None (duration not reported by provider)
    """
    if sleep is None:
        return None
    return sleep.duration_hours


def extract_load_signal(
    snapshot: TrainingLoadSnapshot,
) -> Optional[ReadinessLoadSignal]:
    """Return a provider-neutral ReadinessLoadSignal copied from the snapshot.

    No recalculation of ACWR or any window is performed here.
    Values are taken verbatim from ``snapshot``.

    Returns None when ``snapshot.is_available`` is False.
    """
    if not snapshot.is_available:
        return None
    return ReadinessLoadSignal(
        acute_load_7d=snapshot.acute_load_7d,
        chronic_weekly_load=snapshot.chronic_weekly_load,
        load_change_percent=snapshot.load_change_percent,
        acwr=snapshot.acwr,
    )
