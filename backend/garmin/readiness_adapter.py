"""R3 — Garmin/Mongo → Readiness V2 adapter boundary.

This module is the ONLY place where Garmin/MongoDB data structures are
translated into the provider-neutral Readiness V2 input contract.

Design rules
------------
- This module MAY read Garmin field names (resting_hr, hrv, sleep_hours, etc.)
  and MongoDB document shapes.
- training_v2 modules remain PURE and provider-neutral.
- No fallback neutral values: None remains None (no RHR=55, sleep=7h, etc.).
- No datetime.now() — reference_date must be supplied by the caller.
- No direct DB calls — callers pass pre-fetched document lists.

Entry-point
-----------
    build_readiness_v2_from_garmin_data(
        metrics_docs, activities, reference_date
    ) -> ReadinessResult

    metrics_docs : list of garmin_daily_metrics documents, sorted newest-first.
    activities   : list of garmin_activities documents.
    reference_date : datetime.date — anchor for load window calculations.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

from training_v2.readiness import build_readiness_result
from training_v2.readiness_signals import (
    ReadinessLoadSignal,
    compute_hrv_deviation,
    compute_rhr_deviation,
    extract_load_signal,
    extract_sleep_signal,
)
from training_v2.readiness_subscores import (
    build_load_subscore,
    build_physio_subscore,
    build_sleep_subscore,
)
from training_v2.readiness_sufficiency import (
    PhysioBaseline,
    PhysioSignal,
    ReadinessSufficiencyInput,
    SleepRecord,
    build_readiness_sufficiency,
)
from training_v2.readiness import ReadinessResult  # re-exported for callers
from training_v2.training_load import build_training_load

# ---------------------------------------------------------------------------
# Baseline thresholds (must stay aligned with R1 module)
# ---------------------------------------------------------------------------

_BASELINE_WINDOW_DAYS = 14  # look-back window for valid_measures count


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _latest_non_none(docs: List[dict], field: str) -> Optional[float]:
    """Return the most recent non-None value of *field* across docs."""
    for doc in docs:
        v = doc.get(field)
        if v is not None:
            return float(v)
    return None


def _baseline_for(
    docs: List[dict],
    field: str,
    reference_date: date,
) -> Optional[PhysioBaseline]:
    """Build a PhysioBaseline from garmin_daily_metrics documents.

    Counts valid measures within the last ``_BASELINE_WINDOW_DAYS`` calendar
    days (reference_date − 13 to reference_date inclusive = 14 days).
    Returns None when no document contains a valid value.
    """
    window_start = reference_date - timedelta(days=_BASELINE_WINDOW_DAYS - 1)
    values: List[float] = []
    valid_measures = 0
    for doc in docs:
        raw_date = doc.get("date")
        if raw_date is None:
            continue
        try:
            doc_date = date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            continue
        v = doc.get(field)
        if v is None:
            continue
        values.append(float(v))
        if window_start <= doc_date <= reference_date:
            valid_measures += 1

    if not values:
        return None

    baseline_value = sum(values) / len(values)
    return PhysioBaseline(value=baseline_value, valid_measures=valid_measures)


def _build_physio_signal(
    docs: List[dict],
    field: str,
    reference_date: date,
) -> Optional[PhysioSignal]:
    """Build a PhysioSignal for *field* (e.g. 'resting_hr' or 'hrv')."""
    recent_value = _latest_non_none(docs, field)
    if recent_value is None:
        # Signal entirely absent — return None (not a PhysioSignal with None inside)
        # so that ReadinessSufficiency can detect missing_rhr / missing_hrv.
        return None
    baseline = _baseline_for(docs, field, reference_date)
    return PhysioSignal(recent_value=recent_value, baseline=baseline)


def _build_sleep_record(docs: List[dict]) -> Optional[SleepRecord]:
    """Return the most recent SleepRecord, or None if no sleep data."""
    for doc in docs:
        duration = doc.get("sleep_hours")
        score = doc.get("sleep_score")
        if duration is not None or score is not None:
            return SleepRecord(
                duration_hours=float(duration) if duration is not None else None,
                score=float(score) if score is not None else None,
            )
    return None


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def build_readiness_v2_from_garmin_data(
    metrics_docs: List[dict],
    activities: List[dict],
    reference_date: date,
) -> ReadinessResult:
    """Build a ReadinessResult (V2) from pre-fetched Garmin/MongoDB data.

    Parameters
    ----------
    metrics_docs:
        Documents from ``garmin_daily_metrics``, sorted newest-first.
        May be empty.
    activities:
        Documents from ``garmin_activities``.  May be empty.
    reference_date:
        Anchor date for load window calculations.  Must be supplied by the
        caller; this function never calls datetime.now().

    Returns
    -------
    ReadinessResult
        Immutable final readiness result.  score is None when
        sufficiency_level == INSUFFICIENT.
    """
    # ------------------------------------------------------------------
    # 1. Build provider-neutral physio signals from garmin_daily_metrics.
    #    Garmin field names: resting_hr (RHR), hrv (HRV).
    # ------------------------------------------------------------------
    rhr_signal = _build_physio_signal(metrics_docs, "resting_hr", reference_date)
    hrv_signal = _build_physio_signal(metrics_docs, "hrv", reference_date)

    # ------------------------------------------------------------------
    # 2. Build sleep record from garmin_daily_metrics.
    #    Garmin field names: sleep_hours, sleep_score.
    # ------------------------------------------------------------------
    sleep_record = _build_sleep_record(metrics_docs)

    # ------------------------------------------------------------------
    # 3. Build TrainingLoadSnapshot from garmin_activities via V2 engine.
    #    This is the single source of truth for load; no duplication of
    #    legacy ACWR formulas.
    # ------------------------------------------------------------------
    load_snapshot = build_training_load(activities, reference_date)

    # ------------------------------------------------------------------
    # 4. R1 — Sufficiency classification.
    # ------------------------------------------------------------------
    sufficiency_input = ReadinessSufficiencyInput(
        rhr=rhr_signal,
        hrv=hrv_signal,
        sleep=sleep_record,
        load=load_snapshot,
    )
    sufficiency = build_readiness_sufficiency(sufficiency_input)

    # ------------------------------------------------------------------
    # 5. R1.6 — Signals (deviations).
    # ------------------------------------------------------------------
    rhr_delta = compute_rhr_deviation(rhr_signal)
    hrv_delta_pct = compute_hrv_deviation(hrv_signal)
    sleep_hours = extract_sleep_signal(sleep_record)
    load_signal: Optional[ReadinessLoadSignal] = extract_load_signal(load_snapshot)

    # ------------------------------------------------------------------
    # 6. R2A — Subscores.
    # ------------------------------------------------------------------
    physio_sub = build_physio_subscore(
        rhr_delta_bpm=rhr_delta,
        hrv_delta_percent=hrv_delta_pct,
    )
    sleep_sub = build_sleep_subscore(sleep_duration_hours=sleep_hours)
    load_sub = build_load_subscore(load_signal=load_signal)

    # ------------------------------------------------------------------
    # 7. R2B — Final aggregation.
    # ------------------------------------------------------------------
    return build_readiness_result(
        sufficiency=sufficiency,
        physio=physio_sub,
        sleep=sleep_sub,
        load=load_sub,
    )
