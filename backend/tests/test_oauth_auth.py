"""Tests for OAuth authentication (Google + Apple).

Covers:
    1.  Google — unknown identity → new user created (FREE subscription)
    2.  Google — known identity → same user returned
    3.  Apple  — unknown identity → new user created (FREE subscription)
    4.  Apple  — known identity → same user returned
    5.  Isolation — Google User A ≠ Google User B
    6.  Isolation — Apple User A ≠ Apple User B
    7.  Isolation — Google User ≠ Apple User (even with same sub value)
    8.  JWT    — POST /auth/google → JWT → /auth/me returns correct user
    9.  JWT    — POST /auth/apple  → JWT → /auth/me returns correct user
   10.  Security — invalid Google ID token → 401
   11.  Security — invalid Apple ID token  → 401
   12.  Security — GOOGLE_CLIENT_ID not set → 401 (misconfiguration)
   13.  Security — APPLE_CLIENT_ID not set  → 401 (misconfiguration)
   14.  Apple  — email absent from token (repeat login) → still authenticates via sub
   15.  Google — response never contains provider credentials
   16.  Apple  — response never contains provider credentials
   17.  Trial  — Google user retains same Garmin trial rules (FREE on new account)
   18.  Subscription — new Google user starts as FREE
   19.  Subscription — new Apple user starts as FREE
"""

from __future__ import annotations

import asyncio
import os
import sys
import uuid
from datetime import datetime, timezone
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, patch

import pytest
import pytest_asyncio
import httpx

# Allow importing from the backend root
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("JWT_SECRET_KEY", "test-secret-key-for-unit-tests-only-32chars!")
os.environ.setdefault("JWT_ALGORITHM", "HS256")
os.environ.setdefault("JWT_ACCESS_TOKEN_EXPIRE_MINUTES", "60")
os.environ.setdefault("ENVIRONMENT", "test")
os.environ.setdefault("MONGO_URL", "mongodb://localhost:27017")
os.environ.setdefault("DB_NAME", "test_db")
os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id.apps.googleusercontent.com")
os.environ.setdefault("APPLE_CLIENT_ID", "com.runindex.app")

pytestmark = pytest.mark.asyncio


# ─── In-memory MongoDB fake ────────────────────────────────────────────────────

class _FakeCollection:
    def __init__(self):
        self._docs: list = []

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
                    elif op == "$ne" and dv == val:
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
        self._docs.append(doc.copy())

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


class _FakeDB:
    def __init__(self):
        self.users = _FakeCollection()
        self.subscriptions = _FakeCollection()
        self.auth_identities = _FakeCollection()

    def __getattr__(self, name):
        return _FakeCollection()


# ─── Mock provider token verification ─────────────────────────────────────────

def _make_google_claims(sub: str, email: str, email_verified: bool = True) -> dict:
    return {
        "sub": sub,
        "email": email,
        "email_verified": email_verified,
        "name": "Test User",
        "picture": None,
    }


def _make_apple_claims(sub: str, email: str | None, email_verified: bool = True) -> dict:
    return {
        "sub": sub,
        "email": email,
        "email_verified": email_verified,
    }


# ─── App factory ──────────────────────────────────────────────────────────────

def _make_app(fake_db):
    from fastapi import FastAPI
    from auth.router import auth_router
    from auth.oauth_router import oauth_router

    app = FastAPI()
    app.include_router(auth_router)
    app.include_router(oauth_router)
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
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://test"
    ) as c:
        yield c


# ─── Helpers ──────────────────────────────────────────────────────────────────

