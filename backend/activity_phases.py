"""Provider-neutral observed phases; no prescription or analysis logic."""

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict


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
