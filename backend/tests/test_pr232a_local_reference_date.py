"""C231 — Tests for training_v2.local_reference_date (timezone boundary fix).

Verifies that "today" is derived from the athlete's Garmin-observed local
clock (via the most recent activity's local/GMT offset) rather than a raw
UTC date that can drift by up to a day around midnight.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone

os.environ.setdefault("JWT_SECRET", "test-secret-pr232a-refdate")
os.environ.setdefault("ENVIRONMENT", "test")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from training_v2.local_reference_date import resolve_local_reference_date  # noqa: E402


def _doc(*, start_time_local: str, start_time_gmt: str):
    return {
        "start_time": start_time_local,
        "garmin_activity": {
            "start_time_local": start_time_local,
            "start_time_gmt": start_time_gmt,
        },
    }


def test_no_activities_falls_back_to_utc_date():
    now_utc = datetime(2024, 6, 10, 23, 40, tzinfo=timezone.utc)
    result = resolve_local_reference_date(now_utc=now_utc, garmin_activities=[])
    assert result == date(2024, 6, 10)


def test_boundary_timezone_ahead_of_utc_rolls_forward():
    """23:40 UTC with a UTC+2 athlete is already 01:40 the next local day."""
    now_utc = datetime(2024, 6, 10, 23, 40, tzinfo=timezone.utc)
    docs = [
        _doc(start_time_local="2024-06-09 08:00:00", start_time_gmt="2024-06-09 06:00:00"),
    ]
    result = resolve_local_reference_date(now_utc=now_utc, garmin_activities=docs)
    assert result == date(2024, 6, 11)


def test_boundary_timezone_behind_utc_rolls_backward():
    """00:20 UTC with a UTC-5 athlete is still 19:20 the previous local day."""
    now_utc = datetime(2024, 6, 11, 0, 20, tzinfo=timezone.utc)
    docs = [
        _doc(start_time_local="2024-06-09 08:00:00", start_time_gmt="2024-06-09 13:00:00"),
    ]
    result = resolve_local_reference_date(now_utc=now_utc, garmin_activities=docs)
    assert result == date(2024, 6, 10)


def test_most_recent_activity_offset_wins():
    now_utc = datetime(2024, 6, 10, 12, 0, tzinfo=timezone.utc)
    docs = [
        # Older activity: UTC+0 (must be ignored — a more recent one exists).
        _doc(start_time_local="2024-06-01 08:00:00", start_time_gmt="2024-06-01 08:00:00"),
        # Most recent activity: UTC+9.
        _doc(start_time_local="2024-06-09 08:00:00", start_time_gmt="2024-06-08 23:00:00"),
    ]
    result = resolve_local_reference_date(now_utc=now_utc, garmin_activities=docs)
    assert result == date(2024, 6, 10)  # 12:00 UTC + 9h = 21:00, same calendar day


def test_activity_without_local_time_is_skipped():
    now_utc = datetime(2024, 6, 10, 23, 40, tzinfo=timezone.utc)
    docs = [{"start_time": "2024-06-09 08:00:00", "garmin_activity": {}}]
    result = resolve_local_reference_date(now_utc=now_utc, garmin_activities=docs)
    assert result == date(2024, 6, 10)


def test_module_is_deterministic_pure_function():
    now_utc = datetime(2024, 6, 10, 10, 0, tzinfo=timezone.utc)
    docs = [_doc(start_time_local="2024-06-09 08:00:00", start_time_gmt="2024-06-09 06:00:00")]
    r1 = resolve_local_reference_date(now_utc=now_utc, garmin_activities=docs)
    r2 = resolve_local_reference_date(now_utc=now_utc, garmin_activities=docs)
    assert r1 == r2
