"""R3.5 — Training Load V2 alignment tests for /run-index.

Verifies the requirements from the R3.5 problem statement:
A. payload["metrics"]["training_load"] == build_training_load(activities, ref).acwr
B. payload["metrics"]["training_load_v2"]["acwr"] == snapshot.acwr
C. payload["metrics"]["training_load_v2"]["acute_load_7d"] == snapshot.acute_load_7d
D. payload["metrics"]["training_load_v2"]["load_28d"] == snapshot.load_28d
E. payload["metrics"]["training_load_v2"]["previous_7d_load"] == snapshot.previous_7d_load
F. payload["metrics"]["training_load_v2"]["load_change_percent"] == snapshot.load_change_percent
G. no valid activities → training_load is None, training_load_v2.acwr is None,
   training_load_status == "gray"
H. distance present but duration absent → no load invented, training_load is None
I. multi-user: compute_run_index(userA) does not use userB activities

Additionally:
- Readiness score unchanged when snapshot is shared vs. computed internally
- No fictitious 1.0 ACWR fallback when load is unavailable
- Distance is never used as a duration fallback for load computation
- load_snapshot parameter accepted by build_readiness_v2_from_garmin_data
"""

from __future__ import annotations

import sys
from datetime import date, timedelta
from pathlib import Path
from typing import List, Optional

import pytest

_BACKEND = Path(__file__).resolve().parent.parent
if str(_BACKEND) not in sys.path:
    sys.path.insert(0, str(_BACKEND))

from garmin.insights import compute_run_index, _acwr_status_to_color
from garmin.readiness_adapter import build_readiness_v2_from_garmin_data
from training_v2.training_load import build_training_load, TrainingLoadSnapshot

# ---------------------------------------------------------------------------
# Shared constants
# ---------------------------------------------------------------------------

_REF = date(2026, 1, 28)
_USER_A = "user_alpha"
_USER_B = "user_beta"


# ---------------------------------------------------------------------------
# Fake DB infrastructure (deterministic, multi-user aware)
# ---------------------------------------------------------------------------


class _FakeQuery:
    """Chainable fake MongoDB query that returns a fixed list via to_list()."""

    def __init__(self, docs: List[dict]) -> None:
        self._docs = docs

    def sort(self, *args, **kwargs) -> "_FakeQuery":
        return self

    def limit(self, n: int) -> "_FakeQuery":
        self._docs = self._docs[:n]
        return self

    async def to_list(self, length: int = None) -> List[dict]:
        return list(self._docs)


class _FakeCollection:
    """Fake MongoDB collection whose find() filters by user_id."""

    def __init__(self, all_docs: List[dict]) -> None:
        self._all = all_docs

    def find(self, filter_: dict, projection: dict = None) -> _FakeQuery:
        uid = filter_.get("user_id")
        docs = [d for d in self._all if d.get("user_id") == uid] if uid else list(self._all)
        return _FakeQuery(docs)


class _FakeDB:
    """Fake async DB with garmin_daily_metrics and garmin_activities collections."""

    def __init__(
        self,
        metrics_docs: List[dict],
        activity_docs: List[dict],
    ) -> None:
        self.garmin_daily_metrics = _FakeCollection(metrics_docs)
        self.garmin_activities = _FakeCollection(activity_docs)


# ---------------------------------------------------------------------------
# Helper builders
# ---------------------------------------------------------------------------


def _metrics_docs(
    user_id: str,
    *,
    n: int = 14,
    rhr: Optional[float] = 52.0,
    hrv: Optional[float] = 65.0,
    sleep_hours: Optional[float] = 7.5,
    sleep_score: Optional[float] = 80.0,
    ref: date = _REF,
) -> List[dict]:
    docs = []
    for i in range(n):
        d = ref - timedelta(days=i)
        docs.append({
            "user_id": user_id,
            "date": d.isoformat(),
            "resting_hr": rhr,
            "hrv": hrv,
            "sleep_hours": sleep_hours,
            "sleep_score": sleep_score,
        })
    return docs


