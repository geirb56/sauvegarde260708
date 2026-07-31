"""OAuth authentication router (Google + Apple).

Endpoints:
    POST /api/auth/google   — authenticate with a Google ID token
    POST /api/auth/apple    — authenticate with an Apple ID token

Both endpoints:
    1. Verify the provider ID token server-side (against public JWKS).
    2. Extract the stable provider subject (``sub``) and email.
    3. Look up the ``auth_identities`` collection by (provider, provider_subject).
    4. If found: retrieve the associated RunIndex user.
    5. If not found: create a new RunIndex user and a FREE subscription,
       then record the identity in ``auth_identities``.
    6. Issue a RunIndex JWT using the same ``create_access_token`` function
       used by email/password login.

Security notes:
    - No frontend-supplied user_id, email, or name is trusted.
    - Identities are keyed on the stable ``provider_subject`` (``sub``),
      not on email alone, to prevent email-based account takeover.
    - Account linking is done server-side only:
      if a verified provider email already belongs to an existing RunIndex user,
      the OAuth identity is linked to that same account (no duplicate user).
    - The provider ID token is verified and then discarded; only the RunIndex
      JWT is returned to the frontend.

Race-condition strategy (identity-first, idempotent):
    The unique index on ``auth_identities(provider, provider_subject)`` is used
    as the serialization point for concurrent OAuth requests for the same identity.

    New-user creation flow:
    1. FAST PATH — Existing identity → return associated user.
       If the user document is missing (partial-failure recovery), fall through
       to create it with the identity's existing user_id (self-healing).
    2. EMAIL LINK PATH — Verified email matches an existing RunIndex user
       → insert identity linked to that user; no new user created.
    3. CLAIM PATH — Generate new_user_id, insert auth_identity FIRST.
       • DuplicateKeyError → another concurrent request already claimed this
         identity; look up and return the canonical user.  No orphan user or
         subscription is ever created by the losing request.
       • Success → create user document, then FREE subscription (both guarded
         by DuplicateKeyError to be idempotent against further partial failures).

    Result: at most one user document and one FREE subscription are created per
    (provider, provider_subject) pair, regardless of concurrent requests.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Request, status
from pymongo.errors import DuplicateKeyError

from auth.jwt_utils import create_access_token
from auth.models import TokenResponse, UserResponse
from auth.oauth_models import AppleAuthRequest, GoogleAuthRequest
from auth.oauth_utils import verify_apple_id_token, verify_google_id_token
from subscription_manager import create_free_subscription

logger = logging.getLogger(__name__)

oauth_router = APIRouter(prefix="/auth", tags=["auth"])

# ── Shared helpers ─────────────────────────────────────────────────────────────


def _user_to_response(user: dict) -> UserResponse:
    return UserResponse(
        id=user["id"],
        email=user["email"],
        is_email_verified=user.get("is_email_verified", False),
        is_active=user.get("is_active", True),
        created_at=user["created_at"],
        last_login_at=user.get("last_login_at"),
    )


def _strip_sensitive(user: dict) -> dict:
    """Return a copy of *user* with sensitive fields removed."""
    exclude = {"password_hash", "reset_password_token_hash", "reset_password_expires_at"}
    return {k: v for k, v in user.items() if k not in exclude}


async def _find_or_create_oauth_user(
    db,
    provider: str,
    provider_subject: str,
    provider_email: Optional[str],
    email_verified: bool,
) -> dict:
    """Return the RunIndex user for this OAuth identity, creating one if needed.

    Lookup is performed exclusively on (provider, provider_subject) — never
    on email alone — to prevent email-based account takeover attacks.

    Args:
        db:               Motor database instance.
        provider:         "google" or "apple".
        provider_subject: Stable ``sub`` claim from the provider's ID token.
        provider_email:   Email from the provider (may be None for Apple on
                          repeat logins, or a private relay address).
        email_verified:   Whether the provider considers the email verified.

    Returns:
        The RunIndex user document (without sensitive fields).
    """
    now = datetime.now(timezone.utc)
    _projection = {"_id": 0, "password_hash": 0,
                   "reset_password_token_hash": 0, "reset_password_expires_at": 0}

    # ── FAST PATH: Existing provider identity → same RunIndex user ─────────────
    identity = await db.auth_identities.find_one(
        {"provider": provider, "provider_subject": provider_subject},
        {"_id": 0},
    )

    if identity:
        user = await db.users.find_one({"id": identity["user_id"]}, _projection)
        if user:
            if not user.get("is_active", True):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Account is disabled. Please contact support.",
                )
            await db.users.update_one(
                {"id": user["id"]},
                {"$set": {"last_login_at": now, "updated_at": now}},
            )
            await db.auth_identities.update_one(
                {"provider": provider, "provider_subject": provider_subject},
                {"$set": {"updated_at": now, "email": provider_email}},
            )
            user["last_login_at"] = now
            logger.info("OAuth login: user=%s provider=%s", user["id"], provider)
            return user

        # Self-healing: identity exists but its user is missing (partial failure).
        # We re-use the existing user_id so the identity stays consistent, and
        # fall through to create the missing user document and subscription below.
        logger.warning(
            "auth_identities references missing user %s (provider=%s sub=%s) — self-healing",
            identity["user_id"], provider, provider_subject,
        )
        new_user_id = identity["user_id"]
        provider_email_normalized = provider_email.strip().lower() if provider_email else None
        display_email = (
            provider_email_normalized
            if provider_email_normalized
            else f"{provider}.{provider_subject}@oauth.runindex.internal"
        )
        if not provider_email_normalized:
            email_verified = False
        user_doc = {
            "id": new_user_id,
            "email": display_email,
            "password_hash": None,
            "is_email_verified": email_verified,
            "is_active": True,
            "auth_providers": [provider],
            "created_at": now,
            "updated_at": now,
            "last_login_at": now,
        }
        try:
            await db.users.insert_one(user_doc)
        except DuplicateKeyError:
            # Another healer won; just fetch the user.
            user = await db.users.find_one({"id": new_user_id}, _projection)
            if user:
                return user
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication error. Please try again.",
            )
        try:
            await create_free_subscription(db, new_user_id)
        except DuplicateKeyError:
            pass  # Subscription already exists — idempotent.
        logger.info("Self-healed OAuth user: user=%s provider=%s", new_user_id, provider)
        return _strip_sensitive(user_doc)

    provider_email_normalized = provider_email.strip().lower() if provider_email else None

    # ── EMAIL LINK PATH: Verified email → reuse existing RunIndex user ─────────
    if provider_email_normalized and email_verified:
        existing_user = await db.users.find_one(
            {"email": provider_email_normalized}, _projection,
        )
        if existing_user:
            if not existing_user.get("is_active", True):
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Account is disabled. Please contact support.",
                )
            await db.users.update_one(
                {"id": existing_user["id"]},
                {
                    "$set": {
                        "last_login_at": now,
                        "updated_at": now,
                        "is_email_verified": True,
                    },
                    "$addToSet": {"auth_providers": provider},
                },
            )
            try:
                await db.auth_identities.insert_one({
                    "user_id": existing_user["id"],
                    "provider": provider,
                    "provider_subject": provider_subject,
                    "email": provider_email_normalized,
                    "created_at": now,
                    "updated_at": now,
                })
            except DuplicateKeyError:
                # Concurrent request already linked the identity — harmless.
                pass
            existing_user["last_login_at"] = now
            existing_user["is_email_verified"] = True
            logger.info(
                "OAuth identity linked to existing user: user=%s provider=%s",
                existing_user["id"], provider,
            )
            return existing_user

    # ── CLAIM PATH: New RunIndex user — identity-first to prevent orphans ──────
    if provider_email_normalized:
        display_email = provider_email_normalized
    else:
        display_email = f"{provider}.{provider_subject}@oauth.runindex.internal"
        email_verified = False

    new_user_id = str(uuid.uuid4())

    # Step 1 — Claim the identity slot FIRST.  The unique index serializes
    # concurrent requests: only one insert_one can succeed.
    try:
        await db.auth_identities.insert_one({
            "user_id": new_user_id,
            "provider": provider,
            "provider_subject": provider_subject,
            "email": provider_email_normalized,
            "created_at": now,
            "updated_at": now,
        })
    except DuplicateKeyError:
        # Another concurrent request claimed this identity first.
        # Look up the canonical user — no orphan user or subscription is created
        # by this (losing) request.
        identity = await db.auth_identities.find_one(
            {"provider": provider, "provider_subject": provider_subject},
            {"_id": 0, "user_id": 1},
        )
        if identity and identity.get("user_id"):
            user = await db.users.find_one({"id": identity["user_id"]}, _projection)
            if user:
                logger.info(
                    "OAuth concurrent-claim: canonical user=%s provider=%s",
                    user["id"], provider,
                )
                return user
        logger.error(
            "OAuth concurrent-claim: could not resolve canonical user (provider=%s sub=%s)",
            provider, provider_subject,
        )
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication error. Please try again.",
        )

    # Step 2 — Create user document (we own new_user_id because we won step 1).
    user_doc = {
        "id": new_user_id,
        "email": display_email,
        "password_hash": None,          # no password for OAuth-only accounts
        "is_email_verified": email_verified,
        "is_active": True,
        "auth_providers": [provider],
        "created_at": now,
        "updated_at": now,
        "last_login_at": now,
    }
    try:
        await db.users.insert_one(user_doc)
    except DuplicateKeyError:
        # Should not happen (UUID is unique), but guard defensively.
        logger.error("UUID collision for new OAuth user %s — this is extremely unlikely", new_user_id)
        user = await db.users.find_one({"id": new_user_id}, _projection)
        if user:
            return user
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication error. Please try again.",
        )
    logger.info("New OAuth user created: user=%s provider=%s", new_user_id, provider)

    # Step 3 — Create FREE subscription via subscription_manager (canonical model).
    try:
        await create_free_subscription(db, new_user_id)
    except DuplicateKeyError:
        pass  # Idempotent guard; subscription already exists.
    logger.info("FREE subscription created for OAuth user: %s", new_user_id)

    return _strip_sensitive(user_doc)


# ── Endpoints ──────────────────────────────────────────────────────────────────


@oauth_router.post("/google", response_model=TokenResponse, status_code=200)
async def auth_google(body: GoogleAuthRequest, request: Request):
    """Authenticate (or create an account) via Google ID token.

    The frontend must obtain a valid Google ID token using Google Identity
    Services (accounts.google.com/gsi/client) and send it here.
    The backend verifies the token against Google's public JWKS endpoint and
    never trusts user-supplied identity claims.

    Returns a RunIndex JWT on success.
    """
    try:
        claims = await verify_google_id_token(body.id_token)
    except ValueError as exc:
        logger.warning("Google ID token verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )

    db = request.app.state.db
    user = await _find_or_create_oauth_user(
        db=db,
        provider="google",
        provider_subject=claims["sub"],
        provider_email=claims.get("email"),
        email_verified=claims.get("email_verified", False),
    )

    access_token = create_access_token(user["id"], user["email"])
    return TokenResponse(
        access_token=access_token,
        user=_user_to_response(user),
    )


@oauth_router.post("/apple", response_model=TokenResponse, status_code=200)
async def auth_apple(body: AppleAuthRequest, request: Request):
    """Authenticate (or create an account) via Apple ID token.

    The frontend must use Sign in with Apple (Apple's JS SDK) and send the
    returned ``id_token`` here.  The ``email`` field is optional and only
    present on the very first Apple authorization; the backend does not
    require it on subsequent logins.

    The backend verifies the token against Apple's public JWKS endpoint.
    Apple's stable ``sub`` claim is used as the technical identifier — email
    is not used as a primary key, especially since Apple may provide private
    relay addresses.

    Returns a RunIndex JWT on success.
    """
    try:
        claims = await verify_apple_id_token(body.id_token)
    except ValueError as exc:
        logger.warning("Apple ID token verification failed: %s", exc)
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=str(exc),
        )

    db = request.app.state.db
    user = await _find_or_create_oauth_user(
        db=db,
        provider="apple",
        provider_subject=claims["sub"],
        provider_email=claims.get("email"),
        email_verified=claims.get("email_verified", False),
    )

    access_token = create_access_token(user["id"], user["email"])
    return TokenResponse(
        access_token=access_token,
        user=_user_to_response(user),
    )
