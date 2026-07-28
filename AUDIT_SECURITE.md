# 🔍 AUDIT SÉCURITÉ RUNINDEX

**Date :** 2026-07-28  
**Version auditée :** branche principale (main)  
**Périmètre :** Authentification, isolation multi-utilisateurs, sécurité API, Garmin, Stripe, CORS, variables d'environnement

---

## 1. AUTHENTIFICATION

**Résultat : Authentification inexistante.**

L'ensemble du code d'authentification est un **placeholder non implémenté**. Preuve directe dans `backend/server.py` lignes 319–326 :

```python
# 1. ****** (placeholder for JWT)
if credentials and credentials.credentials:
    token = credentials.credentials
    # TODO: Validate JWT and extract user_id
    # For now, use the token as user_id if not JWT
    if token.startswith("user_"):
        user_id = token
```

| Fonctionnalité | État |
|---|---|
| Inscription | ❌ Inexistante |
| Connexion (login) | ❌ Inexistante |
| Déconnexion (logout) | ❌ Inexistante |
| Email | ❌ Non géré |
| Mot de passe | ❌ Non implémenté |
| Hashage mot de passe | ❌ Pas de mot de passe |
| JWT | ❌ TODO dans le code |
| Expiration token | ❌ Aucun token |
| Refresh token | ❌ Aucun |
| Récupération mot de passe | ❌ Inexistante |
| Vérification email | ❌ Inexistante |
| Suppression de compte | ❌ Inexistante |

Il n'existe aucun endpoint `/auth/register`, `/auth/login`, `/auth/logout` dans tout le projet.

---

## 2. MODÈLE UTILISATEUR

**Résultat : Il n'existe pas de modèle User à proprement parler.**

Il n'y a pas de collection MongoDB `users`. L'identité d'un utilisateur est uniquement constituée d'un `user_id` (chaîne libre). Les données associées à un utilisateur sont éparpillées dans plusieurs collections :

| Collection | Champ d'association | État |
|---|---|---|
| `workouts` | `user_id` | ⚠️ Présent mais pas toujours filtré |
| `subscriptions` | `user_id` | ✅ Filtré |
| `conversations` | `user_id` | ✅ Filtré |
| `garmin_connections` | `user_id` | ✅ Filtré |
| `garmin_activities` | `user_id` | ✅ Filtré |
| `terra_tokens` | `user_id` | ✅ Filtré |
| `user_goals` | `user_id` | ✅ Filtré |
| `training_cycles` | `user_id` | ✅ Filtré |

