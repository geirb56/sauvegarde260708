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
   20.  Linkage — verified OAuth email reuses existing email/password account
   21.  Linkage — unverified OAuth email does not auto-link existing account
   22.  Apple — frontend-supplied fallback email is ignored for account linking
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

from auth.mongo_errors import DuplicateKeyError

pytestmark = pytest.mark.asyncio


# ─── In-memory MongoDB fake ────────────────────────────────────────────────────

class _FakeCollection:
    def __init__(self, *, unique_fields=None, unique_compounds=None):
        self._docs: list = []
        self._unique_fields = tuple(unique_fields or ())
        self._unique_compounds = tuple(tuple(fields) for fields in (unique_compounds or ()))
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

    def _raise_if_duplicate(self, candidate, *, ignore_doc=None):
        for existing in self._docs:
            if ignore_doc is not None and existing is ignore_doc:
                continue
            for field in self._unique_fields:
                value = candidate.get(field)
                if value is not None and existing.get(field) == value:
                    raise DuplicateKeyError(f"Duplicate key for {field}")
            for fields in self._unique_compounds:
                values = tuple(candidate.get(field) for field in fields)
                if any(value is None for value in values):
                    continue
                if all(existing.get(field) == candidate.get(field) for field in fields):
                    raise DuplicateKeyError(f"Duplicate key for {fields}")

    async def find_one(self, query, projection=None):
        await asyncio.sleep(0)
        for doc in self._docs:
            if self._match(doc, query):
                return self._project(doc, projection)
        return None

    async def insert_one(self, doc):
        await asyncio.sleep(0)
        async with self._lock:
            candidate = doc.copy()
            self._raise_if_duplicate(candidate)
            self._docs.append(candidate)

    def _apply_update(self, doc, update):
        if "$set" in update:
            doc.update(update["$set"])
        if "$unset" in update:
            for k in update["$unset"]:
                doc.pop(k, None)
        if "$addToSet" in update:
            for key, value in update["$addToSet"].items():
                current = list(doc.get(key, []))
                if value not in current:
                    current.append(value)
                doc[key] = current

    async def update_one(self, query, update, upsert=False):
        await asyncio.sleep(0)
        async with self._lock:
            for doc in self._docs:
                if self._match(doc, query):
                    candidate = doc.copy()
                    self._apply_update(candidate, update)
                    self._raise_if_duplicate(candidate, ignore_doc=doc)
                    doc.clear()
                    doc.update(candidate)
                    return
            if upsert:
                candidate = dict(query)
                if "$setOnInsert" in update:
                    candidate.update(update["$setOnInsert"])
                self._apply_update(candidate, update)
                self._raise_if_duplicate(candidate)
                self._docs.append(candidate)

    async def delete_one(self, query):
        await asyncio.sleep(0)
        async with self._lock:
            for index, doc in enumerate(self._docs):
                if self._match(doc, query):
                    self._docs.pop(index)
                    return

    async def delete_many(self, query):
        await asyncio.sleep(0)
        async with self._lock:
            self._docs = [doc for doc in self._docs if not self._match(doc, query)]

    async def find_one_and_delete(self, query, projection=None):
        await asyncio.sleep(0)
        async with self._lock:
            for index, doc in enumerate(self._docs):
                if self._match(doc, query):
                    removed = self._docs.pop(index)
                    return self._project(removed, projection)
        return None

    async def count_documents(self, query):
        await asyncio.sleep(0)
        return sum(1 for doc in self._docs if self._match(doc, query))

    async def create_index(self, *args, **kwargs):
        pass


class _FakeDB:
    def __init__(self):
        self.users = _FakeCollection(unique_fields=("email", "id"))
        self.subscriptions = _FakeCollection(unique_fields=("user_id",))
        self.auth_identities = _FakeCollection(unique_compounds=(("provider", "provider_subject"),))
        self.oauth_states = _FakeCollection(unique_fields=("state",))

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


