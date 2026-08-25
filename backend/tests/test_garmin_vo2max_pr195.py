"""PR195 — Tests for native Garmin running VO₂max import.

Covers:
1. GarminVO2Max.from_max_metrics — payload extraction (flat, nested, running-sport)
2. GarminVO2Max.from_max_metrics — edge cases (None, [], bad types)
3. GarminVO2Max.from_max_metrics — precise value + date extraction
4. GccliRunner.fetch_max_metrics — subprocess routing + date parameter
5. GccliProvider.get_max_metrics — delegates to runner
6. service._fetch_and_persist_vo2max — persists to garmin_vo2max; no-overwrite guard
7. service._build_and_persist_capabilities — reads garmin_vo2max, sets has_vo2max
8. insights.compute_run_index — exposes vo2max_running/precise/date in metrics
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from garmin.data_layer import GarminVO2Max
import garmin.service as garmin_service


# --------------------------------------------------------------------------- #
# 1. GarminVO2Max.from_max_metrics — payload extraction
# --------------------------------------------------------------------------- #

class TestGarminVO2MaxExtraction:
    def test_flat_vo2max_value(self):
        payload = [{"vo2MaxValue": 52.5}]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running == 52.5

    def test_nested_generic_vo2max(self):
        payload = [{"generic": {"vo2MaxValue": 48.0}}]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running == 48.0

    def test_running_sport_preferred_over_generic(self):
        payload = [
            {"sportType": "cycling", "vo2MaxValue": 60.0},
            {"sportType": "running", "vo2MaxValue": 51.0},
        ]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running == 51.0

    def test_running_sport_in_generic_block(self):
        payload = [
            {"sportType": "running", "generic": {"vo2MaxValue": 50.5}},
        ]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running == 50.5

    def test_vo2max_running_key_preferred(self):
        # vo2MaxRunning takes priority over vo2MaxValue within the same item.
        payload = [{"vo2MaxRunning": 53.0, "vo2MaxValue": 49.0}]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running == 53.0

    def test_trail_running_sport_recognized(self):
        payload = [{"sportType": "trail_running", "vo2MaxValue": 47.5}]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running == 47.5

    def test_multiple_items_running_wins(self):
        payload = [
            {"sportType": "other", "vo2MaxValue": 55.0},
            {"sportType": "run", "vo2MaxValue": 50.0},
            {"sportType": "cycling", "vo2MaxValue": 62.0},
        ]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running == 50.0

    def test_value_rounded_to_one_decimal(self):
        payload = [{"vo2MaxValue": 51.347}]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running == 51.3

    def test_fallback_to_first_item_no_sport(self):
        payload = [{"vo2MaxValue": 44.0}]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running == 44.0


# --------------------------------------------------------------------------- #
# 2. GarminVO2Max.from_max_metrics — edge cases
# --------------------------------------------------------------------------- #

class TestGarminVO2MaxEdgeCases:
    def test_empty_list(self):
        assert GarminVO2Max.from_max_metrics([]).vo2max_running is None

    def test_none_payload(self):
        assert GarminVO2Max.from_max_metrics(None).vo2max_running is None

    def test_null_vo2max_value(self):
        assert GarminVO2Max.from_max_metrics([{"vo2MaxValue": None}]).vo2max_running is None

    def test_zero_vo2max_value(self):
        # Zero is not a positive value → None (no measurement).
        assert GarminVO2Max.from_max_metrics([{"vo2MaxValue": 0}]).vo2max_running is None

    def test_negative_vo2max_value(self):
        assert GarminVO2Max.from_max_metrics([{"vo2MaxValue": -1.0}]).vo2max_running is None

    def test_non_list_dict_payload(self):
        # A dict instead of list → None, no exception.
        assert GarminVO2Max.from_max_metrics({"vo2MaxValue": 50.0}).vo2max_running is None

    def test_string_payload(self):
        assert GarminVO2Max.from_max_metrics("garbage").vo2max_running is None

    def test_bool_value_rejected(self):
        assert GarminVO2Max.from_max_metrics([{"vo2MaxValue": True}]).vo2max_running is None

    def test_empty_items(self):
        assert GarminVO2Max.from_max_metrics([{}, {}, {}]).vo2max_running is None

    def test_source_field(self):
        result = GarminVO2Max.from_max_metrics([{"vo2MaxValue": 50.0}])
        assert result.source == "garmin"

    def test_precise_absent_when_field_missing(self):
        result = GarminVO2Max.from_max_metrics([{"vo2MaxValue": 50.0}])
        assert result.vo2max_running_precise is None

    def test_date_absent_when_field_missing(self):
        result = GarminVO2Max.from_max_metrics([{"vo2MaxValue": 50.0}])
        assert result.date is None


# --------------------------------------------------------------------------- #
# 3. GarminVO2Max.from_max_metrics — precise value + date extraction
# --------------------------------------------------------------------------- #

class TestGarminVO2MaxPreciseAndDate:
    def test_precise_value_extracted_flat(self):
        payload = [{"vo2MaxValue": 43.0, "vo2MaxPreciseValue": 43.5}]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running == 43.0
        assert result.vo2max_running_precise == 43.5

    def test_precise_not_rounded(self):
        # Precise value must be stored as-is, not rounded to 1 decimal.
        payload = [{"vo2MaxValue": 43.0, "vo2MaxPreciseValue": 43.57}]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running_precise == 43.57

    def test_precise_in_generic_block(self):
        payload = [{"generic": {"vo2MaxValue": 43.0, "vo2MaxPreciseValue": 43.5}}]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running == 43.0
        assert result.vo2max_running_precise == 43.5

    def test_precise_with_running_sport(self):
        payload = [
            {"sportType": "running", "generic": {
                "calendarDate": "2026-08-25",
                "vo2MaxValue": 43.0,
                "vo2MaxPreciseValue": 43.5,
            }},
        ]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running == 43.0
        assert result.vo2max_running_precise == 43.5
        assert result.date == "2026-08-25"

    def test_calendar_date_extracted_flat(self):
        payload = [{"calendarDate": "2026-08-25", "vo2MaxValue": 43.0}]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.date == "2026-08-25"

    def test_calendar_date_extracted_nested(self):
        payload = [{"generic": {"calendarDate": "2026-08-25", "vo2MaxValue": 43.0}}]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.date == "2026-08-25"

    def test_date_none_when_absent(self):
        payload = [{"vo2MaxValue": 43.0}]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.date is None

    def test_precise_zero_rejected(self):
        payload = [{"vo2MaxValue": 43.0, "vo2MaxPreciseValue": 0}]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running_precise is None

    def test_precise_negative_rejected(self):
        payload = [{"vo2MaxValue": 43.0, "vo2MaxPreciseValue": -1.0}]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running_precise is None

    def test_precise_bool_rejected(self):
        payload = [{"vo2MaxValue": 43.0, "vo2MaxPreciseValue": True}]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running_precise is None

    def test_value_only_no_precise(self):
        # value present, precise absent: normal case.
        payload = [{"generic": {"calendarDate": "2026-08-25", "vo2MaxValue": 44.0}}]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running == 44.0
        assert result.vo2max_running_precise is None

    def test_real_payload_example(self):
        # Exact example from spec: calendarDate=2026-08-25, value=43.0, precise=43.5
        payload = [
            {
                "sportType": "running",
                "generic": {
                    "calendarDate": "2026-08-25",
                    "vo2MaxValue": 43.0,
                    "vo2MaxPreciseValue": 43.5,
                },
            }
        ]
        result = GarminVO2Max.from_max_metrics(payload)
        assert result.vo2max_running == 43.0
        assert result.vo2max_running_precise == 43.5
        assert result.date == "2026-08-25"


# --------------------------------------------------------------------------- #
# 4. GccliRunner.fetch_max_metrics — subprocess routing + date parameter
# --------------------------------------------------------------------------- #

class TestGccliRunnerFetchMaxMetrics:
    def _make_runner(self):
        from garmin.runner import GccliRunner
        runner = GccliRunner.__new__(GccliRunner)
        runner.gccli_path = "gccli"
        runner.home = "/tmp/test_home"
        runner.keyring_backend = "file"
        runner.timeout = 30
        runner.max_retries = 1
        return runner

    def test_returns_list_directly(self):
        runner = self._make_runner()
        expected = [{"vo2MaxValue": 52.5}]
        with patch.object(runner, "_run_json", return_value=expected):
            result = runner.fetch_max_metrics()
        assert result == expected

    def test_unwraps_dict_maxMetrics_key(self):
        runner = self._make_runner()
        with patch.object(runner, "_run_json", return_value={"maxMetrics": [{"vo2MaxValue": 50.0}]}):
            result = runner.fetch_max_metrics()
        assert result == [{"vo2MaxValue": 50.0}]

    def test_returns_empty_on_error(self):
        runner = self._make_runner()
        from garmin.runner import GccliError
        with patch.object(runner, "_run_json", side_effect=GccliError("oops")):
            result = runner.fetch_max_metrics()
        assert result == []

    def test_passes_account(self):
        runner = self._make_runner()
        with patch.object(runner, "_run_json", return_value=[]) as mock_run:
            runner.fetch_max_metrics(account="test@example.com")
        mock_run.assert_called_once_with(
            ["health", "max-metrics"], account="test@example.com"
        )

    def test_passes_date_when_provided(self):
        runner = self._make_runner()
        with patch.object(runner, "_run_json", return_value=[]) as mock_run:
            runner.fetch_max_metrics(date="2026-08-25")
        mock_run.assert_called_once_with(
            ["health", "max-metrics", "2026-08-25"], account=None
        )

    def test_no_date_appended_when_none(self):
        runner = self._make_runner()
        with patch.object(runner, "_run_json", return_value=[]) as mock_run:
            runner.fetch_max_metrics()
        mock_run.assert_called_once_with(
            ["health", "max-metrics"], account=None
        )

    def test_date_and_account_together(self):
        runner = self._make_runner()
        with patch.object(runner, "_run_json", return_value=[]) as mock_run:
            runner.fetch_max_metrics(account="u@example.com", date="2026-08-25")
        mock_run.assert_called_once_with(
            ["health", "max-metrics", "2026-08-25"], account="u@example.com"
        )


# --------------------------------------------------------------------------- #
# 5. GccliProvider.get_max_metrics
# --------------------------------------------------------------------------- #

class TestGccliProviderGetMaxMetrics:
    def test_delegates_to_runner(self):
        from garmin.providers.gccli_provider import GccliProvider
        runner = MagicMock()
        runner.fetch_max_metrics.return_value = [{"vo2MaxValue": 52.0}]
        provider = GccliProvider(runner=runner, account="u@example.com")
        result = provider.get_max_metrics("user_1")
        assert result == [{"vo2MaxValue": 52.0}]
        runner.fetch_max_metrics.assert_called_once_with(account="u@example.com")


# --------------------------------------------------------------------------- #
# 6. service._fetch_and_persist_vo2max — persists; no-overwrite guard
# --------------------------------------------------------------------------- #

class TestFetchAndPersistVO2Max:
    def _mock_db(self):
        db = MagicMock()
        db.garmin_vo2max.update_one = AsyncMock()
        return db

    def test_persists_extracted_value(self):
        db = self._mock_db()
        provider = MagicMock()
        provider.get_max_metrics.return_value = [{"vo2MaxValue": 53.0}]

        result = asyncio.run(
            garmin_service._fetch_and_persist_vo2max(db, "user_1", provider)
        )

        assert result == 53.0
        db.garmin_vo2max.update_one.assert_awaited_once()
        call_args = db.garmin_vo2max.update_one.call_args
        set_doc = call_args[0][1]["$set"]
        assert set_doc["vo2max_running"] == 53.0
        assert set_doc["user_id"] == "user_1"

    def test_persists_precise_value(self):
        db = self._mock_db()
        provider = MagicMock()
        provider.get_max_metrics.return_value = [
            {"vo2MaxValue": 43.0, "vo2MaxPreciseValue": 43.5, "calendarDate": "2026-08-25"}
        ]

        asyncio.run(
            garmin_service._fetch_and_persist_vo2max(db, "user_1", provider)
        )

        set_doc = db.garmin_vo2max.update_one.call_args[0][1]["$set"]
        assert set_doc["vo2max_running"] == 43.0
        assert set_doc["vo2max_running_precise"] == 43.5
        assert set_doc["vo2max_date"] == "2026-08-25"

    def test_precise_not_in_set_when_absent(self):
        """When payload has no precise value, vo2max_running_precise is NOT set
        so a previously stored precise value is not erased."""
        db = self._mock_db()
        provider = MagicMock()
        provider.get_max_metrics.return_value = [{"vo2MaxValue": 43.0}]

        asyncio.run(
            garmin_service._fetch_and_persist_vo2max(db, "user_1", provider)
        )

        set_doc = db.garmin_vo2max.update_one.call_args[0][1]["$set"]
        assert set_doc["vo2max_running"] == 43.0
        assert "vo2max_running_precise" not in set_doc
        assert "vo2max_date" not in set_doc

    def test_returns_none_on_exception(self):
        db = self._mock_db()
        provider = MagicMock()
        provider.get_max_metrics.side_effect = RuntimeError("network error")

        result = asyncio.run(
            garmin_service._fetch_and_persist_vo2max(db, "user_1", provider)
        )

        assert result is None

    def test_no_overwrite_when_payload_empty(self):
        """No-overwrite guard: when payload yields no value, update_one is NOT called."""
        db = self._mock_db()
        provider = MagicMock()
        provider.get_max_metrics.return_value = []

        result = asyncio.run(
            garmin_service._fetch_and_persist_vo2max(db, "user_1", provider)
        )

        assert result is None
        db.garmin_vo2max.update_one.assert_not_awaited()

    def test_no_overwrite_when_payload_has_null_value(self):
        """No-overwrite guard: payload with null vo2MaxValue → no write."""
        db = self._mock_db()
        provider = MagicMock()
        provider.get_max_metrics.return_value = [{"vo2MaxValue": None}]

        result = asyncio.run(
            garmin_service._fetch_and_persist_vo2max(db, "user_1", provider)
        )

        assert result is None
        db.garmin_vo2max.update_one.assert_not_awaited()


# --------------------------------------------------------------------------- #
# 7. service._build_and_persist_capabilities — reads garmin_vo2max
# --------------------------------------------------------------------------- #

class TestBuildCapabilitiesWithVO2Max:
    def _mock_db(self, vo2max_val=None, hrv_val=None, bb_val=None, stress_val=None):
        db = MagicMock()

        async def find_one_daily(query, proj, sort=None):
            field = list(proj.keys())[0]
            if field == "hrv" and hrv_val is not None:
                return {"hrv": hrv_val}
            if field == "body_battery" and bb_val is not None:
                return {"body_battery": bb_val}
            if field == "stress" and stress_val is not None:
                return {"stress": stress_val}
            return None

        db.garmin_daily_metrics.find_one = AsyncMock(side_effect=find_one_daily)

        async def find_one_vo2max(query, proj):
            if vo2max_val is not None:
                return {"vo2max_running": vo2max_val}
            return None

        db.garmin_vo2max.find_one = AsyncMock(side_effect=find_one_vo2max)
        db.garmin_connections.update_one = AsyncMock()
        return db

    def test_has_vo2max_true_when_stored(self):
        db = self._mock_db(vo2max_val=52.0)

        asyncio.run(
            garmin_service._build_and_persist_capabilities(db, "user_1")
        )

        set_doc = db.garmin_connections.update_one.call_args[0][1]["$set"]
        assert set_doc["garmin_capabilities"]["has_vo2max"] is True

    def test_has_vo2max_false_when_not_stored(self):
        db = self._mock_db(vo2max_val=None)

        asyncio.run(
            garmin_service._build_and_persist_capabilities(db, "user_1")
        )

        set_doc = db.garmin_connections.update_one.call_args[0][1]["$set"]
        assert set_doc["garmin_capabilities"]["has_vo2max"] is False


# --------------------------------------------------------------------------- #
# 8. insights.compute_run_index — vo2max fields in metrics
# --------------------------------------------------------------------------- #

class TestComputeRunIndexVO2Max:
    def _make_db(self, vo2max_val=None, vo2max_precise=None, vo2max_date=None):
        db = MagicMock()
        metrics_cursor = MagicMock()
        metrics_cursor.sort.return_value = metrics_cursor
        metrics_cursor.limit.return_value = metrics_cursor
        metrics_cursor.to_list = AsyncMock(return_value=[
            {"date": "2024-01-15", "resting_hr": 52, "hrv": 38.0,
             "sleep_hours": 7.5, "sleep_score": 80, "user_id": "u1"},
        ])
        db.garmin_daily_metrics.find.return_value = metrics_cursor

        activities_cursor = MagicMock()
        activities_cursor.sort.return_value = activities_cursor
        activities_cursor.limit.return_value = activities_cursor
        activities_cursor.to_list = AsyncMock(return_value=[])
        db.garmin_activities.find.return_value = activities_cursor

        async def vo2max_find_one(query, proj):
            if vo2max_val is not None:
                doc = {"vo2max_running": vo2max_val}
                if vo2max_precise is not None:
                    doc["vo2max_running_precise"] = vo2max_precise
                if vo2max_date is not None:
                    doc["vo2max_date"] = vo2max_date
                return doc
            return None

        db.garmin_vo2max.find_one = AsyncMock(side_effect=vo2max_find_one)
        return db

    def test_vo2max_running_present_in_metrics(self):
        import datetime
        from garmin.insights import compute_run_index

        db = self._make_db(vo2max_val=51.5)
        ref_date = datetime.date(2024, 1, 16)
        payload = asyncio.run(
            compute_run_index(db, "u1", reference_date=ref_date)
        )

        assert payload is not None
        assert payload["metrics"]["vo2max_running"] == 51.5

    def test_vo2max_running_none_when_missing(self):
        import datetime
        from garmin.insights import compute_run_index

        db = self._make_db(vo2max_val=None)
        ref_date = datetime.date(2024, 1, 16)
        payload = asyncio.run(
            compute_run_index(db, "u1", reference_date=ref_date)
        )

        assert payload is not None
        assert payload["metrics"]["vo2max_running"] is None

    def test_vo2max_precise_and_date_exposed(self):
        import datetime
        from garmin.insights import compute_run_index

        db = self._make_db(vo2max_val=43.0, vo2max_precise=43.5, vo2max_date="2026-08-25")
        ref_date = datetime.date(2024, 1, 16)
        payload = asyncio.run(
            compute_run_index(db, "u1", reference_date=ref_date)
        )

        assert payload is not None
        assert payload["metrics"]["vo2max_running"] == 43.0
        assert payload["metrics"]["vo2max_running_precise"] == 43.5
        assert payload["metrics"]["vo2max_date"] == "2026-08-25"

    def test_vo2max_precise_none_when_not_stored(self):
        import datetime
        from garmin.insights import compute_run_index

        db = self._make_db(vo2max_val=51.5)
        ref_date = datetime.date(2024, 1, 16)
        payload = asyncio.run(
            compute_run_index(db, "u1", reference_date=ref_date)
        )

        assert payload is not None
        assert payload["metrics"]["vo2max_running_precise"] is None
        assert payload["metrics"]["vo2max_date"] is None

