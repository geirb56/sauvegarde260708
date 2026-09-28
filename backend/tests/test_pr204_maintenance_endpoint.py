"""PR204 — Real endpoint tests: Training Goal MAINTENANCE.

These tests exercise the **real** FastAPI handlers via httpx.AsyncClient +
ASGITransport(app=server.app).  They use an in-memory fake database and JWT
auth, following the pattern of test_training_metrics_endpoint.py.

Contracts verified
------------------
SET_GOAL_ENDPOINT  — POST /training/set-goal?goal=MAINTENANCE
    • HTTP 200
    • response.goal == "MAINTENANCE"
    • "Invalid goal" absent from response
    • training_cycles persisted with goal=MAINTENANCE
    • start_date persisted (today)

REFRESH_ENDPOINT   — POST /training/refresh?sessions={2,3,4,5,6} with MAINTENANCE cycle
    • HTTP 200 for each session count
    • no crash with goal=MAINTENANCE
    • sessions_per_week stored in training_prefs (sessions in [2,3,4,5,6])
    • plan payload returned
"""

from __future__ import annotations

import os
import sys
from datetime import datetime, timezone, date, timedelta
from typing import Any, List, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
import pytest_asyncio
import httpx

# ---------------------------------------------------------------------------
# Environment — must be set before server is imported
# ---------------------------------------------------------------------------
os.environ.setdefault("JWT_SECRET_KEY", "test-pr204-endpoint-secret-32chars!!")
os.environ.setdefault("JWT_SECRET", "test-pr204-endpoint-secret-32chars!!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

_BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _BACKEND_DIR not in sys.path:
    sys.path.insert(0, _BACKEND_DIR)

# Ensure the backend `config` package is used (not root-level config.py).
if "config" in sys.modules:
    _config_mod = sys.modules["config"]
    _config_file = getattr(_config_mod, "__file__", "") or ""
    if "__path__" not in dir(_config_mod) or _BACKEND_DIR not in _config_file:
        for _key in [k for k in sys.modules if k == "config" or k.startswith("config.")]:
            del sys.modules[_key]

import server  # noqa: E402
from auth.jwt_utils import create_access_token  # noqa: E402
from access_control import Tier, UserAccess  # noqa: E402

pytestmark = pytest.mark.asyncio

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

_USER_ID = "pr204-test-user"
_USER_EMAIL = "pr204@example.com"

# ---------------------------------------------------------------------------
# Minimal async-compatible fake database
# ---------------------------------------------------------------------------


class _UpdateResult:
    """Minimal mock for pymongo UpdateResult."""
    matched_count = 1
    modified_count = 1


class _DeleteResult:
    deleted_count = 0


class _Collection:
    """In-memory collection supporting find_one, find, update_one, insert_one, delete_one."""

    def __init__(self, docs: Optional[List[dict]] = None) -> None:
        self._docs: List[dict] = list(docs or [])

    def _match(self, doc: dict, query: dict) -> bool:
        for k, v in query.items():
            if isinstance(v, dict):
                continue  # skip operators like $gte
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
                set_fields = update.get("$set", {})
                doc.update(set_fields)
                return _UpdateResult()
        # Not found — upsert
        if upsert:
            new_doc = {**q, **update.get("$set", {})}
            self._docs.append(new_doc)
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

    async def delete_many(self, query: dict) -> _DeleteResult:
        q = {k: v for k, v in query.items() if not isinstance(v, dict)}
        kept_docs = []
        deleted = 0
        for doc in self._docs:
            if self._match(doc, q):
                deleted += 1
            else:
                kept_docs.append(doc)
        self._docs = kept_docs
        result = _DeleteResult()
        result.deleted_count = deleted
        return result

    async def count_documents(self, query: dict) -> int:
        q = {k: v for k, v in query.items() if not isinstance(v, dict)}
        return sum(1 for d in self._docs if self._match(d, q))

    async def create_index(self, *_a: Any, **_kw: Any) -> None:
        pass


class _FakeDB:
    """In-memory database stub for PR204 endpoint tests."""

    def __init__(self) -> None:
        self.training_cycles: _Collection = _Collection()
        self.training_prefs: _Collection = _Collection()
        self.user_goals: _Collection = _Collection()
        self.workouts: _Collection = _Collection()
        self.garmin_activities: _Collection = _Collection()
        self.user_profiles: _Collection = _Collection()
        self.training_context: _Collection = _Collection()
        self.users: _Collection = _Collection([
            {"id": _USER_ID, "email": _USER_EMAIL, "is_active": True, "is_email_verified": True}
        ])

    def __getattr__(self, name: str) -> _Collection:
        col: _Collection = _Collection()
        object.__setattr__(self, name, col)
        return col


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _bearer(user_id: str = _USER_ID, email: str = _USER_EMAIL) -> dict:
    return {"Authorization": "Bearer " + create_access_token(user_id, email)}


def _user_access(_db: Any, user_id: str) -> UserAccess:
    return UserAccess(user_id=user_id, tier=Tier.PREMIUM)


def _patches(fake_db: _FakeDB) -> list:
    return [
        patch.object(server, "db", fake_db),
        patch.object(server.app.state, "db", fake_db),
        patch("server.get_user_access", AsyncMock(side_effect=_user_access)),
    ]


async def _call(method: str, path: str, patches_list: list, **kwargs) -> httpx.Response:
    started = []
    try:
        for p in patches_list:
            p.start()
            started.append(p)
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=server.app),
            base_url="http://test",
        ) as client:
            fn = getattr(client, method)
            return await fn(path, **kwargs)
    finally:
        for p in reversed(started):
            p.stop()


