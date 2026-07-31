from __future__ import annotations

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from unittest.mock import patch

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa
from jwt.algorithms import RSAAlgorithm

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id.apps.googleusercontent.com")
os.environ.setdefault("APPLE_CLIENT_ID", "com.runindex.app")

from auth.oauth_utils import verify_apple_id_token, verify_google_id_token

pytestmark = pytest.mark.asyncio


def _generate_rsa_material(kid: str):
    private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    public_key = private_key.public_key()
    jwk = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk.update({"kid": kid, "alg": "RS256", "use": "sig"})
    return private_key, {"keys": [jwk]}


def _encode_rs256(private_key, kid: str, claims: dict) -> str:
    return jwt.encode(claims, private_key, algorithm="RS256", headers={"kid": kid})


class _FakeResponse:
    def __init__(self, payload):
        self._payload = payload

    def raise_for_status(self):
        return None

    def json(self):
        return self._payload


class _FakeAsyncClient:
    def __init__(self, payload, *args, **kwargs):
        self._payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url):
        return _FakeResponse(self._payload)


def _now_claims() -> tuple[datetime, datetime]:
    now = datetime.now(timezone.utc)
    return now, now + timedelta(minutes=5)


async def _with_google_jwks(jwks, coro):
    with patch("auth.oauth_utils.httpx.AsyncClient", side_effect=lambda *args, **kwargs: _FakeAsyncClient(jwks)):
        return await coro


async def _with_apple_jwks(jwks, coro):
    with patch("auth.oauth_utils.httpx.AsyncClient", side_effect=lambda *args, **kwargs: _FakeAsyncClient(jwks)):
        return await coro


async def test_google_rs256_valid_token_is_accepted():
    private_key, jwks = _generate_rsa_material("google-kid-1")
    now, exp = _now_claims()
    token = _encode_rs256(private_key, "google-kid-1", {
        "sub": "google-sub-crypto-1",
        "email": "crypto@gmail.com",
        "email_verified": True,
        "iss": "https://accounts.google.com",
        "aud": os.environ["GOOGLE_CLIENT_ID"],
        "iat": now,
        "exp": exp,
    })

    claims = await _with_google_jwks(jwks, verify_google_id_token(token))
    assert claims["sub"] == "google-sub-crypto-1"
    assert claims["email"] == "crypto@gmail.com"
    assert claims["email_verified"] is True


async def test_google_invalid_signature_is_rejected():
    trusted_key, jwks = _generate_rsa_material("google-kid-2")
    attacker_key, _ = _generate_rsa_material("google-kid-2")
    now, exp = _now_claims()
    token = _encode_rs256(attacker_key, "google-kid-2", {
        "sub": "google-sub-crypto-2",
        "email": "crypto@gmail.com",
        "email_verified": True,
        "iss": "https://accounts.google.com",
        "aud": os.environ["GOOGLE_CLIENT_ID"],
        "iat": now,
        "exp": exp,
    })

    del trusted_key
    with pytest.raises(ValueError, match="Invalid Google ID token"):
        await _with_google_jwks(jwks, verify_google_id_token(token))


async def test_google_expired_token_is_rejected():
    private_key, jwks = _generate_rsa_material("google-kid-3")
    now = datetime.now(timezone.utc)
    token = _encode_rs256(private_key, "google-kid-3", {
        "sub": "google-sub-crypto-3",
        "email": "crypto@gmail.com",
        "email_verified": True,
        "iss": "https://accounts.google.com",
        "aud": os.environ["GOOGLE_CLIENT_ID"],
        "iat": now - timedelta(minutes=10),
        "exp": now - timedelta(minutes=1),
    })

    with pytest.raises(ValueError, match="expired"):
        await _with_google_jwks(jwks, verify_google_id_token(token))


async def test_google_wrong_issuer_is_rejected():
    private_key, jwks = _generate_rsa_material("google-kid-4")
    now, exp = _now_claims()
    token = _encode_rs256(private_key, "google-kid-4", {
        "sub": "google-sub-crypto-4",
        "email": "crypto@gmail.com",
        "email_verified": True,
        "iss": "https://evil.example.com",
        "aud": os.environ["GOOGLE_CLIENT_ID"],
        "iat": now,
        "exp": exp,
    })

    with pytest.raises(ValueError, match="issuer"):
        await _with_google_jwks(jwks, verify_google_id_token(token))