def _auth(token: str) -> dict:
    return {"Authorization": "Bearer " + token}


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Google — unknown identity → new user created
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoogleNewUser:
    async def test_new_google_user_gets_jwt(self, client):
        claims = _make_google_claims("google-sub-001", "alice@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/google", json={"id_token": "fake-google-token"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "alice@gmail.com"
        assert "id" in data["user"]

    async def test_new_google_user_subscription_is_free(self, client, fake_db):
        claims = _make_google_claims("google-sub-002", "bob@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/google", json={"id_token": "fake-token"})
        assert resp.status_code == 200
        user_id = resp.json()["user"]["id"]
        sub = await fake_db.subscriptions.find_one({"user_id": user_id})
        assert sub is not None
        assert sub["status"] == "free"
        assert sub["trial_used"] is False
        assert sub["garmin_identity"] is None

    async def test_new_google_user_identity_recorded(self, client, fake_db):
        sub_value = "google-sub-003"
        claims = _make_google_claims(sub_value, "carol@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            await client.post("/auth/google", json={"id_token": "fake-token"})
        identity = await fake_db.auth_identities.find_one(
            {"provider": "google", "provider_subject": sub_value}
        )
        assert identity is not None
        assert identity["provider"] == "google"
        assert identity["provider_subject"] == sub_value

    async def test_response_does_not_contain_secrets(self, client):
        claims = _make_google_claims("google-sub-004", "dave@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/google", json={"id_token": "fake-token"})
        body = resp.text
        # The raw fake-token should never appear in the response
        assert "fake-token" not in body
        assert "password" not in body.lower()
        assert "secret" not in body.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 2. Google — known identity → same user returned
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoogleExistingUser:
    async def test_same_google_identity_returns_same_user(self, client):
        claims = _make_google_claims("google-sub-100", "eve@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            r1 = await client.post("/auth/google", json={"id_token": "t1"})
            r2 = await client.post("/auth/google", json={"id_token": "t2"})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["user"]["id"] == r2.json()["user"]["id"]

    async def test_same_google_identity_single_db_entry(self, client, fake_db):
        claims = _make_google_claims("google-sub-101", "frank@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            await client.post("/auth/google", json={"id_token": "t1"})
            await client.post("/auth/google", json={"id_token": "t2"})
        identities = [
            d for d in fake_db.auth_identities._docs
            if d["provider"] == "google" and d["provider_subject"] == "google-sub-101"
        ]
        assert len(identities) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 3. Apple — unknown identity → new user created
# ═══════════════════════════════════════════════════════════════════════════════

class TestAppleNewUser:
    async def test_new_apple_user_gets_jwt(self, client):
        claims = _make_apple_claims("apple-sub-001", "grace@icloud.com")
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/apple", json={"id_token": "fake-apple-token"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "id" in data["user"]

    async def test_new_apple_user_subscription_is_free(self, client, fake_db):
        claims = _make_apple_claims("apple-sub-002", "henry@icloud.com")
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/apple", json={"id_token": "fake-token"})
        user_id = resp.json()["user"]["id"]
        sub = await fake_db.subscriptions.find_one({"user_id": user_id})
        assert sub is not None
        assert sub["status"] == "free"
        assert sub["trial_used"] is False

    async def test_apple_email_absent_still_creates_user(self, client):
        """Apple repeat-login: email may be absent from the ID token."""
        claims = _make_apple_claims("apple-sub-003", email=None, email_verified=False)
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/apple", json={"id_token": "fake-token"})
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_response_does_not_contain_secrets(self, client):
        claims = _make_apple_claims("apple-sub-004", "ivan@icloud.com")
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/apple", json={"id_token": "fake-token"})
        body = resp.text
        assert "fake-token" not in body
        assert "password" not in body.lower()
        assert "secret" not in body.lower()


# ═══════════════════════════════════════════════════════════════════════════════
# 4. Apple — known identity → same user returned
# ═══════════════════════════════════════════════════════════════════════════════

class TestAppleExistingUser:
    async def test_same_apple_identity_returns_same_user(self, client):
        claims = _make_apple_claims("apple-sub-100", "judy@icloud.com")
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            r1 = await client.post("/auth/apple", json={"id_token": "t1"})
            r2 = await client.post("/auth/apple", json={"id_token": "t2"})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["user"]["id"] == r2.json()["user"]["id"]

    async def test_apple_email_absent_on_repeat_login(self, client):
        """Simulate Apple first login (with email) then repeat login (without)."""
        sub = "apple-sub-101"
        claims_first = _make_apple_claims(sub, "kate@icloud.com")
        claims_repeat = _make_apple_claims(sub, email=None, email_verified=False)

        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims_first)):
            r1 = await client.post("/auth/apple", json={"id_token": "t1"})

        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims_repeat)):
            r2 = await client.post("/auth/apple", json={"id_token": "t2"})

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["user"]["id"] == r2.json()["user"]["id"]


# ═══════════════════════════════════════════════════════════════════════════════
# 5–7. Isolation between users and providers
# ═══════════════════════════════════════════════════════════════════════════════

class TestIsolation:
    async def test_different_google_subs_are_different_users(self, client):
        claims_a = _make_google_claims("google-sub-A", "usera@gmail.com")
        claims_b = _make_google_claims("google-sub-B", "userb@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims_a)):
            ra = await client.post("/auth/google", json={"id_token": "ta"})
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims_b)):
            rb = await client.post("/auth/google", json={"id_token": "tb"})
        assert ra.json()["user"]["id"] != rb.json()["user"]["id"]

    async def test_different_apple_subs_are_different_users(self, client):
        claims_a = _make_apple_claims("apple-sub-A", "usera@icloud.com")
        claims_b = _make_apple_claims("apple-sub-B", "userb@icloud.com")
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims_a)):
            ra = await client.post("/auth/apple", json={"id_token": "ta"})
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims_b)):
            rb = await client.post("/auth/apple", json={"id_token": "tb"})
        assert ra.json()["user"]["id"] != rb.json()["user"]["id"]

    async def test_same_sub_different_providers_are_different_users(self, client):
        """A 'sub' value that happens to be the same for Google and Apple must
        never be treated as the same RunIndex user."""
        shared_sub = "identical-sub-value"
        google_claims = _make_google_claims(shared_sub, "same@gmail.com")
        apple_claims = _make_apple_claims(shared_sub, "same@icloud.com")

        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=google_claims)):
            rg = await client.post("/auth/google", json={"id_token": "tg"})
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=apple_claims)):
            ra = await client.post("/auth/apple", json={"id_token": "ta"})

        assert rg.status_code == 200
        assert ra.status_code == 200
        assert rg.json()["user"]["id"] != ra.json()["user"]["id"]


