# Rapport complet — Pull branche PR22 (état après PR #34 : migration Stripe→Paddle)
_Date : 2026-07-29 — audit en lecture seule. Modifs appliquées : `JWT_SECRET_KEY` (déjà présent) + correctif du plugin babel local nécessaire au build (voir §4)._

---

## 1. Ce qui a été récupéré
- **Branche PR22**, HEAD `a6034ba` — *Merge PR #34 : migrate Stripe→Paddle + security hardening*.
- Nouveaux commits depuis `74ed67c` : audit Paddle (`6908e3f`, PR #33) + migration (`a2ffd47`, PR #34).
- **Ampleur** : +12 735 / −366 lignes, 12 fichiers (dont `yarn.lock` désormais versionné).

### Fichiers clés
| Fichier | Nature |
|---|---|
| `backend/server.py` | +523 — endpoints/config/webhook Paddle |
| `backend/services/paddle_webhook_security.py` | **nouveau** — vérif. signature webhook |
| `backend/tests/test_paddle_subscription.py` | **nouveau** (+545) |
| `frontend/package.json` | + `@paddle/paddle-js@^1.6.4` |
| `frontend/src/components/Paywall.jsx` | refonte bouton achat Paddle |
| `frontend/src/pages/Settings.jsx`, `Subscription.jsx`, `context/SubscriptionContext.jsx` | checkout Paddle |
| `AUDIT_STRIPE_TO_PADDLE.md` | doc |

---

## 2. Configuration Paddle (backend)
Variables lues avec **défauts vides** → backend démarre sans elles :
| Variable | Rôle | Où l'obtenir |
|---|---|---|
| `PADDLE_CLIENT_TOKEN` | token navigateur (`test_...`) | Developer Tools > Authentication |
| `PADDLE_API_KEY` | clé API serveur (secret) | Developer Tools > Authentication |
| `PADDLE_WEBHOOK_SECRET` | secret webhook (`pdl_ntfset_...`) | Developer Tools > Notifications |
| `PADDLE_PRICE_ID` | prix Premium 4,99 €/mois (`pri_...`) | Catalog > Products |
| `PADDLE_ENVIRONMENT` | `sandbox`/`production` (défaut sandbox) | — |

Endpoints : `POST /api/subscription/paddle/checkout`, `GET /api/subscription/paddle/config`, `POST /api/webhook/paddle`.

---

## 3. Tests réalisés (API + UI)
| Test | Résultat |
|---|---|
| Démarrage backend | ✅ OK |
| register / workouts / user/features (JWT) | ✅ trial, 200 |
| `/subscription/paddle/config` (sans clés) | ✅ `configured:false` |
| `/subscription/paddle/checkout` (sans clés) | ✅ 503 « Paddle not configured » |
| `/webhook/paddle` (sans secret) | ✅ rejeté |
| Frontend Dashboard + `/subscription` | ✅ rend (après §4), prix 4,99 € affiché |
| Syntaxe backend (AST) | ✅ OK |

---

## 4. ⚠️ Blocage rencontré et corrigé
- **Symptôme** : « Compiled with problems — Maximum call stack size exceeded » sur `Paywall.jsx` → app blanche.
- **Cause** : `Paywall.jsx:180` `PREMIUM_OFFER.features.map(...)` (`.map()` sur member-expression) → **récursion infinie** dans le plugin build local `frontend/plugins/visual-edits/babel-metadata-plugin.js` (`analyzeMemberExpression` ↔ `getArrayIterationContext` ↔ `analyzeIdentifier`, garde `skipArrayContext` non propagé).
- **Correctif (local, dans le plugin)** : `analyzeMemberExpression(…, opts={})` ne rappelle plus `getArrayIterationContext` si `opts.skipArrayContext` ; propagation du flag à `analyzeIdentifier`. Cache `.cache` purgé + restart → build OK.
- ⚠️ Plugin **versionné dans la branche** → correctif **écrasé au prochain pull**. Durable : committer le fix OU refactor `Paywall.jsx` (`const { features } = PREMIUM_OFFER;` puis `features.map`).

---

## 5. Ce qui fonctionne
- Auth JWT + `access_control.py` : inchangés, opérationnels.
- Structure Paddle (backend + frontend) : en place, **fail-safe** sans clés.
- Frontend : compile et rend (après §4).

## 6. Ce qui NE fonctionne pas encore
1. **Paddle non activé** (clés manquantes) → paiement de bout en bout **non testé**.
2. **Correctif plugin volatil** (§4) à pérenniser.
3. **141 activités `default`** non migrées → nouveaux comptes vides.
4. **Garmin mono-compte** (blocage n°1) inchangé.
5. **Durcissement auth** (refresh token, rate-limit, mot de passe, email reset).
6. **Nettoyage legacy Stripe** à faire une fois Paddle validé.

## 7. État global
- Auth + accès : ✅
- Structure Paddle : ✅ en place, non activée
- Frontend : ✅ compile (correctif plugin local, volatil)
- Paiement Paddle e2e : ⏳ non vérifié (clés requises)

## 8. Prochaines étapes
1. Fournir les **clés Paddle sandbox** → ajout `.env` + test checkout/webhook e2e.
2. Pérenniser le **correctif plugin** (commit ou refactor Paywall).
3. **Migration `default`** ; **Garmin par utilisateur** ; **durcissement auth** ; **déploiement P0**.
