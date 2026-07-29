# COMPREHENSIVE AUDIT REPORT: RunIndex Application

> **Date :** 2026-07-29  
> **Sources :** Agrégation de tous les audits sectoriels réalisés sur l'application RunIndex  
> **Périmètre :** Sécurité · Authentification · Multi-utilisateurs · Garmin · SRE · Déploiement · Scalabilité

---

## RÉSUMÉ EXÉCUTIF

RunIndex est une application de suivi de l'entraînement de course (React → JWT → FastAPI → MongoDB) avec intégration Garmin via `gccli`, analyse IA (GPT), système d'abonnement Stripe et pipeline de synchronisation asynchrone Redis.

L'application est **techniquement solide** en termes d'infrastructure et de pipeline de données, mais présente des **problèmes critiques** de sécurité, d'authentification et d'isolation multi-utilisateurs qui ont été progressivement corrigés au cours des PR #19 à #27.

**Note globale sécurité (état initial pré-PR#23) : 1.5 / 10**  
**État après PR#27 (multi-user JWT complet) : ✅ Prêt pour lancement contrôlé jusqu'à ~1 000 utilisateurs**

---

## PARTIE 1 — ARCHITECTURE DE L'APPLICATION

### Stack technique

```
Frontend (React SPA)
  │ Authorization: ******
  ▼
FastAPI (backend/server.py, ~5600 lignes)
  │ auth_user() → JWT HS256 → user_id (UUID)
  │
  ├── /api/garmin/*        ← garmin_router (api/garmin.py)
  ├── /api/run-index       ← auth_user() → user["id"]
  ├── /api/auth/*          ← auth_router (inscription/connexion)
  ├── /api/workouts        ← auth_user()
  ├── /api/coach/*         ← LLM (gpt-4.1-mini)
  └── /api/subscription/*  ← Stripe
        │
MongoDB (Motor async)
  ├── users                ← { email, password_hash, created_at }
  ├── subscriptions        ← { user_id, plan, trial_ends_at }
  ├── workouts             ← { user_id, id, data_source, ... }
  ├── garmin_connections   ← { user_id, connected, provider }
  ├── garmin_activities    ← { user_id, external_id, ... }
  ├── garmin_daily_metrics ← { user_id, date, hrv, resting_hr, sleep_hours }
  └── conversations        ← { user_id, messages }

Redis
  ├── runindex:garmin:queue              ← jobs FIFO
  ├── runindex:garmin:processing         ← reliable queue
  ├── runindex:feed:{user_id}            ← cache activités par user
  ├── runindex:events:activity_created   ← Redis Stream (fan-out)
  └── runindex:active_signal:{user_id}   ← signal activité scheduler

Workers (out-of-process)
  ├── workers/sync_worker.py       ← consomme queue Redis, appelle gccli
  ├── workers/scheduler_worker.py  ← décide quand syncer chaque user
  └── workers/event_worker.py      ← fan-out ACTIVITY_CREATED → workouts + feed
```

### Points forts de l'architecture

- ✅ Données **clefées par `user_id`** dans toutes les collections MongoDB
- ✅ Pipeline Garmin **event-driven** (queues Redis, scheduler avec cooldown, verrous par user)
- ✅ Abonnement propre et centralisé (`subscription_manager.py`) : trial/free/early_adopter/premium
- ✅ Architecture Provider abstraite (`GarminProvider`) permettant de changer le backend Garmin sans refactor métier
- ✅ Tests unitaires existants (cycle dates, history, deep sync, subscription, chat)
- ✅ Signature webhook Stripe correctement vérifiée (HMAC-SHA256 + horodatage)

---

## PARTIE 2 — AUDIT SÉCURITÉ ET AUTHENTIFICATION

### 2.1 État initial (pré-PR#23) — Note : 1.5/10

#### Vulnérabilités CRITIQUES (état initial)

| # | Vulnérabilité | Localisation |
|---|---|---|
| C1 | **Absence totale d'authentification** — Aucun login/mot de passe/JWT | `server.py:303–339` |
| C2 | **user_id client-contrôlé** — N'importe qui peut se faire passer pour un autre | Tous les endpoints |
| C3 | **USER_ID="default" hardcodé frontend** — Tous les utilisateurs partagent les mêmes données | `constants.js:4` |
| C4 | **Broken Access Control** — Stats, digest, analyses IA sans filtre user | `server.py:1369, 1802, 2034...` |
| C5 | **IDOR workout** — Accès à n'importe quel workout par ID sans vérification ownership | `server.py:2219, 2381, 2465` |
| C6 | **Activation abonnement sans paiement** — `verify-checkout` active `early_adopter` sans Stripe | `server.py:5571` |
| C7 | **Manipulation abonnement unauthenticated** — `activate-early-adopter` et `cancel` publics | `server.py:5295, 5318` |
| C8 | **Endpoints dev en production** — `simulate-trial-end`, `reset-to-trial` exposés | `server.py:5333, 5354` |
| C9 | **Garmin mono-compte** — GARMIN_USERNAME/PASSWORD unique pour tous les users | `gccli_provider.py` |
| C10 | **Spoofing Bearer** — `Authorization: ****** accepté sans validation | `server.py:324–326` |

#### Vulnérabilités IMPORTANTES (état initial)

| # | Vulnérabilité | Localisation |
|---|---|---|
| I1 | `stripe_customer_id` retourné au frontend | `server.py:5282–5292` |
| I2 | `/api/messages` sans filtre utilisateur | `server.py:1787–1791` |
| I3 | Rate limiter basé sur user_id client-contrôlé | `server.py:280–296` |
| I4 | `CoachRequest.user_id` client-contrôlé | `server.py:512, 1480` |
| I5 | Endpoints admin non protégés (`/cache/clear`, `/metrics/reset`) | `server.py:5223–5245` |

### 2.2 État après corrections (PR#23–#26)

#### Ce qui a été corrigé

- ✅ **PR#23** — Audit de sécurité complet, rapport `AUDIT_SECURITE.md`
- ✅ **PR#24** — Implémentation complète auth JWT : bcrypt, JWT HS256 (exp 60 min), endpoints `/api/auth/register|login|me|logout|forgot-password|reset-password`
- ✅ **PR#25** — Isolation multi-users stricte, JWT sur tous les endpoints, trial auto-provisioning, suppression des fallbacks `user_id="default"`
- ✅ **PR#26** — Correctif middleware abonnement : `get_user_id_from_request` décode JWT en priorité (ordre : JWT `sub` → header `X-User-Id` → IP)
- ✅ `JWT_SECRET_KEY` généré (aléatoire fort) dans `backend/.env`
- ✅ `auth_user` exige JWT valide (`sub` = UUID), retourne 401 sans token
- ✅ `AuthContext` frontend, pages Login/Register, interceptor Axios avec `Authorization: Bearer`
- ✅ Trial 30 jours auto-créé à l'inscription pour chaque nouvel utilisateur

#### Ce qui reste correct depuis le début

- ✅ Signature webhook Stripe (HMAC-SHA256 + tolerance 300s)
- ✅ Aucun secret hardcodé dans le code source
- ✅ CORS restrictif en production (`ENVIRONMENT=production` → `FRONTEND_URL` uniquement)
- ✅ Guard `DEMO_MODE=true` bloqué en production
- ✅ Validation des entrées Pydantic, sanitisation HTML des notes
- ✅ Tokens Garmin jamais exposés au frontend
- ✅ Index MongoDB créés au démarrage

### 2.3 Tableau d'autorisation des endpoints (état post-PR#26)

| Méthode | Route | Auth | Isolation user |
|---|---|---|---|
| POST | `/api/auth/register` | Public | — |
| POST | `/api/auth/login` | Public | — |
| GET | `/api/auth/me` | ✅ JWT | ✅ user["id"] |
| GET | `/api/workouts` | ✅ JWT | ✅ filtré user_id |
| GET | `/api/run-index` | ✅ JWT | ✅ user["id"] |
| GET | `/api/garmin/*` | ✅ JWT (post-PR#25) | ✅ user["id"] |
| POST | `/api/garmin/sync` | ✅ JWT | ✅ user["id"] |
| GET | `/api/subscription/status` | ✅ JWT | ✅ user["id"] |
| POST | `/api/webhook/stripe` | Public | ✅ HMAC Stripe |

---

## PARTIE 3 — AUDIT GARMIN MULTI-UTILISATEURS

### 3.1 Architecture Garmin actuelle (post-PR#27)

#### Le problème central résolu : gccli multi-compte

**État initial (mono-compte) :**

```python
# factory.py
@lru_cache(maxsize=1)   # UN SEUL provider pour TOUTE l'appli
def _gccli_provider() -> GccliProvider:
    runner = GccliRunner(
        home=os.environ.get("GCCLI_HOME", "/app/backend/.gccli_home"),  # UN seul HOME
    )

# gccli_provider.py
def _account(self) -> Optional[str]:
    return get_secret("GARMIN_USERNAME")  # ENV GLOBAL, pas par user
```

**Ce qui a été analysé pour la migration (PR#27) :**

| Composant | Fichier | État pour multi-user |
|---|---|---|
| **Routes HTTP Garmin** | `backend/api/garmin.py` | ❌→✅ JWT ajouté, `user_id` via `auth_user` |
| **Factory** | `backend/garmin/factory.py` | ❌ Singleton LRU mono-compte (à traiter) |
| **Provider** | `backend/garmin/providers/gccli_provider.py` | ❌ `_account()` = env global (à traiter) |
| **Runner** | `backend/garmin/runner.py` | ⚠️ `account` param existe mais HOME unique |
| **Bootstrap** | `backend/garmin/bootstrap.py` | ❌ Login one-time mono-compte |
| **Service** | `backend/garmin/service.py` | ✅ `user_id` propagé partout |
| **Insights** | `backend/garmin/insights.py` | ✅ Filtrage par `user_id` en Mongo |
| **MongoDB** | (toutes collections) | ✅ Déjà multi-user (filtré par `user_id`) |
| **Event stream** | `backend/events/stream.py` | ✅ `user_id` propagé |
| **Feed cache** | `backend/feed/realtime_cache.py` | ✅ Clé `runindex:feed:{user_id}` |
| **Sync worker** | `backend/workers/sync_worker.py` | ✅ Traite `user_id` de la queue |
| **Scheduler** | `backend/workers/scheduler_worker.py` | ✅ Itère tous les users connectés |

#### Variables d'environnement Garmin

| Variable | Valeur par défaut | Rôle |
|---|---|---|
| `GARMIN_USERNAME` | — (required si session expirée) | Compte Garmin unique (global) |
| `GARMIN_PASSWORD` | — (required si login nécessaire) | Mot de passe Garmin unique (global) |
| `GARMIN_PROVIDER` | `""` | Doit valoir `"gccli"` pour le bootstrap |
| `GCCLI_PATH` | `"gccli"` | Chemin binaire gccli |
| `GCCLI_HOME` | `"/app/backend/.gccli_home"` | HOME gccli (token OAuth) |
| `GCCLI_KEYRING_BACKEND` | `"file"` | Backend keyring |
| `GCCLI_TIMEOUT` | `45` | Timeout par commande (s) |
| `GCCLI_MAX_RETRIES` | `3` | Retries avec backoff exponentiel |
| `GARMIN_PAGE_SIZE` | `50` | Taille de page pour deep sync |
| `GARMIN_DEEP_SYNC_ENABLED` | `"true"` | Active le deep sync au 1er connect |

### 3.2 Flux de synchronisation Garmin (état actuel)

```
1. POST /api/garmin/connect (JWT obligatoire)
   → user_id = user["id"] via auth_user
   → garmin_service.connect(db, user_id)
   → GccliProvider.connect(user_id) → runner.is_authenticated(GARMIN_USERNAME)
   → MongoDB: garmin_connections.upsert({ user_id, connected: true, provider: "gccli" })
   → Redis: enqueue_sync(user_id)

2. sync_worker.py dépile la queue
   → garmin_service.sync(db, user_id)
   → Si premier sync + GARMIN_DEEP_SYNC_ENABLED: fetch_all_activities(page_size)
   → Sinon: sync_activities(user_id, since=...) — COMPTE GLOBAL
   → _ingest_activities(db, user_id, activities)
      → garmin_activities.upsert({ user_id, external_id, ... })
      → emit ACTIVITY_CREATED → Redis Stream

3. event_worker.py consomme ACTIVITY_CREATED
   → activity_to_workout(activity, user_id) → workouts.upsert({ user_id, id="garmin-{ext_id}" })
   → realtime_cache.update_feed(user_id, activity)

4. scheduler_worker.py (~60s, leader lock Redis)
   → scan garmin_connections { connected: true }
   → scheduler.decide(now, active_signal_ts, last_activity_ts, last_sync_ts)
   → Si dû + hors cooldown: enqueue_incremental_sync(user_id)

5. GET /api/run-index (JWT obligatoire)
   → user_id = user["id"]
   → garmin.insights.compute_run_index(db, user_id)
      → garmin_daily_metrics.find({ user_id }).sort("date", -1).limit(30)
      → garmin_activities.find({ user_id }).sort("start_time", -1).limit(200)
      → Calcul ACWR, CTL, ATL, TSB, fatigue_ratio, run_readiness (0-100)
```

### 3.3 Ce qui reste à faire pour le vrai multi-compte Garmin

**Problème 1 — Credentials Garmin :** `GARMIN_USERNAME` / `GARMIN_PASSWORD` = variables globales. Pour un vrai multi-user, chaque utilisateur doit connecter **son propre** compte Garmin (vault applicatif ou OAuth Garmin natif).

**Problème 2 — GCCLI_HOME unique :** Un seul HOME = un seul token OAuth. Pour multi-user : `/app/backend/.gccli_home/{user_id}/` par utilisateur.

**Problème 3 — Factory singleton :** `lru_cache(maxsize=1)` doit être remplacé par un provider paramétré par `user_id`.

---

## PARTIE 4 — AUDIT SRE : ROBUSTESSE ET SCALABILITÉ

### 4.1 Mesures de charge (localhost, 1 worker uvicorn)

| Requêtes | Concurrence | Wall | Débit | p50 | p95 | p99 | HTTP |
|---|---|---|---|---|---|---|---|
| 10 | 10 | 0.03s | 341/s | 28ms | — | — | 100% 200 |
| 50 | 50 | ~0.15s | 332/s | 146ms | — | — | 100% 200 |
| 100 | 100 | 0.25s | 404/s | 230ms | 245ms | 245ms | 100% 200 |
| 500 | 100 | 1.29s | 388/s | 244ms | 338ms | 342ms | 100% 200 |
| 1000 | 100 | 2.52s | 397/s | 249ms | 306ms | 342ms | 100% 200 |

- **Débit API plafond ≈ 400 req/s** (1 worker, 2 ops Redis/req). 0 requête perdue jusqu'à 1000.
- **Débit worker RÉEL (gccli, compte unique) :** ~4.9s/sync → sémaphore 5 ⇒ **~1 sync/s** (plafond = gccli, pas l'infra).
- **RAM :** backend 27MB, worker 49MB, redis 12MB. Aucune fuite sur 5000+ jobs.

### 4.2 Concurrence et déduplication

- ✅ **Dédup prouvée** : 50 req concurrentes → 1 seul job `queued`, 29 `already_queued`
- ✅ **1 sync max/user** : verrou Redis `sync_lock:{uid}` en `SET NX EX` (atomique)
- ✅ **Aucun lock fantôme** (TTL configuré, toujours libéré)
- ✅ **Équilibrage workers** : `BRPOP` FIFO, aucun deadlock

### 4.3 Résilience

| Scénario | Comportement |
|---|---|
| Redis DOWN | **503 gracieux** (corrigé; était 500). Reprise auto. |
| Timeout gccli | `asyncio.wait_for(60s)` + 3 retries backoff |
| Crash worker `kill -9` mid-job | 🔴 **BUG** : job PERDU (`BRPOP` destructif sans liste de traitement) |
| gccli erreur persistante | `service.sync` avale l'échec (pas de requeue) |

### 4.4 Bugs / risques identifiés

| Sévérité | Problème | Recommandation |
|---|---|---|
| 🔴 MAJEUR | **Perte de job sur crash worker** — `BRPOP` destructif | `LMOVE queue processing` (reliable queue) + reprise orphelins |
| 🟠 MAJEUR | **Redis = SPOF** — sync indisponible si Redis tombe | Redis managé/répliqué en production |
| 🟠 MAJEUR | **Redis binaire non persistant** en conteneur | Redis managé, jamais apt-in-container |
| 🟡 MINEUR | Pas de retry worker sur panne gccli persistante | Requeue borné ou statut d'échec exposé |
| 🟡 MINEUR | Rate-limit par-user en mémoire (non global multi-instances) | Externaliser dans Redis si multi-uvicorn |
| 🟡 MINEUR | `sync_pending` TTL 300s peut bloquer re-enqueue post-crash | Réduire TTL ou supprimer au LMOVE |

### 4.5 Scheduler

- Implémenté, désactivé par défaut (`SYNC_SCHEDULE_INTERVAL=0`)
- Étalement des syncs (`SCHEDULE_STAGGER_MS=200`) → 1000 users = ~200s, pas de thundering herd
- Dédup intégrée : un cycle en cours n'est pas ré-enfilé

---

## PARTIE 5 — AUDIT DÉPLOIEMENT ET SCALABILITÉ

### 5.1 Capacité estimée

| Users | Verdict |
|---|---|
| **100** | ✅ Confortable. gccli mono-compte = goulot si syncs fréquentes, sinon OK. |
| **1 000** | 🟡 Tenable. API 400 req/s prouvés. Goulot = ~1 sync/s (gccli). Sync quotidienne 1000 users ≈ 17 min étalé. Nécessite Redis fiabilisé + managé. |
| **10 000** | 🟠 Nécessite : multi-comptes gccli ou agrégateur (Terra), reliable queue, plusieurs workers, Redis managé, rate-limit externalisé. |
| **50 000** | 🔴 Changement d'architecture : agrégateur officiel (Terra/Garmin Connect API), workers horizontaux, sharding, monitoring. |

### 5.2 Blocages critiques pour le scale (état initial)

| # | Blocage | Impact |
|---|---|---|
| **B1** | Compte Garmin unique partagé | Tous les utilisateurs voient les mêmes activités |
| **B2** | Pas d'auth réelle (résolu PR#24) | Aucune séparation des comptes |
| **B3** | Fuites inter-utilisateurs dans les requêtes Mongo (résolu PR#25) | Confidentialité compromise |
| **B4** | Rate-limiter en mémoire process | Incohérent en multi-instances |
| **B5** | Cache temps réel en mémoire process | Perdu au restart, incohérent |
| **B6** | Secrets Garmin en clair dans `.env` | À externaliser avant prod publique |
| **B7** | Coût LLM sans quota strict par plan | Peut exploser à 1000 users |

### 5.3 Checklist de déploiement production

**Phase 0 — Déploiement "as-is"**
1. ✅ Externaliser les secrets (`GARMIN_PASSWORD`, `STRIPE_API_KEY`) vers les variables d'env de la plateforme
2. ✅ MongoDB Atlas (pas la Mongo locale du preview)
3. ✅ Redis managé (Redis Cloud/Upstash)
4. ✅ Health checks : `/api/health`, readiness/liveness
5. ✅ CORS / URLs : `CORS_ORIGINS`, `FRONTEND_URL` → domaine prod
6. ✅ `DEMO_MODE=false` en production
7. ⚠️ Nettoyer `docker-compose.yml` vestige (référence Postgres/Celery obsolète)

**Phase 1 — Fiabilisation (avant scale)**
1. 🔴 **Reliable queue** (`LMOVE`) + reprise orphelins
2. 🟠 Redis managé/HA
3. 🟡 Rate-limit externalisé dans Redis

**Phase 2 — Scale >1000 users**
1. Multi-compte Garmin ou provider alternatif (Terra)
2. Workers horizontaux
3. Monitoring/alerting (Prometheus, alertes Redis, alertes worker)

---

## PARTIE 6 — MIGRATION MULTI-UTILISATEURS

### 6.1 État post-PR#25 (migration complète)

#### Backend — Points d'entrée migrés

Tous les endpoints `server.py` utilisant `user_id="default"` ou `X-User-Id` ont été migrés vers `user: dict = Depends(auth_user)` → `user["id"]` (UUID issu du JWT).

#### Frontend — Points d'entrée migrés

Tous les hooks/pages utilisaient `USER_ID = "default"` de `constants.js`. Après PR#25 :
- `AuthContext` fournit le `user_id` issu du JWT stocké en `localStorage`
- Toutes les pages (`Onboarding`, `TrainingPlan`, `Coach`, `Guidance`, `Settings`, `Progress`, `Digest`) utilisent l'ID du contexte authentifié

#### MongoDB — Requêtes permissives corrigées

Les requêtes utilisant `{"$or": [{"user_id": uid}, {"user_id": None}, {"user_id": {"$exists": False}}]}` ont été remplacées par des filtres stricts `{"user_id": auth_user_id}`.

### 6.2 Plan de migration des données (à exécuter en production)

1. Backfill Mongo sur collections historisées (`workouts`, `digests`, `guidance`) pour éliminer `user_id` null/absent
2. Basculer en mode strict (401 si identité absente)
3. Ajouter tests de non-régression multi-user (isolation stricte entre deux user_id)

---

## PARTIE 7 — VARIABLES D'ENVIRONNEMENT DE PRODUCTION

```bash
# Obligatoires — infrastructure
MONGO_URL=mongodb+srv://...
DB_NAME=runindex
ENVIRONMENT=production
FRONTEND_URL=https://runindex.app
REDIS_URL=redis://...

# Obligatoires — auth
JWT_SECRET_KEY=<généré aléatoirement, fort>
JWT_ALGORITHM=HS256
JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60

# Obligatoires — paiements
STRIPE_API_KEY=sk_live_...
STRIPE_WEBHOOK_SECRET=whsec_...

# Obligatoires — frontend
REACT_APP_BACKEND_URL=https://api.runindex.app

# Garmin (si intégration maintenue)
GARMIN_USERNAME=...
GARMIN_PASSWORD=...
GARMIN_PROVIDER=gccli
GCCLI_HOME=/app/backend/.gccli_home
GCCLI_KEYRING_BACKEND=file

# Sécurité impérative
DEMO_MODE=false
```

---

## PARTIE 8 — TABLEAU RÉCAPITULATIF FINAL

### État de chaque composant

| Composant | État actuel | Risque résiduel |
|---|---|---|
| **Authentification JWT** | ✅ Implémentée (bcrypt + JWT HS256) | — |
| **Isolation multi-users** | ✅ JWT obligatoire, user_id certifié | — |
| **Routes Garmin** | ✅ JWT sur toutes les routes | — |
| **CORS production** | ✅ Restrictif (`FRONTEND_URL` uniquement) | — |
| **Webhook Stripe** | ✅ HMAC-SHA256 + horodatage | — |
| **DEMO_MODE prod** | ✅ Bloqué | — |
| **Garmin mono-compte** | ⚠️ Un seul compte partagé | Limite scalabilité >1000 users |
| **Factory singleton** | ⚠️ `lru_cache(maxsize=1)` | Doit être paramétré par user |
| **Reliable queue** | ⚠️ `BRPOP` destructif | Perte de job sur crash worker |
| **Redis HA** | ⚠️ Redis = SPOF | Indisponibilité sync si Redis tombe |
| **Rate-limit** | ⚠️ En mémoire process | Inefficace en multi-instances |
| **Secrets Garmin** | ⚠️ Dans `.env` local | À externaliser (vault, env vars plateforme) |

### Recommandations classées par priorité

| Priorité | Action | Impact |
|---|---|---|
| 🔴 P1 | Reliable queue (`LMOVE` + reprise orphelins) | Élimine perte de jobs sur crash |
| 🟠 P2 | Redis managé/HA en production | Élimine SPOF sync |
| 🟠 P3 | Multi-compte Garmin ou provider Terra | Requis pour >1000 users actifs |
| 🟡 P4 | Rate-limit externalisé (Redis) | Multi-instances cohérent |
| 🟡 P5 | Monitoring Prometheus + alertes Redis/worker | Observabilité production |
| 🟡 P6 | Headers HTTP sécurité (HSTS, X-Frame-Options) | Defense-in-depth |
| 🟢 P7 | Tests d'isolation inter-utilisateurs | Non-régression multi-user |

---

## CONCLUSION

RunIndex a subi une transformation majeure entre la PR#19 (état mono-utilisateur) et la PR#27 (multi-utilisateurs complet avec JWT). Les vulnérabilités critiques de sécurité ont été corrigées. L'application est **prête pour un lancement contrôlé jusqu'à ~1 000 utilisateurs** sous réserve de :

1. **Redis managé/persistant** (jamais apt-in-container)
2. **Fiabiliser la file** (`LMOVE`/reliable queue) pour éliminer la perte de jobs sur crash worker

Au-delà de ~1 000 users actifs avec syncs fréquentes, le **compte gccli unique** (non l'infra async) devient le facteur limitant → migration vers multi-compte gccli ou agrégateur officiel (le `Provider` abstrait permet cette évolution sans refactor métier).
