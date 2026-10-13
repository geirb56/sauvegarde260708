# PR195 — Garmin Native VO₂max — Final Architecture (V2)

## Summary

PR #195 introduces **native Garmin running VO₂max** import from `gccli health
max-metrics`.  This document describes the final persistence model adopted in
the `CORRECTION FINALE APRÈS C195 BIS` commit.

---

## Persistence Model

### Collection: `garmin_vo2max`

Each document represents **one real Garmin measurement** at a specific date.

| Field | Type | Description |
|---|---|---|
| `user_id` | string | RunIndex user identifier |
| `date` | string (YYYY-MM-DD) | Canonical measurement date from `calendarDate` |
| `vo2max_running` | float | Rounded value from `vo2MaxValue` |
| `vo2max_running_precise` | float or null | Precise value from `vo2MaxPreciseValue` |
| `source` | string | Always `"garmin"` |
| `sport` | string | Always `"running"` |
| `updated_at` | ISO-8601 string | Last write timestamp |

### Unique key

```
(user_id, date)
```

`update_one` uses this composite filter with `upsert=True`.  A new measurement
on a **different date** creates a new document; a second sync for the **same
date** updates the existing one.  An older measurement is never overwritten by
a newer one.

### Index recommendation

A unique index on `(user_id, date)` prevents duplicate documents at the
database level and enables the `sort([("date", -1)])` query to run efficiently:

```python
db.garmin_vo2max.create_index(
    [("user_id", 1), ("date", 1)],
    unique=True,
    background=True,
)
```

This index is **not created in this PR** (no migration infra); it should be
added as a follow-up operational step.

---

## Design Rules

### No scalar overwrite

`update_one({"user_id": user_id}, ...)` — the old "scalar per user" approach
— has been **removed**.  Every persisted point is keyed by `(user_id, date)`.

### No fabricated date

If `calendarDate` is absent from the Garmin payload, the measurement is **not
persisted** as a historical point.  No synthetic date (`today`, epoch, etc.) is
ever invented.  The value may still be returned by `_fetch_and_persist_vo2max`
for use as a transient current value, but no document is written.

### No forward-fill

Dates with no Garmin measurement produce no document.  Calling `CURRENT` on
day D+1 when the last real measurement was on day D does **not** create a new
document for D+1.

### Empty payload never erases history

When `max-metrics` returns `[]` or a null value, `update_one` is **not**
called.  Existing history is untouched.

---

## Latest / Current Selection

All consumers read the most recent valid point with an explicit sort:

```python
await db.garmin_vo2max.find_one(
    {"user_id": user_id, "vo2max_running": {"$ne": None}},
    {"_id": 0, ...},
    sort=[("date", -1)],
)
```

This applies to:

- `_build_and_persist_capabilities()` — `has_vo2max` capability
- `compute_run_index()` in `insights.py` — run-index payload

`vo2max_running`, `vo2max_running_precise`, and `date` always come from the
**same document** — never mixed across documents.

---

## Invariants

| Invariant | Value |
|---|---|
| `FORWARD_FILL_USED` | NO |
| `EMPTY_PAYLOAD_WRITES_NULL` | NO |
| `EMPTY_PAYLOAD_ERASES_HISTORY` | NO |
| `DATE_FABRICATION` | NO |
| `GARMIN_VO2MAX_AFFECTS_TRAINING_PACES` | NO |
| `GARMIN_VO2MAX_AFFECTS_RACE_PREDICTIONS` | NO |
| `GARMIN_VO2MAX_AFFECTS_READINESS` | NO |
| `GARMIN_VO2MAX_AFFECTS_RUNINDEX_SCORE` | NO |

Training Paces remain VDOT-based and fully independent of Garmin VO₂max.

---

## Field Name Canonical Choice

The field `date` (matching `GarminVO2Max.date` and `calendarDate`) is the
single canonical date field in the `garmin_vo2max` collection.  The previously
used `vo2max_date` alias has been removed; all readers use `date`.

---

## Test Coverage

`backend/tests/test_garmin_vo2max_pr195.py` covers:

1. `GarminVO2Max.from_max_metrics` — payload extraction (flat, nested, sport priority)
2. `GarminVO2Max.from_max_metrics` — edge cases (None, [], bad types, zero/negative)
3. Precise value + `calendarDate` extraction
4. `GccliRunner.fetch_max_metrics` — subprocess routing + optional date parameter
5. `GccliProvider.get_max_metrics` — delegation to runner
6. `service._fetch_and_persist_vo2max` — persistence + no-overwrite guard
7. `service._build_and_persist_capabilities` — `has_vo2max` capability
8. `insights.compute_run_index` — vo2max fields in run-index payload
9. **Two-date persistence** — two measurements → two documents; latest = most recent date
10. **Reverse insertion order** — latest is by measurement date, not insert timestamp
11. **Empty payload after history** — history preserved, count unchanged
12. **No forward-fill** — only real measurement dates produce documents
13. **User isolation** — User A and User B data never mix

**Total: 62 tests, all passing.**
