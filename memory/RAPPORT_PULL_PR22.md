# Rapport complet — Pull branche PR22 (état après PR #25)
_Date : 2026-07-28 — analyse en lecture seule. Seule modification hors-code : ajout de `JWT_SECRET_KEY` dans `backend/.env` (nécessaire au démarrage de l'auth)._

---

## 1. Ce qui a été récupéré
- **Dépôt / branche** : `geirb56/sauvegarde260708`, branche **PR22**.
- **Commit HEAD** : `72a77bb` — *Merge PR #25 : ÉTAPE 2/3 — complete multi-user isolation, JWT migration, trial subscription*.
- **Historique de la branche** (récent) :
  - PR #23 : audit de sécurité (`AUDIT_SECURITE.md`).
  - PR #24 (`8155aa1`) : module d'auth JWT (backend + frontend, login gate).
  - **PR #25 (`72a77bb`)** : migration multi-utilisateurs — JWT partout, isolation des données, trial auto.
- **Ampleur PR #25** vs PR #24 : **+210 / -213 lignes**, 20 fichiers (`server.py` +300/-, `auth/router.py`, `coach_service.py`, `terra_integration.py`, + pages/hooks frontend).

---

## 2. Architecture d'authentification (état actuel)
- **Backend `auth/`** : `models.py`, `password.py` (bcrypt), `jwt_utils.py` (JWT HS256, exp 60 min), `dependencies.py`, `router.py` (`/api/auth/register|login|me|logout|forgot-password|reset-password`).
- **`auth_user`** (`server.py:307`) : **exige un JWT valide** ; `sub` = UUID utilisateur. **Fallbacks legacy `X-User-Id` / `?user_id=` SUPPRIMÉS** → renvoie 401 si pas de JWT.
- **Trial auto** (`auth/router.py`) : à l'inscription, création d'un abonnement `trial` de **30 jours** pour le nouvel UUID.
- **Frontend** : `AuthContext` (token en `localStorage`), `App.js` gated (login obligatoire), `index.js` envoie `Authorization: Bearer <JWT>` (n'envoie **plus** `X-User-Id`), pages Login/Register/ForgotPassword/ResetPassword.
- **Config** : `JWT_SECRET_KEY` généré (aléatoire fort) et ajouté à `backend/.env`. Optionnels : `JWT_ALGORITHM` (HS256), `JWT_ACCESS_TOKEN_EXPIRE_MINUTES` (60).

---

## 3. Tests réalisés (via URL externe)
| Test | Résultat |
|---|---|
| Démarrage backend | ✅ OK (session Garmin retrouvée, index Mongo `users` créés) |
| `POST /api/auth/register` | ✅ 200 — `access_token` + `user` (UUID), **trial 30j auto-créé** |
| `POST /api/auth/login` / `GET /api/auth/me` | ✅ 200 |
| Écran `/login` (frontend) | ✅ rendu correct |
| `GET /api/subscription/info` (JWT) | ✅ `status: trial`, `user_id = <UUID>`, 29 jours (utilise bien le JWT) |
| Appel non authentifié `/api/workouts` | ✅ **403** (fallback supprimé) |
| `/api/workouts` avec `X-User-Id: default` | ✅ **401** (faille legacy fermée) |
| `GET /api/workouts` avec JWT valide (trial) | ❌ **403 `subscription_required`** (voir §4) |
| `GET /api/workouts?user_id=<UUID>` avec JWT | ✅ **200 `[]`** (prouve la cause racine) |

Comptes de test créés (jetables) : `isotest_*@runindex.app` / `Test1234!`.

---

## 4. ⚠️ Bug restant (dernier blocage du flux multi-utilisateurs)
**Le middleware d'abonnement n'utilise pas le JWT.**

- `subscription_middleware` (`server.py:397`) résout l'identité via `get_user_id_from_request` (`server.py:284`), qui lit dans l'ordre : **query param `user_id` → header `X-User-Id` → IP**. **Il ne décode jamais le JWT.**
- Le frontend n'envoyant plus que le `Bearer` JWT, le middleware tombe sur l'**adresse IP** → mauvais utilisateur → il **bloque en 403** toutes les **routes protégées** (`/workouts`, `/training/*`, `/coach/*`, `/rag/*`) pour un utilisateur pourtant en **trial**.

**Preuve reproductible :**
- `/api/workouts` (JWT seul) → **403**
- `/api/workouts?user_id=<UUID>` (même JWT) → **200 `[]`**

**Correctif upstream (un seul endroit) :** dans `get_user_id_from_request` (`server.py:284`), décoder le `Authorization: Bearer` JWT **en premier** (comme `auth_user`) et renvoyer `payload["sub"]` avant les fallbacks query/header/IP. Cela rend le middleware cohérent avec `auth_user`.

> Impact : tant que ce n'est pas corrigé, un utilisateur connecté (trial) ne peut pas accéder au cœur de l'app (séances, plan, coach). L'auth « marche » mais l'app protégée reste inaccessible.

---

## 5. Points hors périmètre de cette PR (rappel roadmap)
1. **Migration des données `default`** : les **141 activités Garmin**, l'historique RunIndex, le plan et l'abonnement restent sous `user_id="default"`. Un nouveau compte JWT démarre **vide** (dashboard sans données). Décision à prendre : réassigner `default → votre compte`, ou repartir de zéro.
2. **Garmin mono-compte (blocage n°1 inchangé)** : la synchro reste liée au **compte Garmin unique** du `.env` (`GARMIN_USERNAME`) et ingère sous `default`. Les nouveaux comptes n'auront **pas** de données Garmin → nécessite Garmin OAuth par utilisateur ou un agrégateur (Terra).
3. **Durcissement auth avant prod** : pas de **refresh token** (déconnexion à 60 min), **rate-limit** sur `/auth/login` à confirmer, **politique de mot de passe**, **email de reset** réel à brancher.

---

## 6. État global
- **Authentification JWT multi-utilisateurs** : ✅ implémentée, isolation d'identité en place, trial auto, sécurité legacy fermée.
- **Application protégée utilisable pour un compte connecté** : ❌ **non**, à cause du middleware non migré (§4) — **un seul correctif restant**.
- **Données historiques** : intactes sous `default`, non migrées, invisibles pour les nouveaux comptes.
- **Garmin multi-utilisateurs** : non résolu (blocage n°1).

---

## 7. Prochaines étapes recommandées (ordre)
1. **Corriger le middleware** (§4) — dernier blocage pour que les routes protégées marchent en JWT.
2. **Décider de la migration** des données `default` (réassignation vers votre compte, ou départ à zéro).
3. **Garmin par utilisateur** (OAuth officiel ou Terra).
4. **Durcir l'auth** (refresh token, rate-limit login, politique mot de passe, email reset réel).
5. Une fois validé : **déploiement P0** (secrets hors `.env`, MongoDB Atlas + Redis managés).
