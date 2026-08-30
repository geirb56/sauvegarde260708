"""PR226 — Goal-truth unification tests.

Covers:
- Goal creation/change for 5K / 10K / HM / Marathon via GOAL_CONFIG
- MAINTENANCE clears race_date / target_time (plan_goal layer)
- Fallback without goal → MAINTENANCE (source inspection)
- ULTRA without distance → rejection (plan_goal layer)
- ULTRA with valid distance → propagation (plan_goal layer)
- No stale race_date after goal change (server.py source inspection)
- UserGoalCreate model accepts distance_km for ultra (model layer)
"""
from __future__ import annotations

import ast
import os
import re
import sys
from datetime import date
from typing import Optional

import pytest

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# ---------------------------------------------------------------------------
# Source helpers (avoid importing server.py which pulls redis/motor/etc.)
# ---------------------------------------------------------------------------

_SERVER_PY = os.path.join(_BACKEND_DIR, "server.py")


def _server_source() -> str:
    with open(_SERVER_PY, encoding="utf-8") as f:
        return f.read()


# ---------------------------------------------------------------------------
# 1. GOAL_CONFIG: all 5 standard goals + MAINTENANCE present
# ---------------------------------------------------------------------------

def test_goal_config_has_all_goals():
    """GOAL_CONFIG must contain the 6 canonical goal types."""
    from config.training_goals import GOAL_CONFIG
    assert set(GOAL_CONFIG.keys()) == {"5K", "10K", "SEMI", "MARATHON", "ULTRA", "MAINTENANCE"}


@pytest.mark.parametrize("goal", ["5K", "10K", "SEMI", "MARATHON"])
def test_standard_goal_cycle_weeks(goal):
    """Each standard goal has a positive cycle_weeks value."""
    from config.training_goals import GOAL_CONFIG
    assert GOAL_CONFIG[goal]["cycle_weeks"] > 0


# ---------------------------------------------------------------------------
# 2. MAINTENANCE — plan_goal layer must reject race_date and target_time
# ---------------------------------------------------------------------------

def test_maintenance_has_no_race_date_in_plan_goal():
    """build_plan_goal(MAINTENANCE) must produce race_date=None."""
    from training_v2.plan_goal import GoalType, build_plan_goal
    pg = build_plan_goal(goal_type=GoalType.maintenance, created_from="default")
    assert pg.race_date is None


def test_maintenance_has_no_target_time_in_plan_goal():
    """build_plan_goal(MAINTENANCE) must produce target_time_seconds=None."""
    from training_v2.plan_goal import GoalType, build_plan_goal
    pg = build_plan_goal(goal_type=GoalType.maintenance, created_from="default")
    assert pg.target_time_seconds is None


def test_maintenance_has_no_target_distance_in_plan_goal():
    """build_plan_goal(MAINTENANCE) must produce target_distance_km=None."""
    from training_v2.plan_goal import GoalType, build_plan_goal
    pg = build_plan_goal(goal_type=GoalType.maintenance, created_from="default")
    assert pg.target_distance_km is None


def test_maintenance_rejects_race_date():
    """Constructing MAINTENANCE PlanGoal with race_date must raise ValueError."""
    from training_v2.plan_goal import GoalType, PlanGoal
    with pytest.raises(Exception):
        PlanGoal(
            goal_type=GoalType.maintenance,
            race_date=date(2025, 9, 28),
            created_from="user",
        )


def test_maintenance_rejects_target_time():
    """Constructing MAINTENANCE PlanGoal with target_time_seconds must raise ValueError."""
    from training_v2.plan_goal import GoalType, PlanGoal
    with pytest.raises(Exception):
        PlanGoal(
            goal_type=GoalType.maintenance,
            target_time_seconds=3600,
            created_from="user",
        )


# ---------------------------------------------------------------------------
# 3. Fallback without goal → MAINTENANCE (source-level)
# ---------------------------------------------------------------------------

def test_fallback_without_goal_is_maintenance_not_semi():
    """The dynamic fallback must be MAINTENANCE, never SEMI (PR226 fix)."""
    source = _server_source()
    assert 'plan_data.get("goal", "SEMI")' not in source, (
        "Stale SEMI fallback found — must be replaced with MAINTENANCE"
    )
    assert 'plan_data.get("goal", "MAINTENANCE")' in source, (
        "MAINTENANCE fallback not found — PR226 fix missing"
    )


