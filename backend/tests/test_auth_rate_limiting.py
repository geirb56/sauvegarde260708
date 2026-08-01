"""
Tests for auth rate limiting (PR59 — Auth hardening).

Verifies that login, register, forgot-password and reset-password all enforce
the rate limit and return HTTP 429 after too many attempts.

The global ``_auth_limiter`` is monkey-patched per-test to use a very low
``max_attempts`` threshold so tests stay fast without needing real Redis.
Redis is not required: the limiter automatically falls back to the in-memory
implementation when ``REDIS_URL`` is absent.
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

pytestmark = pytest.mark.asyncio


# ── In-memory fake DB (same as in test_auth.py) ───────────────────────────────

from auth.mongo_errors import DuplicateKeyError


class _FakeCollection:
    def __init__(self, *, unique_fields=None):
        self._docs: list = []
        self._unique_fields = tuple(unique_fields or ())

    def _match(self, doc, query):
        for key, value in query.items():
            if key.startswith("$"):
                continue
            if isinstance(value, dict):
                for op, val in value.items():
                    dv = doc.get(key)
                    if op == "$gt" and not (dv is not None and dv > val):
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
                break

    async def create_index(self, *args, **kwargs):
        pass

    async def count_documents(self, query):
        return sum(1 for doc in self._docs if self._match(doc, query))


class _FakeDB:
    def __init__(self):
        self.users = _FakeCollection(unique_fields=("email", "id"))
        self.subscriptions = _FakeCollection(unique_fields=("user_id",))

    def __getattr__(self, name):
        return _FakeCollection()


# ── App factory ───────────────────────────────────────────────────────────────

def _make_app(fake_db):
    from fastapi import FastAPI
    from auth.router import auth_router

    app = FastAPI()
    app.include_router(auth_router)
    app.state.db = fake_db
    return app


# ── Fixtures ──────────────────────────────────────────────────────────────────

@pytest.fixture
def fake_db():
    return _FakeDB()


@pytest.fixture
def app(fake_db):
    return _make_app(fake_db)


@pytest_asyncio.fixture
async def client(app):
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


@pytest.fixture(autouse=True)
def patch_limiter_max(monkeypatch):
    """Reduce max_attempts to 3 for all tests in this module.

    The fallback _InMemoryAuthRateLimiter is used (no Redis needed).
    Restore original value after each test automatically via monkeypatch.
    """
    import auth.router as _router_mod

    monkeypatch.setattr(_router_mod._auth_limiter, "max_attempts", 3)
    monkeypatch.setattr(_router_mod._auth_limiter._fallback, "max_attempts", 3)
    # Reset in-memory fallback store to avoid state leakage between tests
    _router_mod._auth_limiter._fallback._store.clear()


# ── Helpers ───────────────────────────────────────────────────────────────────

async def _register(client, email="rl@example.com", pw="Password1!"):
    return await client.post("/auth/register", json={"email": email, "password": pw})


# ═══════════════════════════════════════════════════════════════════════════════
# Rate limit: login
# ═══════════════════════════════════════════════════════════════════════════════

async def test_login_rate_limited_after_max_attempts(client):
    """After max_attempts (3) login attempts, the next attempt returns 429."""
    # Use a non-existent email so the register call doesn't consume a slot.
    email = "rl-login@example.com"

    for _ in range(3):
        res = await client.post("/auth/login", json={"email": email, "password": "Wrong1!"})
        assert res.status_code == 401

    # 4th attempt — must be rate-limited
    res = await client.post("/auth/login", json={"email": email, "password": "Wrong1!"})
    assert res.status_code == 429
    assert "Retry-After" in res.headers


async def test_login_retry_after_header_present(client):
    """HTTP 429 response must carry a Retry-After header."""
    email = "rl-retryafter@example.com"
    for _ in range(4):
        res = await client.post("/auth/login", json={"email": email, "password": "Bad1!"})
    assert res.status_code == 429
    assert res.headers.get("Retry-After") == "60"


# ═══════════════════════════════════════════════════════════════════════════════
# Rate limit: register
# ═══════════════════════════════════════════════════════════════════════════════

async def test_register_rate_limited_after_max_attempts(client):
    """After max_attempts (3) register calls for the same email, next returns 429."""
    email = "rl-register@example.com"

    # First call succeeds
    res = await _register(client, email=email)
    assert res.status_code == 201

    # Subsequent calls with same email fail with 409 (duplicate) but still count
    for _ in range(2):
        res = await _register(client, email=email)
        assert res.status_code == 409

    # 4th call should be rate-limited
    res = await _register(client, email=email)
    assert res.status_code == 429


# ═══════════════════════════════════════════════════════════════════════════════
# Rate limit: forgot-password
# ═══════════════════════════════════════════════════════════════════════════════

async def test_forgot_password_rate_limited_after_max_attempts(client):
    """After max_attempts forgot-password calls, the next returns 429."""
    email = "rl-forgot@example.com"

    for _ in range(3):
        res = await client.post("/auth/forgot-password", json={"email": email})
        assert res.status_code == 200

    res = await client.post("/auth/forgot-password", json={"email": email})
    assert res.status_code == 429


# ═══════════════════════════════════════════════════════════════════════════════
# Rate limit: reset-password
# ═══════════════════════════════════════════════════════════════════════════════

async def test_reset_password_rate_limited_after_max_attempts(client):
    """After max_attempts reset-password calls, the next returns 429."""
    for _ in range(3):
        res = await client.post(
            "/auth/reset-password",
            json={"token": "invalid_token", "new_password": "NewPass1!"},
        )
        assert res.status_code == 400  # invalid token, not rate-limited yet

    res = await client.post(
        "/auth/reset-password",
        json={"token": "invalid_token", "new_password": "NewPass1!"},
    )
    assert res.status_code == 429


# ═══════════════════════════════════════════════════════════════════════════════
# Rate limit isolation: separate keys per email
# ═══════════════════════════════════════════════════════════════════════════════

async def test_rate_limit_keys_are_per_email(client):
    """Each email address has its own rate limit bucket."""
    # Exhaust limit for email A
    for _ in range(4):
        await client.post("/auth/login", json={"email": "rl-a@example.com", "password": "X1!"})

    # Email B should still be allowed
    await _register(client, email="rl-b@example.com")
    res = await client.post(
        "/auth/login",
        json={"email": "rl-b@example.com", "password": "Password1!"},
    )
    # Not 429 — different key
    assert res.status_code != 429


# ═══════════════════════════════════════════════════════════════════════════════
# IP spoofing: X-Forwarded-For must NOT bypass the rate limiter by default
# ═══════════════════════════════════════════════════════════════════════════════

async def test_spoofed_x_forwarded_for_does_not_bypass_rate_limit(client, monkeypatch):
    """A spoofed X-Forwarded-For header must not reset the rate-limit counter.

    With TRUSTED_PROXY_COUNT=0 (the default), the limiter uses the direct
    connection IP (always 'testclient' in ASGI tests).  Cycling through fake
    XFF values must not allow unlimited attempts.
    """
    import os as _os
    monkeypatch.setenv("TRUSTED_PROXY_COUNT", "0")

    email = "rl-xff@example.com"

    # 3 attempts with rotating spoofed IPs — should still exhaust the limit
    fake_ips = ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
    for fake_ip in fake_ips:
        res = await client.post(
            "/auth/login",
            json={"email": email, "password": "Bad1!"},
            headers={"X-Forwarded-For": fake_ip},
        )
        assert res.status_code == 401  # not yet limited

    # 4th attempt — still from the same real connection IP → must be 429
    res = await client.post(
        "/auth/login",
        json={"email": email, "password": "Bad1!"},
        headers={"X-Forwarded-For": "99.99.99.99"},
    )
    assert res.status_code == 429
