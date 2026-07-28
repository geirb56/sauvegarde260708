# AUDIT GARMIN — RUNINDEX — PRÉPARATION STEP 3/3 (GCCLI MULTI-UTILISATEURS)

> Date : 2026-07-28  
> Contexte : RunIndex est une application multi-utilisateurs (React → JWT → FastAPI → MongoDB).  
> Objectif : analyser le fonctionnement actuel de Garmin/gccli pour préparer l'implémentation multi-user.

---

## 1. ARCHITECTURE ACTUELLE — VUE D'ENSEMBLE

```
Frontend (React)
  │ Authorization: ******
  ▼
FastAPI (server.py)
  │ auth_user() → JWT → user_id (UUID)
  │
  ├── /api/garmin/*        ← garmin_router (api/garmin.py)  ← PAS de JWT ici
  ├── /api/run-index       ← auth_user() → user["id"]       ← JWT OK
  └── /api/auth/*          ← auth_router
        │
MongoDB (motor async)
  ├── users
  ├── garmin_connections   ← { user_id, connected, provider, ... }
  ├── garmin_activities    ← { user_id, external_id, ... }
  ├── garmin_daily_metrics ← { user_id, date, hrv, resting_hr, sleep_hours }
  └── workouts             ← { user_id, id="garmin-{ext_id}", data_source="garmin" }

Redis
  ├── runindex:garmin:queue              ← jobs FIFO
  ├── runindex:garmin:processing         ← in-flight reliable queue
  ├── runindex:feed:{user_id}            ← cache activities par user
  ├── runindex:events:activity_created   ← Redis Stream (fan-out)
  └── runindex:active_signal:{user_id}   ← signal activité scheduler

Workers (out-of-process)
  ├── workers/sync_worker.py       ← consomme la queue Redis, appelle gccli
  ├── workers/scheduler_worker.py  ← décide quand syncer chaque user
  └── workers/event_worker.py      ← fan-out ACTIVITY_CREATED → workouts + feed
```

---

## 2. LE PROBLÈME CENTRAL : GCCLI EST MONO-COMPTE

C'est **le problème fondamental** pour le Step 3.

### 2a. Factory : singleton LRU, zéro isolement par user

**Fichier :** `backend/garmin/factory.py`

```python
@lru_cache(maxsize=1)   # UN SEUL provider pour TOUTE l'appli
def _gccli_provider() -> GccliProvider:
    runner = GccliRunner(
        home=os.environ.get("GCCLI_HOME", "/app/backend/.gccli_home"),  # UN seul HOME
        ...
    )
```

### 2b. GccliProvider._account() : une seule identité Garmin

**Fichier :** `backend/garmin/providers/gccli_provider.py`

```python
def _account(self) -> Optional[str]:
    return get_secret("GARMIN_USERNAME")  # ENV GLOBAL, pas par user
```

Toutes les méthodes (`connect`, `sync_activities`, `fetch_all_activities`, `get_daily_metrics`, `get_profile`) passent cet `account` unique au runner.

### 2c. GccliRunner._env() : HOME unique = token unique

**Fichier :** `backend/garmin/runner.py`

```python
def _env(self, account: Optional[str] = None) -> dict:
    env = os.environ.copy()
    env["HOME"] = self.home   # /app/backend/.gccli_home (unique, partagé)
    if account:
        env["GCCLI_ACCOUNT"] = account
    return env
```

Le token OAuth gccli est persisté dans le keyring file sous `self.home`.  
**Un seul home = un seul token = un seul compte Garmin connecté pour tous les users.**

### 2d. Bootstrap : login one-time, un seul compte

**Fichier :** `backend/garmin/bootstrap.py`

```python
account = get_secret("GARMIN_USERNAME", required=True)
password = get_secret("GARMIN_PASSWORD", required=True)
runner.login(account, password)
```

---

## 3. ÉTAT DES ROUTES GARMIN : ISOLATION USER_ID vs AUTHENTIFICATION

| Route | Paramètre `user_id` | JWT ? | Problème |
|---|---|---|---|
| `POST /api/garmin/connect` | Query param `user_id="default"` | ❌ NON | N'importe qui peut connecter n'importe quel user |
| `POST /api/garmin/sync` | Query param `user_id="default"` | ❌ NON | Idem |
| `GET /api/garmin/activities` | Query param `user_id="default"` | ❌ NON | Cross-user data leak possible |
| `GET /api/garmin/status` | Query param `user_id="default"` | ❌ NON | Idem |
| `POST /api/garmin/disconnect` | Query param `user_id="default"` | ❌ NON | Idem |
| `GET /api/garmin/daily-metrics` | Query param `user_id="default"` | ❌ NON | Idem |
| `POST /api/garmin/backfill` | Query param `user_id="default"` | ❌ NON | Idem |
| `GET /api/garmin/feed/stream` | Query param `user_id="default"` | ❌ NON | Idem |
| `POST /api/garmin/activity-signal` | Query param `user_id="default"` | ❌ NON | Idem |
| `GET /api/run-index` | `user["id"]` via JWT (`auth_user`) | ✅ OUI | OK (mais gccli lit données du compte global) |

