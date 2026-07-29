# AUDIT — MIGRATION STRIPE → PADDLE
## RunIndex — Rapport complet avant implémentation
**Date :** 2026-07-29  
**Statut :** ⚠️ AUDIT UNIQUEMENT — aucune modification du code

---

## 1. Architecture Stripe actuelle

```
Frontend (Subscription.jsx / Settings.jsx / Paywall.jsx)
    ↓ POST /api/subscription/checkout  (ou /premium/checkout  ou /early-adopter/checkout)
Backend FastAPI (server.py)
    → emergentintegrations.payments.stripe.checkout.StripeCheckout
    → crée une Stripe Checkout Session
    ↓ redirect checkout_url → stripe.com
Utilisateur paie
    ↓ return URL (?session_id=... &subscription=success)
Frontend poll: GET /api/subscription/checkout/status/{session_id}
    → backend appelle stripe_checkout.get_checkout_status()
    → si payé : update MongoDB subscriptions + payment_transactions
Parallèlement :
Stripe → POST /api/webhook/stripe
    → verify_and_parse_stripe_event() (HMAC-SHA256 custom)
    → stripe_checkout.handle_webhook()
    → si paid : update MongoDB
```

---

## 2. Fichiers Stripe trouvés

| Fichier | Rôle |
|---|---|
| `backend/server.py` | Import StripeCheckout, endpoints checkout/webhook, SUBSCRIPTION_TIERS multi-tiers |
| `backend/services/stripe_webhook_security.py` | Vérificateur HMAC-SHA256 maison pour signature Stripe |
| `backend/subscription_manager.py` | Legacy `activate_early_adopter()`, Stripe fields dans le schéma |
| `backend/auth/router.py` | Crée la subscription initiale avec `stripe_customer_id: None` |
| `backend/demo_mode.py` | Subscription de démo avec `stripe_customer_id: "cus_DEMO_MODE"` |
| `backend/requirements.txt` | `stripe==14.4.1` et `emergentintegrations==0.1.0` |
| `backend/tests/test_stripe_webhook_security.py` | Tests signature Stripe |
| `backend/tests/test_subscription.py` | Tests checkout (vérifie URL Stripe) |
| `backend/tests/test_subscription_chat.py` | Tests checkout multi-tiers Stripe |
| `frontend/src/pages/Subscription.jsx` | Checkout Stripe, mention "Paiement sécurisé Stripe" |
| `frontend/src/pages/Settings.jsx` | Callback Stripe (`?session_id`), early_adopter checkout |
| `frontend/src/components/Paywall.jsx` | Stripe Checkout pour early_adopter |
| `frontend/src/lib/i18n.js` | Textes "securePayment: Paiement sécurisé Stripe" (3 langues) |
| `frontend/src/context/SubscriptionContext.jsx` | Fallback dangereux sur erreur API |

---

## 3. Endpoints Stripe trouvés

| Endpoint | Méthode | Description |
|---|---|---|
| `/api/subscription/checkout` | POST | Checkout principal (premium/confort/pro) via Stripe |
| `/api/premium/checkout` | POST | Alias backward-compat → délègue au précédent |
| `/api/subscription/checkout/status/{session_id}` | GET | Poll statut Stripe + activation Premium |
| `/api/premium/checkout/status/{session_id}` | GET | Alias backward-compat |
| `/api/webhook/stripe` | POST | Webhook Stripe principal (signature vérifiée) |
| `/api/subscription/early-adopter/checkout` | POST | Checkout Stripe pour Early Adopter |
| `/api/webhook/stripe/early-adopter` | POST | Webhook Stripe Early Adopter |
| `/api/subscription/verify-checkout/{session_id}` | GET | ⚠️ Vérif + activation (insécure, voir §12) |
| `/api/subscription/early-adopter-offer` | GET | Données de l'offre Early Adopter |
| `/api/subscription/activate-early-adopter` | POST | Activation manuelle (admin/test) |

---

## 4. Modèles MongoDB concernés

### Collection `subscriptions` (document actuel)
```json
{
  "user_id": "...",
  "status": "trial|free|premium|early_adopter|active|...",
  "created_at": "ISO",
  "trial_start": "ISO",
  "trial_end": "ISO",
  "stripe_customer_id": null,
  "stripe_subscription_id": null,
  "paddle_subscription_id": null,
  "paddle_customer_id": null,
  "premium_expires_at": null,
  "price_locked": null,
  "activated_at": null,
  "updated_at": "ISO"
}
```

### Collection `payment_transactions`
```json
{
  "session_id": "cs_...",
  "user_id": "...",
  "amount": 4.99,
  "currency": "eur",
  "tier": "premium|confort|pro",
  "billing_period": "monthly|annual",
  "plan": "early_adopter",
  "status": "pending|completed",
  "product": "runindex_...",
  "stripe_customer_id": "...",
  "stripe_subscription_id": "...",
  "created_at": "ISO",
  "completed_at": "ISO"
}
```

