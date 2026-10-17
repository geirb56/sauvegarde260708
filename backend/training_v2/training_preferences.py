"""Pure desired/active training preference resolution, anchored to local dates."""

from datetime import date, timedelta
from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator, model_validator


TrainingDay = Literal[
    "monday", "tuesday", "wednesday", "thursday", "friday", "saturday", "sunday"
]
PREFERENCE_FIELDS = (
    "sessions_per_week", "preferred_training_days", "preferred_long_run_day"
)


class TrainingPreferencesPayload(BaseModel):
    model_config = ConfigDict(extra="forbid")

    sessions_per_week: Optional[StrictInt] = Field(default=None, ge=2, le=6)
    preferred_training_days: Optional[list[TrainingDay]] = None
    preferred_long_run_day: Optional[TrainingDay] = None

    @field_validator("sessions_per_week")
    @classmethod
    def sessions_cannot_be_reset(cls, value):
        if value is None:
            raise ValueError("sessions_per_week cannot be null.")
        return value

    @field_validator("preferred_training_days")
    @classmethod
    def nonempty_unique_days(cls, value):
        if value is not None and (not value or len(set(value)) != len(value)):
            raise ValueError("Use unique training days; use null, not [], to reset.")
        return value

    @model_validator(mode="after")
    def nonempty_patch(self):
        if not self.model_fields_set:
            raise ValueError("At least one preference must be provided.")
        return self


def desired_preferences(document: Optional[dict]) -> dict:
    document = document or {}
    return {field: document.get(field) for field in PREFERENCE_FIELDS}


def resolve_active_preferences(document: Optional[dict], reference_date: date) -> dict:
    """Legacy preferences are active immediately; pending changes are not."""
    document = document or {}
    effective_from = document.get("effective_from")
    if effective_from and reference_date < date.fromisoformat(effective_from):
        return desired_preferences(document.get("active_preferences"))
    return desired_preferences(document)


def preferences_response(document: Optional[dict], reference_date: date) -> dict:
    return {
        **desired_preferences(document),
        "effective_from": (document or {}).get("effective_from"),
        "active_preferences": resolve_active_preferences(document, reference_date),
    }


def schedule_preferences(document: Optional[dict], changes: dict, reference_date: date) -> dict:
    desired = {**desired_preferences(document), **changes}
    days = desired["preferred_training_days"]
    long_day = desired["preferred_long_run_day"]
    if days is not None and long_day is not None and long_day not in days:
        raise ValueError("preferred_long_run_day must belong to preferred_training_days.")
    return {
        **desired,
        "effective_from": (
            reference_date + timedelta(days=7 - reference_date.weekday())
        ).isoformat(),
        "active_preferences": resolve_active_preferences(document, reference_date),
    }
