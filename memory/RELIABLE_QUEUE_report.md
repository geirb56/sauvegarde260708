# Reliable Queue — Rapport final (livraison at-least-once)

Date : 2026-07-01
Portée : transformer la file Redis destructive (`BRPOP`) en **Reliable Queue**
garantissant qu'aucun job de synchronisation Garmin n'est perdu si un worker
crashe en plein traitement (`kill -9`) ou si Redis redémarre.

Contrainte respectée : **aucune réécriture d'architecture**, **pas de Celery**,
Redis natif uniquement (`BLMOVE` + liste `processing` + ACK + watchdog).

---

## 1. Mécanisme

Cycle de vie d'un job :

```
QUEUE (LPUSH) --BLMOVE(RIGHT→LEFT)--> PROCESSING --ACK(LREM)--> supprimé
                                          |
                        (worker crash, pas d'ACK)
                                          v
                        watchdog: si claim > ORPHAN_TIMEOUT  → requeue vers QUEUE
```

- `QUEUE_KEY` : file FIFO (`LPUSH` en tête, consommation par la queue RIGHT).
- `PROCESSING_KEY` : liste des jobs "en vol". Un job y reste du claim jusqu'à l'ACK.
- `CLAIMS_KEY` : hash `job_id → timestamp de claim`, lu par le watchdog.
- **ACK uniquement en cas de succès** (`ack_job` = `LREM` + `HDEL`). C'est le seul
  point qui retire définitivement un job. Un crash avant l'ACK = job conservé.
- **Watchdog** (`recover_orphans`) : scanne `PROCESSING`, re-pousse vers `QUEUE`
  tout job dont le claim dépasse `ORPHAN_TIMEOUT` (120 s). Un claim manquant est
  "adopté" (horodaté à maintenant) au lieu d'être récupéré immédiatement, pour ne
  pas doubler un worker qui vient tout juste de claim.
- **Idempotence** : `service.sync` fait des `upsert` Mongo → rejouer un job ne crée
  aucun doublon. C'est ce qui rend l'at-least-once sûr.

`ORPHAN_TIMEOUT` (120 s) > `JOB_TIMEOUT` (60 s) : un job légitime en cours n'est
jamais considéré comme orphelin.

---

## 2. Fichiers modifiés

| Fichier | Changement |
|---|---|
| `backend/jobs/queue.py` | + `claim_job` (BLMOVE), `ack_job`, `requeue_job`, `recover_orphans` |
| `backend/workers/sync_worker.py` | boucle passe de `BRPOP` à `claim_job` ; ACK sur succès ; requeue sur retry/lock ; `watchdog_loop` lancée au démarrage |
| `backend/jobs/redis_client.py` | `socket_timeout=None` (sinon `BLMOVE` bloquant lève un TimeoutError client) |
| `/etc/supervisor/conf.d/cardiocoach.conf` | Redis : `--appendonly yes --dir /app/data/redis` (persistance AOF pour survivre à un restart Redis) ; binaire pointé vers `/app/bin/redis-server` (persistant) |

Nouveaux fichiers de test :
- `backend/tests/test_reliable_queue.py`
- `backend/tests/_mock_worker.py` (worker factice qui claim + hang, pour le kill -9)

---

## 3. Résilience infra corrigée

Le binaire `/usr/bin/redis-server` disparaît à chaque restart de conteneur
(volatilité du paquet apt, seul `/app` persiste). Corrigé en copiant le binaire
dans `/app/bin/redis-server` et en pointant supervisor dessus. La persistance AOF
écrit dans `/app/data/redis` (persistant) → l'état de la file survit à un restart
Redis.

---

## 4. Tests — résultats

Lancer : `cd /app/backend && python -m tests.test_reliable_queue`
(le test stoppe le worker live pendant l'exécution puis le relance)

### Mock (isolé, ORPHAN_TIMEOUT=2 s) — ✅ ALL PASSED
- **TEST 1** kill -9 en plein job → job conservé dans `processing`, récupéré par le
  watchdog, **exactement 1** job re-poussé (même id) : aucune perte, aucun doublon.
- **TEST 2** succès normal → ACK retire le job exactement une fois, rien ne reste,
  pas de récupération fantôme.
- **TEST 3** restart Redis avec job en vol → job survit (AOF), récupéré ensuite.

### Réel (gccli, user `default`) — ✅
- Sync e2e via la file : claim → `sync_success` (30 activités, 7 métriques) → ACK.
- `kill -9` du worker réel juste après le claim : `queue=0 processing=1` → **job
  survit**. Watchdog à +120 s : `recovered orphan job id=d77cd... ` → rejeu →
  `sync_success`. Compte d'activités Mongo **inchangé (105)** → idempotent, zéro
  doublon.

---

## 5. Impact perf / compatibilité

- **Perf** : `BLMOVE` a le même coût qu'un `BRPOP` (O(1)). Overhead ajouté : 1 `HSET`
  au claim, 1 `LREM`+`HDEL` à l'ACK, et un scan `LRANGE processing` toutes les 30 s
  par le watchdog (liste courte en régime normal). Négligeable jusqu'à 1000 users.
- **Compatibilité** : signatures API inchangées (`POST /api/garmin/sync` renvoie
  toujours `{"status":"queued"}`). Dédup par user, locks et throttling conservés.
  Aucun changement côté frontend. Provider/gccli intacts.
- **Config** : `SYNC_ORPHAN_TIMEOUT` (120), `SYNC_WATCHDOG_INTERVAL` (30) via env.
