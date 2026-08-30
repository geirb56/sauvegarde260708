"""
Subscription Management System
==============================

RunIndex uses three commercial tiers:

    FREE    — trial expired, trial not yet activated, or no active subscription.
              Limited to free features only.

    TRIAL   — 30-day free trial linked to a Garmin identity.
              Full Premium access during trial period.
              One trial per Garmin account (enforced server-side).

    PREMIUM — Active paid subscription via Paddle.
              Full Premium access while subscription is valid.

Trial eligibility rule (product rule):
    1 Garmin account = 1 Trial maximum.
    The trial is granted server-side when a Garmin account is connected for
    the first time.  The frontend can never create or reset a trial.

    NEW USERS START AS FREE.  The trial is only activated via
    activate_garmin_trial() after a Garmin connection is established.

All access decisions MUST go through access_control.get_user_access().
This module handles only the CRUD operations on subscription documents.

Garmin identity model:
    activate_garmin_trial() receives the garmin_identity derived server-side
    from gccli auth status (the authenticated Garmin email, normalised via
    strip().lower()).  The frontend never provides this value.

    Each RunIndex user operates their own isolated GCCLI session (per-user
    HOME directory under GCCLI_HOME/{user_id}).  After a successful gccli
    login the connect endpoint calls provider.get_profile() to obtain the
    real Garmin email, then passes it to activate_garmin_trial().
"""

from datetime import datetime, timezone, timedelta
from typing import Any, Dict, Optional, TYPE_CHECKING
from uuid import uuid4
import logging

from auth.mongo_errors import DuplicateKeyError
from services.datetime_utils import normalize_utc_datetime

if TYPE_CHECKING:
    from motor.motor_asyncio import AsyncIOMotorDatabase
else:  # pragma: no cover - runtime typing fallback for constrained environments
    AsyncIOMotorDatabase = Any

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Garmin trial blocker sentinel
# ---------------------------------------------------------------------------

# Garmin identity is now derived server-side from gcccli auth status email.
_GARMIN_IDENTITY_AVAILABLE: bool = True

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

# Free trial duration
TRIAL_DURATION_DAYS = 30


# ---------------------------------------------------------------------------
# Canonical subscription statuses
# ---------------------------------------------------------------------------

class SubscriptionStatus:
    TRIAL     = "trial"
    FREE      = "free"
    PREMIUM   = "premium"
    EXPIRED   = "expired"
    CANCELED  = "canceled"
    CANCELLED = CANCELED


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
}


def _build_paddle_event_cas_filter(user_id: str, occurred_at_iso: str, event_id: str) -> Dict[str, Any]:
    """Filter enforcing Paddle occurred_at ordering atomically in MongoDB."""
    return {
        "user_id": user_id,
        "$or": [
            {"paddle_last_event_at": {"$exists": False}},
            {"paddle_last_event_at": None},
            {"paddle_last_event_at": {"$lt": occurred_at_iso}},
            {
                "$and": [
                    {"paddle_last_event_at": occurred_at_iso},
                    {
                        "$or": [
                            {"paddle_last_event_id": {"$exists": False}},
                            {"paddle_last_event_id": None},
                            {"paddle_last_event_id": {"$lte": event_id}},
                        ]
                    },
                ]
            },
        ],
    }


