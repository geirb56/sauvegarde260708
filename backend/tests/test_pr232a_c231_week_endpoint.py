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


async def _get_paces(fake_db: _FakeDB, reference_date: date = _MONDAY) -> Dict:
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
            r = await client.get("/api/training/v2/paces", headers=_bearer())
            return {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text}
    finally:
        for p in reversed(started):
            p.stop()


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


# ---------------------------------------------------------------------------
# C232 (correction) — honest pace-zone wiring on /training/v2/week.
# The previous "blocks" (fabricated splits) field has been removed entirely.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_week_sessions_expose_primary_pace_field_without_fabricated_blocks():
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    result = await _get_week(fake_db)
    assert result["status"] == 200, result["body"]

    sessions = result["body"]["week"]["sessions"]
    assert sessions, "expected at least one session in the week"
    for session in sessions:
        # Every session — including rest and prescription_unavailable —
        # exposes the field (never a KeyError for a consumer), and there is
        # no "blocks" field at all (C232 — fabricated splits removed).
        assert "primary_pace" in session
        assert "blocks" not in session

    rest_sessions = [s for s in sessions if s["workout_type"] == "rest"]
    for rest_session in rest_sessions:
        # Rest days never get a fabricated pace zone.
        assert rest_session["primary_pace"] is None

    quality_sessions = [s for s in sessions if s["workout_type"] == "quality"]
    for quality_session in quality_sessions:
        # C232 — "quality"'s exact nature is not decided by the Training
        # Engine: never a fabricated (e.g. Threshold) pace zone.
        assert quality_session["primary_pace"] is None


# ---------------------------------------------------------------------------
# C232 (correction round 3) — WorkoutStep contract: no fabricated splits, and
# the API reproduces explicit engine-provided steps verbatim.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_week_sessions_have_no_fabricated_steps_today():
    """Test 1/2/9 — generic "quality" and "long_easy" sessions get an empty
    ``steps`` list: WorkoutGenerator does not yet decide any session's
    internal structure, so the API must never invent one. Every session
    still exposes the field (``[]``, never missing/None-as-list)."""
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    result = await _get_week(fake_db)
    assert result["status"] == 200, result["body"]

    sessions = result["body"]["week"]["sessions"]
    assert sessions, "expected at least one session in the week"
    for session in sessions:
        assert "steps" in session
        # No workout_type gets a fabricated structure today — no engine
        # populates WorkoutPrescription.steps yet.
        assert session["steps"] == []

    quality_or_long_easy = [
        s for s in sessions if s["workout_type"] in ("quality", "long_easy")
    ]
    for session in quality_or_long_easy:
        assert session["steps"] == [], (
            f"{session['workout_type']} session must not fabricate a split "
            "(e.g. 3 x 2 km @ threshold, or a marathon-pace segment)"
        )