def _activity_docs(
    user_id: str,
    *,
    n: int = 28,
    duration_s: float = 2400.0,
    distance_m: Optional[float] = 6000.0,
    include_duration: bool = True,
    ref: date = _REF,
) -> List[dict]:
    acts = []
    for i in range(n):
        d = ref - timedelta(days=i)
        act: dict = {
            "user_id": user_id,
            "activity_type": "running",
            "start_time": f"{d.isoformat()}T08:00:00",
        }
        if include_duration:
            act["duration_s"] = duration_s
        if distance_m is not None:
            act["distance_m"] = distance_m
        acts.append(act)
    return acts


# ---------------------------------------------------------------------------
# A. payload["metrics"]["training_load"] == build_training_load(activities, ref).acwr
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_A_training_load_equals_snapshot_acwr():
    """A. metrics.training_load == round(build_training_load(activities, ref).acwr, 3)."""
    acts = _activity_docs(_USER_A)
    db = _FakeDB(_metrics_docs(_USER_A), acts)
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None

    # Compute the expected snapshot independently
    snapshot = build_training_load(acts, _REF)
    assert snapshot.acwr is not None

    expected = round(snapshot.acwr, 3)
    assert payload["metrics"]["training_load"] == expected


# ---------------------------------------------------------------------------
# B. payload["metrics"]["training_load_v2"]["acwr"] == snapshot.acwr
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_B_training_load_v2_acwr_matches_snapshot():
    """B. metrics.training_load_v2.acwr == build_training_load(activities, ref).acwr."""
    acts = _activity_docs(_USER_A)
    db = _FakeDB(_metrics_docs(_USER_A), acts)
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None

    snapshot = build_training_load(acts, _REF)
    assert payload["metrics"]["training_load_v2"]["acwr"] == snapshot.acwr


# ---------------------------------------------------------------------------
# C. payload["metrics"]["training_load_v2"]["acute_load_7d"] == snapshot.acute_load_7d
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_C_training_load_v2_acute_load_7d():
    """C. metrics.training_load_v2.acute_load_7d == snapshot.acute_load_7d."""
    acts = _activity_docs(_USER_A)
    db = _FakeDB(_metrics_docs(_USER_A), acts)
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None

    snapshot = build_training_load(acts, _REF)
    assert payload["metrics"]["training_load_v2"]["acute_load_7d"] == snapshot.acute_load_7d


# ---------------------------------------------------------------------------
# D. payload["metrics"]["training_load_v2"]["load_28d"] == snapshot.load_28d
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_D_training_load_v2_load_28d():
    """D. metrics.training_load_v2.load_28d == snapshot.load_28d."""
    acts = _activity_docs(_USER_A)
    db = _FakeDB(_metrics_docs(_USER_A), acts)
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None

    snapshot = build_training_load(acts, _REF)
    assert payload["metrics"]["training_load_v2"]["load_28d"] == snapshot.load_28d


# ---------------------------------------------------------------------------
# E. payload["metrics"]["training_load_v2"]["previous_7d_load"] == snapshot.previous_7d_load
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_E_training_load_v2_previous_7d_load():
    """E. metrics.training_load_v2.previous_7d_load == snapshot.previous_7d_load."""
    acts = _activity_docs(_USER_A)
    db = _FakeDB(_metrics_docs(_USER_A), acts)
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None

    snapshot = build_training_load(acts, _REF)
    assert payload["metrics"]["training_load_v2"]["previous_7d_load"] == snapshot.previous_7d_load


# ---------------------------------------------------------------------------
# F. payload["metrics"]["training_load_v2"]["load_change_percent"] == snapshot.load_change_percent
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_F_training_load_v2_load_change_percent():
    """F. metrics.training_load_v2.load_change_percent == snapshot.load_change_percent."""
    acts = _activity_docs(_USER_A)
    db = _FakeDB(_metrics_docs(_USER_A), acts)
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None

    snapshot = build_training_load(acts, _REF)
    assert payload["metrics"]["training_load_v2"]["load_change_percent"] == snapshot.load_change_percent


