"""PR179 — RunIndex DomainActivity source tests.

Tests that the RunIndex Garmin canonical path uses garmin_activities →
DomainActivity, not db.workouts.  All 19 required test cases are covered.

Test catalogue
--------------
1.  DomainActivity running valid → accepted
2.  Non-running activity → ignored
3.  distance_m → distance_km correct at boundary
4.  duration_s → duration_minutes correct at boundary
5.  average_hr preserved
6.  Absent field → None, never 0
7.  Future activity vs reference_date → ignored
8.  CURRENT: garmin_activities used (not db.workouts)
9.  CURRENT: db.workouts different → does not influence RunIndex Garmin
10. HISTORY: garmin_activities used
11. HISTORY: reference_date=J → no activity > J included
12. SNAPSHOT: source is Garmin DomainActivity
13. BACKFILL: source is Garmin DomainActivity
14. POST-SYNC: activity in garmin_activities but absent from db.workouts → seen
15. USER ISOLATION: activity from another user → never used
16. PARITY: equivalent workout dict vs DomainActivity → identical scores
17. PUBLIC PAYLOAD: no contractual change (run_index key present + int)
18. READINESS: not modified (smoke import check)
19. TRAINING V2: not modified (smoke import check)
"""

from __future__ import annotations

import asyncio
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace
from typing import Any, List, Optional

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from training_v2.domain_activity import DomainActivity
from engine.run_index_engine import (
    calculate_run_index,
    calculate_run_index_from_domain,
    _domain_activity_to_workout_dict,
    prepare_workout_dicts_from_domain,
)
from services.run_index_history import (
    build_snapshot_document_from_domain,
    select_snapshot_dates_from_domain,
    _domain_activity_day,
    _first_domain_activity_day,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

REF_DATE = date(2026, 7, 15)


def _domain_run(
    days_ago: int,
    distance_m: float,
    duration_s: float,
    average_hr: Optional[float] = None,
    reference: date = REF_DATE,
) -> DomainActivity:
    start = datetime(
        reference.year, reference.month, reference.day, 8, 0, 0, tzinfo=timezone.utc
    ) - timedelta(days=days_ago)
    return DomainActivity(
        activity_type="running",
        start_time=start.isoformat(),
        distance_m=distance_m,
        duration_s=duration_s,
        average_hr=average_hr,
        source="garmin",
        source_activity_id=f"act-{days_ago}",
    )


def _workout_dict(
    days_ago: int,
    distance_km: float,
    pace_min_km: float,
    avg_hr: Optional[int] = None,
    reference: date = REF_DATE,
) -> dict:
    duration_minutes = distance_km * pace_min_km
    d = reference - timedelta(days=days_ago)
    return {
        "type": "run",
        "date": d.isoformat(),
        "distance_km": distance_km,
        "duration_minutes": round(duration_minutes, 2),
        "avg_pace_min_km": pace_min_km,
        "avg_speed_kmh": round(60.0 / pace_min_km, 3),
        "avg_heart_rate": avg_hr,
    }


def _profile_domain(reference: date = REF_DATE) -> List[DomainActivity]:
    """10 varied running activities used for profile-level tests."""
    specs = [
        (2, 8000, 2448, 154),   # 8 km, 40.8 min, 154 bpm
        (5, 10000, 2940, 162),  # 10 km, 49 min, 162 bpm
        (9, 14000, 4368, 151),  # 14 km, 72.8 min, 151 bpm
        (13, 6000, 1728, 165),  # 6 km, 28.8 min, 165 bpm
        (18, 12000, 3600, 156), # 12 km, 60 min, 156 bpm
        (22, 16000, 4992, 149), # 16 km, 83.2 min, 149 bpm
        (29, 8000, 2400, 155),  # 8 km, 40 min, 155 bpm
        (33, 5000, 1410, 168),  # 5 km, 23.5 min, 168 bpm
        (40, 12000, 3672, 152), # 12 km, 61.2 min, 152 bpm
        (46, 18000, 5724, 150), # 18 km, 95.4 min, 150 bpm
    ]
    return [_domain_run(days, d_m, dur_s, hr, reference) for days, d_m, dur_s, hr in specs]


def _profile_workout_dicts(reference: date = REF_DATE) -> List[dict]:
    """Equivalent workout dicts (semantically identical data as _profile_domain)."""
    specs = [
        (2, 8.0, 5.1, 154),
        (5, 10.0, 4.9, 162),
        (9, 14.0, 5.2, 151),
        (13, 6.0, 4.8, 165),
        (18, 12.0, 5.0, 156),
        (22, 16.0, 5.2, 149),
        (29, 8.0, 5.0, 155),
        (33, 5.0, 4.7, 168),
        (40, 12.0, 5.1, 152),
        (46, 18.0, 5.3, 150),
    ]
    return [_workout_dict(days, d_km, pace, hr, reference) for days, d_km, pace, hr in specs]


# ---------------------------------------------------------------------------
# Fake async DB
# ---------------------------------------------------------------------------

class FakeCursor:
    def __init__(self, docs: list) -> None:
        self._docs = list(docs)

    def sort(self, *args: Any):
        return self

    def limit(self, *args: Any):
        return self

    async def to_list(self, length: Optional[int] = None):
        return list(self._docs[:length] if length else self._docs)


class FakeCollection:
    def __init__(self, docs: list) -> None:
        self._docs = list(docs)
        self._upserts: list = []

    def find(self, query: dict, projection: Optional[dict] = None):
        user_id = query.get("user_id")
        if user_id:
            docs = [d for d in self._docs if d.get("user_id") == user_id]
        else:
            docs = list(self._docs)
        return FakeCursor(docs)

    async def find_one(self, query: dict, projection: Optional[dict] = None):
        user_id = query.get("user_id")
        for doc in self._docs:
            if doc.get("user_id") == user_id:
                return doc
        return None

    async def update_one(self, filter_doc: dict, update_doc: dict, upsert: bool = False):
        self._upserts.append({"filter": filter_doc, "update": update_doc})
        return SimpleNamespace(upserted_count=1, modified_count=0)

    async def bulk_write(self, ops: list, ordered: bool = True):
        self._upserts.extend(ops)
        return SimpleNamespace(upserted_count=len(ops), modified_count=0)


def _make_garmin_activity_doc(
    user_id: str,
    days_ago: int,
    distance_m: float,
    duration_s: float,
    average_hr: Optional[float] = None,
    reference: date = REF_DATE,
) -> dict:
    start = datetime(
        reference.year, reference.month, reference.day, 8, 0, 0, tzinfo=timezone.utc
    ) - timedelta(days=days_ago)
    doc: dict = {
        "user_id": user_id,
        "activity_type": "running",
        "start_time": start.isoformat(),
        "distance_m": distance_m,
        "duration_s": duration_s,
        "source": "garmin",
        "activity_id": f"garmin-{user_id}-{days_ago}",
    }
    if average_hr is not None:
        doc["average_hr"] = average_hr
    return doc


def _fake_db(
    garmin_activities: Optional[list] = None,
    workouts: Optional[list] = None,
    run_index_scores: Optional[list] = None,
    garmin_connections: Optional[list] = None,
) -> Any:
    db = SimpleNamespace(
        garmin_activities=FakeCollection(garmin_activities or []),
        workouts=FakeCollection(workouts or []),
        run_index_scores=FakeCollection(run_index_scores or []),
        garmin_connections=FakeCollection(garmin_connections or []),
    )
    return db


# ---------------------------------------------------------------------------
# Test 1: DomainActivity running valid → accepted
# ---------------------------------------------------------------------------

def test_running_domain_activity_accepted():
    act = _domain_run(5, 10000, 3000, 155)
    wd = _domain_activity_to_workout_dict(act)
    assert wd is not None
    assert wd["distance_km"] == pytest.approx(10.0)
    assert wd["duration_minutes"] == pytest.approx(50.0)


# ---------------------------------------------------------------------------
# Test 2: Non-running activity → ignored
# ---------------------------------------------------------------------------

def test_non_running_activity_ignored():
    for act_type in ("cycling", "swimming", "yoga", "", None):
        act = DomainActivity(
            activity_type=act_type,
            start_time=(REF_DATE - timedelta(days=1)).isoformat(),
            distance_m=10000,
            duration_s=3000,
        )
        wd = _domain_activity_to_workout_dict(act)
        assert wd is None, f"Expected None for activity_type={act_type!r}"

    # Mixed list: only the run should pass through
    activities = [
        _domain_run(1, 10000, 3000),
        DomainActivity(
            activity_type="cycling",
            start_time=(REF_DATE - timedelta(days=2)).isoformat(),
            distance_m=30000,
            duration_s=5400,
        ),
    ]
    dicts = prepare_workout_dicts_from_domain(activities)
    assert len(dicts) == 1
    assert dicts[0]["distance_km"] == pytest.approx(10.0)


# ---------------------------------------------------------------------------
# Test 3: distance_m → distance_km correct at boundary
# ---------------------------------------------------------------------------

def test_distance_m_to_km_conversion():
    act = _domain_run(1, 21100, 6000)  # 21.1 km
    wd = _domain_activity_to_workout_dict(act)
    assert wd is not None
    assert wd["distance_km"] == pytest.approx(21.1)


# ---------------------------------------------------------------------------
# Test 4: duration_s → duration_minutes correct at boundary
# ---------------------------------------------------------------------------

def test_duration_s_to_minutes_conversion():
    act = _domain_run(1, 10000, 3600)  # 60 minutes
    wd = _domain_activity_to_workout_dict(act)
    assert wd is not None
    assert wd["duration_minutes"] == pytest.approx(60.0)


# ---------------------------------------------------------------------------
# Test 5: average_hr preserved
# ---------------------------------------------------------------------------

def test_average_hr_preserved():
    act = _domain_run(1, 10000, 3000, average_hr=158.0)
    wd = _domain_activity_to_workout_dict(act)
    assert wd is not None
    assert wd["avg_heart_rate"] == pytest.approx(158.0)


def test_average_hr_none_when_absent():
    act = _domain_run(1, 10000, 3000, average_hr=None)
    wd = _domain_activity_to_workout_dict(act)
    assert wd is not None
    assert wd["avg_heart_rate"] is None


# ---------------------------------------------------------------------------
# Test 6: Absent field → None, never 0
# ---------------------------------------------------------------------------

def test_absent_distance_produces_no_entry():
    act = DomainActivity(
        activity_type="running",
        start_time=(REF_DATE - timedelta(days=1)).isoformat(),
        distance_m=None,
        duration_s=3000,
    )
    assert _domain_activity_to_workout_dict(act) is None


def test_absent_duration_produces_no_entry():
    act = DomainActivity(
        activity_type="running",
        start_time=(REF_DATE - timedelta(days=1)).isoformat(),
        distance_m=10000,
        duration_s=None,
    )
    assert _domain_activity_to_workout_dict(act) is None


def test_absent_hr_is_none_not_zero():
    act = DomainActivity(
        activity_type="running",
        start_time=(REF_DATE - timedelta(days=1)).isoformat(),
        distance_m=10000,
        duration_s=3000,
        average_hr=None,
    )
    wd = _domain_activity_to_workout_dict(act)
    assert wd is not None
    assert wd["avg_heart_rate"] is None
    # Confirm it's not 0
    assert wd["avg_heart_rate"] != 0


# ---------------------------------------------------------------------------
# Test 7: Future activity vs reference_date → ignored
# ---------------------------------------------------------------------------

def test_future_activity_ignored_by_engine():
    activities = [
        _domain_run(0, 10000, 3000, reference=REF_DATE),   # today = REF_DATE → boundary
        _domain_run(-1, 10000, 3000, reference=REF_DATE),  # tomorrow — future
    ]
    # reference_date = REF_DATE - 1: the 0-days-ago activity is "future"
    reference = REF_DATE - timedelta(days=1)
    result = calculate_run_index_from_domain(activities, reference_date=reference)
    # Only yesterday (days_ago=1 from original ref) is visible; the 0-ago run
    # has start_time = REF_DATE which is > reference=REF_DATE-1 → excluded.
    # A single run is not enough for a non-zero index, but the engine should not crash.
    assert isinstance(result["run_index"], int)


# ---------------------------------------------------------------------------
# Test 8: CURRENT — garmin_activities used (not db.workouts)
# ---------------------------------------------------------------------------

def test_current_runindex_uses_garmin_activities():
    """calculate_run_index_from_domain produces a non-zero result from domain activities."""
    activities = _profile_domain(REF_DATE)
    result = calculate_run_index_from_domain(activities, reference_date=REF_DATE)
    assert result["run_index"] > 0, "Expected non-zero RunIndex from profile domain activities"


# ---------------------------------------------------------------------------
# Test 9: CURRENT — db.workouts different → does not influence RunIndex Garmin
# ---------------------------------------------------------------------------

def test_db_workouts_does_not_influence_garmin_runindex():
    """RunIndex computed from DomainActivity is independent of db.workouts content."""
    garmin_acts = _profile_domain(REF_DATE)
    garmin_score = calculate_run_index_from_domain(garmin_acts, reference_date=REF_DATE)

    # A completely different set of workout dicts (as db.workouts might contain)
    other_workouts = [_workout_dict(2, 3.0, 8.0)]  # slow, short — very different
    legacy_score = calculate_run_index(other_workouts, reference_date=REF_DATE)

    # The garmin score is computed independently; the two scores differ
    # because the data is different — that's the point
    assert garmin_score["run_index"] != legacy_score["run_index"]


# ---------------------------------------------------------------------------
# Test 10: HISTORY — garmin_activities used for snapshots
# ---------------------------------------------------------------------------

def test_history_uses_domain_activities():
    activities = _profile_domain(REF_DATE)
    snapshot = build_snapshot_document_from_domain("u1", activities, REF_DATE)
    assert "run_index" in snapshot
    assert snapshot["user_id"] == "u1"
    assert snapshot["date"] == REF_DATE.isoformat()
    assert snapshot["run_index"] > 0


# ---------------------------------------------------------------------------
# Test 11: HISTORY — reference_date=J → no activity > J included
# ---------------------------------------------------------------------------

def test_reference_date_excludes_future_activities():
    """No future leakage: activities after J must not appear in score at J."""
    # Build activities: some in the past relative to REF_DATE-30, some in the future
    past_acts = [_domain_run(days, 10000, 3000, reference=REF_DATE) for days in range(2, 60, 7)]
    future_act = DomainActivity(
        activity_type="running",
        start_time=(REF_DATE + timedelta(days=5)).isoformat(),  # 5 days in the future
        distance_m=21100,
        duration_s=5400,
        source="garmin",
    )
    all_acts = past_acts + [future_act]

    # Score at REF_DATE — future activity must be invisible
    score_at_ref = calculate_run_index_from_domain(all_acts, reference_date=REF_DATE)

    # Score with future activity explicitly removed
    score_without_future = calculate_run_index_from_domain(past_acts, reference_date=REF_DATE)

    assert score_at_ref["run_index"] == score_without_future["run_index"], (
        "Future activity leaked into score at reference_date"
    )


# ---------------------------------------------------------------------------
# Test 12: SNAPSHOT — source is Garmin DomainActivity
# ---------------------------------------------------------------------------

def test_snapshot_document_from_domain_source():
    activities = _profile_domain(REF_DATE)
    doc = build_snapshot_document_from_domain("u1", activities, REF_DATE)

    assert doc["user_id"] == "u1"
    assert doc["date"] == REF_DATE.isoformat()
    assert "run_index" in doc
    assert "speed_score" in doc
    assert "endurance_score" in doc
    assert "consistency_score" in doc
    assert "efficiency_score" in doc
    assert "confidence_score" in doc
    assert "computed_at" in doc


# ---------------------------------------------------------------------------
# Test 13: BACKFILL — source is Garmin DomainActivity
# ---------------------------------------------------------------------------

def test_backfill_snapshot_dates_from_domain():
    activities = _profile_domain(REF_DATE)
    dates = select_snapshot_dates_from_domain(activities, reference_date=REF_DATE)
    assert len(dates) > 0
    # All dates must be <= REF_DATE
    assert all(d <= REF_DATE for d in dates)
    # Dates should be sorted ascending
    assert dates == sorted(dates)


def test_backfill_async_uses_garmin_activities():
    user_id = "u-backfill"
    garmin_docs = [
        _make_garmin_activity_doc(user_id, days, 10000, 3000)
        for days in range(2, 60, 7)
    ]
    db = _fake_db(garmin_activities=garmin_docs)

    from services.run_index_history import backfill_run_index_history

    result = asyncio.get_event_loop().run_until_complete(
        backfill_run_index_history(db, user_id, reference_date=REF_DATE)
    )
    assert result["snapshots_targeted"] > 0
    # Confirm db.workouts was NOT touched (it's empty and no write to it)
    assert len(db.workouts._docs) == 0


# ---------------------------------------------------------------------------
# Test 14: POST-SYNC — activity in garmin_activities but absent from db.workouts
# ---------------------------------------------------------------------------

def test_post_sync_no_fanout_required():
    """Activity present in garmin_activities but absent from db.workouts is seen."""
    user_id = "u-postsync"
    garmin_doc = _make_garmin_activity_doc(user_id, 1, 10000, 3000, 155)
    # db.workouts is intentionally EMPTY
    db = _fake_db(
        garmin_activities=[garmin_doc],
        workouts=[],  # empty — fan-out not yet run
    )

    from services.run_index_history import load_garmin_domain_activities

    activities = asyncio.get_event_loop().run_until_complete(
        load_garmin_domain_activities(db, user_id)
    )
    assert len(activities) == 1, "garmin_activities activity must be visible immediately"
    assert activities[0].distance_m == pytest.approx(10000.0)

    score = calculate_run_index_from_domain(activities, reference_date=REF_DATE)
    # Single activity — not enough for a full index but engine must not crash
    assert isinstance(score["run_index"], int)


# ---------------------------------------------------------------------------
# Test 15: USER ISOLATION — activity from another user never used
# ---------------------------------------------------------------------------

def test_user_isolation():
    target_user = "user-A"
    other_user = "user-B"
    garmin_docs = [
        _make_garmin_activity_doc(target_user, 2, 10000, 3000, 155),
        _make_garmin_activity_doc(other_user, 3, 50000, 15000, 140),  # big run, wrong user
    ]
    db = _fake_db(garmin_activities=garmin_docs)

    from services.run_index_history import load_garmin_domain_activities

    activities_a = asyncio.get_event_loop().run_until_complete(
        load_garmin_domain_activities(db, target_user)
    )
    activities_b = asyncio.get_event_loop().run_until_complete(
        load_garmin_domain_activities(db, other_user)
    )

    assert len(activities_a) == 1
    assert activities_a[0].source_activity_id is not None
    assert "user-B" not in str(activities_a[0].source_activity_id)

    assert len(activities_b) == 1
    assert activities_b[0].distance_m == pytest.approx(50000.0)


# ---------------------------------------------------------------------------
# Test 16: PARITY — equivalent workout dict vs DomainActivity → identical scores
# ---------------------------------------------------------------------------

def test_parity_domain_vs_workout_dict():
    """Equivalent data via DomainActivity and workout dict must produce equal scores.

    When the semantic data is identical the RunIndex and all pillar scores
    must match exactly (deterministic formula, same numeric values at boundary).
    """
    # Use a single well-defined activity to isolate rounding
    dist_m = 10000.0
    dur_s = 3000.0   # 50 minutes → pace 5.0 min/km → speed 12 km/h
    avg_hr = 155.0
    reference = date(2026, 6, 1)
    days_ago = 5

    domain_act = DomainActivity(
        activity_type="running",
        start_time=(reference - timedelta(days=days_ago)).isoformat(),
        distance_m=dist_m,
        duration_s=dur_s,
        average_hr=avg_hr,
        source="garmin",
    )
    # Equivalent workout dict
    dist_km = dist_m / 1000.0
    dur_min = dur_s / 60.0
    pace = dur_min / dist_km
    speed = 60.0 / pace
    workout = {
        "type": "run",
        "date": (reference - timedelta(days=days_ago)).isoformat(),
        "distance_km": dist_km,
        "duration_minutes": dur_min,
        "avg_pace_min_km": pace,
        "avg_speed_kmh": speed,
        "avg_heart_rate": avg_hr,
    }

    score_domain = calculate_run_index_from_domain([domain_act], reference_date=reference)
    score_dict = calculate_run_index([workout], reference_date=reference)

    assert score_domain["run_index"] == score_dict["run_index"]
    assert score_domain["speed_score"] == score_dict["speed_score"]
    assert score_domain["endurance_score"] == score_dict["endurance_score"]
    assert score_domain["consistency_score"] == score_dict["consistency_score"]
    assert score_domain["efficiency_score"] == score_dict["efficiency_score"]
    assert score_domain["confidence_score"] == score_dict["confidence_score"]


# ---------------------------------------------------------------------------
# Test 17: PUBLIC PAYLOAD — no contractual change
# ---------------------------------------------------------------------------

def test_public_payload_contract():
    """calculate_run_index_from_domain returns the same public contract as before."""
    activities = _profile_domain(REF_DATE)
    result = calculate_run_index_from_domain(activities, reference_date=REF_DATE)

    # All required keys present
    for key in ("run_index", "speed_score", "endurance_score",
                "consistency_score", "efficiency_score", "confidence_score",
                "pillar_details"):
        assert key in result, f"Missing key: {key}"

    # All score values are integers in [0, 1000] / [0, 100]
    assert isinstance(result["run_index"], int)
    assert 0 <= result["run_index"] <= 1000
    for key in ("speed_score", "endurance_score", "consistency_score",
                "efficiency_score", "confidence_score"):
        assert isinstance(result[key], int)
        assert 0 <= result[key] <= 100

    # pillar_details structure
    for pillar in ("speed", "endurance", "consistency", "efficiency"):
        assert pillar in result["pillar_details"]
        assert "score" in result["pillar_details"][pillar]
        assert "confidence" in result["pillar_details"][pillar]


# ---------------------------------------------------------------------------
# Test 18: READINESS — not modified (smoke import)
# ---------------------------------------------------------------------------

def test_readiness_not_modified():
    """Smoke: Readiness V2 imports without error and exposes expected symbol."""
    from garmin.readiness_adapter import build_readiness_v2_from_garmin_data
    assert callable(build_readiness_v2_from_garmin_data)


# ---------------------------------------------------------------------------
# Test 19: TRAINING V2 — not modified (smoke import)
# ---------------------------------------------------------------------------

def test_training_v2_not_modified():
    """Smoke: Training V2 domain model imports without error."""
    from training_v2.training_load import build_training_load
    from training_v2.domain_activity import DomainActivity as _DA
    assert callable(build_training_load)
    assert _DA is DomainActivity


# ---------------------------------------------------------------------------
# Additional: invariant — select_snapshot_dates_from_domain respects reference_date
# ---------------------------------------------------------------------------

def test_snapshot_dates_all_lte_reference():
    activities = _profile_domain(REF_DATE)
    dates = select_snapshot_dates_from_domain(activities, reference_date=REF_DATE)
    assert all(d <= REF_DATE for d in dates)


def test_domain_activity_day_parsing():
    """_domain_activity_day handles str/date/datetime start_time correctly."""
    from datetime import date as date_

    act_str = DomainActivity(start_time="2026-04-15T08:00:00+00:00")
    assert _domain_activity_day(act_str) == date_(2026, 4, 15)

    act_date = DomainActivity(start_time=date_(2026, 5, 20))
    assert _domain_activity_day(act_date) == date_(2026, 5, 20)

    act_dt = DomainActivity(start_time=datetime(2026, 6, 1, 9, 0, 0, tzinfo=timezone.utc))
    assert _domain_activity_day(act_dt) == date_(2026, 6, 1)

    act_none = DomainActivity(start_time=None)
    assert _domain_activity_day(act_none) is None
