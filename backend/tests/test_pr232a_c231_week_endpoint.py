"""C231 — End-to-end tests for GET /training/v2/week (real FastAPI handler).

Verifies the endpoint-level wiring introduced for the C231 audit:
- unmatched_actuals scoped to the current week only.
- a prescription snapshot is persisted the first time a past/today session
  is served, and read back (not recomputed) on subsequent calls.
- /training/today no longer reads or returns `training_feedback`.

Uses the same in-memory fake DB + httpx ASGITransport pattern as
test_handlers_pr228.py.

Run from the backend directory:
    python -m pytest tests/test_pr232a_c231_week_endpoint.py -q
"""
from __future__ import annotations

import os
import sys
from datetime import datetime, date, timedelta, timezone
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest

os.environ.setdefault("JWT_SECRET_KEY", "test-pr232a-c231-secret-32chars!!")
os.environ.setdefault("JWT_SECRET", "test-pr232a-c231-secret-32chars!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

if "config" in sys.modules:
    _config_mod = sys.modules["config"]
    _config_file = getattr(_config_mod, "__file__", "") or ""
    if "__path__" not in dir(_config_mod) or _BACKEND_DIR not in _config_file:
        for _key in [k for k in sys.modules if k == "config" or k.startswith("config.")]:
            del sys.modules[_key]

import server  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402
from access_control import Tier, UserAccess  # noqa: E402

try:
    import httpx
except ImportError:
    httpx = None  # type: ignore

pytestmark = pytest.mark.asyncio

_USER_ID = "pr232a-c231-user"
_USER_EMAIL = "pr232a-c231@example.com"
_MONDAY = date(2025, 9, 15)


class _UpdateResult:
    matched_count = 1
    modified_count = 1


class _Collection:
    def __init__(self, docs: Optional[List[dict]] = None) -> None:
        self._docs: List[dict] = list(docs or [])

    def _match(self, doc: dict, query: dict) -> bool:
        for k, v in query.items():
            if isinstance(v, dict):
                continue
            if doc.get(k) != v:
                return False
        return True

    async def find_one(self, query: dict, projection: Optional[dict] = None) -> Optional[dict]:
        q = {k: v for k, v in query.items() if not isinstance(v, dict)}
        for doc in self._docs:
            if self._match(doc, q):
                return dict(doc)
        return None

    class _Cursor:
        def __init__(self, docs: List[dict]) -> None:
            self._docs = docs

        def sort(self, *_a: Any, **_kw: Any) -> "_Collection._Cursor":
            return self

        def limit(self, n: int) -> "_Collection._Cursor":
            self._docs = self._docs[:n]
            return self

        async def to_list(self, length: Optional[int] = None) -> List[dict]:
            if length is not None:
                return list(self._docs[:length])
            return list(self._docs)

    def find(self, query: Optional[dict] = None, projection: Optional[dict] = None) -> "_Collection._Cursor":
        q = {k: v for k, v in (query or {}).items() if not isinstance(v, dict)}
        results = [d for d in self._docs if self._match(d, q)]
        return self._Cursor(results)

    async def update_one(self, query: dict, update: dict, upsert: bool = False) -> _UpdateResult:
        q = {k: v for k, v in query.items() if not isinstance(v, dict)}
        for doc in self._docs:
            if self._match(doc, q):
                doc.update(update.get("$set", {}))
                return _UpdateResult()
        if upsert:
            new_doc = {**q, **update.get("$set", {}), **update.get("$setOnInsert", {})}
            self._docs.append(new_doc)
        return _UpdateResult()

    async def insert_one(self, doc: dict) -> None:
        self._docs.append(dict(doc))

    async def count_documents(self, query: dict) -> int:
        q = {k: v for k, v in query.items() if not isinstance(v, dict)}
        return sum(1 for d in self._docs if self._match(d, q))

    async def create_index(self, *_a: Any, **_kw: Any) -> None:
        pass


class _FakeDB:
    def __init__(self) -> None:
        self.training_cycles: _Collection = _Collection()
        self.training_prefs: _Collection = _Collection()
        self.user_goals: _Collection = _Collection()
        self.garmin_activities: _Collection = _Collection()
        self.garmin_connections: _Collection = _Collection()
        self.user_profiles: _Collection = _Collection()
        self.training_feedback: _Collection = _Collection()
        self.training_prescription_snapshots: _Collection = _Collection()

    def __getattr__(self, name: str) -> _Collection:
        col: _Collection = _Collection()
        object.__setattr__(self, name, col)
        return col


def _bearer() -> dict:
    return {"Authorization": "Bearer " + create_access_token(_USER_ID, _USER_EMAIL)}


def _user_access(_db: Any, user_id: str) -> UserAccess:
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


def _make_fixed_datetime_class(fixed: datetime) -> type:
    class _FixedDT(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return fixed if tz is not None else fixed.replace(tzinfo=None)
    _FixedDT.__name__ = "_FixedDT"
    _FixedDT.__qualname__ = "_FixedDT"
    return _FixedDT


def _patches(fake_db: _FakeDB, reference_date: date = _MONDAY) -> list:
    fixed_dt = datetime(
        reference_date.year, reference_date.month, reference_date.day,
        8, 0, 0, tzinfo=timezone.utc,
    )
    return [
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_user_access)),
        patch("server.datetime", _make_fixed_datetime_class(fixed_dt)),
    ]


