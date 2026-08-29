"""PR #220 — Admin attribution only after authenticated identity proof.

Invariant verified:
    IDENTITY PROVED → CANONICAL USER RESOLVED → ADMIN EVALUATED → ADMIN ATTRIBUTED (maybe)

Tests:
  1. Authenticated admin-email user → is_admin=True
  2. Authenticated non-admin user → is_admin=False
  3. Client registers with admin email → role stored as "user", not "admin"
  4. Server-side identity wins over any pre-auth client claim
  5. Unauthenticated request → no admin, 401
  6. Regression: normal users can still register and log in
  7. Admin guard rejects non-admin authenticated user
"""

from __future__ import annotations

import asyncio
import os
import sys

import httpx
import pytest
import pytest_asyncio

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

from auth.jwt_utils import create_access_token
from auth.mongo_errors import DuplicateKeyError

pytestmark = pytest.mark.asyncio

_ADMIN_EMAIL = "admin@runindex.io"
_USER_EMAIL = "user@runindex.io"
_PASSWORD = "Password1!"


# ── In-memory DB ────────────────────────────────────────────────────────────────

class _FakeCollection:
    def __init__(self, *, unique_fields=None):
        self._docs: list = []
        self._unique_fields = tuple(unique_fields or ())
        self._lock = asyncio.Lock()

    def _match(self, doc, query):
        for key, value in query.items():
            if key.startswith("$"):
                if key == "$or":
                    if not any(self._match(doc, sub) for sub in value):
                        return False
                continue
            if isinstance(value, dict):
                for op, val in value.items():
                    dv = doc.get(key)
                    if op == "$gt" and not (dv is not None and dv > val):
                        return False
                    elif op == "$lt" and not (dv is not None and dv < val):
                        return False
            else:
                if doc.get(key) != value:
                    return False
        return True

    def _project(self, doc, projection):
        if not projection:
            return doc.copy()
        excl = {k for k, v in projection.items() if not v and k != "_id"}
        incl = {k for k, v in projection.items() if v}
        result = doc.copy()
        if incl:
            result = {k: doc[k] for k in incl if k in doc}
        for k in excl:
            result.pop(k, None)
        return result

    async def find_one(self, query, projection=None):
        for doc in self._docs:
            if self._match(doc, query):
                return self._project(doc, projection)
        return None

    async def insert_one(self, doc):
        async with self._lock:
            candidate = doc.copy()
            for existing in self._docs:
                for field in self._unique_fields:
                    value = candidate.get(field)
                    if value is not None and existing.get(field) == value:
                        raise DuplicateKeyError(f"Duplicate key for {field}")
            self._docs.append(candidate)

    async def update_one(self, query, update):
        for doc in self._docs:
            if self._match(doc, query):
                if "$set" in update:
                    doc.update(update["$set"])
                if "$unset" in update:
                    for k in update["$unset"]:
                        doc.pop(k, None)
                if "$addToSet" in update:
                    for k, v in update["$addToSet"].items():
                        lst = doc.setdefault(k, [])
                        if v not in lst:
                            lst.append(v)
                break

    async def create_index(self, *args, **kwargs):
        pass

    async def count_documents(self, query):
        return sum(1 for doc in self._docs if self._match(doc, query))


class _FakeDB:
    def __init__(self):
        self.users = _FakeCollection(unique_fields=("email", "id"))
        self.subscriptions = _FakeCollection(unique_fields=("user_id",))
        self.garmin_connections = _FakeCollection(unique_fields=("user_id",))

    def __getattr__(self, name):
        return _FakeCollection()


# ── App factory ─────────────────────────────────────────────────────────────────

def _make_app(fake_db):
    from fastapi import FastAPI, Depends
    from fastapi.responses import JSONResponse
    from auth.router import auth_router
    from auth.dependencies import get_current_user, require_admin

    app = FastAPI()
    app.include_router(auth_router)
    app.state.db = fake_db

    @app.get("/protected")
    async def _protected(user: dict = Depends(get_current_user)):
        return user

    @app.get("/admin-only")
    async def _admin_only(user: dict = Depends(require_admin)):
        return user

    return app


# ── Fixtures ─────────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_db():
    return _FakeDB()


@pytest.fixture
def app(fake_db):
    return _make_app(fake_db)


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as c:
        yield c


# ── Helpers ──────────────────────────────────────────────────────────────────────

def _bearer(token: str):
    return {"Authorization": "Bearer " + token}


async def _register_and_login(client, email: str, password: str = _PASSWORD):
    r = await client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Authenticated admin-email user → is_admin=True after auth
# ═══════════════════════════════════════════════════════════════════════════════

