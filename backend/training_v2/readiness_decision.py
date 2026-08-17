"""Canonical Readiness decision layer for downstream consumers.

Design rules
------------
- PURE: no DB, no provider calls, no HTTP, no Redis, no LLM, no random, no
  mutable global state, no clock-based calls.
- Consumes an existing ReadinessResult only. It does NOT recompute readiness,
  sufficiency, subscores, or any physiological signal.
- ReadinessSufficiency remains the source of truth for data availability.
- PRODUCT CALIBRATION V1 — RECALIBRABLE — NOT PHYSIOLOGICAL LAW.
- Consumers define neither their own readiness thresholds nor their own
  canonical readiness bands.

Canonical interpretation
------------------------
ReadinessResult -> ReadinessDecision -> consumer

- readiness is None                   -> UNAVAILABLE
- readiness.score is None             -> UNAVAILABLE
- sufficiency_level == INSUFFICIENT   -> UNAVAILABLE
- score >= 75                         -> FAVORABLE
- 55 <= score < 75                    -> CAUTION
- 40 <= score < 55                    -> LOW
- score < 40                          -> VERY_LOW

DEGRADED is preserved as metadata when a score exists; it does not suppress the
band calculation.
"""

from __future__ import annotations

from enum import Enum
from typing import Optional, Tuple

from pydantic import BaseModel, ConfigDict

from .readiness import ReadinessConfidence, ReadinessResult
from .readiness_sufficiency import ReasonCode, SufficiencyLevel

# PRODUCT CALIBRATION V1 — RECALIBRABLE — NOT PHYSIOLOGICAL LAW
READINESS_FAVORABLE_MIN: float = 75.0
READINESS_CAUTION_MIN: float = 55.0
READINESS_LOW_MIN: float = 40.0


class ReadinessBand(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"
    FAVORABLE = "FAVORABLE"
    CAUTION = "CAUTION"
    LOW = "LOW"
    VERY_LOW = "VERY_LOW"


class ReadinessDecision(BaseModel):
    """Immutable canonical readiness interpretation for downstream consumers."""

    model_config = ConfigDict(frozen=True)

    band: ReadinessBand
    score: Optional[float]
    confidence: ReadinessConfidence
    sufficiency_level: SufficiencyLevel
    reason_codes: Tuple[str, ...]
    readiness_reasons: Tuple[ReasonCode, ...]


def build_readiness_decision(readiness: Optional[ReadinessResult]) -> ReadinessDecision:
    """Build the canonical readiness interpretation from an existing result."""

    if readiness is None:
        return ReadinessDecision(
            band=ReadinessBand.UNAVAILABLE,
            score=None,
            confidence=ReadinessConfidence.NONE,
            sufficiency_level=SufficiencyLevel.INSUFFICIENT,
            reason_codes=("READINESS_UNAVAILABLE",),
            readiness_reasons=(),
        )

    readiness_reasons = tuple(readiness.reasons)
    score = readiness.score

    if score is None or readiness.sufficiency_level == SufficiencyLevel.INSUFFICIENT:
        return ReadinessDecision(
            band=ReadinessBand.UNAVAILABLE,
            score=score,
            confidence=readiness.confidence,
            sufficiency_level=readiness.sufficiency_level,
            reason_codes=("READINESS_UNAVAILABLE",),
            readiness_reasons=readiness_reasons,
        )

    if score >= READINESS_FAVORABLE_MIN:
        band = ReadinessBand.FAVORABLE
        reason_codes = ("READINESS_FAVORABLE",)
    elif score >= READINESS_CAUTION_MIN:
        band = ReadinessBand.CAUTION
        reason_codes = ("READINESS_CAUTION",)
    elif score >= READINESS_LOW_MIN:
        band = ReadinessBand.LOW
        reason_codes = ("READINESS_LOW",)
    else:
        band = ReadinessBand.VERY_LOW
        reason_codes = ("READINESS_VERY_LOW",)

    return ReadinessDecision(
        band=band,
        score=score,
        confidence=readiness.confidence,
        sufficiency_level=readiness.sufficiency_level,
        reason_codes=reason_codes,
        readiness_reasons=readiness_reasons,
    )


__all__ = [
    "READINESS_FAVORABLE_MIN",
    "READINESS_CAUTION_MIN",
    "READINESS_LOW_MIN",
    "ReadinessBand",
    "ReadinessDecision",
    "build_readiness_decision",
]
