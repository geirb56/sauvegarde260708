"""FastAPI dependency for JWT-authenticated routes.

Usage in any endpoint:

    from auth.dependencies import get_current_user

    @router.get("/protected")
    async def protected(user: dict = Depends(get_current_user)):
        return {"user_id": user["id"]}

The returned dict always contains at least:
    {
        "id": "<uuid>",
        "email": "<email>",
        "is_email_verified": bool,
        "is_active": bool,
        "authenticated": True,
    }
"""

from __future__ import annotations

import logging
from typing import Optional

import jwt
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from auth.jwt_utils import decode_access_token
from auth.roles import is_admin_user, resolve_user_role

logger = logging.getLogger(__name__)

_security = HTTPBearer(auto_error=False)

# Projection: never return sensitive fields to callers
_SAFE_PROJECTION = {
    "_id": 0,
    "password_hash": 0,
    "reset_password_token_hash": 0,
    "reset_password_expires_at": 0,
    "email_verification_token_hash": 0,
    "email_verification_expires_at": 0,
}


async def get_current_user(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> dict:
    """Strict JWT dependency — raises 401 when no valid token is present."""
    _raise_401 = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Authentication required",
        headers={"WWW-Authenticate": "Bearer"},
    )

    if not credentials or not credentials.credentials:
        raise _raise_401

    token = credentials.credentials
    try:
        payload = decode_access_token(token)
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except jwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid authentication token",
            headers={"WWW-Authenticate": "Bearer"},
        )

    user_id: Optional[str] = payload.get("sub")
    if not user_id:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid token claims",
        )

    db = request.app.state.db
    user = await db.users.find_one({"id": user_id}, _SAFE_PROJECTION)

    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required",
        )
    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is disabled",
        )

    return {
        "id": user["id"],
        "email": user["email"],
        "role": resolve_user_role(user),
        "is_admin": is_admin_user(user),
        "is_email_verified": user.get("is_email_verified", False),
        "is_active": user.get("is_active", True),
        "authenticated": True,
    }


async def get_current_user_optional(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_security),
) -> Optional[dict]:
    """Like get_current_user but returns None instead of raising 401.

    Useful for endpoints that work both authenticated and anonymous.
    """
    if not credentials or not credentials.credentials:
        return None
    try:
        return await get_current_user(request, credentials)
    except HTTPException:
        return None


async def require_admin(user: dict = Depends(get_current_user)) -> dict:
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required",
        )
    return user
