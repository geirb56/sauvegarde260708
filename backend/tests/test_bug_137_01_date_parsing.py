"""PR144 — BUG-137-01: _activity_date must parse space-separated Mongo dates.

Tests cover:
1. Unit: _activity_date with all supported formats
2. Integration: build_recent_training_response sees runs with Mongo dates
3. Boundary: raw Mongo dict → mongo_garmin_activities_to_domain → build_recent_training_response
"""

from datetime import date, datetime, timedelta

import pytest

from training_v2.domain_activity import DomainActivity
from training_v2.training_response import _activity_date, build_recent_training_response


# ---------------------------------------------------------------------------
# Unit tests: _activity_date
# ---------------------------------------------------------------------------

class TestActivityDateParsing:
    """Verify _activity_date handles all expected formats."""

    @pytest.mark.parametrize(
        "start_time,expected",
        [
            # Space-separated (Mongo/Garmin real format — the bug)
            ("2026-08-18 05:11:14", date(2026, 8, 18)),
            ("2026-08-18 05:11:14.123", date(2026, 8, 18)),
            # ISO-T formats (already supported)
            ("2026-08-18T05:11:14", date(2026, 8, 18)),
            ("2026-08-18T05:11:14Z", date(2026, 8, 18)),
            ("2026-08-18T05:11:14.123", date(2026, 8, 18)),
            ("2026-08-18T05:11:14+02:00", date(2026, 8, 18)),
            # Date only
            ("2026-08-18", date(2026, 8, 18)),
            # Native types
            (date(2026, 8, 18), date(2026, 8, 18)),
            (datetime(2026, 8, 18, 5, 11, 14), date(2026, 8, 18)),
            # Invalid → None
            (None, None),
            ("", None),
            ("not-a-date", None),
            ("2026/08/18", None),
        ],
    )
    def test_activity_date_formats(self, start_time, expected):
        act = DomainActivity(
            activity_type="running",
            start_time=start_time,
            distance_m=10000.0,
            duration_s=3000.0,
        )
        assert _activity_date(act) == expected


# ---------------------------------------------------------------------------
# Integration: build_recent_training_response with Mongo-style dates
# ---------------------------------------------------------------------------

class TestBuildResponseWithMongoDates:
    """Verify build_recent_training_response sees activities with space-separated dates."""

    def _make_activity(self, start_time: str, distance_m: float = 10000.0) -> DomainActivity:
        return DomainActivity(
            activity_type="running",
            start_time=start_time,
            distance_m=distance_m,
            duration_s=3000.0,
            average_hr=150.0,
            elevation_gain_m=50.0,
        )

    def test_space_separated_dates_are_selected(self):
        ref = date(2026, 8, 18)
        activities = [
            self._make_activity("2026-08-18 05:11:14"),
            self._make_activity("2026-08-15 06:00:00"),
            self._make_activity("2026-08-10 07:30:00"),
            self._make_activity("2026-08-05 08:00:00"),
            self._make_activity("2026-08-01 09:00:00"),
            self._make_activity("2026-07-28 10:00:00"),
        ]
        result = build_recent_training_response(activities, reference_date=ref)
        assert result.available_running_activities > 0
        assert result.observed_runs > 0
        assert result.response_status != "unavailable"
        assert result.hr_coverage_count > 0
        assert result.average_hr_recent is not None

    def test_mixed_date_formats(self):
        ref = date(2026, 8, 18)
        activities = [
            self._make_activity("2026-08-18 05:11:14"),       # space
            self._make_activity("2026-08-16T06:00:00"),       # ISO-T
            self._make_activity("2026-08-14T07:30:00Z"),      # ISO-Z
            self._make_activity("2026-08-12"),                # date only
            self._make_activity("2026-08-10 08:00:00.123"),   # space + ms
        ]
        result = build_recent_training_response(activities, reference_date=ref)
        assert result.available_running_activities == 5
        assert result.observed_runs == 5
        assert result.response_status == "sufficient"


# ---------------------------------------------------------------------------
# Boundary: raw Mongo → domain → build_recent_training_response
# ---------------------------------------------------------------------------

class TestMongoBoundaryToResponse:
    """End-to-end: raw Mongo dict → domain adapter → RecentTrainingResponse."""

    def test_mongo_to_response_pipeline(self):
        from garmin.domain_adapter import mongo_garmin_activities_to_domain

        ref = date(2026, 8, 18)
        raw_docs = [
            {
                "garmin_activity": {
                    "activity_type": "running",
                    "start_time": "2026-08-18 05:11:14",
                    "distance_m": 10500.0,
                    "duration_s": 3120.0,
                    "average_hr": 152.0,
                    "elevation_gain_m": 45.0,
                }
            },
            {
                "garmin_activity": {
                    "activity_type": "running",
                    "start_time": "2026-08-15 06:30:00",
                    "distance_m": 8200.0,
                    "duration_s": 2700.0,
                    "average_hr": 148.0,
                    "elevation_gain_m": 30.0,
                }
            },
            {
                "garmin_activity": {
                    "activity_type": "running",
                    "start_time": "2026-08-12 07:00:00",
                    "distance_m": 12000.0,
                    "duration_s": 3600.0,
                    "average_hr": 155.0,
                    "elevation_gain_m": 60.0,
                }
            },
            {
                "garmin_activity": {
                    "activity_type": "running",
                    "start_time": "2026-08-08 08:15:00",
                    "distance_m": 6000.0,
                    "duration_s": 2100.0,
                    "average_hr": 145.0,
                    "elevation_gain_m": 20.0,
                }
            },
            {
                "garmin_activity": {
                    "activity_type": "running",
                    "start_time": "2026-08-04 09:00:00",
                    "distance_m": 14000.0,
                    "duration_s": 4200.0,
                    "average_hr": 158.0,
                    "elevation_gain_m": 80.0,
                }
            },
        ]

        domain_activities = mongo_garmin_activities_to_domain(raw_docs)
        result = build_recent_training_response(domain_activities, reference_date=ref)

        # The critical assertion: activities survive the full pipeline
        assert result.available_running_activities == 5
        assert result.observed_runs == 5
        assert result.response_status == "sufficient"
        assert result.hr_coverage_count == 5
        assert result.average_hr_recent is not None
        assert result.average_hr_recent > 0
