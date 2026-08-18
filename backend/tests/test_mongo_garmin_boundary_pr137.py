"""PR137 — Mongo garmin_activities → DomainActivity boundary tests.

Tests cover the explicit adapter boundary introduced in PR137 that converts
raw MongoDB ``garmin_activities`` documents to ``DomainActivity`` before they
are forwarded to Training V2 pure modules.

Test cases
----------
A. Document with full ``garmin_activity`` sub-document
   → all normalised fields are mapped correctly.

B. Legacy document without ``garmin_activity`` sub-document
   → top-level aliases (distance/duration/avg_hr) are exploited.

C. Absent field
   → produces None, never an invented value.

D. ``average_hr`` present in ``garmin_activity`` sub-document
   → value is preserved in DomainActivity (not lost / replaced by None).

E. Intensity minutes present in ``garmin_activity`` sub-document
   → moderate/vigorous arrive in DomainActivity.

F. TrainingLoad regression — build_training_load produces the same result
   whether the input is a pre-normalised DomainActivity list or raw Mongo
   docs processed through the boundary.

G. ``/training/today`` path — server.py uses ``mongo_garmin_activities_to_domain``
   (not raw Mongo docs) before calling Training V2 functions.
"""

from __future__ import annotations

from datetime import date
from typing import Any, Dict

import pytest

from garmin.domain_adapter import (
    mongo_garmin_activities_to_domain,
    mongo_garmin_to_domain,
)
from training_v2.domain_activity import DomainActivity
from training_v2.training_load import build_training_load

# ---------------------------------------------------------------------------
# Shared fixtures
# ---------------------------------------------------------------------------

_START = "2026-08-01T08:00:00"

_MONGO_FULL: Dict[str, Any] = {
    "activity_type": "running",
    "start_time": _START,
    "distance": 10000,
    "duration": 3000,
    "avg_hr": 145,  # top-level alias — should be OVERRIDDEN by subdoc value
    "garmin_activity": {
        "activity_type": "running",
        "start_time": _START,
        "distance_m": 10000,
        "duration_s": 3000,
        "average_hr": 150,
        "max_hr": 170,
        "moderate_intensity_minutes": 20,
        "vigorous_intensity_minutes": 10,
        "elevation_gain": 85,
    },
}

_MONGO_LEGACY: Dict[str, Any] = {
    "activity_type": "running",
    "start_time": _START,
    "distance": 8000,
    "duration": 2400,
    "avg_hr": 148,
    # No garmin_activity sub-document
}


# ===========================================================================
# A — full garmin_activity sub-document
# ===========================================================================

class TestA_FullSubDocument:
    def setup_method(self):
        self.act = mongo_garmin_to_domain(_MONGO_FULL)

    def test_distance_m(self):
        assert self.act.distance_m == 10000.0

    def test_duration_s(self):
        assert self.act.duration_s == 3000.0

    def test_average_hr_from_subdoc(self):
        """average_hr must come from garmin_activity.average_hr (150), not top-level avg_hr (145)."""
        assert self.act.average_hr == 150.0

    def test_max_hr(self):
        assert self.act.max_hr == 170.0

    def test_moderate_intensity_minutes(self):
        assert self.act.moderate_intensity_minutes == 20.0

    def test_vigorous_intensity_minutes(self):
        assert self.act.vigorous_intensity_minutes == 10.0

    def test_elevation_gain_m(self):
        """elevation_gain in sub-document must map to elevation_gain_m."""
        assert self.act.elevation_gain_m == 85.0

    def test_activity_type(self):
        assert self.act.activity_type == "running"

    def test_start_time(self):
        assert self.act.start_time == _START

    def test_returns_domain_activity(self):
        assert isinstance(self.act, DomainActivity)


# ===========================================================================
# B — legacy document without garmin_activity sub-document
# ===========================================================================

