"""RunIndex v2 — Garmin Data Layer (PR01).

Single source of truth for normalized Garmin data. This module is PURE
NORMALIZATION only: it maps the raw gccli JSON payloads (activity summary /
activity details / health endpoints) onto stable, typed models.

Design rules (do not violate):
- No business logic (no RunnerProfile / TrainingHistory / TrainingState / plans).
- No fallback / no fabrication: when Garmin does not provide a value the field
  is ``None``. Empty ``{}`` / ``[]`` / ``null`` payloads must yield valid models
  with ``None`` fields (never raise).
- Additive only: nothing here is wired into the existing engine, score,
  readiness, endpoints or frontend. Future PRs will consume these models.

All raw shapes below come from the real audited gccli 1.9.0 output.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict


# --------------------------------------------------------------------------- #
# Safe extraction helpers (never raise on {} / [] / null / wrong types)
# --------------------------------------------------------------------------- #

def _num(x: Any) -> Optional[float]:
    """Return x as a number if it already is one, else None. Never coerces."""
    if isinstance(x, bool):  # bool is a subclass of int — reject it explicitly
        return None
    if isinstance(x, (int, float)):
        return x
    return None


def _int(x: Any) -> Optional[int]:
    n = _num(x)
    return int(n) if n is not None else None


def _str(x: Any) -> Optional[str]:
    return x if isinstance(x, str) and x != "" else None


def _dict(x: Any) -> Dict[str, Any]:
    return x if isinstance(x, dict) else {}


def _has_data(x: Any) -> bool:
    """True only when Garmin actually returned content (not None/{}/[])."""
    if x is None:
        return False
    if isinstance(x, (list, dict, str)) and len(x) == 0:
        return False
    return True


def _deep_has_positive_number(obj: Any, key_pred) -> bool:
    """True if anywhere in obj a key matching ``key_pred`` holds a real
    positive number (> 0). Used to reject payloads that are non-empty but whose
    business values are all null (e.g. ``[{"vo2MaxValue": null}]``)."""
    stack = [obj]
    while stack:
        cur = stack.pop()
        if isinstance(cur, dict):
            for k, v in cur.items():
                if isinstance(v, (int, float)) and not isinstance(v, bool) and v > 0 and key_pred(k):
                    return True
                if isinstance(v, (dict, list)):
                    stack.append(v)
        elif isinstance(cur, list):
            stack.extend(cur)
    return False


# --------------------------------------------------------------------------- #
# GarminActivity
# --------------------------------------------------------------------------- #

class GarminActivity(BaseModel):
    """Normalized single activity.

    Accepts both the ``activity summary`` object (with ``summaryDTO`` /
    ``metadataDTO``) and the flat ``activities list`` item shape.
    """

    model_config = ConfigDict(extra="ignore")

    activity_id: Optional[str] = None
    activity_type: Optional[str] = None
    start_time: Optional[str] = None
    distance_m: Optional[float] = None
    duration_s: Optional[float] = None
    moving_duration_s: Optional[float] = None
    average_speed_mps: Optional[float] = None
    average_moving_speed_mps: Optional[float] = None
    max_speed_mps: Optional[float] = None
    average_hr: Optional[float] = None
    max_hr: Optional[float] = None
    min_hr: Optional[float] = None
    average_run_cadence: Optional[float] = None
    max_run_cadence: Optional[float] = None
    stride_length: Optional[float] = None
    steps: Optional[int] = None
    elevation_gain: Optional[float] = None
    elevation_loss: Optional[float] = None
    calories: Optional[float] = None
    moderate_intensity_minutes: Optional[int] = None
    vigorous_intensity_minutes: Optional[int] = None
    lap_count: Optional[int] = None
    has_hr_zones: Optional[bool] = None
    has_splits: Optional[bool] = None
    details_available: Optional[bool] = None
    source: str = "garmin"

    @classmethod
    def from_summary(cls, raw: Any, details_available: Optional[bool] = None) -> "GarminActivity":
        raw = _dict(raw)
        summary = _dict(raw.get("summaryDTO")) or raw  # summary object OR flat list item
        meta = _dict(raw.get("metadataDTO"))

        # activity type: {"activityTypeDTO"|"activityType": {"typeKey": ...}}
        atype = raw.get("activityTypeDTO") or raw.get("activityType")
        activity_type = _str(_dict(atype).get("typeKey")) if isinstance(atype, dict) else _str(atype)

        aid = raw.get("activityId") or raw.get("id")
        activity_id = str(aid) if isinstance(aid, (int, str)) and aid != "" else None

        # cadence: summary uses averageRunCadence; list shape uses *InStepsPerMinute
        avg_cad = _num(summary.get("averageRunCadence"))
        if avg_cad is None:
            avg_cad = _num(summary.get("averageRunningCadenceInStepsPerMinute"))
        max_cad = _num(summary.get("maxRunCadence"))
        if max_cad is None:
            max_cad = _num(summary.get("maxRunningCadenceInStepsPerMinute"))

        if details_available is None and raw.get("detailsAvailable") is not None:
            details_available = bool(raw.get("detailsAvailable"))

        return cls(
            activity_id=activity_id,
            activity_type=activity_type,
            start_time=_str(summary.get("startTimeGMT")) or _str(summary.get("startTimeLocal")),
            distance_m=_num(summary.get("distance")),
            duration_s=_num(summary.get("duration")),
            moving_duration_s=_num(summary.get("movingDuration")),
            average_speed_mps=_num(summary.get("averageSpeed")),
            average_moving_speed_mps=_num(summary.get("averageMovingSpeed")),
            max_speed_mps=_num(summary.get("maxSpeed")),
            average_hr=_num(summary.get("averageHR")),
            max_hr=_num(summary.get("maxHR")),
            min_hr=_num(summary.get("minHR")),
            average_run_cadence=avg_cad,
            max_run_cadence=max_cad,
            stride_length=_num(summary.get("strideLength")),
            steps=_int(summary.get("steps")),
            elevation_gain=_num(summary.get("elevationGain")),
            elevation_loss=_num(summary.get("elevationLoss")),
            calories=_num(summary.get("calories")),
            moderate_intensity_minutes=_int(summary.get("moderateIntensityMinutes")),
            vigorous_intensity_minutes=_int(summary.get("vigorousIntensityMinutes")),
            lap_count=_int(meta.get("lapCount")),
            has_hr_zones=(meta.get("hasHrTimeInZones") if isinstance(meta.get("hasHrTimeInZones"), bool) else None),
            has_splits=(meta.get("hasSplits") if isinstance(meta.get("hasSplits"), bool) else None),
            details_available=details_available,
        )


# --------------------------------------------------------------------------- #
# GarminDailyMetrics
# --------------------------------------------------------------------------- #

def _latest_body_battery(bb: Any) -> Optional[int]:
    """Return the most recent body-battery value from a body-battery payload.

    Raw shape (health body-battery view): a list of daily dicts, each with a
    ``bodyBatteryValuesArray`` of ``[timestamp, value]`` pairs.
    """
    if isinstance(bb, list):
        bb = bb[-1] if bb else {}
    bb = _dict(bb)
    arr = bb.get("bodyBatteryValuesArray")
    if isinstance(arr, list) and arr:
        last = arr[-1]
        if isinstance(last, list) and len(last) >= 2:
            return _int(last[1])
    return None


def _extract_daily_date(payload: Any) -> Optional[str]:
    payload = _dict(payload)
    return _str(payload.get("calendarDate")) or _str(payload.get("date"))


class GarminDailyMetrics(BaseModel):
    """Normalized daily wellness metrics for a single date."""

    model_config = ConfigDict(extra="ignore")

    date: Optional[str] = None
    resting_hr: Optional[int] = None
    sleep_hours: Optional[float] = None
    sleep_score: Optional[int] = None
    stress: Optional[int] = None
    body_battery: Optional[int] = None
    respiration: Optional[float] = None
    hrv: Optional[float] = None
    source: str = "garmin"

    @classmethod
    def from_gccli(
        cls,
        date: Optional[str] = None,
        hr: Any = None,
        sleep: Any = None,
        stress: Any = None,
        body_battery: Any = None,
        hrv: Any = None,
    ) -> "GarminDailyMetrics":
        hr = _dict(hr)
        sleep = _dict(sleep)
        stress = _dict(stress)
        hrv = _dict(hrv)

        body_battery_latest = body_battery[-1] if isinstance(body_battery, list) and body_battery else body_battery
        body_battery_latest = _dict(body_battery_latest)
        dto = _dict(sleep.get("dailySleepDTO"))
        sleep_secs = _num(dto.get("sleepTimeSeconds"))
        sleep_hours = round(sleep_secs / 3600, 1) if sleep_secs is not None and sleep_secs > 0 else None
        scores = _dict(dto.get("sleepScores"))
        overall = _dict(scores.get("overall"))
        sleep_score = _int(overall.get("value"))
        respiration = _num(dto.get("averageRespirationValue"))

        stress_val = _num(stress.get("avgStressLevel"))
        # Garmin uses -1/-2 as "no measurement" sentinels.
        if stress_val is not None and stress_val < 0:
            stress_val = None

        hrv_summary = _dict(hrv.get("hrvSummary"))
        hrv_val = _num(hrv_summary.get("lastNightAvg"))
        if hrv_val is None:
            hrv_val = _num(hrv_summary.get("weeklyAvg"))

        resolved_date = (
            _extract_daily_date(hr)
            or _extract_daily_date(sleep)
            or _extract_daily_date(stress)
            or _extract_daily_date(hrv)
            or _extract_daily_date(body_battery_latest)
            or _str(dto.get("calendarDate"))
            or _str(date)
        )

        return cls(
            date=resolved_date,
            resting_hr=_int(hr.get("restingHeartRate")),
            sleep_hours=sleep_hours,
            sleep_score=sleep_score,
            stress=(int(stress_val) if stress_val is not None else None),
            body_battery=_latest_body_battery(body_battery),
            respiration=respiration,
            hrv=hrv_val,
        )


# --------------------------------------------------------------------------- #
# GarminCapabilities
# --------------------------------------------------------------------------- #

class GarminCapabilities(BaseModel):
    """Describes what the user's watch actually produces.

    SEMANTICS — a field set to ``True`` means: **a usable, non-null value was
    actually observed for this account/device**. It does NOT merely mean that
    the corresponding gccli command exists. A non-empty payload whose business
    values are all null (e.g. ``[{"vo2MaxValue": null}]``) yields ``False``.

    Future frontend usage: show "Non disponible sur votre montre" instead of
    0 / "--" when a capability is False.
    """

    model_config = ConfigDict(extra="ignore")

    has_hrv: bool = False
    has_vo2max: bool = False
    has_training_readiness: bool = False
    has_training_status: bool = False
    has_body_battery: bool = False
    has_stress: bool = False
    has_running_dynamics: bool = False
    has_power: bool = False
    has_race_predictions: bool = False

    @staticmethod
    def _hrv_ok(hrv: Any) -> bool:
        s = _dict(_dict(hrv).get("hrvSummary"))
        return _num(s.get("lastNightAvg")) is not None or _num(s.get("weeklyAvg")) is not None

    @staticmethod
    def _vo2max_ok(max_metrics: Any) -> bool:
        # gccli max-metrics items expose vo2Max* fields (generic/cycling blocks).
        return _deep_has_positive_number(max_metrics, lambda k: "vo2" in k.lower())

    @staticmethod
    def _training_readiness_ok(tr: Any) -> bool:
        # training-readiness items expose a top-level "score".
        return _deep_has_positive_number(
            tr, lambda k: k.lower() == "score" or "readinessscore" in k.lower()
        )

    @staticmethod
    def _race_predictions_ok(rp: Any) -> bool:
        # race-predictions expose timeXXX fields (time5K, time10K, ...).
        return _deep_has_positive_number(rp, lambda k: k.lower().startswith("time"))

    @staticmethod
    def _status_ok(ts: Any) -> bool:
        ts = _dict(ts)
        return any(
            ts.get(k) is not None
            for k in ("mostRecentVO2Max", "mostRecentTrainingStatus", "mostRecentTrainingLoadBalance")
        )

    @staticmethod
    def _stress_ok(st: Any) -> bool:
        v = _num(_dict(st).get("avgStressLevel"))
        return v is not None and v >= 0

    @staticmethod
    def _running_dynamics_ok(summary: Any, details: Any) -> bool:
        markers = (
            "groundContactTime", "avgGroundContactTime", "verticalOscillation",
            "avgVerticalOscillation", "verticalRatio", "avgVerticalRatio",
            "directGroundContactTime", "directVerticalOscillation",
        )
        sdto = _dict(summary)
        sdto = _dict(sdto.get("summaryDTO")) or sdto
        if any(m in sdto for m in markers):
            return True
        for md in _dict(details).get("metricDescriptors", []) if isinstance(_dict(details).get("metricDescriptors"), list) else []:
            key = _str(_dict(md).get("key")) or ""
            low = key.lower()
            if "groundcontact" in low or "verticaloscillation" in low or "verticalratio" in low:
                return True
        return False

    @staticmethod
    def _power_ok(summary: Any) -> bool:
        s = _dict(summary)
        meta = _dict(s.get("metadataDTO"))
        if meta.get("hasPowerTimeInZones") is True:
            return True
        sdto = _dict(s.get("summaryDTO")) or s
        return _num(sdto.get("avgPower")) is not None

    @classmethod
    def from_probe(
        cls,
        hrv: Any = None,
        max_metrics: Any = None,
        training_readiness: Any = None,
        training_status: Any = None,
        body_battery: Any = None,
        stress: Any = None,
        activity_summary: Any = None,
        activity_details: Any = None,
        race_predictions: Any = None,
    ) -> "GarminCapabilities":
        return cls(
            has_hrv=cls._hrv_ok(hrv),
            has_vo2max=cls._vo2max_ok(max_metrics),
            has_training_readiness=cls._training_readiness_ok(training_readiness),
            has_training_status=cls._status_ok(training_status),
            has_body_battery=_has_data(body_battery),
            has_stress=cls._stress_ok(stress),
            has_running_dynamics=cls._running_dynamics_ok(activity_summary, activity_details),
            has_power=cls._power_ok(activity_summary),
            has_race_predictions=cls._race_predictions_ok(race_predictions),
        )
