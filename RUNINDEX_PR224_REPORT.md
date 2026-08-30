# RUNINDEX — PR #224 corrective report

## Start point (source of truth)
- Base branch audited: `copilot/dev`
- Start HEAD after merge PR #223: `30422bd8530db4a5b4ba09af20df451fb606636c`

## Modified files
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/server.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/subscription_manager.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/services/paddle_event_index.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_paddle_integrity_pr223.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_paddle_recovery_pr224.py`

## Behavior before
- Legacy `paddle_events` documents without `status` could raise `RuntimeError` in `_claim_paddle_event()`.
- `status=processing` could stay locked forever if worker died after claim.
- Startup used direct `create_index("event_id", unique=True)` without dedup/index-shape migration.
- `cancel_subscription()` could parse a legacy timezone-less ISO value to naive `datetime` and compare it with UTC-aware `now`, raising `TypeError`.

## Behavior after
- `_claim_paddle_event()` recovers legacy/missing/unknown statuses with atomic compare-and-set reclaim instead of raising runtime errors.
- `processing` claims use an explicit lease (`PADDLE_EVENT_PROCESSING_LEASE_SECONDS`, default `900s`, min `60s`): fresh claims stay locked, stale claims are atomically reclaimable.
- Invalid or missing `claimed_at` is treated fail-safe as stale and reclaimable, still atomically.
- Startup now uses `ensure_paddle_events_unique_index()` helper:
  - deduplicates duplicate `event_id` groups first,
  - archives loser documents into `paddle_events_dedup_archive`,
  - drops incompatible `event_id` indexes,
  - migrates legacy `event_id=""` out of indexed scope via `$unset` (no document deletion),
  - creates/ensures unique partial index on `event_id` (`partialFilterExpression: {"event_id": {"$type": "string"}}`),
  - remains idempotent on repeated startup.
- `cancel_subscription()` now normalizes expiry values to UTC-aware datetimes before comparison and persistence.

## Deduplication strategy
- Scope: only documents with non-null `event_id`.
- Winner is deterministic:
  1. status priority `processed > processing > failed > legacy/other`,
  2. then newest timestamp among `processed_at`, `failed_at`, `claimed_at`, `updated_at`, `occurred_at`,
  3. then lowest `_id` lexical tie-break.
- Losers are archived (`paddle_events_dedup_archive`) with winner/loser metadata before deletion from `paddle_events`.

## Processing lease choice
- Lease timeout: `900 seconds` (15 minutes), configurable by env var `PADDLE_EVENT_PROCESSING_LEASE_SECONDS`.
- Justification: long enough for normal webhook processing and short enough to recover abandoned claims automatically.

## Tests run (exact commands and exact results)
1. `cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && python -m pytest tests/test_paddle_recovery_pr224.py`
   - Result: `11 passed in 0.45s`

2. `cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && python -m pytest tests/test_paddle_recovery_pr224.py tests/test_paddle_integrity_pr223.py tests/test_unique_subscription.py`
   - Result: `74 passed, 12 warnings in 1.57s`

3. `cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && MONGO_URL='mongodb://localhost:27017' DB_NAME='test_db' ENVIRONMENT='test' JWT_SECRET='test-secret-32chars-long........' JWT_SECRET_KEY='test-secret-32chars-long........' python -m pytest tests/test_subscription_middleware_a63.py`
   - Result: `24 passed in 1.00s`

## Post-merge #223 findings addressed
- Legacy `paddle_events` compatibility fixed.
- Stale `processing` reclaim with atomic safety added.
- Startup unique-index migration hardened and idempotent.
- UTC aware normalization enforced on cancellation expiry path.

## Commit(s)
- `7fb4a39` — Paddle claim/index/datetime core fixes
- `ce2cc9e` — report + shared datetime helper integration

## Pull request
- Title: `PR #224 — Paddle legacy event recovery and safe idempotency index migration`
- Base: `copilot/dev`
- URL: `https://github.com/geirb56/sauvegarde260708/pull/224`

---

## C224 follow-up (post-audit changes requested)

### HEAD réel avant correction C224
- `de76478a9e3c5b244d37105daaa2dbcc089c2131`

### HEAD final C224
- `3710b02fad4f734bd2122b27d411b1df876481b2`

### Root cause occurred_at race
- Le webhook faisait une décision stale/non-stale via lecture séparée (`find_one`) avant mutation.
- Deux événements différents pouvaient lire le même `paddle_last_event_at` historique, puis écrire hors ordre.

### Design CAS atomique appliqué
- Le CAS `occurred_at` est maintenant dans le filtre Mongo des mutations subscription (dans `subscription_manager`), pas en pré-check séparé.
- Condition atomique: update autorisé seulement si:
  - `paddle_last_event_at` absent/null, ou
  - `paddle_last_event_at < occurred_at`, ou
  - `paddle_last_event_at == occurred_at` avec tie-break déterministe `paddle_last_event_id <= event_id`.
- Le webhook n’utilise plus `_is_stale_subscription_event()`; la décision stale provient du résultat CAS des helpers.

### Comportement égalité occurred_at
- Égalité autorisée uniquement avec tie-break stable sur `event_id` (ordre lexical croissant, donc le plus grand `event_id` reste gagnant final).
- Ce choix est explicite et testé avec deux `event_id` distincts au même `occurred_at`.

### Startup fail-fast index critique Paddle
- `ensure_paddle_events_unique_index()` est exécuté **hors** du grand bloc warning-only.
- Si migration/dedup/archive/drop/create/vérification finale échoue: startup échoue (fail-fast).

