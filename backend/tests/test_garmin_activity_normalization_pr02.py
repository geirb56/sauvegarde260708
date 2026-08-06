"""PR02 — Tests verifying that GccliProvider._normalize delegates to
GarminActivity.from_summary and preserves the historical contract.

Coverage:
- activities-list flat item is correctly converted via GarminActivity
- all historical contract keys are present in the result
- garmin_activity field is added and mirrors normalized.model_dump()
- absent activity_type yields None (no fallback to "running")
- startTimeLocal takes priority over startTimeGMT for the top-level start_time
- "id" key is accepted as an alternative to "activityId"
- {} on GccliProvider._normalize does not raise
- [] and None tested on GarminActivity.from_summary only (provider expects a dict)
"""

from __future__ import annotations

import sys
from pathlib import Path
from types import ModuleType
from unittest.mock import MagicMock

# Allow importing from backend package directory
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import pytest

# Stub config.secrets so GccliProvider import succeeds without env setup.
def _stub(name: str) -> ModuleType:
    m = ModuleType(name)
    sys.modules[name] = m
    return m

_stub("config")
_cs = _stub("config.secrets")
_cs.get_secret = MagicMock(return_value=None)

from garmin.providers.gccli_provider import GccliProvider
from garmin.data_layer import GarminActivity

# ---------------------------------------------------------------------------
# Minimal flat activities-list payload (real gccli 1.9.0 shape)
# ---------------------------------------------------------------------------

FLAT_ACTIVITY = {
    "activityId": 23821475753,
    "activityName": "Vannes Course a pied",
    "activityType": {"typeKey": "running"},
    "startTimeLocal": "2026-08-02T10:08:20.0",
    "startTimeGMT": "2026-08-02T08:08:20.0",
    "distance": 6769.92,
    "duration": 2787.479,
    "averageHR": 146.0,
    "averageSpeed": 2.4289999,
    "calories": 604.0,
    "elevationGain": 23.1,
}

# Historical contract keys that must always be present
CONTRACT_KEYS = [
    "external_id",
    "source",
    "name",
    "activity_type",
    "start_time",
    "distance",
    "duration",
    "avg_hr",
    "pace",
    "pace_seconds_per_km",
    "raw_payload",
]


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def normalize(raw):
    """Call the private static method directly (no Runner/vault needed)."""
    return GccliProvider._normalize(raw)


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

class TestContractPreserved:
    """All historical keys must still exist and carry the correct values."""

    def test_all_contract_keys_present(self):
        result = normalize(FLAT_ACTIVITY)
        for key in CONTRACT_KEYS:
            assert key in result, f"Missing contract key: {key}"

    def test_external_id(self):
        result = normalize(FLAT_ACTIVITY)
        assert result["external_id"] == "23821475753"

    def test_source_is_garmin(self):
        result = normalize(FLAT_ACTIVITY)
        assert result["source"] == "garmin"

    def test_name(self):
        result = normalize(FLAT_ACTIVITY)
        assert result["name"] == "Vannes Course a pied"

    def test_activity_type(self):
        result = normalize(FLAT_ACTIVITY)
        assert result["activity_type"] == "running"

    def test_start_time_prefers_local_over_gmt(self):
        # Historical contract: startTimeLocal takes priority.
        result = normalize(FLAT_ACTIVITY)
        assert result["start_time"] == "2026-08-02T10:08:20.0"

    def test_start_time_falls_back_to_gmt_when_local_absent(self):
        raw = {**FLAT_ACTIVITY}
        del raw["startTimeLocal"]
        result = normalize(raw)
        assert result["start_time"] == "2026-08-02T08:08:20.0"

    def test_distance(self):
        result = normalize(FLAT_ACTIVITY)
        assert result["distance"] == pytest.approx(6769.92)

    def test_duration(self):
        result = normalize(FLAT_ACTIVITY)
        assert result["duration"] == pytest.approx(2787.479)

    def test_avg_hr(self):
        result = normalize(FLAT_ACTIVITY)
        assert result["avg_hr"] == 146

    def test_pace_format(self):
        result = normalize(FLAT_ACTIVITY)
        # pace_seconds_per_km = 2787.479 / (6769.92 / 1000) ≈ 411.8 s/km → 6:52
        pace = result["pace"]
        assert isinstance(pace, str)
        assert ":" in pace

    def test_pace_seconds_per_km(self):
        result = normalize(FLAT_ACTIVITY)
        # 2787.479 / (6769.92 / 1000) ≈ 411.8
        assert result["pace_seconds_per_km"] == pytest.approx(411.8, abs=1.0)

    def test_raw_payload_keys(self):
        result = normalize(FLAT_ACTIVITY)
        rp = result["raw_payload"]
        for key in ("activityId", "distance", "duration", "averageHR", "averageSpeed",
                    "calories", "elevationGain"):
            assert key in rp


