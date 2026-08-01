# AUDIT TECHNIQUE — Migration Garmin mono-compte → Garmin multi-utilisateur (OAuth officiel)

> Objectif : fournir à GitHub Copilot toutes les informations nécessaires pour
> implémenter Garmin multi-utilisateur et la règle **1 compte Garmin = 1 seul Trial
> Premium 30 jours**.
>
> ⚠️ CE DOCUMENT EST UN AUDIT LECTURE-SEULE. Aucun code n'a été modifié.
> Date : Juin 2026 — Branche : PR34 (+ PR39 infra trial).

---

## RÉPONSE À LA QUESTION CENTRALE

**Garmin OAuth officiel permet-il d'obtenir une identité Garmin persistante et fiable par utilisateur ?**

**OUI.** Le *Garmin Connect Developer Program* (API Wellness/Health) utilise **OAuth 2.0 + PKCE**.
Après consentement, l'application obtient un *User Access Token*, puis récupère un identifiant :

```
GET https://apis.garmin.com/wellness-api/rest/user/id
Authorization: Bearer {access_token}
```

Cet **API User ID** est :
- **unique par compte Garmin**,
- **persistant** : il reste identique même si l'utilisateur se déconnecte puis se reconnecte,
- **stable** à travers différents User Access Tokens,
- **fourni par le backend Garmin**, jamais par le frontend.

➡️ C'est **exactement** l'identité recherchée pour garantir « 1 Garmin = 1 Trial ».
Elle doit servir de valeur `garmin_identity` dans `garmin_trial_registry`.

**Endpoints Garmin de référence :**
| But | Endpoint |
|---|---|
| Échange code → token | `POST https://diauth.garmin.com/di-oauth2-service/oauth/token` |
| Identité utilisateur | `GET https://apis.garmin.com/wellness-api/rest/user/id` |
| Permissions accordées | `GET https://apis.garmin.com/wellness-api/rest/user/permissions` |
| Suppression / désinscription | `DELETE https://apis.garmin.com/wellness-api/rest/user/registration` |

Note : Garmin **fait tourner (rotate) les refresh tokens** — il faut réécrire le token stocké à chaque refresh.

---

## 1. Comment Garmin est actuellement intégré dans RunIndex

- Intégration via **`gccli`** (binaire Garmin Connect CLI non officiel), PAS l'API OAuth officielle.
- Couche provider : `backend/garmin/providers/gccli_provider.py` → `GccliRunner` (`backend/garmin/runner.py`).
- Factory : `backend/garmin/factory.py` (`active_provider_name()` = `"gccli"`, singleton `lru_cache`).
- Orchestration : `backend/garmin/service.py` (connect/sync/deep_sync/disconnect/status).
- HTTP : `backend/api/garmin.py` (routes `/api/garmin/*`).
- Bootstrap au démarrage : `backend/garmin/bootstrap.py` (télécharge le binaire gccli, login one-shot).
- Auth : **le frontend ne fournit JAMAIS de mot de passe Garmin** (contrainte non négociable respectée). Les
  identifiants viennent des env `GARMIN_USERNAME` / `GARMIN_PASSWORD`.

## 2. Où le compte Garmin partagé est configuré

- Fichier : `backend/.env` → clés `GARMIN_PROVIDER=gccli`, `GARMIN_USERNAME`, `GARMIN_PASSWORD`.
- Lu par : `gccli_provider.GccliProvider._account()` via `config.secrets.get_secret("GARMIN_USERNAME")`.
- Session persistée : répertoire `GCCLI_HOME` (`/app/backend/.gccli_home`), keyring `file`.
- **Un seul compte Garmin pour toute l'application.** Tous les appels gccli utilisent ce compte.

## 3. Comment les données Garmin sont récupérées et stockées

Flux : `gccli` → provider `_normalize()` → `service._ingest_activities()` → MongoDB.