**Contrairement** aux routes de `server.py` (`/api/workouts`, `/api/run-index`, etc.) qui utilisent toutes `user: dict = Depends(auth_user)` → `user["id"]`, **toutes les routes `garmin_router` prennent `user_id` en query param avec valeur par défaut `"default"`**.

---

## 4. FLUX COMPLET D'UN SYNC (état actuel, étape par étape)

```
1. POST /api/garmin/connect?user_id=<uid>
   → garmin_service.connect(db, user_id)
   → GccliProvider.connect(user_id)
      → runner.is_authenticated(GARMIN_USERNAME)  ← vérifie le token GLOBAL
      → si non: runner.login(GARMIN_USERNAME, GARMIN_PASSWORD)
   → MongoDB: garmin_connections.upsert({ user_id, connected: true, provider: "gccli" })
   → Redis: enqueue_sync(user_id)

2. sync_worker.py dépile la queue
   → garmin_service.sync(db, user_id)
   → Si premier sync + GARMIN_DEEP_SYNC_ENABLED=true: deep_sync(db, user_id)
      → provider.fetch_all_activities(page_size)  ← gccli paginé, COMPTE GLOBAL
   → Sinon: provider.sync_activities(user_id, since=...)  ← COMPTE GLOBAL
   → _ingest_activities(db, user_id, activities)
      → garmin_activities.upsert({ user_id, external_id, ... })
      → emit ACTIVITY_CREATED → Redis Stream (dédupe: uniquement si nouvel external_id)

3. event_worker.py consomme ACTIVITY_CREATED (groupe: workouts_fanout)
   → activity_to_workout(activity, user_id) → workouts.upsert({ user_id, id="garmin-{ext_id}" })
   → realtime_cache.update_feed(user_id, activity)  → Redis: runindex:feed:{user_id}

4. scheduler_worker.py (toutes les ~60s, avec leader lock Redis)
   → scan garmin_connections { connected: true }
   → Pour chaque user: scheduler.decide(now, active_signal_ts, last_activity_ts, last_sync_ts)
   → Si dû + hors cooldown: enqueue_incremental_sync(user_id)

5. GET /api/run-index (JWT obligatoire)
   → user_id = user["id"]
   → garmin_connections.find({ user_id })
   → garmin.insights.compute_run_index(db, user_id)
      → garmin_daily_metrics.find({ user_id }).sort("date", -1).limit(30)
      → garmin_activities.find({ user_id }).sort("start_time", -1).limit(200)
      → Calcul ACWR, CTL, ATL, TSB, fatigue_ratio, run_readiness (0-100)
      → Retour payload complet (metrics, history 7j, recommendation, next_workout)
```

---

## 5. ISOLATION DES DONNÉES EN BASE : DÉJÀ MULTI-USER ✅

La bonne nouvelle : **la couche données est déjà correctement isolée par user_id**. Tous les documents MongoDB ont un champ `user_id` et toutes les requêtes filtrent sur ce champ :

| Collection | Clé d'isolation |
|---|---|
| `garmin_connections` | `{ user_id }` |
| `garmin_activities` | `{ user_id, external_id }` (clé composite) |
| `garmin_daily_metrics` | `{ user_id, date }` |
| `workouts` | `{ user_id, id }` (id = `"garmin-{ext_id}"`) |
| Redis feed | `runindex:feed:{user_id}` |
| Redis pending | `sync_pending:{user_id}` |
| Redis lock | `sync_lock:{user_id}` |
| Redis active signal | `runindex:active_signal:{user_id}` |

---

## 6. VARIABLES D'ENVIRONNEMENT ACTUELLES (Garmin)

