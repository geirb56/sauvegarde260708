"""Direct cryptographic tests for auth/oauth_utils.py.

These tests exercise ``verify_google_id_token`` and ``verify_apple_id_token``
at the crypto layer using real RSA key pairs and real JWT encoding/decoding.
They do NOT mock the verification functions themselves — only the HTTPS calls
that fetch provider public-key sets (JWKS) are mocked.

This demonstrates that the backend cannot be tricked by:
  - Expired tokens
  - Tokens signed with the wrong key
  - Tokens with the wrong audience
  - Tokens with the wrong issuer
  - Tokens using a symmetric algorithm (HS256)
  - Tokens with an unknown kid
  - Missing required claims

Coverage:
  Google:
    G1  Valid RS256 token → success
    G2  Signature invalid (different private key) → ValueError
    G3  Token expired → ValueError("expired")
    G4  Wrong audience → ValueError("audience")
    G5  Wrong issuer → ValueError("issuer")
    G6  Unknown kid in header → ValueError("kid")
    G7  Algorithm HS256 → ValueError("algorithm")
    G8  Email claim absent → ValueError("email")
    G9  email_verified as string "true"/"false" → normalised to bool

  Apple:
    A1  Valid RS256 token → success
    A2  Signature invalid → ValueError
    A3  Token expired → ValueError("expired")
    A4  Wrong audience → ValueError("audience")
    A5  Wrong issuer → ValueError("issuer")
    A6  Unknown kid → ValueError("kid")
    A7  Algorithm HS256 → ValueError("algorithm")
    A8  Email absent → accepted (None returned)
    A9  email_verified as string "true"/"false" → normalised to bool
"""

from __future__ import annotations

import json
import os
import sys
import time
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

# Allow importing from the backend root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("GOOGLE_CLIENT_ID", "test-google-client-id.apps.googleusercontent.com")
os.environ.setdefault("APPLE_CLIENT_ID", "com.runindex.app")

pytestmark = pytest.mark.asyncio

# ── RSA key-pair fixtures ──────────────────────────────────────────────────────

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa
from cryptography.hazmat.backends import default_backend
from jwt.algorithms import RSAAlgorithm
import jwt as pyjwt


def _make_rsa_pair(kid: str = "test-kid-1"):
    """Generate an RSA-2048 key pair and a matching JWKS entry."""
    private_key = rsa.generate_private_key(
        public_exponent=65537,
        key_size=2048,
        backend=default_backend(),
    )
    public_key = private_key.public_key()

    # Serialise public key to JWK format.
    public_pem = public_key.public_bytes(
        serialization.Encoding.PEM,
        serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    jwk_dict = json.loads(RSAAlgorithm.to_jwk(public_key))
    jwk_dict["kid"] = kid
    jwk_dict["alg"] = "RS256"
    jwk_dict["use"] = "sig"

    return private_key, public_key, jwk_dict


# Primary key pair (correctly configured provider).
_PRIV_KEY, _PUB_KEY, _JWK = _make_rsa_pair("test-kid-1")
# Secondary key pair (wrong key — for invalid-signature tests).
_OTHER_PRIV_KEY, _OTHER_PUB_KEY, _OTHER_JWK = _make_rsa_pair("test-kid-other")

_GOOGLE_JWKS = {"keys": [_JWK]}
_APPLE_JWKS = {"keys": [_JWK]}

# ── JWT builders ───────────────────────────────────────────────────────────────

_GOOGLE_CLIENT_ID = os.environ["GOOGLE_CLIENT_ID"]
_APPLE_CLIENT_ID = os.environ["APPLE_CLIENT_ID"]
_NOW = int(time.time())


def _google_token(
    *,
    sub: str = "google-crypto-sub-1",
    email: str | None = "crypto@gmail.com",
    email_verified: bool | str = True,
    aud: str = _GOOGLE_CLIENT_ID,
    iss: str = "https://accounts.google.com",
    exp: int = _NOW + 3600,
    iat: int = _NOW,
    kid: str = "test-kid-1",
    alg: str = "RS256",
    signing_key=None,
) -> str:
    """Build a Google-style ID token."""
    payload: dict = {
        "sub": sub,
        "iss": iss,
        "aud": aud,
        "exp": exp,
        "iat": iat,
    }
    if email is not None:
        payload["email"] = email
    if email_verified is not None:
        payload["email_verified"] = email_verified

    if alg == "HS256":
        # HS256 token: sign with a symmetric secret.
        return pyjwt.encode(
            payload,
            "some-hmac-secret",
            algorithm="HS256",
            headers={"kid": kid},
        )

    key = signing_key if signing_key is not None else _PRIV_KEY
    return pyjwt.encode(
        payload,
        key,
        algorithm="RS256",
        headers={"kid": kid},
    )


def _apple_token(
    *,
    sub: str = "apple-crypto-sub-1",
    email: str | None = "crypto@icloud.com",
    email_verified: bool | str = True,
    aud: str = _APPLE_CLIENT_ID,
    iss: str = "https://appleid.apple.com",
    exp: int = _NOW + 3600,
    iat: int = _NOW,
    kid: str = "test-kid-1",
    alg: str = "RS256",
    signing_key=None,
) -> str:
    """Build an Apple-style ID token."""
    payload: dict = {
        "sub": sub,
        "iss": iss,
        "aud": aud,
        "exp": exp,
        "iat": iat,
    }
    if email is not None:
        payload["email"] = email
    if email_verified is not None:
        payload["email_verified"] = email_verified

    if alg == "HS256":
        return pyjwt.encode(
            payload,
            "some-hmac-secret",
            algorithm="HS256",
            headers={"kid": kid},
        )

    key = signing_key if signing_key is not None else _PRIV_KEY
    return pyjwt.encode(
        payload,
        key,
        algorithm="RS256",
        headers={"kid": kid},
    )


# ── JWKS mock helper ───────────────────────────────────────────────────────────

def _mock_http_get(jwks: dict):
    """Return a context-manager patch that makes httpx.AsyncClient.get return
    a fake JWKS response.
    """
    mock_response = MagicMock()
    mock_response.raise_for_status = MagicMock()
    mock_response.json = MagicMock(return_value=jwks)

    mock_client = AsyncMock()
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=False)
    mock_client.get = AsyncMock(return_value=mock_response)

    return patch("auth.oauth_utils.httpx.AsyncClient", return_value=mock_client)


