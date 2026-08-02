# Plan — Workers Garmin sur Railway + Redis Upstash (backend/front sur Emergent)

> **Préparation / analyse uniquement.** Aucun déploiement, aucune modification irréversible.
> Paddle / Auth / Stripe **non touchés**. Date : 2 août 2026.
>
> Cible : Emergent (frontend + backend FastAPI) · Upstash (Redis via `REDIS_URL`) ·
> Railway (1 seul service qui exécute sync + event + scheduler + monitor).

---

## 0. Compatibilité avec le code actuel — verdict

| Élément | Compatible tel quel ? | Détail |
|---|---|---|
| Redis externe partagé | ✅ | `jobs/redis_client.py` et chaque worker lisent `REDIS_URL` (`aioredis.from_url`). Upstash = TLS → `rediss://`. Backend (enqueue + SSE) et workers doivent pointer sur le **même** Upstash. |
| Queue fiable / retry / idempotence | ✅ | `jobs/queue.py` : LPUSH + `BLMOVE` (queue→processing), ACK `LREM`, watchdog `recover_orphans`, retries backoff, dedupe `sync_pending`, lock par user. Sémantique at-least-once + upserts idempotents → OK sur Redis distant. |
| Isolation utilisateur | ✅ | Tout est scoping `user_id` (Mongo + clés Redis `sync_lock:{user_id}`, feed cache par user). Inchangé. |
| SSE temps réel | ✅ (côté backend) | `/api/garmin/feed/stream` tourne **sur le backend Emergent** et lit le Redis Stream Upstash (`feed/sse.py` → `xread`). `event_worker` (Railway) écrit `workouts` + warm feed cache. Les deux via Upstash. |
| event / scheduler / monitor workers | ✅ | Ne touchent PAS gccli. Purement Mongo+Redis. scheduler & monitor ont un **leader-lock Redis** → sûr même en 1 seule instance. |
| **sync_worker (gccli)** | ❌ **BLOCKER** | Voir §1. La session gccli créée au `/connect` vit sur le **disque local du backend Emergent** (`GCCLI_HOME/{user_id}`). Un worker Railway (autre conteneur/FS) ne l'a pas → sync « not authenticated ». |
| 1 seul service Railway pour les 4 workers | ✅ (fichier ajouté) | Chaque worker expose `async def main()` ; nouvel entrypoint `workers/run_all.py` les lance ensemble (asyncio.gather + restart). |

**Conclusion :** l'architecture est compatible à **~90 %** immédiatement. Le **seul vrai blocker**
est le **partage de la session gccli** entre le backend (login) et le worker sync (Railway).
Sans le résoudre, la synchro Garmin ne fonctionnera pas en prod. Solutions en §1.

---

## 1. Changements de code nécessaires

### 1.A — CRITIQUE : partager la session gccli backend ↔ worker (à implémenter)
Cause : `/api/garmin/connect` (backend Emergent) fait le login gccli et persiste un **token
OAuth** dans `GCCLI_HOME/{user_id}/` (disque local). `sync_worker` (Railway) appelle
`get_provider_for_user(user_id)` qui lit ce même dossier — **absent** sur Railway.

Solution recommandée (minimale, sans OAuth officiel, sans toucher Auth/Paddle) :
**persister la session gccli dans MongoDB et l'hydrater côté worker.**

1. Après un login réussi dans `garmin/service.connect(...)` : sérialiser le contenu de
   `GCCLI_HOME/{user_id}/` (fichiers keyring/token — petits) → stocker en base
   (`garmin_sessions` : `{user_id, files: {relpath: base64}, updated_at}`), chiffré au repos.
2. Dans `garmin/factory.get_provider_for_user(user_id)` **côté worker** (ou au début de
   `service.sync`) : si `GCCLI_HOME/{user_id}/` est vide, **hydrater** depuis `garmin_sessions`
   avant d'appeler gccli. Après un refresh de token par gccli, ré-écrire la session en base.
3. Alternative si un **Volume partagé** est acceptable : monter un stockage réseau commun — non
   applicable entre Emergent et Railway (FS séparés) → la voie DB est la bonne.