async def _apply_paddle_event_ordered_update(
    db: AsyncIOMotorDatabase,
    user_id: str,
    event_id: Optional[str],
    occurred_at: Optional[datetime],
    update_fields: Dict[str, Any],
) -> bool:
    """
    Apply subscription update only if event ordering CAS condition matches.

    Returns True when update is applied, False when stale/lost race.
    """
    normalized_occurred_at = normalize_utc_datetime(occurred_at)
    if not event_id or normalized_occurred_at is None:
        await db.subscriptions.update_one(
            {"user_id": user_id},
            {"$set": update_fields},
            upsert=False,
        )
        return True

    occurred_at_iso = normalized_occurred_at.isoformat()
    update_payload = dict(update_fields)
    update_payload["paddle_last_event_at"] = occurred_at_iso
    update_payload["paddle_last_event_id"] = event_id

    cas_filter = _build_paddle_event_cas_filter(user_id, occurred_at_iso, event_id)
    first = await db.subscriptions.update_one(
        cas_filter,
        {"$set": update_payload},
        upsert=False,
    )
    if getattr(first, "matched_count", 0) > 0:
        return True

    existing = await db.subscriptions.find_one({"user_id": user_id}, {"_id": 1})
    if existing is None:
        try:
            await db.subscriptions.insert_one({"user_id": user_id, **update_payload})
            return True
        except DuplicateKeyError:
            pass

    second = await db.subscriptions.update_one(
        cas_filter,
        {"$set": update_payload},
        upsert=False,
    )
    return getattr(second, "matched_count", 0) > 0


# ---------------------------------------------------------------------------
# Route tables — DEPRECATED
# Use access_control.get_route_access() instead of these lists.
# Kept here only for backward compatibility with any code that still
# imports them directly.
# ---------------------------------------------------------------------------

