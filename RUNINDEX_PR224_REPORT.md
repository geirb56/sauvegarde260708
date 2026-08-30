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
  - creates/ensures unique partial index on `event_id` (`partialFilterExpression: {"event_id": {"$exists": true}}`),
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
