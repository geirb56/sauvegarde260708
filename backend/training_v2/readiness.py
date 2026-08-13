"""R2B — Readiness Final Aggregation V2 (pure deterministic business layer).

This module combines ReadinessSufficiency (R1) and the three subscores from
ReadinessSubscores (R2A) into a single ReadinessResult.

Design rules
------------
- PURE: no MongoDB, no provider-specific calls, no API calls, no LLM, no cache,
  no global mutable state, no environment variables, no datetime.now().
- No recommendation, no color status, no fatigue_ratio, no recovery time.
- No fallback neutral values: None remains None.
- No numeric confidence — confidence is categorical only (NONE/NORMAL/REDUCED).
- R1 (ReadinessSufficiency) is the sole source of truth for sufficiency level.
- R2B does NOT recalculate sufficiency from subscores.
- R2B does NOT invent new reason codes.
- Subscore values must be finite and in [0, 100]; ValueError raised otherwise.
- reasons is a tuple — fully immutable.
- Weights are product calibration V1, recalibratable, not a scientifically
  proven universal weighting.

Aggregation rules
-----------------
INSUFFICIENT  → score=None, confidence=NONE, reasons propagated from R1.
SUFFICIENT + all 3 subscores available
              → full weighted average (physio×40 + sleep×30 + load×30) / 100,
                confidence=NORMAL.
SUFFICIENT + at least one subscore missing
              → renormalized weighted average over available subscores only,
                confidence=REDUCED (sufficiency_level stays SUFFICIENT).
DEGRADED      → renormalized weighted average over available subscores only,
                confidence=REDUCED.
Defensive     → if level is SUFFICIENT/DEGRADED but no usable subscore is
                provided by the caller, score=None, confidence=NONE.

Score format
------------
float 0–100, rounded to 1 decimal place.  Never an int. Never 0 as a default.

Run from the backend directory
-------------------------------
    python -m pytest tests/test_training_v2_readiness.py -q
"""

from __future__ import annotations

import math
from enum import Enum
from typing import Optional, Tuple

from pydantic import BaseModel, ConfigDict

from training_v2.readiness_subscores import (
    LoadSubscore,
    PhysioSubscore,
    SleepSubscore,
)
from training_v2.readiness_sufficiency import ReasonCode, ReadinessSufficiency, SufficiencyLevel

# ---------------------------------------------------------------------------
# Product calibration V1 weights
# Product calibration V1, recalibratable, not a scientifically proven
# universal weighting.
# ---------------------------------------------------------------------------

PRODUCT_CALIBRATION_V1_WEIGHT_PHYSIO: float = 40.0
PRODUCT_CALIBRATION_V1_WEIGHT_SLEEP: float = 30.0
PRODUCT_CALIBRATION_V1_WEIGHT_LOAD: float = 30.0

# ---------------------------------------------------------------------------
# Output contract
# ---------------------------------------------------------------------------


class ReadinessConfidence(str, Enum):
    NONE = "NONE"
    NORMAL = "NORMAL"
    REDUCED = "REDUCED"


class ReadinessResult(BaseModel):
    """Immutable final readiness result — R2B output contract.

    score            : float 0–100 (1 decimal) or None when undetermined.
    confidence       : categorical NONE | NORMAL | REDUCED (never numeric).
    sufficiency_level: propagated from R1 — source of truth.
    reasons          : R1 reason codes propagated as-is (tuple, immutable).
    """

    model_config = ConfigDict(frozen=True)

    score: Optional[float]
    confidence: ReadinessConfidence
    sufficiency_level: SufficiencyLevel
    reasons: Tuple[ReasonCode, ...]


# ---------------------------------------------------------------------------
# Builder
# ---------------------------------------------------------------------------


