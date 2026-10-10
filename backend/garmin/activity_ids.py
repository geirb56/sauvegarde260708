"""Garmin identifiers at the provider boundary; stored keys are never rewritten."""

import re
from typing import Union


def normalize_activity_id(activity_id: Union[str, int]) -> str:
    if isinstance(activity_id, int) and not isinstance(activity_id, bool):
        activity_id = str(activity_id)
    if not isinstance(activity_id, str) or not re.fullmatch(r"[0-9]{1,30}", activity_id):
        raise ValueError("Invalid activity identifier")
    return activity_id
