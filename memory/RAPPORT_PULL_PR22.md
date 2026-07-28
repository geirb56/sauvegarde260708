# Rapport complet — Pull branche PR22
_Date : 2026-07-28 — analyse en lecture seule, aucune fonctionnalité modifiée au-delà de la config JWT_SECRET_KEY nécessaire au démarrage._

---

## 1. Ce qui a été récupéré
- **Dépôt / branche** : `geirb56/sauvegarde260708`, branche **PR22**.
- **Commit HEAD** : `8155aa1` (2026-07-28 14:12) — *Merge PR #24 : implement authentication multi-users*.
- **Contenu principal** :
  - PR #23 : audit de sécurité (`AUDIT_SECURITE.md`, 537 lignes).
  - PR #24 : ajout d'une **authentification JWT multi-utilisateurs** (backend + frontend).
- **Ampleur du diff** vs version précédente (PR16Bis `25835ec`) : **+2600 / -303 lignes**, 35 fichiers.

---

## 2. Détail des changements

### 2.1 Backend — nouveau module `backend/auth/`
| Fichier | Rôle |
|---|---|
| `models.py` | Schémas Pydantic (User, register/login, reset password) |
| `password.py` | Hachage de mot de passe (bcrypt) |
| `jwt_utils.py` | Création/validation JWT (HS256, exp 60 min), tokens courts pour reset |
| `dependencies.py` | `get_current_user` (dépendance FastAPI) |
| `router.py` | Endpoints `/api/auth/*` : register, login, me, logout, forgot-password, reset-password (339 l.) |
| `tests/test_auth.py` | 488 lignes de tests |

### 2.2 Backend — `server.py` (+66 lignes)
- Import et montage du `auth_router` sous `/api/auth/*`.
- **`auth_user` réécrit** : valide le JWT en priorité (claim `sub` = UUID utilisateur). **Conserve** les fallbacks legacy `X-User-Id` et `?user_id=` (annoncés comme temporaires, à retirer en "Step 2"). Si rien : sentinelle `"unauthenticated"` (plus jamais `"default"`).
- Nouveaux index Mongo : collection `users` (`email` unique, `id` unique, `reset_password_token_hash`).
- Le correctif `training/today` (`(plan.get("plan") or {})`) est **présent upstream** (aligné avec le patch local précédent).

### 2.3 Frontend
- **Nouvelles pages** : `Login.jsx`, `Register.jsx`, `ForgotPassword.jsx`, `ResetPassword.jsx`.
- **`AuthContext.jsx`** : gère le token dans `localStorage`, expose `login/register/logout/refreshUser`, appelle `/auth/me` au démarrage.
- **`App.js`** : **gate d'authentification** — l'app entière exige d'être connecté ; routes `/login`, `/register`, etc.
- **`index.js`** : l'intercepteur axios envoie désormais `Authorization: Bearer <JWT>` sur les appels `/api` — **il n'envoie plus `X-User-Id`**.
- Ajustements dans la plupart des pages/hooks (Dashboard, Coach, Sessions, Settings, Progress, useWorkouts, useSettings…).

### 2.4 Docs
- Ajout `AUDIT_SECURITE.md` (racine).
- Suppression `memory/AUDIT_ROADMAP_DEPLOIEMENT_PADDLE_SCALE.md`.

---