> Impact : ~1 helper `garmin/session_store.py` + 2 points d'appel (connect / avant sync).
> Aucune modification d'Auth/Paddle/Stripe. À faire avant que la synchro prod fonctionne.
> ⚠️ Non implémenté ici (ce livrable est un plan) — à valider avec vous avant écriture.

### 1.B — Runner unique pour Railway (déjà ajouté, additif, non déployé)
- **`backend/workers/run_all.py`** (créé) : lance `sync/event/scheduler/monitor` `main()` en
  parallèle dans un seul process, avec restart automatique par worker.
  Démarrage : `python -m workers.run_all` (cwd `/app/backend`).

### 1.C — Aucune autre modification requise
`queue.py`, `redis_client.py`, workers, SSE : **inchangés**. Ils lisent déjà `REDIS_URL`/`MONGO_URL`
depuis l'environnement. Rien à modifier pour pointer vers Upstash.

### 1.D — Point d'attention Upstash (comportement, pas code)
- `BLMOVE`/`XREAD BLOCK` (blocking) sont supportés par Upstash mais **consomment des commandes en
  continu** → sur l'offre gratuite (quota de requêtes/jour), le polling permanent peut épuiser le
  quota. Prévoir un plan payant Upstash pour la prod, ou augmenter `timeout` des BLMOVE.
- `socket_timeout=None` (déjà en place) est requis pour ne pas couper les commandes bloquantes.

---

## 2. Configurations Upstash / Railway à créer

### 2.A — Upstash (Redis)
1. Créer un compte → **Create Database** (type *Redis*), région proche du backend Emergent.
2. Activer **TLS** (par défaut). Récupérer l'URL de connexion **`rediss://default:<PASSWORD>@<host>:6379`**.
3. (Prod) choisir un plan adapté au trafic bloquant (pas seulement free tier).

### 2.B — Railway (workers)
1. **New Project → Deploy from GitHub repo** (`geirb56/sauvegarde260708`, branche voulue).
2. Service unique « **garmin-workers** » :
   - Build : **Dockerfile** = `deploy/railway/Dockerfile.worker` (fichier ajouté), build context = racine du repo.
   - Pas de port public (worker only).
3. Ajouter un **Volume** monté sur **`/data/gccli`** (persistance des sessions gccli locales / cache).
4. Renseigner les variables (voir §3 et `deploy/railway/.env.worker.example`).
5. (Optionnel) health/`autorestart` : Railway redémarre le service en cas de crash.

### 2.C — Emergent (backend)
- Ajouter la **même** `REDIS_URL` Upstash dans l'environnement de prod du backend Emergent
  (le backend enqueue les jobs et sert le SSE en lisant Upstash).

---

## 3. Variables à renseigner

### Backend Emergent (prod)
| Variable | Valeur |
|---|---|
| `REDIS_URL` | `rediss://default:<pwd>@<host>.upstash.io:6379` (Upstash) |
| `MONGO_URL`, `DB_NAME` | fournis par Emergent (managé) |
| `PADDLE_*` (5) | déjà configurés — à reporter en prod (inchangé) |

### Service Railway « garmin-workers »
| Variable | Valeur |
|---|---|
| `REDIS_URL` | **identique** à celle du backend (même Upstash) |
| `MONGO_URL` | **même** cluster Mongo que le backend prod |
| `DB_NAME` | même valeur que le backend |
| `GCCLI_HOME` | `/data/gccli` (= point de montage du Volume) |
| `GARMIN_PROVIDER` | `gccli` |
| `SYNC_MAX_CONCURRENCY` / `SYNC_JOB_TIMEOUT` / `SYNC_MAX_RETRIES` | optionnels (défauts OK) |
| `SYNC_SCHEDULE_INTERVAL` | `0` (le scheduler_worker gère déjà la planification) |

> ⚠️ `MONGO_URL` Railway doit pointer sur **la même base que la prod Emergent**. Si Emergent
> n'expose pas d'URL Mongo externe, il faudra une base Mongo accessible des deux (ex. MongoDB Atlas)
> — à valider (voir §5 Risques).

---

## 4. Étapes manuelles exactes

