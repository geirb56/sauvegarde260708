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
from subscription_manager import create_free_subscription

logger = logging.getLogger(__name__)

oauth_router = APIRouter(prefix="/auth", tags=["auth"])

_SAFE_USER_PROJECTION = {
    "_id": 0,
    "password_hash": 0,
    "reset_password_token_hash": 0,
    "reset_password_expires_at": 0,
}

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


def _oauth_conflict() -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Authentication conflict. Please try again.",
    )


def _normalize_provider_email(provider_email: Optional[str]) -> Optional[str]:
    if not provider_email:
        return None
    normalized = provider_email.strip().lower()
    return normalized or None


def _oauth_placeholder_email(provider: str, provider_subject: str) -> str:
    return f"{provider}.{provider_subject}@oauth.runindex.internal"


async def _load_user_by_id(db, user_id: str) -> Optional[dict]:
    return await db.users.find_one({"id": user_id}, _SAFE_USER_PROJECTION)


async def _ensure_subscription_exists(db, user_id: str) -> None:
    subscription = await db.subscriptions.find_one({"user_id": user_id}, {"_id": 0})
    if subscription:
        return
    try:
        await create_free_subscription(db, user_id)
    except DuplicateKeyError:
        subscription = await db.subscriptions.find_one({"user_id": user_id}, {"_id": 0})
        if not subscription or subscription.get("user_id") != user_id:
            raise HTTPException(
                status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
                detail="Authentication error. Please try again.",
            )


async def _touch_user_login(
    db,
    user_id: str,
    provider: str,
    now: datetime,
    *,
    email_verified: bool,
) -> None:
    update_set = {
        "last_login_at": now,
        "updated_at": now,
    }
    if email_verified:
        update_set["is_email_verified"] = True
    await db.users.update_one(
        {"id": user_id},
        {
            "$set": update_set,
            "$addToSet": {"auth_providers": provider},
        },
    )


async def _record_identity_metadata(
    db,
    provider: str,
    provider_subject: str,
    now: datetime,
    *,
    provider_email: Optional[str],
    email_verified: bool,
) -> None:
    update_set: dict = {"updated_at": now}
    if provider_email:
        update_set["email"] = provider_email
    if email_verified:
        update_set["email_verified"] = True
    await db.auth_identities.update_one(
        {"provider": provider, "provider_subject": provider_subject},
        {"$set": update_set},
    )


async def _claim_identity_user_id(
    db,
    provider: str,
    provider_subject: str,
    user_id: str,
    now: datetime,
    *,
    provider_email: Optional[str],
    email_verified: bool,
) -> str:
    identity_doc = {
        "user_id": user_id,
        "provider": provider,
        "provider_subject": provider_subject,
        "email": provider_email,
        "email_verified": email_verified,
        "created_at": now,
        "updated_at": now,
    }
    try:
        await db.auth_identities.insert_one(identity_doc)
        return user_id
    except DuplicateKeyError:
        identity = await db.auth_identities.find_one(
            {"provider": provider, "provider_subject": provider_subject},
            {"_id": 0, "user_id": 1},
        )
        if not identity or not identity.get("user_id"):
            raise _oauth_conflict()
        return identity["user_id"]


