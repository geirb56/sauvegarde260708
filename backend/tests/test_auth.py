"""
Tests for the authentication system (Step 1).

Uses pytest with asyncio_mode=auto for async tests.
MongoDB is mocked via an in-memory fake implementation.

Covers the 19 required scenarios:
  1.  Register — success
  2.  Register — duplicate email
  3.  Register — invalid password
  4.  Login — success
  5.  Login — wrong password
  6.  Login — unknown user
  7.  JWT — valid token accepted by a protected route
  8.  JWT — invalid token rejected
  9.  JWT — expired token rejected
 10.  GET /api/auth/me — valid token
 11.  GET /api/auth/me — no token → 401
 12.  GET /api/auth/me — tampered token → 401
 13.  Reset password — full flow (request + apply)
 14.  Reset password — expired token rejected
 15.  Logout — valid token
 16.  Register — response never contains password_hash
 17.  Login — response never contains secrets
 18.  Two users get different UUIDs
 19.  Login failure does not reveal whether email is registered
"""

from __future__ import annotations

import asyncio
import hashlib
import os
import secrets as _secrets
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional

import pytest
import pytest_asyncio
import httpx

# Allow importing from the backend root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

# Provide required env vars before any module-level code reads them
os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")

import jwt

from auth.password import hash_password, verify_password
from auth.jwt_utils import create_access_token, decode_access_token
from auth.mongo_errors import DuplicateKeyError

pytestmark = pytest.mark.asyncio


# ─── In-memory MongoDB fake ────────────────────────────────────────────────────

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


# ─── App factory ──────────────────────────────────────────────────────────────

def _make_app(fake_db):
    from fastapi import FastAPI
    from auth.router import auth_router

    app = FastAPI()
    app.include_router(auth_router)  # auth_router already has prefix="/auth"
    app.state.db = fake_db
    return app


# ─── Fixtures ─────────────────────────────────────────────────────────────────

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


# ─── Helpers ──────────────────────────────────────────────────────────────────

async def _register(client, email="user@example.com", pw="Password1!"):
    return await client.post("/auth/register", json={"email": email, "password": pw})


def _auth(token):
    return {"Authorization": "Bearer " + token}


# ═══════════════════════════════════════════════════════════════════════════════
# Unit tests — password utilities
# ═══════════════════════════════════════════════════════════════════════════════

class TestPasswordUtils:
    def test_hash_is_not_plaintext(self):
        pw = "MySecret123!"
        assert hash_password(pw) != pw

    def test_verify_correct(self):
        pw = "Correct1Horse"
        assert verify_password(pw, hash_password(pw)) is True

    def test_verify_wrong(self):
        assert verify_password("wrong", hash_password("right1!")) is False

    def test_hashes_differ(self):
        pw = "SamePass1!"
        assert hash_password(pw) != hash_password(pw)


# ═══════════════════════════════════════════════════════════════════════════════
# Unit tests — JWT utilities
# ═══════════════════════════════════════════════════════════════════════════════

class TestJWTUtils:
    def test_round_trip(self):
        token = create_access_token("u123", "u@x.com")
        payload = decode_access_token(token)
        assert payload["sub"] == "u123"

    def test_expired_raises(self):
        secret = os.environ["JWT_SECRET_KEY"]
        algo = os.environ["JWT_ALGORITHM"]
        tok = jwt.encode({
            "sub": "u1", "email": "u@x.com",
            "iat": datetime.now(timezone.utc) - timedelta(hours=2),
            "exp": datetime.now(timezone.utc) - timedelta(hours=1),
        }, secret, algorithm=algo)
        with pytest.raises(jwt.ExpiredSignatureError):
            decode_access_token(tok)

    def test_tampered_raises(self):
        token = create_access_token("u1", "u@x.com")
        with pytest.raises(jwt.InvalidTokenError):
            decode_access_token(token[:-4] + "xxxx")

    def test_no_password_in_payload(self):
        token = create_access_token("uid", "u@x.com")
        raw = jwt.decode(token, options={"verify_signature": False}, algorithms=["HS256"])
        assert "password" not in raw
        assert "password_hash" not in raw


# ═══════════════════════════════════════════════════════════════════════════════
# Test 1 — Register success
# ═══════════════════════════════════════════════════════════════════════════════

async def test_register_success(client):
    res = await _register(client)
    assert res.status_code == 201
    data = res.json()
    assert "access_token" in data
    assert data["token_type"] == "bearer"
    assert data["user"]["email"] == "user@example.com"