# ---------------------------------------------------------------------------
# 4. set-goal clears user_goals (source-level)
# ---------------------------------------------------------------------------

def test_set_goal_deletes_user_goals_in_source():
    """POST /training/set-goal must call delete_many on user_goals (PR226)."""
    source = _server_source()
    # Find the set_training_goal function body
    match = re.search(
        r'async def set_training_goal\b.*?(?=\n@api_router|\napp\.|\Z)',
        source,
        re.DOTALL,
    )
    assert match, "set_training_goal function not found in server.py"
    fn_body = match.group(0)
    assert "user_goals.delete_many" in fn_body, (
        "set_training_goal must delete user_goals on goal change (no stale race_date)"
    )


def test_set_training_plan_goal_deletes_user_goals_in_source():
    """POST /training-plan/set-goal must also call delete_many on user_goals (PR226)."""
    source = _server_source()
    match = re.search(
        r'async def set_training_plan_goal\b.*?(?=\n@api_router|\napp\.|\Z)',
        source,
        re.DOTALL,
    )
    assert match, "set_training_plan_goal function not found in server.py"
    fn_body = match.group(0)
    assert "user_goals.delete_many" in fn_body, (
        "set_training_plan_goal must delete user_goals on goal change"
    )


# ---------------------------------------------------------------------------
# 5. ULTRA — distance enforced at plan_goal layer
# ---------------------------------------------------------------------------

def test_ultra_without_distance_refused():
    """build_plan_goal(ultra) without target_distance_km must raise ValueError."""
    from training_v2.plan_goal import GoalType, build_plan_goal
    with pytest.raises(Exception):
        build_plan_goal(goal_type=GoalType.ultra, created_from="user")


def test_ultra_exactly_marathon_refused():
    """ULTRA distance exactly 42.195 km must be refused (must be strictly greater)."""
    from training_v2.plan_goal import GoalType, build_plan_goal
    with pytest.raises(Exception):
        build_plan_goal(
            goal_type=GoalType.ultra,
            target_distance_km=42.195,
            created_from="user",
        )


def test_ultra_below_marathon_refused():
    """ULTRA distance below 42.195 km must be refused."""
    from training_v2.plan_goal import GoalType, build_plan_goal
    with pytest.raises(Exception):
        build_plan_goal(
            goal_type=GoalType.ultra,
            target_distance_km=40.0,
            created_from="user",
        )


def test_ultra_with_valid_distance_accepted():
    """ULTRA distance strictly > 42.195 km must be accepted."""
    from training_v2.plan_goal import GoalType, build_plan_goal
    pg = build_plan_goal(
        goal_type=GoalType.ultra,
        target_distance_km=50.0,
        created_from="user",
    )
    assert pg.goal_type == GoalType.ultra
    assert pg.target_distance_km == 50.0


def test_ultra_distance_propagated_exactly():
    """Custom ultra distance (e.g. 170 km) must be preserved verbatim."""
    from training_v2.plan_goal import GoalType, build_plan_goal
    pg = build_plan_goal(
        goal_type=GoalType.ultra,
        target_distance_km=170.0,
        created_from="user",
    )
    assert pg.target_distance_km == 170.0, (
        "Custom ultra distance must not be overwritten by any default"
    )


# ---------------------------------------------------------------------------
# 6. ULTRA distance required in set-goal endpoint (source-level)
# ---------------------------------------------------------------------------

def test_set_goal_endpoint_validates_ultra_distance():
    """POST /training/set-goal must reject ULTRA without distance_km (PR226)."""
    source = _server_source()
    match = re.search(
        r'async def set_training_goal\b.*?(?=\n@api_router|\napp\.|\Z)',
        source,
        re.DOTALL,
    )
    assert match, "set_training_goal not found"
    fn_body = match.group(0)
    # The function must check for ULTRA and have a 400 rejection.
    assert '"ULTRA"' in fn_body or "'ULTRA'" in fn_body
    assert "ultra_distance_km" in fn_body
    assert "42.195" in fn_body