async def _post_google(client, payload: dict) -> httpx.Response:
    challenge = await client.post("/auth/oauth/challenge/google")
    assert challenge.status_code == 200
    body = dict(payload)
    body["state"] = challenge.json()["state"]
    return await client.post("/auth/google", json=body)


async def _post_apple(client, payload: dict) -> httpx.Response:
    challenge = await client.post("/auth/oauth/challenge/apple")
    assert challenge.status_code == 200
    body = dict(payload)
    body["state"] = challenge.json()["state"]
    return await client.post("/auth/apple", json=body)


# ═══════════════════════════════════════════════════════════════════════════════
# 1. Google — unknown identity → new user created
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoogleNewUser:
    async def test_new_google_user_gets_jwt(self, client):
        claims = _make_google_claims("google-sub-001", "alice@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await _post_google(client, {"id_token": "fake-google-token"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert data["token_type"] == "bearer"
        assert data["user"]["email"] == "alice@gmail.com"
        assert "id" in data["user"]

    async def test_new_google_user_subscription_is_free(self, client, fake_db):
        claims = _make_google_claims("google-sub-002", "bob@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await _post_google(client, {"id_token": "fake-token"})
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
            await _post_google(client, {"id_token": "fake-token"})
        identity = await fake_db.auth_identities.find_one(
            {"provider": "google", "provider_subject": sub_value}
        )
        assert identity is not None
        assert identity["provider"] == "google"
        assert identity["provider_subject"] == sub_value

    async def test_response_does_not_contain_secrets(self, client):
        claims = _make_google_claims("google-sub-004", "dave@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await _post_google(client, {"id_token": "fake-token"})
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
            r1 = await _post_google(client, {"id_token": "t1"})
            r2 = await _post_google(client, {"id_token": "t2"})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["user"]["id"] == r2.json()["user"]["id"]

    async def test_same_google_identity_single_db_entry(self, client, fake_db):
        claims = _make_google_claims("google-sub-101", "frank@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            await _post_google(client, {"id_token": "t1"})
            await _post_google(client, {"id_token": "t2"})
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
            resp = await _post_apple(client, {"id_token": "fake-apple-token"})
        assert resp.status_code == 200
        data = resp.json()
        assert "access_token" in data
        assert "id" in data["user"]

    async def test_new_apple_user_subscription_is_free(self, client, fake_db):
        claims = _make_apple_claims("apple-sub-002", "henry@icloud.com")
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await _post_apple(client, {"id_token": "fake-token"})
        user_id = resp.json()["user"]["id"]
        sub = await fake_db.subscriptions.find_one({"user_id": user_id})
        assert sub is not None
        assert sub["status"] == "free"
        assert sub["trial_used"] is False

    async def test_apple_email_absent_still_creates_user(self, client):
        """Apple repeat-login: email may be absent from the ID token."""
        claims = _make_apple_claims("apple-sub-003", email=None, email_verified=False)
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await _post_apple(client, {"id_token": "fake-token"})
        assert resp.status_code == 200
        assert "access_token" in resp.json()

    async def test_response_does_not_contain_secrets(self, client):
        claims = _make_apple_claims("apple-sub-004", "ivan@icloud.com")
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await _post_apple(client, {"id_token": "fake-token"})
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
            r1 = await _post_apple(client, {"id_token": "t1"})
            r2 = await _post_apple(client, {"id_token": "t2"})
        assert r1.status_code == 200
        assert r2.status_code == 200
        assert r1.json()["user"]["id"] == r2.json()["user"]["id"]

    async def test_apple_email_absent_on_repeat_login(self, client):
        """Simulate Apple first login (with email) then repeat login (without)."""
        sub = "apple-sub-101"
        claims_first = _make_apple_claims(sub, "kate@icloud.com")
        claims_repeat = _make_apple_claims(sub, email=None, email_verified=False)

        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims_first)):
            r1 = await _post_apple(client, {"id_token": "t1"})

        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims_repeat)):
            r2 = await _post_apple(client, {"id_token": "t2"})

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
            ra = await _post_google(client, {"id_token": "ta"})
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims_b)):
            rb = await _post_google(client, {"id_token": "tb"})
        assert ra.json()["user"]["id"] != rb.json()["user"]["id"]

    async def test_different_apple_subs_are_different_users(self, client):
        claims_a = _make_apple_claims("apple-sub-A", "usera@icloud.com")
        claims_b = _make_apple_claims("apple-sub-B", "userb@icloud.com")
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims_a)):
            ra = await _post_apple(client, {"id_token": "ta"})
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims_b)):
            rb = await _post_apple(client, {"id_token": "tb"})
        assert ra.json()["user"]["id"] != rb.json()["user"]["id"]

    async def test_same_sub_different_providers_are_different_users(self, client):
        """A 'sub' value that happens to be the same for Google and Apple must
        never be treated as the same RunIndex user."""
        shared_sub = "identical-sub-value"
        google_claims = _make_google_claims(shared_sub, "same@gmail.com")
        apple_claims = _make_apple_claims(shared_sub, "same@icloud.com")

        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=google_claims)):
            rg = await _post_google(client, {"id_token": "tg"})
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=apple_claims)):
            ra = await _post_apple(client, {"id_token": "ta"})

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
            resp = await _post_google(client, {"id_token": "t"})
        token = resp.json()["access_token"]
        user_id = resp.json()["user"]["id"]

        me = await client.get("/auth/me", headers=_auth(token))
        assert me.status_code == 200
        assert me.json()["id"] == user_id
        assert me.json()["email"] == "leo@gmail.com"

    async def test_apple_jwt_works_on_me_endpoint(self, client):
        claims = _make_apple_claims("apple-sub-jwt-1", "mia@icloud.com")
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await _post_apple(client, {"id_token": "t"})
        token = resp.json()["access_token"]
        user_id = resp.json()["user"]["id"]

        me = await client.get("/auth/me", headers=_auth(token))
        assert me.status_code == 200
        assert me.json()["id"] == user_id

    async def test_google_jwt_rejects_tampered_token(self, client):
        claims = _make_google_claims("google-sub-jwt-2", "nick@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            await _post_google(client, {"id_token": "t"})

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
            resp = await _post_google(client, {"id_token": "bad-token"})
        assert resp.status_code == 401

    async def test_invalid_apple_token_returns_401(self, client):
        with patch(
            "auth.oauth_router.verify_apple_id_token",
            new=AsyncMock(side_effect=ValueError("Invalid Apple ID token")),
        ):
            resp = await _post_apple(client, {"id_token": "bad-token"})
        assert resp.status_code == 401

    async def test_google_expired_token_returns_401(self, client):
        with patch(
            "auth.oauth_router.verify_google_id_token",
            new=AsyncMock(side_effect=ValueError("Google ID token has expired.")),
        ):
            resp = await _post_google(client, {"id_token": "expired"})
        assert resp.status_code == 401
        assert "expired" in resp.json()["detail"].lower()

    async def test_google_wrong_audience_returns_401(self, client):
        with patch(
            "auth.oauth_router.verify_google_id_token",
            new=AsyncMock(side_effect=ValueError("Google ID token audience does not match")),
        ):
            resp = await _post_google(client, {"id_token": "wrong-aud"})
        assert resp.status_code == 401

    async def test_apple_wrong_issuer_returns_401(self, client):
        with patch(
            "auth.oauth_router.verify_apple_id_token",
            new=AsyncMock(side_effect=ValueError("Apple ID token issuer is not Apple.")),
        ):
            resp = await _post_apple(client, {"id_token": "wrong-iss"})
        assert resp.status_code == 401

    async def test_missing_google_client_id_returns_401(self, client):
        with patch(
            "auth.oauth_router.verify_google_id_token",
            new=AsyncMock(side_effect=ValueError("GOOGLE_CLIENT_ID is not configured")),
        ):
            resp = await _post_google(client, {"id_token": "t"})
        assert resp.status_code == 401

    async def test_missing_apple_client_id_returns_401(self, client):
        with patch(
            "auth.oauth_router.verify_apple_id_token",
            new=AsyncMock(side_effect=ValueError("APPLE_CLIENT_ID is not configured")),
        ):
            resp = await _post_apple(client, {"id_token": "t"})
        assert resp.status_code == 401

    async def test_empty_google_id_token_rejected(self, client):
        challenge = await client.post("/auth/oauth/challenge/google")
        resp = await client.post("/auth/google", json={"id_token": "", "state": challenge.json()["state"]})
        assert resp.status_code == 422  # Pydantic validation error

    async def test_empty_apple_id_token_rejected(self, client):
        challenge = await client.post("/auth/oauth/challenge/apple")
        resp = await client.post("/auth/apple", json={"id_token": "", "state": challenge.json()["state"]})
        assert resp.status_code == 422

    async def test_missing_google_id_token_rejected(self, client):
        challenge = await client.post("/auth/oauth/challenge/google")
        resp = await client.post("/auth/google", json={"state": challenge.json()["state"]})
        assert resp.status_code == 422

    async def test_missing_apple_id_token_rejected(self, client):
        challenge = await client.post("/auth/oauth/challenge/apple")
        resp = await client.post("/auth/apple", json={"state": challenge.json()["state"]})
        assert resp.status_code == 422

    async def test_missing_google_state_rejected(self, client):
        resp = await client.post("/auth/google", json={"id_token": "t"})
        assert resp.status_code == 422

    async def test_invalid_oauth_state_rejected(self, client):
        claims = _make_google_claims("google-sub-state-1", "state@example.com", True)
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await client.post("/auth/google", json={"id_token": "tok", "state": "invalid-state"})
        assert resp.status_code == 401

    async def test_google_verifier_receives_expected_nonce(self, client):
        verifier = AsyncMock(return_value=_make_google_claims("google-sub-state-2", "state2@example.com", True))
        challenge = await client.post("/auth/oauth/challenge/google")
        assert challenge.status_code == 200
        with patch("auth.oauth_router.verify_google_id_token", new=verifier):
            resp = await client.post(
                "/auth/google",
                json={"id_token": "tok", "state": challenge.json()["state"]},
            )
        assert resp.status_code == 200
        assert verifier.await_args.kwargs["expected_nonce"] == challenge.json()["nonce"]


# ═══════════════════════════════════════════════════════════════════════════════
# 17–19. Subscription — new OAuth users start FREE, Garmin trial rules intact
# ═══════════════════════════════════════════════════════════════════════════════

class TestSubscriptionRules:
    async def test_new_google_user_is_free_no_trial(self, client, fake_db):
        claims = _make_google_claims("google-sub-trial-1", "oscar@gmail.com")
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await _post_google(client, {"id_token": "t"})
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
            resp = await _post_apple(client, {"id_token": "t"})
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
            rg = await _post_google(client, {"id_token": "tg"})

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
            resp = await _post_google(client, {"id_token": "tok"})

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
            resp = await _post_apple(client, {"id_token": "tok"})

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
            resp = await _post_google(client, {"id_token": "tok"})

        assert resp.status_code == 200
        assert resp.json()["user"]["id"] != existing_user_id

    async def test_apple_frontend_email_is_ignored_when_token_has_no_email(self, client):
        claims = _make_apple_claims("apple-sub-no-token-email", email=None, email_verified=False)
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await _post_apple(client, {"id_token": "tok", "email": "spoofed@example.com"})

        assert resp.status_code == 200
        assert resp.json()["user"]["email"] == "apple.apple-sub-no-token-email@oauth.runindex.internal"


class TestOAuthHardening:
    async def test_oauth_state_is_single_use(self, client):
        claims = _make_google_claims("google-sub-single-use", "single@example.com", True)
        challenge = await client.post("/auth/oauth/challenge/google")
        assert challenge.status_code == 200
        payload = {"id_token": "tok", "state": challenge.json()["state"]}

        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            first = await client.post("/auth/google", json=payload)
        assert first.status_code == 200

        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            second = await client.post("/auth/google", json=payload)
        assert second.status_code == 401

    async def test_concurrent_google_requests_create_single_user_identity_and_subscription(
        self, client, fake_db
    ):
        claims = _make_google_claims("google-sub-concurrent-1", "race@gmail.com", True)
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            responses = await asyncio.gather(*[
                _post_google(client, {"id_token": f"tok-{index}"})
                for index in range(10)
            ])

        assert all(response.status_code == 200 for response in responses)
        user_ids = {response.json()["user"]["id"] for response in responses}
        assert len(user_ids) == 1

        assert await fake_db.users.count_documents({}) == 1
        assert await fake_db.auth_identities.count_documents(
            {"provider": "google", "provider_subject": "google-sub-concurrent-1"}
        ) == 1
        assert await fake_db.subscriptions.count_documents(
            {"user_id": next(iter(user_ids))}
        ) == 1

    async def test_existing_apple_identity_without_email_does_not_erase_stored_email(
        self, client, fake_db
    ):
        now = datetime.now(timezone.utc)
        user_id = str(uuid.uuid4())
        fake_db.users._docs.append({
            "id": user_id,
            "email": "stored@icloud.com",
            "password_hash": None,
            "is_email_verified": True,
            "is_active": True,
            "auth_providers": ["apple"],
            "created_at": now,
            "updated_at": now,
            "last_login_at": now,
        })
        fake_db.subscriptions._docs.append({
            "user_id": user_id,
            "status": "free",
            "created_at": now.isoformat(),
            "trial_start": None,
            "trial_end": None,
            "trial_used": False,
            "garmin_identity": None,
            "updated_at": now.isoformat(),
        })
        fake_db.auth_identities._docs.append({
            "user_id": user_id,
            "provider": "apple",
            "provider_subject": "apple-sub-repeat-email",
            "email": "stored@icloud.com",
            "email_verified": True,
            "created_at": now,
            "updated_at": now,
        })

        claims = _make_apple_claims("apple-sub-repeat-email", email=None, email_verified=False)
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await _post_apple(client, {"id_token": "tok"})

        assert resp.status_code == 200
        identity = await fake_db.auth_identities.find_one(
            {"provider": "apple", "provider_subject": "apple-sub-repeat-email"}
        )
        assert identity["email"] == "stored@icloud.com"

    async def test_promotes_placeholder_email_when_verified_email_arrives(self, client, fake_db):
        now = datetime.now(timezone.utc)
        user_id = str(uuid.uuid4())
        fake_db.users._docs.append({
            "id": user_id,
            "email": "apple.apple-sub-promote@oauth.runindex.internal",
            "password_hash": None,
            "is_email_verified": False,
            "is_active": True,
            "auth_providers": ["apple"],
            "created_at": now,
            "updated_at": now,
            "last_login_at": now,
        })
        fake_db.subscriptions._docs.append({
            "user_id": user_id,
            "status": "free",
            "created_at": now.isoformat(),
            "trial_start": None,
            "trial_end": None,
            "trial_used": False,
            "garmin_identity": None,
            "paddle_subscription_id": None,
            "paddle_customer_id": None,
            "premium_expires_at": None,
            "updated_at": now.isoformat(),
        })
        fake_db.auth_identities._docs.append({
            "user_id": user_id,
            "provider": "apple",
            "provider_subject": "apple-sub-promote",
            "email": None,
            "email_verified": False,
            "created_at": now,
            "updated_at": now,
        })

        claims = _make_apple_claims("apple-sub-promote", "promoted@icloud.com", True)
        with patch("auth.oauth_router.verify_apple_id_token", new=AsyncMock(return_value=claims)):
            resp = await _post_apple(client, {"id_token": "tok"})

        assert resp.status_code == 200
        assert resp.json()["user"]["email"] == "promoted@icloud.com"
        user = await fake_db.users.find_one({"id": user_id})
        assert user["email"] == "promoted@icloud.com"
        assert user["is_email_verified"] is True

    async def test_missing_user_identity_returns_error_without_recreation(self, client, fake_db):
        now = datetime.now(timezone.utc)
        missing_user_id = str(uuid.uuid4())
        fake_db.auth_identities._docs.append({
            "user_id": missing_user_id,
            "provider": "google",
            "provider_subject": "google-sub-self-heal",
            "email": "heal@example.com",
            "email_verified": True,
            "created_at": now,
            "updated_at": now,
        })

        claims = _make_google_claims("google-sub-self-heal", "heal@example.com", True)
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await _post_google(client, {"id_token": "tok"})

        assert resp.status_code == 500
        user = await fake_db.users.find_one({"id": missing_user_id})
        subscription = await fake_db.subscriptions.find_one({"user_id": missing_user_id})
        assert user is None
        assert subscription is None

    async def test_missing_user_identity_with_other_email_owner_still_fails_closed(self, client, fake_db):
        now = datetime.now(timezone.utc)
        other_user_id = str(uuid.uuid4())
        fake_db.users._docs.append({
            "id": other_user_id,
            "email": "occupied@example.com",
            "password_hash": "hashed",
            "is_email_verified": False,
            "is_active": True,
            "auth_providers": ["password"],
            "created_at": now,
            "updated_at": now,
            "last_login_at": now,
        })
        fake_db.subscriptions._docs.append({
            "user_id": other_user_id,
            "status": "free",
            "created_at": now.isoformat(),
            "trial_start": None,
            "trial_end": None,
            "trial_used": False,
            "garmin_identity": None,
            "updated_at": now.isoformat(),
        })
        fake_db.auth_identities._docs.append({
            "user_id": str(uuid.uuid4()),
            "provider": "google",
            "provider_subject": "google-sub-collision",
            "email": "occupied@example.com",
            "email_verified": True,
            "created_at": now,
            "updated_at": now,
        })

        claims = _make_google_claims("google-sub-collision", "occupied@example.com", True)
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await _post_google(client, {"id_token": "tok"})

        assert resp.status_code == 500
        assert await fake_db.users.count_documents({}) == 1
        existing_user = await fake_db.users.find_one({"id": other_user_id})
        assert existing_user["auth_providers"] == ["password"]

    async def test_account_linking_conflict_does_not_partially_modify_existing_user(
        self, client, fake_db
    ):
        now = datetime.now(timezone.utc)
        email_user_id = str(uuid.uuid4())
        canonical_user_id = str(uuid.uuid4())
        fake_db.users._docs.extend([
            {
                "id": email_user_id,
                "email": "link-conflict@example.com",
                "password_hash": "hashed",
                "is_email_verified": False,
                "is_active": True,
                "auth_providers": ["password"],
                "created_at": now,
                "updated_at": now,
                "last_login_at": now,
            },
            {
                "id": canonical_user_id,
                "email": "canonical@example.com",
                "password_hash": None,
                "is_email_verified": True,
                "is_active": True,
                "auth_providers": ["google"],
                "created_at": now,
                "updated_at": now,
                "last_login_at": now,
            },
        ])
        fake_db.auth_identities._docs.append({
            "user_id": canonical_user_id,
            "provider": "google",
            "provider_subject": "google-sub-link-conflict",
            "email": "canonical@example.com",
            "email_verified": True,
            "created_at": now,
            "updated_at": now,
        })

        original_find_one = fake_db.auth_identities.find_one
        state = {"hidden": True}

        async def race_find_one(query, projection=None):
            if (
                state["hidden"]
                and query == {"provider": "google", "provider_subject": "google-sub-link-conflict"}
            ):
                state["hidden"] = False
                return None
            return await original_find_one(query, projection)

        fake_db.auth_identities.find_one = race_find_one

        claims = _make_google_claims("google-sub-link-conflict", "link-conflict@example.com", True)
        with patch("auth.oauth_router.verify_google_id_token", new=AsyncMock(return_value=claims)):
            resp = await _post_google(client, {"id_token": "tok"})

        assert resp.status_code == 409
        email_user = await fake_db.users.find_one({"id": email_user_id})
        assert email_user["auth_providers"] == ["password"]
        assert await fake_db.auth_identities.count_documents(
            {"provider": "google", "provider_subject": "google-sub-link-conflict"}
        ) == 1
