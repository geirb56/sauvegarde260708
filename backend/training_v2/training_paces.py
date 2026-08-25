"""Training Paces V2 — VDOT-based Daniels training zones.

PR #194 — VDOT is derived exclusively from qualified performances (#188).

FORBIDDEN sources for training paces:
  - Garmin VO2max → training paces
  - VMA × 3.5 → paces
  - Old VMA HR-speed → paces
  - Race Predictions V2 outputs as shortcuts to VDOT

The Garmin VO2max is an independent informational metric and MUST NOT
alter the training paces computed here.

========================================================================
VDOT formula — Daniels/Gilbert (2004)
========================================================================

Given a qualified observed performance (distance d in meters,
duration t_s in seconds):

    v         = d / (t_s / 60)                     [m/min]
    t         = t_s / 60                            [min]
    pct_vo2   = 0.8
              + 0.1894393 × exp(−0.012778 × t)
              + 0.2989558 × exp(−0.1932605 × t)
    VO2       = −4.60 + 0.182258 × v + 0.000104 × v²
    VDOT      = VO2 / pct_vo2

Valid VDOT range: 20–85.
Below 20 or above 85 — clamped to [20, 85] before use.

========================================================================
VDOT → pace (inverse, calibrated against Daniels tables)
========================================================================

Given VDOT and target VO2 fraction f:
    target_VO2  = f × VDOT
    Solve: 0.000104 × v² + 0.182258 × v − (target_VO2 + 4.60) = 0
    v           = (−0.182258 + sqrt(0.182258² + 4 × 0.000104 × (target_VO2 + 4.60)))
                  / (2 × 0.000104)
    pace_min_km = 1000 / v

RunIndex calibration fractions (calibrated against Daniels VDOT tables;
measured tolerance ≤12 s/km across VDOT 30–70):

    E (Easy)       : [0.56, 0.68] VDOT  → RANGE [pace_faster, pace_slower]
    M (Marathon)   : 0.79 × VDOT        → SINGLE PACE
    T (Threshold)  : 0.88 × VDOT        → SINGLE PACE  (~1-hr race effort)
    I (Interval)   : [1.0, 1.0915] × VDOT  → RANGE  (5-min rep effort)
    R (Repetition) : 1.2335 × VDOT      → SINGLE PACE  (1-min rep effort)

These are RUNINDEX_DANIELS_TABLE_CALIBRATION values reproducing the official
Daniels VDOT tables via the inverse VO2-speed formula.  Fractions above 1.0
do NOT represent a physiological percentage of VO2max; they are inverse-solve
parameters that reproduce the published pace tables.

========================================================================
VDOT selection policy
========================================================================

Input: list of qualified performances from evaluate_performance_quality()
       (confidence = "high" | "medium" | "low")

Recency windows (inherited from performance_model constants):
    HIGH_DAYS   = 21
    MEDIUM_DAYS = 56
    LOW_DAYS    = 120

Selection algorithm (evaluated at reference_date):

CASE 1  — ≥2 HIGH performances, concordant (within VDOT_CONCORDANCE_BAND),
          most-recent within HIGH_DAYS:
          reference = weighted mean of concordant HIGH VDOTs
          paces_confidence = HIGH

CASE 2  — exactly 1 HIGH performance, within HIGH_DAYS:
          reference = that VDOT
          paces_confidence = MEDIUM

CASE 3  — HIGH performance stale (HIGH_DAYS < age ≤ MEDIUM_DAYS):
          reference = that VDOT (no change—staleness is expressed via LOW conf)
          paces_confidence = LOW

CASE 4  — MEDIUM performances within MEDIUM_DAYS, no recent HIGH:
          reference = recency-weighted mean of MEDIUM VDOTs
          paces_confidence = LOW

CASE 5  — all evidence older than MEDIUM_DAYS or only LOW quality:
          paces_confidence = INSUFFICIENT → no paces emitted

Concordance rule: discard any HIGH performance whose VDOT differs from
the others by more than VDOT_CONCORDANCE_BAND (5 VDOT points).
If only one remains after discarding → falls back to CASE 2.

Sudden-jump protection: a new single HIGH that raises the reference by
more than VDOT_JUMP_GUARD (5 VDOT points) vs the previous MEDIUM/LOW
evidence is treated as CASE 2 (single HIGH), NOT CASE 1.

NO-LOOKAHEAD: all calculations accept reference_date; a performance at
date > reference_date is silently excluded.

========================================================================
Readiness independence
========================================================================

Readiness can adapt a SESSION (see daily_adaptation.py) but MUST NOT
modify VDOT or the Daniels pace definitions. These are capability paces,
not prescription paces.

========================================================================
Garmin VO2max independence
========================================================================

The Garmin VO2max field is never read by this module. Training paces
are 100% derived from qualified running performances.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from datetime import date, datetime
from typing import List, Optional, Tuple, Union

from training_v2.domain_activity import DomainActivity
from training_v2.performance_model import (
    CONFIDENCE_HIGH_DAYS,
    CONFIDENCE_MEDIUM_DAYS,
    CONFIDENCE_LOW_DAYS,
    evaluate_performance_quality,
    activity_date as _activity_date,
    performance_duration_s,
)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Valid VDOT range
VDOT_MIN: float = 20.0
VDOT_MAX: float = 85.0

# Pace validity range (min/km)
PACE_MIN_MIN_KM: float = 2.0   # < 2.0 min/km = faster than any human training pace
PACE_MAX_MIN_KM: float = 16.0

# Concordance band: two HIGH VDOTs are "concordant" if they differ by at most this
VDOT_CONCORDANCE_BAND: float = 5.0

# Sudden-jump guard: a new single HIGH is promoted to CASE 2 only if it
# raises the prior reference VDOT by more than this.
VDOT_JUMP_GUARD: float = 5.0

# Daniels intensity fractions (calibrated, see module docstring)
E_FRACTION_LOW: float = 0.56    # slow end of easy range
E_FRACTION_HIGH: float = 0.68   # fast end of easy range
M_FRACTION: float = 0.79        # marathon pace
T_FRACTION: float = 0.88        # threshold / lactate threshold pace
I_FRACTION: float = 1.0915      # interval pace (5-min rep calibration)
R_FRACTION: float = 1.2335      # repetition pace (1-min rep calibration)

# Daniels/Gilbert VO2-speed polynomial coefficients
_A_VO2: float = -4.60
_B_VO2: float = 0.182258
_C_VO2: float = 0.000104

# Daniels %VO2max temporal decay coefficients
_PCT_A: float = 0.8
_PCT_B1: float = 0.1894393
_PCT_K1: float = 0.012778
_PCT_B2: float = 0.2989558
_PCT_K2: float = 0.1932605

# Minimum performance duration for VDOT calculation (90 seconds = very short TT)
MIN_VDOT_DURATION_S: float = 90.0

# Recency weights for VDOT aggregation within each confidence tier
_RECENCY_WEIGHT_RECENT: float = 1.0   # within HIGH_DAYS
_RECENCY_WEIGHT_MEDIUM: float = 0.80  # within MEDIUM_DAYS
_RECENCY_WEIGHT_OLD: float = 0.60     # within LOW_DAYS

# ---------------------------------------------------------------------------
# Data classes
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PaceValue:
    """A single training pace expressed in min/km and optionally km/h."""
    min_per_km: float   # pace in decimal minutes per km
    km_per_hour: float  # speed in km/h
    method: str = "daniels_fraction"

    @property
    def pace_str(self) -> str:
        """Return MM:SS / km string."""
        total_s = int(round(self.min_per_km * 60))
        return f"{total_s // 60}:{total_s % 60:02d}"


@dataclass(frozen=True)
class PaceRange:
    """A training pace defined as a [lower, upper] range."""
    lower: PaceValue   # faster (lower min/km value = faster pace)
    upper: PaceValue   # slower (higher min/km value = slower pace)
    method: str = "daniels_fraction"

    @property
    def lower_str(self) -> str:
        return self.lower.pace_str

    @property
    def upper_str(self) -> str:
        return self.upper.pace_str


@dataclass(frozen=True)
class VdotEvidence:
    """A single VDOT computed from one qualified performance."""
    vdot: float
    confidence: str           # "high" | "medium" | "low"
    performance_date: date
    days_old: int
    distance_m: float
    duration_s: float
    recency_weight: float


@dataclass(frozen=True)
class VdotResult:
    """VDOT reference selected from qualified performances.

    reference_vdot is None when paces_confidence == "insufficient".
    """
    reference_vdot: Optional[float]
    paces_confidence: str    # "high" | "medium" | "low" | "insufficient"
    evidence_count: int
    high_count: int
    medium_count: int
    concordant: bool
    reason: str
    evidence: Tuple[VdotEvidence, ...] = field(default_factory=tuple)


@dataclass(frozen=True)
class TrainingPaces:
    """Full Daniels training paces for a runner.

    reference_date: the snapshot date (no-lookahead).
    vdot_reference: the selected VDOT value (None if insufficient).
    confidence: HIGH | MEDIUM | LOW | INSUFFICIENT.

    E and I are PaceRange (lower bound = faster pace, upper = slower pace).
    M, T, R are PaceValue (single pace).
    """
    reference_date: date
    vdot_result: VdotResult
    confidence: str         # mirrors vdot_result.paces_confidence in uppercase

    # Pace fields — None when confidence == "insufficient"
    easy: Optional[PaceRange]
    marathon: Optional[PaceValue]
    threshold: Optional[PaceValue]
    interval: Optional[PaceRange]
    repetition: Optional[PaceValue]

    reason: str             # human-readable derivation note
    model_version: str = "v2"


# ---------------------------------------------------------------------------
# Internal: Daniels formula utilities
# ---------------------------------------------------------------------------


def _pct_vo2max(t_minutes: float) -> float:
    """Fraction of VO2max sustainable for t_minutes (Daniels/Gilbert 2004)."""
    return (
        _PCT_A
        + _PCT_B1 * math.exp(-_PCT_K1 * t_minutes)
        + _PCT_B2 * math.exp(-_PCT_K2 * t_minutes)
    )


def _vo2_at_speed(v_m_per_min: float) -> float:
    """VO2 demand (mL/kg/min) at speed v_m_per_min."""
    return _A_VO2 + _B_VO2 * v_m_per_min + _C_VO2 * v_m_per_min ** 2


def _speed_at_vo2(target_vo2: float) -> Optional[float]:
    """Speed (m/min) that demands target_vo2 mL/kg/min.

    Solves: 0.000104·v² + 0.182258·v − (target_vo2 + 4.60) = 0
    Returns None if discriminant < 0 or result is non-positive.
    """
    c_const = -(target_vo2 + abs(_A_VO2))
    discriminant = _B_VO2 ** 2 - 4 * _C_VO2 * c_const
    if discriminant < 0:
        return None
    v = (-_B_VO2 + math.sqrt(discriminant)) / (2 * _C_VO2)
    return v if v > 0 else None


def _pace_at_fraction(vdot: float, fraction: float) -> Optional[PaceValue]:
    """Compute training pace for intensity fraction of VDOT."""
    target_vo2 = vdot * fraction
    v = _speed_at_vo2(target_vo2)
    if v is None or v <= 0:
        return None
    pace_min_km = 1000.0 / v
    if not (PACE_MIN_MIN_KM <= pace_min_km <= PACE_MAX_MIN_KM):
        return None
    kmh = 60.0 / pace_min_km
    return PaceValue(min_per_km=round(pace_min_km, 4), km_per_hour=round(kmh, 2))


def vdot_from_performance(distance_m: float, duration_s: float) -> Optional[float]:
    """Compute VDOT from an observed performance (Daniels/Gilbert 2004).

    Parameters
    ----------
    distance_m:
        Race/effort distance in metres.
    duration_s:
        Race/effort duration in seconds.

    Returns
    -------
    VDOT as float, clamped to [VDOT_MIN, VDOT_MAX], or None if inputs are invalid.
    """
    if not (distance_m > 0 and duration_s >= MIN_VDOT_DURATION_S):
        return None
    t_min = duration_s / 60.0
    v_m_per_min = distance_m / t_min
    if v_m_per_min <= 0:
        return None
    pct = _pct_vo2max(t_min)
    if pct <= 0:
        return None
    vo2 = _vo2_at_speed(v_m_per_min)
    if vo2 <= 0:
        return None
    vdot = vo2 / pct
    return float(max(VDOT_MIN, min(VDOT_MAX, vdot)))


def daniels_paces(vdot: float, reference_date: date) -> TrainingPaces:
    """Compute all five Daniels training zones from a VDOT value.

    Parameters
    ----------
    vdot:
        VDOT value. Clamped to [VDOT_MIN, VDOT_MAX].
    reference_date:
        Snapshot date written into the returned TrainingPaces.
        Must be supplied explicitly — no date.today() fallback allowed
        (determinism requirement: no system date in the business layer).

    This is a pure mathematical function: no activities, no lookahead.
    Use compute_training_paces() for the full pipeline.

    Returns a TrainingPaces with a synthetic VdotResult (no evidence).
    """
    vdot = float(max(VDOT_MIN, min(VDOT_MAX, vdot)))
    vdot_result = VdotResult(
        reference_vdot=vdot,
        paces_confidence="high",
        evidence_count=1,
        high_count=1,
        medium_count=0,
        concordant=True,
        reason="direct_vdot_input",
        evidence=(),
    )
    return _build_training_paces(reference_date, vdot_result)


# ---------------------------------------------------------------------------
# Internal: VDOT evidence builder
# ---------------------------------------------------------------------------


def _recency_weight(days_old: int) -> float:
    if days_old <= CONFIDENCE_HIGH_DAYS:
        return _RECENCY_WEIGHT_RECENT
    if days_old <= CONFIDENCE_MEDIUM_DAYS:
        return _RECENCY_WEIGHT_MEDIUM
    if days_old <= CONFIDENCE_LOW_DAYS:
        return _RECENCY_WEIGHT_OLD
    return 0.0


def _collect_vdot_evidence(
    activities: List[DomainActivity],
    reference_date: date,
    user_max_hr: Optional[float] = None,
) -> List[VdotEvidence]:
    """Evaluate all activities and return VDOT evidence for qualified ones.

    No-lookahead: activities with date > reference_date are excluded.
    """
    evidence: List[VdotEvidence] = []
    for activity in activities:
        act_date = _activity_date(activity)
        if act_date is None or act_date > reference_date:
            continue

        quality = evaluate_performance_quality(
            activity, activities, reference_date, user_max_hr
        )
        if not quality.qualified:
            continue

        dur_s = performance_duration_s(activity)
        dist_m = getattr(activity, "distance_m", None)
        if dur_s is None or dist_m is None or dist_m <= 0 or dur_s < MIN_VDOT_DURATION_S:
            continue

        vdot = vdot_from_performance(dist_m, dur_s)
        if vdot is None:
            continue

        days_old = (reference_date - act_date).days
        w = _recency_weight(days_old)
        if w <= 0:
            continue

        evidence.append(VdotEvidence(
            vdot=vdot,
            confidence=quality.confidence,
            performance_date=act_date,
            days_old=days_old,
            distance_m=dist_m,
            duration_s=dur_s,
            recency_weight=w,
        ))

    return evidence


# ---------------------------------------------------------------------------
# Internal: VDOT selection policy
# ---------------------------------------------------------------------------


def _weighted_mean(items: List[Tuple[float, float]]) -> float:
    """Weighted mean of (value, weight) pairs. Assumes sum(weights) > 0."""
    total_w = sum(w for _, w in items)
    return sum(v * w for v, w in items) / total_w


def _select_vdot_reference(
    evidence: List[VdotEvidence],
    reference_date: date,
) -> VdotResult:
    """Implement the 5-case VDOT selection policy.

    Returns VdotResult with selected reference_vdot and paces_confidence.
    """
    if not evidence:
        return VdotResult(
            reference_vdot=None,
            paces_confidence="insufficient",
            evidence_count=0,
            high_count=0,
            medium_count=0,
            concordant=False,
            reason="no_qualified_evidence",
            evidence=(),
        )

    high_recent = [e for e in evidence if e.confidence == "high" and e.days_old <= CONFIDENCE_HIGH_DAYS]
    high_stale  = [e for e in evidence if e.confidence == "high" and CONFIDENCE_HIGH_DAYS < e.days_old <= CONFIDENCE_MEDIUM_DAYS]
    medium_usable = [e for e in evidence if e.confidence == "medium" and e.days_old <= CONFIDENCE_MEDIUM_DAYS]
    high_all    = high_recent + high_stale

    high_count  = len(high_all)
    medium_count = len(medium_usable)

    # ── CASE 1 / 2: Recent HIGH performances ─────────────────────────────
    if high_recent:
        vdots = sorted([e.vdot for e in high_recent])
        if len(high_recent) >= 2:
            # Concordance check: are all VDOTs within VDOT_CONCORDANCE_BAND?
            concordant = (max(vdots) - min(vdots)) <= VDOT_CONCORDANCE_BAND
            if concordant:
                # CASE 1: multiple concordant HIGH
                pairs = [(e.vdot, e.recency_weight) for e in high_recent]
                ref_vdot = _weighted_mean(pairs)

                # Sudden-jump guard: compare to medium evidence
                if medium_usable:
                    prior_pairs = [(e.vdot, e.recency_weight) for e in medium_usable]
                    prior_vdot = _weighted_mean(prior_pairs)
                    if ref_vdot - prior_vdot > VDOT_JUMP_GUARD:
                        # Suspicious single-jump → treat as MEDIUM confidence
                        return VdotResult(
                            reference_vdot=round(ref_vdot, 2),
                            paces_confidence="medium",
                            evidence_count=len(evidence),
                            high_count=high_count,
                            medium_count=medium_count,
                            concordant=True,
                            reason="case1_concordant_high_jump_guard",
                            evidence=tuple(evidence),
                        )

                return VdotResult(
                    reference_vdot=round(ref_vdot, 2),
                    paces_confidence="high",
                    evidence_count=len(evidence),
                    high_count=high_count,
                    medium_count=medium_count,
                    concordant=True,
                    reason="case1_multiple_concordant_high",
                    evidence=tuple(evidence),
                )
            else:
                # Non-concordant: discard outlier, use best recent HIGH
                median_vdot = vdots[len(vdots) // 2]
                filtered = [e for e in high_recent if abs(e.vdot - median_vdot) <= VDOT_CONCORDANCE_BAND]
                if len(filtered) >= 2:
                    pairs = [(e.vdot, e.recency_weight) for e in filtered]
                    ref_vdot = _weighted_mean(pairs)
                    return VdotResult(
                        reference_vdot=round(ref_vdot, 2),
                        paces_confidence="high",
                        evidence_count=len(evidence),
                        high_count=high_count,
                        medium_count=medium_count,
                        concordant=True,
                        reason="case1_high_outlier_removed",
                        evidence=tuple(evidence),
                    )
                else:
                    # Only one left after outlier removal → CASE 2
                    best = max(filtered or high_recent, key=lambda e: e.recency_weight)
                    return VdotResult(
                        reference_vdot=round(best.vdot, 2),
                        paces_confidence="medium",
                        evidence_count=len(evidence),
                        high_count=high_count,
                        medium_count=medium_count,
                        concordant=False,
                        reason="case2_single_high_after_outlier_removal",
                        evidence=tuple(evidence),
                    )
        else:
            # CASE 2: exactly one recent HIGH
            best = high_recent[0]
            return VdotResult(
                reference_vdot=round(best.vdot, 2),
                paces_confidence="medium",
                evidence_count=len(evidence),
                high_count=high_count,
                medium_count=medium_count,
                concordant=True,
                reason="case2_single_recent_high",
                evidence=tuple(evidence),
            )

    # ── CASE 3: Stale HIGH (no recent HIGH) ──────────────────────────────
    if high_stale:
        best = max(high_stale, key=lambda e: e.recency_weight)
        return VdotResult(
            reference_vdot=round(best.vdot, 2),
            paces_confidence="low",
            evidence_count=len(evidence),
            high_count=high_count,
            medium_count=medium_count,
            concordant=True,
            reason="case3_stale_high",
            evidence=tuple(evidence),
        )

    # ── CASE 4: MEDIUM only ──────────────────────────────────────────────
    if medium_usable:
        if len(medium_usable) >= 2:
            pairs = [(e.vdot, e.recency_weight) for e in medium_usable]
            ref_vdot = _weighted_mean(pairs)
            return VdotResult(
                reference_vdot=round(ref_vdot, 2),
                paces_confidence="low",
                evidence_count=len(evidence),
                high_count=0,
                medium_count=medium_count,
                concordant=True,
                reason="case4_medium_only_multiple",
                evidence=tuple(evidence),
            )
        else:
            best = medium_usable[0]
            return VdotResult(
                reference_vdot=round(best.vdot, 2),
                paces_confidence="low",
                evidence_count=len(evidence),
                high_count=0,
                medium_count=1,
                concordant=True,
                reason="case4_medium_only_single",
                evidence=tuple(evidence),
            )

    # ── CASE 5: all evidence too old or only LOW quality ─────────────────
    return VdotResult(
        reference_vdot=None,
        paces_confidence="insufficient",
        evidence_count=len(evidence),
        high_count=0,
        medium_count=0,
        concordant=False,
        reason="case5_no_usable_evidence",
        evidence=tuple(evidence),
    )


# ---------------------------------------------------------------------------
# Internal: pace builder
# ---------------------------------------------------------------------------


def _build_training_paces(reference_date: date, vdot_result: VdotResult) -> TrainingPaces:
    """Build TrainingPaces from a VdotResult."""
    confidence_upper = vdot_result.paces_confidence.upper()
    vdot = vdot_result.reference_vdot

    if vdot is None or vdot_result.paces_confidence == "insufficient":
        return TrainingPaces(
            reference_date=reference_date,
            vdot_result=vdot_result,
            confidence="INSUFFICIENT",
            easy=None,
            marathon=None,
            threshold=None,
            interval=None,
            repetition=None,
            reason="insufficient_evidence",
        )

    # E range: lower (faster) = E_FRACTION_HIGH, upper (slower) = E_FRACTION_LOW
    e_lower = _pace_at_fraction(vdot, E_FRACTION_HIGH)
    e_upper = _pace_at_fraction(vdot, E_FRACTION_LOW)
    easy = PaceRange(lower=e_lower, upper=e_upper) if (e_lower and e_upper) else None

    # I range: lower = I_FRACTION (faster), upper = slightly below
    i_pace = _pace_at_fraction(vdot, I_FRACTION)
    # I upper (slower end) calibrated at 5-min effort but +5% slower
    i_upper = _pace_at_fraction(vdot, I_FRACTION * 0.95)
    interval = PaceRange(lower=i_pace, upper=i_upper) if (i_pace and i_upper) else None

    marathon = _pace_at_fraction(vdot, M_FRACTION)
    threshold = _pace_at_fraction(vdot, T_FRACTION)
    repetition = _pace_at_fraction(vdot, R_FRACTION)

    reason = (
        f"vdot={vdot:.2f} confidence={vdot_result.paces_confidence} "
        f"reason={vdot_result.reason}"
    )
    return TrainingPaces(
        reference_date=reference_date,
        vdot_result=vdot_result,
        confidence=confidence_upper,
        easy=easy,
        marathon=marathon,
        threshold=threshold,
        interval=interval,
        repetition=repetition,
        reason=reason,
    )


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------


def compute_training_paces(
    activities: List[DomainActivity],
    reference_date: Union[date, datetime],
    user_max_hr: Optional[float] = None,
) -> TrainingPaces:
    """Compute V2 training paces from qualified performances.

    Parameters
    ----------
    activities:
        All DomainActivity objects for the user.  The function filters
        internally (no-lookahead, qualification gates).
    reference_date:
        Snapshot date. Activities after this date are excluded (no-lookahead).
    user_max_hr:
        Optional known FCmax (wired to None at runtime per project policy).

    Returns
    -------
    TrainingPaces with VDOT-derived Daniels zones, or TrainingPaces with
    confidence=="INSUFFICIENT" and all paces None when evidence is absent.

    Invariant: calling with any set of activities, then adding a future
    activity (date > reference_date), produces identical results (no-lookahead).
    """
    if isinstance(reference_date, datetime):
        reference_date = reference_date.date()

    evidence = _collect_vdot_evidence(activities, reference_date, user_max_hr)
    vdot_result = _select_vdot_reference(evidence, reference_date)
    return _build_training_paces(reference_date, vdot_result)


def training_paces_to_api_dict(paces: TrainingPaces) -> dict:
    """Serialize TrainingPaces to a JSON-serialisable dict for the API."""

    def pace_value_dict(p: Optional[PaceValue]) -> Optional[dict]:
        if p is None:
            return None
        return {
            "min_per_km": p.min_per_km,
            "km_per_hour": p.km_per_hour,
            "pace_str": p.pace_str,
            "method": p.method,
        }

    def pace_range_dict(r: Optional[PaceRange]) -> Optional[dict]:
        if r is None:
            return None
        return {
            "lower": pace_value_dict(r.lower),
            "upper": pace_value_dict(r.upper),
            "lower_str": r.lower_str,
            "upper_str": r.upper_str,
            "method": r.method,
        }

    vr = paces.vdot_result
    return {
        "reference_date": paces.reference_date.isoformat(),
        "confidence": paces.confidence,
        "vdot_reference": vr.reference_vdot,
        "vdot_evidence_count": vr.evidence_count,
        "vdot_high_count": vr.high_count,
        "vdot_medium_count": vr.medium_count,
        "vdot_concordant": vr.concordant,
        "vdot_reason": vr.reason,
        "paces": {
            "easy": pace_range_dict(paces.easy),
            "marathon": pace_value_dict(paces.marathon),
            "threshold": pace_value_dict(paces.threshold),
            "interval": pace_range_dict(paces.interval),
            "repetition": pace_value_dict(paces.repetition),
        },
        "reason": paces.reason,
        "model_version": paces.model_version,
    }


# ---------------------------------------------------------------------------
# Test-accessible aliases (internal policy functions)
# ---------------------------------------------------------------------------

select_vdot_reference = _select_vdot_reference  # for unit testing of policy logic
