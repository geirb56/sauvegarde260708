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
   18.  Subscription — new Google user starts as FREE (with Paddle fields)
   19.  Subscription — new Apple user starts as FREE (with Paddle fields)
   20.  Linkage — verified OAuth email reuses existing email/password account
   21.  Linkage — unverified OAuth email does not auto-link existing account
   22.  Apple — frontend-supplied fallback email is ignored for account linking
   23.  Concurrency — loser of identity-claim race returns canonical user, no orphan
   24.  Concurrency — self-healing when user missing after identity claimed
   25.  Concurrency — idempotent sequential calls return same user
   26.  Linkage-D — Apple repeat-login (no email) resolved via (provider, sub) only
   27.  Linkage-E — Google + Apple same email link to same existing password user
   28.  Garmin Trial — existing Garmin trial not reset by OAuth login
   29.  Garmin Trial — Premium status not changed by OAuth login
   30.  JWT Security — JWT sub claim equals RunIndex user_id (not provider sub)
   31.  JWT Security — no provider token in response
   32.  JWT Security — frontend-supplied email not used for identity
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
from pymongo.errors import DuplicateKeyError as MongoDuplicateKeyError

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
                if "$addToSet" in update:
                    for k, v in update["$addToSet"].items():
                        lst = doc.setdefault(k, [])
                        if v not in lst:
                            lst.append(v)
                break

    async def create_index(self, *args, **kwargs):
        pass


class _FakeUniqueCollection(_FakeCollection):
    """Fake collection that enforces a unique constraint on a tuple of fields.

    Raises ``MongoDuplicateKeyError`` (the real pymongo class) when a document
    with the same values for ``unique_keys`` already exists, mirroring the
    behaviour of MongoDB's unique index.
    """

    def __init__(self, unique_keys: list):
        super().__init__()
        self._unique_keys = unique_keys  # e.g. ["provider", "provider_subject"]

    async def insert_one(self, doc):
        query = {k: doc[k] for k in self._unique_keys if k in doc}
        if query and any(self._match(d, query) for d in self._docs):
            raise MongoDuplicateKeyError(
                f"E11000 duplicate key error — unique constraint on {self._unique_keys}"
            )
        await super().insert_one(doc)


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


class TestOAuthAccountLinking:
    async def test_google_verified_email_reuses_existing_email_password_user(
        self, client, fake_db
    ):
        register = await client.post(
            "/auth/register",
            json={"email": "link-google@example.com", "password": "Password1!"},
        )
        assert register.status_code == 201
        existing_user_id = register.json()["user"]["id"]

        claims = _make_google_claims("google-sub-link-1", "link-google@example.com", True)
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/google", json={"id_token": "tok"})

        assert resp.status_code == 200
        assert resp.json()["user"]["id"] == existing_user_id
        identities = [
            d for d in fake_db.auth_identities._docs
            if d["provider"] == "google" and d["provider_subject"] == "google-sub-link-1"
        ]
        assert len(identities) == 1
        assert identities[0]["user_id"] == existing_user_id

    async def test_apple_verified_email_reuses_existing_email_password_user(
        self, client, fake_db
    ):
        register = await client.post(
            "/auth/register",
            json={"email": "link-apple@example.com", "password": "Password1!"},
        )
        assert register.status_code == 201
        existing_user_id = register.json()["user"]["id"]

        claims = _make_apple_claims("apple-sub-link-1", "link-apple@example.com", True)
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/apple", json={"id_token": "tok"})

        assert resp.status_code == 200
        assert resp.json()["user"]["id"] == existing_user_id
        identities = [
            d for d in fake_db.auth_identities._docs
            if d["provider"] == "apple" and d["provider_subject"] == "apple-sub-link-1"
        ]
        assert len(identities) == 1
        assert identities[0]["user_id"] == existing_user_id

    async def test_unverified_google_email_does_not_auto_link(self, client):
        register = await client.post(
            "/auth/register",
            json={"email": "no-link@example.com", "password": "Password1!"},
        )
        assert register.status_code == 201
        existing_user_id = register.json()["user"]["id"]

        claims = _make_google_claims("google-sub-no-link-1", "no-link@example.com", False)
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/google", json={"id_token": "tok"})

        assert resp.status_code == 200
        assert resp.json()["user"]["id"] != existing_user_id

    async def test_apple_frontend_email_is_ignored_when_token_has_no_email(self, client):
        claims = _make_apple_claims("apple-sub-no-token-email", email=None, email_verified=False)
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post(
                "/auth/apple",
                json={"id_token": "tok", "email": "spoofed@example.com"},
            )

        assert resp.status_code == 200
        assert resp.json()["user"]["email"] == "apple.apple-sub-no-token-email@oauth.runindex.internal"


