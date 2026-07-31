"""OAuth identity token verification utilities.

Supports:
    Google  — ID token verification via Google's tokeninfo endpoint and
              google-auth library (google.oauth2.id_token).
    Apple   — ID token verification via Apple's public JWKS endpoint
              (https://appleid.apple.com/auth/keys).

Neither function ever trusts claims from the frontend directly.
The backend fetches the provider's public keys and validates the JWT
signature, issuer, audience, and expiration.

Environment variables:
    GOOGLE_CLIENT_ID   — OAuth client ID used to validate the audience claim.
    APPLE_CLIENT_ID    — App/Service ID used to validate the audience claim.
"""

from __future__ import annotations

import logging
import os
from typing import Any, Dict, Optional

import httpx
import jwt as pyjwt
from jwt.algorithms import RSAAlgorithm

logger = logging.getLogger(__name__)


def _as_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "1", "yes"}
    if isinstance(value, (int, float)):
        return value != 0
    return False


# ── Google ─────────────────────────────────────────────────────────────────────

_GOOGLE_CERTS_URL = "https://www.googleapis.com/oauth2/v3/certs"
_GOOGLE_ISSUERS = {"accounts.google.com", "https://accounts.google.com"}


async def verify_google_id_token(id_token: str, *, expected_nonce: Optional[str] = None) -> Dict[str, Any]:
    """Verify a Google ID token and return its claims.

    Fetches Google's public keys, verifies the JWT signature, and validates
    the standard claims (iss, aud, exp).

    Args:
        id_token: The raw Google ID token string from the frontend.

    Returns:
        dict with at least: sub, email, email_verified (bool), iss, aud, exp.

    Raises:
        ValueError: If the token is invalid, expired, or from the wrong issuer/audience.
    """
    client_id = os.getenv("GOOGLE_CLIENT_ID", "").strip()
    if not client_id:
        raise ValueError("GOOGLE_CLIENT_ID is not configured on the server.")

    # Fetch Google's public JWKS
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(_GOOGLE_CERTS_URL)
            resp.raise_for_status()
            jwks = resp.json()
    except Exception as exc:
        logger.error("Failed to fetch Google public keys: %s", exc)
        raise ValueError("Could not verify Google identity (provider unavailable).")

    # Decode JWT header to get key ID
    try:
        header = pyjwt.get_unverified_header(id_token)
    except pyjwt.exceptions.DecodeError as exc:
        raise ValueError(f"Invalid Google ID token format: {exc}") from exc

    kid = header.get("kid")
    alg = header.get("alg", "RS256")
    if alg != "RS256":
        raise ValueError("Google ID token uses an unsupported signing algorithm.")

    # Find the matching public key
    matching_key = None
    for key_data in jwks.get("keys", []):
        if key_data.get("kid") == kid:
            matching_key = RSAAlgorithm.from_jwk(key_data)
            break

    if matching_key is None:
        raise ValueError("Google ID token key ID not found in Google's public keys.")

    # Verify the JWT
    try:
        claims = pyjwt.decode(
            id_token,
            key=matching_key,
            algorithms=["RS256"],
            audience=client_id,
            options={"require": ["sub", "email", "exp", "iat", "iss"]},
        )
    except pyjwt.ExpiredSignatureError:
        raise ValueError("Google ID token has expired.")
    except pyjwt.InvalidAudienceError:
        raise ValueError("Google ID token audience does not match GOOGLE_CLIENT_ID.")
    except pyjwt.InvalidIssuerError:
        raise ValueError("Google ID token issuer is not Google.")
    except pyjwt.InvalidTokenError as exc:
        raise ValueError(f"Invalid Google ID token: {exc}") from exc

    # Validate issuer manually (pyjwt accepts issuer= only as string, not set)
    if claims.get("iss") not in _GOOGLE_ISSUERS:
        raise ValueError(f"Unexpected Google ID token issuer: {claims.get('iss')}")

    if not claims.get("email"):
        raise ValueError("Google ID token does not contain an email claim.")
    if expected_nonce and claims.get("nonce") != expected_nonce:
        raise ValueError("Google ID token nonce mismatch.")

    return {
        "sub": claims["sub"],
        "email": claims["email"],
        "email_verified": _as_bool(claims.get("email_verified", False)),
        "name": claims.get("name"),
        "picture": claims.get("picture"),
    }


# ── Apple ──────────────────────────────────────────────────────────────────────

_APPLE_JWKS_URL = "https://appleid.apple.com/auth/keys"
_APPLE_ISSUER = "https://appleid.apple.com"


async def verify_apple_id_token(id_token: str, *, expected_nonce: Optional[str] = None) -> Dict[str, Any]:
    """Verify an Apple ID token and return its claims.

    Fetches Apple's public JWKS, verifies the JWT signature, and validates
    the standard claims (iss, aud, exp).

    Args:
        id_token: The raw Apple ID token string from the frontend.

    Returns:
        dict with at least: sub, iss, aud, exp. Email may be absent on
        subsequent logins (Apple only sends it on first authorization).

    Raises:
        ValueError: If the token is invalid, expired, or from the wrong issuer/audience.
    """
    client_id = os.getenv("APPLE_CLIENT_ID", "").strip()
    if not client_id:
        raise ValueError("APPLE_CLIENT_ID is not configured on the server.")

    # Fetch Apple's public JWKS
    try:
        async with httpx.AsyncClient(timeout=10.0) as http:
            resp = await http.get(_APPLE_JWKS_URL)
            resp.raise_for_status()
            jwks = resp.json()
    except Exception as exc:
        logger.error("Failed to fetch Apple public keys: %s", exc)
        raise ValueError("Could not verify Apple identity (provider unavailable).")

    # Decode JWT header to get key ID
    try:
        header = pyjwt.get_unverified_header(id_token)
    except pyjwt.exceptions.DecodeError as exc:
        raise ValueError(f"Invalid Apple ID token format: {exc}") from exc

    kid = header.get("kid")
    alg = header.get("alg", "RS256")
    if alg != "RS256":
        raise ValueError("Apple ID token uses an unsupported signing algorithm.")

    # Find the matching public key
    matching_key = None
    for key_data in jwks.get("keys", []):
        if key_data.get("kid") == kid:
            matching_key = RSAAlgorithm.from_jwk(key_data)
            break

    if matching_key is None:
        raise ValueError("Apple ID token key ID not found in Apple's public keys.")

    # Verify the JWT
    try:
        claims = pyjwt.decode(
            id_token,
            key=matching_key,
            algorithms=["RS256"],
            audience=client_id,
            options={"require": ["sub", "exp", "iat", "iss"]},
        )
    except pyjwt.ExpiredSignatureError:
        raise ValueError("Apple ID token has expired.")
    except pyjwt.InvalidAudienceError:
        raise ValueError("Apple ID token audience does not match APPLE_CLIENT_ID.")
    except pyjwt.InvalidIssuerError:
        raise ValueError("Apple ID token issuer is not Apple.")
    except pyjwt.InvalidTokenError as exc:
        raise ValueError(f"Invalid Apple ID token: {exc}") from exc

    # Validate issuer
    if claims.get("iss") != _APPLE_ISSUER:
        raise ValueError(f"Unexpected Apple ID token issuer: {claims.get('iss')}")
    if expected_nonce and claims.get("nonce") != expected_nonce:
        raise ValueError("Apple ID token nonce mismatch.")

    # email may be absent on subsequent logins — this is expected Apple behaviour
    return {
        "sub": claims["sub"],
        "email": claims.get("email"),  # may be None or a private relay address
        "email_verified": _as_bool(claims.get("email_verified", False)),
    }
