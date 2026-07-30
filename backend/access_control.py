"""
access_control.py — RunIndex Central Access Control
=====================================================

SINGLE SOURCE OF TRUTH for all subscription and feature access decisions.

Commercial tiers:
    FREE    — trial expired, no active paid subscription
    TRIAL   — 30-day free trial (full Premium access)
    PREMIUM — active paid subscription via Paddle (or Stripe legacy)

Architecture:
    JWT authenticated user
         ↓
    get_user_access(db, user_id) → UserAccess
         ↓
    UserAccess.tier             → FREE | TRIAL | PREMIUM
    UserAccess.can(feature)     → bool
    UserAccess.is_unlimited_chat → bool
    UserAccess.chat_monthly_quota → int | None  (None = no limit)

Security guarantees:
    - DB error → fail closed (returns FREE, no premium access granted)
    - DEMO_MODE in production → raises RuntimeError at import time
    - All access decisions flow through UserAccess.can(), never scattered conditions
    - User identity always comes from JWT, never from frontend-provided values
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from enum import Enum
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Environment guards — evaluated at import time for fast startup failure
# ---------------------------------------------------------------------------

ENVIRONMENT: str = os.getenv("ENVIRONMENT", "development").strip().lower()
DEMO_MODE: bool = os.getenv("DEMO_MODE", "false").strip().lower() in ("true", "1", "yes")


def _check_demo_mode_safety() -> None:
    """
    Raise immediately if DEMO_MODE is enabled in a production environment.

    This check runs at module import time so misconfigured deployments fail
    fast during startup rather than silently granting premium access to all users.
    """
    if DEMO_MODE and ENVIRONMENT == "production":
        raise RuntimeError(
            "CRITICAL SECURITY ERROR: DEMO_MODE=true is FORBIDDEN when "
            "ENVIRONMENT=production. "
            "Set DEMO_MODE=false (or remove it) in your production environment "
            "before starting the server."
        )


# Fail fast on import — prevents a misconfigured production deployment from
# ever reaching the point where it could grant premium access incorrectly.
_check_demo_mode_safety()

if DEMO_MODE:
    logger.warning(
        "⚠️  DEMO_MODE is ENABLED — subscription checks are bypassed. "
        "This MUST NOT be used in production."
    )


# ---------------------------------------------------------------------------
# Tier definitions
# ---------------------------------------------------------------------------

class Tier(str, Enum):
    FREE    = "free"
    TRIAL   = "trial"
    PREMIUM = "premium"


# Features available to TRIAL and PREMIUM users
PREMIUM_FEATURES: frozenset = frozenset({
    "training_plan",
    "plan_adaptation",
    "session_analysis",
    "sync_enabled",
    "api_access",
    "llm_access",
    "full_access",
    "rag_access",
    "coach_detailed",
    "coach_workout_analysis",
    "race_predictions",
    "full_cycle",
    "terra_sync",
    "garmin_sync",
})

# Features available to all authenticated users (any tier)
FREE_FEATURES: frozenset = frozenset({
    "dashboard_insight",
    "workout_list",
    "workout_create",
    "basic_stats",
    "chat_limited",
    "settings",
    "profile",
    "run_index",
    "vma_estimate",
})

# Chat quota constants
# FREE users: hard monthly limit
CHAT_QUOTA_FREE: int = 10
# Anti-abuse hard cap applied on top of is_unlimited (not a commercial quota)
CHAT_ANTIABUSE_CAP: int = 500

# ---------------------------------------------------------------------------
# Legacy status → Tier mapping
#
# The old system had: starter, premium, confort, pro, early_adopter, active,
# trial, free.  These are all mapped to the three canonical tiers below.
# Legacy "premium-equivalent" statuses still need an active subscription or
# no expiration date to be treated as PREMIUM; "active" checks expires_at.
# ---------------------------------------------------------------------------

_LEGACY_PREMIUM_STATUSES: frozenset = frozenset({
    "early_adopter",
    "active",
    "starter",
    "confort",
    "pro",
})

_LEGACY_FREE_STATUSES: frozenset = frozenset({
    "free",
    "expired",
    "cancelled",
    "suspended",
})


def normalize_legacy_status(status: Optional[str]) -> Tier:
    """
    Map any legacy or current subscription status string to a canonical Tier.

    This is used for display/migration purposes only.
    The authoritative tier resolution for access control is _resolve_access().
    """
    if not status:
        return Tier.FREE
    s = status.lower()
    if s == "trial":
        return Tier.TRIAL
    if s == "premium":
        return Tier.PREMIUM
    if s in _LEGACY_PREMIUM_STATUSES:
        return Tier.PREMIUM
    if s in _LEGACY_FREE_STATUSES:
        return Tier.FREE
    logger.warning(f"[AccessControl] Unknown subscription status '{status}' → FREE")
    return Tier.FREE


# ---------------------------------------------------------------------------
# UserAccess — the resolved access object
# ---------------------------------------------------------------------------

class UserAccess:
    """
    Resolved access state for an authenticated user.

    Created exclusively by get_user_access(). Treat as immutable.
    All access decisions MUST flow through this object — never check
    subscription status directly in route handlers or middleware.

    Examples::

        access = await get_user_access(db, user_id)

        if not access.can("training_plan"):
            raise HTTPException(403, "Premium required")

        if not access.is_unlimited_chat:
            # enforce monthly quota
            quota = access.chat_monthly_quota   # int
    """

    __slots__ = (
        "user_id",
        "tier",
        "trial_end",
        "premium_expires_at",
        "paddle_subscription_id",
        "is_demo",
    )

    def __init__(
        self,
        user_id: str,
        tier: Tier,
        trial_end: Optional[datetime] = None,
        premium_expires_at: Optional[datetime] = None,
        paddle_subscription_id: Optional[str] = None,
        is_demo: bool = False,
    ) -> None:
        self.user_id = user_id
        self.tier = tier
        self.trial_end = trial_end
        self.premium_expires_at = premium_expires_at
        self.paddle_subscription_id = paddle_subscription_id
        self.is_demo = is_demo

    # -- Status helpers -------------------------------------------------------

    @property
    def is_free(self) -> bool:
        return self.tier == Tier.FREE

    @property
    def is_trial(self) -> bool:
        return self.tier == Tier.TRIAL

    @property
    def is_premium(self) -> bool:
        return self.tier == Tier.PREMIUM

    @property
    def has_premium_access(self) -> bool:
        """True for both TRIAL and PREMIUM — both receive full premium access."""
        return self.tier in (Tier.TRIAL, Tier.PREMIUM)

    # -- Feature access -------------------------------------------------------

    def can(self, feature: str) -> bool:
        """
        Check whether this user may access a named feature.

        Returns True  if the feature is free (any tier) or if the user has
                      premium access and the feature is a premium feature.
        Returns False for premium features when the user is FREE.
        Returns False for unknown features (fail-closed default).
        """
        if feature in FREE_FEATURES:
            return True
        if feature in PREMIUM_FEATURES:
            return self.has_premium_access
        # Unknown feature — deny by default (fail closed)
        logger.warning(
            f"[AccessControl] Unknown feature '{feature}' requested by "
            f"user '{self.user_id}' — denying (fail closed)"
        )
        return False

    # -- Chat quota -----------------------------------------------------------

    @property
    def is_unlimited_chat(self) -> bool:
        """
        True when the user has no commercial monthly chat limit.

        TRIAL and PREMIUM users are truly unlimited (no commercial cap).
        Anti-abuse protections (CHAT_ANTIABUSE_CAP) are separate and always
        apply regardless of this flag.
        """
        return self.has_premium_access

    @property
    def chat_monthly_quota(self) -> Optional[int]:
        """
        Monthly chat quota.

        Returns None  for unlimited tiers (TRIAL, PREMIUM).
        Returns int   for FREE (CHAT_QUOTA_FREE messages/month).
        """
        return None if self.is_unlimited_chat else CHAT_QUOTA_FREE

    # -- Trial info -----------------------------------------------------------

    @property
    def trial_days_remaining(self) -> Optional[int]:
        """Days remaining in the trial, or None if not in trial."""
        if self.tier != Tier.TRIAL or self.trial_end is None:
            return None
        now = datetime.now(timezone.utc)
        remaining = (self.trial_end - now).days
        return max(0, remaining)

    # -- Serialization --------------------------------------------------------

    def to_api_dict(self) -> dict:
        """
        Serialize to a dict suitable for the /api/subscription/status response.

        The frontend consumes this to display status badges, paywalls, etc.
        It MUST NOT use any field here to bypass backend enforcement.
        """
        feature_access = {}
        for feat in PREMIUM_FEATURES | FREE_FEATURES:
            feature_access[feat] = self.can(feat)

        return {
            "subscription_status": self.tier.value,
            "is_free": self.is_free,
            "is_trial": self.is_trial,
            "is_premium": self.is_premium,
            "has_premium_access": self.has_premium_access,
            "trial_end": self.trial_end.isoformat() if self.trial_end else None,
            "trial_days_remaining": self.trial_days_remaining,
            "premium_expires_at": (
                self.premium_expires_at.isoformat() if self.premium_expires_at else None
            ),
            "is_unlimited_chat": self.is_unlimited_chat,
            "chat_monthly_quota": self.chat_monthly_quota,
            "feature_access": feature_access,
        }

    def __repr__(self) -> str:
        return f"UserAccess(user_id={self.user_id!r}, tier={self.tier.value!r})"


# ---------------------------------------------------------------------------
# get_user_access — the single entry point for all access decisions
# ---------------------------------------------------------------------------

async def get_user_access(db, user_id: str) -> UserAccess:
    """
    Retrieve and resolve the access state for an authenticated user.

    This is the ONLY function that should be called to determine a user's
    subscription tier and permissions. Never read the subscriptions collection
    directly in route handlers.

    Failure modes:
        - DB unavailable → returns FREE (fail closed for premium features)
        - User not found → creates a 30-day trial automatically
        - Invalid/missing subscription data → returns FREE (fail closed)

    DEMO_MODE:
        If DEMO_MODE=true (development only), always returns PREMIUM without
        a DB lookup. Cannot be active when ENVIRONMENT=production (checked at
        import time).
    """
    # --- DEMO MODE (development only) ---
    if DEMO_MODE:
        logger.debug(f"[AccessControl] DEMO_MODE — granting PREMIUM to '{user_id}'")
        return UserAccess(user_id=user_id, tier=Tier.PREMIUM, is_demo=True)

    # --- DB lookup ---
    try:
        subscription = await db.subscriptions.find_one(
            {"user_id": user_id}, {"_id": 0}
        )
    except Exception as exc:
        # FAIL CLOSED — cannot verify subscription → deny premium access
        logger.error(
            f"[AccessControl] DB error looking up subscription for '{user_id}': {exc}. "
            "Failing closed — returning FREE."
        )
        return UserAccess(user_id=user_id, tier=Tier.FREE)

    # --- New user — auto-create FREE subscription ---
    if subscription is None:
        try:
            # Lazy import to avoid circular dependency
            from subscription_manager import create_free_subscription
            subscription = await create_free_subscription(db, user_id)
            logger.info(f"[AccessControl] Auto-created FREE subscription for new user '{user_id}'")
        except Exception as exc:
            logger.error(
                f"[AccessControl] Failed to create subscription for '{user_id}': {exc}. "
                "Failing closed — returning FREE."
            )
            return UserAccess(user_id=user_id, tier=Tier.FREE)

    return _resolve_access(user_id, subscription)


def _resolve_access(user_id: str, subscription: dict) -> UserAccess:
    """
    Convert a raw subscription document into a UserAccess.

    This is the authoritative tier-resolution logic. It handles both current
    canonical statuses (trial, premium, free) and all known legacy statuses
    (early_adopter, active, starter, confort, pro, expired, etc.).

    Expiration is checked here in memory; DB updates happen lazily via
    check_trial_expiration() and check_premium_expiration() in
    subscription_manager.py.
    """
    status = (subscription.get("status") or "free").lower()
    now = datetime.now(timezone.utc)

    # ── TRIAL ─────────────────────────────────────────────────────────────
    if status == "trial":
        trial_end = _parse_dt(subscription.get("trial_end"))
        if trial_end and now > trial_end:
            logger.info(f"[AccessControl] Trial expired for '{user_id}'")
            return UserAccess(user_id=user_id, tier=Tier.FREE, trial_end=trial_end)
        return UserAccess(user_id=user_id, tier=Tier.TRIAL, trial_end=trial_end)

    # ── PREMIUM (canonical) ───────────────────────────────────────────────
    if status == "premium":
        premium_expires_at = _parse_dt(subscription.get("premium_expires_at"))
        if premium_expires_at and now > premium_expires_at:
            logger.info(f"[AccessControl] Premium expired for '{user_id}'")
            return UserAccess(
                user_id=user_id, tier=Tier.FREE, premium_expires_at=premium_expires_at
            )
        paddle_id = (
            subscription.get("paddle_subscription_id")
            or subscription.get("stripe_subscription_id")
        )
        return UserAccess(
            user_id=user_id,
            tier=Tier.PREMIUM,
            premium_expires_at=premium_expires_at,
            paddle_subscription_id=paddle_id,
        )

    # ── LEGACY PREMIUM statuses ───────────────────────────────────────────
    # early_adopter, active (Stripe), starter, confort, pro
    if status in _LEGACY_PREMIUM_STATUSES:
        # "active" (Stripe) — verify expires_at
        if status == "active":
            expires_at = _parse_dt(subscription.get("expires_at"))
            if expires_at and now > expires_at:
                logger.info(
                    f"[AccessControl] Legacy 'active' subscription expired for '{user_id}'"
                )
                return UserAccess(user_id=user_id, tier=Tier.FREE)
        # All other legacy premium statuses had no expiration date in the old system.
        # Treat them as PREMIUM with no expiry (grandfathered).
        premium_expires_at = _parse_dt(
            subscription.get("premium_expires_at") or subscription.get("expires_at")
        )
        return UserAccess(
            user_id=user_id,
            tier=Tier.PREMIUM,
            premium_expires_at=premium_expires_at,
        )

    # ── FREE / EXPIRED / UNKNOWN ──────────────────────────────────────────
    return UserAccess(user_id=user_id, tier=Tier.FREE)


# ---------------------------------------------------------------------------
# Route access classification
# ---------------------------------------------------------------------------

class RouteAccess(str, Enum):
    PUBLIC  = "public"   # No authentication required
    FREE    = "free"     # Any authenticated user (any tier)
    PREMIUM = "premium"  # Authenticated + TRIAL or PREMIUM required


# Route prefix → required access level.
# Longest-prefix match is used (see get_route_access()).
# This table is the canonical declaration of which routes need what level.
ROUTE_ACCESS_MAP: Dict[str, RouteAccess] = {
    # ── Public (no auth) ─────────────────────────────────────────────────
    "/api/health":              RouteAccess.PUBLIC,
    "/api/auth/":               RouteAccess.PUBLIC,
    "/api/webhook/":            RouteAccess.PUBLIC,   # signature-verified internally

    # ── Free (any authenticated user) ────────────────────────────────────
    "/api/subscription/":       RouteAccess.FREE,
    "/api/premium/":            RouteAccess.FREE,
    "/api/user/":               RouteAccess.FREE,
    "/api/dashboard/insight":   RouteAccess.FREE,
    "/api/stats":               RouteAccess.FREE,
    "/api/workouts":            RouteAccess.FREE,
    "/api/run-index":           RouteAccess.FREE,
    "/api/cache/":              RouteAccess.FREE,
    "/api/metrics":             RouteAccess.FREE,
    # Chat history is free; send is handled separately (quota enforcement)
    "/api/chat/history":        RouteAccess.FREE,
    "/api/chat/store-response": RouteAccess.FREE,
    "/api/chat/send":           RouteAccess.FREE,     # quota enforced inside the handler

    # ── Premium (TRIAL or PREMIUM required) ──────────────────────────────
    "/api/training/plan":             RouteAccess.PREMIUM,
    "/api/training/refresh":          RouteAccess.PREMIUM,
    "/api/training/full-cycle":       RouteAccess.PREMIUM,
    "/api/training/race-predictions": RouteAccess.PREMIUM,
    "/api/training/dynamic-plan":     RouteAccess.PREMIUM,
    "/api/training/feedback":         RouteAccess.PREMIUM,
    "/api/training/today":            RouteAccess.PREMIUM,
    "/api/training/week-plan":        RouteAccess.PREMIUM,
    "/api/training/metrics":          RouteAccess.PREMIUM,
    "/api/training/vma-history":      RouteAccess.PREMIUM,
    "/api/training/set-goal":         RouteAccess.PREMIUM,
    "/api/training/goals":            RouteAccess.PREMIUM,
    "/api/training/":                 RouteAccess.PREMIUM,
    "/api/training-plan":             RouteAccess.PREMIUM,
    "/api/coach/analyze":             RouteAccess.PREMIUM,
    "/api/coach/workout-analysis":    RouteAccess.PREMIUM,
    "/api/coach/detailed-analysis":   RouteAccess.PREMIUM,
    "/api/coach/guidance":            RouteAccess.PREMIUM,
    "/api/coach/digest":              RouteAccess.PREMIUM,
    "/api/coach/":                    RouteAccess.PREMIUM,
    "/api/rag/":                      RouteAccess.PREMIUM,
    "/api/terra/":                    RouteAccess.PREMIUM,
    "/api/garmin/":                   RouteAccess.PREMIUM,
    "/api/sync/":                     RouteAccess.PREMIUM,
}


def get_route_access(path: str) -> RouteAccess:
    """
    Determine the required access level for a request path.

    Uses longest-prefix matching against ROUTE_ACCESS_MAP.
    Unknown routes default to PREMIUM (fail closed — unknown endpoints
    are not granted free or public access automatically).
    """
    best_prefix = ""
    best_access = RouteAccess.PREMIUM  # fail-closed default

    for prefix, access in ROUTE_ACCESS_MAP.items():
        if path.startswith(prefix) and len(prefix) > len(best_prefix):
            best_prefix = prefix
            best_access = access

    if not best_prefix:
        logger.warning(
            f"[AccessControl] Route '{path}' not in ROUTE_ACCESS_MAP — "
            "defaulting to PREMIUM (fail closed)"
        )

    return best_access


# ---------------------------------------------------------------------------
# Utility
# ---------------------------------------------------------------------------

def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    """Parse an ISO datetime string to a timezone-aware UTC datetime."""
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None