# ═══════════════════════════════════════════════════════════════════════════════
# 18–19. Subscription — Paddle fields present, no price_locked, no trial
# ═══════════════════════════════════════════════════════════════════════════════

class TestSubscriptionPaddleAlignment:
    """Verify that the subscription created for new OAuth users matches the
    canonical model produced by subscription_manager.create_free_subscription().
    """

    async def test_google_new_user_subscription_has_paddle_fields(self, client, fake_db):
        claims = _make_google_claims("paddle-google-sub-1", "paddle-g@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/google", json={"id_token": "t"})
        user_id = resp.json()["user"]["id"]
        sub = await fake_db.subscriptions.find_one({"user_id": user_id})
        assert sub is not None
        assert sub["status"] == "free"
        assert sub["trial_used"] is False
        assert sub["trial_start"] is None
        assert sub["trial_end"] is None
        assert sub["garmin_identity"] is None
        # Paddle fields must be present (canonical model)
        assert "paddle_subscription_id" in sub
        assert sub["paddle_subscription_id"] is None
        assert "paddle_customer_id" in sub
        assert sub["paddle_customer_id"] is None
        # Legacy Stripe fields must be preserved for historical data
        assert "stripe_customer_id" in sub
        assert sub["stripe_customer_id"] is None

    async def test_apple_new_user_subscription_has_paddle_fields(self, client, fake_db):
        claims = _make_apple_claims("paddle-apple-sub-1", "paddle-a@icloud.com")
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/apple", json={"id_token": "t"})
        user_id = resp.json()["user"]["id"]
        sub = await fake_db.subscriptions.find_one({"user_id": user_id})
        assert sub is not None
        assert sub["status"] == "free"
        assert sub["trial_used"] is False
        assert sub["trial_start"] is None
        assert sub["trial_end"] is None
        assert sub["garmin_identity"] is None
        assert "paddle_subscription_id" in sub
        assert sub["paddle_subscription_id"] is None
        assert "paddle_customer_id" in sub
        assert sub["paddle_customer_id"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# 23–25. Concurrency / Idempotence
# ═══════════════════════════════════════════════════════════════════════════════

class TestConcurrencyIdempotence:
    """Tests for the identity-first race-condition prevention strategy.

    The key invariant: the unique index on auth_identities(provider, provider_subject)
    serialises concurrent signup requests.  Only the "winner" creates a user
    document and FREE subscription.  The "loser" returns the winner's user
    without leaving any orphaned documents behind.
    """

    async def test_winner_creates_exactly_one_user_and_subscription(self):
        """Happy-path: single call creates one user, one identity, one subscription."""
        db = _FakeDB()
        from auth.oauth_router import _find_or_create_oauth_user

        user = await _find_or_create_oauth_user(
            db, "google", "sub-winner-1", "winner@gmail.com", True
        )

        assert user["id"] is not None
        users = [d for d in db.users._docs if d.get("email") == "winner@gmail.com"]
        assert len(users) == 1
        subs = [d for d in db.subscriptions._docs if d["user_id"] == user["id"]]
        assert len(subs) == 1
        identities = [
            d for d in db.auth_identities._docs
            if d["provider"] == "google" and d["provider_subject"] == "sub-winner-1"
        ]
        assert len(identities) == 1

    async def test_loser_concurrent_claim_returns_canonical_user_no_orphan(self):
        """Loser of the concurrent identity-claim returns winner's user, no orphan created.

        Scenario:
        1. Winner claims identity and creates user + subscription.
        2. Loser: fast-path finds nothing (simulated), tries to insert identity →
           DuplicateKeyError → looks up canonical user → returns it.
        No orphan user or subscription is created by the loser.
        """
        from auth.oauth_router import _find_or_create_oauth_user

        now = datetime.now(timezone.utc)
        winner_id = str(uuid.uuid4())

        # Pre-populate the DB as the winner already left it.
        db = _FakeDB()
        await db.users.insert_one({
            "id": winner_id,
            "email": "concurrent@gmail.com",
            "password_hash": None,
            "is_active": True,
            "is_email_verified": True,
            "auth_providers": ["google"],
            "created_at": now,
            "updated_at": now,
            "last_login_at": now,
        })
        await db.subscriptions.insert_one({
            "user_id": winner_id,
            "status": "free",
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "trial_used": False,
            "trial_start": None,
            "trial_end": None,
            "garmin_identity": None,
            "paddle_subscription_id": None,
            "paddle_customer_id": None,
            "premium_expires_at": None,
            "stripe_customer_id": None,
            "stripe_subscription_id": None,
        })
        await db.auth_identities.insert_one({
            "user_id": winner_id,
            "provider": "google",
            "provider_subject": "sub-concurrent-1",
            "email": "concurrent@gmail.com",
            "created_at": now,
            "updated_at": now,
        })

        # Simulate the loser: identity is not visible during fast-path check,
        # then becomes visible after the DuplicateKeyError is raised.
        fast_path_calls = [0]
        original_find = db.auth_identities.find_one

        async def controlled_find(query, projection=None):
            fast_path_calls[0] += 1
            if fast_path_calls[0] == 1:
                # Fast-path: loser sees nothing yet (winner's write not yet committed
                # from loser's perspective).
                return None
            # Subsequent calls (after DuplicateKeyError): winner's data is visible.
            return await original_find(query, projection)

        db.auth_identities.find_one = controlled_find

        # Make insert_one raise DuplicateKeyError (winner already claimed it).
        async def raise_dup(doc):
            raise MongoDuplicateKeyError("E11000 duplicate key error")

        db.auth_identities.insert_one = raise_dup

        user = await _find_or_create_oauth_user(
            db, "google", "sub-concurrent-1", "concurrent@gmail.com", True
        )

        # Loser must return the winner's user.
        assert user["id"] == winner_id

        # No orphan user created by the loser.
        users = [d for d in db.users._docs]
        assert len(users) == 1

        # No orphan subscription created by the loser.
        subs = [d for d in db.subscriptions._docs]
        assert len(subs) == 1

    async def test_idempotent_sequential_calls_return_same_user(self):
        """Sequential calls for the same identity are idempotent (fast path)."""
        db = _FakeDB()
        from auth.oauth_router import _find_or_create_oauth_user

        u1 = await _find_or_create_oauth_user(
            db, "google", "sub-idempotent-1", "idem@gmail.com", True
        )
        u2 = await _find_or_create_oauth_user(
            db, "google", "sub-idempotent-1", "idem@gmail.com", True
        )

        assert u1["id"] == u2["id"]
        users = [d for d in db.users._docs if d.get("email") == "idem@gmail.com"]
        assert len(users) == 1
        subs = [d for d in db.subscriptions._docs if d["user_id"] == u1["id"]]
        assert len(subs) == 1

    async def test_self_healing_when_user_missing_after_identity_claimed(self):
        """Self-healing: identity exists but user document is missing (partial failure).

        This can happen if the process crashed between inserting the identity and
        creating the user document.  The next request must create the missing user
        and subscription using the identity's existing user_id.
        """
        from auth.oauth_router import _find_or_create_oauth_user

        now = datetime.now(timezone.utc)
        db = _FakeDB()
        orphan_id = str(uuid.uuid4())

        # Identity exists but no user or subscription (partial failure).
        await db.auth_identities.insert_one({
            "user_id": orphan_id,
            "provider": "apple",
            "provider_subject": "sub-healing-1",
            "email": "heal@icloud.com",
            "created_at": now,
            "updated_at": now,
        })

        user = await _find_or_create_oauth_user(
            db, "apple", "sub-healing-1", "heal@icloud.com", True
        )

        # Self-healed user must use the identity's existing user_id.
        assert user["id"] == orphan_id

        # User document must now exist.
        user_docs = [d for d in db.users._docs if d.get("id") == orphan_id]
        assert len(user_docs) == 1

        # Subscription must now exist.
        subs = [d for d in db.subscriptions._docs if d["user_id"] == orphan_id]
        assert len(subs) == 1

    async def test_unique_index_on_identities_prevents_duplicate_via_http(self, fake_db, app):
        """Two sequential HTTP requests for the same identity create only one user."""
        # Use a unique-constraint-aware collection so DuplicateKeyError is raised
        # on the second identity insert, exactly as MongoDB would.
        fake_db.auth_identities = _FakeUniqueCollection(["provider", "provider_subject"])

        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app), base_url="http://test"
        ) as c:
            claims = _make_google_claims("unique-idx-sub-1", "uniqueidx@gmail.com")
            with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
                r1 = await c.post("/auth/google", json={"id_token": "t1"})
                r2 = await c.post("/auth/google", json={"id_token": "t2"})

        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["user"]["id"] == r2.json()["user"]["id"]
        # Exactly one user and one subscription.
        users = [d for d in fake_db.users._docs if d.get("email") == "uniqueidx@gmail.com"]
        assert len(users) == 1
        subs = [d for d in fake_db.subscriptions._docs if d["user_id"] == users[0]["id"]]
        assert len(subs) == 1


