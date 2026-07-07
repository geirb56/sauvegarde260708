"""
demo_mode.py — CardioCoach Demo Subscription Patch
===================================================

Active un mode démonstration qui simule un abonnement actif (early_adopter)
pour tous les utilisateurs, sans toucher à la base de données.

Utilisation :
  Ajouter dans .env (ou config) :
      DEMO_MODE=true

  Puis dans server.py ou subscription_manager.py, remplacer les appels directs
  à `get_user_subscription()` par `get_demo_subscription()` si DEMO_MODE est True,
  OU utiliser `is_subscription_active(user)` comme helper universel.

Conditions :
  - DEMO_MODE=false (ou absent) → comportement 100% normal, aucun effet.
  - DEMO_MODE=true              → tous les utilisateurs ont un abonnement actif.
"""

import os
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config — lit DEMO_MODE depuis les variables d'environnement
# ---------------------------------------------------------------------------

DEMO_MODE: bool = os.getenv("DEMO_MODE", "false").strip().lower() in ("true", "1", "yes")

if DEMO_MODE:
    logger.warning(
        "⚠️  DEMO_MODE is ENABLED — All subscription checks will return ACTIVE. "
        "Do NOT use this in production."
    )


# ---------------------------------------------------------------------------
# Subscription simulée pour le mode demo
# ---------------------------------------------------------------------------

def _build_demo_subscription(user_id: str = "demo_user") -> Dict:
    """
    Construit un dict subscription qui imite un early_adopter actif.
    Compatible avec le schéma attendu par subscription_manager.py.
    """
    now = datetime.now(timezone.utc)
    return {
        "user_id": user_id,
        "status": "early_adopter",       # Accès complet (voir FEATURES dans subscription_manager.py)
        "created_at": now.isoformat(),
        "trial_start": None,
        "trial_end": None,
        "stripe_customer_id": "cus_DEMO_MODE",
        "stripe_subscription_id": "sub_DEMO_MODE",
        "price_locked": 4.99,
        "activated_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "_demo": True,                    # Flag interne pour logs/debug
    }


# ---------------------------------------------------------------------------
# Helper principal — à utiliser partout dans server.py / adaptation_engine.py
# ---------------------------------------------------------------------------

def is_subscription_active(subscription: Optional[Dict]) -> bool:
    """
    Retourne True si l'abonnement est actif.

    Règles :
      - Si DEMO_MODE est True  → toujours True, peu importe le contenu de `subscription`.
      - Si DEMO_MODE est False → vérifie le statut réel (trial, early_adopter, premium).

    Statuts considérés "actifs" :
      - "trial"          : essai gratuit non expiré
      - "early_adopter"  : abonnement payant actif
      - "premium"        : réservé pour le futur

    Usage dans server.py :
        from demo_mode import is_subscription_active
        sub = await get_user_subscription(db, user_id)
        if not is_subscription_active(sub):
            raise HTTPException(status_code=403, detail="Subscription required")

    Usage dans adaptation_engine.py :
        from demo_mode import is_subscription_active
        if is_subscription_active(user_subscription):
            # accès autorisé
    """
    # --- Mode demo : bypass total ---
    if DEMO_MODE:
        logger.debug("DEMO_MODE active — subscription check bypassed, returning True")
        return True

    # --- Comportement normal ---
    if not subscription:
        return False

    status = subscription.get("status", "free")

    ACTIVE_STATUSES = {"trial", "early_adopter", "premium"}
    return status in ACTIVE_STATUSES


# ---------------------------------------------------------------------------
# Wrapper async pour get_user_subscription (drop-in replacement)
# ---------------------------------------------------------------------------

async def get_demo_subscription(db, user_id: str) -> Dict:
    """
    Drop-in replacement pour `get_user_subscription(db, user_id)`.

    - Si DEMO_MODE est True  → retourne immédiatement une subscription simulée.
    - Si DEMO_MODE est False → délègue à la vraie fonction (aucun effet de bord).

    Usage dans server.py :
        # Avant :
        subscription = await get_user_subscription(db, user_id)

        # Après (avec patch demo) :
        from demo_mode import get_demo_subscription
        subscription = await get_demo_subscription(db, user_id)
    """
    if DEMO_MODE:
        logger.debug(f"DEMO_MODE — returning simulated subscription for user '{user_id}'")
        return _build_demo_subscription(user_id)

    # Import ici pour éviter les circular imports
    from subscription_manager import get_user_subscription
    return await get_user_subscription(db, user_id)


# ---------------------------------------------------------------------------
# Patch du status endpoint (optionnel — pour /api/subscription/status)
# ---------------------------------------------------------------------------

def patch_subscription_status_response(response: Dict, user_id: str) -> Dict:
    """
    Patch optionnel à appliquer sur la réponse de /api/subscription/status.

    Si DEMO_MODE est True, force is_premium=True et tier="early_adopter".
    Si DEMO_MODE est False, retourne la réponse inchangée.

    Usage dans server.py (endpoint get_subscription_status) :
        from demo_mode import patch_subscription_status_response
        result = { ... }   # ta réponse normale
        return patch_subscription_status_response(result, user_id)
    """
    if not DEMO_MODE:
        return response

    logger.debug(f"DEMO_MODE — patching subscription status response for user '{user_id}'")
    patched = response.copy()
    patched.update({
        "tier": "early_adopter",
        "tier_name": "Early Adopter (DEMO)",
        "is_premium": True,
        "is_unlimited": True,
        "messages_remaining": 999,
        "messages_limit": 999,
        "_demo_mode": True,
    })
    return patched