class TestB_LegacyNoSubDocument:
    def setup_method(self):
        self.act = mongo_garmin_to_domain(_MONGO_LEGACY)

    def test_distance_m_from_top_level(self):
        """Top-level 'distance' alias must be used."""
        assert self.act.distance_m == 8000.0

    def test_duration_s_from_top_level(self):
        """Top-level 'duration' alias must be used."""
        assert self.act.duration_s == 2400.0

    def test_average_hr_from_avg_hr_alias(self):
        """Top-level 'avg_hr' alias must map to average_hr."""
        assert self.act.average_hr == 148.0

    def test_max_hr_is_none(self):
        assert self.act.max_hr is None

    def test_moderate_intensity_minutes_is_none(self):
        assert self.act.moderate_intensity_minutes is None

    def test_vigorous_intensity_minutes_is_none(self):
        assert self.act.vigorous_intensity_minutes is None

    def test_elevation_gain_m_is_none(self):
        assert self.act.elevation_gain_m is None


# ===========================================================================
# C — absent field → None, never invented value
# ===========================================================================

class TestC_AbsentFields:
    def test_missing_average_hr_is_none(self):
        doc = {"activity_type": "running", "start_time": _START, "distance": 5000, "duration": 1500}
        act = mongo_garmin_to_domain(doc)
        assert act.average_hr is None

    def test_missing_max_hr_is_none(self):
        doc = {"activity_type": "running", "start_time": _START}
        act = mongo_garmin_to_domain(doc)
        assert act.max_hr is None

    def test_missing_elevation_is_none(self):
        doc = {"activity_type": "running", "start_time": _START}
        act = mongo_garmin_to_domain(doc)
        assert act.elevation_gain_m is None

    def test_missing_distance_is_none(self):
        doc = {"activity_type": "running", "start_time": _START}
        act = mongo_garmin_to_domain(doc)
        assert act.distance_m is None

    def test_missing_duration_is_none(self):
        doc = {"activity_type": "running", "start_time": _START}
        act = mongo_garmin_to_domain(doc)
        assert act.duration_s is None

    def test_subdoc_missing_field_is_none(self):
        """If garmin_activity sub-doc is present but a field is absent → None."""
        doc = {
            "activity_type": "running",
            "start_time": _START,
            "garmin_activity": {"activity_type": "running"},
        }
        act = mongo_garmin_to_domain(doc)
        assert act.average_hr is None
        assert act.max_hr is None
        assert act.elevation_gain_m is None

    def test_zero_hr_returns_none(self):
        """HR == 0 must return None (None ≠ 0 contract)."""
        doc = {
            "activity_type": "running",
            "start_time": _START,
            "garmin_activity": {"average_hr": 0, "max_hr": 0},
        }
        act = mongo_garmin_to_domain(doc)
        assert act.average_hr is None
        assert act.max_hr is None

    def test_negative_hr_returns_none(self):
        doc = {"activity_type": "running", "start_time": _START, "garmin_activity": {"average_hr": -5}}
        act = mongo_garmin_to_domain(doc)
        assert act.average_hr is None

    def test_string_hr_returns_none(self):
        doc = {"activity_type": "running", "start_time": _START, "garmin_activity": {"average_hr": "n/a"}}
        act = mongo_garmin_to_domain(doc)
        assert act.average_hr is None


# ===========================================================================
# D — average_hr from garmin_activity preserved in DomainActivity
# ===========================================================================

def test_d_average_hr_preserved():
    """D. average_hr from garmin_activity sub-doc must arrive in DomainActivity."""
    doc = {
        "activity_type": "running",
        "start_time": _START,
        "avg_hr": 130,  # top-level alias (lower value — must NOT win)
        "garmin_activity": {
            "average_hr": 155,
        },
    }
    act = mongo_garmin_to_domain(doc)
    assert act.average_hr == 155.0, (
        f"Expected 155.0 from garmin_activity.average_hr; got {act.average_hr}"
    )


# ===========================================================================
# E — intensity minutes from garmin_activity preserved
# ===========================================================================

