"""DomainCapabilities — provider-neutral capability flags for Training V2."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict


class DomainCapabilities(BaseModel):
    """Minimal business capability model required by RunnerProfile."""

    model_config = ConfigDict(frozen=True)

    has_hrv: bool = False
    has_vo2max: bool = False
    has_training_readiness: bool = False
    has_power: bool = False
    has_running_dynamics: bool = False


__all__ = ["DomainCapabilities"]