def build_readiness_result(
    sufficiency: ReadinessSufficiency,
    physio: Optional[PhysioSubscore],
    sleep: Optional[SleepSubscore],
    load: Optional[LoadSubscore],
) -> ReadinessResult:
    """Combine R1 sufficiency with R2A subscores into a ReadinessResult.

    Parameters
    ----------
    sufficiency:
        Output of build_readiness_sufficiency (R1).  This is the sole source
        of truth for the sufficiency level.
    physio:
        Optional PhysioSubscore from build_physio_subscore (R2A).
    sleep:
        Optional SleepSubscore from build_sleep_subscore (R2A).
    load:
        Optional LoadSubscore from build_load_subscore (R2A).

    Returns
    -------
    ReadinessResult
        Immutable final readiness result.
    """
    level = sufficiency.level
    reasons: tuple[ReasonCode, ...] = tuple(sufficiency.reasons)

    # ------------------------------------------------------------------
    # CAS 1 — INSUFFICIENT
    # ------------------------------------------------------------------
    if level == SufficiencyLevel.INSUFFICIENT:
        return ReadinessResult(
            score=None,
            confidence=ReadinessConfidence.NONE,
            sufficiency_level=level,
            reasons=reasons,
        )

    # ------------------------------------------------------------------
    # CAS 2 & 3 — SUFFICIENT / DEGRADED
    # Extract available subscore values, rejecting non-finite or
    # out-of-range values to prevent silent corruption.
    # ------------------------------------------------------------------
    def _validate_score(v: Optional[float], name: str) -> Optional[float]:
        if v is None:
            return None
        if not math.isfinite(v):
            raise ValueError(f"Subscore '{name}' must be finite, got {v!r}")
        if v < 0.0 or v > 100.0:
            raise ValueError(
                f"Subscore '{name}' must be in [0, 100], got {v!r}"
            )
        return v

    physio_score: Optional[float] = _validate_score(
        physio.score if physio is not None else None, "physio"
    )
    sleep_score: Optional[float] = _validate_score(
        sleep.score if sleep is not None else None, "sleep"
    )
    load_score: Optional[float] = _validate_score(
        load.score if load is not None else None, "load"
    )

    # Build list of (value, weight) pairs for available subscores only.
    pairs: list[tuple[float, float]] = []
    if physio_score is not None:
        pairs.append((physio_score, PRODUCT_CALIBRATION_V1_WEIGHT_PHYSIO))
    if sleep_score is not None:
        pairs.append((sleep_score, PRODUCT_CALIBRATION_V1_WEIGHT_SLEEP))
    if load_score is not None:
        pairs.append((load_score, PRODUCT_CALIBRATION_V1_WEIGHT_LOAD))

    # ------------------------------------------------------------------
    # Defensive case: level is SUFFICIENT/DEGRADED but caller provided no
    # usable subscore.  Never return 0.
    # ------------------------------------------------------------------
    if not pairs:
        return ReadinessResult(
            score=None,
            confidence=ReadinessConfidence.NONE,
            sufficiency_level=level,
            reasons=reasons,
        )

    # ------------------------------------------------------------------
    # Weighted average (renormalized automatically by total weight).
    # ------------------------------------------------------------------
    total_weight = sum(w for _, w in pairs)
    weighted_sum = sum(v * w for v, w in pairs)
    raw_score = weighted_sum / total_weight

    # Clamp to [0, 100] and round to 1 decimal.
    clamped = max(0.0, min(100.0, raw_score))
    final_score = round(clamped, 1)

    # ------------------------------------------------------------------
    # Confidence — categorical, never numeric.
    # SUFFICIENT + all 3 subscores present → NORMAL
    # SUFFICIENT + at least one subscore missing → REDUCED
    # DEGRADED → REDUCED
    # ------------------------------------------------------------------
    all_subscores_available = (
        physio_score is not None
        and sleep_score is not None
        and load_score is not None
    )
    if level == SufficiencyLevel.SUFFICIENT and all_subscores_available:
        confidence = ReadinessConfidence.NORMAL
    else:
        confidence = ReadinessConfidence.REDUCED

    return ReadinessResult(
        score=final_score,
        confidence=confidence,
        sufficiency_level=level,
        reasons=reasons,
    )