# ---------------------------------------------------------------------------
# SET_GOAL ENDPOINT — Real handler tests
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_set_goal_maintenance_http_success():
    """POST /training/set-goal?goal=MAINTENANCE → HTTP 200."""
    fake_db = _FakeDB()
    r = await _call("post", "/api/training/set-goal?goal=MAINTENANCE",
                    _patches(fake_db), headers=_bearer())
    assert r.status_code == 200, r.text


@pytest.mark.asyncio
async def test_set_goal_maintenance_response_valid():
    """Response contains goal=MAINTENANCE and status=updated; no 'Invalid goal'."""
    fake_db = _FakeDB()
    r = await _call("post", "/api/training/set-goal?goal=MAINTENANCE",
                    _patches(fake_db), headers=_bearer())
    assert r.status_code == 200, r.text
    body = r.json()
    assert "Invalid goal" not in str(body), f"Unexpected: {body}"
    assert body.get("goal") == "MAINTENANCE"
    assert body.get("status") == "updated"


@pytest.mark.asyncio
async def test_set_goal_maintenance_cycle_persisted():
    """training_cycles collection is updated with goal=MAINTENANCE after the call."""
    fake_db = _FakeDB()
    r = await _call("post", "/api/training/set-goal?goal=MAINTENANCE",
                    _patches(fake_db), headers=_bearer())
    assert r.status_code == 200, r.text

    # Inspect in-memory collection directly
    persisted = await fake_db.training_cycles.find_one({"user_id": _USER_ID})
    assert persisted is not None, "No training_cycles document was upserted"
    assert persisted.get("goal") == "MAINTENANCE"


@pytest.mark.asyncio
async def test_set_goal_maintenance_start_date_persisted():
    """start_date is persisted (today's date) when goal=MAINTENANCE is set."""
    fake_db = _FakeDB()
    before = datetime.now(timezone.utc)
    r = await _call("post", "/api/training/set-goal?goal=MAINTENANCE",
                    _patches(fake_db), headers=_bearer())
    after = datetime.now(timezone.utc)
    assert r.status_code == 200, r.text

    persisted = await fake_db.training_cycles.find_one({"user_id": _USER_ID})
    assert persisted is not None
    start_date = persisted.get("start_date")
    assert start_date is not None, "start_date not persisted"
    # start_date should be a datetime between before and after
    if isinstance(start_date, str):
        start_date = datetime.fromisoformat(start_date.replace("Z", "+00:00"))
    if isinstance(start_date, datetime) and start_date.tzinfo is None:
        start_date = start_date.replace(tzinfo=timezone.utc)
    if isinstance(start_date, datetime):
        assert before <= start_date <= after, f"start_date {start_date} not between {before} and {after}"


@pytest.mark.asyncio
async def test_set_goal_maintenance_no_race_date_created():
    """set-goal handler must NOT write race_date to training_cycles for MAINTENANCE."""
    fake_db = _FakeDB()
    r = await _call("post", "/api/training/set-goal?goal=MAINTENANCE",
                    _patches(fake_db), headers=_bearer())
    assert r.status_code == 200, r.text
    persisted = await fake_db.training_cycles.find_one({"user_id": _USER_ID})
    assert persisted is not None
    assert persisted.get("race_date") is None, (
        f"race_date must not be set by set-goal handler: {persisted}"
    )
    assert persisted.get("target_time") is None, (
        f"target_time must not be set by set-goal handler: {persisted}"
    )

@pytest.mark.asyncio
async def test_set_goal_invalid_value_rejected():
    """POST /training/set-goal?goal=INVALID returns error, not 200 with goal."""
    fake_db = _FakeDB()
    r = await _call("post", "/api/training/set-goal?goal=INVALID",
                    _patches(fake_db), headers=_bearer())
    body = r.json()
    assert body.get("goal") != "INVALID", f"INVALID goal should not be persisted: {body}"
    assert "error" in body or r.status_code != 200, f"Expected error for invalid goal: {body}"


# ---------------------------------------------------------------------------
# REFRESH ENDPOINT — Real handler tests with MAINTENANCE cycle active
# ---------------------------------------------------------------------------

def _make_db_with_maintenance_cycle(user_id: str = _USER_ID) -> _FakeDB:
    """Return a _FakeDB pre-seeded with a MAINTENANCE training cycle."""
    fake_db = _FakeDB()
    fake_db.training_cycles._docs.append({
        "user_id": user_id,
        "goal": "MAINTENANCE",
        "start_date": datetime.now(timezone.utc),
        "updated_at": datetime.now(timezone.utc),
    })
    return fake_db
