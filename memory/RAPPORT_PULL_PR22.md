# Rapport complet — Pull branche PR22 (état après PR #32)
_Date : 2026-07-29 — analyse en lecture seule. Aucune modification de code applicatif lors de ce pull (le correctif frontend précédent a été intégré upstream). `JWT_SECRET_KEY` reste présent dans `backend/.env`._

---

## 1. Ce qui a été récupéré
- **Dépôt / branche** : `geirb56/sauvegarde260708`, branche **PR22**.
- **Commit HEAD** : `74ed67c` — *Merge PR #32 : correction système d'abonnement (access_control)*.
- **Historique récent de la branche** :
  - PR #24 — module d'auth JWT (login gate).
  - PR #25 — isolation multi-users + trial auto.
  - PR #26 — correctif middleware (identité via JWT).
  - PR #27 — audit Garmin multi-user (`AUDIT_GARMIN_STEP3.md`).
  - PR #29 — audit fonctionnalités RunIndex.
  - **PR #32 (`74ed67c`)** — intégration de `access_control.py` (source unique de vérité des accès).
- **Changements vs version locale précédente** :
  - **Nouveau** : `backend/access_control.py`.
  - **Modifiés** : `backend/server.py`, `backend/subscription_manager.py`.
  - Docs ajoutées (audits) ; `texte.txt` supprimé.
  - **Frontend : aucun changement** (mon correctif `Subscription.jsx` a été committé upstream).

---

## 2. Détail des changements backend
### 2.1 `access_control.py` (nouveau)
- **Source unique de vérité** pour toutes les décisions d'abonnement/feature.
- Tiers commerciaux : **FREE** (trial expiré / pas d'abo) · **TRIAL** (30 j, accès Premium complet) · **PREMIUM** (abo payant Paddle, ou Stripe legacy).
- API : `get_user_access(db, user_id) → UserAccess` ; `UserAccess.tier`, `.can(feature)`, `.is_unlimited_chat`, `.chat_monthly_quota`.
- **Garanties de sécurité** :
  - Erreur DB → **fail closed** (retourne FREE, aucun accès premium accordé).
  - `DEMO_MODE` + `ENVIRONMENT=production` → **RuntimeError à l'import** (garde-fou).
  - Toutes les décisions passent par `UserAccess.can()` (plus de conditions éparpillées).
  - Identité **toujours issue du JWT**, jamais de valeurs fournies par le frontend.

### 2.2 `server.py`
- Import et intégration d'`access_control` dans le **middleware d'abonnement** et l'endpoint **`/subscription/status`** (classification des routes + résolution du tier par utilisateur).
- **Nouvel endpoint `GET /api/user/features`** : renvoie le plan de l'utilisateur + les drapeaux d'accès par fonctionnalité (le frontend s'en sert pour verrouiller/afficher les features).

### 2.3 `subscription_manager.py`
- Ajustements alignés sur `access_control` (résolution/normalisation des tiers).

---

## 3. Configuration / synchro
- Synchro rsync dans `/app` en **préservant** : `.env`, `.git`, `.emergent`, session Garmin `.gccli_home`, binaire `gccli`, `node_modules`, `/app/memory`.
- `JWT_SECRET_KEY` toujours présent dans `backend/.env`.
- `yarn.lock` régénéré (absent de la branche) — aucune nouvelle dépendance.
- Contrôle syntaxique **AST OK** sur `access_control.py`, `server.py`, `subscription_manager.py`.
- Aucun problème de build frontend (frontend inchangé, `Subscription.jsx` déjà corrigé upstream).

---

## 4. Tests réalisés (API + UI, via URL externe)
| Test | Résultat |
|---|---|
| Démarrage backend | ✅ OK (session Garmin retrouvée, index Mongo créés) |
| `POST /api/auth/register` | ✅ 200 — token + UUID, trial 30 j auto |
| `GET /api/workouts` (JWT) | ✅ **200 `[]`** |
| `GET /api/subscription/status` (JWT) | ✅ `tier: trial`, `is_premium: true`, `messages_limit: 999`, expiry 2026-08-28 |
| `GET /api/user/features` (JWT, **nouveau**) | ✅ `plan: trial`, `trial_active: true`, `has_premium_access: true`, 29 j, `feature_access{ sync, race_predictions, llm, chat, rag, ... }` |
| Appel non authentifié `/api/workouts` | ✅ **401** |
| Écran `/login` (frontend) | ✅ rendu correct (build OK) |

Compte de test créé (jetable) : `pr32_*@runindex.app` / `Test1234!`.

---

## 5. Ce qui fonctionne
- **Authentification JWT multi-utilisateurs** : ✅ complète (register/login/me/reset), isolation, trial auto.
- **Gestion des accès centralisée** : ✅ `access_control.py` opérationnel (fail-closed, JWT-only).
- **Nouvel endpoint `/api/user/features`** : ✅ expose le plan + les drapeaux par feature pour piloter l'UI.
- **Routes protégées** : ✅ accessibles pour un compte connecté (trial).
- **Frontend** : ✅ compile et rend (login/register/dashboard).

---

## 6. Points non traités (rappel roadmap)
1. **Migration des données `default`** : les **141 activités Garmin**, l'historique RunIndex, le plan restent sous `user_id="default"`. Un nouveau compte JWT démarre **vide**. Décision à prendre : réassigner `default → votre compte`, ou repartir de zéro.
2. **Garmin mono-compte (blocage n°1 inchangé)** : la synchro reste liée au **compte Garmin unique** du `.env` (`GARMIN_USERNAME`), ingérée sous `default`. Les nouveaux comptes n'auront **pas** de données Garmin → nécessite Garmin OAuth par utilisateur ou un agrégateur (Terra). Le bouton « Connect Garmin » du dashboard doit être branché. La branche contient l'audit `AUDIT_GARMIN_STEP3.md`.
3. **Durcissement auth avant prod** : pas de **refresh token** (déconnexion à 60 min), **rate-limit** sur `/auth/login`, **politique de mot de passe**, **email de reset** réel à brancher.
4. **Paddle** : `access_control` mentionne Paddle comme provider PREMIUM cible, mais l'intégration paiement Paddle n'est pas confirmée branchée (Stripe legacy encore présent).

---

## 7. État global
- **Auth JWT + contrôle d'accès multi-utilisateurs** : ✅ opérationnels et vérifiés de bout en bout.
- **App utilisable pour un compte connecté** : ✅ oui.
- **Données historiques** : intactes sous `default`, **non migrées**, invisibles pour les nouveaux comptes.
- **Garmin multi-utilisateurs** : ❌ non résolu (blocage n°1).

---

## 8. Prochaines étapes recommandées (ordre)
1. **Décider de la migration** des données `default` (réassignation vers votre compte, ou départ à zéro).
2. **Garmin par utilisateur** (implémenter l'étape 3 de l'audit : OAuth officiel ou Terra) + brancher « Connect Garmin ».
3. **Durcir l'auth** (refresh token, rate-limit login, politique mot de passe, email reset réel).
4. **Confirmer/brancher Paddle** (remplacer/compléter Stripe legacy).
5. **Déploiement P0** (secrets hors `.env`, MongoDB Atlas + Redis managés, `deployment_agent`).