### Collection `chat_messages`
Utilisée pour le comptage du quota mensuel (10 messages/mois FREE).

---

## 5. Composants frontend concernés

| Fichier | Ce qui concerne Stripe/paiement |
|---|---|
| `pages/Subscription.jsx` | `handleSubscribe()` → POST checkout, `handleSuccess()` → GET status, texte "Stripe", `PREMIUM_TIERS` avec legacy tiers |
| `pages/Settings.jsx` | Callback Stripe sur URL params, `handlePaymentSuccess()` polling, `handleSubscribe()` → `/premium/checkout`, early_adopter checkout |
| `components/Paywall.jsx` | `handleActivate()` → early_adopter/checkout → redirect Stripe |
| `context/SubscriptionContext.jsx` | **Fallback sécuritaire cassé** sur erreur API (→ force trial avec tout à true) |
| `lib/i18n.js` | `securePayment: "Paiement sécurisé Stripe"` (FR/EN/ES) |

---

## 6. Anciennes logiques "early_adopter"

- **Produit** : `early_adopter` = abonnement Premium à 4,99 €/mois "garanti à vie", créé avant la migration vers les tiers standards.
- **Endpoints dédiés** : `/api/subscription/early-adopter/checkout`, `/api/webhook/stripe/early-adopter`, `/api/subscription/early-adopter-offer`, `/api/subscription/activate-early-adopter`
- **`activate_early_adopter()`** dans `subscription_manager.py` : wrapper legacy, met le statut à `"premium"` (canonique) et stocke les anciens IDs Stripe.
- **`access_control.py`** : `early_adopter` est dans `_LEGACY_PREMIUM_STATUSES` → mappé à `PREMIUM` sans expiration (grandfathered).
- **Frontend** : `Paywall.jsx`, `Settings.jsx` appellent encore l'endpoint early_adopter/checkout. `SubscriptionContext.jsx` expose `isEarlyAdopter`. `Subscription.jsx` inclut `early_adopter` dans `PREMIUM_TIERS`.
- **`SUBSCRIPTION_TIERS`** dans `server.py` : contient encore `confort` (5,99 €/mois) et `pro` (9,99 €/mois).
- **`demo_mode.py`** : la subscription de démo utilise encore le statut `early_adopter`.

---

## 7. Données Stripe historiques

- Les champs `stripe_customer_id` et `stripe_subscription_id` sont présents dans les documents `subscriptions` existants pour les utilisateurs `early_adopter` ou `active` historiques.
- La collection `payment_transactions` contient des sessions Stripe passées.
- `access_control.py` lit `stripe_subscription_id` en fallback dans `_resolve_access()` (ligne 415) pour alimenter `paddle_subscription_id` dans `UserAccess`.
- **Il n'y a pas de requête Stripe API en lecture** pour vérifier des abonnements existants — les données Stripe sont uniquement dans MongoDB.
- **Stratégie de préservation** : les champs Stripe doivent être conservés en lecture seule dans les documents existants. Les utilisateurs `early_adopter` avec `premium_expires_at: null` sont des abonnements perpétuels grandfathered — ils restent PREMIUM via `access_control.py` sans aucune interaction Stripe ou Paddle.

---

## 8. Variables d'environnement

### À retirer (Stripe)
```
STRIPE_API_KEY
STRIPE_WEBHOOK_SECRET
```

### À ajouter (Paddle — backend uniquement)
```
PADDLE_API_KEY          # Clé API Paddle (jamais dans le frontend, jamais dans le code)
PADDLE_WEBHOOK_SECRET   # Secret de signature webhook Paddle
PADDLE_ENVIRONMENT      # "sandbox" | "production"
PADDLE_PRICE_ID         # ID du prix Paddle (4,99 €/mois)
PADDLE_PRODUCT_ID       # ID du produit Paddle (RunIndex Premium)
```

### Frontend (clé publique uniquement)
```
REACT_APP_PADDLE_CLIENT_TOKEN   # Client-side token Paddle.js (public, pas secret)
```

> ⚠️ `PADDLE_API_KEY` ne doit jamais être exposé côté frontend ni apparaître dans les logs.

---

## 9. Architecture Paddle cible

```
Frontend (Subscription.jsx / Settings.jsx / Paywall.jsx)
    ↓ GET /api/subscription/checkout-params   (retourne price_id + customer_id Paddle)
    ↓ Paddle.js (client-side overlay) — aucun secret exposé
    ↓ Paddle Checkout (overlay ou redirect)
Paddle
    ↓ POST /api/webhook/paddle    (signature Paddle vérifiée côté backend)
Backend FastAPI
    → verify_paddle_webhook_signature()
    → lire subscription.custom_data.user_id  (fourni à la création du checkout)
    → appel subscription_manager.activate_premium() / renew_premium() / cancel_subscription()
    → update MongoDB subscriptions
    ↓
access_control.get_user_access()
    ↓
UserAccess (FREE | TRIAL | PREMIUM)
    ↓
Permissions vérifiées par chaque handler
```