# ═══════════════════════════════════════════════════════════════════════════════
# 26. Account Linkage-D — Apple repeat-login without email
# ═══════════════════════════════════════════════════════════════════════════════

class TestAccountLinkingExtended:
    """Extended account-linking tests (cases D and E from the spec)."""

    async def test_d_apple_repeat_login_no_email_resolved_via_sub(self, client):
        """D — Apple repeat login (no email) finds account via (provider, sub) only."""
        sub = "apple-sub-D-001"

        # First login: Apple provides email.
        claims_first = _make_apple_claims(sub, "apple-d@icloud.com", True)
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims_first)):
            r1 = await client.post("/auth/apple", json={"id_token": "t1"})
        assert r1.status_code == 200
        user_id_first = r1.json()["user"]["id"]

        # Second login: Apple omits email (typical repeat-login behaviour).
        claims_repeat = _make_apple_claims(sub, email=None, email_verified=False)
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims_repeat)):
            r2 = await client.post("/auth/apple", json={"id_token": "t2"})
        assert r2.status_code == 200
        assert r2.json()["user"]["id"] == user_id_first  # Same account

    async def test_e_google_and_apple_verified_same_email_link_to_same_user(
        self, client, fake_db
    ):
        """E — Google and Apple with the same verified email both link to the
        same existing password account; no duplicate user is created.
        """
        # Existing password-based account.
        register = await client.post(
            "/auth/register",
            json={"email": "shared@example.com", "password": "Password1!"},
        )
        assert register.status_code == 201
        password_user_id = register.json()["user"]["id"]

        # Google login with same verified email → links to password account.
        google_claims = _make_google_claims("google-sub-E-001", "shared@example.com", True)
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=google_claims)):
            rg = await client.post("/auth/google", json={"id_token": "tg"})
        assert rg.status_code == 200
        assert rg.json()["user"]["id"] == password_user_id

        # Apple login with same verified email → links to same password account.
        apple_claims = _make_apple_claims("apple-sub-E-001", "shared@example.com", True)
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=apple_claims)):
            ra = await client.post("/auth/apple", json={"id_token": "ta"})
        assert ra.status_code == 200
        assert ra.json()["user"]["id"] == password_user_id

        # Only one user exists for this email.
        users = [d for d in fake_db.users._docs if d.get("email") == "shared@example.com"]
        assert len(users) == 1

        # Only one subscription exists for this user.
        subs = [d for d in fake_db.subscriptions._docs if d["user_id"] == password_user_id]
        assert len(subs) == 1

    async def test_e_google_and_apple_unverified_different_users(self, client, fake_db):
        """E — Google and Apple with the same UNVERIFIED email create separate users
        (no cross-provider account takeover via unverified email).
        """
        google_claims = _make_google_claims("google-sub-E-unverified", "unverified@example.com", False)
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=google_claims)):
            rg = await client.post("/auth/google", json={"id_token": "tg"})
        assert rg.status_code == 200

        apple_claims = _make_apple_claims("apple-sub-E-unverified", "unverified@example.com", False)
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=apple_claims)):
            ra = await client.post("/auth/apple", json={"id_token": "ta"})
        assert ra.status_code == 200

        # Different users — unverified email must NOT link accounts.
        assert rg.json()["user"]["id"] != ra.json()["user"]["id"]


