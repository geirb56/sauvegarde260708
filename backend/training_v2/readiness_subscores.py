"""R2A — Readiness Subscores V2 (pure deterministic business layer).

This module computes three independent subscores:
- PhysioSubscore
- SleepSubscore
- LoadSubscore

Rules:
- Outputs are always in [0, 100] or None.
- No final readiness score is computed here.
- Pure, deterministic, provider-neutral, no I/O, no DB, no datetime.now().
- No fallback neutral values: None remains None.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict

from training_v2.readiness_signals import ReadinessLoadSignal

# ---------------------------------------------------------------------------
# PRODUCT_CALIBRATION_V1 (explicitly product calibration, not universal science)
# ---------------------------------------------------------------------------

# Physio — RHR delta (bpm)
PRODUCT_CALIBRATION_V1_RHR_SCORE_AT_OR_BELOW_BASELINE = 100.0
PRODUCT_CALIBRATION_V1_RHR_SCORE_0_TO_2 = 90.0
PRODUCT_CALIBRATION_V1_RHR_SCORE_2_TO_4 = 75.0
PRODUCT_CALIBRATION_V1_RHR_SCORE_4_TO_6 = 55.0
PRODUCT_CALIBRATION_V1_RHR_SCORE_6_TO_8 = 35.0
PRODUCT_CALIBRATION_V1_RHR_SCORE_ABOVE_8 = 20.0

# Physio — HRV relative delta (%)
PRODUCT_CALIBRATION_V1_HRV_SCORE_AT_OR_ABOVE_MINUS_5 = 100.0
PRODUCT_CALIBRATION_V1_HRV_SCORE_MINUS_10_TO_MINUS_5 = 90.0
PRODUCT_CALIBRATION_V1_HRV_SCORE_MINUS_20_TO_MINUS_10 = 70.0
PRODUCT_CALIBRATION_V1_HRV_SCORE_MINUS_30_TO_MINUS_20 = 45.0
PRODUCT_CALIBRATION_V1_HRV_SCORE_BELOW_MINUS_30 = 25.0

# Sleep — duration (hours)
PRODUCT_CALIBRATION_V1_SLEEP_SCORE_8_PLUS = 100.0
PRODUCT_CALIBRATION_V1_SLEEP_SCORE_7_TO_8 = 90.0
PRODUCT_CALIBRATION_V1_SLEEP_SCORE_6_TO_7 = 70.0
PRODUCT_CALIBRATION_V1_SLEEP_SCORE_5_TO_6 = 45.0
PRODUCT_CALIBRATION_V1_SLEEP_SCORE_BELOW_5 = 20.0

# Load — load_change_percent (%)
PRODUCT_CALIBRATION_V1_LOAD_SCORE_AT_OR_BELOW_10 = 100.0
PRODUCT_CALIBRATION_V1_LOAD_SCORE_10_TO_25 = 90.0
PRODUCT_CALIBRATION_V1_LOAD_SCORE_25_TO_40 = 75.0
PRODUCT_CALIBRATION_V1_LOAD_SCORE_40_TO_60 = 55.0
PRODUCT_CALIBRATION_V1_LOAD_SCORE_ABOVE_60 = 35.0

# ---------------------------------------------------------------------------
# Output contracts
# ---------------------------------------------------------------------------


class PhysioSubscore(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: Optional[float]
    rhr_component: Optional[float]
    hrv_component: Optional[float]


class SleepSubscore(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: Optional[float]


class LoadSubscore(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: Optional[float]


class ReadinessSubscores(BaseModel):
    model_config = ConfigDict(frozen=True)

    physio: PhysioSubscore
    sleep: SleepSubscore
    load: LoadSubscore


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bounded(score: float) -> float:
    return max(0.0, min(100.0, float(score)))


def _rhr_component(rhr_delta_bpm: Optional[float]) -> Optional[float]:
    if rhr_delta_bpm is None:
        return None
    if rhr_delta_bpm <= 0:
        return PRODUCT_CALIBRATION_V1_RHR_SCORE_AT_OR_BELOW_BASELINE
    if rhr_delta_bpm <= 2:
        return PRODUCT_CALIBRATION_V1_RHR_SCORE_0_TO_2
    if rhr_delta_bpm <= 4:
        return PRODUCT_CALIBRATION_V1_RHR_SCORE_2_TO_4
    if rhr_delta_bpm <= 6:
        return PRODUCT_CALIBRATION_V1_RHR_SCORE_4_TO_6
    if rhr_delta_bpm <= 8:
        return PRODUCT_CALIBRATION_V1_RHR_SCORE_6_TO_8
    return PRODUCT_CALIBRATION_V1_RHR_SCORE_ABOVE_8


def _hrv_component(hrv_delta_percent: Optional[float]) -> Optional[float]:
    if hrv_delta_percent is None:
        return None
    if hrv_delta_percent >= -5:
        return PRODUCT_CALIBRATION_V1_HRV_SCORE_AT_OR_ABOVE_MINUS_5
    if hrv_delta_percent >= -10:
        return PRODUCT_CALIBRATION_V1_HRV_SCORE_MINUS_10_TO_MINUS_5
    if hrv_delta_percent >= -20:
        return PRODUCT_CALIBRATION_V1_HRV_SCORE_MINUS_20_TO_MINUS_10
    if hrv_delta_percent >= -30:
        return PRODUCT_CALIBRATION_V1_HRV_SCORE_MINUS_30_TO_MINUS_20
    return PRODUCT_CALIBRATION_V1_HRV_SCORE_BELOW_MINUS_30


def _sleep_component(sleep_duration_hours: Optional[float]) -> Optional[float]:
    if sleep_duration_hours is None:
        return None
    if sleep_duration_hours >= 8:
        return PRODUCT_CALIBRATION_V1_SLEEP_SCORE_8_PLUS
    if sleep_duration_hours >= 7:
        return PRODUCT_CALIBRATION_V1_SLEEP_SCORE_7_TO_8
    if sleep_duration_hours >= 6:
        return PRODUCT_CALIBRATION_V1_SLEEP_SCORE_6_TO_7
    if sleep_duration_hours >= 5:
        return PRODUCT_CALIBRATION_V1_SLEEP_SCORE_5_TO_6
    return PRODUCT_CALIBRATION_V1_SLEEP_SCORE_BELOW_5


def _load_base_component(load_change_percent: Optional[float]) -> Optional[float]:
    if load_change_percent is None:
        return None
    if load_change_percent <= 10:
        return PRODUCT_CALIBRATION_V1_LOAD_SCORE_AT_OR_BELOW_10
    if load_change_percent <= 25:
        return PRODUCT_CALIBRATION_V1_LOAD_SCORE_10_TO_25
    if load_change_percent <= 40:
        return PRODUCT_CALIBRATION_V1_LOAD_SCORE_25_TO_40
    if load_change_percent <= 60:
        return PRODUCT_CALIBRATION_V1_LOAD_SCORE_40_TO_60
    return PRODUCT_CALIBRATION_V1_LOAD_SCORE_ABOVE_60


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def build_physio_subscore(
    *,
    rhr_delta_bpm: Optional[float],
    hrv_delta_percent: Optional[float],
) -> PhysioSubscore:
    rhr = _rhr_component(rhr_delta_bpm)
    hrv = _hrv_component(hrv_delta_percent)

    if rhr is not None and hrv is not None:
        score = _bounded((rhr + hrv) / 2.0)
    elif rhr is not None:
        score = _bounded(rhr)
    elif hrv is not None:
        score = _bounded(hrv)
    else:
        score = None

    return PhysioSubscore(score=score, rhr_component=rhr, hrv_component=hrv)


def build_sleep_subscore(*, sleep_duration_hours: Optional[float]) -> SleepSubscore:
    score = _sleep_component(sleep_duration_hours)
    return SleepSubscore(score=_bounded(score) if score is not None else None)


def build_load_subscore(
    *,
    load_signal: Optional[ReadinessLoadSignal],
) -> LoadSubscore:
    if load_signal is None:
        return LoadSubscore(score=None)

    base_score = _load_base_component(load_signal.load_change_percent)
    if base_score is None:
        return LoadSubscore(score=None)

    return LoadSubscore(score=_bounded(base_score))


def build_readiness_subscores(
    *,
    rhr_delta_bpm: Optional[float],
    hrv_delta_percent: Optional[float],
    sleep_duration_hours: Optional[float],
    load_signal: Optional[ReadinessLoadSignal],
) -> ReadinessSubscores:
    return ReadinessSubscores(
        physio=build_physio_subscore(
            rhr_delta_bpm=rhr_delta_bpm,
            hrv_delta_percent=hrv_delta_percent,
        ),
        sleep=build_sleep_subscore(sleep_duration_hours=sleep_duration_hours),
        load=build_load_subscore(
            load_signal=load_signal,
        ),
    )