**Champs "modèle utilisateur" attendus — manquants :**
- ❌ Pas de `email` stocké
- ❌ Pas de `password_hash`
- ❌ Pas de `created_at` utilisateur (seulement sur l'abonnement)
- ✅ `user_id` unique (chaîne UUID ou "default")
- ✅ Abonnement associé via `subscriptions.user_id`

---

## 3. ISOLATION DES UTILISATEURS — PRIORITÉ MAXIMALE

**Résultat : ISOLATION INEXISTANTE. C'est le problème central.**

### Problème racine — Le `user_id` est fourni par le client

Dans `backend/server.py`, la fonction `auth_user` retourne :

```python
return {"id": user_id, "authenticated": bool(credentials)}
```

Avec cette priorité :
1. ****** commençant par `"user_"` → utilisé tel quel sans vérification
2. Header `X-User-Id` → accepté sans vérification
3. Query param `?user_id=xxx` → accepté sans vérification
4. Fallback → `"default"`

**N'importe quel client peut fournir n'importe quel `user_id` et accéder aux données d'un autre utilisateur.**

### `USER_ID = "default"` codé en dur côté frontend

Dans `frontend/src/utils/constants.js` :
```javascript
export const USER_ID = "default";
```

Et dans `frontend/src/hooks/useSettings.js` :
```javascript
const res = await axios.get(`${API_BASE}/user/goal?user_id=default`);
```

Tous les utilisateurs partagent le même identifiant "default" → ils voient tous les mêmes données.

### Endpoints qui exposent les données de TOUS les utilisateurs simultanément

| Endpoint | Requête MongoDB | Problème |
|---|---|---|
| `GET /api/stats` | `db.workouts.find({})` | Retourne les stats de TOUS les utilisateurs mélangées |
| `POST /api/coach/guidance` | `db.workouts.find({})` | Analyse les données de TOUS les utilisateurs |
| `GET /api/coach/digest` | `db.workouts.find({})` | Bilan de TOUS les utilisateurs |
| `GET /api/rag/dashboard` | `db.workouts.find({})` | Dashboard toutes données confondues |
| `GET /api/rag/weekly-review` | `db.workouts.find({})` | Revue toutes données confondues |
| `GET /api/coach/workout-analysis/{id}` | `db.workouts.find({})` | Analyse sur contexte global |
| `GET /api/coach/detailed-analysis/{id}` | `db.workouts.find({})` | Analyse sur contexte global |
| `GET /api/messages` | `db.conversations.find({})` | TOUS les messages de TOUS les utilisateurs |
| `GET /api/training/race-predictions` | `db.workouts.find({...})` | Prédictions sans filtre user |
| `GET /api/training/vma-history` | `db.workouts.find({...})` | Historique sans filtre user |
| `GET /api/user/vma-estimate` | `db.workouts.find({"type": "run"})` | Sans filtre user |

### IDOR — Accès à un workout par ID sans vérification de propriété

Exemple : `GET /api/rag/workout/{workout_id}` (`server.py` ligne 2223) :
```python
workout = await db.workouts.find_one({"id": workout_id}, {"_id": 0})
```
**Aucune vérification que le workout appartient à l'utilisateur connecté.**

---

## 4. AUTORISATION

### Tableau des endpoints

| Méthode | Route | Public/Protégé | Identification | Contrôle d'accès | Risque |
|---|---|---|---|---|---|
| GET | `/api/workouts` | Protégé (subscription) | `?user_id=` | user_id client | 🔴 IDOR total |
| GET | `/api/workouts/{id}` | Protégé (subscription) | `?user_id=` | user_id client | 🔴 IDOR |
| POST | `/api/workouts` | Protégé (subscription) | `?user_id=` | user_id client | 🔴 Injection cross-user |
| GET | `/api/stats` | Semi-protégé | Aucune | Aucun | 🔴 Données globales |
| GET | `/api/dashboard/insight` | Public | `?user_id=` | user_id client | 🟠 IDOR |
| GET | `/api/coach/digest` | Semi-protégé | `?user_id=` | Aucun filtre | 🔴 Données globales |
| GET | `/api/coach/workout-analysis/{id}` | Protégé | `?user_id=` | Aucune ownership | 🔴 IDOR |
| GET | `/api/training/plan` | Protégé | `auth_user` (header) | Pas de JWT réel | 🔴 Spoofable |
| POST | `/api/training/set-goal` | Protégé | `auth_user` | Pas de JWT réel | 🔴 Spoofable |
| GET | `/api/training/race-predictions` | Protégé | `auth_user` | Requête sans user filter | 🔴 Données globales |
| GET | `/api/subscription/status` | Public | `?user_id=` | user_id client | 🟠 Énumération |
| POST | `/api/subscription/activate-early-adopter` | Public | body `user_id` | **Aucun** | 🔴 Activation gratuite |
| POST | `/api/subscription/cancel` | Public | `?user_id=` | user_id client | 🔴 Cancellation tierce |
| POST | `/api/subscription/simulate-trial-end` | Public | `?user_id=` | **Aucun** | 🔴 Manipulation |
| POST | `/api/subscription/reset-to-trial` | Public | `?user_id=` | **Aucun** | 🔴 Manipulation |
| GET | `/api/subscription/verify-checkout/{id}` | Public | `?user_id=` | Activation sans Stripe | 🔴 Fraude |
| DELETE | `/api/cache/clear` | Public | Aucune | **Aucun** | 🟠 DoS |
| GET | `/api/metrics` | Public | Aucune | **Aucun** | 🟡 Info disclosure |
| GET | `/api/garmin/*` | Public | `?user_id=` | user_id client | 🔴 IDOR |
| POST | `/api/webhook/stripe` | Public | Signature Stripe | ✅ HMAC vérifié | 🟢 OK |
| GET | `/api/run-index/history` | Semi-protégé | `auth_user` | Pas de JWT réel | 🔴 Spoofable |

---

## 5. MOTS DE PASSE

**Résultat : Il n'y a pas de système de mots de passe.**

Il n'existe aucun endpoint d'inscription, aucun champ `password` dans aucune collection MongoDB, aucune bibliothèque de hashage (bcrypt, Argon2) dans les requirements. Ce n'est pas un "problème de hashage" — c'est l'absence totale d'un système d'authentification par identifiants.

---

## 6. JWT / TOKENS / SESSIONS

**Résultat : Aucun JWT implémenté.**

Le code `server.py` contient explicitement :
```python
# TODO: Validate JWT and extract user_id
# For now, use the token as user_id if not JWT
if token.startswith("user_"):
    user_id = token
```

Un attaquant peut envoyer le header `Authorization: ****** pour se faire passer pour l'utilisateur `user_alice`.

| Critère | État |
|---|---|
| Algorithme JWT | ❌ Non implémenté |
| SECRET_KEY | ❌ N/A (pas de JWT) |
| Expiration token | ❌ N/A |
| Validation signature | ❌ N/A |
| Refresh token | ❌ N/A |
| Stockage frontend | Non applicable (pas de token réel) |
| Risque XSS/vol session | Non applicable |

---

## 7. FRONTEND REACT

**Résultat : Aucun système d'authentification.**

L'application React (`App.js`) :
- ❌ Aucun `AuthContext`
- ❌ Aucune page de login
- ❌ Aucune route protégée
- ❌ Aucune redirection vers un login
- ❌ Aucun intercepteur Axios pour les 401
- ❌ `USER_ID = "default"` codé en dur dans `constants.js`

Toutes les pages sont accessibles directement sans authentification. `useSettings.js` utilise systématiquement `user_id=default` hardcodé.

---

## 8. GARMIN

**Résultat : Architecture problématique pour le multi-utilisateurs.**

La connexion Garmin (via `gccli`) utilise un seul couple `GARMIN_USERNAME` / `GARMIN_PASSWORD` au niveau du **serveur** (bootstrap au démarrage). Ce n'est pas une intégration OAuth multi-utilisateurs — c'est une connexion backend unique partagée.

Dans `backend/garmin/providers/gccli_provider.py` :
```python
return get_secret("GARMIN_USERNAME")
password = get_secret("GARMIN_PASSWORD")
```

Ce design signifie que :
- Tous les utilisateurs partagent le **même compte Garmin** côté backend
- `user_id` permet de distinguer les données stockées en MongoDB, mais les activités Garmin récupérées appartiennent toutes au même compte Garmin physique
- Il n'y a **pas d'isolation Garmin A → Données A / Garmin B → Données B**

De plus, les endpoints Garmin acceptent `user_id` comme query parameter non vérifié :
- `GET /api/garmin/activities?user_id=X` → accès aux activités de l'utilisateur X
- `POST /api/garmin/connect?user_id=X` → connecte Garmin pour X sans être X
- `POST /api/garmin/disconnect?user_id=X` → déconnecte X sans être X

---

## 9. OPENAI / IA

**Résultat : Isolation partielle, plusieurs fuites.**

La plupart des analyses IA utilisent la requête MongoDB `db.workouts.find({})` sans filtre par utilisateur :

- `POST /api/coach/analyze` : le contexte peut inclure des workouts d'autres utilisateurs qui n'ont pas de `user_id` défini.
- `GET /api/rag/workout/{workout_id}` : `all_workouts = db.workouts.find({})` → le contexte comparatif envoyé à l'IA inclut les données de tous les utilisateurs.
- `GET /api/coach/workout-analysis/{workout_id}` : idem.
- Le modèle `CoachRequest` contient un champ `user_id: Optional[str] = "default"` fourni par le frontend — le client contrôle quel utilisateur est "coaché".

---

## 10. STRIPE / ABONNEMENTS

**Résultat : Le webhook Stripe est sécurisé. La gestion abonnement ne l'est pas.**

| Aspect | État |
|---|---|
| Signature webhook HMAC-SHA256 | ✅ Correctement implémentée |
| `STRIPE_WEBHOOK_SECRET` en env var | ✅ Correct |
| Vérification horodatage (tolerance 300s) | ✅ Correct |
| Association Stripe → user_id | ⚠️ Via metadata non vérifiée |
| `POST /api/subscription/activate-early-adopter` | 🔴 Public, aucune auth |
| `POST /api/subscription/cancel` | 🔴 Public, aucune auth |
| `GET /api/subscription/verify-checkout/{session}` | 🔴 Active l'abonnement sans appel Stripe réel |
| `POST /api/subscription/simulate-trial-end` | 🔴 Exposé en production (aucune protection) |
| `POST /api/subscription/reset-to-trial` | 🔴 Exposé en production |

L'endpoint `verify-checkout` (ligne 5595) active directement l'abonnement `early_adopter` pour n'importe quelle session enregistrée :
```python
if transaction.get("plan") == "early_adopter":
    await activate_early_adopter(db, user_id, ...)
```
**N'importe qui peut appeler cet endpoint avec son `user_id` et obtenir un abonnement payant gratuitement.**

---

## 11. CORS / PRODUCTION

**Résultat : Configuration CORS correcte en production.**

```python
if ENVIRONMENT == "production":
    return [FRONTEND_URL.rstrip("/")]
```

En production (`ENVIRONMENT=production`), seul `FRONTEND_URL` est autorisé. ✅  
En développement, localhost:3000 est ajouté. ✅  
`allow_credentials=True` est correct avec une origine spécifique. ✅

---

## 12. VARIABLES D'ENVIRONNEMENT

| Variable | Obligatoire prod | Usage |
|---|---|---|
| `MONGO_URL` | ✅ Obligatoire | Connexion MongoDB |
| `DB_NAME` | ✅ Obligatoire | Nom de la base de données |
| `ENVIRONMENT` | ✅ Obligatoire | `"production"` ou `"development"` |
| `FRONTEND_URL` | ✅ Obligatoire | CORS + redirections Stripe |
| `STRIPE_API_KEY` | ✅ Obligatoire (paiements) | Clé API Stripe |
| `STRIPE_WEBHOOK_SECRET` | ✅ Obligatoire (paiements) | Vérification webhooks Stripe |
| `GARMIN_USERNAME` | ✅ Obligatoire si Garmin | Identifiant Garmin Connect |
| `GARMIN_PASSWORD` | ✅ Obligatoire si Garmin | Mot de passe Garmin Connect |
| `GARMIN_PROVIDER` | ⚠️ Optionnel | `"gccli"` par défaut |
| `REDIS_URL` | ✅ Obligatoire | Queue de synchronisation |
| `REACT_APP_BACKEND_URL` | ✅ Obligatoire (frontend) | URL du backend FastAPI |
| `DEMO_MODE` | ⚠️ Optionnel | `"false"` impératif en prod |
| `CORS_ORIGINS` | ⚠️ Optionnel | Origines supplémentaires (dev) |
| `GARMIN_PAGE_SIZE` | ⚠️ Optionnel | Taille page sync |
| `GARMIN_DEEP_SYNC_ENABLED` | ⚠️ Optionnel | `"true"` par défaut |
| `TERRA_API_BASE_URL` | ⚠️ Optionnel | URL API Terra |

**Constats :**
- Aucune variable n'est hardcodée dans le code source ✅
- Il manque une variable `JWT_SECRET_KEY` (JWT non implémenté)
- Il manque des variables pour un service mail (email non implémenté)

---

## 13. TESTS

| Domaine | Fichiers existants | Couverture sécurité |
|---|---|---|
| Abonnement | `test_subscription.py`, `test_subscription_chat.py`, `test_subscription_trial.py` | Fonctionnel, pas d'isolation |
| Webhook Stripe | `test_stripe_webhook_security.py` | ✅ Bon |
| Demo mode | `test_demo_mode_security.py` | ✅ Vérifie prod guard |
| Garmin | `test_garmin_deep_sync.py` | Fonctionnel |
| Secrets | `test_secrets.py` | ✅ Bon |
| Coach | `test_coach_conversational.py` | Fonctionnel |
| Run Index | `test_run_index_engine.py`, `test_run_index_screen.py` | Fonctionnel |

**Ce qui manque totalement :**
- ❌ Aucun test d'authentification (login/logout)
- ❌ Aucun test d'isolation inter-utilisateurs (utilisateur A vs B)
- ❌ Aucun test d'accès non autorisé (HTTP 401/403)
- ❌ Aucun test IDOR
- ❌ Aucun test de manipulation d'abonnement sans paiement
- ❌ Aucun test d'endpoint DEV exposé en production

**Les tests existants sont insuffisants pour une mise en production.**

---

## 14. AUDIT DES VULNÉRABILITÉS

### 🔴 CRITIQUE

| # | Vulnérabilité | Localisation |
|---|---|---|
| C1 | **Absence totale d'authentification** — Aucun login/mot de passe/JWT | `server.py:303–339` |
| C2 | **user_id client-contrôlé** — N'importe qui peut se faire passer pour un autre utilisateur | Tous les endpoints |
| C3 | **USER_ID="default" hardcodé frontend** — Tous les utilisateurs partagent les mêmes données | `constants.js:4` |
| C4 | **Broken Access Control — données globales** — Stats, digest, analyses, IA sans filtre user | `server.py:1369, 1802, 2034, 2148...` |
| C5 | **IDOR workout** — Accès à n'importe quel workout par ID sans vérification ownership | `server.py:2219, 2381, 2465` |
| C6 | **Activation abonnement sans paiement** — `verify-checkout` active early_adopter sans vérification Stripe | `server.py:5571` |
| C7 | **Manipulation abonnement unauthenticated** — `activate-early-adopter` et `cancel` publics | `server.py:5295, 5318` |
| C8 | **Endpoints dev exposés en production** — `simulate-trial-end`, `reset-to-trial` | `server.py:5333, 5354` |
| C9 | **Garmin mono-compte** — GARMIN_USERNAME/PASSWORD unique partagé par tous les utilisateurs | `garmin/providers/gccli_provider.py` |
| C10 | **Spoofing ****** — `Authorization: ****** accepté sans validation | `server.py:324–326` |

### 🟠 IMPORTANT

| # | Vulnérabilité | Localisation |
|---|---|---|
| I1 | **stripe_customer_id retourné au frontend** — Exposition de l'identifiant client Stripe | `server.py:5282–5292` |
| I2 | **`/api/messages` sans filtre** — Retourne toutes les conversations | `server.py:1787–1791` |
| I3 | **Rate limiter basé sur user_id client** — Facilement contournable | `server.py:280–296` |
| I4 | **CoachRequest.user_id client-contrôlé** — Le client choisit quel utilisateur est analysé | `server.py:512, 1480` |
| I5 | **Endpoints admin non protégés** — `/cache/clear`, `/metrics/reset` accessibles sans auth | `server.py:5223–5245` |

### 🟡 AMÉLIORATION

| # | | Localisation |
|---|---|---|
| A1 | Logger `user_id` dans les logs pourrait fuiter dans des systèmes de monitoring tiers | `server.py` |
| A2 | La politique CORS est correcte mais `allow_methods=["*"]` pourrait être restreint | `server.py:5636` |
| A3 | Aucun en-tête HTTP de sécurité (HSTS, X-Frame-Options, etc.) | Manquant |
| A4 | `WorkoutCreate.notes` est sanitisé ✅ mais d'autres champs texte libres ne le sont pas | `server.py:490–495` |

### 🟢 CORRECTEMENT IMPLÉMENTÉ

| # | |
|---|---|
| OK1 | Signature webhook Stripe vérifiée (HMAC-SHA256 + horodatage) |
| OK2 | Aucune valeur secrète hardcodée dans le code |
| OK3 | CORS restrictif en production |
| OK4 | `DEMO_MODE=true` bloqué en production (`validate_demo_mode_safety()`) |
| OK5 | Validation des données d'entrée via Pydantic |
| OK6 | Sanitisation HTML dans les notes workouts |
| OK7 | Index MongoDB créés correctement |
| OK8 | La bibliothèque `secrets` Python utilisée pour la génération d'identifiants |
| OK9 | Tokens Garmin jamais exposés au frontend |
| OK10 | Middleware de rate limiting en place |

---

## 15. RAPPORT FINAL

### A. NOTE DE PRÉPARATION PRODUCTION

**Note globale sécurité / gestion multi-utilisateurs : 1.5 / 10**

Cette note reflète l'état actuel pré-authentification. L'infrastructure, les webhooks Stripe et le CORS sont bien conçus, mais l'absence d'authentification et d'isolation utilisateur rend l'application non déployable pour plusieurs utilisateurs.

---

### B. CE QUI EST DÉJÀ CORRECT

- ✅ Vérification de signature webhook Stripe (HMAC-SHA256 avec tolérance temporelle)
- ✅ Aucun secret hardcodé dans le code source
- ✅ CORS correctement restreint en production à `FRONTEND_URL` uniquement
- ✅ Guard `DEMO_MODE=true` interdit en production
- ✅ Validation des entrées avec Pydantic (types, longueurs, caractères)
- ✅ Sanitisation HTML dans les champs notes
- ✅ Tokens Garmin jamais exposés au frontend
- ✅ Rate limiter en place
- ✅ Index MongoDB créés au démarrage
- ✅ Architecture de secrets centralisée (`config/secrets.py`)

---

### C. 🔴 BLOQUANTS PRODUCTION

1. **Absence totale d'authentification** — Il n'existe pas de login/inscription/JWT. Impossible de déployer pour plusieurs utilisateurs.
2. **`USER_ID = "default"` hardcodé dans le frontend** — Tous les utilisateurs voient les mêmes données.
3. **user_id fourni par le client sans vérification** — Broken Access Control complet sur tous les endpoints.
4. **Requêtes MongoDB sans filtre utilisateur** (stats, digest, guidance, rag, analyses) — Les données de tous les utilisateurs sont mélangées.
5. **Endpoint `verify-checkout` active un abonnement payant sans appel Stripe réel** — Fraude possible.
6. **Endpoints dev exposés en production** (`simulate-trial-end`, `reset-to-trial`) — Manipulation d'abonnement.
7. **Activation d'abonnement sans authentification** — `activate-early-adopter` et `cancel` accessibles à tous.
8. **Architecture Garmin mono-compte** — Incompatible avec le multi-utilisateurs.

---

### D. 🟠 PROBLÈMES IMPORTANTS

1. `stripe_customer_id` retourné au frontend dans `/api/subscription/info`
2. `/api/messages` retourne les messages de tous les utilisateurs sans filtre
3. `CoachRequest.user_id` est client-contrôlé — permet à un utilisateur de faire analyser les données d'un autre
4. Endpoints d'administration (`/cache/clear`, `/metrics/reset`) sans protection
5. Rate limiter contournable par cycling de `user_id`
6. IDOR sur `workout_id`, `analysis_id`, etc. : aucune vérification de propriété

---

### E. 🟡 AMÉLIORATIONS

1. Ajouter des en-têtes HTTP de sécurité (HSTS, X-Content-Type-Options, X-Frame-Options)
2. Restreindre `allow_methods` CORS aux méthodes réellement utilisées
3. Limiter la verbosité des messages d'erreur (ne pas exposer les stack traces)
4. Logger les tentatives d'accès non autorisé
5. Ajouter une validation de longueur sur les autres champs texte libres

---

### F. ARCHITECTURE ACTUELLE

```
Utilisateur (navigateur)
        ↓
React SPA (sans auth, USER_ID="default")
        ↓  HTTP avec ?user_id=default (ou header X-User-Id)
FastAPI (auth_user = placeholder JWT non implémenté)
        ↓
MongoDB (collections: workouts, subscriptions, garmin_activities, terra_tokens...)
        ↓
Services externes:
  - OpenAI (analyses IA)
  - Stripe (paiements — webhook sécurisé ✅)
  - Garmin Connect (via gccli — mono-compte unique)
  - Terra API (intégration dormante)
  - Redis (queue de synchronisation)
```

**Architecture cible (multi-utilisateurs) :**

```
Utilisateur → React (AuthContext + token JWT)
           → FastAPI (valide JWT, extrait user_id certifié)
           → MongoDB (filtres user_id systématiques)
```

---

### G. VARIABLES PRODUCTION NÉCESSAIRES

```
# Obligatoires (existantes)
MONGO_URL
DB_NAME
ENVIRONMENT=production
FRONTEND_URL=https://runindex.app
STRIPE_API_KEY
STRIPE_WEBHOOK_SECRET
REDIS_URL
REACT_APP_BACKEND_URL=https://api.runindex.app

# À créer (inexistantes aujourd'hui — nécessaires pour l'auth)
JWT_SECRET_KEY
JWT_ALGORITHM
JWT_ACCESS_TOKEN_EXPIRE_MINUTES
MAIL_SERVER / SENDGRID_API_KEY   # pour vérification email

# Garmin (si intégration mono-compte maintenue)
GARMIN_USERNAME
GARMIN_PASSWORD

# Sécurité impérative
DEMO_MODE=false
```

---

### H. CHECKLIST DE CORRECTION (ordre exact)

| # | Priorité | Fichier(s) | Problème | Résultat attendu |
|---|---|---|---|---|
| 1 | 🔴 CRITIQUE | `server.py`, `frontend/src/` | Implémenter inscription/connexion (email + mot de passe haché bcrypt/Argon2) avec génération de JWT signé | Chaque utilisateur a une identité propre |
| 2 | 🔴 CRITIQUE | `server.py:303–339` | Remplacer le placeholder `auth_user` par une vraie validation JWT (vérification signature + expiration + extraction user_id) | user_id n'est plus client-contrôlé |
| 3 | 🔴 CRITIQUE | `frontend/src/utils/constants.js`, `useSettings.js`, tous les hooks | Supprimer `USER_ID = "default"`, remplacer par le user_id issu du token JWT | Chaque utilisateur voit ses propres données |
| 4 | 🔴 CRITIQUE | `server.py:1369, 1802, 2034, 2148, 2219, 3769, 4044` | Ajouter `{"user_id": current_user["id"]}` dans toutes les requêtes MongoDB qui ne filtrent pas par utilisateur | Isolation complète des données |
| 5 | 🔴 CRITIQUE | `server.py:2219, 2381, 2465, 677` | Vérifier la propriété du workout/activity avant de le retourner (`workout["user_id"] == current_user["id"]`) | Fin des IDOR |
| 6 | 🔴 CRITIQUE | `server.py:5571–5618` | Supprimer l'activation locale de `verify-checkout` — n'activer que via le webhook Stripe | Impossible d'obtenir un abonnement payant gratuitement |
| 7 | 🔴 CRITIQUE | `server.py:5295–5351` | Protéger `activate-early-adopter`, `cancel`, `simulate-trial-end`, `reset-to-trial` derrière l'authentification JWT | Fin de la manipulation d'abonnement |
| 8 | 🔴 CRITIQUE | `garmin/providers/gccli_provider.py`, `api/garmin.py` | Décider de l'architecture multi-compte Garmin (OAuth individuel vs mono-compte admin) | Isolation des données sportives par utilisateur |
| 9 | 🟠 IMPORTANT | `server.py:5282` | Ne pas retourner `stripe_customer_id` dans la réponse publique de `subscription/info` | Réduction de la surface d'exposition |
| 10 | 🟠 IMPORTANT | `server.py:1787` | Filtrer `/api/messages` par `user_id` authentifié | Fin de la fuite des conversations |
| 11 | 🟠 IMPORTANT | `server.py:5217, 5240` | Protéger `/cache/clear` et `/metrics/reset` par token admin | Fin du DoS par cache clear |

---

### I. VERDICT FINAL

**Le système actuel de gestion des utilisateurs de RunIndex est-il suffisamment sécurisé pour être utilisé par de vrais utilisateurs ?**

## ❌ NON

**Raison :** RunIndex est actuellement conçu comme une **application mono-utilisateur** avec un `user_id = "default"` hardcodé partout. Il n'existe aucun système d'authentification (pas de login, pas de mot de passe, pas de JWT). Toutes les données de tous les futurs utilisateurs seraient mélangées et mutuellement accessibles. Un utilisateur pourrait consulter les données sportives d'un autre, modifier son abonnement, vider ses caches, ou activer un abonnement payant gratuitement.

La mise en production en l'état exposerait les **données personnelles et physiologiques** de vos utilisateurs à n'importe qui, en violation du RGPD.

**Ce projet nécessite une implémentation complète du système d'authentification avant tout déploiement public.**