Collections MongoDB :
| Collection | Contenu | Clé |
|---|---|---|
| `garmin_connections` | statut de connexion, provider, dernière sync, activity_count, deep_sync_done | `user_id` (unique) |
| `garmin_activities` | activités normalisées (source de vérité) | `(user_id, external_id)` unique |
| `garmin_daily_metrics` | HRV, FC repos, sommeil | `(user_id, date)` unique |
| `workouts` (dérivé) | séances produit issues des activités (`data_source="garmin"`) | `(user_id, ...)` |

Pipeline : ingestion `garmin_activities` → événement `ACTIVITY_CREATED` (Redis stream) → worker fan-out
construit `workouts` + cache feed → backfill RunIndex history. **gccli n'est jamais appelé dans le flux
requête HTTP** (offload worker `workers/sync_worker.py`).

## 4. Comment les activités sont associées aux utilisateurs RunIndex

**⚠️ POINT CRITIQUE — Elles ne le sont PAS réellement.**

- Les handlers de `backend/api/garmin.py` prennent `user_id: str = "default"` en **query param**,
  avec valeur par défaut `"default"`. Ils **ne résolvent PAS le user_id depuis le JWT**.
- Le frontend (`frontend/src/pages/Onboarding.jsx`, ligne 74) appelle
  `POST ${API}/garmin/connect` avec un corps `{}` et **aucun user_id** → tombe sur `"default"`.
- État réel de la base (vérifié) :
  - `garmin_connections` : **1 seul document**, `user_id="default"`, `connected=true`, `activity_count=141`.
  - `garmin_activities` : **141 documents, tous `user_id="default"`** (`distinct user_id = ["default"]`).

➡️ Conclusion : aujourd'hui **toutes les données Garmin appartiennent au pseudo-utilisateur `"default"`**,
partagé par tout le monde. Il n'existe aucune identité Garmin par utilisateur RunIndex.

## 5. Fichiers et composants concernés