async def _self_heal_identity_user(
    db,
    *,
    identity: dict,
    provider: str,
    provider_subject: str,
    now: datetime,
    provider_email: Optional[str],
    email_verified: bool,
) -> dict:
    recovered_email = identity.get("email") or provider_email or _oauth_placeholder_email(provider, provider_subject)
    conflicting_user = await db.users.find_one(
        {"email": recovered_email},
        {"_id": 0, "id": 1},
    )
    if conflicting_user and conflicting_user.get("id") != identity["user_id"]:
        logger.error(
            "OAuth self-heal refused: identity provider=%s sub=%s references missing user %s but email %s belongs to user %s",
            provider,
            provider_subject,
            identity["user_id"],
            recovered_email,
            conflicting_user["id"],
        )
        raise _oauth_conflict()

    healed_user = {
        "id": identity["user_id"],
        "email": recovered_email,
        "password_hash": None,
        "is_email_verified": bool(email_verified or identity.get("email_verified", False)),
        "is_active": True,
        "auth_providers": [provider],
        "created_at": now,
        "updated_at": now,
        "last_login_at": now,
    }
    try:
        await db.users.insert_one(healed_user)
    except DuplicateKeyError:
        healed_user = await _load_user_by_id(db, identity["user_id"])
        if not healed_user:
            raise _oauth_conflict()

    await _ensure_subscription_exists(db, identity["user_id"])
    await _touch_user_login(
        db,
        identity["user_id"],
        provider,
        now,
        email_verified=bool(email_verified or identity.get("email_verified", False)),
    )
    await _record_identity_metadata(
        db,
        provider,
        provider_subject,
        now,
        provider_email=provider_email,
        email_verified=email_verified,
    )
    healed_user["last_login_at"] = now
    if email_verified:
        healed_user["is_email_verified"] = True
    logger.warning(
        "Self-healed OAuth identity for missing user %s (provider=%s sub=%s)",
        identity["user_id"],
        provider,
        provider_subject,
    )
    return healed_user


async def _load_or_self_heal_identity_user(
    db,
    *,
    identity: dict,
    provider: str,
    provider_subject: str,
    now: datetime,
    provider_email: Optional[str],
    email_verified: bool,
) -> dict:
    user = await _load_user_by_id(db, identity["user_id"])
    if user:
        return user
    return await _self_heal_identity_user(
        db,
        identity=identity,
        provider=provider,
        provider_subject=provider_subject,
        now=now,
        provider_email=provider_email,
        email_verified=email_verified,
    )


async def _cleanup_orphaned_oauth_user(db, user_id: str) -> None:
    delete_user = getattr(db.users, "delete_one", None)
    delete_subscriptions = getattr(db.subscriptions, "delete_many", None)
    if delete_user:
        await delete_user({"id": user_id})
    if delete_subscriptions:
        await delete_subscriptions({"user_id": user_id})


async def _resolve_existing_user_login(
    db,
    *,
    user: dict,
    provider: str,
    provider_subject: str,
    now: datetime,
    provider_email: Optional[str],
    email_verified: bool,
) -> dict:
    if not user.get("is_active", True):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Account is disabled. Please contact support.",
        )

    canonical_user_id = await _claim_identity_user_id(
        db,
        provider,
        provider_subject,
        user["id"],
        now,
        provider_email=provider_email,
        email_verified=email_verified,
    )
    if canonical_user_id != user["id"]:
        logger.error(
            "OAuth identity collision detected: provider=%s sub=%s expected user=%s got user=%s",
            provider,
            provider_subject,
            user["id"],
            canonical_user_id,
        )
        raise _oauth_conflict()

    await _ensure_subscription_exists(db, user["id"])
    await _touch_user_login(
        db,
        user["id"],
        provider,
        now,
        email_verified=email_verified,
    )
    await _record_identity_metadata(
        db,
        provider,
        provider_subject,
        now,
        provider_email=provider_email,
        email_verified=email_verified,
    )
    user["last_login_at"] = now
    if email_verified:
        user["is_email_verified"] = True
    return user


