"""
Subscription Management System
==============================

User statuses:
- free: Limited access (no API, no LLM, no sync)
- trial: 30-day free trial, granted only after Garmin identity verified (full access)
- early_adopter: €4.99/month for life (full access)
- premium: Paid subscription via Stripe (full access, alias for early_adopter perms)

Trial rules:
- 1 Garmin account = 1 Trial, enforced via garmin_trial_registry collection
- New users default to FREE; Trial is only granted after backend-verified Garmin identity
- The decision is always made server-side; the frontend never self-assigns a trial

"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Dict
from motor.motor_asyncio import AsyncIOMotorDatabase
import logging
import hashlib
from pymongo.errors import DuplicateKeyError
from demo_mode import DEMO_MODE

logger = logging.getLogger(__name__)

# Free trial duration in days
TRIAL_DURATION_DAYS = 30

# Early Adopter price
EARLY_ADOPTER_PRICE = 4.99

# Subscription statuses
class SubscriptionStatus:
    TRIAL = "trial"
    FREE = "free"
    EARLY_ADOPTER = "early_adopter"
    PREMIUM = "premium"

# Features by status
# PREMIUM has identical permissions to EARLY_ADOPTER and TRIAL (full access)
FEATURES = {
    SubscriptionStatus.TRIAL: {
        "training_plan": True,
        "plan_adaptation": True,
        "session_analysis": True,
        "sync_enabled": True,
        "api_access": True,
        "llm_access": True,
        "full_access": True
    },
    SubscriptionStatus.FREE: {
        "training_plan": False,
        "plan_adaptation": False,
        "session_analysis": False,
        "sync_enabled": False,
        "api_access": False,
        "llm_access": False,
        "full_access": False
    },
    SubscriptionStatus.EARLY_ADOPTER: {
        "training_plan": True,
        "plan_adaptation": True,
        "session_analysis": True,
        "sync_enabled": True,
        "api_access": True,
        "llm_access": True,
        "full_access": True
    },
    SubscriptionStatus.PREMIUM: {
        "training_plan": True,
        "plan_adaptation": True,
        "session_analysis": True,
        "sync_enabled": True,
        "api_access": True,
        "llm_access": True,
        "full_access": True
    },
}


# Protected routes (require an active subscription)
PROTECTED_ROUTES = [
    "/api/training/plan",
    "/api/training/refresh",
    "/api/training/full-cycle",
    "/api/training/race-predictions",
    "/api/coach/analyze",
    "/api/coach/workout-analysis",
    "/api/coach/detailed-analysis",
    "/api/rag/",
    "/api/workouts",  # Workout list
]

# Always accessible routes (even in free)
PUBLIC_ROUTES = [
    "/api/health",
    "/api/subscription/",
    "/api/premium/",
    "/api/user/",
    "/api/dashboard/insight",  # Basic insight
]


async def get_user_subscription(db: AsyncIOMotorDatabase, user_id: str) -> Dict:
    """
    Retrieves a user's subscription status.
    New users get FREE status by default.
    Trial is only granted after Garmin identity verification via claim_garmin_trial().
    """
    subscription = await db.subscriptions.find_one({"user_id": user_id})

    if not subscription:
        # New user → FREE by default (no auto-trial)
        subscription = await _create_free_subscription(db, user_id)

    # Check if trial has expired
    subscription = await check_trial_expiration(db, subscription)

    return subscription


async def _create_free_subscription(db: AsyncIOMotorDatabase, user_id: str) -> Dict:
    """Creates a FREE subscription for a new user (no trial, no card required)."""
    now = datetime.now(timezone.utc)

    subscription = {
        "user_id": user_id,
        "status": SubscriptionStatus.FREE,
        "plan": SubscriptionStatus.FREE,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
    }

    await db.subscriptions.insert_one(subscription)
    logger.info(f"Created FREE subscription for new user {user_id}")

    subscription.pop("_id", None)
    return subscription


async def create_trial_subscription(db: AsyncIOMotorDatabase, user_id: str) -> Dict:
    """
    Creates or updates a trial subscription for a user.
    
    IMPORTANT: This function should only be called from claim_garmin_trial()
    after the Garmin identity has been verified server-side.
    Do NOT call this directly to grant trials without Garmin verification.
    """
    now = datetime.now(timezone.utc)
    trial_end = now + timedelta(days=TRIAL_DURATION_DAYS)

    subscription = {
        "user_id": user_id,
        "status": SubscriptionStatus.TRIAL,
        "plan": SubscriptionStatus.TRIAL,
        "created_at": now.isoformat(),
        "trial_start": now.isoformat(),
        "trial_end": trial_end.isoformat(),
        "price_locked": None,
        "updated_at": now.isoformat()
    }

    await db.subscriptions.update_one(
        {"user_id": user_id},
        {"$set": subscription},
        upsert=True,
    )
    logger.info(f"Created trial subscription for user {user_id}, expires {trial_end}")

    subscription.pop("_id", None)
    return subscription


async def check_trial_expiration(db: AsyncIOMotorDatabase, subscription: Dict) -> Dict:
    """Checks if the free trial has expired and updates the status."""
    if subscription.get("status") != SubscriptionStatus.TRIAL:
        return subscription
    
    trial_end_str = subscription.get("trial_end")
    if not trial_end_str:
        return subscription
    
    try:
        trial_end = datetime.fromisoformat(trial_end_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        
        if now > trial_end:
            # Trial expired -> switch to free
            await db.subscriptions.update_one(
                {"user_id": subscription["user_id"]},
                {
                    "$set": {
                        "status": SubscriptionStatus.FREE,
                        "updated_at": now.isoformat()
                    }
                }
            )
            subscription["status"] = SubscriptionStatus.FREE
            logger.info(f"Trial expired for user {subscription['user_id']}, now FREE")
    except Exception as e:
        logger.error(f"Error checking trial expiration: {e}")
    
    return subscription


# ============================================================
# GARMIN TRIAL REGISTRY — 1 Garmin account = 1 Trial
# ============================================================

def _hash_garmin_identity(raw_identity: str) -> str:
    """Return a stable SHA-256 hex digest of the Garmin identity string.

    Avoids storing the raw Garmin username/email in the registry while keeping
    the constraint deterministic and collision-resistant.
    """
    return hashlib.sha256(raw_identity.strip().lower().encode()).hexdigest()


async def claim_garmin_trial(
    db: AsyncIOMotorDatabase,
    user_id: str,
    garmin_identity_raw: str,
) -> Dict:
    """
    Atomically claim a Trial for the given RunIndex user using a verified Garmin identity.

    Rules enforced here (server-side only):
    - 1 Garmin identity → 1 Trial, ever (enforced by unique index on garmin_identity).
    - The garmin_identity_raw MUST come from the backend integration, never from the
      frontend. Callers are responsible for obtaining it from the provider/env.
    - Returns {"granted": True, "subscription": {...}} on success.
    - Returns {"granted": False, "reason": "...", "subscription": {...}} when the Trial
      was already used by this or another RunIndex account.
    - Race-condition safe: the unique MongoDB index + insert-on-absence guarantees
      at most one insert succeeds even with concurrent requests.
    """
    garmin_identity = _hash_garmin_identity(garmin_identity_raw)
    now = datetime.now(timezone.utc)
    trial_end = now + timedelta(days=TRIAL_DURATION_DAYS)

    # Check whether this RunIndex user already has a non-free subscription
    existing_sub = await db.subscriptions.find_one({"user_id": user_id}, {"_id": 0})
    if existing_sub and existing_sub.get("status") in (
        SubscriptionStatus.TRIAL,
        SubscriptionStatus.EARLY_ADOPTER,
        SubscriptionStatus.PREMIUM,
    ):
        logger.info(
            "[GarminTrial] user=%s already has status=%s — no new trial",
            user_id, existing_sub.get("status"),
        )
        return {"granted": False, "reason": "already_active", "subscription": existing_sub}

    # Attempt to atomically register this Garmin identity as trial_used.
    # The unique index on garmin_trial_registry.garmin_identity ensures only one
    # concurrent insert can succeed (DuplicateKeyError for subsequent attempts).
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
        # Another RunIndex user already claimed the trial with this Garmin identity.
        logger.info(
            "[GarminTrial] garmin_identity=%s already used trial — user=%s gets FREE",
            garmin_identity[:12], user_id,
        )
        current_sub = await get_user_subscription(db, user_id)
        return {"granted": False, "reason": "garmin_trial_already_used", "subscription": current_sub}

    # Garmin identity is fresh → grant the trial.
    subscription = await create_trial_subscription(db, user_id)
    logger.info(
        "[GarminTrial] Trial granted user=%s garmin_identity=%s expires=%s",
        user_id, garmin_identity[:12], trial_end.isoformat(),
    )
    return {"granted": True, "subscription": subscription}


async def get_garmin_trial_record(db: AsyncIOMotorDatabase, garmin_identity_raw: str) -> Optional[Dict]:
    """Return the garmin_trial_registry record for a given raw Garmin identity, or None."""
    garmin_identity = _hash_garmin_identity(garmin_identity_raw)
    doc = await db.garmin_trial_registry.find_one(
        {"garmin_identity": garmin_identity}, {"_id": 0}
    )
    return doc


async def activate_early_adopter(
    db: AsyncIOMotorDatabase,
    user_id: str,
    paddle_customer_id: str,
    paddle_subscription_id: str
) -> Dict:
    """Activates the Early Adopter subscription for a user via Paddle."""
    now = datetime.now(timezone.utc)
    
    result = await db.subscriptions.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "status": SubscriptionStatus.EARLY_ADOPTER,
                "plan": SubscriptionStatus.EARLY_ADOPTER,
                "paddle_customer_id": paddle_customer_id,
                "paddle_subscription_id": paddle_subscription_id,
                "price_locked": EARLY_ADOPTER_PRICE,
                "activated_at": now.isoformat(),
                "updated_at": now.isoformat()
            }
        },
        upsert=True
    )
    
    logger.info(f"Activated Early Adopter for user {user_id}")
    
    subscription = await db.subscriptions.find_one({"user_id": user_id})
    subscription.pop("_id", None)
    return subscription


async def cancel_subscription(db: AsyncIOMotorDatabase, user_id: str) -> Dict:
    """Cancels the subscription and switches the user to free."""
    now = datetime.now(timezone.utc)
    
    await db.subscriptions.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "status": SubscriptionStatus.FREE,
                "cancelled_at": now.isoformat(),
                "updated_at": now.isoformat()
            }
        }
    )
    
    logger.info(f"Cancelled subscription for user {user_id}")
    
    subscription = await db.subscriptions.find_one({"user_id": user_id})
    subscription.pop("_id", None)
    return subscription


def get_trial_days_remaining(subscription: Dict) -> Optional[int]:
    """Calculates the number of days remaining in the trial."""
    if subscription.get("status") != SubscriptionStatus.TRIAL:
        return None
    
    trial_end_str = subscription.get("trial_end")
    if not trial_end_str:
        return None
    
    try:
        trial_end = datetime.fromisoformat(trial_end_str.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        remaining = (trial_end - now).days
        return max(0, remaining)
    except:
        return None


def has_feature_access(subscription: Dict, feature: str) -> bool:
    """Checks if the user has access to a feature."""
    # --- DEMO MODE PATCH ---
    if DEMO_MODE:
        return True
    # --- fin patch ---

    status = subscription.get("status", SubscriptionStatus.FREE)
    features = FEATURES.get(status, FEATURES[SubscriptionStatus.FREE])
    return features.get(feature, False)


def is_route_protected(path: str) -> bool:
    """Checks if a route requires an active subscription."""
    # Check if it's a public route
    for public in PUBLIC_ROUTES:
        if path.startswith(public):
            return False
    
    # Check if it's a protected route
    for protected in PROTECTED_ROUTES:
        if path.startswith(protected):
            return True
    
    return False


def get_subscription_display(subscription: Dict, lang: str = "en") -> Dict:
    """Returns subscription display information."""
    status = subscription.get("status", SubscriptionStatus.FREE)
    
    displays = {
        SubscriptionStatus.TRIAL: {
            "fr": {
                "label": "Essai gratuit actif",
                "description": "Profite de toutes les fonctionnalités",
                "badge": "ESSAI",
                "badge_color": "blue"
            },
            "en": {
                "label": "Free trial active",
                "description": "Enjoy all features",
                "badge": "TRIAL",
                "badge_color": "blue"
            }
        },
        SubscriptionStatus.FREE: {
            "fr": {
                "label": "Accès limité",
                "description": "Abonnement requis pour accéder au coach",
                "badge": "LIMITÉ",
                "badge_color": "gray"
            },
            "en": {
                "label": "Limited access",
                "description": "Subscription required to access coach",
                "badge": "LIMITED",
                "badge_color": "gray"
            }
        },
        SubscriptionStatus.EARLY_ADOPTER: {
            "fr": {
                "label": "Early Adopter",
                "description": "4,99 € / mois (prix garanti à vie)",
                "badge": "EARLY ADOPTER",
                "badge_color": "amber"
            },
            "en": {
                "label": "Early Adopter",
                "description": "€4.99 / month (price guaranteed for life)",
                "badge": "EARLY ADOPTER",
                "badge_color": "amber"
            }
        },
        SubscriptionStatus.PREMIUM: {
            "fr": {
                "label": "Premium",
                "description": "Accès complet à toutes les fonctionnalités",
                "badge": "PREMIUM",
                "badge_color": "amber"
            },
            "en": {
                "label": "Premium",
                "description": "Full access to all features",
                "badge": "PREMIUM",
                "badge_color": "amber"
            }
        },

    }

    display = displays.get(status, displays[SubscriptionStatus.FREE]).get(lang, displays.get(status, displays[SubscriptionStatus.FREE]).get("fr", {}))

    # Add remaining days for trial
    if status == SubscriptionStatus.TRIAL:
        days_remaining = get_trial_days_remaining(subscription)
        if days_remaining is not None:
            if lang == "fr":
                display["days_remaining"] = days_remaining
                display["days_label"] = f"{days_remaining} jour{'s' if days_remaining > 1 else ''} restant{'s' if days_remaining > 1 else ''}"
            else:
                display["days_remaining"] = days_remaining
                display["days_label"] = f"{days_remaining} day{'s' if days_remaining > 1 else ''} remaining"

    return display