## 3. Configuration effectuée pour le démarrage
- **`JWT_SECRET_KEY`** est **requis** (`get_secret(..., required=True)`). Il a été **généré (secret aléatoire fort) et ajouté à `backend/.env`**. Toutes les clés existantes ont été préservées.
- Variables optionnelles disponibles : `JWT_ALGORITHM` (défaut HS256), `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (défaut 60).
- Fichiers protégés préservés lors de la synchro : `.env`, `.git`, `.emergent`, session Garmin `.gccli_home`, binaire `gccli`, `node_modules`, `/app/memory`.
- `yarn.lock` régénéré (absent de la branche) — aucune nouvelle dépendance npm (l'auth front n'utilise qu'axios + localStorage).

---

## 4. Tests réalisés (via URL externe)
| Test | Résultat |
|---|---|
| Démarrage backend | ✅ OK (session Garmin retrouvée, index Mongo créés) |
| `POST /api/auth/register` | ✅ 200 — renvoie `access_token` + `user` (UUID généré) |
| `GET /api/auth/me` (Bearer) | ✅ 200 — profil utilisateur correct |
| `POST /api/auth/login` | ✅ 200 — token + user |
| Écran `/login` (frontend) | ✅ rendu correct (RunIndex, email/password, forgot, sign up) |
| `GET /api/workouts` avec JWT (nouvel user) | ⚠️ bloqué `subscription_required` / `free` |
| `GET /api/subscription/info` avec JWT | ⚠️ renvoie `user_id: default` (ignore le JWT) |
| `GET /api/workouts?user_id=default` (legacy) | ✅ 141 activités toujours présentes |

Compte de test créé : `testrunner@runindex.app` / `Test1234!` (consigné dans `test_credentials.md`).

---

## 5. Problèmes / limites identifiés (⚠️ IMPORTANT)
La branche indique elle-même **"Step 2 pending"** : la bascule multi-utilisateurs n'est **pas terminée**. Conséquences concrètes :

1. **Incohérence d'identité entre endpoints**
   - `/subscription/info`, `/subscription/checkout`, `/subscription/verify-checkout`, etc. ont encore la signature `user_id: str = "default"` → ils **ignorent le JWT** et répondent pour l'utilisateur `default`.
   - `/workouts`, `/training/*` passent par `auth_user` → ils utilisent bien l'**UUID réel** du JWT.
   - Résultat : un même utilisateur connecté est vu comme `default` par certains endpoints et comme son UUID par d'autres.

2. **Nouvel inscrit = expérience cassée**
   - Aucun **trial** n'est créé à l'inscription → `/workouts` et les features protégées renvoient `free` / `subscription_required`.
   - Dashboard vide (aucune donnée sous son UUID).

3. **Données historiques non migrées**
   - Les **141 activités Garmin**, l'historique RunIndex, le plan et l'abonnement trial restent sous `user_id="default"`.
   - Un nouveau compte ne les voit pas.

4. **Régression pour le propriétaire (vous)**
   - Le frontend n'envoie plus `X-User-Id=default` → via l'UI, **vous ne voyez plus vos 141 activités** tant qu'aucune migration `default → votre UUID` n'est faite.

5. **Garmin toujours mono-compte (blocage n°1 inchangé)**
   - La synchro reste liée au compte Garmin unique du `.env` (`GARMIN_USERNAME`) et ingère sous `default`. Les nouveaux comptes n'auront pas de données Garmin. PR22 ne résout pas ce point.

6. **Sécurité — points à vérifier avant prod** (issus de l'implémentation)
   - Robustesse du hachage bcrypt et politique de mot de passe (longueur, complexité).
   - Expiration JWT 60 min sans refresh token → déconnexions fréquentes (pas de rotation de token).
   - Flux reset password : envoi d'email réel non branché (à confirmer), gestion du `reset_password_token_hash`.
   - Rate-limiting sur `/auth/login` (anti brute-force) à confirmer.

---

## 6. État global
- **Authentification JWT** : ✅ fonctionnelle et testée (register/login/me + UI login).
- **Application multi-utilisateurs réellement utilisable** : ❌ **non** — migration Step 2 incomplète (identité, trial, données, Garmin).
- **Données existantes** : intactes sous `default`, mais **inaccessibles via l'UI** en l'état.

---

## 7. Recommandations / prochaines étapes
Pour rendre l'app multi-utilisateurs opérationnelle, il faut (par ordre) :
1. **Terminer le Step 2** : remplacer tous les `user_id="default"` par l'identité issue de `auth_user` (JWT) sur l'ensemble des endpoints (subscription, checkout, goal, chat, run-index, dashboard…).
2. **Créer un trial automatiquement à l'inscription** (ou au premier accès) pour chaque nouvel UUID.
3. **Migration des données** : décider du sort des données `default` (réassignation vers votre compte, ou archivage + départ à zéro).
4. **Garmin par utilisateur** (blocage n°1) : OAuth Garmin officiel ou agrégateur (Terra) — 1 token par utilisateur au lieu du compte global.
5. **Durcissement auth** : refresh token, rate-limit login, politique de mot de passe, email reset réel.
6. **Retirer les fallbacks legacy** `X-User-Id` / `?user_id=` une fois le Step 2 fini (sinon faille : n'importe qui peut se faire passer pour `default`).

> ⚠️ Point de sécurité : tant que le fallback `X-User-Id`/`?user_id=` reste actif, un appel non authentifié avec `X-User-Id: default` accède aux données `default`. À fermer avant toute mise en production.