async def _get_week(fake_db: _FakeDB, reference_date: date = _MONDAY) -> Dict:
    if httpx is None:
        pytest.skip("httpx not installed")
    ps = _patches(fake_db, reference_date)
    started = []
    try:
        for p in ps:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
        ) as client:
            r = await client.get("/api/training/v2/week", headers=_bearer())
            return {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text}
    finally:
        for p in reversed(started):
            p.stop()


async def _get_today(fake_db: _FakeDB, reference_date: date = _MONDAY) -> Dict:
    if httpx is None:
        pytest.skip("httpx not installed")
    ps = _patches(fake_db, reference_date)
    started = []
    try:
        for p in ps:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
        ) as client:
            r = await client.get("/api/training/today", headers=_bearer())
            return {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text}
    finally:
        for p in reversed(started):
            p.stop()


@pytest.mark.asyncio
async def test_c234_paces_uses_garmin_local_reference_date_at_utc_midnight():
    """The paces endpoint must share Today/Week's local Garmin clock."""
    fake_db = _FakeDB()
    _seed_connected(fake_db, connected=True)
    fake_db.garmin_activities._docs.append({
        "user_id": _USER_ID,
        "start_time": "2025-09-15 08:00:00",
        "garmin_activity": {
            "start_time": "2025-09-15 06:00:00",
            "start_time_local": "2025-09-15 08:00:00",
        },
    })
    captured = {}

    async def _load(_db, *, user_id, reference_date):
        captured["reference_date"] = reference_date
        from training_v2.training_paces import compute_training_paces
        return compute_training_paces([], reference_date, user_max_hr=None)

    fixed_dt = datetime(2025, 9, 15, 22, 30, tzinfo=timezone.utc)
    patches = [
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_user_access)),
        patch("server.datetime", _make_fixed_datetime_class(fixed_dt)),
        patch("training_v2.training_paces_authority.load_canonical_training_paces", _load),
    ]
    started = []
    try:
        for p in patches:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
        ) as client:
            response = await client.get("/api/training/v2/paces", headers=_bearer())
        assert response.status_code == 200, response.text
    finally:
        for p in reversed(started):
            p.stop()

    assert captured["reference_date"] == date(2025, 9, 16)


def _seed_cycle(fake_db: _FakeDB, goal: str = "SEMI", reference_date: date = _MONDAY, race_weeks_ahead: int = 16) -> None:
    cycle_start = (reference_date - timedelta(weeks=4)).isoformat()
    fake_db.training_cycles._docs.append({
        "user_id": _USER_ID, "goal": goal, "start_date": cycle_start,
    })
    race_date = (reference_date + timedelta(weeks=race_weeks_ahead)).isoformat()
    fake_db.user_goals._docs.append({
        "user_id": _USER_ID, "distance_type": "semi", "event_date": race_date,
    })


