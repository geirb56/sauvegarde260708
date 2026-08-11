"""DomainActivity — provider-neutral activity input for Training V2."""

from __future__ import annotations

from datetime import date, datetime
from typing import Any, Optional, Union

from pydantic import BaseModel, ConfigDict


class DomainActivity(BaseModel):
    """Minimal business activity model required by Training V2."""

    model_config = ConfigDict(frozen=True)

    activity_type: Optional[str] = None
    start_time: Optional[Union[str, date, datetime]] = None
    distance_m: Optional[float] = None
    duration_s: Optional[float] = None


def _domain_start_time(value: Any) -> Optional[Union[str, date, datetime]]:
    if isinstance(value, (str, date, datetime)):
        return value
    return None


def to_domain_activity(activity: Any) -> DomainActivity:
    """Coerce a generic activity object into a DomainActivity without raising."""
    if activity is None:
        return DomainActivity()

    if isinstance(activity, DomainActivity):
        return activity

    if isinstance(activity, dict):
        act_type = activity.get('activity_type')
        start = activity.get('start_time')
        dist = activity.get('distance_m', activity.get('distance'))
        dur = activity.get('duration_s', activity.get('duration'))
    else:
        act_type = getattr(activity, 'activity_type', None)
        start = getattr(activity, 'start_time', None)
        dist = getattr(activity, 'distance_m', getattr(activity, 'distance', None))
        dur = getattr(activity, 'duration_s', getattr(activity, 'duration', None))

    return DomainActivity(
        activity_type=act_type if isinstance(act_type, str) else None,
        start_time=_domain_start_time(start),
        distance_m=dist if isinstance(dist, (int, float)) and not isinstance(dist, bool) else None,
        duration_s=dur if isinstance(dur, (int, float)) and not isinstance(dur, bool) else None,
    )