# ═══════════════════════════════════════════════════════════════════════════════
# 28–29. Garmin Trial — OAuth login must not reset or create a trial
# ═══════════════════════════════════════════════════════════════════════════════

class TestGarminTrialProtection:
    """OAuth login must never modify an existing Garmin trial or Premium status."""

    async def test_existing_garmin_trial_not_reset_by_google_login(self, client, fake_db):
        """An account with an active Garmin trial retains it after Google OAuth login."""
        # Create the user via Google OAuth.
        claims = _make_google_claims("google-trial-sub-1", "garmin-trial@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/google", json={"id_token": "t"})
        assert resp.status_code == 200
        user_id = resp.json()["user"]["id"]

        # Manually simulate that the user's Garmin trial is already active.
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        trial_end = (now + timedelta(days=20)).isoformat()
        trial_start = now.isoformat()
        await fake_db.subscriptions.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "status": "trial",
                    "trial_used": True,
                    "trial_start": trial_start,
                    "trial_end": trial_end,
                    "garmin_identity": "runner@garmin.com",
                }
            },
        )

        # Second Google OAuth login (same identity).
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp2 = await client.post("/auth/google", json={"id_token": "t2"})
        assert resp2.status_code == 200
        assert resp2.json()["user"]["id"] == user_id

        # Trial must be unchanged.
        sub = await fake_db.subscriptions.find_one({"user_id": user_id})
        assert sub["status"] == "trial"
        assert sub["trial_used"] is True
        assert sub["trial_start"] == trial_start
        assert sub["trial_end"] == trial_end
        assert sub["garmin_identity"] == "runner@garmin.com"

    async def test_existing_garmin_trial_not_reset_by_apple_login(self, client, fake_db):
        """An account with an active Garmin trial retains it after Apple OAuth login."""
        claims = _make_apple_claims("apple-trial-sub-1", "garmin-trial@icloud.com")
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/apple", json={"id_token": "t"})
        assert resp.status_code == 200
        user_id = resp.json()["user"]["id"]

        from datetime import timedelta
        now = datetime.now(timezone.utc)
        trial_end = (now + timedelta(days=15)).isoformat()
        await fake_db.subscriptions.update_one(
            {"user_id": user_id},
            {
                "$set": {
                    "status": "trial",
                    "trial_used": True,
                    "trial_start": now.isoformat(),
                    "trial_end": trial_end,
                    "garmin_identity": "apple-runner@garmin.com",
                }
            },
        )

        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp2 = await client.post("/auth/apple", json={"id_token": "t2"})
        assert resp2.status_code == 200
        assert resp2.json()["user"]["id"] == user_id

        sub = await fake_db.subscriptions.find_one({"user_id": user_id})
        assert sub["status"] == "trial"
        assert sub["trial_used"] is True
        assert sub["garmin_identity"] == "apple-runner@garmin.com"

    async def test_premium_status_not_changed_by_oauth_login(self, client, fake_db):
        """A Premium account retains its status after Google/Apple OAuth login."""
        claims = _make_google_claims("google-premium-sub-1", "premium@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/google", json={"id_token": "t"})
        assert resp.status_code == 200
        user_id = resp.json()["user"]["id"]

        # Manually set account to Premium.
        from datetime import timedelta
        now = datetime.now(timezone.utc)
        premium_exp = (now + timedelta(days=30)).isoformat()
        await fake_db.subscriptions.update_one(
            {"user_id": user_id},
            {"$set": {"status": "premium", "premium_expires_at": premium_exp}},
        )

        # Re-login via Google.
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp2 = await client.post("/auth/google", json={"id_token": "t2"})
        assert resp2.status_code == 200

        sub = await fake_db.subscriptions.find_one({"user_id": user_id})
        assert sub["status"] == "premium"
        assert sub["premium_expires_at"] == premium_exp

    async def test_new_google_signup_explicit_trial_fields(self, client, fake_db):
        """Google signup: explicit assertions on all trial-related subscription fields."""
        claims = _make_google_claims("google-explicit-trial-sub", "explicit-g@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/google", json={"id_token": "t"})
        assert resp.status_code == 200
        user_id = resp.json()["user"]["id"]
        sub = await fake_db.subscriptions.find_one({"user_id": user_id})
        assert sub["status"] == "free"
        assert sub["trial_used"] is False
        assert sub["trial_start"] is None
        assert sub["trial_end"] is None
        assert sub["garmin_identity"] is None

    async def test_new_apple_signup_explicit_trial_fields(self, client, fake_db):
        """Apple signup: explicit assertions on all trial-related subscription fields."""
        claims = _make_apple_claims("apple-explicit-trial-sub", "explicit-a@icloud.com")
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/apple", json={"id_token": "t"})
        assert resp.status_code == 200
        user_id = resp.json()["user"]["id"]
        sub = await fake_db.subscriptions.find_one({"user_id": user_id})
        assert sub["status"] == "free"
        assert sub["trial_used"] is False
        assert sub["trial_start"] is None
        assert sub["trial_end"] is None
        assert sub["garmin_identity"] is None