**Après paiement (frontend) :**
- `Paddle.checkout.open({ onComplete: () => refreshSubscription() })`
- Rafraîchit depuis `/api/subscription/status` — ne décide jamais lui-même que l'utilisateur est Premium.

---

## 10. Liste exacte des fichiers à modifier

| Fichier | Modifications |
|---|---|
| `backend/server.py` | Remplacer import StripeCheckout → logique Paddle ; remplacer les endpoints checkout/webhook Stripe ; simplifier SUBSCRIPTION_TIERS à free + premium ; corriger chat/send pour utiliser access_control ; supprimer `verify_checkout_session` insécure |
| `backend/services/stripe_webhook_security.py` | Remplacer par `paddle_webhook_security.py` |
| `backend/auth/router.py` | Garder `stripe_customer_id`/`stripe_subscription_id: null` pour migration (ne pas supprimer) |
| `backend/demo_mode.py` | Remplacer status `early_adopter` → `premium`, `stripe_customer_id` → `paddle_customer_id` |
| `backend/requirements.txt` | Retirer `stripe==14.4.1` et `emergentintegrations==0.1.0` ; ajouter lib Paddle |
| `backend/tests/test_stripe_webhook_security.py` | Remplacer par `test_paddle_webhook_security.py` |
| `backend/tests/test_subscription.py` | Adapter les tests checkout Stripe vers Paddle |
| `backend/tests/test_subscription_chat.py` | Adapter tests multi-tiers (supprimer confort/pro) |
| `frontend/src/context/SubscriptionContext.jsx` | **CRITIQUE** : corriger le fallback erreur |
| `frontend/src/pages/Subscription.jsx` | Remplacer handleSubscribe Stripe par Paddle.js ; texte Stripe → Paddle |
| `frontend/src/pages/Settings.jsx` | Retirer callback `?session_id` Stripe ; remplacer handleSubscribe |
| `frontend/src/components/Paywall.jsx` | Remplacer Stripe checkout par Paddle.js |
| `frontend/src/lib/i18n.js` | Remplacer `securePayment: "... Stripe"` → `"... Paddle"` (3 langues) |

---

## 11. Liste exacte des fichiers à supprimer

| Fichier | Raison |
|---|---|
| `backend/services/stripe_webhook_security.py` | Remplacé par `paddle_webhook_security.py` |

---

## 12. Risques identifiés

### 🔴 CRITIQUES — Sécurité

**1. `SubscriptionContext.jsx` L.33-48** — Fallback erreur réseau → force Premium  
Sur erreur réseau/API, le contexte force `status: "trial"` avec TOUTES les fonctionnalités à `true`. Une indisponibilité backend accorde l'accès Premium à tous les utilisateurs côté frontend.  
→ **Doit devenir : état inconnu / aucune permission accordée localement.**

```jsx
// Actuel (DANGEREUX) :
setSubscription({
  status: "trial",
  features: { training_plan: true, ..., full_access: true }
});

// Cible :
setSubscription({ status: "unknown", features: {} });
setError(err);
```

**2. `/api/subscription/verify-checkout/{session_id}`** — Activation sans vérification réelle  
Active un abonnement `early_adopter` si un document `payment_transactions` avec `plan: "early_adopter"` existe, sans vérifier le statut réel du paiement Stripe.  
→ **Doit être supprimé ou refactoré pour n'activer que via webhook.**

**3. `/api/subscription/activate-early-adopter`** — user_id depuis le body  
Accepte `user_id` depuis le corps de la requête. Ne vérifie pas que le JWT correspond au body.  
→ **Doit utiliser uniquement l'identité JWT.**

### 🟡 ARCHITECTURE

**4. `chat/send` endpoint** — Double source de vérité  
A sa propre logique subscription (constante `PREMIUM_STATUSES`, lecture directe MongoDB) au lieu d'utiliser `access_control.get_user_access()`.

**5. SUBSCRIPTION_TIERS multi-tiers** — `confort` et `pro` encore exposés  
Ces tiers ne doivent pas être proposés dans Paddle. Le checkout Paddle n'expose qu'un seul produit : RunIndex Premium 4,99 €/mois.

**6. `check_subscription_status`** — Statut incohérent  
Active avec status `"active"` (legacy Stripe) et `expires_at` au lieu de `"premium"` et `premium_expires_at`.

### 🟡 LEGACY

**7. `billing_period: annual`** — Non supporté par le modèle commercial cible  
Le checkout actuel supporte `annual` mais ce n'est pas dans le modèle Paddle cible.