async def test_authenticated_admin_user_receives_admin_status(client, monkeypatch):
    """After successful auth, a user with an admin email is recognised as admin."""
    monkeypatch.setenv("ADMIN_EMAILS", _ADMIN_EMAIL)
    token = await _register_and_login(client, _ADMIN_EMAIL)
    res = await client.get("/protected", headers=_bearer(token))
    assert res.status_code == 200
    data = res.json()
    assert data["is_admin"] is True
    assert data["role"] == "admin"
    assert data["authenticated"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — Authenticated non-admin user → no admin
# ═══════════════════════════════════════════════════════════════════════════════

async def test_authenticated_non_admin_user_has_no_admin_status(client, monkeypatch):
    """A successfully authenticated user not in ADMIN_EMAILS gets no admin rights."""
    monkeypatch.setenv("ADMIN_EMAILS", _ADMIN_EMAIL)
    token = await _register_and_login(client, _USER_EMAIL)
    res = await client.get("/protected", headers=_bearer(token))
    assert res.status_code == 200
    data = res.json()
    assert data["is_admin"] is False
    assert data["role"] == "user"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Client-supplied admin email at register → role stored as "user"
# ═══════════════════════════════════════════════════════════════════════════════

async def test_register_stores_role_user_not_admin_in_db(client, fake_db, monkeypatch):
    """Registration must NEVER write role=admin to the DB based on client email."""
    monkeypatch.setenv("ADMIN_EMAILS", _ADMIN_EMAIL)
    await _register_and_login(client, _ADMIN_EMAIL)

    stored = await fake_db.users.find_one({"email": _ADMIN_EMAIL})
    assert stored is not None
    # The persisted role must be "user" — admin is evaluated at auth time only
    assert stored.get("role") == "user", (
        f"role must be stored as 'user' at registration; got {stored.get('role')!r}"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Server-side identity always wins over client claim
# ═══════════════════════════════════════════════════════════════════════════════

async def test_server_identity_wins_over_client_claim(client, fake_db, monkeypatch):
    """Even if a client registers with an admin email, the DB role is 'user' and
    admin is resolved at auth time from the server-side DB record, not from the
    registration payload."""
    monkeypatch.setenv("ADMIN_EMAILS", _ADMIN_EMAIL)

    # Attacker registers with admin email
    token = await _register_and_login(client, _ADMIN_EMAIL)

    # The stored role is "user" (fix invariant: no pre-auth admin bake-in)
    stored = await fake_db.users.find_one({"email": _ADMIN_EMAIL})
    assert stored["role"] == "user"

    # Yet the authenticated response correctly reflects admin (email in ADMIN_EMAILS)
    # because resolve_user_role checks the DB email at auth time
    res = await client.get("/protected", headers=_bearer(token))
    assert res.status_code == 200
    data = res.json()
    assert data["is_admin"] is True   # email-based check in roles.py fires post-auth


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — Unauthenticated request → 401, no admin
# ═══════════════════════════════════════════════════════════════════════════════

async def test_unauthenticated_request_gets_no_admin(client):
    """A request without a token must be rejected with 401."""
    res = await client.get("/protected")
    assert res.status_code == 401

    res_admin = await client.get("/admin-only")
    assert res_admin.status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — Regression: normal users can still use the auth flow
# ═══════════════════════════════════════════════════════════════════════════════

async def test_normal_user_can_register_and_login(client, monkeypatch):
    """Normal registration and login flows must not be broken by the fix."""
    monkeypatch.setenv("ADMIN_EMAILS", "")

    reg = await client.post(
        "/auth/register",
        json={"email": "normal@example.com", "password": _PASSWORD},
    )
    assert reg.status_code == 201
    token = reg.json()["access_token"]

    login = await client.post(
        "/auth/login",
        json={"email": "normal@example.com", "password": _PASSWORD},
    )
    assert login.status_code == 200
    login_token = login.json()["access_token"]

    for tok in (token, login_token):
        res = await client.get("/protected", headers=_bearer(tok))
        assert res.status_code == 200
        assert res.json()["email"] == "normal@example.com"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7 — Admin guard rejects authenticated non-admin
# ═══════════════════════════════════════════════════════════════════════════════

async def test_admin_guard_rejects_non_admin(client, monkeypatch):
    """require_admin must return 403 for a valid but non-admin authenticated user."""
    monkeypatch.setenv("ADMIN_EMAILS", _ADMIN_EMAIL)

    token = await _register_and_login(client, _USER_EMAIL)
    res = await client.get("/admin-only", headers=_bearer(token))
    assert res.status_code == 403


async def test_admin_guard_allows_admin(client, monkeypatch):
    """require_admin must allow a valid, admin-email authenticated user."""
    monkeypatch.setenv("ADMIN_EMAILS", _ADMIN_EMAIL)

    token = await _register_and_login(client, _ADMIN_EMAIL)
    res = await client.get("/admin-only", headers=_bearer(token))
    assert res.status_code == 200
    assert res.json()["is_admin"] is True
