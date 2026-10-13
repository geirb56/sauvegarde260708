"""PR #219 — A55: ADMIN_EMAILS requires verified email identity.

Security invariant:
    ADMIN_EMAIL + is_email_verified=False  →  USER
    ADMIN_EMAIL + is_email_verified=True   →  ADMIN

After register with an admin email, is_email_verified=False so the JWT returned
does NOT grant admin access. Admin is only granted after the email is verified
server-side.

Tests:
  1.  ADMIN_EMAIL + unverified → role=user, is_admin=False
  2.  ADMIN_EMAIL + unverified → require_admin = 403
  3.  ADMIN_EMAIL + verified   → role=admin, is_admin=True
  4.  ADMIN_EMAIL + verified   → require_admin = 200
  5.  Normal email verified    → role=user
  6.  Normal email unverified  → role=user
  7.  register always persists role="user"
  8.  Unauthenticated          → 401
  9.  Client cannot self-grant admin via register payload
 10.  Explicit DB role="admin" (legitimate admin account) continues to work
"""

from __future__ import annotations

import asyncio
import os
import sys
from datetime import datetime, timezone

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


async def _register(client, email: str, password: str = _PASSWORD):
    r = await client.post("/auth/register", json={"email": email, "password": password})
    assert r.status_code == 201, r.text
    return r.json()["access_token"]


