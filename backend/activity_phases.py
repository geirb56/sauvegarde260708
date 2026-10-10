"""Provider-neutral observed phases; no prescription or analysis logic."""

from typing import Literal, Optional
import math

from pydantic import BaseModel, ConfigDict


ACTIVITY_PHASE_SCHEMA_VERSION = 2


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