# ═══════════════════════════════════════════════════════════════════════════════
# Google tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestGoogleCrypto:
    """G1–G9: Direct cryptographic tests for verify_google_id_token()."""

    async def test_g1_valid_rs256_token(self):
        """G1 — A correctly signed RS256 Google token is accepted."""
        from auth.oauth_utils import verify_google_id_token

        token = _google_token()
        with _mock_http_get(_GOOGLE_JWKS):
            claims = await verify_google_id_token(token)

        assert claims["sub"] == "google-crypto-sub-1"
        assert claims["email"] == "crypto@gmail.com"
        assert claims["email_verified"] is True

    async def test_g2_invalid_signature(self):
        """G2 — Token signed with the wrong private key is rejected."""
        from auth.oauth_utils import verify_google_id_token

        # Signed with a different key whose public key is NOT in the JWKS.
        token = _google_token(signing_key=_OTHER_PRIV_KEY)
        with _mock_http_get(_GOOGLE_JWKS):  # JWKS only has _JWK, not _OTHER_JWK
            with pytest.raises(ValueError, match="(?i)(invalid|signature|key)"):
                await verify_google_id_token(token)

    async def test_g3_expired_token(self):
        """G3 — An expired token is rejected."""
        from auth.oauth_utils import verify_google_id_token

        token = _google_token(exp=_NOW - 3600, iat=_NOW - 7200)
        with _mock_http_get(_GOOGLE_JWKS):
            with pytest.raises(ValueError, match="(?i)expired"):
                await verify_google_id_token(token)

    async def test_g4_wrong_audience(self):
        """G4 — A token with the wrong audience (aud) is rejected."""
        from auth.oauth_utils import verify_google_id_token

        token = _google_token(aud="wrong-client-id.apps.googleusercontent.com")
        with _mock_http_get(_GOOGLE_JWKS):
            with pytest.raises(ValueError, match="(?i)audience"):
                await verify_google_id_token(token)

    async def test_g5_wrong_issuer(self):
        """G5 — A token with an unexpected issuer is rejected."""
        from auth.oauth_utils import verify_google_id_token

        token = _google_token(iss="https://evil.com")
        with _mock_http_get(_GOOGLE_JWKS):
            with pytest.raises(ValueError, match="(?i)issuer"):
                await verify_google_id_token(token)

    async def test_g5b_accounts_google_com_issuer_accepted(self):
        """G5b — Both Google issuer variants are accepted."""
        from auth.oauth_utils import verify_google_id_token

        for iss in ("accounts.google.com", "https://accounts.google.com"):
            token = _google_token(iss=iss)
            with _mock_http_get(_GOOGLE_JWKS):
                claims = await verify_google_id_token(token)
            assert claims["sub"] == "google-crypto-sub-1"

    async def test_g6_unknown_kid(self):
        """G6 — A token with a kid not present in the JWKS is rejected."""
        from auth.oauth_utils import verify_google_id_token

        token = _google_token(kid="unknown-kid-xyz")
        with _mock_http_get(_GOOGLE_JWKS):  # JWKS has kid="test-kid-1" only
            with pytest.raises(ValueError, match="(?i)key id|kid"):
                await verify_google_id_token(token)

    async def test_g7_hs256_algorithm_rejected(self):
        """G7 — A token using HS256 (symmetric) is rejected; RS256 is required."""
        from auth.oauth_utils import verify_google_id_token

        token = _google_token(alg="HS256")
        with _mock_http_get(_GOOGLE_JWKS):
            with pytest.raises(ValueError, match="(?i)algorithm|unsupported"):
                await verify_google_id_token(token)

    async def test_g8_email_absent_rejected(self):
        """G8 — A Google token without an email claim is rejected."""
        from auth.oauth_utils import verify_google_id_token

        token = _google_token(email=None)
        with _mock_http_get(_GOOGLE_JWKS):
            with pytest.raises(ValueError, match="(?i)email"):
                await verify_google_id_token(token)

    async def test_g9_email_verified_string_true_normalised(self):
        """G9a — email_verified="true" (string) is normalised to bool True."""
        from auth.oauth_utils import verify_google_id_token

        token = _google_token(email_verified="true")
        with _mock_http_get(_GOOGLE_JWKS):
            claims = await verify_google_id_token(token)
        assert claims["email_verified"] is True

    async def test_g9_email_verified_string_false_normalised(self):
        """G9b — email_verified="false" (string) is normalised to bool False."""
        from auth.oauth_utils import verify_google_id_token

        token = _google_token(email_verified="false")
        with _mock_http_get(_GOOGLE_JWKS):
            claims = await verify_google_id_token(token)
        assert claims["email_verified"] is False

    async def test_g9_email_verified_int_one_normalised(self):
        """G9c — email_verified=1 (int) is normalised to bool True."""
        from auth.oauth_utils import verify_google_id_token

        token = _google_token(email_verified=1)
        with _mock_http_get(_GOOGLE_JWKS):
            claims = await verify_google_id_token(token)
        assert claims["email_verified"] is True

    async def test_g_frontend_cannot_inject_claims(self):
        """Frontend-crafted claims cannot bypass server-side validation.

        A token signed with a key not in the provider's JWKS must be rejected,
        even if its payload contains valid-looking claims.
        """
        from auth.oauth_utils import verify_google_id_token

        # Frontend signs with its own key, absent from the JWKS.
        frontend_priv, _, _ = _make_rsa_pair("frontend-kid")
        token = _google_token(signing_key=frontend_priv, kid="frontend-kid")
        with _mock_http_get(_GOOGLE_JWKS):  # Only contains test-kid-1
            with pytest.raises(ValueError):
                await verify_google_id_token(token)