# ---------------------------------------------------------------------------
# G. no valid activities → training_load is None, acwr is None, status gray
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_G_no_activities_training_load_none_status_gray():
    """G. no valid activities → training_load is None, training_load_v2.acwr is None,
    training_load_status == 'gray'."""
    db = _FakeDB(_metrics_docs(_USER_A), [])
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None

    m = payload["metrics"]
    assert m["training_load"] is None, "training_load must be None when no activities"
    assert m["training_load_v2"]["acwr"] is None, "training_load_v2.acwr must be None"
    assert m["training_load_status"] == "gray", "training_load_status must be gray"


# ---------------------------------------------------------------------------
# H. distance present but duration absent → no load invented, training_load is None
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_H_distance_only_no_load():
    """H. activities with distance but no duration → training_load is None (no fabrication)."""
    acts = _activity_docs(_USER_A, include_duration=False, distance_m=6000.0)
    db = _FakeDB(_metrics_docs(_USER_A), acts)
    payload = await compute_run_index(db, _USER_A, reference_date=_REF)
    assert payload is not None

    m = payload["metrics"]
    assert m["training_load"] is None, "distance without duration must not produce a load"
    assert m["training_load_v2"]["acwr"] is None
    assert m["training_load_v2"]["acute_load_7d"] == 0.0
    assert m["training_load_v2"]["load_28d"] == 0.0


# ---------------------------------------------------------------------------
# I. multi-user: compute_run_index(userA) does not use userB activities
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_I_multi_user_isolation():
    """I. userA result is independent of userB activities."""
    acts_a = _activity_docs(_USER_A, duration_s=1800.0)
    acts_b = _activity_docs(_USER_B, duration_s=3600.0)
    metrics_a = _metrics_docs(_USER_A)
    metrics_b = _metrics_docs(_USER_B)

    # DB contains docs for both users
    all_metrics = metrics_a + metrics_b
    all_acts = acts_a + acts_b
    db = _FakeDB(all_metrics, all_acts)

    payload_a = await compute_run_index(db, _USER_A, reference_date=_REF)
    payload_b = await compute_run_index(db, _USER_B, reference_date=_REF)

    assert payload_a is not None
    assert payload_b is not None

    # Expected snapshots from each user's activities alone
    snap_a = build_training_load(acts_a, _REF)
    snap_b = build_training_load(acts_b, _REF)

    # userA payload must match userA-only snapshot
    assert payload_a["metrics"]["training_load_v2"]["acute_load_7d"] == snap_a.acute_load_7d
    assert payload_a["metrics"]["training_load_v2"]["load_28d"] == snap_a.load_28d
    assert payload_a["metrics"]["training_load_v2"]["acwr"] == snap_a.acwr

    # userB payload must match userB-only snapshot
    assert payload_b["metrics"]["training_load_v2"]["acute_load_7d"] == snap_b.acute_load_7d
    assert payload_b["metrics"]["training_load_v2"]["load_28d"] == snap_b.load_28d
    assert payload_b["metrics"]["training_load_v2"]["acwr"] == snap_b.acwr

    # The two payloads must differ (userA sessions are shorter → less load)
    assert snap_a.acute_load_7d != snap_b.acute_load_7d



# ---------------------------------------------------------------------------
# Helper builders for pure unit tests (no DB, no user_id)
# ---------------------------------------------------------------------------


def _metrics(
    *,
    n: int = 14,
    rhr: Optional[float] = 52.0,
    hrv: Optional[float] = 65.0,
    sleep_hours: Optional[float] = 7.5,
    sleep_score: Optional[float] = 80.0,
    ref: date = _REF,
) -> List[dict]:
    docs = []
    for i in range(n):
        d = ref - timedelta(days=i)
        docs.append({
            "date": d.isoformat(),
            "resting_hr": rhr,
            "hrv": hrv,
            "sleep_hours": sleep_hours,
            "sleep_score": sleep_score,
        })
    return docs