**8. `auth/router.py`** — Champs Stripe créés au register  
Crée le document trial avec `stripe_customer_id: None`. Ces champs peuvent rester pour compatibilité historique.

---

## 13. Plan de migration (ordre des étapes)

### ÉTAPE 1 — Corrections de sécurité (indépendant de Stripe/Paddle)
1. Corriger `SubscriptionContext.jsx` : erreur API → `{ status: "unknown", features: {} }`, pas de permission
2. Supprimer `/api/subscription/verify-checkout/{session_id}` ou le sécuriser
3. Corriger `chat/send` pour utiliser `get_user_access()` au lieu de sa propre logique

### ÉTAPE 2 — Backend Paddle
1. Ajouter `backend/services/paddle_webhook_security.py`
2. Ajouter endpoint `POST /api/webhook/paddle` : vérification signature, mapping événements, appels `subscription_manager`
3. Remplacer `POST /api/subscription/checkout` : retourner paramètres Paddle pour Paddle.js
4. Simplifier `SUBSCRIPTION_TIERS` : garder `free` + `premium` uniquement
5. Mettre à jour `demo_mode.py` : statut `premium`, `paddle_customer_id`
6. Retirer import `emergentintegrations.payments.stripe` et `stripe==14.4.1`
7. Ajouter variables d'env Paddle dans la configuration

### ÉTAPE 3 — Frontend Paddle
1. Ajouter `@paddle/paddle-js` dans `package.json`
2. Remplacer les 3 points de checkout par `Paddle.Checkout.open()`
3. `custom_data.user_id` fourni par le backend via JWT (pas depuis localStorage)
4. Après `onComplete`, rafraîchir depuis `/api/subscription/status`
5. Mettre à jour les textes i18n.js (Stripe → Paddle, 3 langues)

### ÉTAPE 4 — Événements Paddle
| Événement Paddle | Action |
|---|---|
| `subscription.activated` | `activate_premium(user_id, paddle_sub_id, paddle_cust_id, period_end)` |
| `subscription.updated` | `renew_premium(user_id, paddle_sub_id, new_period_end)` |
| `transaction.completed` | Maintenir PREMIUM, mettre à jour période |
| `subscription.cancelled` | `cancel_subscription(user_id)` — PREMIUM jusqu'à `period_end` |
| `subscription.past_due` | Logger ; `check_premium_expiration` gère la transition FREE |
| `subscription.paused` | Traiter selon statut réel Paddle |

### ÉTAPE 5 — Tests
1. Créer `test_paddle_webhook_security.py` (remplace test_stripe)
2. Adapter tests checkout et subscription
3. Ajouter tests : webhook sans signature, webhook rejouté, user isolation, frontend ne peut pas décider Premium

### ÉTAPE 6 — Données Stripe legacy
- Garder les champs `stripe_customer_id` / `stripe_subscription_id` en lecture seule dans MongoDB
- Les utilisateurs `early_adopter` historiques restent PREMIUM indéfiniment via `access_control.py`
- `payment_transactions` Stripe conservées comme archive

---

## 14. État de la migration au moment de l'audit

| Composant | État |
|---|---|
| `subscription_manager.py` | ✅ Déjà Paddle-ready (`activate_premium`, `renew_premium`, champs `paddle_*`) |
| `access_control.py` | ✅ Déjà Paddle-ready (lit `paddle_subscription_id`) |
| `server.py` (checkout/webhook) | ❌ Encore 100% Stripe |
| Frontend (checkout) | ❌ Encore 100% Stripe |
| `SubscriptionContext.jsx` fallback | 🔴 Bug sécurité présent |
| `/api/subscription/verify-checkout` | 🔴 Bug sécurité présent |
| `chat/send` logique subscription | 🟡 Deuxième source de vérité |
| `SUBSCRIPTION_TIERS` multi-tiers | 🟡 confort/pro encore exposés |

---

## 15. Règles absolues rappelées

1. Ne jamais faire confiance au frontend pour accorder Premium.
2. Ne jamais mettre de secret Paddle dans le code ou le frontend.
3. Vérifier les signatures webhook côté backend.
4. Rendre les webhooks idempotents.
5. Utiliser le JWT pour identifier l'utilisateur — jamais un `user_id` fourni par le frontend.
6. Conserver `access_control.py` comme source unique de vérité pour les permissions.
7. Conserver Trial = 30 jours avec accès Premium complet.
8. Premium = 4,99 €/mois uniquement.
9. Free = 10 messages IA/mois, contrôlé côté backend.
10. Ne pas réintroduire `starter`, `confort`, `pro`, `early_adopter` comme nouveaux tiers.
11. Ne pas migrer les 141 activités "default".
12. Ne pas modifier Garmin.
13. Ne pas supprimer les données Stripe historiques sans stratégie.
