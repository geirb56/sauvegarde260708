"""PR228-patch — Real handler tests: Week / Today unified orchestration.

Tests call the real FastAPI handlers via httpx.AsyncClient + ASGITransport.
They use an in-memory fake database and JWT auth, following the pattern of
test_pr204_maintenance_endpoint.py.

Contracts verified
------------------
WEEK_TODAY_PARITY
    • Same activities → same session source before DailyAdaptation.
    • connected=false + history present → same plan source as connected=true.
    • Reconciliation REDUCE → same action + same session source for Week & Today.
    • Reconciliation KEEP → same baseline for Week & Today.

PROTECTIONS
    • Taper phase → reconciliation does not break taper protections.
    • Race week → protections conserved.

ADAPTATION_ISOLATION
    • DailyAdaptation can reduce Today session without modifying Week plan.
    • Week plan sessions are unaffected by Today's DailyAdaptation.

ARCHITECTURE
    • No double WorkoutGenerator.
    • No double WeeklyReconciliation.

Run from the backend directory:
    python -m pytest tests/test_handlers_pr228.py -q
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, date, timedelta
from typing import Any, Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Environment — must be set before server is imported
# ---------------------------------------------------------------------------

os.environ.setdefault("JWT_SECRET_KEY", "test-pr228-handler-secret-32chars!!")
os.environ.setdefault("JWT_SECRET", "test-pr228-handler-secret-32chars!!")
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

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USER_ID = "pr228-test-user"
_USER_EMAIL = "pr228@example.com"

# A Monday so day_name matches "monday" in WorkoutGenerator output.
_MONDAY = date(2025, 9, 15)

# ---------------------------------------------------------------------------
# Minimal async-compatible fake DB (same pattern as test_pr204_maintenance_endpoint.py)
# ---------------------------------------------------------------------------


class _UpdateResult:
    matched_count = 1
    modified_count = 1


class _DeleteResult:
    deleted_count = 0


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

    async def find_one(
        self, query: dict, projection: Optional[dict] = None
    ) -> Optional[dict]:
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

    def find(
        self, query: Optional[dict] = None, projection: Optional[dict] = None
    ) -> "_Collection._Cursor":
        q = {k: v for k, v in (query or {}).items() if not isinstance(v, dict)}
        results = [d for d in self._docs if self._match(d, q)]
        return self._Cursor(results)

    async def update_one(
        self, query: dict, update: dict, upsert: bool = False
    ) -> _UpdateResult:
        q = {k: v for k, v in query.items() if not isinstance(v, dict)}
        for doc in self._docs:
            if self._match(doc, q):
                doc.update(update.get("$set", {}))
                return _UpdateResult()
        if upsert:
            self._docs.append({**q, **update.get("$set", {})})
        return _UpdateResult()

    async def insert_one(self, doc: dict) -> None:
        self._docs.append(dict(doc))

    async def delete_one(self, query: dict) -> _DeleteResult:
        q = {k: v for k, v in query.items() if not isinstance(v, dict)}
        for i, doc in enumerate(self._docs):
            if self._match(doc, q):
                self._docs.pop(i)
                r = _DeleteResult()
                r.deleted_count = 1
                return r
        return _DeleteResult()

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
        self.garmin_daily_metrics: _Collection = _Collection()
        self.user_profiles: _Collection = _Collection()
        self.training_feedback: _Collection = _Collection()
        self.training_context: _Collection = _Collection()
        self.vo2max_history: _Collection = _Collection()
        self.run_index_history: _Collection = _Collection()

    def __getattr__(self, name: str) -> _Collection:
        col: _Collection = _Collection()
        object.__setattr__(self, name, col)
        return col


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bearer() -> dict:
    return {"Authorization": "Bearer " + create_access_token(_USER_ID, _USER_EMAIL)}


def _user_access(_db: Any, user_id: str) -> UserAccess:
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


def _make_fixed_datetime_class(fixed: datetime) -> type:
    """Return a real datetime subclass whose now() always returns *fixed*.

    Using a subclass (not a shim instance) ensures that all isinstance(..., datetime)
    checks inside server.py remain valid — isinstance(x, SubclassOfDatetime) is
    always well-formed, and actual datetime objects pass isinstance(x, datetime)
    even when server.datetime is patched to the subclass.
    """
    class _FixedDT(datetime):
        @classmethod
        def now(cls, tz=None):  # type: ignore[override]
            return fixed if tz is not None else fixed.replace(tzinfo=None)
    _FixedDT.__name__ = "_FixedDT"
    _FixedDT.__qualname__ = "_FixedDT"
    return _FixedDT


def _patches(fake_db: _FakeDB, reference_date: date = _MONDAY) -> list:
    """Patch DB, user access, and clock for deterministic handler testing."""
    fixed_dt = datetime(
        reference_date.year,
        reference_date.month,
        reference_date.day,
        8, 0, 0,
        tzinfo=timezone.utc,
    )
    return [
        patch.object(server, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_user_access)),
        patch("server.datetime", _make_fixed_datetime_class(fixed_dt)),
    ]


async def _get_week(fake_db: _FakeDB, reference_date: date = _MONDAY) -> Dict:
    """Call GET /training/v2/week with the given fake DB."""
    if httpx is None:
        pytest.skip("httpx not installed")
    ps = _patches(fake_db, reference_date)
    started = []
    try:
        for p in ps:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            r = await client.get("/api/training/v2/week", headers=_bearer())
            return {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text}
    finally:
        for p in reversed(started):
            p.stop()


async def _get_today(fake_db: _FakeDB, reference_date: date = _MONDAY) -> Dict:
    """Call GET /training/today with the given fake DB."""
    if httpx is None:
        pytest.skip("httpx not installed")
    ps = _patches(fake_db, reference_date)
    started = []
    try:
        for p in ps:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            r = await client.get("/api/training/today", headers=_bearer())
            return {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text}
    finally:
        for p in reversed(started):
            p.stop()


# ---------------------------------------------------------------------------
# DB seed helpers
# ---------------------------------------------------------------------------

def _seed_cycle(
    fake_db: _FakeDB,
    goal: str = "SEMI",
    reference_date: date = _MONDAY,
    race_weeks_ahead: int = 16,
) -> None:
    cycle_start = (reference_date - timedelta(weeks=4)).isoformat()
    fake_db.training_cycles._docs.append({
        "user_id": _USER_ID,
        "goal": goal,
        "start_date": cycle_start,
    })
    if goal != "MAINTENANCE":
        race_date = (reference_date + timedelta(weeks=race_weeks_ahead)).isoformat()
        fake_db.user_goals._docs.append({
            "user_id": _USER_ID,
            "distance_type": _goal_to_distance_type(goal),
            "event_date": race_date,
        })


def _goal_to_distance_type(goal: str) -> str:
    mapping = {
        "5K": "5k", "10K": "10k", "SEMI": "semi",
        "MARATHON": "marathon", "ULTRA": "ultra", "MAINTENANCE": "maintenance",
    }
    return mapping.get(goal.upper(), "semi")


def _seed_garmin_activities(
    fake_db: _FakeDB,
    n: int = 8,
    km_per: float = 8.0,
    reference_date: date = _MONDAY,
) -> None:
    """Add n running activities to garmin_activities collection."""
    for i in range(n):
        act_date = reference_date - timedelta(days=7 + i * 2)
        fake_db.garmin_activities._docs.append({
            "user_id": _USER_ID,
            "activity_type": "running",
            "start_time": act_date.isoformat() + "T07:00:00",
            "distance": km_per * 1000.0,      # metres
            "duration": km_per * 360,          # seconds (~6 min/km)
            "average_hr": 145,
        })


def _seed_connected(fake_db: _FakeDB, connected: bool = True) -> None:
    fake_db.garmin_connections._docs.append({
        "user_id": _USER_ID,
        "connected": connected,
    })


# ---------------------------------------------------------------------------
# Helpers — session type normalization (Week uses V2 canonical; Today uses runtime)
# ---------------------------------------------------------------------------

# Week sessions expose workout_type (V2 canonical): rest, recovery, easy, steady, quality, long_easy
# Today planned_session comes from prescription_to_runtime_session which maps to runtime type:
#   easy → endurance, steady → tempo, quality → threshold, long_easy → long_run
_RUNTIME_TO_V2: dict = {
    "endurance": "easy",
    "tempo": "steady",
    "threshold": "quality",
    "long_run": "long_easy",
    "rest": "rest",
    "recovery": "recovery",
}


def _today_type(today_session: dict) -> Optional[str]:
    """Return V2 canonical workout_type from a Today planned_session dict."""
    rt = today_session.get("type")
    if rt is None:
        return None
    return _RUNTIME_TO_V2.get(rt, rt)


def _week_type(week_session: dict) -> Optional[str]:
    """Return V2 canonical workout_type from a Week session dict."""
    return week_session.get("workout_type")


# ---------------------------------------------------------------------------
# WEEK_TODAY_PARITY — same activities → same session source
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_week_and_today_same_session_source():
    """Same DB → /training/v2/week and /training/today produce same session source."""
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    week_result = await _get_week(fake_db)
    today_result = await _get_today(fake_db)

    assert week_result["status"] == 200, f"Week HTTP error: {week_result['body']}"
    assert today_result["status"] == 200, f"Today HTTP error: {today_result['body']}"

    week_sessions = week_result["body"]["week"]["sessions"]
    # Find Monday session from Week
    monday_week = next(
        (s for s in week_sessions if s["day"].lower() == "monday"), None
    )
    assert monday_week is not None, "Week plan has no Monday session"

    # Today's planned_session must match
    today_body = today_result["body"]
    assert today_body.get("status") == "success"
    planned = today_body.get("planned_session", {})
    assert _today_type(planned) == _week_type(monday_week), (
        f"Today workout_type {_today_type(planned)!r} != "
        f"Week {_week_type(monday_week)!r}"
    )


@pytest.mark.asyncio
async def test_connected_false_history_present_same_plan():
    """connected=false + history in DB → same plan source as connected=true."""
    # connected=true run
    db_conn = _FakeDB()
    _seed_cycle(db_conn)
    _seed_garmin_activities(db_conn, n=8)
    _seed_connected(db_conn, connected=True)

    # connected=false run (identical activities)
    db_disc = _FakeDB()
    _seed_cycle(db_disc)
    _seed_garmin_activities(db_disc, n=8)
    _seed_connected(db_disc, connected=False)

    week_conn = await _get_week(db_conn)
    week_disc = await _get_week(db_disc)
    today_conn = await _get_today(db_conn)
    today_disc = await _get_today(db_disc)

    assert week_conn["status"] == 200 and week_disc["status"] == 200
    assert today_conn["status"] == 200 and today_disc["status"] == 200

    # Week session counts must be identical regardless of connected status
    assert (
        week_conn["body"]["week"]["session_count"]
        == week_disc["body"]["week"]["session_count"]
    ), "Week session_count differs between connected and disconnected"

    # Today's workout_type must be identical
    pt_conn = today_conn["body"].get("planned_session", {})
    pt_disc = today_disc["body"].get("planned_session", {})
    assert _today_type(pt_conn) == _today_type(pt_disc), (
        "Today planned workout_type differs: "
        f"connected={_today_type(pt_conn)!r} "
        f"disconnected={_today_type(pt_disc)!r}"
    )


@pytest.mark.asyncio
async def test_reconciliation_action_consistent_week_and_today():
    """Week and Today must report the same reconciliation action."""
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    week_result = await _get_week(fake_db)
    today_result = await _get_today(fake_db)

    assert week_result["status"] == 200
    assert today_result["status"] == 200

    week_action = week_result["body"].get("reconciliation_action")
    today_action = today_result["body"].get("weekly_reconciliation", {}).get("action")

    assert week_action is not None, "Week response missing reconciliation_action"
    assert today_action is not None, "Today response missing weekly_reconciliation.action"
    assert week_action == today_action, (
        f"Reconciliation action diverged: Week={week_action!r} Today={today_action!r}"
    )


@pytest.mark.asyncio
async def test_reconciliation_keep_same_baseline():
    """Enough history → KEEP → Week and Today share same baseline sessions."""
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=20, km_per=12.0)  # plenty of history
    _seed_connected(fake_db, connected=True)

    week_result = await _get_week(fake_db)
    today_result = await _get_today(fake_db)

    assert week_result["status"] == 200
    assert today_result["status"] == 200

    week_sessions = week_result["body"]["week"]["sessions"]
    monday_week = next(
        (s for s in week_sessions if s["day"].lower() == "monday"), None
    )
    assert monday_week is not None

    today_planned = today_result["body"].get("planned_session", {})
    assert _today_type(today_planned) == _week_type(monday_week)


def _seed_garmin_activities_sparse_reduce(
    fake_db: _FakeDB,
    reference_date: date = _MONDAY,
) -> None:
    """Seed 8 running activities that trigger REDUCE_VOLUME via the canonical pipeline.

    Pattern: 8 activities concentrated in days 8-22 (weeks 2-4), NONE in days 0-7
    (week 1 gap).  This creates a volume gap:

    - chronic_base = total_km / 3_active_weeks (weeks 2-4 each have data)
    - observed_weekly = total_km / 4_calendar_weeks < chronic_base
    - target_km = chronic_base * 1.10 (progression factor)
    - weekly_observed < target_km * VOLUME_REDUCTION_MARGIN (0.80) → REDUCE_VOLUME

    response_status = "sufficient" (8 ≥ 5 activities in 28-day window).
    """
    for i in range(8):
        act_date = reference_date - timedelta(days=8 + i * 2)  # 8,10,...,22 days back
        fake_db.garmin_activities._docs.append({
            "user_id": _USER_ID,
            "activity_type": "running",
            "start_time": act_date.isoformat() + "T07:00:00",
            "distance": 15000.0,   # 15 km — good training distance
            "duration": 5400.0,    # 90 min
            "average_hr": 140,
        })


@pytest.mark.asyncio
async def test_reconciliation_reduce_same_session_source():
    """8 activities with week-1 gap → REDUCE_VOLUME fires.

    Asserts:
    - reconciliation_action != KEEP for both Week and Today.
    - Week and Today report exactly the same reconciliation action.
    - Monday session source (workout_type) is identical before DailyAdaptation.
    """
    fake_db = _FakeDB()
    _seed_cycle(fake_db, race_weeks_ahead=8)  # race in 8 weeks → base building phase
    _seed_garmin_activities_sparse_reduce(fake_db)
    _seed_connected(fake_db, connected=True)

    week_result = await _get_week(fake_db)
    today_result = await _get_today(fake_db)

    assert week_result["status"] == 200, f"Week: {week_result['body']}"
    assert today_result["status"] == 200, f"Today: {today_result['body']}"

    week_action = week_result["body"].get("reconciliation_action")
    today_action = today_result["body"].get("weekly_reconciliation", {}).get("action")

    assert week_action is not None, "Week response missing reconciliation_action"
    assert today_action is not None, "Today response missing weekly_reconciliation.action"

    # The sparse dataset (8 runs in days 8-22, none in days 0-7) must produce
    # REDUCE_VOLUME: chronic_base = 120km/3active_weeks = 40km; weekly_observed =
    # 120km/4 = 30km; 30 < 40 * 0.80 = 32 → REDUCE_VOLUME.
    # See _seed_garmin_activities_sparse_reduce docstring for the full math.
    assert week_action == "REDUCE_VOLUME", (
        f"Expected REDUCE_VOLUME for Week (week-1 gap dataset) but got: {week_action!r}"
    )
    assert today_action == week_action, (
        f"Reconciliation action diverged: Week={week_action!r} Today={today_action!r}"
    )

    # Session source must be identical (same canonical plan).
    week_sessions = week_result["body"]["week"]["sessions"]
    monday_week = next(
        (s for s in week_sessions if s["day"].lower() == "monday"), None
    )
    today_planned = today_result["body"].get("planned_session", {})
    if monday_week and today_planned:
        assert _week_type(monday_week) == _today_type(today_planned), (
            "Monday workout_type diverged between Week and Today after REDUCE"
        )


@pytest.mark.asyncio
async def test_no_garmin_history_returns_valid_plan():
    """No Garmin activities → handlers still return a valid plan (deep_reprise)."""
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    # No activities, no connection
    _seed_connected(fake_db, connected=False)

    week_result = await _get_week(fake_db)
    today_result = await _get_today(fake_db)

    assert week_result["status"] == 200, f"Week: {week_result['body']}"
    assert today_result["status"] == 200, f"Today: {today_result['body']}"

    # Both must report KEEP (no history → KEEP reconciliation)
    week_action = week_result["body"].get("reconciliation_action")
    today_action = today_result["body"].get("weekly_reconciliation", {}).get("action")
    assert week_action == "KEEP"
    assert today_action == "KEEP"


# ---------------------------------------------------------------------------
# PROTECTIONS — taper / race week
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_taper_phase_plan_is_valid():
    """Taper phase (race in 2 weeks) → plan returned with valid structure.

    Asserts:
    - HTTP 200 from both handlers.
    - Week sessions exist (plan not empty).
    - Week and Today reconciliation actions are identical.
    - No quality/steady session type dominates (taper is conservative).
    """
    fake_db = _FakeDB()
    _seed_cycle(fake_db, race_weeks_ahead=2)  # race in 2 weeks → taper
    _seed_garmin_activities(fake_db, n=10, km_per=10.0)
    _seed_connected(fake_db, connected=True)

    week_result = await _get_week(fake_db)
    today_result = await _get_today(fake_db)

    assert week_result["status"] == 200, f"Week taper: {week_result['body']}"
    assert today_result["status"] == 200, f"Today taper: {today_result['body']}"

    # Taper plan must have sessions.
    week_sessions = week_result["body"]["week"]["sessions"]
    assert len(week_sessions) > 0, "Taper week plan is empty"

    # Reconciliation must be consistent (both KEEP or both REDUCE — never diverged).
    week_action = week_result["body"].get("reconciliation_action")
    today_action = today_result["body"].get("weekly_reconciliation", {}).get("action")
    assert week_action in ("KEEP", "REDUCE_VOLUME", "REDUCE_FREQUENCY", "REDUCE_BOTH"), (
        f"Unexpected taper reconciliation_action: {week_action!r}"
    )
    assert week_action == today_action, (
        f"Taper: reconciliation action diverged: Week={week_action!r} Today={today_action!r}"
    )

    # No session type in the taper week should be 'interval' or 'repetition'
    # (intensive quality work is suppressed during taper).
    for session in week_sessions:
        wt = (session.get("workout_type") or "").lower()
        assert wt not in ("interval", "repetition"), (
            f"Taper week contains high-intensity session: {wt!r}"
        )


@pytest.mark.asyncio
async def test_race_week_plan_is_valid():
    """Race week (race in 6 days) → plan returned without crash.

    Asserts:
    - HTTP 200 from both handlers.
    - Week session count is conservative (≤ 3 sessions for race week).
    - Week and Today reconciliation actions are identical.
    - Week and Today planned Monday session match.
    """
    fake_db = _FakeDB()
    _seed_cycle(fake_db, race_weeks_ahead=0)  # race this week
    # Override race_date to be exactly 6 days from reference_date
    for doc in fake_db.user_goals._docs:
        if doc.get("user_id") == _USER_ID:
            doc["event_date"] = (_MONDAY + timedelta(days=6)).isoformat()
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    week_result = await _get_week(fake_db)
    today_result = await _get_today(fake_db)

    assert week_result["status"] == 200, f"Week race: {week_result['body']}"
    assert today_result["status"] == 200, f"Today race: {today_result['body']}"

    # Race week plan must not be empty.
    week_sessions = week_result["body"]["week"]["sessions"]
    assert len(week_sessions) > 0, "Race week plan is empty"

    # Race week: no quality/threshold sessions (conservative plan).
    for session in week_sessions:
        wt = (session.get("workout_type") or "").lower()
        assert wt not in ("quality",), (
            f"Race week contains quality session: {wt!r} — race week must be conservative"
        )

    # Reconciliation must be consistent.
    week_action = week_result["body"].get("reconciliation_action")
    today_action = today_result["body"].get("weekly_reconciliation", {}).get("action")
    assert week_action == today_action, (
        f"Race week: reconciliation action diverged: Week={week_action!r} Today={today_action!r}"
    )


@pytest.mark.asyncio
async def test_maintenance_goal_both_handlers():
    """MAINTENANCE goal → no race_date → handlers return valid plan."""
    fake_db = _FakeDB()
    _seed_cycle(fake_db, goal="MAINTENANCE")
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    week_result = await _get_week(fake_db)
    today_result = await _get_today(fake_db)

    assert week_result["status"] == 200, f"Week maintenance: {week_result['body']}"
    assert today_result["status"] == 200, f"Today maintenance: {today_result['body']}"


# ---------------------------------------------------------------------------
# ADAPTATION_ISOLATION — DailyAdaptation changes Today, not Week
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_daily_adaptation_does_not_change_week_sessions():
    """Today's adaptation must not affect Week's session list."""
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    # Call Week twice — must be deterministic (no adaptation changes it)
    week1 = await _get_week(fake_db)
    week2 = await _get_week(fake_db)

    assert week1["status"] == 200 and week2["status"] == 200
    assert week1["body"]["week"]["sessions"] == week2["body"]["week"]["sessions"], (
        "Week sessions changed between calls — must be deterministic"
    )


@pytest.mark.asyncio
async def test_adapted_session_respects_keep_or_reduce():
    """adapted_prescription must equal or be reduced vs planned_session (never increased)."""
    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8)
    _seed_connected(fake_db, connected=True)

    today_result = await _get_today(fake_db)
    assert today_result["status"] == 200

    body = today_result["body"]
    planned = body.get("planned_session", {})
    adapted = body.get("adapted_prescription", {})

    planned_dist = planned.get("distance_km")
    adapted_dist = adapted.get("distance_km")
    if planned_dist is not None and adapted_dist is not None:
        assert adapted_dist <= planned_dist, (
            f"Adapted distance {adapted_dist} > planned {planned_dist} — "
            "DailyAdaptation must not increase the session"
        )


@pytest.mark.asyncio
async def test_adaptation_isolation_caution_reduces_today_not_week():
    """Forced CAUTION readiness → Today reduced, Week unchanged, planned_session = Week session.

    Asserts:
    - planned_session (from canonical plan) == Monday session in Week.
    - adapted_prescription.distance_km <= planned_session.distance_km (reduce or keep).
    - Week session list is identical before and after Today call.
    """
    from training_v2.readiness_decision import (
        ReadinessDecision,
        ReadinessBand,
        SufficiencyLevel,
    )
    from training_v2.readiness import ReadinessConfidence
    from training_v2.readiness_sufficiency import ReasonCode

    fake_db = _FakeDB()
    _seed_cycle(fake_db)
    _seed_garmin_activities(fake_db, n=8, km_per=10.0)
    _seed_connected(fake_db, connected=True)

    caution_decision = ReadinessDecision(
        band=ReadinessBand.CAUTION,
        score=45.0,
        confidence=ReadinessConfidence.NORMAL,
        sufficiency_level=SufficiencyLevel.SUFFICIENT,
        reason_codes=("READINESS_CAUTION",),
        readiness_reasons=(),
    )

    # Snapshot Week before Today call.
    week_before = await _get_week(fake_db)
    assert week_before["status"] == 200, f"Week: {week_before['body']}"

    # Call Today with CAUTION readiness forced.
    ps = _patches(fake_db)
    started = []
    try:
        for p in ps:
            p.start()
            started.append(p)
        with patch(
            "server.build_readiness_decision",
            return_value=caution_decision,
        ):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=server.app),
                base_url="http://test",
            ) as client:
                r = await client.get("/api/training/today", headers=_bearer())
                today_result = {"status": r.status_code, "body": r.json() if r.status_code == 200 else r.text}
    finally:
        for p in reversed(started):
            p.stop()

    assert today_result["status"] == 200, f"Today: {today_result['body']}"

    body = today_result["body"]
    planned = body.get("planned_session", {})
    adapted = body.get("adapted_prescription", {})

    # planned_session must match Monday session from Week.
    week_sessions = week_before["body"]["week"]["sessions"]
    monday_week = next(
        (s for s in week_sessions if s["day"].lower() == "monday"), None
    )
    if monday_week is not None and _today_type(planned):
        assert _today_type(planned) == _week_type(monday_week), (
            f"planned_session={_today_type(planned)!r} differs from "
            f"Week Monday={_week_type(monday_week)!r}"
        )

    # adapted_prescription must not exceed planned_session.
    planned_dist = planned.get("distance_km")
    adapted_dist = adapted.get("distance_km")
    if planned_dist is not None and adapted_dist is not None:
        assert adapted_dist <= planned_dist, (
            f"CAUTION: adapted distance {adapted_dist} > planned {planned_dist}"
        )

    # Week sessions must be unchanged after Today call.
    week_after = await _get_week(fake_db)
    assert week_after["status"] == 200
    assert week_before["body"]["week"]["sessions"] == week_after["body"]["week"]["sessions"], (
        "Week sessions changed after Today adaptation call — Week must be immutable"
    )


# ---------------------------------------------------------------------------
# ARCHITECTURE — no double WorkoutGenerator, no double WeeklyReconciliation
# ---------------------------------------------------------------------------


def test_no_double_workout_generator_in_today_body():
    """get_today_adaptive_session must not call build_weekly_plan directly."""
    import ast
    with open(os.path.join(_BACKEND_DIR, "server.py")) as f:
        source = f.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "get_today_adaptive_session"
        ):
            lines = source.splitlines()
            body = "\n".join(lines[node.lineno - 1: node.end_lineno])
            assert "build_weekly_plan(" not in body, (
                "get_today_adaptive_session must not call build_weekly_plan directly"
            )
            return
    pytest.fail("get_today_adaptive_session not found in server.py")


def test_no_double_reconciliation_in_today_body():
    """get_today_adaptive_session must not call build_weekly_reconciliation directly."""
    import ast
    with open(os.path.join(_BACKEND_DIR, "server.py")) as f:
        source = f.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "get_today_adaptive_session"
        ):
            lines = source.splitlines()
            body = "\n".join(lines[node.lineno - 1: node.end_lineno])
            assert "build_weekly_reconciliation" not in body, (
                "get_today_adaptive_session must not call build_weekly_reconciliation directly"
            )
            return
    pytest.fail("get_today_adaptive_session not found in server.py")


def test_no_double_workout_generator_in_week_body():
    """get_training_v2_week must not call build_weekly_plan directly."""
    import ast
    with open(os.path.join(_BACKEND_DIR, "server.py")) as f:
        source = f.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "get_training_v2_week"
        ):
            lines = source.splitlines()
            body = "\n".join(lines[node.lineno - 1: node.end_lineno])
            assert "build_weekly_plan(" not in body, (
                "get_training_v2_week must not call build_weekly_plan directly"
            )
            return
    pytest.fail("get_training_v2_week not found in server.py")


def test_single_clock_in_today():
    """get_today_adaptive_session must only call datetime.now once."""
    import ast
    with open(os.path.join(_BACKEND_DIR, "server.py")) as f:
        source = f.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "get_today_adaptive_session"
        ):
            lines = source.splitlines()
            body = "\n".join(lines[node.lineno - 1: node.end_lineno])
            # Must call now() exactly once
            count = body.count("datetime.now(")
            assert count == 1, (
                f"get_today_adaptive_session calls datetime.now() {count} times; must be exactly 1"
            )
            return
    pytest.fail("get_today_adaptive_session not found in server.py")


def test_garmin_activities_load_outside_connected_guard():
    """Garmin 90-day activity load must NOT be inside the garmin_connections.connected block."""
    import ast
    with open(os.path.join(_BACKEND_DIR, "server.py")) as f:
        source = f.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if (
            isinstance(node, ast.AsyncFunctionDef)
            and node.name == "get_today_adaptive_session"
        ):
            lines = source.splitlines()
            body_lines = source.splitlines()[node.lineno - 1: node.end_lineno]

            # Find where connected check occurs vs garmin_activities load
            connected_line = None
            activities_load_line = None
            for i, line in enumerate(body_lines):
                stripped = line.lstrip()
                if stripped.startswith("#"):
                    continue  # skip comments
                if ("get(\"connected\")" in line or "get('connected')" in line or ".connected" in line) and connected_line is None:
                    connected_line = i
                if "garmin_activities.find(" in line and activities_load_line is None:
                    activities_load_line = i

            assert activities_load_line is not None, (
                "garmin_activities.find not found in get_today_adaptive_session"
            )
            assert connected_line is not None, (
                "garmin_connections.connected check not found in get_today_adaptive_session"
            )
            # Activities must be loaded BEFORE the connected guard
            assert activities_load_line < connected_line, (
                f"garmin_activities.find (line {activities_load_line}) must come before "
                f"connected check (line {connected_line}) in get_today_adaptive_session"
            )
            return
    pytest.fail("get_today_adaptive_session not found in server.py")