# ═══════════════════════════════════════════════════════════════════════════════
# Apple tests
# ═══════════════════════════════════════════════════════════════════════════════

class TestAppleCrypto:
    """A1–A9: Direct cryptographic tests for verify_apple_id_token()."""

    async def test_a1_valid_rs256_token(self):
        """A1 — A correctly signed RS256 Apple token is accepted."""
        from auth.oauth_utils import verify_apple_id_token

        token = _apple_token()
        with _mock_http_get(_APPLE_JWKS):
            claims = await verify_apple_id_token(token)

        assert claims["sub"] == "apple-crypto-sub-1"
        assert claims["email"] == "crypto@icloud.com"
        assert claims["email_verified"] is True

    async def test_a2_invalid_signature(self):
        """A2 — Token signed with a key not in Apple's JWKS is rejected."""
        from auth.oauth_utils import verify_apple_id_token

        token = _apple_token(signing_key=_OTHER_PRIV_KEY)
        with _mock_http_get(_APPLE_JWKS):
            with pytest.raises(ValueError, match="(?i)(invalid|signature|key)"):
                await verify_apple_id_token(token)

    async def test_a3_expired_token(self):
        """A3 — An expired Apple token is rejected."""
        from auth.oauth_utils import verify_apple_id_token

        token = _apple_token(exp=_NOW - 3600, iat=_NOW - 7200)
        with _mock_http_get(_APPLE_JWKS):
            with pytest.raises(ValueError, match="(?i)expired"):
                await verify_apple_id_token(token)

    async def test_a4_wrong_audience(self):
        """A4 — A token with the wrong audience is rejected."""
        from auth.oauth_utils import verify_apple_id_token

        token = _apple_token(aud="wrong.bundle.id")
        with _mock_http_get(_APPLE_JWKS):
            with pytest.raises(ValueError, match="(?i)audience"):
                await verify_apple_id_token(token)

    async def test_a5_wrong_issuer(self):
        """A5 — A token with an issuer other than Apple's is rejected."""
        from auth.oauth_utils import verify_apple_id_token

        token = _apple_token(iss="https://evil.com")
        with _mock_http_get(_APPLE_JWKS):
            with pytest.raises(ValueError, match="(?i)issuer"):
                await verify_apple_id_token(token)

    async def test_a6_unknown_kid(self):
        """A6 — A token referencing an unknown kid is rejected."""
        from auth.oauth_utils import verify_apple_id_token

        token = _apple_token(kid="unknown-kid-xyz")
        with _mock_http_get(_APPLE_JWKS):
            with pytest.raises(ValueError, match="(?i)key id|kid"):
                await verify_apple_id_token(token)

    async def test_a7_hs256_algorithm_rejected(self):
        """A7 — A token using HS256 is rejected; RS256 is required."""
        from auth.oauth_utils import verify_apple_id_token

        token = _apple_token(alg="HS256")
        with _mock_http_get(_APPLE_JWKS):
            with pytest.raises(ValueError, match="(?i)algorithm|unsupported"):
                await verify_apple_id_token(token)

    async def test_a8_email_absent_accepted(self):
        """A8 — Apple token without email is accepted (normal repeat-login behaviour)."""
        from auth.oauth_utils import verify_apple_id_token

        token = _apple_token(email=None, email_verified=None)
        with _mock_http_get(_APPLE_JWKS):
            claims = await verify_apple_id_token(token)

        assert claims["sub"] == "apple-crypto-sub-1"
        assert claims["email"] is None

    async def test_a9_email_verified_string_true_normalised(self):
        """A9a — email_verified="true" (string) is normalised to bool True."""
        from auth.oauth_utils import verify_apple_id_token

        token = _apple_token(email_verified="true")
        with _mock_http_get(_APPLE_JWKS):
            claims = await verify_apple_id_token(token)
        assert claims["email_verified"] is True

    async def test_a9_email_verified_string_false_normalised(self):
        """A9b — email_verified="false" (string) is normalised to bool False."""
        from auth.oauth_utils import verify_apple_id_token

        token = _apple_token(email_verified="false")
        with _mock_http_get(_APPLE_JWKS):
            claims = await verify_apple_id_token(token)
        assert claims["email_verified"] is False

    async def test_a9_email_verified_int_zero_normalised(self):
        """A9c — email_verified=0 (int) is normalised to bool False."""
        from auth.oauth_utils import verify_apple_id_token

        token = _apple_token(email_verified=0)
        with _mock_http_get(_APPLE_JWKS):
            claims = await verify_apple_id_token(token)
        assert claims["email_verified"] is False

    async def test_a_frontend_cannot_inject_claims(self):
        """Frontend-crafted Apple claims cannot bypass server-side validation."""
        from auth.oauth_utils import verify_apple_id_token

        frontend_priv, _, _ = _make_rsa_pair("frontend-apple-kid")
        token = _apple_token(signing_key=frontend_priv, kid="frontend-apple-kid")
        with _mock_http_get(_APPLE_JWKS):
            with pytest.raises(ValueError):
                await verify_apple_id_token(token)

    async def test_a_jwks_fetch_failure_raises(self):
        """If Apple's JWKS endpoint is unavailable, ValueError is raised (fail safe)."""
        from auth.oauth_utils import verify_apple_id_token

        token = _apple_token()

        # Make httpx.AsyncClient.get raise an exception.
        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("network error"))

        with patch("auth.oauth_utils.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="(?i)unavailable|provider"):
                await verify_apple_id_token(token)

    async def test_g_jwks_fetch_failure_raises(self):
        """If Google's JWKS endpoint is unavailable, ValueError is raised (fail safe)."""
        from auth.oauth_utils import verify_google_id_token

        token = _google_token()

        mock_client = AsyncMock()
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client.get = AsyncMock(side_effect=Exception("network error"))

        with patch("auth.oauth_utils.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(ValueError, match="(?i)unavailable|provider"):
                await verify_google_id_token(token)