@pytest.mark.asyncio
async def test_explicit_engine_steps_are_reproduced_verbatim_by_the_api():
    """Test 3/4/5 — when the live ``WorkoutPrescription`` for a strictly
    future session DOES carry explicit ``steps`` (simulating a future
    engine capability that does not exist yet), the API must reproduce
    them EXACTLY: no aggregation, no recomputed repetition/recovery, no
    dropped/renamed field.
    """
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    from training_v2.week_plan_bridge import build_canonical_weekly_plan as _real_build
    from training_v2.workout_generator import WorkoutStep

    injected_steps = (
        WorkoutStep(kind="warmup", distance_km=2.0, pace_zone="easy"),
        WorkoutStep(kind="work", repetitions=3, distance_km=2.0, pace_zone="threshold"),
        WorkoutStep(kind="recovery", duration_minutes=2.0),
        WorkoutStep(kind="cooldown", distance_km=1.0, pace_zone="easy"),
    )

    def _patched(**kwargs):
        canonical = _real_build(**kwargs)
        sessions = list(canonical.weekly_plan.sessions)
        # Inject into the first strictly-future (day != monday, the
        # reference_date), non-rest session — a today-or-past session would
        # be frozen and never carry live steps (same rule as primary_pace).
        target_idx = next(
            i for i, s in enumerate(sessions)
            if s.day != "monday" and s.workout_type != "rest"
        )
        sessions[target_idx] = sessions[target_idx].model_copy(
            update={"steps": injected_steps}
        )
        new_weekly_plan = canonical.weekly_plan.model_copy(
            update={"sessions": tuple(sessions)}
        )
        return type(canonical)(
            original_target=canonical.original_target,
            reconciliation_result=canonical.reconciliation_result,
            reconciled_target=canonical.reconciled_target,
            weekly_plan=new_weekly_plan,
        )

    with patch("training_v2.week_plan_bridge.build_canonical_weekly_plan", side_effect=_patched):
        result = await _get_week(fake_db)

    assert result["status"] == 200, result["body"]
    sessions = result["body"]["week"]["sessions"]
    target_session = next(s for s in sessions if s["day"] != "monday" and s["steps"])
    assert target_session["steps"] == [
        {"kind": "warmup", "repetitions": None, "distance_km": 2.0, "duration_minutes": None, "pace_zone": "easy", "pace_range": None, "reason_codes": []},
        {"kind": "work", "repetitions": 3, "distance_km": 2.0, "duration_minutes": None, "pace_zone": "threshold", "pace_range": None, "reason_codes": []},
        {"kind": "recovery", "repetitions": None, "distance_km": None, "duration_minutes": 2.0, "pace_zone": None, "pace_range": None, "reason_codes": []},
        {"kind": "cooldown", "repetitions": None, "distance_km": 1.0, "duration_minutes": None, "pace_zone": "easy", "pace_range": None, "reason_codes": []},
    ]

    # No other session was affected — everything else stays steps=[].
    others = [s for s in sessions if s is not target_session]
    for other in others:
        assert other["steps"] == []


@pytest.mark.asyncio
async def test_prescription_unavailable_session_has_no_steps():
    """Test 9 — ``None`` stays ``None`` / no fabricated steps: a
    prescription_unavailable day never gets a steps list either."""
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_connected(fake_db, connected=True)
    # No garmin activities seeded -> continuity_state == no_history and no
    # frozen snapshot exists for past days: they surface as
    # prescription_unavailable (never a fabricated historical prescription).
    past_reference = _MONDAY + timedelta(days=3)

    result = await _get_week(fake_db, reference_date=past_reference)
    assert result["status"] == 200, result["body"]
    sessions = result["body"]["week"]["sessions"]
    unavailable = [s for s in sessions if s["execution_status"] == "prescription_unavailable"]
    assert unavailable, "expected at least one prescription_unavailable session with no history"
    for session in unavailable:
        assert session["steps"] == []


@pytest.mark.asyncio
async def test_prescription_unavailable_session_has_no_pace_zone():
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_connected(fake_db, connected=True)
    # No garmin activities seeded -> continuity_state == no_history and no
    # frozen snapshot exists for past days: they surface as
    # prescription_unavailable (never a fabricated historical prescription).
    past_reference = _MONDAY + timedelta(days=3)

    result = await _get_week(fake_db, reference_date=past_reference)
    assert result["status"] == 200, result["body"]

    unavailable = [
        s for s in result["body"]["week"]["sessions"]
        if s.get("execution_status") == "prescription_unavailable"
    ]
    for session in unavailable:
        assert session["primary_pace"] is None


# ---------------------------------------------------------------------------
# C232 (correction) — BLOCKER 2 FIX: /training/v2/paces and /training/v2/week
# must agree, even when the last HIGH-quality performance is older than 90
# days (previously excluded by /training/v2/week's own 90-day-windowed
# query, but retained as fallback evidence by training_paces.py's own
# selection policy — see canonical_training_paces.py docstring).
# ---------------------------------------------------------------------------

