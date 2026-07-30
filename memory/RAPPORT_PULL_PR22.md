# Rapport complet — Pull branche PR22 (état après PR #26)
_Date : 2026-07-28 — analyse en lecture seule. Modifications hors-code : ajout de `JWT_SECRET_KEY` dans `backend/.env` (nécessaire au démarrage) + correctif frontend d'1 fichier (voir §4)._

---

## 1. Ce qui a été récupéré
- **Dépôt / branche** : `geirb56/sauvegarde260708`, branche **PR22**.
- **Commit HEAD** : `987dc26` — *Merge PR #26 : fix middleware JWT*.
- **Historique récent de la branche** :
  - PR #23 — audit de sécurité (`AUDIT_SECURITE.md`).
  - PR #24 (`8155aa1`) — module d'auth JWT (backend + frontend, login gate).
  - PR #25 (`72a77bb`) — « ÉTAPE 2/3 » : isolation multi-users, JWT sur endpoints, trial auto.
  - **PR #26 (`987dc26`)** — correctif du middleware d'abonnement (identité via JWT).
- **Ampleur PR #26** : `backend/server.py` uniquement, **+21 / -7 lignes**.

---

## 2. État de l'architecture multi-utilisateurs
- **Auth backend** (`backend/auth/`) : bcrypt, JWT HS256 (exp 60 min), endpoints `/api/auth/register|login|me|logout|forgot-password|reset-password`.
- **`auth_user`** : exige un JWT valide (`sub` = UUID). Fallbacks legacy `X-User-Id`/`?user_id=` **supprimés** → 401 sans JWT.
- **Trial auto** : abonnement `trial` 30 jours créé à l'inscription pour chaque nouvel UUID.
- **Middleware d'abonnement** (correctif PR #26) : `get_user_id_from_request` décode désormais le **JWT en premier** (ordre : JWT `sub` → header `X-User-Id` → IP), cohérent avec `auth_user`. C'était le dernier blocage des routes protégées.
- **Frontend** : `AuthContext` (token `localStorage`), `App.js` gated (login obligatoire), interceptor axios envoie `Authorization: Bearer <JWT>`, pages Login/Register/ForgotPassword/ResetPassword.
- **Config** : `JWT_SECRET_KEY` généré (aléatoire fort) et présent dans `backend/.env`.

---

## 3. Tests réalisés (via URL externe + UI)
| Test | Résultat |
|---|---|
| Démarrage backend | ✅ OK (session Garmin retrouvée, index `users` créés) |
| `POST /api/auth/register` | ✅ 200 — token + UUID, trial 30j auto-créé |
| `POST /api/auth/login` / `GET /api/auth/me` | ✅ 200 |
| `GET /api/subscription/info` (JWT) | ✅ `trial`, `user_id = <UUID>`, 29 jours |
| `GET /api/workouts` (JWT valide) | ✅ **200 `[]`** (routes protégées débloquées) |
| `GET /api/training/today` (JWT) | ✅ 200 (réponse gracieuse) |
| `POST /api/chat/send` (JWT, trial) | ✅ réponse coach (chat illimité en trial) |
| Appel non authentifié `/api/workouts` | ✅ **403** |
| `X-User-Id: default` | ✅ **401** (faille legacy fermée) |
| Parcours UI : inscription → dashboard | ✅ redirection vers `/`, dashboard rendu |
| Nouveau compte = données isolées | ✅ RunIndex 0/1000, « Connect your Garmin », séance du jour |

Comptes de test créés (jetables) : `isofix_*`, `uifull_*@runindex.app` / `Test1234!`.

---

## 4. Problème rencontré et corrigé pendant ce pull
- **Build frontend cassé** : `frontend/src/pages/Subscription.jsx` contenait **2 chaînes non terminées** (guillemets fermants manquants) :
  - ligne 186 : `axios.get(API + "/subscription/status)` → doit être `"/subscription/status"`.
  - ligne 198 : `API + "/subscription/checkout/status/" + sessionId + "` → guillemet ouvrant orphelin à retirer.
  - Symptôme : « Compiled with problems / Unterminated string constant » → **application blanche** dans le navigateur.
  - **Ces erreurs sont présentes DANS la branche.**
- **Action** : corrigées en local. Scan automatique de tous les `.jsx/.js` du frontend → **aucun autre fichier affecté**.
- **Après correctif** : le frontend recompile, l'inscription mène au dashboard (voir §3).
- ⚠️ **À committer côté GitHub** (Save to Github) sinon ce correctif sera **écrasé au prochain pull**.

---

## 5. Ce qui fonctionne maintenant
- **Authentification JWT multi-utilisateurs** : ✅ complète (register/login/me/reset), isolation d'identité, trial auto, sécurité legacy fermée.
- **Routes protégées** : ✅ accessibles pour un compte connecté (le blocage middleware est résolu).
- **Parcours utilisateur complet** : ✅ inscription → dashboard isolé fonctionnel.
- **Frontend** : ✅ compile (après correctif §4).

---

## 6. Points non traités par PR22 (rappel roadmap)
1. **Migration des données `default`** : les **141 activités Garmin**, l'historique RunIndex, le plan et l'abonnement restent sous `user_id="default"`. Un nouveau compte JWT démarre **vide**. Décision à prendre : réassigner `default → votre compte`, ou repartir de zéro.
2. **Garmin mono-compte (blocage n°1 inchangé)** : la synchro reste liée au **compte Garmin unique** du `.env` (`GARMIN_USERNAME`), ingérée sous `default`. Les nouveaux comptes n'auront **pas** de données Garmin → nécessite Garmin OAuth par utilisateur ou un agrégateur (Terra). Le bouton « Connect Garmin » du dashboard doit être branché sur ce mécanisme.
3. **Durcissement auth avant prod** : pas de **refresh token** (déconnexion à 60 min), **rate-limit** sur `/auth/login` (anti brute-force) à confirmer, **politique de mot de passe**, **email de reset** réel à brancher.
4. **Résidus mineurs** : quelques valeurs par défaut `user_id="default"` subsistent dans des modèles de requête (`ChatRequest`, `ActivateSubscriptionRequest`) — sans impact fonctionnel observé, mais à nettoyer.

---

## 7. État global
- **Auth JWT multi-utilisateurs** : ✅ opérationnelle et vérifiée de bout en bout.
- **App utilisable pour un compte connecté** : ✅ oui (après correctif frontend §4).
- **Données historiques** : intactes sous `default`, **non migrées**, invisibles pour les nouveaux comptes.
- **Garmin multi-utilisateurs** : ❌ non résolu (blocage n°1).

---

## 8. Prochaines étapes recommandées (ordre)
1. **Committer le correctif `Subscription.jsx`** sur GitHub (Save to Github).
2. **Décider de la migration** des données `default` (réassignation vers votre compte, ou départ à zéro).
3. **Garmin par utilisateur** (OAuth officiel ou Terra) + brancher le bouton « Connect Garmin ».
4. **Durcir l'auth** (refresh token, rate-limit login, politique mot de passe, email reset réel).
5. **Déploiement P0** (secrets hors `.env`, MongoDB Atlas + Redis managés, `deployment_agent`).
