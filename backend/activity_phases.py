"""Provider-neutral observed phases; no prescription or analysis logic."""

from typing import Literal, Optional
import math

from pydantic import BaseModel, ConfigDict


ACTIVITY_PHASE_SCHEMA_VERSION = 2

# Garmin typed-splits native types with a known canonical phase type. Shared by
# import (garmin.data_layer) and cached-phase reading so both agree.
GARMIN_NATIVE_PHASE_TYPES = {
    "INTERVAL_ACTIVE": "effort",
    "INTERVAL_RECOVERY": "recovery",
    "INTERVAL_REST": "recovery",
    "INTERVAL_WARMUP": "warmup",
    "INTERVAL_COOLDOWN": "cooldown",
}


def garmin_native_phase_type(native_type: object) -> Optional[str]:
    """Canonical phase type for a known Garmin native type, else ``None``."""
    if not isinstance(native_type, str):
        return None
    return GARMIN_NATIVE_PHASE_TYPES.get(native_type)


class ActivityPhase(BaseModel):
    model_config = ConfigDict(frozen=True, extra="ignore")

    order: int
    native_type: Optional[str] = None
    phase_type: Literal["effort", "recovery", "warmup", "cooldown", "unknown"] = "unknown"
    duration_s: Optional[float] = None
    distance_m: Optional[float] = None
    average_speed_mps: Optional[float] = None
    average_hr: Optional[float] = None
    max_hr: Optional[float] = None
    min_hr: Optional[float] = None
    source: str

    @property
    def pace_sec_per_km(self) -> Optional[float]:
        """Derived on consumption, not persisted as another source of truth."""
        speed = self.average_speed_mps
        if speed is None or not math.isfinite(speed) or speed <= 0:
            return None
        pace = 1000 / speed
        return pace if math.isfinite(pace) else None