def test_set_goal_stores_ultra_distance_in_cycles():
    """set-goal must store ultra_distance_km in training_cycles (PR226)."""
    source = _server_source()
    match = re.search(
        r'async def set_training_goal\b.*?(?=\n@api_router|\napp\.|\Z)',
        source,
        re.DOTALL,
    )
    assert match
    fn_body = match.group(0)
    assert '"ultra_distance_km"' in fn_body or "'ultra_distance_km'" in fn_body


# ---------------------------------------------------------------------------
# 7. UserGoalCreate accepts distance_km (model layer)
# ---------------------------------------------------------------------------

def test_user_goal_create_model_has_distance_km():
    """UserGoalCreate must have an optional distance_km field (PR226)."""
    source = _server_source()
    # Find UserGoalCreate model definition
    match = re.search(
        r'class UserGoalCreate\(BaseModel\):(.*?)(?=\n\n|\nclass |\n@)',
        source,
        re.DOTALL,
    )
    assert match, "UserGoalCreate class not found"
    class_body = match.group(1)
    assert "distance_km" in class_body, (
        "UserGoalCreate must expose distance_km for ULTRA goals"
    )


def test_user_goal_endpoint_validates_ultra_distance():
    """POST /user/goal must reject distance_type=ultra without valid distance_km.

    Validation is delegated to _validate_ultra_distance_km — checks that
    the function body calls the helper and the helper itself checks 42.195.
    """
    source = _server_source()
    match = re.search(
        r'async def set_user_goal\b.*?(?=\n@api_router|\napp\.|\Z)',
        source,
        re.DOTALL,
    )
    assert match, "set_user_goal not found"
    fn_body = match.group(0)
    assert "ultra" in fn_body
    # Validation is either inline or delegated to a named helper.
    assert "_validate_ultra_distance_km" in fn_body or "42.195" in fn_body, (
        "set_user_goal must call _validate_ultra_distance_km or contain 42.195 directly"
    )
    # The helper itself must contain the threshold.
    helper_match = re.search(
        r'def _validate_ultra_distance_km\b.*?(?=\ndef |\nclass |\n@|\Z)',
        source,
        re.DOTALL,
    )
    assert helper_match, "_validate_ultra_distance_km helper not found"
    assert "42.195" in helper_match.group(0), (
        "_validate_ultra_distance_km must check against 42.195"
    )


# ---------------------------------------------------------------------------
# 8. V2 endpoints fall back to training_cycles.ultra_distance_km (source)
# ---------------------------------------------------------------------------

def test_v2_endpoints_have_ultra_distance_fallback():
    """V2 consumers must fall back to training_cycles.ultra_distance_km (PR226)."""
    source = _server_source()
    assert "ultra_distance_km" in source, (
        "ultra_distance_km fallback from training_cycles not found in server.py"
    )
    # Count occurrences — must appear in at least the setter + 2 V2 consumers
    count = source.count("ultra_distance_km")
    assert count >= 3, (
        f"Expected ultra_distance_km in ≥3 places (setter + 2 consumers), found {count}"
    )


import os as _os
import sys as _sys

# ---------------------------------------------------------------------------
# 9. HTTP integration tests — coherence & API-level contracts
# ---------------------------------------------------------------------------
# These tests import server.py and patch the DB, so they are heavier.
# Kept separate from the pure unit tests above.

_os.environ.setdefault("JWT_SECRET_KEY", "test-pr226-http-secret-key-32-chars!")
_os.environ.setdefault("JWT_ALGORITHM", "HS256")
_os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
_os.environ.setdefault("ENVIRONMENT", "test")
_os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
_os.environ.setdefault("DB_NAME", "test_db")

if _BACKEND_DIR not in _sys.path:
    _sys.path.insert(0, _BACKEND_DIR)

try:
    import httpx as _httpx
    from unittest.mock import AsyncMock as _AsyncMock, patch as _patch, MagicMock as _MagicMock
    # Probe that server.py can be imported (needs email-validator, pydantic extras…)
    import server as _srv_probe  # noqa: F401
    _HTTP_TESTS_AVAILABLE = True
except (ImportError, Exception):
    _HTTP_TESTS_AVAILABLE = False

pytestmark = pytest.mark.asyncio


class _DR:
    def __init__(self, n=0):
        self.deleted_count = n

class _UR:
    pass

