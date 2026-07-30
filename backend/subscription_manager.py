"""
Subscription Management System
==============================

RunIndex uses three commercial tiers:

    FREE    — default for new users and for expired/unpaid accounts.
              Limited to free features only.

    TRIAL   — 30-day free trial granted only after a backend-verified Garmin
              identity claim. One Garmin identity can unlock at most one trial.

    PREMIUM — Active paid subscription via Paddle (or Stripe, legacy).
              Full Premium access while subscription is valid.

NOTE: Legacy statuses (early_adopter, active, starter, confort, pro) are
      transparently mapped to PREMIUM by access_control.py. They should not
      appear in new subscription documents.

All access decisions MUST go through access_control.get_user_access().
This module handles only the CRUD operations on subscription documents.
"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
from motor.motor_asyncio import AsyncIOMotorDatabase
import logging
import hashlib

from pymongo.errors import DuplicateKeyError

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Free trial duration
TRIAL_DURATION_DAYS = 30

# Legacy — kept for backward-compat references in existing endpoints
EARLY_ADOPTER_PRICE = 4.99
EARLY_ADOPTER_PRICE_ID = "price_early_adopter_499"


# ---------------------------------------------------------------------------
# Canonical subscription statuses
# ---------------------------------------------------------------------------

class SubscriptionStatus:
    # Current canonical statuses
    TRIAL   = "trial"
    FREE    = "free"
    PREMIUM = "premium"

    # Legacy statuses — kept for migration compatibility only.
    # These are no longer created for new subscriptions.
    EARLY_ADOPTER = "early_adopter"   # → maps to PREMIUM
    ACTIVE        = "active"          # Stripe "active" → maps to PREMIUM
    STARTER       = "starter"         # → maps to PREMIUM
    CONFORT       = "confort"         # → maps to PREMIUM
    PRO           = "pro"             # → maps to PREMIUM
    EXPIRED       = "expired"         # → maps to FREE
    CANCELLED     = "cancelled"       # → maps to FREE


# ---------------------------------------------------------------------------
# Feature tables
#
# These are used by the /api/subscription/info endpoint for display purposes.
# For actual access enforcement use access_control.UserAccess.can().
# ---------------------------------------------------------------------------

def _premium_features(enabled: bool) -> dict:
    return {
        "training_plan":     enabled,
        "plan_adaptation":   enabled,
        "session_analysis":  enabled,
        "sync_enabled":      enabled,
        "api_access":        enabled,
        "llm_access":        enabled,
        "full_access":       enabled,
        "rag_access":        enabled,
        "coach_detailed":    enabled,
        "race_predictions":  enabled,
    }


FEATURES = {
    SubscriptionStatus.TRIAL:   _premium_features(True),
    SubscriptionStatus.PREMIUM: _premium_features(True),
    SubscriptionStatus.FREE:    _premium_features(False),
    # Legacy entries — map to the same feature set as their equivalent tier
    SubscriptionStatus.EARLY_ADOPTER: _premium_features(True),
    SubscriptionStatus.ACTIVE:        _premium_features(True),
}

# ---------------------------------------------------------------------------
# Route tables — DEPRECATED
# Use access_control.get_route_access() instead of these lists.
# Kept here only for backward compatibility with any code that still
# imports them directly.
# ---------------------------------------------------------------------------

PROTECTED_ROUTES = [
    "/api/training/plan",
    "/api/training/refresh",
    "/api/training/full-cycle",
    "/api/training/race-predictions",
    "/api/coach/analyze",
    "/api/coach/workout-analysis",
    "/api/coach/detailed-analysis",
    "/api/rag/",
]

PUBLIC_ROUTES = [
    "/api/health",
    "/api/subscription/",
    "/api/premium/",
    "/api/user/",
    "/api/dashboard/insight",
]


async def get_user_subscription(db: AsyncIOMotorDatabase, user_id: str) -> Dict:
    """
    Retrieve a user's raw subscription document.

    New users default to FREE. A Trial is granted only through
    claim_garmin_trial() after backend-side Garmin identity verification.

    NOTE: For access-control decisions use access_control.get_user_access()
    instead of this function. This function is kept for display/CRUD use.
    """
    subscription = await db.subscriptions.find_one({"user_id": user_id})

    if not subscription:
        subscription = await _create_free_subscription(db, user_id)

    # Lazily persist trial expiration to DB
    subscription = await check_trial_expiration(db, subscription)
    # Lazily persist premium expiration to DB
    subscription = await check_premium_expiration(db, subscription)

    return subscription


async def _create_free_subscription(db: AsyncIOMotorDatabase, user_id: str) -> Dict:
    """Create the default FREE subscription for a brand-new user."""
    now = datetime.now(timezone.utc)

    subscription = {
        "user_id": user_id,
        "status": SubscriptionStatus.FREE,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        # Paid-subscription fields remain unset until checkout/webhook activation.
        "paddle_subscription_id": None,
        "paddle_customer_id": None,
        "premium_expires_at": None,
        # Legacy Stripe fields — kept for migration compatibility
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
    }

    await db.subscriptions.insert_one(subscription)
    logger.info("Created FREE subscription for new user '%s'", user_id)

    subscription.pop("_id", None)
    return subscription


async def create_trial_subscription(db: AsyncIOMotorDatabase, user_id: str) -> Dict:
    """
    Create or upgrade a user's subscription to a 30-day trial.

    IMPORTANT: This function must only be called after Garmin identity
    verification succeeds server-side.
    """
    now = datetime.now(timezone.utc)
    trial_end = now + timedelta(days=TRIAL_DURATION_DAYS)

    subscription = {
        "user_id": user_id,
        "status": SubscriptionStatus.TRIAL,
        "created_at": now.isoformat(),
        "trial_start": now.isoformat(),
        "trial_end": trial_end.isoformat(),
        # Paddle fields (null until user subscribes)
        "paddle_subscription_id": None,
        "paddle_customer_id": None,
        "premium_expires_at": None,
        # Legacy Stripe fields — kept for migration compatibility
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "updated_at": now.isoformat(),
    }

    await db.subscriptions.update_one(
        {"user_id": user_id},
        {"$set": subscription},
        upsert=True,
    )
    logger.info("Created 30-day Garmin trial for user '%s', expires %s", user_id, trial_end.isoformat())

    subscription.pop("_id", None)
    return subscription


async def check_trial_expiration(db: AsyncIOMotorDatabase, subscription: Dict) -> Dict:
    """
    Lazily check whether a trial has expired and update MongoDB if so.

    TRIAL → FREE transition is persisted atomically.
    """
    if subscription.get("status") != SubscriptionStatus.TRIAL:
        return subscription

    trial_end_str = subscription.get("trial_end")
    if not trial_end_str:
        return subscription

    try:
        trial_end = datetime.fromisoformat(trial_end_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)

        if now > trial_end:
            await db.subscriptions.update_one(
                {"user_id": subscription["user_id"]},
                {"$set": {"status": SubscriptionStatus.FREE, "updated_at": now.isoformat()}},
            )
            subscription["status"] = SubscriptionStatus.FREE
            logger.info(f"Trial expired for user '{subscription['user_id']}' — set to FREE")
    except Exception as exc:
        logger.error(f"Error checking trial expiration: {exc}")

    return subscription


async def check_premium_expiration(db: AsyncIOMotorDatabase, subscription: Dict) -> Dict:
    """
    Lazily check whether a Premium subscription has expired and update MongoDB.

    PREMIUM → FREE transition is persisted atomically.
    Applies to canonical PREMIUM status and to the legacy "active" status.
    """
    status = subscription.get("status")
    if status not in (SubscriptionStatus.PREMIUM, SubscriptionStatus.ACTIVE):
        return subscription

    expires_field = "premium_expires_at" if status == SubscriptionStatus.PREMIUM else "expires_at"
    expires_str = subscription.get(expires_field)
    if not expires_str:
        return subscription

    try:
        expires_at = datetime.fromisoformat(expires_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)

        if now > expires_at:
            await db.subscriptions.update_one(
                {"user_id": subscription["user_id"]},
                {"$set": {"status": SubscriptionStatus.FREE, "updated_at": now.isoformat()}},
            )
            subscription["status"] = SubscriptionStatus.FREE
            logger.info(
                f"Premium expired for user '{subscription['user_id']}' — set to FREE"
            )
    except Exception as exc:
        logger.error(f"Error checking premium expiration: {exc}")

    return subscription


def _hash_garmin_identity(raw_identity: str) -> str:
    """Hash the backend-verified Garmin identity before persisting it."""
    return hashlib.sha256(raw_identity.strip().lower().encode()).hexdigest()


async def claim_garmin_trial(
    db: AsyncIOMotorDatabase,
    user_id: str,
    garmin_identity_raw: str,
) -> Dict:
    """
    Atomically claim a Trial for a user using a backend-verified Garmin identity.

    Enforced server-side rules:
    - New users start on FREE, never on TRIAL.
    - One Garmin identity can claim at most one Trial across all RunIndex accounts.
    - The Garmin identity must come from the backend integration, never the client.
    """
    garmin_identity = _hash_garmin_identity(garmin_identity_raw)
    now = datetime.now(timezone.utc)
    trial_end = now + timedelta(days=TRIAL_DURATION_DAYS)

    existing_sub = await db.subscriptions.find_one({"user_id": user_id}, {"_id": 0})
    if existing_sub and existing_sub.get("status") in (
        SubscriptionStatus.TRIAL,
        SubscriptionStatus.PREMIUM,
        SubscriptionStatus.ACTIVE,
        SubscriptionStatus.EARLY_ADOPTER,
        SubscriptionStatus.STARTER,
        SubscriptionStatus.CONFORT,
        SubscriptionStatus.PRO,
    ):
        logger.info(
            "[GarminTrial] user=%s already has status=%s — no new trial",
            user_id,
            existing_sub.get("status"),
        )
        return {"granted": False, "reason": "already_active", "subscription": existing_sub}

    registry_doc = {
        "garmin_identity": garmin_identity,
        "trial_used": True,
        "trial_started_at": now.isoformat(),
        "trial_expires_at": trial_end.isoformat(),
        "first_runindex_user_id": user_id,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    try:
        await db.garmin_trial_registry.insert_one(registry_doc)
    except DuplicateKeyError:
        logger.info(
            "[GarminTrial] garmin_identity=%s already used trial — user=%s stays FREE",
            garmin_identity[:12],
            user_id,
        )
        current_sub = await get_user_subscription(db, user_id)
        return {
            "granted": False,
            "reason": "garmin_trial_already_used",
            "subscription": current_sub,
        }

    subscription = await create_trial_subscription(db, user_id)
    logger.info(
        "[GarminTrial] Trial granted user=%s garmin_identity=%s expires=%s",
        user_id,
        garmin_identity[:12],
        trial_end.isoformat(),
    )
    return {"granted": True, "subscription": subscription}


async def get_garmin_trial_record(db: AsyncIOMotorDatabase, garmin_identity_raw: str) -> Optional[Dict]:
    """Return the registry record for a raw Garmin identity, if any."""
    garmin_identity = _hash_garmin_identity(garmin_identity_raw)
    return await db.garmin_trial_registry.find_one({"garmin_identity": garmin_identity}, {"_id": 0})


async def activate_premium(
    db: AsyncIOMotorDatabase,
    user_id: str,
    paddle_subscription_id: str,
    paddle_customer_id: str,
    premium_expires_at: Optional[datetime] = None,
) -> Dict:
    """
    Activate Premium for a user after a successful Paddle payment.

    Called from the Paddle webhook handler.  Never called directly from the
    frontend.
    """
    now = datetime.now(timezone.utc)

    update_fields = {
        "status": SubscriptionStatus.PREMIUM,
        "paddle_subscription_id": paddle_subscription_id,
        "paddle_customer_id": paddle_customer_id,
        "activated_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "cancelled_at": None,
    }
    if premium_expires_at:
        update_fields["premium_expires_at"] = premium_expires_at.isoformat()

    await db.subscriptions.update_one(
        {"user_id": user_id},
        {"$set": update_fields},
        upsert=True,
    )
    logger.info(
        f"Activated PREMIUM for user '{user_id}' "
        f"(paddle_sub={paddle_subscription_id}, expires={premium_expires_at})"
    )

    subscription = await db.subscriptions.find_one({"user_id": user_id})
    subscription.pop("_id", None)
    return subscription


async def renew_premium(
    db: AsyncIOMotorDatabase,
    user_id: str,
    paddle_subscription_id: str,
    new_expires_at: datetime,
) -> Dict:
    """
    Extend Premium expiry after a successful Paddle renewal payment.
    """
    now = datetime.now(timezone.utc)
    await db.subscriptions.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "status": SubscriptionStatus.PREMIUM,
                "paddle_subscription_id": paddle_subscription_id,
                "premium_expires_at": new_expires_at.isoformat(),
                "updated_at": now.isoformat(),
                "cancelled_at": None,
            }
        },
        upsert=True,
    )
    logger.info(
        f"Renewed PREMIUM for user '{user_id}' until {new_expires_at.isoformat()}"
    )
    subscription = await db.subscriptions.find_one({"user_id": user_id})
    subscription.pop("_id", None)
    return subscription


async def cancel_subscription(db: AsyncIOMotorDatabase, user_id: str) -> Dict:
    """
    Mark a subscription as cancelled.

    Per business rule: the user keeps Premium access until premium_expires_at.
    Only when that date passes does access revert to FREE (handled lazily by
    check_premium_expiration).  If no expiry is set, access reverts immediately.
    """
    now = datetime.now(timezone.utc)

    # Determine whether access should stay Premium until end of paid period
    subscription = await db.subscriptions.find_one({"user_id": user_id})
    premium_expires_at = None
    if subscription:
        raw_exp = subscription.get("premium_expires_at") or subscription.get("expires_at")
        if raw_exp:
            try:
                premium_expires_at = datetime.fromisoformat(raw_exp.replace("Z", "+00:00"))
            except (ValueError, TypeError):
                pass

    if premium_expires_at and premium_expires_at > now:
        # Access remains PREMIUM until end of paid period
        new_status = SubscriptionStatus.PREMIUM
        logger.info(
            f"Subscription cancelled for '{user_id}' — Premium access until "
            f"{premium_expires_at.isoformat()}"
        )
    else:
        # No remaining paid period — revert to FREE immediately
        new_status = SubscriptionStatus.FREE
        logger.info(f"Subscription cancelled for '{user_id}' — set to FREE immediately")

    await db.subscriptions.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "status": new_status,
                "cancelled_at": now.isoformat(),
                "updated_at": now.isoformat(),
            }
        },
    )

    subscription = await db.subscriptions.find_one({"user_id": user_id})
    subscription.pop("_id", None)
    return subscription


# ---------------------------------------------------------------------------
# Legacy wrapper — kept for backward compatibility with existing call sites
# ---------------------------------------------------------------------------

async def activate_early_adopter(
    db: AsyncIOMotorDatabase,
    user_id: str,
    stripe_customer_id: str = "",
    stripe_subscription_id: str = "",
    paddle_customer_id: str = "",
    paddle_subscription_id: str = "",
) -> Dict:
    """
    Legacy activation wrapper (Early Adopter → PREMIUM).

    New code should call activate_premium() instead.
    Kept to avoid breaking existing admin/testing endpoints.
    """
    now = datetime.now(timezone.utc)
    await db.subscriptions.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "status": SubscriptionStatus.EARLY_ADOPTER,
                "stripe_customer_id": stripe_customer_id or paddle_customer_id or f"cus_legacy_{user_id}",
                "stripe_subscription_id": stripe_subscription_id or paddle_subscription_id or f"sub_legacy_{user_id}",
                "paddle_customer_id": paddle_customer_id or None,
                "paddle_subscription_id": paddle_subscription_id or None,
                # Legacy display price — not used for access decisions
                "price_locked": EARLY_ADOPTER_PRICE,
                "activated_at": now.isoformat(),
                "updated_at": now.isoformat(),
                # No expiry for grandfathered early adopters
                "premium_expires_at": None,
            }
        },
        upsert=True,
    )
    logger.info(f"(Legacy) Activated Early Adopter → PREMIUM for user '{user_id}'")
    subscription = await db.subscriptions.find_one({"user_id": user_id})
    subscription.pop("_id", None)
    return subscription


# ---------------------------------------------------------------------------
# Display helpers
# ---------------------------------------------------------------------------

def get_trial_days_remaining(subscription: Dict) -> Optional[int]:
    """Return days remaining in trial, or None if not in trial."""
    if subscription.get("status") != SubscriptionStatus.TRIAL:
        return None
    trial_end_str = subscription.get("trial_end")
    if not trial_end_str:
        return None
    try:
        trial_end = datetime.fromisoformat(trial_end_str.replace("Z", "+00:00"))
        remaining = (trial_end - datetime.now(timezone.utc)).days
        return max(0, remaining)
    except Exception:
        return None


def has_feature_access(subscription: Dict, feature: str) -> bool:
    """
    Check whether a subscription document grants access to a feature.

    IMPORTANT: For route/middleware enforcement use access_control.UserAccess.can()
    which has proper fail-closed behaviour and DEMO_MODE guards.
    This function is kept for backward-compat display use only.
    """
    status = subscription.get("status", SubscriptionStatus.FREE)
    # Normalise legacy statuses to their canonical feature set
    from access_control import normalize_legacy_status, Tier
    tier = normalize_legacy_status(status)
    if tier in (Tier.TRIAL, Tier.PREMIUM):
        feature_set = _premium_features(True)
    else:
        feature_set = _premium_features(False)
    return feature_set.get(feature, False)


def is_route_protected(path: str) -> bool:
    """
    DEPRECATED — use access_control.get_route_access() instead.
    Kept for any remaining direct imports.
    """
    from access_control import get_route_access, RouteAccess
    return get_route_access(path) == RouteAccess.PREMIUM


def get_subscription_display(subscription: Dict, lang: str = "en") -> Dict:
    """Return UI display information for the subscription status."""
    status = subscription.get("status", SubscriptionStatus.FREE)

    # Normalise legacy statuses for display
    from access_control import normalize_legacy_status, Tier
    tier = normalize_legacy_status(status)

    if tier == Tier.TRIAL:
        displays = {
            "fr": {"label": "Essai gratuit actif", "description": "Profite de toutes les fonctionnalités", "badge": "ESSAI", "badge_color": "blue"},
            "en": {"label": "Free trial active", "description": "Enjoy all features", "badge": "TRIAL", "badge_color": "blue"},
        }
    elif tier == Tier.PREMIUM:
        displays = {
            "fr": {"label": "Premium", "description": "Accès complet à toutes les fonctionnalités", "badge": "PREMIUM", "badge_color": "violet"},
            "en": {"label": "Premium", "description": "Full access to all features", "badge": "PREMIUM", "badge_color": "violet"},
        }
    else:
        displays = {
            "fr": {"label": "Accès limité", "description": "Abonnement requis pour accéder au coach", "badge": "LIMITÉ", "badge_color": "gray"},
            "en": {"label": "Limited access", "description": "Subscription required to access coach", "badge": "LIMITED", "badge_color": "gray"},
        }

    display = displays.get(lang, displays["en"]).copy()

    if tier == Tier.TRIAL:
        days_remaining = get_trial_days_remaining(subscription)
        if days_remaining is not None:
            display["days_remaining"] = days_remaining
            if lang == "fr":
                display["days_label"] = f"{days_remaining} jour{'s' if days_remaining != 1 else ''} restant{'s' if days_remaining != 1 else ''}"
            else:
                display["days_label"] = f"{days_remaining} day{'s' if days_remaining != 1 else ''} remaining"

    return display
