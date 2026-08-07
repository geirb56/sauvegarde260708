"""PR05 — PlanGoal: pure deterministic goal layer for RunIndex V2.

Design rules
------------
- PURE: no MongoDB, no Garmin calls, no API calls, no LLM, no cache,
  no global mutable state, no datetime.now().
- PlanGoal describes user intent.  It does NOT prescribe training strategy.
- PlanGoal does NOT judge whether a goal is feasible, realistic, or
  compatible with the runner's profile.
- No imports from training_engine, training_load_engine, llm_coach,
  coach_service, TrainingState, TrainingLoad, TrainingHistory, or RunnerProfile.

Principle
---------
"PlanGoal décrit. Il ne prescrit pas."

Supported goal types
--------------------
  maintenance    → Maintien en forme
  5k             → 5 km
  10k            → 10 km
  half_marathon  → Semi-marathon
  marathon       → Marathon
  ultra          → Ultra

Canonical distances (centralised here — never dispersed)
---------------------------------------------------------
  5k             = 5.0 km
  10k            = 10.0 km
  half_marathon  = 21.0975 km
  marathon       = 42.195 km
  ultra          > 42.195 km  (must be supplied explicitly)

Provenance
----------
  "user"     — goal explicitly chosen by the user.
  "default"  — no user input available; RunIndex built a maintenance goal.

"""

from __future__ import annotations

from datetime import date
from enum import Enum
from typing import Optional

from pydantic import BaseModel, ConfigDict, field_validator, model_validator

# ---------------------------------------------------------------------------
# Constants (canonical distances — single source of truth)
# ---------------------------------------------------------------------------

DISTANCE_5K_KM: float = 5.0
DISTANCE_10K_KM: float = 10.0
DISTANCE_HALF_MARATHON_KM: float = 21.0975
DISTANCE_MARATHON_KM: float = 42.195

_STANDARD_GOAL_DISTANCES: dict[str, float] = {
    "5k": DISTANCE_5K_KM,
    "10k": DISTANCE_10K_KM,
    "half_marathon": DISTANCE_HALF_MARATHON_KM,
    "marathon": DISTANCE_MARATHON_KM,
}

ULTRA_MIN_DISTANCE_KM: float = DISTANCE_MARATHON_KM  # strictly > 42.195


# ---------------------------------------------------------------------------
# GoalType enum
# ---------------------------------------------------------------------------


class GoalType(str, Enum):
    """Closed set of supported training goal types."""

    maintenance = "maintenance"
    five_k = "5k"
    ten_k = "10k"
    half_marathon = "half_marathon"
    marathon = "marathon"
    ultra = "ultra"


# ---------------------------------------------------------------------------
# PlanGoal model
# ---------------------------------------------------------------------------


class PlanGoal(BaseModel):
    """Immutable snapshot representing what the user wants to prepare for.

    PlanGoal describes user intent.  It does NOT prescribe:
    - weekly volume
    - progression
    - periodisation
    - number of sessions
    - long run
    - intensity
    - any session
    - feasibility assessment

    These responsibilities belong to PR06+.
    """

    model_config = ConfigDict(frozen=True)

    goal_type: GoalType

    # All optional — absence of data is not invented data.
    target_distance_km: Optional[float] = None
    target_time_seconds: Optional[int] = None
    race_date: Optional[date] = None

    created_from: str  # "user" | "default"

    # ------------------------------------------------------------------
    # Field-level validators
    # ------------------------------------------------------------------

    @field_validator("target_time_seconds")
    @classmethod
    def _validate_time(cls, v: Optional[int]) -> Optional[int]:
        if v is not None and v <= 0:
            raise ValueError("target_time_seconds must be strictly positive when provided")
        return v

    @field_validator("created_from")
    @classmethod
    def _validate_created_from(cls, v: str) -> str:
        allowed = {"user", "default"}
        if v not in allowed:
            raise ValueError(f"created_from must be one of {allowed}, got {v!r}")
        return v

    # ------------------------------------------------------------------
    # Cross-field validation
    # ------------------------------------------------------------------

    @model_validator(mode="after")
    def _validate_goal_consistency(self) -> "PlanGoal":
        goal = self.goal_type

        # ── maintenance ──────────────────────────────────────────────────
        if goal == GoalType.maintenance:
            if self.target_time_seconds is not None:
                raise ValueError(
                    "maintenance goal must not have target_time_seconds"
                )
            if self.race_date is not None:
                raise ValueError(
                    "maintenance goal must not have race_date"
                )
            if self.target_distance_km is not None:
                raise ValueError(
                    "maintenance goal must not have target_distance_km"
                )
            return self

        # ── standard distances ────────────────────────────────────────────
        if goal.value in _STANDARD_GOAL_DISTANCES:
            canonical = _STANDARD_GOAL_DISTANCES[goal.value]
            # The builder always sets this to the canonical value.
            # Direct PlanGoal construction without the builder must also
            # supply exactly the canonical distance.
            if self.target_distance_km != canonical:
                raise ValueError(
                    f"target_distance_km for {goal.value} must be exactly "
                    f"{canonical}, got {self.target_distance_km}"
                )
            return self

        # ── ultra ─────────────────────────────────────────────────────────
        if goal == GoalType.ultra:
            if self.target_distance_km is None:
                raise ValueError("ultra goal requires target_distance_km")
            if self.target_distance_km <= ULTRA_MIN_DISTANCE_KM:
                raise ValueError(
                    f"ultra goal requires target_distance_km > {ULTRA_MIN_DISTANCE_KM}, "
                    f"got {self.target_distance_km}"
                )
            return self

        return self  # pragma: no cover — exhaustive by GoalType enum


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def build_plan_goal(
    *,
    goal_type: GoalType | str,
    target_time_seconds: Optional[int] = None,
    race_date: Optional[date] = None,
    target_distance_km: Optional[float] = None,
    created_from: str = "user",
) -> PlanGoal:
    """Build an immutable :class:`PlanGoal` from explicit inputs.

    Deterministic — no external I/O, no datetime.now(), no randomness.

    Parameters
    ----------
    goal_type:
        The type of goal (GoalType enum or its string value).
    target_time_seconds:
        Optional chronometric target in canonical seconds.  Must be > 0 when
        provided.  PlanGoal does NOT judge feasibility.
    race_date:
        Optional scheduled race date.  No implicit use of today's date.
    target_distance_km:
        Must be absent (None) for maintenance and standard distance goals
        (5k, 10k, half_marathon, marathon) — the distance is derived automatically.
        Required and strictly > 42.195 for ultra goals.
    created_from:
        Provenance of this goal: "user" (explicit choice) or "default"
        (built by RunIndex in the absence of user input).
    """
    if isinstance(goal_type, str):
        goal_type = GoalType(goal_type)

    # Standard distances: distance is derived from goal_type — caller must NOT supply it.
    if goal_type.value in _STANDARD_GOAL_DISTANCES:
        if target_distance_km is not None:
            raise ValueError(
                f"target_distance_km must not be provided for {goal_type.value!r}: "
                "the distance is automatically derived from the goal type."
            )
        target_distance_km = _STANDARD_GOAL_DISTANCES[goal_type.value]

    # For maintenance and ultra: validation is handled inside the model.

    return PlanGoal(
        goal_type=goal_type,
        target_distance_km=target_distance_km,
        target_time_seconds=target_time_seconds,
        race_date=race_date,
        created_from=created_from,
    )


__all__ = ["GoalType", "PlanGoal", "build_plan_goal"]