def _seed_benchmark_pool(fake_db: _FakeDB, ref: date, n: int = 7, speed_kmh: float = 10.0) -> None:
    """Easy benchmark runs, all STRICTLY BEFORE the qualifying HIGH activity
    seeded by _seed_stale_high_performance (200 days before ref), so
    training_paces.py's speed-percentile computation (strictly-prior, 90-day
    window before the activity's own date) has enough qualifying context."""
    for i in range(n):
        act_date = ref - timedelta(days=210 + i * 2)
        dur_s = 10_000.0 / (speed_kmh * 1000.0 / 3600.0)
        fake_db.garmin_activities._docs.append({
            "user_id": _USER_ID,
            "source": "garmin",
            "activity_id": f"benchmark-{i}",
            "activity_type": "running",
            "start_time": act_date.isoformat() + " 07:00:00",
            "garmin_activity": {"start_time_local": act_date.isoformat() + " 07:00:00"},
            "distance_m": 10_000.0,
            "duration_s": dur_s,
            "average_hr": 140.0,
            "max_hr": 175.0,
        })


def _seed_stale_high_performance(fake_db: _FakeDB, ref: date, days_ago: int = 200) -> None:
    """A single 10 km performance, well over 90 days old, that qualifies as
    HIGH evidence per training_paces.py (fast pace + high relative HR vs. the
    benchmark pool seeded by _seed_benchmark_pool)."""
    act_date = ref - timedelta(days=days_ago)
    speed_ms = 12_000.0 / 3600.0  # 12 km/h = 5:00/km
    dur_s = 10_000.0 / speed_ms
    fake_db.garmin_activities._docs.append({
        "user_id": _USER_ID,
        "source": "garmin",
        "activity_id": "stale-high-performance",
        "activity_type": "running",
        "start_time": act_date.isoformat() + " 07:00:00",
        "garmin_activity": {"start_time_local": act_date.isoformat() + " 07:00:00"},
        "distance_m": 10_000.0,
        "duration_s": dur_s,
        "average_hr": 160.0,
        "max_hr": 175.0,
    })


@pytest.mark.asyncio
async def test_paces_and_week_agree_when_last_high_performance_is_over_90_days_old():
    # #5 of the mandatory C232 test list.
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_connected(fake_db, connected=True)
    _seed_benchmark_pool(fake_db, _MONDAY)
    _seed_stale_high_performance(fake_db, _MONDAY, days_ago=200)

    paces_result = await _get_paces(fake_db)
    week_result = await _get_week(fake_db)
    assert paces_result["status"] == 200, paces_result["body"]
    assert week_result["status"] == 200, week_result["body"]

    paces_body = paces_result["body"]
    # The stale (>90 days) HIGH performance must still be visible as
    # evidence — /training/v2/paces must not report INSUFFICIENT.
    assert paces_body["confidence"] != "INSUFFICIENT"
    assert paces_body["paces"]["easy"] is not None

    # C232 (correction round 2, item 4) — a pace zone is only ever resolved
    # for a still-strictly-future session (today-or-past is served from a
    # FROZEN snapshot, which never carries a pace — see
    # test_frozen_session_pace_is_never_recomputed_from_live_paces below).
    # Restrict this equivalence check to future easy/recovery/long_easy
    # sessions, which is exactly the scope where /training/v2/week is
    # allowed to attach a live-resolved pace at all.
    easy_sessions = [
        s for s in week_result["body"]["week"]["sessions"]
        if s["workout_type"] in ("easy", "recovery", "long_easy")
        and s["planned_date"] > _MONDAY.isoformat()
    ]
    assert easy_sessions, "expected at least one future easy/recovery/long_easy session"
    for session in easy_sessions:
        # #6 — identical inputs + identical reference_date => identical
        # pace values between endpoints (never one showing a pace and the
        # other None for the exact same user/day).
        assert session["primary_pace"] is not None
        assert session["primary_pace"]["lower_min_per_km"] == pytest.approx(
            paces_body["paces"]["easy"]["lower"]["min_per_km"]
        )
        assert session["primary_pace"]["upper_min_per_km"] == pytest.approx(
            paces_body["paces"]["easy"]["upper"]["min_per_km"]
        )


