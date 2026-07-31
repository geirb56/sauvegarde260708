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

    # 1) Existing provider identity → same RunIndex user.
    identity = await db.auth_identities.find_one(
        {"provider": provider, "provider_subject": provider_subject},
        {"_id": 0},
    )

    if identity:
        user = await db.users.find_one(
            {"id": identity["user_id"]},
            {"_id": 0, "password_hash": 0,
             "reset_password_token_hash": 0, "reset_password_expires_at": 0},
        )
        if not user:
            logger.error(
                "auth_identities references missing user %s (provider=%s sub=%s)",
                identity["user_id"], provider, provider_subject,
            )
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication error. Please try again.",
            )
        if not user.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is disabled. Please contact support.",
            )

        update_set: dict = {"last_login_at": now, "updated_at": now}
        await db.users.update_one({"id": user["id"]}, {"$set": update_set})
        await db.auth_identities.update_one(
            {"provider": provider, "provider_subject": provider_subject},
            {"$set": {"updated_at": now, "email": provider_email}},
        )
        user["last_login_at"] = now
        logger.info("OAuth login: user=%s provider=%s", user["id"], provider)
        return user

    provider_email_normalized = provider_email.strip().lower() if provider_email else None

    # 2) Unknown identity + verified email: reuse existing RunIndex user by email.
    if provider_email_normalized and email_verified:
        existing_user = await db.users.find_one(
            {"email": provider_email_normalized},
            {"_id": 0, "password_hash": 0, "reset_password_token_hash": 0, "reset_password_expires_at": 0},
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
                pass

            existing_user["last_login_at"] = now
            existing_user["is_email_verified"] = True
            logger.info(
                "OAuth identity linked to existing user: user=%s provider=%s",
                existing_user["id"],
                provider,
            )
            return existing_user

    # 3) Unknown identity: create a new RunIndex user.
    if provider_email_normalized:
        display_email = provider_email_normalized
    else:
        display_email = f"{provider}.{provider_subject}@oauth.runindex.internal"
        email_verified = False

    new_user_id = str(uuid.uuid4())
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
        # Race safety: if a verified email account appeared concurrently,
        # bind to it instead of creating a duplicate RunIndex account.
        if provider_email_normalized and email_verified:
            existing_user = await db.users.find_one(
                {"email": provider_email_normalized},
                {"_id": 0, "password_hash": 0, "reset_password_token_hash": 0, "reset_password_expires_at": 0},
            )
            if existing_user:
                await db.users.update_one(
                    {"id": existing_user["id"]},
                    {
                        "$set": {"last_login_at": now, "updated_at": now, "is_email_verified": True},
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
                    pass
                existing_user["last_login_at"] = now
                existing_user["is_email_verified"] = True
                return existing_user
        raise

    logger.info("New OAuth user created: user=%s provider=%s", new_user_id, provider)

    # 4) Create FREE subscription — same logic as email/password registration.
    await db.subscriptions.insert_one({
        "user_id": new_user_id,
        "status": "free",
        "created_at": now.isoformat(),
        "trial_start": None,
        "trial_end": None,
        "trial_used": False,
        "garmin_identity": None,
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "price_locked": None,
        "updated_at": now.isoformat(),
    })
    logger.info("FREE subscription created for OAuth user: %s", new_user_id)

    # 5) Record provider identity.
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
        # Another request linked the identity first: return the canonical user.
        identity = await db.auth_identities.find_one(
            {"provider": provider, "provider_subject": provider_subject},
            {"_id": 0, "user_id": 1},
        )
        if identity and identity.get("user_id"):
            existing_user = await db.users.find_one(
                {"id": identity["user_id"]},
                {"_id": 0, "password_hash": 0, "reset_password_token_hash": 0, "reset_password_expires_at": 0},
            )
            if existing_user:
                return existing_user
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Authentication error. Please try again.",
        )

    return user_doc


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
