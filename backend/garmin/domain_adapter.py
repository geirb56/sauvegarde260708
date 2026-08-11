"""Garmin -> DomainActivity adapter boundary."""

from __future__ import annotations

from .data_layer import GarminActivity
from training_v2.domain_activity import DomainActivity


def to_domain_activity(activity: GarminActivity) -> DomainActivity:
    """Convert a normalized Garmin activity into the Training V2 domain model."""
    return DomainActivity(
        activity_type=activity.activity_type,
        start_time=activity.start_time,
        distance_m=activity.distance_m,
        duration_s=activity.duration_s,
    )
