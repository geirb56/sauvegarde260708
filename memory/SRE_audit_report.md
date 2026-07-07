# CardioCoach — Audit SRE Robustesse & Scalabilité (2026-07-01)

> ⚠️ Correction : le backend utilise **MongoDB**, pas PostgreSQL. Les mesures ci-dessous portent sur MongoDB.
> Méthodologie charge : jobs enfilés pour des **user_ids distincts non connectés** → `service.sync()` revient vite ("not connected"), ce qui mesure l'**infra** (API/Redis/worker/Mongo/locks) sans marteler Garmin (compte gccli unique).

## 1. Charge (mesuré, localhost, sans ingress)

| Requêtes | Concurrence | Wall | Débit | p50 | p95 | p99 | HTTP | Queue après |
|---|---|---|---|---|---|---|---|---|
| 10 | 10 | 0.03s | 341/s | 28ms | — | — | 100% 200 | drainé |
| 50 | 50 | ~0.15s | 332/s | 146ms | — | — | 100% 200 | drainé |
| 100 | 100 | 0.25s | 404/s | 230ms | 245ms | 245ms | 100% 200 | drainé |
| 500 | 100 | 1.29s | 388/s | 244ms | 338ms | 342ms | 100% 200 | 0 |
| 1000 | 100 | 2.52s | 397/s | 249ms | 306ms | 342ms | 100% 200 | 0 |

