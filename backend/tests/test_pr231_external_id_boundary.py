"""C231 (P0 #1) — the REAL document persisted by ``_ingest_activities`` /
``gccli_provider._normalize`` carries the stable id as top-level
``external_id`` (never a top-level ``activity_id``/``source_activity_id``).

Regression coverage: before this fix, ``mongo_garmin_to_domain()`` only
looked at ``doc.get("activity_id") or doc.get("source_activity_id")`` for
the stable id — both ALWAYS ``None`` on real documents, silently breaking
every Garmin<->prescription matching that depends on activity identity.
"""
from __future__ import annotations

import os
import sys
from datetime import date, datetime, timezone

os.environ.setdefault("JWT_SECRET_KEY", "test-pr231-extid-secret-32chars!!")
os.environ.setdefault("JWT_SECRET", "test-pr231-extid-secret-32chars!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

from garmin.domain_adapter import (  # noqa: E402
    mongo_garmin_to_domain,
    mongo_garmin_to_observed_activity,
)
from training_v2.performed_workout import (  # noqa: E402
    PrescribedWorkout,
    build_performed_workouts,
    MatchingStatus,
)

_USER_ID = "user-pr231-extid"


def _real_ingested_doc(
    *,
    external_id: str = "act-real-12345",
    activity_id_in_subdoc: str = "act-real-12345",
    start_time_local: str = "2024-06-10T07:00:00",
    distance_m: float = 8000.0,
    duration_s: float = 2880.0,
) -> dict:
    """Build a document EXACTLY shaped like what ``_ingest_activities``
    actually persists via ``gccli_provider._normalize()``.

    - top-level ``external_id`` (the ONLY stable-id field ever persisted at
      top level for modern documents)
    - NO top-level ``activity_id`` (that field simply does not exist on real
      documents)
    - ``source == "garmin"``
    - ``user_id`` (added by ``_ingest_activities`` itself)
    - a real ``garmin_activity`` sub-document (``GarminActivity.model_dump()``)
      whose OWN ``activity_id`` mirrors the same external id.
    """
    garmin_activity_subdoc = {
        "activity_id": activity_id_in_subdoc,
        "activity_type": "running",
        "start_time": "2024-06-10T05:00:00Z",  # GMT-first, per model convention
        "start_time_local": start_time_local,
        "distance_m": distance_m,
        "duration_s": duration_s,
        "moving_duration_s": duration_s,
        "average_speed_mps": None,
        "average_moving_speed_mps": None,
        "max_speed_mps": None,
        "average_hr": 145.0,
        "max_hr": 168.0,
        "min_hr": None,
        "average_run_cadence": None,
        "max_run_cadence": None,
        "stride_length": None,
        "steps": None,
        "elevation_gain": 42.0,
        "elevation_loss": None,
        "calories": None,
        "moderate_intensity_minutes": None,
        "vigorous_intensity_minutes": None,
    }
    return {
        # _ingest_activities: {**act, "user_id": user_id, "synced_at": ...}
        "external_id": external_id,
        "source": "garmin",
        "name": "Morning Run",
        "activity_type": "running",
        "start_time": start_time_local,  # local-first, per historical top-level convention
        "distance": distance_m,
        "duration": duration_s,
        "avg_hr": 145,
        "pace": "6:00",
        "pace_seconds_per_km": 360.0,
        "raw_payload": {"activityId": external_id},
        "garmin_activity": garmin_activity_subdoc,
        "user_id": _USER_ID,
        "synced_at": datetime.now(timezone.utc).isoformat(),
    }


def test_mongo_garmin_to_domain_resolves_external_id_from_real_document():
    doc = _real_ingested_doc()
    assert "activity_id" not in doc, "Sanity check: real documents have no top-level activity_id."

    domain = mongo_garmin_to_domain(doc)

    assert domain.source_activity_id == "act-real-12345"
    assert domain.source == "garmin"


def test_mongo_garmin_to_observed_activity_uses_external_id():
    doc = _real_ingested_doc(external_id="act-observed-999")

    observed = mongo_garmin_to_observed_activity(doc, user_id=_USER_ID)

    assert observed is not None
    assert observed.activity_id == "act-observed-999"


def test_pr230_matching_succeeds_using_the_real_external_id_document():
    """End-to-end: a document shaped exactly like real ingestion output must
    successfully match against a prescribed workout via PR230's boundary."""
    doc = _real_ingested_doc(
        external_id="act-match-1",
        start_time_local="2024-06-10T07:00:00",
        distance_m=8000.0,
        duration_s=2880.0,
    )
    observed = mongo_garmin_to_observed_activity(doc, user_id=_USER_ID)
    assert observed is not None

    prescription = PrescribedWorkout(
        prescription_id="p1",
        user_id=_USER_ID,
        planned_date=date(2024, 6, 10),
        workout_type="easy",
        distance_km=8.0,
        duration_min=48.0,
        intensity_class="low",
    )
    ledger = build_performed_workouts(
        user_id=_USER_ID,
        reference_date=date(2024, 6, 10),
        prescriptions=[prescription],
        activities=[observed],
    )
    row = ledger.entries[0]
    assert row.matching_status == MatchingStatus.MATCHED
    assert row.activity_id == "act-match-1"


def test_legacy_top_level_activity_id_still_resolves_when_no_external_id():
    """Legacy documents that pre-date the external_id convention (if any
    still exist) must still resolve via the fallback chain — never crash,
    never fabricate."""
    doc = _real_ingested_doc()
    del doc["external_id"]
    doc["activity_id"] = "legacy-top-level-id"

    domain = mongo_garmin_to_domain(doc)
    assert domain.source_activity_id == "legacy-top-level-id"


def test_no_id_anywhere_never_fabricates_one():
    doc = _real_ingested_doc()
    del doc["external_id"]
    doc["garmin_activity"] = {**doc["garmin_activity"], "activity_id": None}

    domain = mongo_garmin_to_domain(doc)
    assert domain.source_activity_id is None
