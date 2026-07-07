"""Compute the Dashboard 'cardio-coach' payload from REAL Garmin data.

Replaces the static _CARDIO_COACH_MOCK_DATA: resting HR + sleep come from
gccli (`garmin_daily_metrics`), and training load / ACWR / fatigue ratio /
readiness are COMPUTED from the real synced activities (`garmin_activities`).

HRV is not available on every Garmin device/account; when it is missing the
fatigue model gracefully reweights to resting HR + sleep + load (no HRV term),
and the HRV fields are returned as null so the UI shows "—".

The returned dict matches the shape the existing /api/cardio-coach endpoint and
the Dashboard frontend expect.
"""

from __future__ import annotations

import logging
from datetime import datetime, timedelta, timezone
from typing import List, Optional

logger = logging.getLogger(__name__)

_DAY_ABBREVS = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]


def _parse_day(value: str) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:10])
    except ValueError:
        return None


def _activity_load(act: dict) -> float:
    """Training load proxy = session duration in minutes (TRIMP-like).

    Falls back to an estimate from distance (~6 min/km) when duration is absent.
    """
    duration_s = act.get("duration") or 0
    if duration_s:
        return float(duration_s) / 60.0
    distance_m = act.get("distance") or 0
    if distance_m:
        return (float(distance_m) / 1000.0) * 6.0
    return 0.0


def _compute_acwr(activities: List[dict], today) -> float:
    """Acute:Chronic Workload Ratio from real activities (7d vs 28d daily avg)."""
    return compute_load_metrics(activities, today)["acwr_raw"]


def compute_load_metrics(activities: List[dict], today) -> dict:
    """Duration-based training-load metrics — SINGLE SOURCE OF TRUTH.

    Used by both the Dashboard (/cardio-coach) and the Training page
    (/training/metrics) so ACWR and TSB are identical across the app.
    Load proxy = session duration (TRIMP-like) via _activity_load().
    """
    acute = 0.0
    chronic = 0.0
    for act in activities:
        d = _parse_day(act.get("start_time") or act.get("synced_at") or "")
        if not d:
            continue
        days_ago = (today - d.date()).days
        if days_ago < 0:
            continue
        load = _activity_load(act)
        if days_ago < 28:
            chronic += load
        if days_ago < 7:
            acute += load
    acute_avg = acute / 7.0
    chronic_avg = chronic / 28.0
    acwr_raw = (acute_avg / chronic_avg) if chronic_avg > 0 else 1.0
    ctl = chronic / 4.0   # chronic base (weekly-average load)
    atl = acute           # acute fatigue (current week load)
    return {
        "acute": round(acute, 1),
        "chronic": round(chronic, 1),
        "acwr_raw": acwr_raw,
        "acwr": round(acwr_raw, 2),
        "ctl": round(ctl, 1),
        "atl": round(atl, 1),
        "tsb": round(ctl - atl, 1),
    }


async def compute_training_load_metrics(db, user_id: str) -> Optional[dict]:
    """Fetch the user's real Garmin activities and return duration-based
    load metrics (ACWR, CTL, ATL, TSB). Returns None when no activities."""
    activities = await (
        db.garmin_activities.find({"user_id": user_id}, {"_id": 0})
        .sort("start_time", -1)
        .limit(200)
        .to_list(length=200)
    )
    if not activities:
        return None
    today = datetime.now(timezone.utc).date()
    return compute_load_metrics(activities, today)


def _mean(values: List[float]) -> Optional[float]:
    vals = [v for v in values if v is not None]
    if not vals:
        return None
    return sum(vals) / len(vals)


def _latest_with(metrics_docs: List[dict], key: str) -> Optional[dict]:
    """Return the most recent metrics doc whose `key` is a real (non-null) value.

    metrics_docs is sorted newest-first. This guarantees a REAL device value
    (e.g. HRV) is used whenever the device actually reported one, instead of
    falling back to the degraded model just because the very latest day is empty.
    """
    for doc in metrics_docs:
        if doc.get(key) is not None:
            return doc
    return None