def _seed_garmin_activities(fake_db: _FakeDB, n: int = 8, km_per: float = 8.0, reference_date: date = _MONDAY) -> None:
    for i in range(n):
        act_date = reference_date - timedelta(days=7 + i * 2)
        fake_db.garmin_activities._docs.append({
            "user_id": _USER_ID,
            "source": "garmin",
            "activity_id": f"seed-{i}",
            "activity_type": "running",
            "start_time": act_date.isoformat() + " 07:00:00",
            "garmin_activity": {"start_time_local": act_date.isoformat() + " 07:00:00"},
            "distance_m": km_per * 1000.0,
            "duration_s": km_per * 360,
            "average_hr": 145,
        })


def _seed_connected(fake_db: _FakeDB, connected: bool = True) -> None:
    fake_db.garmin_connections._docs.append({"user_id": _USER_ID, "connected": connected})


@pytest.mark.asyncio
async def test_week_endpoint_persists_snapshot_for_todays_session():
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    result = await _get_week(fake_db)
    assert result["status"] == 200, result["body"]

    monday_session = next(
        s for s in result["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    assert monday_session["planned_date"] == _MONDAY.isoformat()

    # A snapshot must now exist for Monday's session (today == planned_date).
    snapshot_docs = fake_db.training_prescription_snapshots._docs
    monday_snapshots = [d for d in snapshot_docs if d.get("planned_date") == _MONDAY.isoformat()]
    assert len(monday_snapshots) == 1
    assert monday_snapshots[0]["distance_km"] == monday_session["distance_km"]


@pytest.mark.asyncio
async def test_week_endpoint_reuses_existing_snapshot_never_overwritten():
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    first = await _get_week(fake_db)
    assert first["status"] == 200, first["body"]
    snapshot_after_first = list(fake_db.training_prescription_snapshots._docs)
    assert len(snapshot_after_first) >= 1

    # Manually tamper with the persisted snapshot to simulate a value that
    # would differ from whatever a live recompute might produce, then call
    # again: the endpoint must NEVER overwrite it.
    for doc in fake_db.training_prescription_snapshots._docs:
        if doc.get("day") == "monday":
            doc["distance_km"] = 999.0

    second = await _get_week(fake_db)
    assert second["status"] == 200, second["body"]
    monday_session_2 = next(
        s for s in second["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    # Effective display uses the (tampered, but frozen) snapshot untouched.
    assert monday_session_2["distance_km"] == 999.0
    # No duplicate snapshot rows were created.
    monday_snapshots = [
        d for d in fake_db.training_prescription_snapshots._docs if d.get("day") == "monday"
    ]
    assert len(monday_snapshots) == 1


@pytest.mark.asyncio
async def test_unmatched_actuals_excludes_previous_week_activity():
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    # Extra activity from the PREVIOUS week that cannot match any session.
    prev_week_date = _MONDAY - timedelta(days=7)
    fake_db.garmin_activities._docs.append({
        "user_id": _USER_ID,
        "source": "garmin",
        "activity_id": "prev-week-extra",
        "activity_type": "running",
        "start_time": prev_week_date.isoformat() + " 07:00:00",
        "garmin_activity": {"start_time_local": prev_week_date.isoformat() + " 07:00:00"},
        "distance_m": 5000.0,
        "duration_s": 1800.0,
    })

    result = await _get_week(fake_db)
    assert result["status"] == 200, result["body"]
    unmatched_ids = {a["activity_id"] for a in result["body"]["week"]["unmatched_actuals"]}
    assert "prev-week-extra" not in unmatched_ids


@pytest.mark.asyncio
async def test_today_endpoint_has_no_training_feedback_field():
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)
    fake_db.training_feedback._docs.append({
        "user_id": _USER_ID, "date": _MONDAY.isoformat(), "status": "done",
    })

    result = await _get_today(fake_db)
    assert result["status"] == 200, result["body"]
    assert "recent_feedback" not in result["body"]


# ── C234 — StructuredWorkoutPrescriptionEngine real pipeline wiring ────────


@pytest.mark.asyncio
async def test_today_endpoint_exposes_structured_prescription():
    """C234 Blocker 1: /training/today must now transport a real structured
    prescription built from the ATOMICALLY-SERVED session, not a module only
    reachable in isolated unit tests."""
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    result = await _get_today(fake_db)
    assert result["status"] == 200, result["body"]
    structured = result["body"]["structured_prescription"]
    assert structured is not None
    # served_prescription is the legacy *runtime* dict (frontend compat, uses
    # remapped "type"/"duration" keys) — structured_prescription instead uses
    # canonical WorkoutPrescription.workout_type values. Both must describe
    # the exact same underlying (atomically served) session.
    assert isinstance(structured["workout_type"], str)
    # None != 0 — structural distance sum must not silently coerce unknowns.
    assert isinstance(structured["steps"], list) and len(structured["steps"]) >= 1


@pytest.mark.asyncio
async def test_week_endpoint_exposes_structured_field_per_session():
    """C234 Blocker 1: /training/v2/week sessions must carry a `structured`
    field produced from the resolved/effective (never stale) prescription."""
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    result = await _get_week(fake_db)
    assert result["status"] == 200, result["body"]
    sessions = result["body"]["week"]["sessions"]
    assert any(s.get("structured") is not None for s in sessions)
    monday_session = next(s for s in sessions if s["day"].lower() == "monday")
    if monday_session.get("workout_type") != "rest":
        assert monday_session["structured"] is not None
        assert monday_session["structured"]["workout_type"] == monday_session["workout_type"]


@pytest.mark.asyncio
async def test_today_and_week_structured_prescription_converge_for_same_day():
    """C234 §15 — Today/Week convergence: hitting /training/today first (which
    freezes today's served snapshot) then /training/v2/week must yield the
    IDENTICAL structured contract for Monday — never a divergent recompute."""
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    today_result = await _get_today(fake_db)
    assert today_result["status"] == 200, today_result["body"]
    today_structured = today_result["body"]["structured_prescription"]

    week_result = await _get_week(fake_db)
    assert week_result["status"] == 200, week_result["body"]
    monday_session = next(
        s for s in week_result["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )

    assert monday_session["structured"] == today_structured


# ---------------------------------------------------------------------------
# C234 FINAL CORRECTIVE AUDIT — single Training Paces authority +
# historical structured lock (2 blockers).
# ---------------------------------------------------------------------------

def _seed_qualified_high_activity(
    fake_db: _FakeDB, *, reference_date: date, days_ago: int
) -> None:
    """Seed ONE qualified HIGH-confidence performance at ``days_ago`` before
    ``reference_date``, plus its own strictly-prior speed benchmark pool
    (dated relative to the performance itself, per
    ``performance_model._personal_speed_percentile_90d``'s 90-day-before-the-
    -activity window — NOT relative to ``reference_date``).

    Mirrors ``tests/test_training_paces_pr194.py::_qualified_high_activity``
    (10 km @ 12 km/h, avg_hr=160/max_hr=175 vs a 10 km/h benchmark pool at
    avg_hr=140/max_hr=175) so this reproduces the exact same HIGH
    qualification (score ~0.88, relative_hr ~0.914, speed_percentile 100%).
    """
    anchor = reference_date - timedelta(days=days_ago)
    # Benchmark pool: 7 runs strictly prior to `anchor` (11..17 days before).
    for i in range(7):
        bench_date = anchor - timedelta(days=11 + i)
        dur_s = 10_000.0 / (10.0 * 1000.0 / 3600.0)
        fake_db.garmin_activities._docs.append({
            "user_id": _USER_ID,
            "source": "garmin",
            "activity_id": f"bench-{i}",
            "activity_type": "running",
            "start_time": bench_date.isoformat() + " 07:00:00",
            "garmin_activity": {"start_time_local": bench_date.isoformat() + " 07:00:00"},
            "distance_m": 10_000.0,
            "duration_s": dur_s,
            "average_hr": 140.0,
            "max_hr": 175.0,
        })
    # The qualified HIGH performance itself.
    dur_s = 10_000.0 / (12.0 * 1000.0 / 3600.0)
    fake_db.garmin_activities._docs.append({
        "user_id": _USER_ID,
        "source": "garmin",
        "activity_id": "high-historical",
        "activity_type": "running",
        "start_time": anchor.isoformat() + " 07:00:00",
        "garmin_activity": {"start_time_local": anchor.isoformat() + " 07:00:00"},
        "distance_m": 10_000.0,
        "duration_s": dur_s,
        "average_hr": 160.0,
        "max_hr": 175.0,
    })


@pytest.mark.asyncio
async def test_c234_training_paces_single_authority_high_historical_over_90_days():
    """C234 Blocker 1 — a HIGH performance qualified >90 days ago (no better
    recent evidence) must NOT be silently dropped by Today/Week just because
    the Training Engine's own 90-day window would have excluded it.

    /training/v2/paces, /training/today and /training/v2/week must all use
    the SAME canonical Training Paces authority (no 90-day truncation), so
    all three observe the same (LOW-confidence, but present) paces.
    """
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_connected(fake_db, connected=True)
    _seed_qualified_high_activity(fake_db, reference_date=_MONDAY, days_ago=100)

    # 1) /training/v2/paces must expose real (non-null) paces at LOW confidence.
    ps = _patches(fake_db, _MONDAY)
    started = []
    try:
        for p in ps:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app), base_url="http://test",
        ) as client:
            r = await client.get("/api/training/v2/paces", headers=_bearer())
            assert r.status_code == 200, r.text
            paces_body = r.json()
    finally:
        for p in reversed(started):
            p.stop()

    assert paces_body["confidence"] == "LOW", (
        f"HIGH historical (>90d, no better recent evidence) must survive at "
        f"LOW confidence per training_paces.py policy, got {paces_body['confidence']!r}"
    )
    assert paces_body["paces"]["easy"] is not None, (
        "PACE_UNAVAILABLE must NOT occur here: the Training Engine's 90-day "
        "window must never truncate Training Paces evidence."
    )

    # 2) /training/today's structured prescription must use the SAME paces
    #    authority (never PACE_UNAVAILABLE purely due to the 90-day cutoff).
    today_result = await _get_today(fake_db)
    assert today_result["status"] == 200, today_result["body"]
    today_structured = today_result["body"]["structured_prescription"]
    assert today_structured is not None

    # 3) /training/v2/week's live (today) session must use the same evidence.
    week_result = await _get_week(fake_db)
    assert week_result["status"] == 200, week_result["body"]
    monday_session = next(
        s for s in week_result["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    if monday_session.get("workout_type") != "rest":
        assert monday_session["structured"] is not None
        assert monday_session["structured"] == today_structured


@pytest.mark.asyncio
async def test_c234_historical_frozen_session_structured_is_none():
    """C234 Blocker 2 — a strictly historical day backed by a frozen
    PrescriptionSnapshot PARENT must never have `structured` recomputed.

    First call freezes Monday's snapshot (Monday == reference_date, i.e.
    "today"). A later call with a reference_date further into the SAME
    ISO week makes Monday strictly historical (planned_date < reference_date);
    its `structured` must then be None with structured_status =
    "historical_unavailable", even though the frozen parent snapshot exists.
    """
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    first = await _get_week(fake_db, reference_date=_MONDAY)
    assert first["status"] == 200, first["body"]
    monday_first = next(
        s for s in first["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    if monday_first.get("workout_type") == "rest":
        pytest.skip("Seeded plan produced a rest day on Monday; nothing to structure.")
    assert monday_first["structured"] is not None
    assert monday_first.get("structured_status") == "today_served"

    later_reference_date = _MONDAY + timedelta(days=2)  # Wednesday, same ISO week
    second = await _get_week(fake_db, reference_date=later_reference_date)
    assert second["status"] == 200, second["body"]
    monday_second = next(
        s for s in second["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    assert monday_second["structured"] is None, (
        "A day backed only by a frozen parent snapshot (no structured "
        "snapshot yet — #235) must never have `structured` recomputed."
    )
    assert monday_second.get("structured_status") == "historical_unavailable"
    # The frozen PARENT itself must still be honest/unchanged.
    assert monday_second["distance_km"] == monday_first["distance_km"]
    assert monday_second["workout_type"] == monday_first["workout_type"]


@pytest.mark.asyncio
async def test_c234_historical_structured_stays_none_after_goal_change():
    """C234 §11 — historical immutability. Changing goal/phase between the
    first (freezing) call and a later historical call must NOT resurrect a
    recomputed `structured` for the now-historical day."""
    fake_db = _FakeDB()
    _seed_cycle(fake_db, goal="SEMI")
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    first = await _get_week(fake_db, reference_date=_MONDAY)
    assert first["status"] == 200, first["body"]
    monday_first = next(
        s for s in first["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    if monday_first.get("workout_type") == "rest":
        pytest.skip("Seeded plan produced a rest day on Monday; nothing to structure.")

    # Change the plan goal entirely (Half -> Marathon) after Monday was frozen.
    fake_db.training_cycles._docs.clear()
    fake_db.user_goals._docs.clear()
    _seed_cycle(fake_db, goal="MARATHON")
    for doc in fake_db.user_goals._docs:
        doc["distance_type"] = "marathon"

    later_reference_date = _MONDAY + timedelta(days=2)
    second = await _get_week(fake_db, reference_date=later_reference_date)
    assert second["status"] == 200, second["body"]
    monday_second = next(
        s for s in second["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    assert monday_second["structured"] is None
    assert monday_second.get("structured_status") == "historical_unavailable"
    assert monday_second["workout_type"] == monday_first["workout_type"], (
        "The frozen parent must remain the exact same regardless of a later "
        "goal change."
    )
    assert monday_second["distance_km"] == monday_first["distance_km"]


@pytest.mark.asyncio
async def test_c234_historical_structured_stays_none_after_training_paces_change():
    """C234 §12 — a strong Training Paces change (new, much faster activities)
    after a historical day was frozen must NOT resurrect a recomputed
    `structured` for that historical day."""
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8, km_per=8.0)
    _seed_connected(fake_db, connected=True)

    first = await _get_week(fake_db, reference_date=_MONDAY)
    assert first["status"] == 200, first["body"]
    monday_first = next(
        s for s in first["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    if monday_first.get("workout_type") == "rest":
        pytest.skip("Seeded plan produced a rest day on Monday; nothing to structure.")

    # Add much faster recent activities (would shift VDOT/paces substantially).
    _seed_qualified_high_activity(fake_db, reference_date=_MONDAY, days_ago=3)

    later_reference_date = _MONDAY + timedelta(days=2)
    second = await _get_week(fake_db, reference_date=later_reference_date)
    assert second["status"] == 200, second["body"]
    monday_second = next(
        s for s in second["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    assert monday_second["structured"] is None, (
        "A Training Paces change must never resurrect a historical structure."
    )
    assert monday_second.get("structured_status") == "historical_unavailable"
    assert monday_second["workout_type"] == monday_first["workout_type"]
    assert monday_second["distance_km"] == monday_first["distance_km"]


@pytest.mark.asyncio
async def test_c234_future_session_structured_stays_live():
    """C234 §13 — a strictly future session (no snapshot) must keep a live,
    non-None `structured` field with structured_status = "future_live";
    the historical-exclusion fix must not affect future sessions."""
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    result = await _get_week(fake_db, reference_date=_MONDAY)
    assert result["status"] == 200, result["body"]
    sessions = result["body"]["week"]["sessions"]
    future_sessions = [
        s for s in sessions
        if s["planned_date"] > _MONDAY.isoformat() and s.get("workout_type") != "rest"
    ]
    assert future_sessions, "Expected at least one non-rest future session in the seeded week."
    for s in future_sessions:
        assert s["structured"] is not None, (
            f"Future session {s['day']} must keep a live structured prescription."
        )
        assert s.get("structured_status") == "future_live"


@pytest.mark.asyncio
async def test_c234_today_structured_status_is_today_served():
    """C234 §14 — Today's structured prescription is built from the
    atomically-served parent (never a losing local DailyAdaptation
    candidate) and must carry structured_status == "today_served",
    identical between Today and Week for the same day."""
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    today_result = await _get_today(fake_db)
    assert today_result["status"] == 200, today_result["body"]
    today_structured = today_result["body"]["structured_prescription"]

    week_result = await _get_week(fake_db)
    assert week_result["status"] == 200, week_result["body"]
    monday_session = next(
        s for s in week_result["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    if monday_session.get("workout_type") == "rest":
        pytest.skip("Seeded plan produced a rest day on Monday; nothing to structure.")
    assert monday_session.get("structured_status") == "today_served"
    assert monday_session["structured"] == today_structured