def _activities(
    *,
    n: int = 28,
    duration_s: float = 2400.0,
    distance_m: Optional[float] = 6000.0,
    include_duration: bool = True,
    ref: date = _REF,
) -> List[dict]:
    acts = []
    for i in range(n):
        d = ref - timedelta(days=i)
        act: dict = {
            "activity_type": "running",
            "start_time": f"{d.isoformat()}T08:00:00",
        }
        if include_duration:
            act["duration_s"] = duration_s
        if distance_m is not None:
            act["distance_m"] = distance_m
        acts.append(act)
    return acts


# ---------------------------------------------------------------------------
# 2. No fallback 1.0 when load is unavailable
# ---------------------------------------------------------------------------


def test_no_acwr_fallback_when_no_activities():
    """No activities → acwr is None, not 1.0."""
    snapshot = build_training_load([], _REF)
    assert snapshot.acwr is None
    assert snapshot.status == "unavailable"
    assert snapshot.is_available is False


def test_training_load_none_when_no_chronic_load():
    """No activities → chronic_weekly_load == 0 → acwr is None (no fallback)."""
    snapshot = build_training_load([], _REF)
    assert snapshot.acwr is None


def test_acwr_not_invented_when_distance_only():
    """Activities with distance_m but no duration_s contribute NO load (no fallback)."""
    acts = _activities(include_duration=False, distance_m=6000.0)
    snapshot = build_training_load(acts, _REF)
    # No valid duration → no load → acwr is None
    assert snapshot.acwr is None
    assert snapshot.acute_load_7d == 0.0
    assert snapshot.load_28d == 0.0


# ---------------------------------------------------------------------------
# 3. Distance is never used as duration fallback
# ---------------------------------------------------------------------------


def test_distance_only_produces_zero_load():
    """Load is 0 when only distance is present (no duration)."""
    acts = _activities(include_duration=False, distance_m=10_000.0)
    snapshot = build_training_load(acts, _REF)
    assert snapshot.acute_load_7d == 0.0
    assert snapshot.load_28d == 0.0


def test_duration_drives_load_not_distance():
    """Same duration, wildly different distances → load stays the same."""
    def _make(dist_m: float) -> List[dict]:
        return [
            {
                "activity_type": "running",
                "start_time": f"{(_REF - timedelta(days=i)).isoformat()}T08:00:00",
                "duration_s": 3000.0,
                "distance_m": dist_m,
            }
            for i in range(14)
        ]

    s1 = build_training_load(_make(5_000.0), _REF)
    s2 = build_training_load(_make(50_000.0), _REF)
    assert s1.acute_load_7d == s2.acute_load_7d
    assert s1.load_28d == s2.load_28d


# ---------------------------------------------------------------------------
# 4. Readiness score unchanged when snapshot is passed vs. computed internally
# ---------------------------------------------------------------------------


def test_readiness_score_unchanged_with_shared_snapshot():
    """Passing a pre-built snapshot gives the same ReadinessResult as not passing one."""
    acts = _activities()
    metrics_docs = _metrics()
    snapshot = build_training_load(acts, _REF)

    r_shared = build_readiness_v2_from_garmin_data(
        metrics_docs, acts, _REF, load_snapshot=snapshot
    )
    r_internal = build_readiness_v2_from_garmin_data(metrics_docs, acts, _REF)

    assert r_shared == r_internal


def test_readiness_score_deterministic_across_calls():
    """build_readiness_v2_from_garmin_data is deterministic for same inputs."""
    acts = _activities()
    metrics_docs = _metrics()
    snapshot = build_training_load(acts, _REF)
    r1 = build_readiness_v2_from_garmin_data(
        metrics_docs, acts, _REF, load_snapshot=snapshot
    )
    r2 = build_readiness_v2_from_garmin_data(
        metrics_docs, acts, _REF, load_snapshot=snapshot
    )
    assert r1 == r2