# ═══════════════════════════════════════════════════════════════════════════════
# 30–32. JWT Security
# ═══════════════════════════════════════════════════════════════════════════════

class TestJWTSecurity:
    """Verify that the issued JWT is a proper RunIndex JWT with no provider secrets."""

    async def test_google_jwt_sub_is_runindex_user_id_not_provider_sub(self, client):
        """JWT 'sub' must be the RunIndex user UUID, never the Google sub."""
        provider_sub = "google-jwt-sec-sub-1"
        claims = _make_google_claims(provider_sub, "jwtsec-g@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/google", json={"id_token": "t"})
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        runindex_user_id = resp.json()["user"]["id"]

        # Decode without verification just to inspect claims.
        import jwt as pyjwt
        raw = pyjwt.decode(
            token,
            os.environ["JWT_SECRET_KEY"],
            algorithms=[os.environ.get("JWT_ALGORITHM", "HS256")],
        )
        assert raw["sub"] == runindex_user_id
        assert raw["sub"] != provider_sub

    async def test_apple_jwt_sub_is_runindex_user_id_not_provider_sub(self, client):
        """JWT 'sub' must be the RunIndex user UUID, never the Apple sub."""
        provider_sub = "apple-jwt-sec-sub-1"
        claims = _make_apple_claims(provider_sub, "jwtsec-a@icloud.com")
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/apple", json={"id_token": "t"})
        assert resp.status_code == 200
        token = resp.json()["access_token"]
        runindex_user_id = resp.json()["user"]["id"]

        import jwt as pyjwt
        raw = pyjwt.decode(
            token,
            os.environ["JWT_SECRET_KEY"],
            algorithms=[os.environ.get("JWT_ALGORITHM", "HS256")],
        )
        assert raw["sub"] == runindex_user_id
        assert raw["sub"] != provider_sub

    async def test_google_response_contains_no_provider_id_token(self, client):
        """The response body must not contain the provider id_token."""
        claims = _make_google_claims("google-jwt-sec-2", "notoken-g@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/google", json={"id_token": "secret-provider-token"})
        assert "secret-provider-token" not in resp.text
        # Access token is a RunIndex JWT, not the provider's token
        token = resp.json()["access_token"]
        assert token != "secret-provider-token"

    async def test_apple_response_contains_no_provider_id_token(self, client):
        """The response body must not contain the provider id_token."""
        claims = _make_apple_claims("apple-jwt-sec-2", "notoken-a@icloud.com")
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/apple", json={"id_token": "secret-apple-token"})
        assert "secret-apple-token" not in resp.text
        token = resp.json()["access_token"]
        assert token != "secret-apple-token"

    async def test_frontend_user_id_in_request_body_is_ignored(self, client):
        """Any user_id sent in the request body must be completely ignored.

        The GoogleAuthRequest model only accepts 'id_token'; extra fields are
        silently discarded by Pydantic (or rejected as 422 depending on config).
        The resulting user must be created by the backend, not by the frontend.
        """
        claims = _make_google_claims("google-frontend-id-sub", "frontendid@gmail.com")
        spoofed_id = "00000000-frontend-supplied-00000000"
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post(
                "/auth/google",
                json={"id_token": "t", "user_id": spoofed_id},
            )
        assert resp.status_code in (200, 422)
        if resp.status_code == 200:
            assert resp.json()["user"]["id"] != spoofed_id

    async def test_jwt_token_type_is_bearer(self, client):
        """The token_type in the response must be 'bearer'."""
        claims = _make_google_claims("google-tokentype-sub", "tokentype@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/google", json={"id_token": "t"})
        assert resp.status_code == 200
        assert resp.json()["token_type"] == "bearer"

