"""Compute the Dashboard 'run-index' payload from REAL Garmin data.

Replaces the static _CARDIO_COACH_MOCK_DATA: resting HR + sleep come from
gccli (`garmin_daily_metrics`), and training load / ACWR / fatigue ratio /
readiness are COMPUTED from the real synced activities (`garmin_activities`).

HRV is not available on every Garmin device/account; when it is missing the
fatigue model gracefully reweights to resting HR + sleep + load (no HRV term),
and the HRV fields are returned as null so the UI shows "—".

The returned dict matches the shape the existing /api/run-index endpoint and
the Dashboard frontend expect.

``TrainingLoadSnapshot`` (V2) is the SINGLE SOURCE OF TRUTH for all load
metrics in the /run-index path:
- ``build_training_load()`` is called exactly once per request.
- The resulting snapshot is shared with Readiness V2 (no second computation).
- ``metrics.training_load_v2`` exposes the V2 snapshot for observability.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timedelta, timezone
from typing import List, Optional

from garmin.readiness_adapter import (
    _CURRENT_SIGNAL_MAX_AGE_DAYS,
    build_readiness_v2_from_garmin_data,
    get_rhr_v2_baseline,
)
from training_v2.training_load import build_training_load

logger = logging.getLogger(__name__)

_DAY_ABBREVS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]

# Map V2 ACWR status labels to Dashboard colour tokens.
_ACWR_STATUS_COLOR: dict = {
    "balanced": "green",
    "elevated": "yellow",
    "high": "red",
    "low": "yellow",
    "very_low": "yellow",
    "unavailable": "gray",
}


def _acwr_status_to_color(status: str) -> str:
    return _ACWR_STATUS_COLOR.get(status, "gray")


def _parse_day(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10])
    except ValueError:
        return None


def _mean(values: List[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _latest_with(
    metrics_docs: List[dict],
    key: str,
    reference_date: Optional[date] = None,
) -> Optional[dict]:
    """Return the most recent metrics doc whose `key` is a real (non-null) value.

    metrics_docs is sorted newest-first.  When *reference_date* is supplied,
    only documents dated within ``_CURRENT_SIGNAL_MAX_AGE_DAYS`` of
    *reference_date* are considered.  A doc whose date cannot be parsed, or
    that is older than the staleness window, is silently skipped — stale data
    must never be presented as a current measurement.
    """
    cutoff: Optional[date] = None
    if reference_date is not None:
        cutoff = reference_date - timedelta(days=_CURRENT_SIGNAL_MAX_AGE_DAYS)

    for doc in metrics_docs:
        if doc.get(key) is None:
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


async def compute_run_index(
    db,
    user_id: str,
    language: str = "fr",
    reference_date=None,
) -> Optional[dict]:
    """Build the run-index payload from real Garmin data, or None if no data.

    Parameters
    ----------
    db:
        Async database handle with garmin_daily_metrics and garmin_activities.
    user_id:
        User whose data to fetch.
    language:
        i18n locale key (``"fr"``, ``"en"``, ``"es"``).  Defaults to ``"fr"``.
    reference_date:
        Anchor date for all time-windowed calculations (load, sufficiency,
        history).  When *None* the current UTC date is used.  Pass an explicit
        :class:`datetime.date` in tests to make them deterministic.
    """
    lang = (language or "fr").lower()
    # --- Daily health metrics (most recent first) ---
    metrics_docs = await (
        db.garmin_daily_metrics.find({"user_id": user_id}, {"_id": 0})
        .sort("date", -1)
        .limit(30)
        .to_list(length=30)
    )
    activities = await (
        db.garmin_activities.find({"user_id": user_id}, {"_id": 0})
        .sort("start_time", -1)
        .limit(200)
        .to_list(length=200)
    )
    conn_doc = await db.garmin_connections.find_one(
        {"user_id": user_id},
        {"_id": 0, "garmin_capabilities.has_hrv": 1},
    )
    hrv_supported = None
    if isinstance(conn_doc, dict):
        caps = conn_doc.get("garmin_capabilities") or {}
        if isinstance(caps, dict) and "has_hrv" in caps:
            hrv_supported = bool(caps.get("has_hrv"))

    # --- Native Garmin VO₂max ---
    # Fetched from gccli health max-metrics during sync and stored in garmin_vo2max.
    # Select the most recent valid point by measurement date (sparse history).
    vo2max_doc = await db.garmin_vo2max.find_one(
        {"user_id": user_id, "vo2max_running": {"$ne": None}},
        {"_id": 0, "vo2max_running": 1, "vo2max_running_precise": 1, "date": 1},
        sort=[("date", -1)],
    )
    vo2max_running: Optional[float] = (vo2max_doc or {}).get("vo2max_running")
    vo2max_running_precise: Optional[float] = (vo2max_doc or {}).get("vo2max_running_precise")
    vo2max_date: Optional[str] = (vo2max_doc or {}).get("date")

    if not metrics_docs and not activities:
        return None

    today = reference_date if reference_date is not None else datetime.now(timezone.utc).date()

    # Use the most RECENT REAL (non-null) reading per metric within the
    # staleness window.  A device value from >7 days ago is treated as absent.
    hrv_doc = _latest_with(metrics_docs, "hrv", today)
    rhr_doc = _latest_with(metrics_docs, "resting_hr", today)
    sleep_doc = _latest_with(metrics_docs, "sleep_hours", today)

    hrv_today = hrv_doc.get("hrv") if hrv_doc else None
    rhr_today = rhr_doc.get("resting_hr") if rhr_doc else None
    sleep_hours = sleep_doc.get("sleep_hours") if sleep_doc else None
    sleep_score_raw = (sleep_doc.get("sleep_score") if sleep_doc else None)  # 0-100 or None

    have_hrv = hrv_today is not None
    have_rhr = rhr_today is not None

    # --- Baselines (rolling mean over available history) ---
    hrv_baseline = _mean([d.get("hrv") for d in metrics_docs]) if have_hrv else None
    # rhr_baseline: single source of truth aligned with Readiness V2 (14-day window,
    # excludes today, no fictitious fallback — None remains None when no prior data).
    rhr_baseline = get_rhr_v2_baseline(metrics_docs, today)
    if hrv_baseline is None and have_hrv:
        hrv_baseline = hrv_today

    # Sleep efficiency derived from sleep score when present; None when absent.
    # No fabricated default — absent sleep data stays absent (None ≠ 0).
    if sleep_score_raw is not None:
        sleep_efficiency: Optional[float] = sleep_score_raw / 100.0 if sleep_score_raw > 1.0 else float(sleep_score_raw)
    else:
        sleep_efficiency = None
    sleep_hours_val: Optional[float] = sleep_hours

    # --- Training Load V2 — single source of truth (R3.5) ---
    # build_training_load() is called exactly once; the snapshot is shared
    # with Readiness V2 via the load_snapshot kwarg so there is no second
    # computation and no divergence between Dashboard and Readiness.
    load_snapshot = build_training_load(activities, today)
    acwr: Optional[float] = load_snapshot.acwr

    # --- Fatigue model (reweight when HRV is missing) ---
    hrv_delta = (float(hrv_baseline) - float(hrv_today)) if (have_hrv and hrv_baseline is not None) else None
    # rhr_delta for display: None when rhr_today or rhr_baseline unavailable (no fictitious fallback).
    rhr_delta: Optional[float] = (
        float(rhr_today) - float(rhr_baseline)
        if (have_rhr and rhr_baseline is not None)
        else None
    )
    # sleep_penalty: only computed from real device data; None when sleep is absent.
    # Hours term (max(0, 8 - h)) is computed whenever hours are available.
    # Efficiency term is added only when sleep_score is present; when absent the
    # term is zero (i.e. the efficiency component is omitted entirely — no invented
    # neutral value, just hours-only penalty).
    if sleep_hours_val is not None:
        hours_penalty = max(0.0, 8.0 - sleep_hours_val)
        # When sleep_efficiency is None the device did not report a sleep score;
        # we omit the efficiency component (0.0 contribution) rather than assuming
        # any particular efficiency level.
        eff_penalty = (1.0 - sleep_efficiency) * 2.0 if sleep_efficiency is not None else 0.0
        sleep_penalty: Optional[float] = hours_penalty + eff_penalty
    else:
        sleep_penalty = None

    # --- Run Readiness V2 ---
    _v2_result = build_readiness_v2_from_garmin_data(
        metrics_docs,
        activities,
        today,
        load_snapshot=load_snapshot,
        hrv_supported=hrv_supported,
    )
    run_readiness_v2: Optional[float] = _v2_result.score
    readiness_v2_confidence: str = _v2_result.confidence.value
    readiness_v2_sufficiency: str = _v2_result.sufficiency_level.value
    readiness_v2_reasons: list = [r.value for r in _v2_result.reasons]

    run_readiness = run_readiness_v2

    # --- Recommendation derived from readiness (number & badge always agree) ---
    # When run_readiness is None (INSUFFICIENT) the state is UNAVAILABLE — not
    # a training recommendation.  None must NEVER map to REST/EASY RUN/RUN HARD.
    if run_readiness is not None and run_readiness >= 75:
        recommendation, rec_emoji, rec_color = "RUN HARD", "🟢", "green"
    elif run_readiness is not None and run_readiness >= 55:
        recommendation, rec_emoji, rec_color = "EASY RUN", "🟡", "yellow"
    elif run_readiness is not None:
        recommendation, rec_emoji, rec_color = "REST", "🔴", "red"
    else:
        recommendation, rec_emoji, rec_color = "UNAVAILABLE", "⚪", "gray"
    readiness_status = rec_color

    # Localize the user-facing labels (fr default / es / en).
    _REC_I18N = {
        "RUN HARD": {"fr": "SÉANCE INTENSE", "es": "ENTRENO INTENSO"},
        "EASY RUN": {"fr": "FOOTING FACILE", "es": "CARRERA SUAVE"},
        "REST": {"fr": "REPOS", "es": "DESCANSO"},
        "UNAVAILABLE": {"fr": "INDISPONIBLE", "es": "NO DISPONIBLE"},
    }
    if lang != "en":
        recommendation = _REC_I18N.get(recommendation, {}).get(lang, recommendation)

    # --- Statuses ---
    hrv_status = "green"
    if hrv_delta is not None:
        hrv_status = "green" if hrv_delta <= 5 else ("yellow" if hrv_delta <= 10 else "red")
    rhr_status = (
        "gray" if rhr_delta is None
        else ("green" if rhr_delta <= 3 else ("yellow" if rhr_delta <= 7 else "red"))
    )
    sleep_status = (
        "gray"
        if sleep_penalty is None
        else ("green" if sleep_penalty <= 1.0 else ("yellow" if sleep_penalty <= 2.5 else "red"))
    )
    # Load status is derived from the V2 snapshot status label (no fallback colour).
    load_status = _acwr_status_to_color(load_snapshot.status)

    # --- Reasons (omit HRV when unavailable) — localized ---
    reasons = []
    if hrv_delta is not None:
        sign = "+" if hrv_delta >= 0 else ""
        _t = {"fr": f"Écart VFC {sign}{hrv_delta:.1f} ms vs référence",
              "es": f"Desviación VFC {sign}{hrv_delta:.1f} ms vs referencia",
              "en": f"HRV deviation {sign}{hrv_delta:.1f} ms vs baseline"}
        reasons.append(_t.get(lang, _t["fr"]))
    else:
        _t = {"fr": "VFC non enregistrée par votre appareil Garmin",
              "es": "VFC no registrada por tu dispositivo Garmin",
              "en": "HRV not recorded by your Garmin device"}
        reasons.append(_t.get(lang, _t["fr"]))
    if have_rhr and rhr_delta is not None:
        sign = "+" if rhr_delta >= 0 else ""
        _t = {"fr": f"FC de repos {sign}{rhr_delta:.1f} bpm vs référence ({rhr_today:.0f} bpm)",
              "es": f"FC en reposo {sign}{rhr_delta:.1f} bpm vs referencia ({rhr_today:.0f} bpm)",
              "en": f"RHR {sign}{rhr_delta:.1f} bpm vs baseline ({rhr_today:.0f} bpm)"}
        reasons.append(_t.get(lang, _t["fr"]))
    if sleep_hours_val is not None:
        _t = {"fr": f"Sommeil {sleep_hours_val:.1f} h", "es": f"Sueño {sleep_hours_val:.1f} h",
              "en": f"Sleep {sleep_hours_val:.1f} h"}
        reasons.append(_t.get(lang, _t["fr"]))
    else:
        _t = {"fr": "Données sommeil absentes", "es": "Datos de sueño ausentes",
              "en": "Sleep data absent"}
        reasons.append(_t.get(lang, _t["fr"]))
    if acwr is not None:
        _t = {"fr": f"Charge d'entraînement (ACWR) {acwr:.2f}",
              "es": f"Carga de entrenamiento (ACWR) {acwr:.2f}",
              "en": f"Training Load (ACWR) {acwr:.2f}"}
    else:
        _t = {"fr": "Charge d'entraînement (ACWR) indisponible",
              "es": "Carga de entrenamiento (ACWR) no disponible",
              "en": "Training Load (ACWR) unavailable"}
    reasons.append(_t.get(lang, _t["fr"]))

    # --- 30-day history (oldest -> newest) — run_readiness = Readiness V2 ---
    # For each historical day J:
    #   - metrics filtered to date <= J (newest-first, no future leakage)
    #   - activities filtered to start_time <= J (no future leakage)
    #   - Readiness V2 built with reference_date=J
    #   - training_load = build_training_load(hist_activities, J).acwr (V2, None when unavailable)
    #   - score = float 0–100 or None (INSUFFICIENT → None, never a fallback)
    recent = list(reversed(metrics_docs[:30]))
    history = []
    for doc in recent:
        d = _parse_day(doc.get("date", ""))
        if d is None:
            # Skip docs with no parseable date — no anchor to filter future data.
            continue
        day_label = _DAY_ABBREVS[d.weekday()]
        doc_hrv = doc.get("hrv")

        # run_readiness V2: only data available at day J, no legacy fallbacks.
        hist_day = d.date()
        # Metrics available at J: date field must be present, valid, and <= J.
        # Absent or invalid dates are excluded (never assumed available).
        hist_metrics = []
        for m in metrics_docs:
            raw = m.get("date")
            parsed = _parse_day(raw) if raw is not None else None
            if parsed is not None and parsed.date() <= hist_day:
                hist_metrics.append(m)
        # Activities available at J: start_time date must be valid and <= J.
        # Absent or unparseable start_time → excluded.
        hist_activities = []
        for a in activities:
            act_dt = _parse_day(a.get("start_time") or a.get("synced_at") or "")
            if act_dt is not None and act_dt.date() <= hist_day:
                hist_activities.append(a)
        hist_v2 = build_readiness_v2_from_garmin_data(
            hist_metrics,
            hist_activities,
            hist_day,
            hrv_supported=hrv_supported,
        )
        doc_readiness: Optional[float] = hist_v2.score  # float 0–100 or None
        hist_load_snapshot = build_training_load(hist_activities, hist_day)
        doc_training_load: Optional[float] = hist_load_snapshot.acwr

        history.append({
            "day": day_label,
            "date": doc.get("date"),
            "hrv": round(float(doc_hrv), 1) if doc_hrv is not None else None,
            "training_load": round(doc_training_load, 3) if doc_training_load is not None else None,
            "run_readiness": doc_readiness,
        })

    return {
        "mock": False,
        "source": "garmin",
        "recommendation": recommendation,
        "recommendation_emoji": rec_emoji,
        "recommendation_color": rec_color,
        "reasons": reasons,
        "metrics": {
            "hrv_today": round(float(hrv_today), 1) if have_hrv else None,
            "hrv_baseline": round(float(hrv_baseline), 1) if (have_hrv and hrv_baseline is not None) else None,
            "hrv_delta": round(hrv_delta, 1) if hrv_delta is not None else None,
            "hrv_status": hrv_status,
            "hrv_available": have_hrv,
            "rhr_today": round(float(rhr_today), 1) if have_rhr else None,
            "rhr_baseline": round(float(rhr_baseline), 1) if rhr_baseline is not None else None,
            "rhr_delta": round(rhr_delta, 1) if rhr_delta is not None else None,
            "rhr_status": rhr_status,
            "sleep_hours": round(sleep_hours_val, 1) if sleep_hours_val is not None else None,
            "sleep_efficiency": round(sleep_efficiency, 2) if sleep_efficiency is not None else None,
            "sleep_score": round(sleep_penalty, 2) if sleep_penalty is not None else None,
            "sleep_status": sleep_status,
            # training_load now mirrors snapshot.acwr (Optional); frontend must
            # accept null (no chronic load = unavailable, never a fake 1.0).
            "training_load": round(acwr, 3) if acwr is not None else None,
            "training_load_status": load_status,
            "run_readiness": run_readiness,  # float or None (INSUFFICIENT)
            "run_readiness_status": readiness_status,
            "confidence": readiness_v2_confidence,
            "sufficiency_level": readiness_v2_sufficiency,
            "readiness_reasons": readiness_v2_reasons,
            "training_load_v2": {
                "acute_load_7d": load_snapshot.acute_load_7d,
                "load_28d": load_snapshot.load_28d,
                "chronic_weekly_load": load_snapshot.chronic_weekly_load,
                "previous_7d_load": load_snapshot.previous_7d_load,
                "load_change_percent": load_snapshot.load_change_percent,
                "acwr": load_snapshot.acwr,
                "status": load_snapshot.status,
                "confidence": load_snapshot.confidence,
            },
            # Native Garmin running VO₂max.  None when the device does
            # not produce this metric or before the first sync with max-metrics.
            "vo2max_running": vo2max_running,
            "vo2max_running_precise": vo2max_running_precise,
            "vo2max_date": vo2max_date,
        },
        "history": history,
    }