PROTECTED_ROUTES = [
    "/api/training/plan",
    "/api/training/refresh",
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
    Creates a 30-day trial if the user has no subscription yet.

    NOTE: For access-control decisions use access_control.get_user_access()
    instead of this function.  This function is kept for display/CRUD use.
    """
    subscription = await db.subscriptions.find_one({"user_id": user_id})

    if not subscription:
        # New users start as FREE — trial is activated separately via activate_garmin_trial()
        subscription = await create_free_subscription(db, user_id)

    # Lazily persist trial expiration to DB
    subscription = await check_trial_expiration(db, subscription)
    # Lazily persist premium expiration to DB
    subscription = await check_premium_expiration(db, subscription)

    return subscription


async def create_free_subscription(db: AsyncIOMotorDatabase, user_id: str) -> Dict:
    """
    Create a FREE subscription for a brand-new user.

    New accounts start as FREE.  Premium trial access is granted only after a
    Garmin identity is verified via activate_garmin_trial().

    This function is idempotent: if a subscription already exists it is returned
    as-is.  Use upsert=False to protect against concurrent creation.
    """
    now = datetime.now(timezone.utc)

    subscription = {
        "user_id": user_id,
        "status": SubscriptionStatus.FREE,
        "created_at": now.isoformat(),
        # Trial fields — populated only when activate_garmin_trial() is called
        "trial_start": None,
        "trial_end": None,
        "trial_used": False,
        "garmin_identity": None,
        # Paddle fields (null until user subscribes)
        "paddle_subscription_id": None,
        "paddle_customer_id": None,
        "premium_expires_at": None,
        "updated_at": now.isoformat(),
    }

    try:
        await db.subscriptions.insert_one(subscription)
        logger.info("Created FREE subscription")
    except DuplicateKeyError:
        existing_subscription = await db.subscriptions.find_one({"user_id": user_id}, {"_id": 0})
        if not existing_subscription or existing_subscription.get("user_id") != user_id:
            raise
        logger.info("FREE subscription already exists")
        return existing_subscription

    subscription.pop("_id", None)
    return subscription


async def create_trial_subscription(db: AsyncIOMotorDatabase, user_id: str) -> Dict:
    """
    Create a 30-day trial subscription for a user.

    This function should only be called after a Garmin identity has been
    verified as eligible (no prior trial used).  See activate_garmin_trial()
    for the gated version that enforces the "1 Garmin = 1 Trial" rule.

    Trial dates are always calculated and stored server-side in UTC.
    The frontend can never call this function.

    NOTE: Direct call sites that previously used this to auto-create a trial
    on signup must be updated to call create_free_subscription() instead.
    """
    now = datetime.now(timezone.utc)
    trial_end = now + timedelta(days=TRIAL_DURATION_DAYS)

    subscription = {
        "user_id": user_id,
        "status": SubscriptionStatus.TRIAL,
        "created_at": now.isoformat(),
        "trial_start": now.isoformat(),
        "trial_end": trial_end.isoformat(),
        "trial_used": True,
        "garmin_identity": None,   # Populated by activate_garmin_trial()
        # Paddle fields (null until user subscribes)
        "paddle_subscription_id": None,
        "paddle_customer_id": None,
        "premium_expires_at": None,
        "updated_at": now.isoformat(),
    }

    await db.subscriptions.insert_one(subscription)
    logger.info(f"Created 30-day trial for user '{user_id}', expires {trial_end.isoformat()}")

    subscription.pop("_id", None)
    return subscription


async def activate_garmin_trial(
    db: AsyncIOMotorDatabase,
    user_id: str,
    garmin_identity: str,
) -> Dict:
    """
    Attempt to activate a 30-day Premium trial for a RunIndex user linked to
    a specific Garmin identity.

    Enforces the product rule: 1 Garmin account = 1 Trial maximum.

    Algorithm (atomic, race-condition safe):
    1. Validate that garmin_identity is a non-empty server-provided value.
    2. Check the garmin_trial_registry collection for a prior trial using this
       Garmin identity (ANY RunIndex user).
    3. If already used → return the current subscription unchanged (FREE).
    4. If not used → atomically insert a registry entry with $setOnInsert
       (unique index prevents duplicates under concurrent requests).
    5. Upsert the user's subscription to TRIAL status.

    Args:
        db:               AsyncIOMotorDatabase
        user_id:          RunIndex user UUID (from JWT, never frontend-provided)
        garmin_identity:  Stable, server-derived Garmin account identifier.
                          MUST come from the Garmin backend, never from the
                          request body or frontend storage.

    Returns:
        The updated subscription document (status may be "trial" or "free").

    Raises:
        ValueError: If garmin_identity is empty or None (fail safe).
    """
    if not _GARMIN_IDENTITY_AVAILABLE:
        raise NotImplementedError(
            "BLOCKER: activate_garmin_trial() requires a per-user Garmin identity. "
            "The current Garmin integration uses a single shared backend account "
            "(GARMIN_USERNAME env var) and provides no per-user Garmin identifier. "
            "This function will be enabled once the Garmin multi-user OAuth "
            "architecture is implemented. "
            "See AUDIT_GARMIN_STEP3.md and the feature/garmin-trial-eligibility PR."
        )

    if not garmin_identity or not str(garmin_identity).strip():
        raise ValueError(
            "garmin_identity must be a non-empty server-provided value. "
            "Frontend-provided or empty values are not accepted."
        )

    garmin_identity = str(garmin_identity).strip().lower()
    now = datetime.now(timezone.utc)
    trial_end = now + timedelta(days=TRIAL_DURATION_DAYS)
    claim_token = uuid4().hex

    current_subscription = await get_user_subscription(db, user_id)
    current_status = current_subscription.get("status")

    # Existing paid or active trial users must keep their status; never restart
    # an active trial and never regress premium to trial.
    if current_status in (SubscriptionStatus.PREMIUM, SubscriptionStatus.TRIAL):
        return current_subscription

    # Never grant a second trial to the same RunIndex user.
    if current_subscription.get("trial_used"):
        return current_subscription

    # ── Step 1: Check if this Garmin identity already used a trial ────────────
    # The garmin_trial_registry has a unique index on garmin_identity.
    # We use find_one_and_update with upsert=True and $setOnInsert to atomically
    # claim a trial slot, preventing race conditions.
    try:
        registry_result = await db.garmin_trial_registry.find_one_and_update(
            {"garmin_identity": garmin_identity},
            {
                "$setOnInsert": {
                    "garmin_identity": garmin_identity,
                    "first_trial_user_id": user_id,
                    "trial_activated_at": now.isoformat(),
                    "trial_started_at": now.isoformat(),
                    "trial_expires_at": trial_end.isoformat(),
                    "trial_used": True,
                    "trial_claim_token": claim_token,
                }
            },
            upsert=True,
            return_document=True,  # return the document after the operation
        )
    except Exception as exc:
        # Duplicate key error (race condition: another request won the upsert)
        # The index raises DuplicateKeyError — treat as "trial already used".
        logger.warning(
            "[GarminTrial] Race condition or DB error for garmin_identity '%s': %s — "
            "treating as trial already used (fail safe).",
            garmin_identity, exc,
        )
        sub = await db.subscriptions.find_one({"user_id": user_id}, {"_id": 0})
        if not sub:
            return await create_free_subscription(db, user_id)
        return await check_trial_expiration(db, sub)

    # If we did not create the registry record in this call, this Garmin identity
    # already consumed its one-time trial (same or different RunIndex account).
    if registry_result.get("trial_claim_token") != claim_token:
        logger.info(
            "[GarminTrial] Garmin identity '%s' already used a trial — user '%s' keeps current status.",
            garmin_identity,
            user_id,
        )
        return await get_user_subscription(db, user_id)

    # ── Step 2: Activate the trial for this user ──────────────────────────────
    await db.subscriptions.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "status": SubscriptionStatus.TRIAL,
                "trial_start": now.isoformat(),
                "trial_end": trial_end.isoformat(),
                "trial_used": True,
                "garmin_identity": garmin_identity,
                "updated_at": now.isoformat(),
            }
        },
        upsert=True,
    )
    logger.info(
        "[GarminTrial] Trial activated for user '%s' (garmin_identity='%s') — "
        "expires %s",
        user_id, garmin_identity, trial_end.isoformat(),
    )

    subscription = await db.subscriptions.find_one({"user_id": user_id}, {"_id": 0})
    return subscription or {}


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
    """
    status = subscription.get("status")
    if status != SubscriptionStatus.PREMIUM:
        return subscription

    expires_str = subscription.get("premium_expires_at")
    if not expires_str:
        now = datetime.now(timezone.utc)
        await db.subscriptions.update_one(
            {"user_id": subscription["user_id"]},
            {"$set": {"status": SubscriptionStatus.FREE, "updated_at": now.isoformat()}},
        )
        subscription["status"] = SubscriptionStatus.FREE
        logger.warning(
            f"Premium for user '{subscription['user_id']}' missing expiry — set to FREE"
        )
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
        now = datetime.now(timezone.utc)
        await db.subscriptions.update_one(
            {"user_id": subscription["user_id"]},
            {"$set": {"status": SubscriptionStatus.FREE, "updated_at": now.isoformat()}},
        )
        subscription["status"] = SubscriptionStatus.FREE
        logger.error(
            f"Error checking premium expiration for user '{subscription['user_id']}': {exc}. "
            "Set to FREE."
        )

    return subscription


async def activate_premium(
    db: AsyncIOMotorDatabase,
    user_id: str,
    paddle_subscription_id: str,
    paddle_customer_id: str,
    premium_expires_at: Optional[datetime] = None,
    paddle_last_event_at: Optional[datetime] = None,
    paddle_event_id: Optional[str] = None,
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
    applied = await _apply_paddle_event_ordered_update(
        db,
        user_id,
        paddle_event_id,
        paddle_last_event_at,
        update_fields,
    )
    if not paddle_event_id or normalize_utc_datetime(paddle_last_event_at) is None:
        await db.subscriptions.update_one(
            {"user_id": user_id},
            {"$set": update_fields},
            upsert=True,
        )
        applied = True
    if not applied:
        current = await db.subscriptions.find_one({"user_id": user_id}) or {"user_id": user_id}
        current.pop("_id", None)
        current["_stale_event"] = True
        return current
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
    paddle_last_event_at: Optional[datetime] = None,
    paddle_event_id: Optional[str] = None,
) -> Dict:
    """
    Extend Premium expiry after a successful Paddle renewal payment.
    """
    now = datetime.now(timezone.utc)
    update_fields = {
        "status": SubscriptionStatus.PREMIUM,
        "paddle_subscription_id": paddle_subscription_id,
        "premium_expires_at": new_expires_at.isoformat(),
        "updated_at": now.isoformat(),
        "cancelled_at": None,
    }
    applied = await _apply_paddle_event_ordered_update(
        db,
        user_id,
        paddle_event_id,
        paddle_last_event_at,
        update_fields,
    )
    if not paddle_event_id or normalize_utc_datetime(paddle_last_event_at) is None:
        await db.subscriptions.update_one(
            {"user_id": user_id},
            {"$set": update_fields},
            upsert=True,
        )
        applied = True
    if not applied:
        current = await db.subscriptions.find_one({"user_id": user_id}) or {"user_id": user_id}
        current.pop("_id", None)
        current["_stale_event"] = True
        return current
    logger.info(
        f"Renewed PREMIUM for user '{user_id}' until {new_expires_at.isoformat()}"
    )
    subscription = await db.subscriptions.find_one({"user_id": user_id})
    subscription.pop("_id", None)
    return subscription


async def cancel_subscription(
    db: AsyncIOMotorDatabase,
    user_id: str,
    premium_expires_at: Optional[datetime] = None,
    paddle_last_event_at: Optional[datetime] = None,
    paddle_event_id: Optional[str] = None,
) -> Dict:
    """
    Mark a subscription as canceled.

    Per business rule: the user keeps Premium access until premium_expires_at.
    Only when that date passes does access revert to FREE (handled lazily by
    check_premium_expiration).  If no expiry is set, access reverts immediately.
    """
    now = datetime.now(timezone.utc)

    # Determine whether access should stay Premium until end of paid period
    subscription = await db.subscriptions.find_one({"user_id": user_id})
    effective_expires_at = normalize_utc_datetime(premium_expires_at)
    if subscription and effective_expires_at is None:
        raw_exp = subscription.get("premium_expires_at") or subscription.get("expires_at")
        effective_expires_at = normalize_utc_datetime(raw_exp)

    if effective_expires_at and effective_expires_at > now:
        # Access remains PREMIUM until end of paid period
        new_status = SubscriptionStatus.PREMIUM
        logger.info(
            f"Subscription cancelled for '{user_id}' — Premium access until "
            f"{effective_expires_at.isoformat()}"
        )
    else:
        # No remaining paid period — revert to FREE immediately
        new_status = SubscriptionStatus.FREE
        logger.info(f"Subscription cancelled for '{user_id}' — set to FREE immediately")

    update_fields = {
        "status": new_status,
        "cancelled_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }
    if effective_expires_at:
        update_fields["premium_expires_at"] = effective_expires_at.isoformat()
    applied = await _apply_paddle_event_ordered_update(
        db,
        user_id,
        paddle_event_id,
        paddle_last_event_at,
        update_fields,
    )
    if not applied:
        current = await db.subscriptions.find_one({"user_id": user_id}) or {"user_id": user_id}
        current.pop("_id", None)
        current["_stale_event"] = True
        return current

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
    if status in (SubscriptionStatus.TRIAL, SubscriptionStatus.PREMIUM):
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

    if status == SubscriptionStatus.TRIAL:
        displays = {
            "fr": {"label": "Essai gratuit actif", "description": "Profite de toutes les fonctionnalités", "badge": "ESSAI", "badge_color": "blue"},
            "en": {"label": "Free trial active", "description": "Enjoy all features", "badge": "TRIAL", "badge_color": "blue"},
        }
    elif status == SubscriptionStatus.PREMIUM:
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

    if status == SubscriptionStatus.TRIAL:
        days_remaining = get_trial_days_remaining(subscription)
        if days_remaining is not None:
            display["days_remaining"] = days_remaining
            if lang == "fr":
                display["days_label"] = f"{days_remaining} jour{'s' if days_remaining != 1 else ''} restant{'s' if days_remaining != 1 else ''}"
            else:
                display["days_label"] = f"{days_remaining} day{'s' if days_remaining != 1 else ''} remaining"

    return display