**Backend**
- `backend/api/garmin.py` — routes HTTP (à lier au JWT + flux OAuth).
- `backend/garmin/service.py` — orchestration (connect/sync/disconnect).
- `backend/garmin/factory.py` — sélection du provider (ajouter provider OAuth).
- `backend/garmin/providers/base.py` — interface `Provider` (à étendre pour l'identité).
- `backend/garmin/providers/gccli_provider.py` — provider actuel (mono-compte).
- `backend/garmin/runner.py` — exécuteur gccli.
- `backend/garmin/bootstrap.py` — login one-shot au démarrage (obsolète en multi-user).
- `backend/subscription_manager.py` — `activate_garmin_trial()` (déjà écrit, gaté par `_GARMIN_IDENTITY_AVAILABLE=False`).
- `backend/access_control.py` — table `ROUTE_ACCESS_MAP` (conflit `/api/garmin/` = PREMIUM, cf. §15).
- `backend/server.py` — montage router (l.5984-5985), middleware abonnement (l.421+), index startup (l.6044-6059), config Paddle.
- `backend/config/secrets.py` — lecture des secrets.
- `backend/.env` — variables Garmin.

**Frontend**
- `frontend/src/pages/Onboarding.jsx` — bouton "Connecter Garmin" (l.71-93), à remplacer par le flux OAuth (redirection).
- `frontend/src/context/SubscriptionContext.jsx` — rafraîchit l'état d'abonnement (trial affiché après retour OAuth).
- `frontend/src/components/Paywall.jsx` — inchangé.
- Nouvelle page/route de **callback OAuth** à créer (ex : `/garmin/callback`).

## 6. Garmin OAuth officiel est-il compatible avec l'architecture actuelle ?

**Oui, techniquement compatible, mais nécessite un nouveau provider et un flux de redirection.**

- L'architecture provider (`Provider` abstraite + factory) est **conçue pour accueillir un backend OAuth**
  (commentaire explicite dans `base.py` : « gccli / mock / future OAuth »).
- La couche service/ingestion (`garmin_activities`, événements, workouts) est réutilisable telle quelle,
  à condition que `user_id` soit le **vrai UUID RunIndex** (issu du JWT) et non `"default"`.
- Différence majeure : gccli fait un login serveur silencieux ; OAuth impose une **redirection navigateur**
  (l'utilisateur consent sur garmin.com) puis un **callback** avec `code` → échange token côté backend.
- Il faudra stocker **par utilisateur** : access_token, refresh_token, expiry, et surtout l'**API User ID**.

## 7. Credentials / accès développeur Garmin nécessaires

À obtenir **AVANT** tout développement (prérequis bloquant) :
1. **Candidature au Garmin Connect Developer Program** (partner-gated, approbation ~quelques jours ouvrés).
2. Après approbation, dans le Developer Portal :
   - **Client ID** (Consumer Key)
   - **Client Secret** (Consumer Secret)
   - **Redirect URI(s)** enregistrée(s) (préview + production).
3. **Scopes/permissions** à demander (ex. `ACTIVITY_EXPORT`, lecture wellness) selon les besoins RunIndex.

Variables d'environnement à prévoir (`backend/.env`, à fournir par l'utilisateur, jamais en dur) :
```
GARMIN_OAUTH_CLIENT_ID=
GARMIN_OAUTH_CLIENT_SECRET=
GARMIN_OAUTH_REDIRECT_URI=
GARMIN_PROVIDER=oauth      # bascule gccli → oauth
```

## 8. Identité Garmin stable garantissant « 1 Garmin = 1 Trial »

**L'API User ID Garmin** obtenu via `GET /wellness-api/rest/user/id` (voir tête de document).

- Persistant, unique par compte Garmin, stable après reconnexion → **clé anti-abus fiable**.
- À utiliser comme `garmin_identity` dans `garmin_trial_registry`.
- ❌ NE PAS utiliser : email, cookie, localStorage, JWT seul, compte gccli partagé, ni valeur envoyée par le frontend.

## 9. Comment cette identité doit être stockée dans MongoDB

**`garmin_connections`** (une entrée par utilisateur RunIndex) — ajouter :
```jsonc
{
  "user_id": "<UUID RunIndex issu du JWT>",   // remplace "default"
  "garmin_user_id": "<API User ID Garmin>",    // identité persistante
  "connected": true,
  "provider": "oauth",
  "oauth_access_token": "<chiffré>",
  "oauth_refresh_token": "<chiffré>",
  "oauth_token_expires_at": "<ISO>",
  "scopes": ["ACTIVITY_EXPORT", "..."],
  "connected_at": "<ISO>", "last_sync": "<ISO>", "activity_count": 0
}
```

**`garmin_trial_registry`** (registre anti-abus — DÉJÀ en place) :
```jsonc
{
  "garmin_identity": "<API User ID Garmin>",   // = garmin_user_id
  "first_trial_user_id": "<UUID RunIndex>",
  "trial_activated_at": "<ISO>"
}
```
✅ **Index unique `garmin_identity` DÉJÀ CRÉÉ au startup** (`server.py` l.6053-6055) et **vérifié présent en base**
(`garmin_identity_1 { unique: true, sparse: false }`). La garantie de concurrence atomique est donc prête côté DB.

**`subscriptions`** : champ `garmin_identity` déjà prévu (rempli par `activate_garmin_trial`).

> Sécurité : les tokens OAuth doivent être **chiffrés au repos** (clé serveur), jamais renvoyés au frontend.

## 10. Tokens, refresh, expiration, révocation

- **Access token** : durée courte → stocker `expires_at`, rafraîchir avant appel si expiré.
- **Refresh token** : Garmin **rote** le refresh token → à chaque refresh, **écraser** l'ancien en base.
- **Expiration** : si refresh échoue (token révoqué côté Garmin) → marquer la connexion `connected=false`,
  demander une reconnexion OAuth. **Ne jamais supprimer** l'entrée `garmin_trial_registry` (sinon un
  déconnect/reconnect redonnerait un trial → faille).
- **Révocation / déconnexion** : appeler `DELETE /wellness-api/rest/user/registration` côté Garmin
  (exigence du programme), puis nettoyer `garmin_connections` de l'utilisateur — mais **conserver** le registre trial.

## 11. Empêcher un utilisateur de déclarer l'identité Garmin d'un autre