- **Débit API plafond ≈ 400 req/s** (1 worker uvicorn, 2 ops Redis/req). 0 requête perdue jusqu'à 1000.
- Latence par requête isolée : **~2 ms** (mesurée hors burst). Les p50 ≈ 250ms ci-dessus = effet de burst (100 req simultanées sérialisées sur 1 event loop).
- **Débit worker (infra, no-op)** : drain de 500 jobs en 0.50s ≈ **~1000 jobs/s**.
- **Débit worker RÉEL (gccli, compte unique)** : ~4.9s/sync mesuré → sémaphore 5 ⇒ **~1 sync/s réelle** (plafond dominé par gccli + compte unique, pas par l'infra).
- CPU : négligeable au repos ; pics courts pendant les bursts. RAM : backend 27MB, worker 49MB, redis 12MB. Mongo : upserts, non saturé.

## 2. Concurrence (mesuré)
- **Dédup PROUVÉE** (worker arrêté, 50 req concurrentes même user) → **1 seul `queued`**, 29 `already_queued`, **queue = 1**, `sync_pending` posé. ✅
- **1 sync max/user** : verrou Redis `sync_lock:{uid}` en `SET NX EX` (atomique) → garantit le single-flight quel que soit le nombre de workers.
- **Locks toujours libérés** : après 5000+ jobs → **0 `sync_lock`, 0 `sync_pending`, 0 en queue**. ✅ Pas de course critique observée.

## 3. Résilience
- **Redis DOWN** → `/sync` renvoie **503 gracieux** (après correctif ; était 500). Backend reste debout. Reprise auto quand Redis revient → 200. ✅ *(Redis = SPOF de la feature sync.)*
- **Timeout gccli** : `asyncio.wait_for(60s)` au niveau job + timeout 15-60s/commande dans le runner + **3 retries backoff** dans le runner. ✅
- **gccli plante / erreur réseau** : le runner retente 3× (transitoire). Mais ⚠️ **`service.sync` avale l'échec final** (retourne `success:false`) → le **worker ne retente pas** une panne gccli persistante (comportement défendable : ne pas boucler sur une connexion cassée, mais pas de requeue).
- **Crash brutal du worker (kill -9) mid-job** : ⚠️ **BUG MAJEUR** — le job consommé par `BRPOP` est **retiré de Redis avant traitement** (pas de `BRPOPLPUSH`/liste de traitement) → **job en cours PERDU** sur crash brutal. Le verrou expire seul (TTL 120s, pas de lock fantôme) ; mais le `sync_pending` (TTL 300s) bloque un re-enqueue jusqu'à 5 min.
- **Aucun lock fantôme** (TTL) ✅. **Retries** fonctionnels ✅.

## 4. Long run (mesuré)
- ~5000+ jobs sur la session. **Aucune fuite mémoire** (backend 28→27MB, worker 48→49MB). **Aucune fuite de FD** (backend 10, worker 11). Pas de ralentissement progressif observé. ✅

## 5. Multi-workers
- Le verrou par-user (`SET NX EX`) + dédup garantissent **aucune double sync** quel que soit le nombre de workers.
- Équilibrage : `BRPOP` sur une file partagée = répartition naturelle FIFO entre workers. Pas de deadlock (pas de verrous imbriqués).
- ⚠️ Combiné au point §3 : ajouter des workers augmente le risque de **jobs perdus** sur crash tant que la file n'est pas fiabilisée (BRPOPLPUSH).

## 6. Scheduler
- Implémenté, **désactivé par défaut** (`SYNC_SCHEDULE_INTERVAL=0`). Enfile tous les users connectés avec **étalement** (`SCHEDULE_STAGGER_MS=200`) → 1000 users = ~200s d'enfilage, pas de thundering herd. Dédup empêche l'emballement (un cycle en cours n'est pas ré-enfilé). ✅ *(non exécuté à 1000 users réels ici — compte gccli unique).*

## 7. Sécurité (mesuré)
- Scan de **4904 lignes** de logs worker + backend → **aucun mot de passe, token ou secret** en clair. ✅
- L'UI n'accepte aucun credential Garmin (couche connect = user_id seul).

## 8. Rapport final

### Bugs / risques
- 🔴 **MAJEUR — perte de job sur crash worker** : `BRPOP` destructif sans liste de traitement. Fix reco : `LMOVE queue processing` (reliable queue) + reprise des orphelins. (Non corrigé : dépasse la "correction minimale".)
- 🟠 **MAJEUR — Redis = SPOF** : sync indisponible si Redis tombe (503 propre désormais, mais pas de HA). Reco prod : Redis managé/répliqué.
- 🟠 **MAJEUR (environnement) — binaire Redis non persistant** : `redis-server` installé via apt **disparaît** dans ce conteneur (seul `/app` persiste). Reco prod : Redis managé, jamais apt-in-container.
- 🟡 **MINEUR — pas de retry worker sur panne gccli persistante** (`service.sync` avale l'erreur). À décider : requeue borné vs statut d'échec exposé.
- 🟡 **MINEUR — message 429 trompeur** : affiche les stats/minute alors que c'est le **burst** (30/2s/user) qui déclenche. Ajouter le motif "burst" au payload.
- 🟡 **MINEUR — `sync_pending` TTL 300s** peut bloquer un re-enqueue après un job perdu (réduire le TTL ou le supprimer au moment du LMOVE).
- 🟢 Rate limit **par-user** en mémoire = **par-process** (non global si plusieurs uvicorn). OK à petite échelle, à externaliser (Redis) si multi-instances.

### Correctifs minimaux appliqués pendant l'audit
- ✅ Dégradation gracieuse **503** quand Redis est down (au lieu de 500) sur `/sync` ; `/connect` ne casse plus si l'enfilage échoue.

### Capacité estimée (avant évolution d'archi)
| Users | Verdict |
|---|---|
| **100** | ✅ Confortable. gccli compte unique = goulot si sync fréquentes ; sinon OK. |
| **1 000** | 🟡 **Tenable pour l'enfilage/API** (400 req/s prouvés). Goulot réel = **1 sync/s** (gccli + compte unique + sémaphore 5). Sync quotidienne de 1000 users = ~17 min : OK si étalé. Nécessite Redis fiabilisé (reliable queue) et Redis managé. |
| **10 000** | 🟠 Nécessite : multi-comptes gccli **ou** agrégateur (Terra), reliable queue, plusieurs workers, Redis managé, rate-limit externalisé. |
| **50 000** | 🔴 Changement d'architecture requis : agrégateur officiel (Terra/Garmin), workers horizontaux, sharding, monitoring. gccli ne tient pas à cette échelle. |

### Verdict production
**Prête pour un lancement contrôlé jusqu'à ~1 000 utilisateurs**, à 2 conditions :
1. **Redis managé/persistant** (jamais apt-in-container).
2. **Fiabiliser la file** (`LMOVE`/reliable queue) pour éliminer la perte de job sur crash — recommandation #1 avant d'ajouter des workers.

Au-delà de ~1 000 users actifs avec sync fréquentes, le **compte gccli unique** (et non l'infra async) devient le facteur limitant → basculer vers le multi-compte ou l'agrégateur officiel (le `Provider` abstrait le permet sans refactor métier).

### Recommandations classées (impact / coût)
1. 🔴 Reliable queue `LMOVE` + reprise orphelins — *fort impact / coût moyen*.
2. 🟠 Redis managé (HA) — *fort impact / coût faible*.
3. 🟠 Plan de connexion multi-compte / TerraProvider derrière le `Provider` — *fort impact / coût moyen-élevé* (requis >1k).
4. 🟡 Externaliser le rate-limit dans Redis (multi-instances) — *moyen / faible*.
5. 🟡 Politique de retry explicite sur panne gccli + payload 429 clarifié — *faible / faible*.