# ---------------------------------------------------------------------------
# 5. Multi-user isolation
# ---------------------------------------------------------------------------


def test_multi_user_isolation():
    """Snapshots for different activity sets are independent."""
    acts_a = _activities(duration_s=1800.0)  # 30 min sessions
    acts_b = _activities(duration_s=3600.0)  # 60 min sessions

    snap_a = build_training_load(acts_a, _REF)
    snap_b = build_training_load(acts_b, _REF)

    assert snap_a.acute_load_7d != snap_b.acute_load_7d
    assert snap_a.load_28d != snap_b.load_28d

    # Readiness results are also independent.
    m = _metrics()
    r_a = build_readiness_v2_from_garmin_data(m, acts_a, _REF, load_snapshot=snap_a)
    r_b = build_readiness_v2_from_garmin_data(m, acts_b, _REF, load_snapshot=snap_b)
    # Each result must match building internally from the same activities —
    # confirms the passed snapshot is used and not bleed from the other user.
    r_a_check = build_readiness_v2_from_garmin_data(m, acts_a, _REF)
    r_b_check = build_readiness_v2_from_garmin_data(m, acts_b, _REF)
    assert r_a == r_a_check
    assert r_b == r_b_check


# ---------------------------------------------------------------------------
# 6. frontend null-safety: training_load == None when acwr is unavailable
# ---------------------------------------------------------------------------


def test_snapshot_acwr_none_means_no_load():
    """When acwr is None the snapshot clearly signals unavailability."""
    snapshot = build_training_load([], _REF)
    assert snapshot.acwr is None
    # The value exposed as training_load in the response would be None (not 1.0).
    # Simulate the mapping applied in compute_run_index:
    training_load_response = round(snapshot.acwr, 3) if snapshot.acwr is not None else None
    assert training_load_response is None


# ---------------------------------------------------------------------------
# 7. training_load_v2 block fields are consistent
# ---------------------------------------------------------------------------


def test_training_load_v2_block_consistency():
    """Snapshot fields are internally consistent."""
    acts = _activities()
    snap = build_training_load(acts, _REF)

    # chronic_weekly_load == load_28d / 4
    assert abs(snap.chronic_weekly_load - snap.load_28d / 4.0) < 1e-6

    # acwr == acute / chronic_weekly when both > 0
    if snap.chronic_weekly_load > 0:
        expected_acwr = round(snap.acute_load_7d / snap.chronic_weekly_load, 3)
        assert snap.acwr == expected_acwr

    # load_change_percent is None iff previous_7d_load == 0
    if snap.previous_7d_load == 0.0:
        assert snap.load_change_percent is None
    else:
        assert snap.load_change_percent is not None


def test_training_load_v2_block_no_activities():
    """Snapshot fields when no activities: all zero, acwr/load_change_percent None."""
    snap = build_training_load([], _REF)
    assert snap.acute_load_7d == 0.0
    assert snap.load_28d == 0.0
    assert snap.chronic_weekly_load == 0.0
    assert snap.previous_7d_load == 0.0
    assert snap.acwr is None
    assert snap.load_change_percent is None
    assert snap.status == "unavailable"
    assert snap.confidence == "none"


# ---------------------------------------------------------------------------
# 8. _acwr_status_to_color helper
# ---------------------------------------------------------------------------


def test_acwr_status_to_color_mapping():
    assert _acwr_status_to_color("balanced") == "green"
    assert _acwr_status_to_color("elevated") == "yellow"
    assert _acwr_status_to_color("high") == "red"
    assert _acwr_status_to_color("low") == "yellow"
    assert _acwr_status_to_color("very_low") == "yellow"
    assert _acwr_status_to_color("unavailable") == "gray"
    assert _acwr_status_to_color("unknown_future_label") == "gray"