| Variable | Valeur par défaut | Rôle |
|---|---|---|
| `GARMIN_USERNAME` | — (required si session expirée) | Compte Garmin unique (global) |
| `GARMIN_PASSWORD` | — (required si login nécessaire) | Mot de passe Garmin unique (global) |
| `GARMIN_PROVIDER` | `""` | Doit valoir `"gccli"` pour le bootstrap |
| `GCCLI_PATH` | `"gccli"` | Chemin binaire gccli |
| `GCCLI_HOME` | `"/app/backend/.gccli_home"` | HOME gccli (token OAuth stocké ici) |
| `GCCLI_KEYRING_BACKEND` | `"file"` | Backend keyring (file = token sur disque) |
| `GCCLI_TIMEOUT` | `45` | Timeout par commande (s), clampé 15-60 |
| `GCCLI_MAX_RETRIES` | `3` | Retries avec backoff exponentiel |
| `GARMIN_PAGE_SIZE` | `50` | Taille de page pour deep sync |
| `GARMIN_INCREMENTAL_LIMIT` | `10` | Limite pour sync incrémental |
| `GARMIN_DEEP_SYNC_ENABLED` | `"true"` | Active le deep sync au 1er connect |

---

## 7. CE QUI DOIT CHANGER POUR LE STEP 3 (MULTI-USER)

### Problème 1 — Credentials Garmin : un seul compte global

**Situation actuelle :** `GARMIN_USERNAME` / `GARMIN_PASSWORD` = variables d'env globales.  
Toute l'app se connecte avec **un seul** compte Garmin Connect.

**Pour multi-user :** Chaque user RunIndex doit pouvoir connecter **son propre** compte Garmin. Il faut soit :
- Stocker les credentials Garmin chiffrés par user en base (modèle "vault" applicatif)
- Ou implémenter le vrai OAuth Garmin Connect (ne dépend plus de gccli)

### Problème 2 — GCCLI_HOME : un seul répertoire de token

**Situation actuelle :** Un seul `GCCLI_HOME` → un seul token OAuth gccli sur disque.

**Pour multi-user :** Chaque user doit avoir son propre HOME gccli isolé, ex :
```
/app/backend/.gccli_home/{user_id}/
```
Le `GccliRunner` dispose déjà d'un paramètre `account` dans `_env()` mais ne crée pas de HOME isolé par user. C'est le point d'extension naturel.

### Problème 3 — garmin_router : pas de JWT

**Situation actuelle :** Toutes les routes `/api/garmin/*` prennent `user_id` en query param, sans authentication.

**Pour multi-user sécurisé :** Remplacer `user_id: str = "default"` par `user: dict = Depends(auth_user)` → `user_id = user["id"]` sur chaque route (identique aux autres routes de `server.py`).

### Problème 4 — Factory lru_cache(maxsize=1)

**Situation actuelle :** Un seul provider singleton pour toute l'application.

**Pour multi-user :** Le provider (ou le runner) doit être instancié/paramétré par user_id, ou le `account` + `home` doivent être passés dynamiquement à chaque appel.

---

## 8. TABLEAU RÉCAPITULATIF — ÉTAT DE CHAQUE COMPOSANT

| Composant | Fichier | État pour multi-user |
|---|---|---|
| **Routes HTTP Garmin** | `backend/api/garmin.py` | ❌ Pas de JWT, `user_id` en query param |
| **Factory** | `backend/garmin/factory.py` | ❌ Singleton LRU mono-compte |
| **Provider** | `backend/garmin/providers/gccli_provider.py` | ❌ `_account()` = env global |
| **Runner** | `backend/garmin/runner.py` | ⚠️ `account` param existe mais HOME unique |
| **Bootstrap** | `backend/garmin/bootstrap.py` | ❌ Login one-time mono-compte |
| **Service orchestration** | `backend/garmin/service.py` | ✅ `user_id` propagé partout |
| **Insights / run-index** | `backend/garmin/insights.py` | ✅ Filtrage par `user_id` en Mongo |
| **Backfill** | `backend/garmin/backfill.py` | ✅ Par `user_id` |
| **MongoDB collections** | (toutes) | ✅ Déjà multi-user (filtrées par `user_id`) |
| **Event stream** | `backend/events/stream.py` | ✅ `user_id` propagé |
| **Feed cache Redis** | `backend/feed/realtime_cache.py` | ✅ Clé `runindex:feed:{user_id}` |
| **Sync worker** | `backend/workers/sync_worker.py` | ✅ Traite `user_id` de la queue |
| **Scheduler worker** | `backend/workers/scheduler_worker.py` | ✅ Itère tous les users connectés |
| **Route /api/run-index** | `backend/server.py` | ✅ JWT → `user["id"]` |
| **auth_user dependency** | `backend/server.py` | ✅ JWT HS256, `sub` = UUID user |
| **get_current_user** | `backend/auth/dependencies.py` | ✅ JWT + lookup MongoDB `users` |