# ═══════════════════════════════════════════════════════════════════════════════
# 8–9. JWT — OAuth → /auth/me returns correct user
# ═══════════════════════════════════════════════════════════════════════════════

class TestJWTAfterOAuth:
    async def test_google_jwt_works_on_me_endpoint(self, client):
        claims = _make_google_claims("google-sub-jwt-1", "leo@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/google", json={"id_token": "t"})
        token = resp.json()["access_token"]
        user_id = resp.json()["user"]["id"]

        me = await client.get("/auth/me", headers=_auth(token))
        assert me.status_code == 200
        assert me.json()["id"] == user_id
        assert me.json()["email"] == "leo@gmail.com"

    async def test_apple_jwt_works_on_me_endpoint(self, client):
        claims = _make_apple_claims("apple-sub-jwt-1", "mia@icloud.com")
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/apple", json={"id_token": "t"})
        token = resp.json()["access_token"]
        user_id = resp.json()["user"]["id"]

        me = await client.get("/auth/me", headers=_auth(token))
        assert me.status_code == 200
        assert me.json()["id"] == user_id

    async def test_google_jwt_rejects_tampered_token(self, client):
        claims = _make_google_claims("google-sub-jwt-2", "nick@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            await client.post("/auth/google", json={"id_token": "t"})

        me = await client.get("/auth/me", headers=_auth("tampered.invalid.token"))
        assert me.status_code == 401

    async def test_no_token_returns_401(self, client):
        resp = await client.get("/auth/me")
        assert resp.status_code == 401


# ═══════════════════════════════════════════════════════════════════════════════
# 10–13. Security — invalid tokens / misconfiguration
# ═══════════════════════════════════════════════════════════════════════════════

class TestOAuthSecurity:
    async def test_invalid_google_token_returns_401(self, client):
        with patch(
            "auth.oauth_router.verify_google_id_token",
            new=AsyncMock(side_effect=ValueError("Invalid Google ID token")),
        ):
            resp = await client.post("/auth/google", json={"id_token": "bad-token"})
        assert resp.status_code == 401

    async def test_invalid_apple_token_returns_401(self, client):
        with patch(
            "auth.oauth_router.verify_apple_id_token",
            new=AsyncMock(side_effect=ValueError("Invalid Apple ID token")),
        ):
            resp = await client.post("/auth/apple", json={"id_token": "bad-token"})
        assert resp.status_code == 401

    async def test_google_expired_token_returns_401(self, client):
        with patch(
            "auth.oauth_router.verify_google_id_token",
            new=AsyncMock(side_effect=ValueError("Google ID token has expired.")),
        ):
            resp = await client.post("/auth/google", json={"id_token": "expired"})
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    async def test_google_wrong_audience_returns_401(self, client):
        with patch(
            "auth.oauth_router.verify_google_id_token",
            new=AsyncMock(side_effect=ValueError("Google ID token audience does not match")),
        ):
            resp = await client.post("/auth/google", json={"id_token": "wrong-aud"})
        assert resp.status_code == 401

    async def test_apple_wrong_issuer_returns_401(self, client):
        with patch(
            "auth.oauth_router.verify_apple_id_token",
            new=AsyncMock(side_effect=ValueError("Apple ID token issuer is not Apple.")),
        ):
            resp = await client.post("/auth/apple", json={"id_token": "wrong-iss"})
        assert resp.status_code == 401

    async def test_missing_google_client_id_returns_401(self, client):
        with patch(
            "auth.oauth_router.verify_google_id_token",
            new=AsyncMock(side_effect=ValueError("GOOGLE_CLIENT_ID is not configured")),
        ):
            resp = await client.post("/auth/google", json={"id_token": "t"})
        assert resp.status_code == 401

    async def test_missing_apple_client_id_returns_401(self, client):
        with patch(
            "auth.oauth_router.verify_apple_id_token",
            new=AsyncMock(side_effect=ValueError("APPLE_CLIENT_ID is not configured")),
        ):
            resp = await client.post("/auth/apple", json={"id_token": "t"})
        assert resp.status_code == 401

    async def test_empty_google_id_token_rejected(self, client):
        resp = await client.post("/auth/google", json={"id_token": ""})
        assert resp.status_code == 422  # Pydantic validation error

    async def test_empty_apple_id_token_rejected(self, client):
        resp = await client.post("/auth/apple", json={"id_token": ""})
        assert resp.status_code == 422

    async def test_missing_google_id_token_rejected(self, client):
        resp = await client.post("/auth/google", json={})
        assert resp.status_code == 422

    async def test_missing_apple_id_token_rejected(self, client):
        resp = await client.post("/auth/apple", json={})
        assert resp.status_code == 422


# ═══════════════════════════════════════════════════════════════════════════════
# 17–19. Subscription — new OAuth users start FREE, Garmin trial rules intact
# ═══════════════════════════════════════════════════════════════════════════════

class TestSubscriptionRules:
    async def test_new_google_user_is_free_no_trial(self, client, fake_db):
        claims = _make_google_claims("google-sub-trial-1", "oscar@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/google", json={"id_token": "t"})
        user_id = resp.json()["user"]["id"]
        sub = await fake_db.subscriptions.find_one({"user_id": user_id})
        assert sub["status"] == "free"
        assert sub["trial_used"] is False
        assert sub["garmin_identity"] is None
        assert sub["trial_start"] is None
        assert sub["trial_end"] is None

    async def test_new_apple_user_is_free_no_trial(self, client, fake_db):
        claims = _make_apple_claims("apple-sub-trial-1", "pam@icloud.com")
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/apple", json={"id_token": "t"})
        user_id = resp.json()["user"]["id"]
        sub = await fake_db.subscriptions.find_one({"user_id": user_id})
        assert sub["status"] == "free"
        assert sub["trial_used"] is False
        assert sub["garmin_identity"] is None

    async def test_google_user_and_email_user_have_independent_subscriptions(
        self, client, fake_db
    ):
        """Creating a Google account and an email account with different IDs
        must not share subscriptions."""
        g_claims = _make_google_claims("google-sub-indep", "quinn@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=g_claims)):
            rg = await client.post("/auth/google", json={"id_token": "tg"})

        # Register email/password user with a different email
        re = await client.post(
            "/auth/register", json={"email": "quinn_email@example.com", "password": "Password1!"}
        )

        assert rg.status_code == 200
        assert re.status_code == 201

        gid = rg.json()["user"]["id"]
        eid = re.json()["user"]["id"]
        assert gid != eid

        gsub = await fake_db.subscriptions.find_one({"user_id": gid})
        esub = await fake_db.subscriptions.find_one({"user_id": eid})
        assert gsub is not None
        assert esub is not None
        assert gsub["user_id"] != esub["user_id"]
