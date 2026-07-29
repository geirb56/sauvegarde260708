# AUDIT CIBLÉ — Anciennes logiques d'abonnement FRONTEND
_Date : 2026-07-29 — lecture seule, AUCUN code modifié. Périmètre : `/app/frontend/src`._

---

## A. RÉSUMÉ

**« Le frontend utilise-t-il encore d'anciennes logiques d'abonnement ? »**

### ⚠️ OUI — partiellement.

- Le frontend **n'utilise PAS** l'endpoint canonique `GET /api/user/features` ni le champ `feature_access`.
- Il pilote l'accès via **`GET /subscription/info`** (`subscription.status` + `subscription.features`) et **`GET /subscription/status`** (`tier` + quota chat).
- **Bonne nouvelle** : `/subscription/info` est **déjà branché sur `access_control.py`** (backend `get_user_access`, `status = user_access.tier.value`). Donc le gating d'accès est **fonctionnellement aligné** avec la source de vérité, même s'il ne passe pas par `/api/user/features`.
- **Persistent** : références legacy `early_adopter` / `starter` / `confort` / `pro` (surtout affichage + flux de paiement Stripe), et du code mort (`withSubscription`, `PremiumBadge`).

---

## B. Résultats "isPremium"

| Fichier | Ligne | Utilisation | Statut |
|---|---|---|---|
| `components/ChatCoach.jsx` | 163 | `const isPremium = tier !== "free"` — variable **locale** dérivée de `subscription/status.tier` | 🟡 INFORMATIONNEL — contrôle uniquement l'affichage d'un badge (ligne 177), pas l'accès |
| `components/ChatCoach.jsx` | 177 | `{isPremium && (<Badge>{tierName}</Badge>)}` | 🟡 INFORMATIONNEL |
| `components/PremiumBadge.jsx` | 4-5 | prop `isPremium` d'un composant | 🔴 CODE MORT — `PremiumBadge`/`PremiumUpgradeCard` **ne sont importés nulle part** |
| `context/SubscriptionContext.jsx` | 68 | `const isPremium = subscription?.status === "premium"` | ⚠️ À MODIFIER (concept) — dérivé de `/subscription/info` (aligné access_control) mais **`isPremium` n'est consommé par aucun composant** |
| `context/SubscriptionContext.jsx` | 86 | export `isPremium` | ⚠️ exporté mais non utilisé |

> Aucune décision d'accès réelle n'est prise via `isPremium`.

---

## C. Résultats `subscription === "active"`

| Fichier | Ligne | Utilisation | Statut |
|---|---|---|---|
| — | — | **Aucune occurrence** de `subscription === "active"` / `!== "active"` dans le frontend | 🟢 OK |

