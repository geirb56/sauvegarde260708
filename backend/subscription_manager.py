"""
Subscription Management System
==============================

User statuses:
- trial: 7-day free trial (full access)
- free: Limited access (no API, no LLM, no sync)
- early_adopter: €4.99/month for life (full access)
- premium: Reserved for future

"""

from datetime import datetime, timezone, timedelta
from typing import Optional, Dict, Tuple
from motor.motor_asyncio import AsyncIOMotorDatabase
import logging
from demo_mode import DEMO_MODE

logger = logging.getLogger(__name__)

# Free trial duration in days
TRIAL_DURATION_DAYS = 7

# Early Adopter price
EARLY_ADOPTER_PRICE = 4.99
EARLY_ADOPTER_PRICE_ID = "price_early_adopter_499"  # Stripe Price ID

# Subscription statuses
class SubscriptionStatus:
    TRIAL = "trial"
    FREE = "free"
    EARLY_ADOPTER = "early_adopter"
    PREMIUM = "premium"

# Features by status
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
    }
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
    Creates a trial account if the user doesn't exist.
    """
    subscription = await db.subscriptions.find_one({"user_id": user_id})
    
    if not subscription:
        # New user -> create a free trial
        subscription = await create_trial_subscription(db, user_id)

    # Check if trial has expired
    subscription = await check_trial_expiration(db, subscription)
    
    return subscription


async def create_trial_subscription(db: AsyncIOMotorDatabase, user_id: str) -> Dict:
    """Creates a trial subscription for a new user."""
    now = datetime.now(timezone.utc)
    trial_end = now + timedelta(days=TRIAL_DURATION_DAYS)
    
    subscription = {
        "user_id": user_id,
        "status": SubscriptionStatus.TRIAL,
        "created_at": now.isoformat(),
        "trial_start": now.isoformat(),
        "trial_end": trial_end.isoformat(),
        "stripe_customer_id": None,
        "stripe_subscription_id": None,
        "price_locked": None,
        "updated_at": now.isoformat()
    }
    
    await db.subscriptions.insert_one(subscription)
    logger.info(f"Created trial subscription for user {user_id}, expires {trial_end}")

    # Return without _id
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


async def activate_early_adopter(
    db: AsyncIOMotorDatabase,
    user_id: str,
    stripe_customer_id: str,
    stripe_subscription_id: str
) -> Dict:
    """Activates the Early Adopter subscription for a user."""
    now = datetime.now(timezone.utc)
    
    result = await db.subscriptions.update_one(
        {"user_id": user_id},
        {
            "$set": {
                "status": SubscriptionStatus.EARLY_ADOPTER,
                "stripe_customer_id": stripe_customer_id,
                "stripe_subscription_id": stripe_subscription_id,
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
                "badge_color": "violet"
            },
            "en": {
                "label": "Premium",
                "description": "Full access to all features",
                "badge": "PREMIUM",
                "badge_color": "violet"
            }
        }
    }
    
    display = displays.get(status, displays[SubscriptionStatus.FREE]).get(lang, displays[status]["fr"])

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