def test_e_intensity_minutes_preserved():
    """E. moderate/vigorous intensity minutes from subdoc must arrive in DomainActivity."""
    doc = {
        "activity_type": "running",
        "start_time": _START,
        "garmin_activity": {
            "moderate_intensity_minutes": 25,
            "vigorous_intensity_minutes": 12,
        },
    }
    act = mongo_garmin_to_domain(doc)
    assert act.moderate_intensity_minutes == 25.0
    assert act.vigorous_intensity_minutes == 12.0


# ===========================================================================
# F — TrainingLoad regression
# ===========================================================================

def test_f_training_load_regression():
    """F. build_training_load produces the same ACWR from Mongo docs processed
    through the boundary as from manually constructed DomainActivity inputs."""
    ref = date(2026, 8, 5)
    # Build via boundary
    mongo_docs = [
        {
            "activity_type": "running",
            "start_time": f"2026-08-0{i+1}T08:00:00",
            "garmin_activity": {
                "distance_m": 10000,
                "duration_s": 3000,
            },
        }
        for i in range(5)
    ]
    domain_acts = mongo_garmin_activities_to_domain(mongo_docs)
    snap_via_boundary = build_training_load(domain_acts, ref)

    # Build from hand-crafted DomainActivity
    manual_acts = [
        DomainActivity(
            activity_type="running",
            start_time=f"2026-08-0{i+1}T08:00:00",
            distance_m=10000.0,
            duration_s=3000.0,
        )
        for i in range(5)
    ]
    snap_manual = build_training_load(manual_acts, ref)

    assert snap_via_boundary.acwr == snap_manual.acwr
    assert snap_via_boundary.acute_load_7d == snap_manual.acute_load_7d


# ===========================================================================
# G — server.py /training/today uses mongo_garmin_activities_to_domain
# ===========================================================================

def test_g_server_uses_boundary():
    """G. The /training/today handler in server.py must call
    ``mongo_garmin_activities_to_domain`` before passing activities to
    Training V2 functions (not raw Mongo docs).
    Uses source-code inspection to avoid importing the full server module."""
    import pathlib

    server_path = pathlib.Path(__file__).parent.parent / "server.py"
    source = server_path.read_text(encoding="utf-8")

    assert "mongo_garmin_activities_to_domain" in source, (
        "server.py must import/use mongo_garmin_activities_to_domain"
    )

    # Verify the boundary call appears before build_training_load in the endpoint source
    boundary_pos = source.find("domain_activities = mongo_garmin_activities_to_domain")
    load_pos = source.find("build_training_load(domain_activities")
    response_pos = source.find("build_recent_training_response(domain_activities")
    assert boundary_pos != -1, "domain_activities assignment not found in server.py"
    assert load_pos != -1, "build_training_load(domain_activities, ...) not found in server.py"
    assert response_pos != -1, "build_recent_training_response(domain_activities, ...) not found in server.py"
    assert boundary_pos < load_pos, "Boundary call must precede build_training_load"
    assert boundary_pos < response_pos, "Boundary call must precede build_recent_training_response"

    # Verify the import is present
    assert "from garmin.domain_adapter import mongo_garmin_activities_to_domain" in source, (
        "server.py must import mongo_garmin_activities_to_domain from garmin.domain_adapter"
    )


# ===========================================================================
# Extra: mongo_garmin_activities_to_domain list contract
# ===========================================================================

def test_list_converter_returns_one_per_doc():
    docs = [_MONGO_FULL, _MONGO_LEGACY]
    result = mongo_garmin_activities_to_domain(docs)
    assert len(result) == 2
    assert all(isinstance(a, DomainActivity) for a in result)


def test_list_converter_empty_list():
    result = mongo_garmin_activities_to_domain([])
    assert result == []


def test_list_converter_none_doc():
    """Non-dict entries must not raise; they produce a blank DomainActivity."""
    result = mongo_garmin_activities_to_domain([None])  # type: ignore[list-item]
    assert len(result) == 1
    assert isinstance(result[0], DomainActivity)
    assert result[0].activity_type is None