@pytest.mark.asyncio
async def test_paces_and_week_agree_when_garmin_temporarily_disconnected():
    # C232 (correction, round 8) — test G of the mandatory list: a user
    # whose Garmin account is currently marked NOT connected, but who has
    # historical activities already persisted in `garmin_activities`, must
    # still get Training Paces from BOTH endpoints. `load_canonical_training_
    # paces()` never reads `garmin_connections` at all (see
    # canonical_training_paces.py) — the live-connection flag only gates a
    # SEPARATE daily-metrics fetch used by DailyAdaptation, never the
    # Training Paces history query.
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_connected(fake_db, connected=False)
    _seed_benchmark_pool(fake_db, _MONDAY)
    _seed_stale_high_performance(fake_db, _MONDAY, days_ago=200)

    paces_result = await _get_paces(fake_db)
    week_result = await _get_week(fake_db)
    assert paces_result["status"] == 200, paces_result["body"]
    assert week_result["status"] == 200, week_result["body"]

    paces_body = paces_result["body"]
    assert paces_body["confidence"] != "INSUFFICIENT"
    assert paces_body["paces"]["easy"] is not None

    easy_sessions = [
        s for s in week_result["body"]["week"]["sessions"]
        if s["workout_type"] in ("easy", "recovery", "long_easy")
        and s["planned_date"] > _MONDAY.isoformat()
    ]
    assert easy_sessions, "expected at least one future easy/recovery/long_easy session"
    for session in easy_sessions:
        assert session["primary_pace"] is not None
        assert session["primary_pace"]["lower_min_per_km"] == pytest.approx(
            paces_body["paces"]["easy"]["lower"]["min_per_km"]
        )


@pytest.mark.asyncio
async def test_paces_no_lookahead_future_activity_has_no_effect():
    # #7 of the mandatory C232 test list.
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_connected(fake_db, connected=True)
    _seed_benchmark_pool(fake_db, _MONDAY)
    _seed_stale_high_performance(fake_db, _MONDAY, days_ago=200)

    baseline = await _get_paces(fake_db)
    assert baseline["status"] == 200, baseline["body"]

    # A future activity (after reference_date) must never influence today's
    # computed paces.
    future_date = _MONDAY + timedelta(days=30)
    fake_db.garmin_activities._docs.append({
        "user_id": _USER_ID,
        "source": "garmin",
        "activity_id": "future-activity",
        "activity_type": "running",
        "start_time": future_date.isoformat() + " 07:00:00",
        "garmin_activity": {"start_time_local": future_date.isoformat() + " 07:00:00"},
        "distance_m": 10_000.0,
        "duration_s": 30 * 60.0,
        "average_hr": 165.0,
        "max_hr": 175.0,
    })

    with_future = await _get_paces(fake_db)
    assert with_future["status"] == 200, with_future["body"]
    assert with_future["body"] == baseline["body"]


@pytest.mark.asyncio
async def test_insufficient_confidence_is_none_with_no_fallback():
    # #8 of the mandatory C232 test list.
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_connected(fake_db, connected=True)
    # No qualifying performance seeded at all -> INSUFFICIENT.

    paces_result = await _get_paces(fake_db)
    assert paces_result["status"] == 200, paces_result["body"]
    paces_body = paces_result["body"]
    assert paces_body["confidence"] == "INSUFFICIENT"
    for key in ("easy", "marathon", "threshold", "interval", "repetition"):
        assert paces_body["paces"][key] is None

    week_result = await _get_week(fake_db)
    assert week_result["status"] == 200, week_result["body"]
    for session in week_result["body"]["week"]["sessions"]:
        # No fallback pace zone is ever fabricated when paces are INSUFFICIENT.
        assert session["primary_pace"] is None