### Vérification finale de l’index
- Après création/migration, le helper relit les indexes et exige:
  - clé `event_id`,
  - `unique=True`,
  - `partialFilterExpression={"event_id": {"$type": "string"}}`.
- Sinon, exception explicite (startup fail).

### Stratégie event_id=null / legacy
- Le partial unique index cible les `event_id` de type string.
- Les legacy `event_id=""` sont migrés avant création d’index via `$unset` de `event_id` (documents conservés).
- Les documents sans `event_id` ou `event_id=null` restent hors contrainte unique et ne bloquent pas le startup.
- La déduplication ne traite que les vrais `event_id` utilisables (string non vide).

### Fichiers modifiés (C224 follow-up)
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/server.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/subscription_manager.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/services/paddle_event_index.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_paddle_integrity_pr223.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_paddle_recovery_pr224.py`

### Tests exécutés (commandes exactes + résultats exacts)
1. `cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && python -m pytest tests/test_paddle_integrity_pr223.py -k 'concurrent or equal_occurred or startup_fails_fast' -vv`
   - Résultat: `6 passed, 12 warnings in 1.67s`

2. `cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && python -m pytest tests/test_paddle_integrity_pr223.py`
   - Résultat: `31 passed, 12 warnings in 1.81s`

3. `cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && python -m pytest tests/test_paddle_recovery_pr224.py`
   - Résultat: `20 passed in 1.48s`

4. `cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && python -m pytest tests/test_unique_subscription.py`
   - Résultat: `37 passed in 1.43s`

5. `cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && MONGO_URL='mongodb://localhost:27017' DB_NAME='test_db' ENVIRONMENT='test' JWT_SECRET='test-secret-32chars-long........' JWT_SECRET_KEY='test-secret-32chars-long........' python -m pytest tests/test_subscription_middleware_a63.py`
   - Résultat: `24 passed in 1.97s`

6. `cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && MONGO_URL='mongodb://localhost:27017' DB_NAME='test_db' ENVIRONMENT='test' JWT_SECRET='test-secret-32chars-long........' JWT_SECRET_KEY='test-secret-32chars-long........' python -m pytest tests/test_paddle_subscription.py tests/test_subscription_trial.py`
   - Résultat: `4 failed, 41 passed, 13 warnings, 2 errors in 1.64s`
   - Détail: échecs/errors préexistants frontend/source assertions + `REACT_APP_BACKEND_URL missing`.

### Runtime
- Runtime réel backend + webhooks Paddle en environnement live: **NON TESTÉ** dans cette tâche.

---

## C224 blocker final — MongoDB partialFilterExpression valid

### Correction appliquée
- `partialFilterExpression` final: `{"event_id": {"$type": "string"}}` (MongoDB valide).
- Aucune utilisation de `$ne` dans la spec d’index.
- Migration pré-index des docs legacy `event_id=""` par `$unset` de `event_id` (aucune suppression de document).
- `event_id=null` et `event_id` absent restent hors index.
- Déduplication + archivage limités aux vrais `event_id` string non vides.
- Vérification post-création conservée (relecture index + clé/event_id + unique + partial exact), startup fail-fast conservé.

### Fichiers modifiés pour ce blocker
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/services/paddle_event_index.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_paddle_recovery_pr224.py`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/RUNINDEX_PR224_REPORT.md`

### Tests exacts (cette correction)
1. `cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && python -m pytest tests/test_paddle_recovery_pr224.py tests/test_paddle_integrity_pr223.py tests/test_unique_subscription.py`
   - Résultat: `90 passed, 12 warnings in 2.65s`

2. `cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && MONGO_URL='mongodb://localhost:27017' DB_NAME='test_db' ENVIRONMENT='test' JWT_SECRET='test-secret-32chars-long........' JWT_SECRET_KEY='test-secret-32chars-long........' python -m pytest tests/test_paddle_subscription.py tests/test_subscription_trial.py`
   - Résultat: `4 failed, 41 passed, 13 warnings, 2 errors in 1.66s`

### Clarification “4 failed / 2 errors” (noms exacts)
**FAILED**
- `tests/test_paddle_subscription.py::TestFrontendFailClosed::test_error_fallback_is_free_not_trial`
- `tests/test_paddle_subscription.py::TestFrontendFailClosed::test_error_fallback_features_are_disabled`
- `tests/test_paddle_subscription.py::TestWebhookIdempotence::test_paddle_webhook_checks_event_id`
- `tests/test_paddle_subscription.py::TestVerifyCheckoutDisabled::test_endpoint_returns_410_in_source`

**ERROR**
- `tests/test_subscription_trial.py` import-time assertion: `REACT_APP_BACKEND_URL missing` (x2 workers)

### Vérification sur base `copilot/dev`
Commande exécutée sur worktree base (`/tmp/pr224_basecheck`):
- `cd /tmp/pr224_basecheck/backend && MONGO_URL='mongodb://localhost:27017' DB_NAME='test_db' ENVIRONMENT='test' JWT_SECRET='test-secret-32chars-long........' JWT_SECRET_KEY='test-secret-32chars-long........' python -m pytest tests/test_paddle_subscription.py tests/test_subscription_trial.py`
- Résultat: **même statut** `4 failed, 41 passed, 13 warnings, 2 errors in 1.90s`
- Conclusion: ces 4 fails + 2 errors sont aussi présents sur `copilot/dev` (préexistants, non introduits par PR224).

### Test MongoDB réel
- `REAL_MONGODB_INDEX_TEST=NOT RUN`
- Raison: `ServerSelectionTimeoutError` (localhost:27017 refusé).
