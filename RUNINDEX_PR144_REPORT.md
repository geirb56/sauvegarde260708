# RUNINDEX_PR144_REPORT

## 1. HEAD copilot/dev de départ

Branch: `claude/bug-137-01-runtime-response-parsing-fix` (from `copilot/dev`)

## 2. Reproduction du bug

`_activity_date()` in `training_response.py` used explicit `strptime` formats that did **not** include `"YYYY-MM-DD HH:MM:SS"` (space-separated). Mongo/Garmin data arrives in this format → all activities returned `None` → `available_running=0`, `response_status="unavailable"`.

## 3. Cause racine

`_activity_date()` only accepted:
- `%Y-%m-%dT%H:%M:%S`
- `%Y-%m-%dT%H:%M:%SZ`
- `%Y-%m-%d`

Missing: `%Y-%m-%d %H:%M:%S` and variants with microseconds/timezone.

## 4. Fichiers modifiés

- `backend/training_v2/training_response.py` — fix `_activity_date()`
- `backend/tests/test_bug_137_01_date_parsing.py` — new test file

## 5. Correction exacte

Replaced the `strptime` loop with `datetime.fromisoformat()` (with Z-normalization) + fallback patterns, aligned with `training_history._parse_date()`.

## 6. Formats de dates désormais supportés

| Format | Example |
|--------|---------|
| Date only | `2026-08-18` |
| ISO-T | `2026-08-18T05:11:14` |
| ISO-Z | `2026-08-18T05:11:14Z` |
| ISO with ms | `2026-08-18T05:11:14.123` |
| ISO with tz | `2026-08-18T05:11:14+02:00` |
| Space-separated | `2026-08-18 05:11:14` |
| Space + ms | `2026-08-18 05:11:14.123` |
| `date` object | native |
| `datetime` object | native |

Invalid strings → `None`. No fallback to current date.

## 7. Tests ajoutés

- `TestActivityDateParsing`: 14 parametrized cases (all formats + invalids)
- `TestBuildResponseWithMongoDates`: 2 integration tests verifying `build_recent_training_response` sees activities
- `TestMongoBoundaryToResponse`: 1 end-to-end test (raw Mongo dict → `mongo_garmin_activities_to_domain()` → `build_recent_training_response()`)

## 8. Résultats

| Suite | Passed | Failed | Skipped |
|-------|--------|--------|---------|
| test_bug_137_01_date_parsing.py | 16 | 0 | 0 |
| test_training_response_pr132.py | 67 | 0 | 0 |
| mongo-related tests | 37 | 0 | 0 |
| daily_adaptation/training_today | 35 | 0 | 0 |

## 9. Invariants vérifiés

- `None != 0` : preserved
- Invalid date → `None` (not reference_date, not today, not epoch)
- No I/O, no Mongo, no Garmin imports in `training_response.py`
- Deterministic: same inputs → same output
- Provider-neutral

## 10. Diff scope

Only `_activity_date()` logic changed in `training_response.py`. No other function modified.

## 11. Risques

- **Minimal**: The fix uses `datetime.fromisoformat()` which is standard library and already used by `_parse_date()` in the same codebase.
- No business logic change. No new dependencies.

## 12. Validation runtime encore requise

Runtime validation: PENDING — à effectuer sur Emergent après merge dans copilot/dev.

Expected post-merge result:
- `available_running > 0`
- `observed_runs > 0`
- `response_status != "unavailable"`
- `hr_coverage_count > 0`
- `average_hr_recent != None`
