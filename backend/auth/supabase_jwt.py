"""
Supabase JWT validation for RunIndex backend.

Validates Supabase-issued JWTs and extracts the authenticated user_id (sub claim).
"""

from __future__ import annotations

import os
import logging
from typing import Optional

import jwt
from jwt import PyJWTError

logger = logging.getLogger(__name__)

# Supabase JWT secret — must be set in environment
SUPABASE_JWT_SECRET = os.environ.get("SUPABASE_JWT_SECRET", "")


def verify_supabase_jwt(token: str) -> Optional[dict]:
    """
    Validate a Supabase JWT and return the decoded payload.

    Returns None if the token is invalid, expired, or the secret is not configured.
    The 'sub' claim in the payload is the Supabase user UUID.
    """
    if not SUPABASE_JWT_SECRET:
        logger.warning("[Auth] SUPABASE_JWT_SECRET not configured — rejecting all tokens")
        return None

    try:
        payload = jwt.decode(
            token,
            SUPABASE_JWT_SECRET,
            algorithms=["HS256"],
            options={"verify_aud": False},  # Supabase uses 'authenticated' as audience
        )
        return payload
    except PyJWTError as exc:
        logger.warning(f"[Auth] JWT validation failed: {exc}")
        return None


def extract_user_id(token: str) -> Optional[str]:
    """
    Validate token and return the Supabase user ID (UUID from 'sub' claim).
    Returns None if the token is invalid.
    """
    payload = verify_supabase_jwt(token)
    if not payload:
        return None
    user_id = payload.get("sub")
    if not user_id:
        logger.warning("[Auth] JWT has no 'sub' claim")
        return None
    return str(user_id)
