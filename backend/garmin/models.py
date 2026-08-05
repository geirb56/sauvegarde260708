from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass
class GarminActivity:
    activity_id: str | None = None
    activity_type: str | None = None
    start_time: str | None = None
    distance_m: float | None = None
    duration_s: float | None = None
    moving_duration_s: float | None = None
    average_speed_mps: float | None = None
    average_moving_speed_mps: float | None = None
    max_speed_mps: float | None = None
    average_hr: int | None = None
    max_hr: int | None = None
    min_hr: int | None = None
    average_run_cadence: float | None = None
    max_run_cadence: float | None = None
    stride_length: float | None = None
    steps: int | None = None
    elevation_gain: float | None = None
    elevation_loss: float | None = None
    calories: float | None = None
    moderate_intensity_minutes: int | None = None
    vigorous_intensity_minutes: int | None = None
    lap_count: int | None = None
    has_hr_zones: bool | None = None
    has_splits: bool | None = None
    details_available: bool | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GarminDailyMetrics:
    date: str | None = None
    resting_hr: int | None = None
    sleep_hours: float | None = None
    sleep_score: int | None = None
    stress: float | None = None
    body_battery: int | None = None
    respiration: float | None = None
    hrv: float | None = None
    source: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass
class GarminCapabilities:
    has_hrv: bool | None = None
    has_vo2max: bool | None = None
    has_training_readiness: bool | None = None
    has_training_status: bool | None = None
    has_body_battery: bool | None = None
    has_stress: bool | None = None
    has_running_dynamics: bool | None = None
    has_power: bool | None = None
    has_race_predictions: bool | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