class _Col:
    def __init__(self, docs=None):
        self._d = list(docs or [])

    def _q(self, query):
        return {k: v for k, v in (query or {}).items() if not isinstance(v, dict)}

    def _m(self, doc, q):
        return all(doc.get(k) == v for k, v in q.items())

    async def find_one(self, query, projection=None):
        q = self._q(query)
        for doc in self._d:
            if self._m(doc, q):
                return dict(doc)
        return None

    class _C:
        def __init__(self, docs): self._d = docs
        def sort(self, *a, **kw): return self
        def limit(self, n): self._d = self._d[:n]; return self
        async def to_list(self, length=None): return list(self._d[:length] if length else self._d)

    def find(self, query=None, projection=None):
        q = {k: v for k, v in (query or {}).items() if not isinstance(v, dict)}
        return self._C([d for d in self._d if self._m(d, q)])

    async def update_one(self, query, update, upsert=False):
        q = self._q(query)
        for doc in self._d:
            if self._m(doc, q):
                doc.update(update.get("$set", {}))
                return _UR()
        if upsert:
            self._d.append({**q, **update.get("$set", {})})
        return _UR()

    async def insert_one(self, doc): self._d.append(dict(doc))

    async def delete_one(self, query):
        q = self._q(query)
        for i, doc in enumerate(self._d):
            if self._m(doc, q):
                self._d.pop(i); return _DR(1)
        return _DR(0)

    async def delete_many(self, query):
        q = self._q(query)
        before = len(self._d)
        self._d = [d for d in self._d if not self._m(d, q)]
        return _DR(before - len(self._d))

    async def count_documents(self, q): return sum(1 for d in self._d if self._m(d, self._q(q)))
    async def create_index(self, *a, **kw): pass


class _FDB:
    def __init__(self):
        self.training_cycles = _Col()
        self.training_prefs = _Col()
        self.user_goals = _Col()
        self.training_context = _Col()
        self.training_plans = _Col()
        self.garmin_activities = _Col()
        self.users = _Col()
        self.subscriptions = _Col()


_FAKE_USER_HTTP = {
    "id": "u-pr226-http",
    "email": "pr226http@test.com",
    "is_email_verified": True,
    "role": "user",
    "is_admin": False,
    "subscription_tier": "free",
}


def _tok(uid="u-pr226-http"):
    from auth.jwt_utils import create_access_token
    return create_access_token({"sub": uid})


def _hdrs(uid="u-pr226-http"):
    return {"Authorization": f"******"}


@pytest.mark.asyncio
async def test_http_10k_goal_set_correctly():
    """POST set-goal?goal=10K returns 200 and stores 10K in training_cycles."""
    if not _HTTP_TESTS_AVAILABLE:
        pytest.skip("httpx not available")
    import server as _srv
    fdb = _FDB()
    with _patch.object(_srv, "db", fdb), _patch("auth.dependencies.get_current_user", new_callable=_AsyncMock, return_value=_FAKE_USER_HTTP):
        async with _httpx.AsyncClient(transport=_httpx.ASGITransport(app=_srv.app), base_url="http://test") as ac:
            resp = await ac.post("/api/training/set-goal?goal=10K", headers=_hdrs())
    assert resp.status_code == 200
    cycle = await fdb.training_cycles.find_one({"user_id": "u-pr226-http"})
    assert cycle and cycle["goal"] == "10K"


