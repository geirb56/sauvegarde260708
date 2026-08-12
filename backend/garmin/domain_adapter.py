"""Garmin -> DomainActivity adapter boundary."""

from __future__ import annotations

from .data_layer import GarminActivity, GarminCapabilities
from training_v2.domain_capabilities import DomainCapabilities
from training_v2.domain_activity import DomainActivity


def to_domain_activity(activity: GarminActivity) -> DomainActivity:
    """Convert a normalized Garmin activity into the Training V2 domain model."""
    return DomainActivity(
        activity_type=activity.activity_type,
        start_time=activity.start_time,
        distance_m=activity.distance_m,
        duration_s=activity.duration_s,
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
    )


def to_domain_capabilities(capabilities: GarminCapabilities) -> DomainCapabilities:
    """Convert Garmin capabilities into the minimal Training V2 capability model."""
    return DomainCapabilities(
        has_hrv=capabilities.has_hrv,
        has_vo2max=capabilities.has_vo2max,
        has_training_readiness=capabilities.has_training_readiness,
        has_power=capabilities.has_power,
        has_running_dynamics=capabilities.has_running_dynamics,
    )
