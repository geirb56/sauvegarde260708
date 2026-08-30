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
        metrics_docs, activities, reference_date,
        load_snapshot=None,
    ) -> ReadinessResult

    metrics_docs   : list of garmin_daily_metrics documents, sorted newest-first.
    activities     : list of garmin_activities documents.
    reference_date : datetime.date — anchor for load window calculations.
    load_snapshot  : optional pre-built TrainingLoadSnapshot.  When supplied the
                     adapter uses it directly and skips calling build_training_load(),
                     so the /run-index path can share a single snapshot with the
                     Dashboard metrics without a duplicate computation.
"""

from __future__ import annotations

from datetime import date, timedelta
from typing import List, Optional

# ---------------------------------------------------------------------------
# Staleness limit for physio signals (RHR, HRV, sleep).
# A daily-metrics document older than this many days relative to reference_date
# is NEVER used as the "current" reading; it would be stale data presented as
# today's measurement.
# ---------------------------------------------------------------------------
_MAX_PHYSIO_STALENESS_DAYS = 7

from training_v2.readiness import build_readiness_result, ReadinessResult
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

from training_v2.training_load import build_training_load, TrainingLoadSnapshot

# ---------------------------------------------------------------------------
# Baseline thresholds (must stay aligned with R1 module)
# ---------------------------------------------------------------------------

_BASELINE_WINDOW_DAYS = 14  # look-back window for valid_measures count


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _latest_doc_with(
    docs: List[dict],
    field: str,
    reference_date: Optional[date] = None,
) -> Optional[dict]:
    """Return the most recent document that has a non-None value for *field*.

    When *reference_date* is supplied, only documents whose ``date`` field is
    within the last ``_MAX_PHYSIO_STALENESS_DAYS`` days are considered.  A
    document without a parseable ``date`` is always excluded when
    *reference_date* is provided so that undated records are never silently
    treated as current.
    """
    cutoff: Optional[date] = None
    if reference_date is not None:
        cutoff = reference_date - timedelta(days=_MAX_PHYSIO_STALENESS_DAYS)

    for doc in docs:
        if doc.get(field) is None:
            continue
        if cutoff is not None:
            raw_date = doc.get("date")
            if raw_date is None:
                continue
            try:
                doc_date = date.fromisoformat(str(raw_date)[:10])
            except ValueError:
                continue
            if doc_date < cutoff or doc_date > reference_date:
                continue
        return doc
    return None


def _baseline_for(
    docs: List[dict],
    field: str,
    recent_date: date,
) -> Optional[PhysioBaseline]:
    """Build a PhysioBaseline from garmin_daily_metrics documents.

    Baseline window: recent_date − ``_BASELINE_WINDOW_DAYS`` days up to
    recent_date − 1 day (inclusive).  The measurement at *recent_date* itself
    is intentionally excluded so that a very abnormal day cannot distort its
    own reference.

    ``valid_measures`` is the exact count of documents with a non-None value
    for *field* that fall within that window — no document outside the window
    is ever counted.

    Returns None when no prior document contains a valid value.
    """
    window_end = recent_date - timedelta(days=1)
    window_start = recent_date - timedelta(days=_BASELINE_WINDOW_DAYS)

    values: List[float] = []
    for doc in docs:
        raw_date = doc.get("date")
        if raw_date is None:
            continue
        try:
            doc_date = date.fromisoformat(str(raw_date)[:10])
        except ValueError:
            continue
        if not (window_start <= doc_date <= window_end):
            continue
        v = doc.get(field)
        if v is None:
            continue
        values.append(float(v))

    if not values:
        return None

    baseline_value = sum(values) / len(values)
    return PhysioBaseline(value=baseline_value, valid_measures=len(values))


def _build_physio_signal(
    docs: List[dict],
    field: str,
    reference_date: date,
) -> Optional[PhysioSignal]:
    """Build a PhysioSignal for *field* (e.g. 'resting_hr' or 'hrv').

    recent_value is taken from the most recent document that has a non-None
    value for *field* and whose date is within ``_MAX_PHYSIO_STALENESS_DAYS``
    of *reference_date*.  A document older than that window is silently treated
    as absent — stale data is never presented as current.

    The baseline is computed only from documents whose date strictly precedes
    recent_date (within the 14-day window), so that the recent measurement
    never inflates its own reference.
    """
    recent_doc = _latest_doc_with(docs, field, reference_date)
    if recent_doc is None:
        # Signal entirely absent — return None so ReadinessSufficiency can
        # detect missing_rhr / missing_hrv.
        return None
    recent_value = float(recent_doc[field])
    try:
        recent_date = date.fromisoformat(str(recent_doc.get("date", ""))[:10])
    except ValueError:
        # Malformed date on the most recent doc — fall back to reference_date
        # so the window anchor is still meaningful.
        recent_date = reference_date
    baseline = _baseline_for(docs, field, recent_date)
    return PhysioSignal(recent_value=recent_value, baseline=baseline)


def _build_sleep_record(
    docs: List[dict],
    reference_date: Optional[date] = None,
) -> Optional[SleepRecord]:
    """Return the most recent SleepRecord within the staleness window, or None.

    When *reference_date* is supplied, only documents dated within
    ``_MAX_PHYSIO_STALENESS_DAYS`` of *reference_date* are considered.  A
    sleep record older than that window is treated as absent — it must not be
    silently used as "last night's" sleep.
    """
    cutoff: Optional[date] = None
    if reference_date is not None:
        cutoff = reference_date - timedelta(days=_MAX_PHYSIO_STALENESS_DAYS)

    for doc in docs:
        duration = doc.get("sleep_hours")
        score = doc.get("sleep_score")
        if duration is None and score is None:
            continue
        if cutoff is not None:
            raw_date = doc.get("date")
            if raw_date is None:
                continue
            try:
                doc_date = date.fromisoformat(str(raw_date)[:10])
            except ValueError:
                continue
            if doc_date < cutoff or doc_date > reference_date:
                continue
        return SleepRecord(
            duration_hours=float(duration) if duration is not None else None,
            score=float(score) if score is not None else None,
        )
    return None


# ---------------------------------------------------------------------------
# Public helpers
# ---------------------------------------------------------------------------


def get_rhr_v2_baseline(
    metrics_docs: List[dict],
    reference_date: date,
) -> Optional[float]:
    """Return the RHR baseline value used by Readiness V2.

    Delegates to the same ``_baseline_for`` / ``_build_physio_signal`` logic
    used internally, so the value returned here is identical to the one used
    when building a ReadinessResult.  Returns None when no prior documents
    with a valid ``resting_hr`` exist within the 14-day window.

    Callers (e.g. compute_run_index) must use this function as the single
    source of truth for the displayed ``rhr_baseline`` and ``rhr_delta`` so
    that the Dashboard and Readiness V2 always agree.
    """
    signal = _build_physio_signal(metrics_docs, "resting_hr", reference_date)
    if signal is None or signal.baseline is None:
        return None
    return signal.baseline.value


# ---------------------------------------------------------------------------
# Public entry-point
# ---------------------------------------------------------------------------


def build_readiness_v2_from_garmin_data(
    metrics_docs: List[dict],
    activities: List[dict],
    reference_date: date,
    load_snapshot: Optional[TrainingLoadSnapshot] = None,
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
    load_snapshot:
        Optional pre-built :class:`TrainingLoadSnapshot`.  When supplied the
        function uses it directly instead of calling :func:`build_training_load`,
        so the /run-index path can share a single V2 snapshot across both the
        Dashboard metrics and Readiness V2 without a second computation.

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
    sleep_record = _build_sleep_record(metrics_docs, reference_date)

    # ------------------------------------------------------------------
    # 3. TrainingLoadSnapshot — use the caller-supplied one when available
    #    so that /run-index computes load only once and shares it with
    #    Readiness V2.  Fall back to build_training_load() when not given.
    # ------------------------------------------------------------------
    if load_snapshot is None:
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