# ---------------------------------------------------------------------------
# CORRECTION C232 (round 2) — historical immutability: a FROZEN prescription
# never acquires a pace zone retroactively from TODAY's live TrainingPaces.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_frozen_session_pace_is_never_recomputed_from_live_paces():
    # #C of the mandatory (round 2) C232 test list.
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    first = await _get_week(fake_db, reference_date=_MONDAY)
    assert first["status"] == 200, first["body"]
    monday_session = next(
        s for s in first["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    # A snapshot has just been frozen for Monday (today == planned_date, see
    # test_week_endpoint_persists_snapshot_for_todays_session). The snapshot
    # itself never persists a pace (prescription_snapshot.PrescriptionSnapshot
    # has no pace field) — so it must be displayed as unknown, even for the
    # very same call that just froze it.
    assert monday_session["primary_pace"] is None

    # Now view the SAME week later in the cycle (Monday is now strictly in
    # the past) with DIFFERENT live evidence that would change the live
    # TrainingPaces if it were (wrongly) recomputed for that day.
    later_reference = _MONDAY + timedelta(days=3)
    fake_db.garmin_activities._docs.append({
        "user_id": _USER_ID,
        "source": "garmin",
        "activity_id": "much-faster-benchmark",
        "activity_type": "running",
        "start_time": (later_reference - timedelta(days=1)).isoformat() + " 07:00:00",
        "garmin_activity": {
            "start_time_local": (later_reference - timedelta(days=1)).isoformat() + " 07:00:00"
        },
        "distance_m": 10_000.0,
        "duration_s": 30 * 60.0,  # much faster pace than the seeded easy runs
        "average_hr": 178.0,
        "max_hr": 190.0,
    })

    second = await _get_week(fake_db, reference_date=later_reference)
    assert second["status"] == 200, second["body"]
    monday_session_2 = next(
        s for s in second["body"]["week"]["sessions"] if s["day"].lower() == "monday"
    )
    # Still None: an old, already-frozen prescription never gains a pace it
    # never had while it was current — "None reste None".
    assert monday_session_2["primary_pace"] is None
    # The frozen distance/workout_type themselves are unaffected either.
    assert monday_session_2["distance_km"] == monday_session["distance_km"]
    assert monday_session_2["workout_type"] == monday_session["workout_type"]


# ---------------------------------------------------------------------------
# CORRECTION C232 (round 2) — week volume: plan vs. real Garmin volume
# (matched + unmatched), no double counting.
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
async def test_unmatched_actuals_distance_is_disjoint_from_matched_sessions():
    # #E of the mandatory (round 2) C232 test list. The backend contract
    # this relies on: unmatched_actuals never repeats an activity already
    # exposed as a session's `actual` (PR230 boundary — matching_status is
    # mutually exclusive between "matched" sessions and "unmatched_actual"
    # extras), so a frontend real-volume sum (matched + unmatched) can never
    # double count the same Garmin activity.
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    # A real Garmin activity that matches Monday's prescription closely
    # enough to be attributed to it (freezes Monday's snapshot at the same
    # time — see test_week_endpoint_persists_snapshot_for_todays_session).
    monday_session = next(
        s for s in (await _get_week(fake_db, reference_date=_MONDAY))["body"]["week"]["sessions"]
        if s["day"].lower() == "monday"
    )
    fake_db.garmin_activities._docs.append({
        "user_id": _USER_ID,
        "source": "garmin",
        "activity_id": "monday-match",
        "activity_type": "running",
        "start_time": _MONDAY.isoformat() + " 07:00:00",
        "garmin_activity": {"start_time_local": _MONDAY.isoformat() + " 07:00:00"},
        "distance_m": (monday_session["distance_km"] or 10.0) * 1000.0,
        "duration_s": (monday_session["distance_km"] or 10.0) * 1000.0 * 6.0,
    })
    first = await _get_week(fake_db, reference_date=_MONDAY)
    assert first["status"] == 200, first["body"]

    # A second, GENUINELY extra real activity this week, on a rest day (no
    # prescribed session to attribute it to): an unplanned extra run.
    extra_date = _MONDAY + timedelta(days=1)
    fake_db.garmin_activities._docs.append({
        "user_id": _USER_ID,
        "source": "garmin",
        "activity_id": "extra-real-run",
        "activity_type": "running",
        "start_time": extra_date.isoformat() + " 18:00:00",
        "garmin_activity": {"start_time_local": extra_date.isoformat() + " 18:00:00"},
        "distance_m": 6000.0,
        "duration_s": 1800.0,
    })

    later_reference = _MONDAY + timedelta(days=3)
    result = await _get_week(fake_db, reference_date=later_reference)
    assert result["status"] == 200, result["body"]

    matched_activity_ids = {
        s["actual"]["activity_id"]
        for s in result["body"]["week"]["sessions"]
        if s.get("actual") is not None
    }
    unmatched_activity_ids = {
        a["activity_id"] for a in result["body"]["week"]["unmatched_actuals"]
    }
    # No overlap: an activity can never appear as BOTH a matched session's
    # actual AND an unmatched extra — summing both sets is never a double
    # count of the same real Garmin activity.
    assert matched_activity_ids.isdisjoint(unmatched_activity_ids)
    assert "monday-match" in matched_activity_ids
    assert "extra-real-run" in unmatched_activity_ids


# ─────────────────────────────────────────────────────────────────────────────
# C232 (correction, round 7) — BLOCKER 1 & 3 FIX: Today and Week must
# represent the EXACT SAME served prescription — including `steps` — for
# today's own session, in both call orders, and that must survive a replay
# on a later day (frozen, never recomputed).
# ─────────────────────────────────────────────────────────────────────────────

def _patched_build_with_monday_steps(injected_steps):
    """Returns a monkeypatch target that injects `injected_steps` into the
    Monday (today, for _MONDAY reference_date) LIVE session, simulating a
    future engine capability that actually decides structure."""
    from training_v2.week_plan_bridge import build_canonical_weekly_plan as _real_build

    def _patched(**kwargs):
        canonical = _real_build(**kwargs)
        sessions = list(canonical.weekly_plan.sessions)
        idx = next(i for i, s in enumerate(sessions) if s.day == "monday")
        sessions[idx] = sessions[idx].model_copy(update={"steps": injected_steps})
        new_weekly_plan = canonical.weekly_plan.model_copy(update={"sessions": tuple(sessions)})
        return type(canonical)(
            original_target=canonical.original_target,
            reconciliation_result=canonical.reconciliation_result,
            reconciled_target=canonical.reconciled_target,
            weekly_plan=new_weekly_plan,
        )

    return _patched


@pytest.mark.asyncio
async def test_today_snapshots_explicit_steps_verbatim():
    """Test A — a future/explicit-steps prescription served via
    /training/today gets snapshotted with EXACTLY those steps."""
    from training_v2.workout_generator import WorkoutStep

    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    injected_steps = (
        WorkoutStep(kind="warmup", distance_km=2.0, pace_zone="easy"),
        WorkoutStep(kind="work", repetitions=3, distance_km=2.0, pace_zone="threshold"),
        WorkoutStep(kind="cooldown", distance_km=1.0, pace_zone="easy"),
    )

    with patch(
        "training_v2.week_plan_bridge.build_canonical_weekly_plan",
        side_effect=_patched_build_with_monday_steps(injected_steps),
    ):
        result = await _get_today(fake_db, reference_date=_MONDAY)

    assert result["status"] == 200, result["body"]
    served_steps = result["body"]["served_prescription"]["steps"]
    assert served_steps == [
        {"kind": "warmup", "repetitions": None, "distance_km": 2.0, "duration_minutes": None, "pace_zone": "easy", "pace_range": None, "reason_codes": []},
        {"kind": "work", "repetitions": 3, "distance_km": 2.0, "duration_minutes": None, "pace_zone": "threshold", "pace_range": None, "reason_codes": []},
        {"kind": "cooldown", "repetitions": None, "distance_km": 1.0, "duration_minutes": None, "pace_zone": "easy", "pace_range": None, "reason_codes": []},
    ]


@pytest.mark.asyncio
async def test_today_then_week_expose_exactly_the_same_steps():
    """Test B — Today -> Week: once Today has served+snapshotted a
    session's steps, /training/v2/week must expose EXACTLY the same steps
    for that day, never a re-derived/aggregated/empty version."""
    from training_v2.workout_generator import WorkoutStep

    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    injected_steps = (
        WorkoutStep(kind="warmup", distance_km=2.0, pace_zone="easy"),
        WorkoutStep(kind="work", repetitions=3, distance_km=2.0, pace_zone="threshold"),
        WorkoutStep(kind="cooldown", distance_km=1.0, pace_zone="easy"),
    )
    patch_target = _patched_build_with_monday_steps(injected_steps)

    with patch("training_v2.week_plan_bridge.build_canonical_weekly_plan", side_effect=patch_target):
        today_result = await _get_today(fake_db, reference_date=_MONDAY)
        assert today_result["status"] == 200, today_result["body"]

        week_result = await _get_week(fake_db, reference_date=_MONDAY)
        assert week_result["status"] == 200, week_result["body"]

    monday_session = next(s for s in week_result["body"]["week"]["sessions"] if s["day"] == "monday")
    assert monday_session["steps"] == today_result["body"]["served_prescription"]["steps"]
    assert monday_session["steps"] != []


@pytest.mark.asyncio
async def test_week_then_today_expose_exactly_the_same_steps():
    """Test C — the reverse order: Week serves+snapshots first, then Today
    must expose EXACTLY the same steps it already froze."""
    from training_v2.workout_generator import WorkoutStep

    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    injected_steps = (
        WorkoutStep(kind="warmup", distance_km=2.0, pace_zone="easy"),
        WorkoutStep(kind="work", repetitions=3, distance_km=2.0, pace_zone="threshold"),
        WorkoutStep(kind="cooldown", distance_km=1.0, pace_zone="easy"),
    )
    patch_target = _patched_build_with_monday_steps(injected_steps)

    with patch("training_v2.week_plan_bridge.build_canonical_weekly_plan", side_effect=patch_target):
        week_result = await _get_week(fake_db, reference_date=_MONDAY)
        assert week_result["status"] == 200, week_result["body"]

        today_result = await _get_today(fake_db, reference_date=_MONDAY)
        assert today_result["status"] == 200, today_result["body"]

    monday_session = next(s for s in week_result["body"]["week"]["sessions"] if s["day"] == "monday")
    assert today_result["body"]["served_prescription"]["steps"] == monday_session["steps"]
    assert today_result["body"]["served_prescription"]["steps"] != []


@pytest.mark.asyncio
async def test_replay_later_day_reproduces_exact_same_frozen_steps():
    """Test D — replay J+N: once Monday's session is frozen (with explicit
    steps), calling /training/v2/week again on a LATER reference_date (with
    the live engine now returning DIFFERENT — here, no — steps for that
    same day) must still reproduce the ORIGINAL frozen steps verbatim."""
    from training_v2.workout_generator import WorkoutStep

    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    injected_steps = (
        WorkoutStep(kind="warmup", distance_km=2.0, pace_zone="easy"),
        WorkoutStep(kind="work", repetitions=3, distance_km=2.0, pace_zone="threshold"),
        WorkoutStep(kind="cooldown", distance_km=1.0, pace_zone="easy"),
    )
    patch_target = _patched_build_with_monday_steps(injected_steps)

    with patch("training_v2.week_plan_bridge.build_canonical_weekly_plan", side_effect=patch_target):
        first = await _get_week(fake_db, reference_date=_MONDAY)
        assert first["status"] == 200, first["body"]

    # Replay on a later day: NO patch active anymore, so the live engine
    # would build Monday with steps=() if it were ever re-consulted for
    # that (now past) day — but it must not be: the snapshot wins.
    later_reference = _MONDAY + timedelta(days=3)
    later = await _get_week(fake_db, reference_date=later_reference)
    assert later["status"] == 200, later["body"]

    monday_session = next(s for s in later["body"]["week"]["sessions"] if s["day"] == "monday")
    assert monday_session["steps"] == [
        {"kind": "warmup", "repetitions": None, "distance_km": 2.0, "duration_minutes": None, "pace_zone": "easy", "pace_range": None, "reason_codes": []},
        {"kind": "work", "repetitions": 3, "distance_km": 2.0, "duration_minutes": None, "pace_zone": "threshold", "pace_range": None, "reason_codes": []},
        {"kind": "cooldown", "repetitions": None, "distance_km": 1.0, "duration_minutes": None, "pace_zone": "easy", "pace_range": None, "reason_codes": []},
    ]