1. **Upstash** : créer la DB Redis → copier `rediss://…`.
2. **Emergent** : ajouter `REDIS_URL` (Upstash) aux variables de prod du backend → redeploy backend.
3. **(Code) implémenter 1.A** (partage session gccli via Mongo) — je le fais sur votre feu vert.
4. **GitHub** : « Save to Github » pour que `workers/run_all.py` + `deploy/railway/*` + le code 1.A
   soient dans le repo (Railway déploie depuis GitHub).
5. **Railway** : New Project → repo → service « garmin-workers » → Dockerfile `deploy/railway/Dockerfile.worker`.
6. **Railway** : ajouter le **Volume** `/data/gccli`.
7. **Railway** : coller les variables (§3) → Deploy.
8. Vérifier les logs Railway : `[run_all] starting worker=sync/event/scheduler/monitor`.
9. Lancer les tests (§5).

---

## 5. Tests à effectuer

### Connectivité / démarrage
- [ ] Backend Emergent prod : `GET /api/garmin/queue/health` → répond, `active_workers ≥ 1`
      (le heartbeat des workers Railway remonte via Upstash).
- [ ] Logs Railway : 4 workers démarrés, aucun crash-loop.
- [ ] `redis-cli -u $REDIS_URL PING` → `PONG` (depuis un shell local).

### Flux queue → sync → workouts (après 1.A implémenté)
- [ ] Un user connecte Garmin (backend Emergent) → `garmin_sessions` créé en Mongo.
- [ ] `POST /api/garmin/sync` (backend) → job dans `runindex:garmin:queue` (Upstash).
- [ ] Le **sync_worker Railway** hydrate la session, exécute gccli, écrit `garmin_activities`.
- [ ] `ACTIVITY_CREATED` (Redis Stream) consommé par **event_worker** → `workouts` créés + feed cache.
- [ ] `GET /api/garmin/activities` (user premium/trial) → activités visibles.

### Fiabilité / idempotence / isolation
- [ ] Tuer le service Railway pendant un sync → au redémarrage, le **watchdog** requeue l'orphelin
      (job non perdu), et le re-run n'introduit pas de doublons (upserts).
- [ ] 2 users en parallèle → aucune fuite croisée (données scoping `user_id`).
- [ ] `sync_lock:{user_id}` empêche 2 syncs simultanés du même user.

### SSE
- [ ] Ouvrir `GET /api/garmin/feed/stream` (backend Emergent) ; déclencher un sync ⇒ un event SSE
      arrive en quasi temps réel (produit par event_worker via Upstash).

### Scheduler / Monitor (leader-lock)
- [ ] 1 seule instance → scheduler enqueue des incrémentaux pour les users « due ».
- [ ] monitor : `queue/health` reflète l'état ; pas de spam d'alertes.

### Non-régression (à vérifier inchangés)
- [ ] Paddle : `configured:true`, checkout OK. Auth (JWT/Google/Apple) OK. **Aucune modif.**

---

## Risques / points ouverts
1. **Session gccli (1.A)** = prérequis dur ; sans lui, sync prod KO. À implémenter.
2. **Mongo partagé** : Railway et Emergent doivent écrire la **même** base. Si Emergent n'expose pas
   d'URL Mongo externe, prévoir MongoDB Atlas accessible des deux (décision infra).
3. **Upstash quotas** : commandes bloquantes permanentes → prévoir un plan payant.
4. **gccli sur Railway** : login réel dépend toujours du compte Garmin de l'utilisateur (MFA/anti-bot),
   limite intrinsèque déjà documentée.
5. **Coût/latence** : Emergent↔Upstash↔Railway = 3 réseaux ; latence acceptable pour de la sync async.

## Fichiers ajoutés par cette préparation (additifs, non déployés, réversibles)
- `backend/workers/run_all.py` — runner unique des 4 workers.
- `deploy/railway/Dockerfile.worker` — image du service Railway.
- `deploy/railway/.env.worker.example` — gabarit des variables Railway.
- `RAILWAY_WORKERS_PLAN.md` — ce document.

Aucun fichier existant modifié ; Paddle/Auth/Stripe intacts ; rien de déployé.
