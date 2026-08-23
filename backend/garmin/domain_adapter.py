"""Garmin -> DomainActivity adapter boundary.

Two conversion paths are exposed:

``to_domain_activity(GarminActivity)``
    Converts a provider-layer :class:`GarminActivity` Pydantic model (already
    normalised by the data-layer) into a :class:`DomainActivity`.  Used by
    the sync/ingestion pipeline.

``mongo_garmin_to_domain(dict)``
    Converts a raw MongoDB document from the ``garmin_activities`` collection
    into a :class:`DomainActivity`.  This is the explicit Mongo → Training V2
    boundary required by PR137.

    Priority: ``doc["garmin_activity"]`` sub-document (normalised by the
    ingestion pipeline) is preferred when present.  Top-level fields act as
    fallback for legacy documents that pre-date the sub-document convention.

    Mapping summary (subdoc → DomainActivity):
        activity_type              → activity_type
        start_time                 → start_time
        distance_m                 → distance_m     (top-level alias: distance)
        duration_s                 → duration_s     (top-level alias: duration)
        moving_duration_s          → moving_duration_s
        average_hr                 → average_hr     (top-level alias: avg_hr)
        max_hr                     → max_hr
        moderate_intensity_minutes → moderate_intensity_minutes
        vigorous_intensity_minutes → vigorous_intensity_minutes
        elevation_gain             → elevation_gain_m   ← explicit rename
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from .data_layer import GarminActivity, GarminCapabilities
from training_v2.domain_capabilities import DomainCapabilities
from training_v2.domain_activity import (
    DomainActivity,
    _domain_intensity_minutes,
    _domain_source_activity_id,
    _domain_start_time,
)


def to_domain_activity(activity: GarminActivity) -> DomainActivity:
    """Convert a normalized Garmin activity into the Training V2 domain model."""
    moving_dur_raw = activity.moving_duration_s
    duration_raw = activity.duration_s
    moving_dur: Optional[float] = None
    if (
        moving_dur_raw is not None
        and isinstance(moving_dur_raw, (int, float))
        and float(moving_dur_raw) > 0
    ):
        val = float(moving_dur_raw)
        if duration_raw is None or not isinstance(duration_raw, (int, float)) or val <= float(duration_raw):
            moving_dur = val

    return DomainActivity(
        activity_type=activity.activity_type,
        start_time=activity.start_time,
        distance_m=activity.distance_m,
        duration_s=activity.duration_s,
        moving_duration_s=moving_dur,
        source=activity.source,
        source_activity_id=activity.activity_id,
        moderate_intensity_minutes=(
            float(activity.moderate_intensity_minutes)
            if activity.moderate_intensity_minutes is not None
            else None
        ),
        vigorous_intensity_minutes=(
            float(activity.vigorous_intensity_minutes)
            if activity.vigorous_intensity_minutes is not None
            else None
        ),
        average_hr=(
            float(activity.average_hr)
            if activity.average_hr is not None and float(activity.average_hr) > 0
            else None
        ),
        max_hr=(
            float(activity.max_hr)
            if activity.max_hr is not None and float(activity.max_hr) > 0
            else None
        ),
        elevation_gain_m=(
            float(activity.elevation_gain)
            if activity.elevation_gain is not None
            else None
        ),
    )


# ---------------------------------------------------------------------------
# Mongo garmin_activities → DomainActivity boundary (PR137)
# ---------------------------------------------------------------------------

def _opt_float_positive(value: Any) -> Optional[float]:
    """Return float(value) when value is a positive real number, else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    f = float(value)
    return f if f > 0 else None


def _opt_float_any(value: Any) -> Optional[float]:
    """Return float(value) for any real number (including negative and zero), else None."""
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    return float(value)