async def test_register_creates_paddle_compatible_free_subscription(client, fake_db):
    res = await _register(client, email="subfields@example.com")
    assert res.status_code == 201
    user_id = res.json()["user"]["id"]

    subscription = await fake_db.subscriptions.find_one({"user_id": user_id})
    assert subscription is not None
    assert subscription["status"] == "free"
    assert subscription["trial_used"] is False
    assert subscription["garmin_identity"] is None
    assert "paddle_subscription_id" in subscription
    assert subscription["paddle_subscription_id"] is None
    assert "paddle_customer_id" in subscription
    assert subscription["paddle_customer_id"] is None
    assert "premium_expires_at" in subscription
    assert subscription["premium_expires_at"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# Test 2 — Register duplicate email
# ═══════════════════════════════════════════════════════════════════════════════

async def test_register_duplicate_email(client):
    await _register(client, email="dup@example.com")
    res2 = await _register(client, email="dup@example.com")
    assert res2.status_code == 409


async def test_concurrent_register_duplicate_email_returns_single_account(client, fake_db):
    responses = await asyncio.gather(*[
        _register(client, email="race-register@example.com")
        for _ in range(2)
    ])
    statuses = sorted(response.status_code for response in responses)
    assert statuses == [201, 409]
    assert await fake_db.users.count_documents({"email": "race-register@example.com"}) == 1
    user = await fake_db.users.find_one({"email": "race-register@example.com"})
    assert await fake_db.subscriptions.count_documents({"user_id": user["id"]}) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# Test 3 — Register invalid password
# ═══════════════════════════════════════════════════════════════════════════════

async def test_register_invalid_password(client):
    res = await client.post("/auth/register", json={"email": "x@x.com", "password": "abc"})
    assert res.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# Test 4 — Login success
# ═══════════════════════════════════════════════════════════════════════════════

async def test_login_success(client):
    await _register(client, email="login4@example.com")
    res = await client.post("/auth/login", json={"email": "login4@example.com", "password": "Password1!"})
    assert res.status_code == 200
    assert "access_token" in res.json()


# ═══════════════════════════════════════════════════════════════════════════════
# Test 5 — Login wrong password
# ═══════════════════════════════════════════════════════════════════════════════

async def test_login_wrong_password(client):
    await _register(client, email="wp5@example.com")
    res = await client.post("/auth/login", json={"email": "wp5@example.com", "password": "WrongPass9!"})
    assert res.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# Test 6 — Login unknown user
# ═══════════════════════════════════════════════════════════════════════════════

async def test_login_unknown_user(client):
    res = await client.post("/auth/login", json={"email": "nobody6@example.com", "password": "Password1!"})
    assert res.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# Test 7 — Valid JWT accepted
# ═══════════════════════════════════════════════════════════════════════════════

async def test_valid_jwt_accepted(client):
    reg = await _register(client, email="jwt7@example.com")
    token = reg.json()["access_token"]
    res = await client.get("/auth/me", headers=_auth(token))
    assert res.status_code == 200


# ═══════════════════════════════════════════════════════════════════════════════
# Test 8 — Invalid JWT rejected
# ═══════════════════════════════════════════════════════════════════════════════

async def test_invalid_jwt_rejected(client):
    res = await client.get("/auth/me", headers=_auth("not.a.valid.token"))
    assert res.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# Test 9 — Expired JWT rejected
# ═══════════════════════════════════════════════════════════════════════════════

async def test_expired_jwt_rejected(client):
    secret = os.environ["JWT_SECRET_KEY"]
    expired_tok = jwt.encode({
        "sub": "fake-user",
        "email": "e@e.com",
        "iat": datetime.now(timezone.utc) - timedelta(hours=2),
        "exp": datetime.now(timezone.utc) - timedelta(hours=1),
    }, secret, algorithm="HS256")
    res = await client.get("/auth/me", headers=_auth(expired_tok))
    assert res.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# Test 10 — /auth/me with valid token
# ═══════════════════════════════════════════════════════════════════════════════

async def test_me_valid_token(client):
    reg = await _register(client, email="me10@example.com")
    token = reg.json()["access_token"]
    res = await client.get("/auth/me", headers=_auth(token))
    assert res.status_code == 200
    data = res.json()
    assert data["email"] == "me10@example.com"
    assert "id" in data
    assert "is_email_verified" in data


# ═══════════════════════════════════════════════════════════════════════════════
# Test 11 — /auth/me no token → 401
# ═══════════════════════════════════════════════════════════════════════════════

async def test_me_no_token(client):
    res = await client.get("/auth/me")
    assert res.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# Test 12 — /auth/me tampered token → 401
# ═══════════════════════════════════════════════════════════════════════════════

async def test_me_tampered_token(client):
    bad = jwt.encode({
        "sub": "hacker",
        "email": "h@h.com",
        "iat": datetime.now(timezone.utc),
        "exp": datetime.now(timezone.utc) + timedelta(hours=1),
    }, "wrong-secret", algorithm="HS256")
    res = await client.get("/auth/me", headers=_auth(bad))
    assert res.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# Test 13 — Reset password full flow
# ═══════════════════════════════════════════════════════════════════════════════

async def test_reset_password_flow(client, fake_db):
    email = "reset13@example.com"
    await _register(client, email=email)

    # Trigger forgot-password
    res_fp = await client.post("/auth/forgot-password", json={"email": email})
    assert res_fp.status_code == 200

    # Find the user doc and inject a known raw token
    user_doc = None
    for doc in fake_db.users._docs:
        if doc.get("email") == email:
            user_doc = doc
            break
    assert user_doc is not None

    raw = _secrets.token_urlsafe(32)
    user_doc["reset_password_token_hash"] = hashlib.sha256(raw.encode()).hexdigest()
    user_doc["reset_password_expires_at"] = datetime.now(timezone.utc) + timedelta(hours=1)

    res_rp = await client.post(
        "/auth/reset-password",
        json={"token": raw, "new_password": "NewPassword2@"},
    )
    assert res_rp.status_code == 200
    assert "reset_password_token_hash" not in user_doc


# ═══════════════════════════════════════════════════════════════════════════════
# Test 14 — Expired reset token rejected
# ═══════════════════════════════════════════════════════════════════════════════

async def test_reset_password_expired_token(client, fake_db):
    email = "expired14@example.com"
    await _register(client, email=email)

    user_doc = next((d for d in fake_db.users._docs if d.get("email") == email), None)
    assert user_doc is not None

    raw = _secrets.token_urlsafe(32)
    user_doc["reset_password_token_hash"] = hashlib.sha256(raw.encode()).hexdigest()
    user_doc["reset_password_expires_at"] = datetime.now(timezone.utc) - timedelta(hours=1)

    res = await client.post(
        "/auth/reset-password",
        json={"token": raw, "new_password": "NewPassword3@"},
    )
    assert res.status_code == 400


# ═══════════════════════════════════════════════════════════════════════════════
# Test 15 — Logout
# ═══════════════════════════════════════════════════════════════════════════════

async def test_logout_valid_token(client):
    reg = await _register(client, email="logout15@example.com")
    token = reg.json()["access_token"]
    res = await client.post("/auth/logout", headers=_auth(token))
    assert res.status_code == 200
    assert "message" in res.json()


async def test_logout_no_token(client):
    res = await client.post("/auth/logout")
    assert res.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# Test 16 — No password_hash in register response
# ═══════════════════════════════════════════════════════════════════════════════

async def test_register_no_password_hash_in_response(client):
    res = await _register(client, email="nohash16@example.com")
    assert res.status_code == 201
    assert "password_hash" not in res.text
    assert "password_hash" not in str(res.json())


# ═══════════════════════════════════════════════════════════════════════════════
# Test 17 — No secrets in login response
# ═══════════════════════════════════════════════════════════════════════════════

async def test_login_no_secrets_in_response(client):
    await _register(client, email="sec17@example.com")
    res = await client.post("/auth/login", json={"email": "sec17@example.com", "password": "Password1!"})
    assert res.status_code == 200
    body = res.text
    assert "password_hash" not in body
    assert "reset_password_token" not in body
    assert "email_verification_token" not in body


# ═══════════════════════════════════════════════════════════════════════════════
# Test 18 — Two users get different UUIDs
# ═══════════════════════════════════════════════════════════════════════════════

async def test_two_users_different_ids(client):
    r1 = await _register(client, email="u1@multi.com")
    r2 = await _register(client, email="u2@multi.com")
    assert r1.status_code == 201
    assert r2.status_code == 201
    id1 = r1.json()["user"]["id"]
    id2 = r2.json()["user"]["id"]
    assert id1 != id2
    assert id1 != "default"
    assert id2 != "default"


# ═══════════════════════════════════════════════════════════════════════════════
# Test 19 — Non-disclosure: login error doesn't reveal if email exists
# ═══════════════════════════════════════════════════════════════════════════════

async def test_login_non_disclosure(client):
    await _register(client, email="known19@example.com")

    res_known = await client.post(
        "/auth/login", json={"email": "known19@example.com", "password": "WrongPass9!"}
    )
    res_unknown = await client.post(
        "/auth/login", json={"email": "notexist19@example.com", "password": "WrongPass9!"}
    )
    assert res_known.status_code == 401
    assert res_unknown.status_code == 401
    assert res_known.json()["detail"] == res_unknown.json()["detail"]