async def _resolve_user_insert_collision(
    db,
    *,
    provider: str,
    provider_subject: str,
    now: datetime,
    provider_email: Optional[str],
    email_verified: bool,
    display_email: str,
) -> dict:
    identity = await db.auth_identities.find_one(
        {"provider": provider, "provider_subject": provider_subject},
        {"_id": 0},
    )
    if identity:
        user = await _load_or_self_heal_identity_user(
            db,
            identity=identity,
            provider=provider,
            provider_subject=provider_subject,
            now=now,
            provider_email=provider_email,
            email_verified=email_verified,
        )
        return await _resolve_existing_user_login(
            db,
            user=user,
            provider=provider,
            provider_subject=provider_subject,
            now=now,
            provider_email=provider_email,
            email_verified=email_verified,
        )

    placeholder_email = _oauth_placeholder_email(provider, provider_subject)
    candidate_email = (
        provider_email
        if email_verified and provider_email
        else placeholder_email if display_email == placeholder_email else None
    )
    if not candidate_email:
        raise _oauth_conflict()
    existing_user = await db.users.find_one({"email": candidate_email}, _SAFE_USER_PROJECTION)
    if not existing_user:
        raise _oauth_conflict()

    return await _resolve_existing_user_login(
        db,
        user=existing_user,
        provider=provider,
        provider_subject=provider_subject,
        now=now,
        provider_email=provider_email,
        email_verified=email_verified,
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
    provider_email_normalized = _normalize_provider_email(provider_email)

    # 1) Existing provider identity → same RunIndex user.
    identity = await db.auth_identities.find_one(
        {"provider": provider, "provider_subject": provider_subject},
        {"_id": 0},
    )

    if identity:
        user = await _load_or_self_heal_identity_user(
            db,
            identity=identity,
            provider=provider,
            provider_subject=provider_subject,
            now=now,
            provider_email=provider_email_normalized,
            email_verified=email_verified,
        )
        if not user.get("is_active", True):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Account is disabled. Please contact support.",
            )

        await _ensure_subscription_exists(db, user["id"])
        await _touch_user_login(
            db,
            user["id"],
            provider,
            now,
            email_verified=email_verified,
        )
        await _record_identity_metadata(
            db,
            provider,
            provider_subject,
            now,
            provider_email=provider_email_normalized,
            email_verified=email_verified,
        )
        user["last_login_at"] = now
        if email_verified:
            user["is_email_verified"] = True
        logger.info("OAuth login: user=%s provider=%s", user["id"], provider)
        return user

    # 2) Unknown identity + verified email: reuse existing RunIndex user by email.
    if provider_email_normalized and email_verified:
        existing_user = await db.users.find_one(
            {"email": provider_email_normalized},
            _SAFE_USER_PROJECTION,
        )
        if existing_user:
            existing_user = await _resolve_existing_user_login(
                db,
                user=existing_user,
                provider=provider,
                provider_subject=provider_subject,
                now=now,
                provider_email=provider_email_normalized,
                email_verified=True,
            )
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
        display_email = _oauth_placeholder_email(provider, provider_subject)
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
        return await _resolve_user_insert_collision(
            db,
            provider=provider,
            provider_subject=provider_subject,
            now=now,
            provider_email=provider_email_normalized,
            email_verified=email_verified,
            display_email=display_email,
        )

    logger.info("New OAuth user created: user=%s provider=%s", new_user_id, provider)

    # 4) Create FREE subscription — same logic as email/password registration.
    await _ensure_subscription_exists(db, new_user_id)
    logger.info("FREE subscription created for OAuth user: %s", new_user_id)

    # 5) Record provider identity.
    canonical_user_id = await _claim_identity_user_id(
        db,
        provider,
        provider_subject,
        new_user_id,
        now,
        provider_email=provider_email_normalized,
        email_verified=email_verified,
    )
    if canonical_user_id != new_user_id:
        await _cleanup_orphaned_oauth_user(db, new_user_id)
        canonical_identity = await db.auth_identities.find_one(
            {"provider": provider, "provider_subject": provider_subject},
            {"_id": 0},
        )
        if not canonical_identity:
            raise _oauth_conflict()
        existing_user = await _load_or_self_heal_identity_user(
            db,
            identity=canonical_identity,
            provider=provider,
            provider_subject=provider_subject,
            now=now,
            provider_email=provider_email_normalized,
            email_verified=email_verified,
        )
        if existing_user["id"] != canonical_user_id:
            raise _oauth_conflict()
        await _ensure_subscription_exists(db, canonical_user_id)
        await _touch_user_login(
            db,
            canonical_user_id,
            provider,
            now,
            email_verified=email_verified,
        )
        await _record_identity_metadata(
            db,
            provider,
            provider_subject,
            now,
            provider_email=provider_email_normalized,
            email_verified=email_verified,
        )
        existing_user["last_login_at"] = now
        if email_verified:
            existing_user["is_email_verified"] = True
        return existing_user

    await _record_identity_metadata(
        db,
        provider,
        provider_subject,
        now,
        provider_email=provider_email_normalized,
        email_verified=email_verified,
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
