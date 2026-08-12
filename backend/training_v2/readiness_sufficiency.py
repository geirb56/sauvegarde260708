"""R1 — ReadinessSufficiency: pure deterministic sufficiency layer for RunIndex V2.

Design rules
------------
- PURE: no MongoDB, no provider-specific calls, no API calls, no LLM, no cache,
  no global mutable state, no environment variables.
- No Readiness score, no 0–100 numeric output.
- No fallback neutral values: absent data stays absent.
- No Garmin / Strava / Terra / provider dependency.
- All results are deterministic and fully reproducible for identical inputs.

Classification
--------------
The function returns one of three levels:

    SUFFICIENT   — all signals are exploitable and baselines are solid.
    DEGRADED     — computation is possible but at least one needed signal is
                   incomplete or its baseline is thin.
    INSUFFICIENT — a blocking signal is entirely missing.

Exactly 8 reason codes (cumulable)
-----------------------------------
    missing_hrv           — no recent HRV measure
    missing_rhr           — no recent RHR measure
    missing_physio        — both HRV and RHR are absent  (blocking)
    missing_sleep         — no recent sleep record
    missing_load          — no exploitable training load  (blocking)
    thin_baseline_rhr     — RHR baseline < 5 valid measures over 14 days
    thin_baseline_hrv     — HRV baseline < 5 valid measures over 14 days
    thin_load_history     — load history < 14 calendar days

Precedence rules for DEGRADED vs SUFFICIENT
--------------------------------------------
A missing individual physio signal (missing_hrv or missing_rhr) does NOT
cause DEGRADED when the other signal is fully exploitable:

    HRV absent + RHR exploitable  → missing_hrv present, NOT DEGRADED for that reason
    RHR absent + HRV exploitable  → missing_rhr present, NOT DEGRADED for that reason

DEGRADED is triggered by:
    - missing_sleep
    - thin_baseline of the physiological signal actually used
    - thin_load_history

Baseline thresholds
--------------------
    >= 5 valid measures over 14 days → sufficient baseline
    <  5 valid measures over 14 days → thin baseline  (thin_baseline_rhr / thin_baseline_hrv)

Load history thresholds (reused from TrainingLoadSnapshot.confidence)
-----------------------------------------------------------------------
    "none"   → missing_load  (blocking)
    "low"    → thin_load_history  (non-blocking, causes DEGRADED)
    "medium" → exploitable (>= 14 days)
    "high"   → mature (>= 28 days)

Run from the backend directory
-------------------------------
    python -m pytest tests/test_training_v2_readiness_sufficiency.py -q
"""

from __future__ import annotations

from enum import Enum
from typing import List, Optional

from pydantic import BaseModel, ConfigDict

from training_v2.training_load import TrainingLoadSnapshot

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_BASELINE_MIN_MEASURES = 5  # minimum valid measures over 14 days for a solid baseline


# ---------------------------------------------------------------------------
# Enumerations
# ---------------------------------------------------------------------------


class SufficiencyLevel(str, Enum):
    SUFFICIENT = "SUFFICIENT"
    DEGRADED = "DEGRADED"
    INSUFFICIENT = "INSUFFICIENT"


class ReasonCode(str, Enum):
    missing_hrv = "missing_hrv"
    missing_rhr = "missing_rhr"
    missing_physio = "missing_physio"
    missing_sleep = "missing_sleep"
    missing_load = "missing_load"
    thin_baseline_rhr = "thin_baseline_rhr"
    thin_baseline_hrv = "thin_baseline_hrv"
    thin_load_history = "thin_load_history"


# ---------------------------------------------------------------------------
# Provider-neutral input contract
# ---------------------------------------------------------------------------


class PhysioBaseline(BaseModel):
    """Baseline information for a single physiological signal (RHR or HRV).

    valid_measures: number of valid measurements collected over the last 14 days.
    """

    model_config = ConfigDict(frozen=True)

    valid_measures: int


class PhysioSignal(BaseModel):
    """A recent physiological measurement with its associated baseline.

    recent_value: the most recent measurement (float). None = absent.
    baseline: baseline descriptor; None = no baseline data available.
    """

    model_config = ConfigDict(frozen=True)

    recent_value: Optional[float]
    baseline: Optional[PhysioBaseline]


class SleepRecord(BaseModel):
    """Minimal sleep information.

    A present (non-None) SleepRecord means a recent sleep record exists.
    Pass ``None`` to ``ReadinessSufficiencyInput.sleep`` to signal absent sleep.

    Additional fields (duration_hours, score, etc.) are intentionally absent
    to avoid fabricating neutral values.
    """

    model_config = ConfigDict(frozen=True)


class ReadinessSufficiencyInput(BaseModel):
    """Provider-neutral input contract for the ReadinessSufficiency layer.

    Fields
    ------
    rhr    : Recent RHR measurement + baseline.  None = signal entirely absent.
    hrv    : Recent HRV measurement + baseline.  None = signal entirely absent.
    sleep  : Recent sleep record.                None = no recent sleep data.
    load   : TrainingLoadSnapshot computed by training_v2.training_load.
             Must be supplied explicitly by the caller (no lazy computation).
    """

    model_config = ConfigDict(frozen=True)

    rhr: Optional[PhysioSignal]
    hrv: Optional[PhysioSignal]
    sleep: Optional[SleepRecord]
    load: TrainingLoadSnapshot


