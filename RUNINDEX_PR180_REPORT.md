# RUNINDEX PR#180 — Hotfix: Circular Import garmin.service ↔ garmin.backfill

```
BASE_BRANCH  = copilot/dev
HEAD_START   = 56412edbc33cd9cf4f951d294f7d9e05284e6d68
HEAD_FINAL   = (set after merge)

ROOT_CAUSE   = circular import garmin.service <-> garmin.backfill
               backfill.py imported `activity_to_workout` at module level;
               service.py imports the backfill mechanism → cycle at boot.

FIX          = lazy import activity_to_workout inside backfill_user
               `from .service import activity_to_workout` moved from top-level
               to the body of `async def backfill_user(...)`.
```

## Import smoke tests

```
SERVICE_IMPORT        = PASS
BACKFILL_IMPORT       = PASS
REVERSE_IMPORT_ORDER  = PASS
SERVER_IMPORT         = PASS
```

## Invariants

```
BACKFILL_BEHAVIOR_CHANGED  = NO
RUNINDEX_SOURCE_CHANGED    = NO
RUNINDEX_FORMULA_CHANGED   = NO
WORKOUT_SELF_HEAL_CHANGED  = NO
READINESS_CHANGED          = NO
TRAINING_V2_CHANGED        = NO
FRONTEND_CHANGED           = NO
LOCKFILES_CHANGED          = NO
```

## Tests

```
tests = pending runtime smoke
```

## Runtime smoke

```
RUNTIME_SMOKE = NOT_RUN  (requires live environment)
```

## Diff

Only file changed: `backend/garmin/backfill.py`
- Removed top-level: `from .service import activity_to_workout`
- Added inside `backfill_user`: `from .service import activity_to_workout`

No other file modified.

## Verdict

READY FOR MERGE INTO copilot/dev — pending runtime smoke PASS on live environment.
