# Endpoint de monitoring `GET /api/garmin/queue/health` — Rapport

Date : 2026-07-02
Objectif : endpoint de supervision **lecture Redis seule** pour surveiller la
santé de la Reliable Queue en production. Aucune modification de la logique
métier ni du fonctionnement de la queue.

---

## 1. Format JSON

```json
{
  "status": "healthy",                 // "healthy" | "degraded" | "unhealthy"
  "redis_connected": true,             // bool — ping Redis réussi
  "queue_length": 0,                   // int  — jobs en attente de claim
  "processing_length": 1,              // int  — jobs en cours (in-flight)
  "active_workers": 2,                 // int  — heartbeats worker vivants
  "oldest_processing_seconds": 8,      // int  — âge du plus vieux job in-flight (0 si aucun)
  "orphans_recovered_total": 14,       // int  — cumul jobs re-queue par le watchdog
  "failed_jobs_total": 2,              // int  — cumul jobs en échec après max retries
  "timestamp": "2026-07-02T05:29:47.352663+00:00"  // ISO-8601 UTC
}
```

### Règles de statut

| Statut | Conditions |
|---|---|
| **HEALTHY** | Redis OK **et** `active_workers >= 1` **et** `oldest_processing < 96s` **et** `queue_length < 500` |
| **DEGRADED** | `queue_length >= 500` **ou** `oldest_processing >= 96s` |
| **UNHEALTHY** | Redis indisponible **ou** `active_workers == 0` **ou** `oldest_processing >= 120s` **ou** `queue_length >= 2000` |

Seuils : `96s = 0.8 × ORPHAN_TIMEOUT`, `120s = ORPHAN_TIMEOUT`. `500`/`2000`
fixes. Le suivi du *taux* de `failed_jobs_total` (« augmente rapidement ») est
laissé au système de scraping/alerting externe (Prometheus) : l'endpoint expose
le compteur brut mais reste sans état pour garantir < 10 ms.

---

## 2. Fichiers modifiés / ajoutés

| Fichier | Changement | Nature |
|---|---|---|
| `backend/jobs/health.py` | **nouveau** — `queue_health()` : 1 pipeline Redis + 1 SCAN heartbeats | lecture seule |
| `backend/api/garmin.py` | + route `GET /garmin/queue/health` (→ `/api/garmin/queue/health`) + docstring | additif |
| `backend/jobs/queue.py` | + constantes monitoring (`HEARTBEAT_*`, `STATS_*`) ; `INCRBY orphans_recovered` dans `recover_orphans` | instrumentation additive |
| `backend/workers/sync_worker.py` | + `heartbeat_loop` (SET TTL 15s toutes les 10s) ; `INCR failed_jobs` dans la branche échec terminal | instrumentation additive |
| `backend/tests/test_queue_health.py` | **nouveau** — 6 tests | test |

Aucune modification de : `BLMOVE`/`claim_job`/`ack_job`/`requeue_job`,
throttling, locks, dédup, retries, timeouts, provider gccli, service métier.

### Clés Redis de monitoring (écriture uniquement par le worker)
- `cardiocoach:worker:heartbeat:{pid}` — TTL 15s, rafraîchie toutes les 10s.
- `cardiocoach:stats:orphans_recovered` — INCR par le watchdog.
- `cardiocoach:stats:failed_jobs` — INCR sur échec terminal.

---

## 3. Coût CPU / RAM & performances

- **Endpoint** : 1 aller-retour Redis pipeliné (`LLEN`×2, `HGETALL claims`,
  `GET`×2) + un `SCAN MATCH heartbeat:* COUNT 100` (keyspace heartbeats minuscule,
  = nombre de workers). Aucune écriture, aucun accès Mongo.
  **Latence mesurée : moyenne 0.16 ms, max 0.18 ms** (serveur, 20 appels) → très
  en-deçà des 10 ms exigés.
- **Heartbeat worker** : 1 `SET` toutes les 10s par worker. Négligeable
  (~0.006 op/s/worker).
- **Compteurs** : 1 `INCR` seulement lors d'une récupération d'orphelin ou d'un
  échec terminal (événements rares).
- **RAM** : quelques octets par clé (N workers + 2 compteurs). Négligeable.

Impact sur le traitement des synchronisations : **nul** — le heartbeat et les
compteurs sont dans des tâches/branches séparées et best-effort (une erreur
d'instrumentation n'interrompt jamais un job).

---

## 4. Compatibilité

- Aucune signature d'API existante modifiée ; nouvelle route uniquement.
- Aucun changement côté frontend requis.
- Reliable Queue inchangée : les tests `test_reliable_queue.py` repassent
  **ALL PASSED** après ces ajouts (non-régression confirmée).

---

## 5. Validation des tests

`cd /app/backend && python -m tests.test_queue_health` → **ALL PASSED ✅**
(le worker live est stoppé pendant le test pour un contrôle déterministe des
heartbeats, puis relancé).

| Test | Résultat |
|---|---|
| Redis OK + queue vide + worker présent → healthy | ✅ |
| Redis indisponible → unhealthy, `redis_connected=false` | ✅ |
| Queue chargée (600 → degraded, 2100 → unhealthy) | ✅ |
| Worker absent (0 heartbeat) → unhealthy | ✅ |
| Récupération d'orphelin → `orphans_recovered_total` +1 | ✅ |
| Latence < 10 ms (avg 0.16 / max 0.18 ms) | ✅ |

Endpoint live vérifié : `{"status":"healthy","redis_connected":true,"active_workers":1,...}`.

---

## 6. Confirmation

✅ **Aucune logique métier modifiée.** Seules des écritures Redis de monitoring
(heartbeat + 2 compteurs INCR) et un endpoint en lecture seule ont été ajoutés.
Le comportement de la Reliable Queue, du worker et des synchronisations Garmin
est strictement identique.

## Note infra (résilience conteneur)
Le paquet `redis` (binaire + libs `liblzf`, `libjemalloc`) disparaît aux restarts
de conteneur. Persisté dans `/app` : binaires `/app/bin/redis-{server,cli}`, libs
`/app/lib/`, avec `LD_LIBRARY_PATH=/app/lib` dans le supervisor. Persistance AOF
dans `/app/data/redis`.