- `garmin_identity` (= API User ID) est **exclusivement** dérivé du token OAuth échangé **côté backend**.
  Il n'est **jamais** accepté depuis le corps de requête, un header, ou le frontend.
- Le `state` OAuth (anti-CSRF) doit être généré et vérifié côté serveur — la collection `oauth_states`
  existe déjà (index unique `state`, TTL `expires_at`, cf. `server.py` l.6031-6032) et est réutilisable.
- Le lien `user_id RunIndex ↔ garmin_user_id` est écrit uniquement par le backend après échange de token,
  en associant le `state` au user JWT courant.
- `activate_garmin_trial(db, user_id, garmin_identity)` (déjà écrit) enforce le claim atomique :
  seul le **premier** `first_trial_user_id` obtient le trial ; les suivants restent FREE.

## 12. Gestion des cas

| Cas | Comportement cible |
|---|---|
| **Connexion Garmin** | Redirection OAuth → callback → échange token → récup API User ID → upsert `garmin_connections` (par user_id JWT) → `activate_garmin_trial(user_id, garmin_user_id)` → deep sync. |
| **Déconnexion** | `DELETE registration` Garmin + purge `garmin_connections`/activités du user. **Conserver** `garmin_trial_registry`. |
| **Reconnexion** | Nouveau flux OAuth → même API User ID → `activate_garmin_trial` voit l'entrée registry existante → **pas de nouveau trial** (reste FREE ou statut courant). |
| **Changement de compte Garmin** | Nouvel API User ID → nouvelle entrée registry possible → trial accordé **si ce compte Garmin n'a jamais eu de trial**. (Anti-abus : le multi-comptes Garmin reste possible mais coûteux à l'utilisateur ; hors scope règle actuelle.) |
| **Utilisateurs simultanés** | Isolation par `user_id` JWT sur toutes les collections ; claim trial protégé par l'index unique + `find_one_and_update $setOnInsert`. |

## 13. Impact sur gccli

- gccli devient un **provider legacy**. Deux options :
  - (a) le retirer une fois OAuth validé, ou
  - (b) le garder derrière `GARMIN_PROVIDER=gccli` pour un usage admin/debug (mono-compte).
- `bootstrap.py` (login one-shot serveur) devient inutile en mode OAuth → à ne plus exécuter si `GARMIN_PROVIDER=oauth`.
- Le compte serveur unique (`GARMIN_USERNAME`/`PASSWORD`) n'est plus utilisé pour les utilisateurs finaux.

## 14. Impact sur access_control.py