async def compute_cardio_coach(db, user_id: str, language: str = "fr") -> Optional[dict]:
    """Build the cardio-coach payload from real Garmin data, or None if no data."""
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

    if not metrics_docs and not activities:
        return None

    today = datetime.now(timezone.utc).date()

    # Use the most RECENT REAL (non-null) reading per metric. If the device
    # actually reported HRV, that real value is used (never recomputed/faked).
    hrv_doc = _latest_with(metrics_docs, "hrv")
    rhr_doc = _latest_with(metrics_docs, "resting_hr")
    sleep_doc = _latest_with(metrics_docs, "sleep_hours")

    hrv_today = hrv_doc.get("hrv") if hrv_doc else None
    rhr_today = rhr_doc.get("resting_hr") if rhr_doc else None
    sleep_hours = sleep_doc.get("sleep_hours") if sleep_doc else None
    sleep_score_raw = (sleep_doc.get("sleep_score") if sleep_doc else None)  # 0-100 or None

    have_hrv = hrv_today is not None
    have_rhr = rhr_today is not None

    # --- Baselines (rolling mean over available history) ---
    hrv_baseline = _mean([d.get("hrv") for d in metrics_docs]) if have_hrv else None
    rhr_baseline = _mean([d.get("resting_hr") for d in metrics_docs])
    if rhr_baseline is None:
        rhr_baseline = rhr_today if have_rhr else 55.0
    if hrv_baseline is None and have_hrv:
        hrv_baseline = hrv_today

    # Sleep efficiency derived from sleep score when present, else a neutral default.
    if sleep_score_raw is not None:
        sleep_efficiency = sleep_score_raw / 100.0 if sleep_score_raw > 1.0 else float(sleep_score_raw)
    else:
        sleep_efficiency = 0.85
    sleep_hours_val = sleep_hours if sleep_hours is not None else 7.0

    # --- Training load / ACWR from real activities ---
    acwr = _compute_acwr(activities, today)
    training_load = max(0.1, acwr)

    # --- Fatigue model (reweight when HRV is missing) ---
    hrv_delta = (float(hrv_baseline) - float(hrv_today)) if (have_hrv and hrv_baseline is not None) else None
    rhr_delta = (float(rhr_today) - float(rhr_baseline)) if have_rhr else 0.0
    sleep_penalty = max(0.0, 8.0 - sleep_hours_val) + (1.0 - sleep_efficiency) * 2.0

    if have_hrv:
        w_hrv, w_rhr, w_sleep = 0.5, 0.3, 0.2
        hrv_term = w_hrv * (hrv_delta or 0.0)
    else:
        w_hrv, w_rhr, w_sleep = 0.0, 0.6, 0.4
        hrv_term = 0.0
    fatigue_physio = hrv_term + w_rhr * rhr_delta + w_sleep * sleep_penalty
    # Fatigue cannot be negative; a very fresh state is simply 0.
    fatigue_physio = max(0.0, fatigue_physio)
    # Fatigue Ratio = physiological fatigue only (RHR/HRV/sleep), centred on 1.0.
    # NOT divided by ACWR: training load is shown separately. Higher = more fatigued.
    # 1.0 fresh · ~1.2 moderate · >1.5 high.
    fatigue_ratio = 1.0 + fatigue_physio / 10.0

    # --- Run Readiness (SINGLE SOURCE OF TRUTH, computed backend-side) ---
    # Score 0-100. Two penalties subtracted from a fresh baseline of 100:
    #  1. Physiological fatigue (RHR/HRV/sleep). Works WITH OR WITHOUT HRV
    #     because fatigue_physio already reweights when HRV is unavailable
    #     (many Garmin devices do not record HRV).
    #  2. ACWR load risk, penalised on BOTH sides of the optimal 0.8-1.3 zone:
    #     overload (>1.3) penalised steeply, detraining (<0.8) penalised mildly.
    physio_penalty = min(60.0, fatigue_physio * 6.0)
    if acwr > 1.3:
        acwr_penalty = min(60.0, (acwr - 1.3) * 130.0)
    elif acwr < 0.8:
        acwr_penalty = min(30.0, (0.8 - acwr) * 60.0)
    else:
        acwr_penalty = 0.0
    run_readiness = int(round(max(5.0, min(100.0, 100.0 - physio_penalty - acwr_penalty))))

    # --- Recommendation derived from readiness (number & badge always agree) ---
    if run_readiness >= 75:
        recommendation, rec_emoji, rec_color = "RUN HARD", "🟢", "green"
        nw_label, nw_icon = "Intervals – 6 x 800 m", "run"
    elif run_readiness >= 55:
        recommendation, rec_emoji, rec_color = "EASY RUN", "🟡", "yellow"
        nw_label, nw_icon = "Easy Run – 45 min Z2", "run"
    else:
        recommendation, rec_emoji, rec_color = "REST", "🔴", "red"
        nw_label, nw_icon = "Rest Day", "rest"
    readiness_status = rec_color

    # Localize the user-facing labels (fr default / es / en).
    _REC_I18N = {
        "RUN HARD": {"fr": "SÉANCE INTENSE", "es": "ENTRENO INTENSO"},
        "EASY RUN": {"fr": "FOOTING FACILE", "es": "CARRERA SUAVE"},
        "REST": {"fr": "REPOS", "es": "DESCANSO"},
    }
    _NW_I18N = {
        "Intervals – 6 x 800 m": {"fr": "Fractionné – 6 x 800 m", "es": "Series – 6 x 800 m"},
        "Easy Run – 45 min Z2": {"fr": "Footing facile – 45 min Z2", "es": "Carrera suave – 45 min Z2"},
        "Rest Day": {"fr": "Jour de repos", "es": "Día de descanso"},
    }
    if lang != "en":
        recommendation = _REC_I18N.get(recommendation, {}).get(lang, recommendation)
        nw_label = _NW_I18N.get(nw_label, {}).get(lang, nw_label)

    # --- Statuses ---
    hrv_status = "green"
    if hrv_delta is not None:
        hrv_status = "green" if hrv_delta <= 5 else ("yellow" if hrv_delta <= 10 else "red")
    rhr_status = "green" if rhr_delta <= 3 else ("yellow" if rhr_delta <= 7 else "red")
    sleep_status = "green" if sleep_penalty <= 1.0 else ("yellow" if sleep_penalty <= 2.5 else "red")
    load_status = "green" if 0.8 <= acwr <= 1.3 else ("yellow" if acwr <= 1.5 else "red")
    fatigue_status = "green" if fatigue_ratio <= 1.2 else ("yellow" if fatigue_ratio <= 1.5 else "red")

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
    if have_rhr:
        sign = "+" if rhr_delta >= 0 else ""
        _t = {"fr": f"FC de repos {sign}{rhr_delta:.1f} bpm vs référence ({rhr_today:.0f} bpm)",
              "es": f"FC en reposo {sign}{rhr_delta:.1f} bpm vs referencia ({rhr_today:.0f} bpm)",
              "en": f"RHR {sign}{rhr_delta:.1f} bpm vs baseline ({rhr_today:.0f} bpm)"}
        reasons.append(_t.get(lang, _t["fr"]))
    _t = {"fr": f"Sommeil {sleep_hours_val:.1f} h", "es": f"Sueño {sleep_hours_val:.1f} h",
          "en": f"Sleep {sleep_hours_val:.1f} h"}
    reasons.append(_t.get(lang, _t["fr"]))
    _t = {"fr": f"Charge d'entraînement (ACWR) {acwr:.2f}", "es": f"Carga de entrenamiento (ACWR) {acwr:.2f}",
          "en": f"Training Load (ACWR) {acwr:.2f}"}
    reasons.append(_t.get(lang, _t["fr"]))
    _t = {"fr": f"Ratio de fatigue {fatigue_ratio:.2f}", "es": f"Ratio de fatiga {fatigue_ratio:.2f}",
          "en": f"Fatigue Ratio {fatigue_ratio:.2f}"}
    reasons.append(_t.get(lang, _t["fr"]))

    # --- 7-day history (oldest -> newest) ---
    recent = list(reversed(metrics_docs[:7]))
    history = []
    for doc in recent:
        d = _parse_day(doc.get("date", ""))
        day_label = _DAY_ABBREVS[d.weekday()] if d else (doc.get("date", "")[-2:] or "?")
        doc_hrv = doc.get("hrv")
        doc_rhr = doc.get("resting_hr")
        doc_sleep = doc.get("sleep_hours") or 7.0
        doc_rhr_delta = (float(doc_rhr) - float(rhr_baseline)) if doc_rhr is not None else 0.0
        doc_sleep_penalty = max(0.0, 8.0 - doc_sleep)
        if doc_hrv is not None and hrv_baseline is not None:
            doc_fp = 0.5 * (float(hrv_baseline) - float(doc_hrv)) + 0.3 * doc_rhr_delta + 0.2 * doc_sleep_penalty
        else:
            doc_fp = 0.6 * doc_rhr_delta + 0.4 * doc_sleep_penalty
        doc_fatigue_ratio = 1.0 + max(0.0, doc_fp) / 10.0
        history.append({
            "day": day_label,
            "date": doc.get("date"),
            "hrv": round(float(doc_hrv), 1) if doc_hrv is not None else None,
            "training_load": round(training_load, 2),
            "fatigue_ratio": round(doc_fatigue_ratio, 2),
        })

    return {
        "mock": False,
        "source": "garmin",
        "recommendation": recommendation,
        "recommendation_emoji": rec_emoji,
        "recommendation_color": rec_color,
        "next_workout": {"label": nw_label, "icon": nw_icon},
        "reasons": reasons,
        "metrics": {
            "hrv_today": round(float(hrv_today), 1) if have_hrv else None,
            "hrv_baseline": round(float(hrv_baseline), 1) if (have_hrv and hrv_baseline is not None) else None,
            "hrv_delta": round(hrv_delta, 1) if hrv_delta is not None else None,
            "hrv_status": hrv_status,
            "hrv_available": have_hrv,
            "rhr_today": round(float(rhr_today), 1) if have_rhr else None,
            "rhr_baseline": round(float(rhr_baseline), 1),
            "rhr_delta": round(rhr_delta, 1),
            "rhr_status": rhr_status,
            "sleep_hours": round(sleep_hours_val, 1),
            "sleep_efficiency": round(sleep_efficiency, 2),
            "sleep_score": round(sleep_penalty, 2),
            "sleep_status": sleep_status,
            "training_load": round(training_load, 2),
            "training_load_status": load_status,
            "fatigue_physio": round(fatigue_physio, 2),
            "fatigue_ratio": round(fatigue_ratio, 2),
            "fatigue_status": fatigue_status,
            "run_readiness": run_readiness,
            "run_readiness_status": readiness_status,
        },
        "history": history,
    }