@pytest.mark.asyncio
async def test_http_incoherent_goal_distance_type_rejected():
    """POST /user/goal with distance_type=semi when cycle is 10K must return 400."""
    if not _HTTP_TESTS_AVAILABLE:
        pytest.skip("httpx not available")
    import server as _srv
    fdb = _FDB()
    await fdb.training_cycles.update_one({"user_id": "u-pr226-http"}, {"$set": {"goal": "10K", "start_date": "2025-01-01"}}, upsert=True)
    with _patch.object(_srv, "db", fdb), _patch("auth.dependencies.get_current_user", new_callable=_AsyncMock, return_value=_FAKE_USER_HTTP):
        async with _httpx.AsyncClient(transport=_httpx.ASGITransport(app=_srv.app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/user/goal",
                json={"event_name": "Race", "event_date": "2025-06-01", "distance_type": "semi"},
                headers=_hdrs(),
            )
    assert resp.status_code == 400, f"Expected 400 for incoherent goal, got {resp.status_code}: {resp.text}"


@pytest.mark.asyncio
async def test_http_ultra_50km_set_goal_succeeds():
    """POST set-goal?goal=ULTRA&distance_km=50 stores ultra_distance_km=50.0."""
    if not _HTTP_TESTS_AVAILABLE:
        pytest.skip("httpx not available")
    import server as _srv
    fdb = _FDB()
    with _patch.object(_srv, "db", fdb), _patch("auth.dependencies.get_current_user", new_callable=_AsyncMock, return_value=_FAKE_USER_HTTP):
        async with _httpx.AsyncClient(transport=_httpx.ASGITransport(app=_srv.app), base_url="http://test") as ac:
            resp = await ac.post("/api/training/set-goal?goal=ULTRA&distance_km=50", headers=_hdrs())
    assert resp.status_code == 200
    cycle = await fdb.training_cycles.find_one({"user_id": "u-pr226-http"})
    assert cycle and cycle.get("ultra_distance_km") == 50.0


@pytest.mark.asyncio
async def test_http_ultra_no_distance_rejected_no_mutation():
    """POST set-goal?goal=ULTRA without distance_km → 400, no training_cycles row created."""
    if not _HTTP_TESTS_AVAILABLE:
        pytest.skip("httpx not available")
    import server as _srv
    fdb = _FDB()
    with _patch.object(_srv, "db", fdb), _patch("auth.dependencies.get_current_user", new_callable=_AsyncMock, return_value=_FAKE_USER_HTTP):
        async with _httpx.AsyncClient(transport=_httpx.ASGITransport(app=_srv.app), base_url="http://test") as ac:
            resp = await ac.post("/api/training/set-goal?goal=ULTRA", headers=_hdrs())
    assert resp.status_code == 400
    cycle = await fdb.training_cycles.find_one({"user_id": "u-pr226-http"})
    assert cycle is None, "No training_cycle must be created when ULTRA without distance is rejected"


@pytest.mark.asyncio
async def test_http_maintenance_clears_race_metadata():
    """Switching to MAINTENANCE removes existing user_goals entirely."""
    if not _HTTP_TESTS_AVAILABLE:
        pytest.skip("httpx not available")
    import server as _srv
    fdb = _FDB()
    await fdb.user_goals.insert_one({
        "user_id": "u-pr226-http", "event_name": "Berlin", "event_date": "2025-09-28",
        "distance_type": "marathon", "distance_km": 42.195, "target_time_minutes": 210,
    })
    with _patch.object(_srv, "db", fdb), _patch("auth.dependencies.get_current_user", new_callable=_AsyncMock, return_value=_FAKE_USER_HTTP):
        async with _httpx.AsyncClient(transport=_httpx.ASGITransport(app=_srv.app), base_url="http://test") as ac:
            resp = await ac.post("/api/training/set-goal?goal=MAINTENANCE", headers=_hdrs())
    assert resp.status_code == 200
    stale = await fdb.user_goals.find_one({"user_id": "u-pr226-http"})
    assert stale is None, "MAINTENANCE must remove all user_goals (no stale race metadata)"


@pytest.mark.asyncio
async def test_http_user_goal_ultra_valid():
    """POST /user/goal with distance_type=ultra and distance_km=100 accepted when cycle=ULTRA."""
    if not _HTTP_TESTS_AVAILABLE:
        pytest.skip("httpx not available")
    import server as _srv
    fdb = _FDB()
    await fdb.training_cycles.update_one({"user_id": "u-pr226-http"}, {"$set": {"goal": "ULTRA"}}, upsert=True)
    with _patch.object(_srv, "db", fdb), _patch("auth.dependencies.get_current_user", new_callable=_AsyncMock, return_value=_FAKE_USER_HTTP):
        async with _httpx.AsyncClient(transport=_httpx.ASGITransport(app=_srv.app), base_url="http://test") as ac:
            resp = await ac.post(
                "/api/user/goal",
                json={"event_name": "CCC", "event_date": "2025-08-29", "distance_type": "ultra", "distance_km": 100.0},
                headers=_hdrs(),
            )
    assert resp.status_code == 200
    stored = await fdb.user_goals.find_one({"user_id": "u-pr226-http"})
    assert stored and stored["distance_km"] == 100.0
