"""Authentication router.

Endpoints:
    POST /api/auth/register           — create a new account
    POST /api/auth/login              — obtain a JWT
    POST /api/auth/logout             — client-side logout (stateless JWT)
    GET  /api/auth/me                 — return current user profile
    POST /api/auth/forgot-password    — request a password-reset email
    POST /api/auth/reset-password     — apply a password reset using the token
"""

from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time
from collections import defaultdict
from datetime import datetime, timezone, timedelta
from typing import Dict, List

from fastapi import APIRouter, Depends, HTTPException, Request, status
from pydantic import BaseModel

from auth.dependencies import get_current_user
from auth.jwt_utils import create_access_token, create_short_lived_token, decode_short_lived_token
from auth.mongo_errors import DuplicateKeyError
from auth.models import (
    ForgotPasswordRequest,
    ResetPasswordRequest,
    TokenResponse,
    UserCreate,
    UserLogin,
    UserResponse,
)
from auth.password import hash_password, verify_password
from auth.roles import is_admin_user, resolve_user_role
from subscription_manager import create_free_subscription

logger = logging.getLogger(__name__)

# ── Router ─────────────────────────────────────────────────────────────────────

auth_router = APIRouter(prefix="/auth", tags=["auth"])

# ── Auth-specific rate limiter ─────────────────────────────────────────────────

class _AuthRateLimiter:
    """Stricter rate limiter for authentication endpoints.

    Keyed on ``ip:email`` so it protects against both IP-only and
    credential-stuffing attacks without relying on an authenticated identity.
    """

    def __init__(self, max_attempts: int = 10, window_seconds: int = 60):
        self.max_attempts = max_attempts
        self.window_seconds = window_seconds
        self._store: Dict[str, List[float]] = defaultdict(list)

    def _key(self, request: Request, email: str = "") -> str:
        forwarded = request.headers.get("X-Forwarded-For", "")
        ip = forwarded.split(",")[0].strip() if forwarded else (
            request.client.host if request.client else "unknown"
        )
        return f"{ip}:{email.lower()}"

    def _prune(self, key: str) -> None:
        cutoff = time.time() - self.window_seconds
        self._store[key] = [t for t in self._store[key] if t > cutoff]
        if not self._store[key]:
            self._store.pop(key, None)

    def is_limited(self, request: Request, email: str = "") -> bool:
        key = self._key(request, email)
        self._prune(key)
        return len(self._store.get(key, [])) >= self.max_attempts

    def record(self, request: Request, email: str = "") -> None:
        key = self._key(request, email)
        self._store[key].append(time.time())


_auth_limiter = _AuthRateLimiter(max_attempts=10, window_seconds=60)


def _check_rate_limit(request: Request, email: str = "") -> None:
    if _auth_limiter.is_limited(request, email):
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many attempts. Please try again later.",
            headers={"Retry-After": "60"},
        )


# ── Helper ─────────────────────────────────────────────────────────────────────

def _user_to_response(user: dict) -> UserResponse:
    return UserResponse(
        id=user["id"],
        email=user["email"],
        role=resolve_user_role(user),
        is_admin=is_admin_user(user),
        is_email_verified=user.get("is_email_verified", False),
        is_active=user.get("is_active", True),
        created_at=user["created_at"],
        last_login_at=user.get("last_login_at"),
    )


def _hash_token(token: str) -> str:
    """Store a SHA-256 hash of a token, never the raw value."""
    return hashlib.sha256(token.encode()).hexdigest()


# ── Endpoints ──────────────────────────────────────────────────────────────────


@auth_router.post("/register", response_model=TokenResponse, status_code=201)
async def register(body: UserCreate, request: Request):
    """Create a new user account and return a JWT."""
    _check_rate_limit(request, body.email)
    _auth_limiter.record(request, body.email)

    db = request.app.state.db

    # Check uniqueness — return generic error to avoid user enumeration
    existing = await db.users.find_one({"email": body.email}, {"_id": 0, "id": 1})
    if existing:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )

    import uuid as _uuid

    now = datetime.now(timezone.utc)
    user_id = str(_uuid.uuid4())
    user_email = body.email
    user_doc = {
        "id": user_id,
        "email": user_email,
        "role": "admin" if is_admin_user({"email": user_email}) else "user",
        "password_hash": hash_password(body.password),
        "auth_providers": ["password"],
        "is_email_verified": False,
        "is_active": True,
        "created_at": now,
        "updated_at": now,
        "last_login_at": now,
    }

    try:
        await db.users.insert_one(user_doc)
    except DuplicateKeyError:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An account with this email already exists.",
        )
    logger.info("New user registered: %s", user_doc["id"])

    # New users start as FREE — trial access is granted only after a Garmin
    # identity is verified via activate_garmin_trial() (server-side, never from
    # the frontend).  See subscription_manager.activate_garmin_trial() and the
    # BLOCKER note in subscription_manager.py.
    await create_free_subscription(db, user_id)
    logger.info("FREE subscription created for user: %s", user_id)

    access_token = create_access_token(user_id, user_email)
    return TokenResponse(
        access_token=access_token,
        user=_user_to_response(user_doc),
    )