> Les seules occurrences du mot `"active"` sont : `Layout.jsx:116` (classe CSS de nav) et `TrainingPlan.jsx:267` (statut de cycle d'entraînement `active/upcoming/completed`) — **rien à voir avec l'abonnement**. 🟢 OK.

---

## D. Résultats `tier === "pro"`

| Fichier | Ligne | Utilisation | Statut |
|---|---|---|---|
| — | — | **Aucune** comparaison directe `tier === "pro"` | 🟢 OK |
| `pages/Subscription.jsx` | 148 | `"pro"` présent dans le Set `PREMIUM_TIERS` (compat legacy) | ⚠️ voir §F |

---

## E. Résultats `tier === "premium"`

| Fichier | Ligne | Utilisation | Statut |
|---|---|---|---|
| — | — | **Aucune** comparaison directe `tier === "premium"` pour l'accès | 🟢 OK |
| `pages/Subscription.jsx` | 148/238 | `PREMIUM_TIERS.has(currentTier)` inclut `"premium"` ; `isInTrial = currentTier === "trial"` | 🟡 INFORMATIONNEL — page de tarifs, affichage du plan courant uniquement |
| `pages/Subscription.jsx` | 558/560 | `disabled={currentTier === "free"}` + libellé | 🟡 INFORMATIONNEL — état d'un bouton sur la page tarifs |

---

## F. Autres anciennes logiques (early_adopter / starter / confort / pro / active)

| Fichier | Ligne | Utilisation | Statut |
|---|---|---|---|
| `context/SubscriptionContext.jsx` | 67, 85 | `isEarlyAdopter = status === "early_adopter"` (exporté) | ⚠️ À MODIFIER / legacy — utilisé seulement pour un **badge d'affichage** dans Settings |
| `pages/Settings.jsx` | 45,743-832 | `isEarlyAdopter`, `isTrial` → **affichage** (Crown, badge, prix) | 🟡 INFORMATIONNEL |
| `pages/Settings.jsx` | 85-86,154,165-173 | Flux de **paiement Stripe "early_adopter"** (checkout, callback `early_adopter_success`) | 🔴 OBSOLÈTE pour Paddle — logique d'achat Stripe à remplacer |
| `pages/Subscription.jsx` | 146-148 | `PREMIUM_TIERS = {premium, starter, confort, pro, early_adopter}` (commenté "backward compatibility") | ⚠️ À ISOLER en compat legacy — utilisé pour l'affichage "plan premium ?" sur la page tarifs |
| `pages/Subscription.jsx` | 186-187,200 | `axios.get(/subscription/status)` → `setCurrentTier(res.data.tier)` ; checkout | ⚠️/🔴 — lecture OK (aligné), mais le **checkout** est Stripe (à revoir Paddle) |
| `lib/i18n.js` | 416-441, 465, 894-943, 1307-1356 | Libellés `starter/confort/pro/earlyAdopter/subscriptionActivated/securePayment "Stripe"` | 🟡 INFORMATIONNEL — traductions ; mentionnent "Stripe" (à mettre à jour lors du passage Paddle) |
| `hooks/useSettings.js` | 58-82 | `usePremiumStatus()` appelle `GET /premium/status` (endpoint legacy) | ⚠️ À MODIFIER — hook défini mais **non consommé** (code mort potentiel) |
| `context/SubscriptionContext.jsx` | 117-133 | HOC `withSubscription` | 🔴 CODE MORT — importé/utilisé nulle part |

---

## G. `/api/user/features`

**Le frontend n'appelle JAMAIS `GET /api/user/features` et n'utilise JAMAIS `feature_access`.**

- Recherche exhaustive : les seules occurrences de "features" côté frontend sont des **tableaux marketing statiques** dans `Subscription.jsx` (`WHY_FEATURES`, `FREE_FEATURES`, `PREMIUM_FEATURES`) — sans rapport avec l'endpoint.
- À la place, la source d'accès effective est :
  - **`SubscriptionContext.jsx`** → `GET /subscription/info?language=…` (ligne 26). Fournit `subscription.status` (free/trial/premium) et `subscription.features` (`training_plan`, `plan_adaptation`, `session_analysis`, `sync_enabled`, `llm_access`, `full_access`).
  - Expose : `isFree/isTrial/isPremium/isEarlyAdopter`, `hasFeature(f)`, `canAccessPlan`, `canAccessCoach`, `canSync`, `trialDaysRemaining`, labels d'affichage.
  - **`useSubscriptionStatus()`** (`hooks/useSettings.js:32`) et `ChatCoach`/`Subscription` → `GET /subscription/status` (tier + quota chat).

**Où c'est réellement utilisé pour l'accès :**
- `TrainingPlan.jsx:259` : `if (isFree || apiError === "subscription_required") return <Paywall/>`.
- `Progress.jsx:142` : `if (isFree) return <Paywall/>`.
- `ChatCoach` : quota (`messages_remaining`, `is_unlimited`, `messages_limit`) **fourni par le backend** ; `canSendMessages = messages_remaining > 0`.

> ⚠️ Point important : `hasFeature()` lit `subscription.features` (de `/subscription/info`), qui a **les mêmes noms** que `feature_access` mais provient d'un **autre endpoint**. Il y a donc **3 endpoints qui se recouvrent** (`/subscription/info`, `/subscription/status`, `/api/user/features`). Le frontend en utilise 2, jamais le canonique.

---

## H. PROBLÈMES

### 🔴 CRITIQUE
- *(sécurité)* **Aucun** trouvé. Aucune donnée de permission n'est stockée en local (voir §I), et le backend reste l'autorité (403/401). Les paywalls frontend sont purement visuels.

### 🟠 IMPORTANT
1. **`feature_access` / `/api/user/features` non utilisés** : le frontend n'utilise pas la source canonique voulue. Il dépend de `/subscription/info` + `/subscription/status` (fonctionnels mais redondants). Risque de dérive si ces endpoints divergent d'`access_control`.
2. **Flux de paiement Stripe "early_adopter"** (`Settings.jsx`, `Subscription.jsx`) : logique d'achat legacy à remplacer pour Paddle (checkout + callbacks).
3. **Fallback fail-open** (`SubscriptionContext.jsx:33-49`) : en cas d'erreur `/subscription/info`, le contexte force `status:"trial"` + toutes les features `true`. Côté **affichage** l'utilisateur pourrait voir des zones "débloquées" à tort — mais le backend bloque réellement (403). À corriger par cohérence (fail-closed ou état "inconnu").

### 🟡 MINEUR
4. **Code mort** : `withSubscription` (HOC), `PremiumBadge`/`PremiumUpgradeCard`, `usePremiumStatus()` (→ `/premium/status`) — non consommés. À supprimer ou isoler.
5. **Tiers legacy d'affichage** : `PREMIUM_TIERS {starter,confort,pro,early_adopter}` + libellés i18n (`starter/confort/pro`) + mentions "Stripe". Purement cosmétiques mais à nettoyer/renommer pour le modèle FREE/TRIAL/PREMIUM + Paddle.

### 🟢 OK
6. **localStorage** : uniquement `access_token` (JWT). Aucune permission locale.
7. **Routes** : toutes sous `ProtectedRoute` (auth). Gating premium par page (Paywall) — UX only, backend autoritaire.
8. Aucune comparaison `subscription === "active"` / `tier === "pro"` / `tier === "premium"` **pour décider d'un accès**.

---

## I. localStorage / sessionStorage

| Clé | Fichier | Usage | Statut |
|---|---|---|---|
| `access_token` | `index.js:16`, `AuthContext` | JWT injecté dans l'en-tête `Authorization` | 🟢 OK |
| *(rien d'autre)* | — | **Aucun** `isPremium`/`subscription`/`tier`/`plan` en local/session storage | 🟢 OK — **pas de faille** : les droits ne sont jamais décidés côté client à partir d'une valeur locale modifiable |

---

## J. CORRECTIONS RECOMMANDÉES (à faire APRÈS l'audit — non appliquées)

| # | Fichier | Ligne | Ancienne logique | Nouvelle logique recommandée |
|---|---|---|---|---|
| 1 | `context/SubscriptionContext.jsx` | 26 | `GET /subscription/info` | Migrer vers `GET /api/user/features` (source canonique) → exposer `plan` + `feature_access` |
| 2 | `context/SubscriptionContext.jsx` | 71-92 | `hasFeature(f)` lit `subscription.features` | `hasFeature(f)` lit `feature_access[f]` de `/api/user/features` (noms alignés : `training_plan`, `plan_adaptation`, `session_analysis`, `sync_enabled`, `llm_access`, `full_access`, `rag_access`, …) |
| 3 | `pages/TrainingPlan.jsx` | 259 | `if (isFree) → Paywall` | `if (!hasFeature("training_plan")) → Paywall` (permission, pas statut) |
| 4 | `pages/Progress.jsx` | 142 | `if (isFree) → Paywall` | `if (!hasFeature("full_access"/"race_predictions")) → Paywall` |
| 5 | `context/SubscriptionContext.jsx` | 33-49 | fallback fail-open (`trial` + toutes features `true`) | fail-closed : ne rien débloquer sur erreur (état "inconnu") |
| 6 | `components/ChatCoach.jsx` | 163,177 | `isPremium = tier !== "free"` pour un badge | garder pour l'**affichage** uniquement (déjà informationnel) ; le quota reste 100% backend (déjà le cas) |
| 7 | `pages/Settings.jsx` / `pages/Subscription.jsx` | 85-173 / 186-200 | checkout Stripe `early_adopter` | remplacer par le checkout **Paddle** (intégration Paddle) |
| 8 | `pages/Subscription.jsx` | 146-148 | `PREMIUM_TIERS {starter,confort,pro,early_adopter}` | réduire à `premium` (+ garder legacy isolé/commenté si abonnés existants) |
| 9 | divers | — | `withSubscription`, `PremiumBadge`, `PremiumUpgradeCard`, `usePremiumStatus` | supprimer (code mort) |

---

## VERDICT

**Le frontend est-il maintenant cohérent avec `access_control.py` ? → PARTIELLEMENT.**
- ✅ Aucune faille de sécurité : le backend reste l'autorité (401/403), rien en localStorage, pas de gating client à partir de valeurs falsifiables.
- ✅ Le gating d'accès est **fonctionnellement aligné** (il repose sur `/subscription/info`, lui-même branché sur `access_control`).
- ⚠️ Mais il **n'utilise pas** l'endpoint canonique `/api/user/features` ni `feature_access` ; il conserve des références legacy (early_adopter/starter/confort/pro), un fallback fail-open, et du code mort.

**Peut-on passer à l'intégration Paddle sans corriger le frontend ? → OUI (pour les permissions), avec une réserve.**
- Le gating d'accès continuera de fonctionner : dès que le backend marquera un utilisateur payé comme `status/tier = "premium"` (via `access_control`), les conditions génériques du frontend (`isFree`, `hasFeature`, `status === "premium"`) réagiront correctement. **Aucun correctif d'accès n'est bloquant pour Paddle.**
- **RÉSERVE (obligatoire dans le cadre de Paddle lui-même)** : le **frontend de PAIEMENT** est encore câblé sur **Stripe/early_adopter** (`Settings.jsx` lignes 85-173, `Subscription.jsx` lignes 186-200). Ces écrans **devront** être adaptés au checkout Paddle — non pas comme "correctif d'ancienne logique d'accès", mais comme partie intégrante de l'intégration Paddle.

**Corrections nécessaires AVANT Paddle (strict minimum) :**
1. Remplacer le checkout Stripe `early_adopter` par le checkout Paddle (`Settings.jsx`, `Subscription.jsx`) + callbacks de succès.
2. (Recommandé, non bloquant) Corriger le fallback fail-open de `SubscriptionContext` pour éviter d'afficher des features "débloquées" en cas d'erreur réseau.

**Non bloquant / à faire ensuite (nettoyage) :** migrer le contexte vers `/api/user/features`+`feature_access`, réduire les tiers legacy, supprimer le code mort.