async def test_google_wrong_audience_is_rejected():
    private_key, jwks = _generate_rsa_material("google-kid-5")
    now, exp = _now_claims()
    token = _encode_rs256(private_key, "google-kid-5", {
        "sub": "google-sub-crypto-5",
        "email": "crypto@gmail.com",
        "email_verified": True,
        "iss": "https://accounts.google.com",
        "aud": "wrong-audience",
        "iat": now,
        "exp": exp,
    })

    with pytest.raises(ValueError, match="audience"):
        await _with_google_jwks(jwks, verify_google_id_token(token))


async def test_google_wrong_kid_is_rejected():
    private_key, jwks = _generate_rsa_material("google-kid-6")
    now, exp = _now_claims()
    token = _encode_rs256(private_key, "missing-kid", {
        "sub": "google-sub-crypto-6",
        "email": "crypto@gmail.com",
        "email_verified": True,
        "iss": "https://accounts.google.com",
        "aud": os.environ["GOOGLE_CLIENT_ID"],
        "iat": now,
        "exp": exp,
    })

    with pytest.raises(ValueError, match="key ID"):
        await _with_google_jwks(jwks, verify_google_id_token(token))


async def test_google_hs256_is_rejected():
    now, exp = _now_claims()
    token = jwt.encode({
        "sub": "google-sub-crypto-7",
        "email": "crypto@gmail.com",
        "email_verified": True,
        "iss": "https://accounts.google.com",
        "aud": os.environ["GOOGLE_CLIENT_ID"],
        "iat": now,
        "exp": exp,
    }, "not-a-google-key", algorithm="HS256", headers={"kid": "google-kid-7"})

    with pytest.raises(ValueError, match="unsupported signing algorithm"):
        await _with_google_jwks({"keys": []}, verify_google_id_token(token))


async def test_google_missing_email_is_rejected():
    private_key, jwks = _generate_rsa_material("google-kid-8")
    now, exp = _now_claims()
    token = _encode_rs256(private_key, "google-kid-8", {
        "sub": "google-sub-crypto-8",
        "email_verified": True,
        "iss": "https://accounts.google.com",
        "aud": os.environ["GOOGLE_CLIENT_ID"],
        "iat": now,
        "exp": exp,
    })

    with pytest.raises(ValueError):
        await _with_google_jwks(jwks, verify_google_id_token(token))


async def test_apple_rs256_valid_token_is_accepted_without_email():
    private_key, jwks = _generate_rsa_material("apple-kid-1")
    now, exp = _now_claims()
    token = _encode_rs256(private_key, "apple-kid-1", {
        "sub": "apple-sub-crypto-1",
        "iss": "https://appleid.apple.com",
        "aud": os.environ["APPLE_CLIENT_ID"],
        "iat": now,
        "exp": exp,
    })

    claims = await _with_apple_jwks(jwks, verify_apple_id_token(token))
    assert claims["sub"] == "apple-sub-crypto-1"
    assert claims["email"] is None


async def test_apple_invalid_signature_is_rejected():
    trusted_key, jwks = _generate_rsa_material("apple-kid-2")
    attacker_key, _ = _generate_rsa_material("apple-kid-2")
    now, exp = _now_claims()
    token = _encode_rs256(attacker_key, "apple-kid-2", {
        "sub": "apple-sub-crypto-2",
        "iss": "https://appleid.apple.com",
        "aud": os.environ["APPLE_CLIENT_ID"],
        "iat": now,
        "exp": exp,
    })

    del trusted_key
    with pytest.raises(ValueError, match="Invalid Apple ID token"):
        await _with_apple_jwks(jwks, verify_apple_id_token(token))


async def test_apple_wrong_issuer_is_rejected():
    private_key, jwks = _generate_rsa_material("apple-kid-3")
    now, exp = _now_claims()
    token = _encode_rs256(private_key, "apple-kid-3", {
        "sub": "apple-sub-crypto-3",
        "iss": "https://evil.example.com",
        "aud": os.environ["APPLE_CLIENT_ID"],
        "iat": now,
        "exp": exp,
    })

    with pytest.raises(ValueError, match="issuer"):
        await _with_apple_jwks(jwks, verify_apple_id_token(token))