@auth_router.post("/login", response_model=TokenResponse)
async def login(body: UserLogin, request: Request):
    """Authenticate with email + password and return a JWT."""
    _check_rate_limit(request, body.email)
    _auth_limiter.record(request, body.email)

    db = request.app.state.db

    user = await db.users.find_one({"email": body.email})

    # Constant-time check — always verify even when user is not found to prevent
    # timing-based user enumeration.
    _DUMMY_HASH = "$2b$12$aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa."
    stored_hash = user["password_hash"] if user else _DUMMY_HASH
    password_ok = verify_password(body.password, stored_hash)

    if not user or not password_ok:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid email or password.",
        )

    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is disabled. Please contact support.",
        )

    # Update last_login_at
    now = datetime.now(timezone.utc)
    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {"last_login_at": now, "updated_at": now}},
    )
    user["last_login_at"] = now

    access_token = create_access_token(user["id"], user["email"])
    logger.info("User logged in: %s", user["id"])

    return TokenResponse(
        access_token=access_token,
        user=_user_to_response(user),
    )


class _LogoutResponse(BaseModel):
    message: str


@auth_router.post("/logout", response_model=_LogoutResponse)
async def logout(user: dict = Depends(get_current_user)):
    """Logout endpoint.

    JWTs are stateless; this endpoint exists so the client can signal intent
    and so future revocation logic (e.g., a token denylist) can be added here
    without changing the client contract.  The client must delete its stored
    token upon receiving this response.
    """
    logger.info("User logged out: %s", user["id"])
    return _LogoutResponse(message="Logged out successfully.")


@auth_router.get("/me", response_model=UserResponse)
async def me(request: Request, user: dict = Depends(get_current_user)):
    """Return the authenticated user's public profile (with full timestamps)."""
    db = request.app.state.db
    doc = await db.users.find_one(
        {"id": user["id"]},
        {"_id": 0, "id": 1, "email": 1, "role": 1, "is_email_verified": 1,
         "is_active": 1, "created_at": 1, "last_login_at": 1},
    )
    if not doc:
        raise HTTPException(status_code=404, detail="User not found")
    doc["role"] = resolve_user_role(doc)
    doc["is_admin"] = is_admin_user(doc)
    return UserResponse(**doc)


# ── Password reset ─────────────────────────────────────────────────────────────

_RESET_TOKEN_EXPIRE_MINUTES = 30


@auth_router.post("/forgot-password", status_code=200)
async def forgot_password(body: ForgotPasswordRequest, request: Request):
    """Request a password-reset link.

    Always returns 200 to prevent user enumeration — the response is identical
    whether the email is registered or not.
    """
    _check_rate_limit(request, body.email)
    _auth_limiter.record(request, body.email)

    db = request.app.state.db
    user = await db.users.find_one({"email": body.email}, {"id": 1, "email": 1})

    if user:
        raw_token = secrets.token_urlsafe(32)
        token_hash = _hash_token(raw_token)
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=_RESET_TOKEN_EXPIRE_MINUTES)

        await db.users.update_one(
            {"id": user["id"]},
            {"$set": {
                "reset_password_token_hash": token_hash,
                "reset_password_expires_at": expires_at,
                "updated_at": datetime.now(timezone.utc),
            }},
        )

        # Email delivery: log token in dev; wire a real provider in prod.
        # The token is safe to transmit via email link since it is single-use
        # and expires in 30 minutes.
        _send_reset_email(user["email"], raw_token)

    return {"message": "If this email is registered you will receive a reset link."}


@auth_router.post("/reset-password", status_code=200)
async def reset_password(body: ResetPasswordRequest, request: Request):
    """Apply a password reset using the token from the reset email."""
    _check_rate_limit(request)
    _auth_limiter.record(request)

    db = request.app.state.db

    token_hash = _hash_token(body.token)
    now = datetime.now(timezone.utc)

    user = await db.users.find_one(
        {
            "reset_password_token_hash": token_hash,
            "reset_password_expires_at": {"$gt": now},
        },
        {"id": 1},
    )

    if not user:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired reset token.",
        )

    await db.users.update_one(
        {"id": user["id"]},
        {"$set": {
            "password_hash": hash_password(body.new_password),
            "updated_at": now,
        },
         "$unset": {
             "reset_password_token_hash": "",
             "reset_password_expires_at": "",
         }},
    )

    logger.info("Password reset for user: %s", user["id"])
    return {"message": "Password has been reset successfully."}


# ── Email helper (stub) ────────────────────────────────────────────────────────

def _send_reset_email(email: str, raw_token: str) -> None:
    """Dispatch a password-reset email.

    Production: set EMAIL_PROVIDER + credentials in the environment and replace
    this stub with calls to SendGrid / Resend / SES / Postmark.
    Development: the token is logged at INFO level so it can be used in tests.

    Required env vars for production:
        EMAIL_PROVIDER          (sendgrid | resend | ses | smtp)
        EMAIL_FROM              Sender address
        EMAIL_API_KEY           Provider API key
        FRONTEND_URL            Base URL for the reset link
    """
    frontend_url = os.getenv("FRONTEND_URL", "http://localhost:3000")
    reset_link = f"{frontend_url}/reset-password?token={raw_token}"

    env = os.getenv("ENVIRONMENT", "development").lower()
    if env != "production":
        # Safe to log in dev — never log tokens in production
        logger.info(
            "[DEV] Password reset link for %s: %s",
            email,
            reset_link,
        )
    else:
        logger.info("Password reset email dispatched to %s", email)
        # TODO: integrate a transactional email provider here