- `access_control.py` reste la **source de vérité** ; la logique tier (FREE/TRIAL/PREMIUM) est inchangée.
- `activate_garmin_trial` fait passer un user en `trial` → `get_user_access` renvoie TRIAL automatiquement.
- **⚠️ Conflit à corriger** : `ROUTE_ACCESS_MAP["/api/garmin/"] = RouteAccess.PREMIUM` (l.507).
  Le middleware (`server.py` l.442-462) **bloque en 403 tout user FREE** sur `/api/garmin/*`.
  Or, pour obtenir un trial, un user FREE **doit** pouvoir lancer la connexion Garmin.
  → Les routes de **connexion/callback OAuth** (`/api/garmin/oauth/start`, `/api/garmin/oauth/callback`,
  `/api/garmin/connect`) doivent être **reclassées `FREE`** ; les routes de données (`/sync`, `/activities`,
  `/daily-metrics`) peuvent rester PREMIUM (le trial donne déjà l'accès premium).

## 15. Impact sur le nouveau système Trial

- L'infra est **prête** : `activate_garmin_trial()` (atomique), `garmin_trial_registry` + index unique (créé),
  `create_free_subscription` à l'inscription.
- Il reste à : (1) passer `_GARMIN_IDENTITY_AVAILABLE=True`, (2) appeler `activate_garmin_trial(db, user_id_jwt,
  garmin_user_id)` depuis le callback OAuth **après** obtention de l'API User ID.
- La signature de `activate_garmin_trial` est déjà correcte (n'accepte que des valeurs serveur).

## 16. Impact sur les 141 activités "default"

- Elles restent sous `user_id="default"` — **à NE PAS supprimer ni migrer sans décision explicite** (contrainte).
- En multi-user, elles deviennent **orphelines** (aucun compte JWT ne pointe sur "default").
- Options futures (hors scope, décision utilisateur requise) :
  - les laisser telles quelles (invisibles pour les nouveaux users), ou
  - les rattacher au compte dont l'API User ID Garmin correspond au compte gccli d'origine, si un jour ce
    compte se connecte via OAuth.
- **Aucune action automatique recommandée.**

## 17. Compatibilité avec l'architecture Paddle de PR34

- **Totalement indépendante.** Paddle gère le passage TRIAL/FREE → PREMIUM via webhook signé + `activate_premium()`.
- Le flux Garmin/OAuth n'écrit que le statut `trial` ; Paddle écrit le statut `premium`. Aucun couplage.
- `subscription.garmin_identity` et `subscription.paddle_subscription_id` coexistent dans le même document.
- ✅ Aucune régression Paddle attendue. Le webhook, la sécurité HMAC et l'idempotence restent inchangés.

---

# RAPPORT DE SYNTHÈSE

## A. Architecture Garmin ACTUELLE

```
                 backend/.env (GARMIN_USERNAME/PASSWORD)
                              │
        Tous les users ──► gccli (1 compte serveur partagé)
                              │
                    user_id = "default" (query param, jamais le JWT)
                              │
             garmin_connections / garmin_activities  (user_id="default")
                              │
                    141 activités, partagées par tout le monde
```
Pas d'identité Garmin par utilisateur → « 1 Garmin = 1 Trial » **impossible à garantir**.

## B. Architecture Garmin CIBLE

```
User A (JWT) ─► OAuth Garmin ─► API User ID A ─► garmin_connections{user_id:A, garmin_user_id:A} ─► activités A
User B (JWT) ─► OAuth Garmin ─► API User ID B ─► garmin_connections{user_id:B, garmin_user_id:B} ─► activités B
User C (JWT) ─► OAuth Garmin ─► API User ID A ─► registry déjà pris par A ─► reste FREE, activités A (lecture)
```
Isolation par `user_id` JWT + identité anti-abus = `garmin_user_id` (API User ID Garmin).

## C. Identité Garmin recommandée pour le Trial

**API User ID Garmin** — `GET https://apis.garmin.com/wellness-api/rest/user/id`.
Persistant, unique, stable après reconnexion, fourni par le backend Garmin. Stocké comme `garmin_identity`.

## D. Données MongoDB nécessaires

- `garmin_connections` : + `garmin_user_id`, `oauth_access_token` (chiffré), `oauth_refresh_token` (chiffré),
  `oauth_token_expires_at`, `scopes`. `user_id` = UUID JWT (plus `"default"`).
- `garmin_trial_registry` : `{garmin_identity, first_trial_user_id, trial_activated_at}` — **index unique DÉJÀ créé**.
- `subscriptions` : `garmin_identity` (déjà prévu), statut passe à `trial`.
- `oauth_states` : réutiliser pour le `state` anti-CSRF (déjà indexé + TTL).

## E. Fichiers que GitHub Copilot devra modifier / créer

**Modifier** : `backend/api/garmin.py`, `backend/garmin/service.py`, `backend/garmin/factory.py`,
`backend/garmin/providers/base.py`, `backend/subscription_manager.py` (`_GARMIN_IDENTITY_AVAILABLE=True`),
`backend/access_control.py` (reclasser routes OAuth en FREE), `backend/server.py` (routes/middleware),
`backend/.env` (nouvelles clés OAuth), `frontend/src/pages/Onboarding.jsx`.
**Créer** : `backend/garmin/providers/oauth_provider.py` (provider OAuth 2.0 PKCE), routes
`/api/garmin/oauth/start` + `/api/garmin/oauth/callback`, page frontend de callback `/garmin/callback`.

## F. Prérequis Garmin à obtenir AVANT développement

1. Approbation **Garmin Connect Developer Program** (partner-gated, quelques jours).
2. **Client ID**, **Client Secret**, **Redirect URI** enregistrés.
3. Scopes/permissions validés.
4. Renseigner `GARMIN_OAUTH_CLIENT_ID/SECRET/REDIRECT_URI` + `GARMIN_PROVIDER=oauth` dans `backend/.env`.

## G. Risques / Blockers

- **BLOCKER n°1** : accès Developer Program non encore obtenu (dépendance externe, délai d'approbation).
- **BLOCKER n°2 (code)** : conflit `ROUTE_ACCESS_MAP` — `/api/garmin/` = PREMIUM empêche un user FREE de
  se connecter pour obtenir son trial. À corriger (routes OAuth en FREE).
- Rotation des refresh tokens Garmin : mauvaise gestion = perte de session → prévoir écrasement systématique.
- Chiffrement des tokens au repos obligatoire (secret serveur).
- 141 activités `"default"` deviennent orphelines (décision utilisateur requise, pas d'action auto).
- gccli et OAuth ne doivent pas cohabiter pour un même user (choisir via `GARMIN_PROVIDER`).
- Ne jamais accepter `garmin_identity` depuis le frontend (règle anti-abus absolue).

## H. Plan de migration par étapes

1. **Prérequis** : obtenir credentials Developer Program, renseigner `.env`.
2. **Provider OAuth** : créer `oauth_provider.py` (PKCE : génération `code_verifier/challenge`, échange token,
   `get_garmin_user_id()`, refresh). Étendre `Provider` (base) avec `get_identity()`.
3. **Routes OAuth** : `/api/garmin/oauth/start` (FREE) génère `state` + redirection ;
   `/api/garmin/oauth/callback` (FREE) vérifie `state`, échange token, récupère API User ID, upsert
   `garmin_connections` (user_id JWT), appelle `activate_garmin_trial`, lance deep sync.
4. **Access control** : reclasser routes de connexion en FREE ; garder données en PREMIUM.
5. **Lier au JWT** : remplacer `user_id="default"` par le user_id JWT dans tous les handlers `api/garmin.py`.
6. **Débloquer le trial** : `_GARMIN_IDENTITY_AVAILABLE=True`.
7. **Frontend** : bouton "Connecter Garmin" → redirection OAuth ; page callback → `refreshSubscription`.
8. **Tokens** : refresh automatique + rotation ; déconnexion via `DELETE registration`.
9. **Tests** (§I).
10. **Décision séparée** : sort des 141 activités `"default"`.

## I. Tests indispensables

1. **User A + Garmin A → TRIAL** : connexion OAuth de A donne un trial 30 j (statut `trial`, premium_access=true).
2. **User B + Garmin B → TRIAL** : compte Garmin différent → trial accordé indépendamment.
3. **User C + Garmin A → FREE** : Garmin A déjà enregistré dans le registry → C reste FREE (aucun trial).
4. **Déconnexion / reconnexion (même Garmin) → PAS de nouveau trial** : le registry conserve l'entrée.
5. **Requêtes concurrentes** (2 users réclamant Garmin A en parallèle) → un seul obtient le trial (index unique).
6. **Isolation multi-users** : activités/plans/chat de A jamais visibles par B (filtre `user_id` JWT partout).
7. **Trial expiré → FREE** : après 30 j, `check_trial_expiration` bascule en FREE ; garmin identity conservée.
8. **Trial expiré → Paddle → PREMIUM** : webhook Paddle passe FREE→PREMIUM sans toucher le registry Garmin.
9. **Refresh token** : appel après expiration de l'access token → refresh transparent, nouveau refresh stocké.
10. **Révocation Garmin** : token révoqué côté Garmin → connexion marquée déconnectée, pas de crash.
11. **Anti-injection** : tentative d'envoyer `garmin_identity` via le corps/headers/query → ignorée (backend-only).
12. **Non-régression Paddle** : config/checkout/webhook/signature/idempotence inchangés.
13. **Build frontend** : compile OK, page onboarding + callback fonctionnelles.
14. **Route FREE OAuth** : un user FREE peut atteindre `/api/garmin/oauth/start` (pas de 403).