def mongo_garmin_to_domain(doc: Dict[str, Any]) -> DomainActivity:
    """Convert a raw MongoDB ``garmin_activities`` document to a :class:`DomainActivity`.

    The ``garmin_activity`` sub-document is used when present (it contains the
    normalised Garmin field names).  Each field falls back to the top-level
    document for legacy documents that pre-date the sub-document convention.

    Rules
    -----
    - Pure and deterministic; no I/O, no side effects.
    - None ≠ 0: absent fields are returned as None, never as 0.
    - No fabricated values: only data explicitly present in the document is used.
    - Provider-neutral output: the returned DomainActivity knows nothing about
      MongoDB or Garmin internals.
    """
    sub: Dict[str, Any] = doc.get("garmin_activity") or {}

    # activity_type — same name at both levels
    activity_type = sub.get("activity_type") or doc.get("activity_type")
    act_type: Optional[str] = activity_type if isinstance(activity_type, str) else None

    # start_time — same name at both levels
    start_raw = sub.get("start_time") or doc.get("start_time")
    start_time = _domain_start_time(start_raw)

    # distance_m — subdoc canonical name; top-level alias is "distance"
    # A zero distance is physiologically meaningless; use _opt_float_positive.
    dist_raw = sub.get("distance_m") if "distance_m" in sub else doc.get("distance_m", doc.get("distance"))
    distance_m = _opt_float_positive(dist_raw) if dist_raw is not None else None

    # duration_s — subdoc canonical name; top-level alias is "duration"
    # A zero duration contributes no load; use _opt_float_positive.
    dur_raw = sub.get("duration_s") if "duration_s" in sub else doc.get("duration_s", doc.get("duration"))
    duration_s = _opt_float_positive(dur_raw) if dur_raw is not None else None

    # moving_duration_s — subdoc canonical name; validated against duration_s.
    mov_raw = sub.get("moving_duration_s") if "moving_duration_s" in sub else doc.get("moving_duration_s")
    moving_duration_s: Optional[float] = None
    if mov_raw is not None:
        mov_val = _opt_float_positive(mov_raw)
        if mov_val is not None:
            if duration_s is None or mov_val <= duration_s:
                moving_duration_s = mov_val

    # average_hr — subdoc canonical name; top-level alias is "avg_hr"
    avg_hr_raw = sub.get("average_hr") if "average_hr" in sub else doc.get("average_hr", doc.get("avg_hr"))
    average_hr = _opt_float_positive(avg_hr_raw) if avg_hr_raw is not None else None

    # max_hr — subdoc canonical name; no alias at top level
    max_hr_raw = sub.get("max_hr") if "max_hr" in sub else doc.get("max_hr")
    max_hr = _opt_float_positive(max_hr_raw) if max_hr_raw is not None else None

    # moderate_intensity_minutes — only in subdoc for modern documents
    mod_raw = sub.get("moderate_intensity_minutes") if "moderate_intensity_minutes" in sub else doc.get("moderate_intensity_minutes")
    moderate_intensity_minutes = _domain_intensity_minutes(mod_raw) if mod_raw is not None else None

    # vigorous_intensity_minutes — only in subdoc for modern documents
    vig_raw = sub.get("vigorous_intensity_minutes") if "vigorous_intensity_minutes" in sub else doc.get("vigorous_intensity_minutes")
    vigorous_intensity_minutes = _domain_intensity_minutes(vig_raw) if vig_raw is not None else None

    # elevation_gain_m — subdoc field is "elevation_gain" (no _m suffix);
    # top-level also uses "elevation_gain".  Explicit rename → elevation_gain_m.
    # Zero elevation gain is valid (flat run); use _opt_float_any.
    elev_raw = sub.get("elevation_gain") if "elevation_gain" in sub else doc.get("elevation_gain_m", doc.get("elevation_gain"))
    elevation_gain_m = _opt_float_any(elev_raw) if elev_raw is not None else None

    # source / source_activity_id — top-level only
    source_raw = doc.get("source")
    source: Optional[str] = source_raw if isinstance(source_raw, str) else None
    source_activity_id = _domain_source_activity_id(doc.get("activity_id") or doc.get("source_activity_id"))

    return DomainActivity(
        activity_type=act_type,
        start_time=start_time,
        distance_m=distance_m,
        duration_s=duration_s,
        moving_duration_s=moving_duration_s,
        source=source,
        source_activity_id=source_activity_id,
        moderate_intensity_minutes=moderate_intensity_minutes,
        vigorous_intensity_minutes=vigorous_intensity_minutes,
        average_hr=average_hr,
        max_hr=max_hr,
        elevation_gain_m=elevation_gain_m,
    )


def mongo_garmin_activities_to_domain(docs: List[Dict[str, Any]]) -> List[DomainActivity]:
    """Convert a list of raw MongoDB ``garmin_activities`` documents to DomainActivity.

    Returns one DomainActivity per input document.  Documents that are None or
    not dict-like produce a blank DomainActivity (no exception raised).
    """
    result: List[DomainActivity] = []
    for doc in docs:
        if isinstance(doc, dict):
            result.append(mongo_garmin_to_domain(doc))
        else:
            result.append(DomainActivity())
    return result


def to_domain_capabilities(capabilities: GarminCapabilities) -> DomainCapabilities:
    """Convert Garmin capabilities into the minimal Training V2 capability model."""
    return DomainCapabilities(
        has_hrv=capabilities.has_hrv,
        has_vo2max=capabilities.has_vo2max,
        has_training_readiness=capabilities.has_training_readiness,
        has_power=capabilities.has_power,
        has_running_dynamics=capabilities.has_running_dynamics,
    )