class TestActivityTypeNoFallback:
    """Absent activity type must yield None — no silent fallback to 'running'."""

    def test_absent_type_is_none(self):
        result = normalize({"activityId": 1, "distance": 1000, "duration": 300})
        assert result["activity_type"] is None

    def test_explicit_type_preserved(self):
        result = normalize({**FLAT_ACTIVITY, "activityType": {"typeKey": "cycling"}})
        assert result["activity_type"] == "cycling"


class TestAlternativeIdKey:
    """Provider must accept 'id' as a fallback when 'activityId' is absent."""

    def test_id_key_sets_external_id(self):
        result = normalize({"id": 123, "distance": 5000, "duration": 1800})
        assert result["external_id"] == "123"

    def test_id_key_sets_garmin_activity_id(self):
        result = normalize({"id": 123, "distance": 5000, "duration": 1800})
        assert result["garmin_activity"]["activity_id"] == "123"


class TestGarminActivityAdded:
    """PR02 new field: garmin_activity must be present and mirror the model."""

    def test_garmin_activity_key_present(self):
        result = normalize(FLAT_ACTIVITY)
        assert "garmin_activity" in result

    def test_garmin_activity_is_dict(self):
        result = normalize(FLAT_ACTIVITY)
        assert isinstance(result["garmin_activity"], dict)

    def test_garmin_activity_matches_model(self):
        result = normalize(FLAT_ACTIVITY)
        expected = GarminActivity.from_summary(FLAT_ACTIVITY).model_dump()
        assert result["garmin_activity"] == expected

    def test_garmin_activity_source(self):
        result = normalize(FLAT_ACTIVITY)
        assert result["garmin_activity"]["source"] == "garmin"

    def test_garmin_activity_distance(self):
        result = normalize(FLAT_ACTIVITY)
        assert result["garmin_activity"]["distance_m"] == pytest.approx(6769.92)

    def test_garmin_activity_average_hr(self):
        result = normalize(FLAT_ACTIVITY)
        assert result["garmin_activity"]["average_hr"] == pytest.approx(146.0)

    def test_garmin_activity_start_time_gmt_convention(self):
        # garmin_activity sub-document uses model convention (GMT first).
        # This is documented as a known residual difference from the top-level start_time.
        result = normalize(FLAT_ACTIVITY)
        assert result["garmin_activity"]["start_time"] == "2026-08-02T08:08:20.0"


class TestDegenerateInputs:
    """Robustness tests — scope is documented carefully.

    GccliProvider._normalize: tested with {} (empty dict) only.
      It expects a dict; [] and None are not its documented contract.
    GarminActivity.from_summary: tested with {}, [], and None — it must
      tolerate all three (PR01 guarantee).
    """

    def test_empty_dict_on_normalize_does_not_raise(self):
        result = normalize({})
        assert isinstance(result, dict)
        for key in CONTRACT_KEYS:
            assert key in result

    def test_empty_dict_on_normalize_has_garmin_activity(self):
        result = normalize({})
        assert "garmin_activity" in result
        assert isinstance(result["garmin_activity"], dict)

    def test_none_on_from_summary_does_not_raise(self):
        act = GarminActivity.from_summary(None)
        assert act.activity_id is None
        assert act.distance_m is None

    def test_empty_list_on_from_summary_does_not_raise(self):
        act = GarminActivity.from_summary([])
        assert act.activity_id is None

    def test_empty_dict_on_from_summary_does_not_raise(self):
        act = GarminActivity.from_summary({})
        assert act.activity_id is None

    def test_missing_hr_gives_none(self):
        result = normalize({"activityId": 1})
        assert result["avg_hr"] is None

    def test_missing_distance_gives_none_pace(self):
        result = normalize({"activityId": 1, "duration": 300})
        assert result["pace"] is None
        assert result["pace_seconds_per_km"] is None