async def _verify_email_in_db(fake_db, email: str) -> None:
    """Simulate server-side email verification (e.g. via email link click)."""
    await fake_db.users.update_one(
        {"email": email},
        {"$set": {"is_email_verified": True}},
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — A55 exploit: ADMIN_EMAIL + unverified → USER  (not admin)
# ═══════════════════════════════════════════════════════════════════════════════

async def test_admin_email_unverified_gets_user_role(client, fake_db, monkeypatch):
    """A55 exploit scenario: register with admin email → JWT does NOT grant admin.

    register sets is_email_verified=False; JWT after register must yield
    role=user / is_admin=False even though the email is in ADMIN_EMAILS.
    """
    monkeypatch.setenv("ADMIN_EMAILS", _ADMIN_EMAIL)

    token = await _register(client, _ADMIN_EMAIL)

    # Confirm DB state
    stored = await fake_db.users.find_one({"email": _ADMIN_EMAIL})
    assert stored is not None
    assert stored.get("is_email_verified") is False
    assert stored.get("role") == "user"

    # JWT from register must NOT grant admin
    res = await client.get("/protected", headers=_bearer(token))
    assert res.status_code == 200
    data = res.json()
    assert data["is_admin"] is False, "A55: unverified admin email must not grant is_admin=True"
    assert data["role"] == "user", "A55: unverified admin email must not grant role=admin"
    assert data["is_email_verified"] is False


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — ADMIN_EMAIL + unverified → require_admin = 403
# ═══════════════════════════════════════════════════════════════════════════════

async def test_admin_email_unverified_blocked_by_require_admin(client, monkeypatch):
    """require_admin must return 403 for a valid JWT with unverified admin email."""
    monkeypatch.setenv("ADMIN_EMAILS", _ADMIN_EMAIL)

    token = await _register(client, _ADMIN_EMAIL)
    res = await client.get("/admin-only", headers=_bearer(token))
    assert res.status_code == 403, (
        "A55: unverified admin email JWT must be rejected by require_admin with 403"
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — ADMIN_EMAIL + verified → role=admin, is_admin=True
# ═══════════════════════════════════════════════════════════════════════════════

async def test_admin_email_verified_gets_admin_role(client, fake_db, monkeypatch):
    """After server-side email verification, ADMIN_EMAIL user becomes admin."""
    monkeypatch.setenv("ADMIN_EMAILS", _ADMIN_EMAIL)

    token = await _register(client, _ADMIN_EMAIL)

    # Before verification: USER
    res = await client.get("/protected", headers=_bearer(token))
    assert res.json()["is_admin"] is False

    # Simulate server-side email verification
    await _verify_email_in_db(fake_db, _ADMIN_EMAIL)

    # After verification: ADMIN
    res2 = await client.get("/protected", headers=_bearer(token))
    assert res2.status_code == 200
    data = res2.json()
    assert data["is_admin"] is True
    assert data["role"] == "admin"
    assert data["is_email_verified"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — ADMIN_EMAIL + verified → require_admin = 200
# ═══════════════════════════════════════════════════════════════════════════════

async def test_admin_email_verified_allowed_by_require_admin(client, fake_db, monkeypatch):
    """After email verification, require_admin allows the ADMIN_EMAIL user."""
    monkeypatch.setenv("ADMIN_EMAILS", _ADMIN_EMAIL)

    token = await _register(client, _ADMIN_EMAIL)
    await _verify_email_in_db(fake_db, _ADMIN_EMAIL)

    res = await client.get("/admin-only", headers=_bearer(token))
    assert res.status_code == 200
    assert res.json()["is_admin"] is True


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — Normal email verified → USER
# ═══════════════════════════════════════════════════════════════════════════════

async def test_normal_email_verified_stays_user(client, fake_db, monkeypatch):
    """A normal (non-admin) email remains USER even after email verification."""
    monkeypatch.setenv("ADMIN_EMAILS", _ADMIN_EMAIL)

    token = await _register(client, _USER_EMAIL)
    await _verify_email_in_db(fake_db, _USER_EMAIL)

    res = await client.get("/protected", headers=_bearer(token))
    assert res.status_code == 200
    data = res.json()
    assert data["is_admin"] is False
    assert data["role"] == "user"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — Normal email unverified → USER
# ═══════════════════════════════════════════════════════════════════════════════

async def test_normal_email_unverified_is_user(client, monkeypatch):
    """A freshly registered normal user with unverified email is USER."""
    monkeypatch.setenv("ADMIN_EMAILS", _ADMIN_EMAIL)

    token = await _register(client, _USER_EMAIL)
    res = await client.get("/protected", headers=_bearer(token))
    assert res.status_code == 200
    data = res.json()
    assert data["is_admin"] is False
    assert data["role"] == "user"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7 — register always persists role="user"
# ═══════════════════════════════════════════════════════════════════════════════

async def test_register_always_stores_role_user(client, fake_db, monkeypatch):
    """Registration must never write role=admin to the DB regardless of email."""
    monkeypatch.setenv("ADMIN_EMAILS", _ADMIN_EMAIL)

    for email in (_ADMIN_EMAIL, _USER_EMAIL):
        await client.post("/auth/register", json={"email": email, "password": _PASSWORD})
        stored = await fake_db.users.find_one({"email": email})
        assert stored is not None
        assert stored.get("role") == "user", (
            f"register must store role='user'; got {stored.get('role')!r} for {email}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Test 8 — Unauthenticated → 401
# ═══════════════════════════════════════════════════════════════════════════════

async def test_unauthenticated_request_rejected(client):
    """Requests without a token are rejected with 401."""
    assert (await client.get("/protected")).status_code == 401
    assert (await client.get("/admin-only")).status_code in (401, 403)


# ═══════════════════════════════════════════════════════════════════════════════
# Test 9 — Client cannot self-grant admin via register
# ═══════════════════════════════════════════════════════════════════════════════

async def test_client_cannot_self_grant_admin(client, fake_db, monkeypatch):
    """Extra fields in the register body are ignored; no admin privilege obtained."""
    monkeypatch.setenv("ADMIN_EMAILS", _ADMIN_EMAIL)

    res = await client.post(
        "/auth/register",
        json={
            "email": _ADMIN_EMAIL,
            "password": _PASSWORD,
            "role": "admin",
            "is_admin": True,
            "is_email_verified": True,
        },
    )
    assert res.status_code == 201

    # Check DB: is_email_verified must still be False (client cannot set it)
    stored = await fake_db.users.find_one({"email": _ADMIN_EMAIL})
    assert stored["is_email_verified"] is False
    assert stored["role"] == "user"

    # JWT from register must not grant admin
    token = res.json()["access_token"]
    prot = await client.get("/protected", headers=_bearer(token))
    assert prot.json()["is_admin"] is False
    assert (await client.get("/admin-only", headers=_bearer(token))).status_code == 403


# ═══════════════════════════════════════════════════════════════════════════════
# Test 10 — Explicit DB role="admin" (legitimate pre-provisioned admin) works
# ═══════════════════════════════════════════════════════════════════════════════

async def test_explicit_db_role_admin_still_works(app, fake_db, monkeypatch):
    """An account pre-provisioned in the DB with role=admin is still recognised
    as admin, regardless of is_email_verified.  This preserves the existing
    policy for server-side admin accounts that are not created via /register.
    """
    monkeypatch.setenv("ADMIN_EMAILS", "")

    now = datetime.now(timezone.utc)
    admin_id = "pre-provisioned-admin-id"
    await fake_db.users.insert_one({
        "id": admin_id,
        "email": "provisioned@internal.io",
        "role": "admin",
        "password_hash": None,
        "is_email_verified": False,   # even unverified, DB role wins
        "is_active": True,
        "auth_providers": [],
        "created_at": now,
        "updated_at": now,
        "last_login_at": now,
    })

    token = create_access_token(admin_id, "provisioned@internal.io")
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        res = await c.get("/protected", headers=_bearer(token))
        assert res.status_code == 200
        data = res.json()
        assert data["is_admin"] is True
        assert data["role"] == "admin"