# ---------------------------------------------------------------------------
# Output model
# ---------------------------------------------------------------------------


class ReadinessSufficiency(BaseModel):
    """Immutable result of the ReadinessSufficiency classification.

    level   : one of SUFFICIENT | DEGRADED | INSUFFICIENT
    reasons : sorted, deduplicated list of ReasonCode values (may be empty)
    """

    model_config = ConfigDict(frozen=True)

    level: SufficiencyLevel
    reasons: List[ReasonCode]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _has_recent_value(signal: Optional[PhysioSignal]) -> bool:
    return signal is not None and signal.recent_value is not None


def _has_solid_baseline(signal: Optional[PhysioSignal]) -> bool:
    """True when the signal has a baseline with >= 5 valid measures."""
    if signal is None:
        return False
    if signal.baseline is None:
        return False
    return signal.baseline.valid_measures >= _BASELINE_MIN_MEASURES


def _load_confidence_to_codes(
    confidence: str,
) -> tuple[bool, List[ReasonCode]]:
    """Map TrainingLoadSnapshot.confidence to (is_blocking, reason_codes).

    Returns
    -------
    is_blocking : True when confidence == "none" (missing_load)
    codes       : list of applicable reason codes
    """
    if confidence == "none":
        return True, [ReasonCode.missing_load]
    if confidence == "low":
        return False, [ReasonCode.thin_load_history]
    # "medium" or "high" → exploitable, no issues
    return False, []


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def build_readiness_sufficiency(
    inputs: ReadinessSufficiencyInput,
) -> ReadinessSufficiency:
    """Classify readiness data sufficiency in a fully deterministic manner.

    Parameters
    ----------
    inputs:
        Provider-neutral :class:`ReadinessSufficiencyInput` built by the caller.

    Returns
    -------
    :class:`ReadinessSufficiency` with a level and a sorted list of reason codes.
    """
    reasons: List[ReasonCode] = []

    # ------------------------------------------------------------------
    # 1. Physio signals
    # ------------------------------------------------------------------
    rhr_present = _has_recent_value(inputs.rhr)
    hrv_present = _has_recent_value(inputs.hrv)

    if not rhr_present:
        reasons.append(ReasonCode.missing_rhr)
    if not hrv_present:
        reasons.append(ReasonCode.missing_hrv)

    physio_blocking = not rhr_present and not hrv_present
    if physio_blocking:
        reasons.append(ReasonCode.missing_physio)

    # ------------------------------------------------------------------
    # 2. Sleep
    # ------------------------------------------------------------------
    sleep_missing = inputs.sleep is None
    if sleep_missing:
        reasons.append(ReasonCode.missing_sleep)

    # ------------------------------------------------------------------
    # 3. Training load
    # ------------------------------------------------------------------
    load_blocking, load_codes = _load_confidence_to_codes(inputs.load.confidence)
    reasons.extend(load_codes)

    # ------------------------------------------------------------------
    # 4. Baseline quality — only for the signal(s) actually present
    # ------------------------------------------------------------------
    rhr_baseline_thin = rhr_present and not _has_solid_baseline(inputs.rhr)
    hrv_baseline_thin = hrv_present and not _has_solid_baseline(inputs.hrv)

    if rhr_baseline_thin:
        reasons.append(ReasonCode.thin_baseline_rhr)
    if hrv_baseline_thin:
        reasons.append(ReasonCode.thin_baseline_hrv)

    # ------------------------------------------------------------------
    # 5. Determine level
    # ------------------------------------------------------------------
    # INSUFFICIENT takes priority: any blocking reason
    if physio_blocking or load_blocking:
        level = SufficiencyLevel.INSUFFICIENT
    else:
        # Check whether DEGRADED conditions apply
        degraded = False

        # Sleep missing
        if sleep_missing:
            degraded = True

        # Thin load history
        if ReasonCode.thin_load_history in reasons:
            degraded = True

        # Thin baseline of the signal(s) actually used
        # A thin baseline only causes DEGRADED when no solid alternative
        # physiological signal is available:
        #   - only one signal present and its baseline is thin → DEGRADED
        #   - both signals present but both baselines are thin  → DEGRADED
        #   - both signals present, one thin + one solid        → NOT DEGRADED
        rhr_solid = rhr_present and _has_solid_baseline(inputs.rhr)
        hrv_solid = hrv_present and _has_solid_baseline(inputs.hrv)
        physio_side_degraded = (rhr_baseline_thin or hrv_baseline_thin) and not (
            rhr_solid or hrv_solid
        )
        if physio_side_degraded:
            degraded = True

        level = SufficiencyLevel.DEGRADED if degraded else SufficiencyLevel.SUFFICIENT

    # ------------------------------------------------------------------
    # 6. Sort and deduplicate reasons for deterministic output
    # ------------------------------------------------------------------
    unique_reasons = sorted(set(reasons), key=lambda r: r.value)

    return ReadinessSufficiency(level=level, reasons=unique_reasons)
