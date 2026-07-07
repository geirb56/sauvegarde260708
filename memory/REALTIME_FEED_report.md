# Quasi-Real-Time Feed (Strava-like) — Rapport

Date : 2026-07-05
Objectif : expérience "quasi temps réel" avec **sync batch incrémental uniquement**
(Garmin ne pousse pas en temps réel), scalable 10k users, sans Kafka, sans
microservices, sans toucher au Provider ni au frontend.

---

## Architecture (séparation stricte, event-driven)

```
gccli sync (worker) ──> garmin_activities   [SOURCE OF TRUTH, dedupe external_id]
                          │  emit ACTIVITY_CREATED
                          ▼
              Redis Stream cardiocoach:events:activity_created (MAXLEN 10k)
                          │  consumer group workouts_fanout
                          ▼
        event-worker (fan-out) ──> workouts  [couche produit/UI, dérivée]
                                └─> feed cache Redis cardiocoach:feed:{user}
```
Règle absolue respectée : **le sync worker n'écrit JAMAIS `workouts` directement**.
`garmin_activities` reste immuable ; `workouts` est dérivé et remplaçable.

---

## Livrables par tâche

| Tâche | Implémentation |
|---|---|
| 1. Incremental sync | `garmin/service.py::incremental_sync` (`since = last_activity_timestamp`, dedupe external_id) + `GccliProvider.sync_activities` (limite réduite `GARMIN_INCREMENTAL_LIMIT=10` + filtre `since`) |
| 2. Smart scheduler | `sync/scheduler.py` (pur : `classify_tier`/`is_due`/`decide` — ACTIVE 15min / NORMAL 2h / INACTIVE 24h) + `workers/scheduler_worker.py` (process dédié, leader-élu, scan enqueue seulement les users DUE) |
| 3. Event ingestion | `events/stream.py` (Redis Stream cappé + consumer group) ; `service._ingest_activities` émet `ACTIVITY_CREATED` par activité NOUVELLE |
| 4. Instant feed cache | `feed/realtime_cache.py` (`update_feed`/`warm_feed`/`get_feed`, liste Redis par user, MAXLEN 50, TTL 7j) |
| 5. Feed API | `GET /api/garmin/activities` : cache d'abord → Mongo fallback + warm ; param `since` incrémental ; rétrocompatible ; `<50ms` (cache) |
| 6. Worker pipeline | fetch → dedupe → write garmin_activities → emit event → fan-out (workouts + cache). `workers/event_worker.py` (consumer group, scalable) |
| 7. Anti-explosion | `sync/rate_limiter.py` : cap concurrence globale `GARMIN_GLOBAL_MAX_SYNCS=8` (compteur Redis) + cooldown per-user `SYNC_USER_COOLDOWN=900s` |
| 8. Perceived real-time | endpoint feed rapide + `POST /api/garmin/activity-signal` (marque ACTIVE via Redis, **sans sync/gccli**) → scheduler passe le user en tier ACTIVE (polling léger côté UI) |
| 9. Contraintes | zéro blocage FastAPI (tout enqueue) ; lourd dans les workers ; usage Garmin ≈ baseline (incrémental + cooldown) ; workers horizontalement scalables (consumer groups + leader locks) |

Nouveaux process supervisor : `event-worker` (priority 25), `scheduler-worker` (35).

---

## Tests

- `tests/test_sync_scheduler.py` → **ALL PASSED** (tiers, cadence due, cooldown,
  cap global, feed cache newest-first/since/warm).
- Testing agent (`test_reports/iteration_24.json`) : **14/14 PASSED** — sync
  non-bloquant, ingestion dedupe, fan-out Stream, feed cache, filtre `since`,
  activity-signal (pas de sync), cooldown, cap global, queue health, status.
- Non-régression : `test_reliable_queue`, `test_queue_health` toujours verts.

### Correctifs post-audit
- **Collision cross-user** : upsert `workouts` clé par `{id, user_id}` (les
  external_id partagés entre users ne s'écrasent plus).
- **Cache partiel** : `GET /activities` ne sert le cache que si `since` fourni ou
  `len(cache) >= limit`, sinon fallback DB + warm (jamais moins de résultats que
  la DB).

---

## Validation live
- `POST /sync` → `{status: queued}` (non bloquant) ; sync-worker ingère 30
  activités/user ; 123 événements consommés (lag=0) ; feed cache alimenté
  (boot1=30, default=n) ; cooldown 900s posé ; `GET /activities` → `source=cache`
  (5/5) ; `activity-signal` → `{status: ok, tier_hint: active}`.

## Notes / non-implémenté
- Backfill des `workouts` pour les activités ingérées AVANT ce changement non
  effectué (couche dérivée, régénérable en re-jouant un sync). Les nouvelles
  activités passent par le pipeline event-driven.
- Provider abstraction et frontend inchangés (conformément aux contraintes).

---

## SSE — couche de livraison temps réel (2026-07-05)
`GET /api/garmin/feed/stream?user_id=...` — Server-Sent Events, **lecture seule**.
- Pure couche de livraison : aucun sync, aucun gccli, aucune écriture DB.
- Consomme le Redis Stream via **XREAD non-destructif** (pas de consumer group)
  → le groupe fan-out reste intact, N clients / N instances lisent en parallèle
  (scalable horizontalement).
- **Reconnect-safe / idempotent** : reprise depuis l'en-tête `Last-Event-ID`
  (ou `?last_id=`) = id d'entrée du Stream ; aucun état serveur par client.
- Filtre par `user_id` ; frames `event: activity_created` + heartbeats `: ping`.
- Empreinte faible : 1 connexion Redis dédiée par flux (isolée du pool partagé),
  fermée à la déconnexion ; `feed/sse.py`.
- Modules/handler : `feed/sse.py::event_stream`, endpoint dans `api/garmin.py`.
- Tests `tests/test_sse.py` → **ALL PASSED** (livraison + filtrage user, reprise
  via Last-Event-ID sans replay). Vérifié en direct sur `localhost:8001` :
  `: connected` puis frame `id:/event: activity_created/data:` filtrée.

⚠️ **Limitation infra preview** : l'ingress du preview **bufferise** les réponses
streaming (le flux n'apparaît pas via l'URL externe, mais fonctionne en local).
En production, l'ingress/proxy doit désactiver le buffering pour `text/event-stream`
(l'en-tête `X-Accel-Buffering: no` est déjà envoyé pour nginx ; pour d'autres
proxys, régler `proxy_buffering off`).
