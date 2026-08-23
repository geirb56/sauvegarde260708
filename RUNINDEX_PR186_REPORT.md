# RUNINDEX PR #186 — Performance Model V2 Data Quality Report

## Summary

PR #186 fiabilise VMA V2 et Race Predictions V2 sur 5 objectifs de qualité des données.

---

## Data Layer Audit

```
MOVING_DURATION_RAW_SOURCE =
summaryDTO.movingDuration

MOVING_DURATION_DATA_LAYER =
GarminActivity.moving_duration_s

MOVING_DURATION_MONGO_FIELD =
garmin_activity.moving_duration_s
(persisted via GarminActivity.model_dump() in gccli_provider.py line 238)

MOVING_DURATION_PERSISTED =
YES
```

---

## Performance Model V2 Configuration

```
DOMAIN_MOVING_DURATION =
YES
(DomainActivity.moving_duration_s field added; propagated in:
  - garmin/domain_adapter.py → to_domain_activity()
  - garmin/domain_adapter.py → mongo_garmin_to_domain()
  - training_v2/domain_activity.py → to_domain_activity())

PERFORMANCE_DURATION_PRIORITY =
moving_duration_s > duration_s fallback
(implemented in training_v2/performance_model._performance_duration_s())

VMA_WINDOW_DAYS =
42

CURRENT_HISTORY_SAME_WINDOW =
YES
(estimate_vma() and get_vma_history_snapshots() both use _activities_in_vma_window
 with window_days=VMA_WINDOW_DAYS=42)

VMA_TRAIL_ALLOWED =
NO
(trail_running excluded from _VMA_ROAD_TYPES)

VMA_MAX_ELEVATION_GAIN_PER_KM =
30

MIN_RIEGEL_RELATIVE_HR =
0.80

RIEGEL_WITHOUT_AVG_HR_ALLOWED =
NO

RIEGEL_WITHOUT_FCMAX_ALLOWED =
NO

SYNTHETIC_PREDICTIONS =
NO
(no SOURCE A, no VMA-to-Riegel synthesis, no fabricated effort)

RIEGEL_VMA_CONFIDENCE_DEPENDENCY =
NO
(get_race_predictions() is fully independent of estimate_vma())

TOTAL_SESSIONS_6W_WINDOW_DAYS =
42
(compute_athlete_profile() counts running activities in 42-day window only;
 server.py /training/race-predictions total_sessions_6w fixed to count
 only running activity types)

FRONTEND_MODIFIED =
NO
```

---

## Changed Files

| File | Change |
|------|--------|
| `backend/training_v2/domain_activity.py` | Added `moving_duration_s: Optional[float] = None` field; propagated in `to_domain_activity()` |
| `backend/garmin/domain_adapter.py` | Propagated `moving_duration_s` in `to_domain_activity()` and `mongo_garmin_to_domain()` with guard (moving <= duration) |
| `backend/training_v2/performance_model.py` | **NEW** — Full Performance Model V2 module |
| `backend/tests/test_performance_model_pr185.py` | **NEW** — Base model tests |
| `backend/tests/test_performance_model_pr186.py` | **NEW** — PR186 data quality tests (29 test cases) |
| `backend/server.py` | Fixed `total_sessions_6w` to count only running activity types |
| `RUNINDEX_PR186_REPORT.md` | This file |

---

## performance_model.py Constants

| Constant | Value |
|----------|-------|
| `VMA_WINDOW_DAYS` | 42 |
| `MAX_ROAD_ELEVATION_GAIN_PER_KM` | 30.0 |
| `MIN_RIEGEL_RELATIVE_HR` | 0.80 |
| `RIEGEL_K` | 1.06 (unchanged) |
| `MIN_ACTIVITIES_HR_MODEL` | 3 (unchanged) |
| `MIN_HR_RANGE_BPM` | 20.0 (unchanged) |
| `MIN_DISTINCT_HR_LEVELS` | 3 (unchanged) |
| `MIN_R2` | 0.50 (unchanged) |

---

## Test Results

```
tests =
63 passed / 0 skipped / 0 failed / 0 errors
(test_performance_model_pr185.py + test_performance_model_pr186.py)

regression =
170 passed / 0 failed
(domain_activity, mongo_boundary_pr137, garmin_data_layer, runner_profile_pr07,
 performance_model_pr185, performance_model_pr186)
```

---

## Test Coverage (PR #186 numbered tests)

| # | Test | Status |
|---|------|--------|
| 1 | duration=3600, moving=3000, 10km → speed 12km/h | ✅ |
| 2 | moving absent → fallback duration_s | ✅ |
| 3 | moving=0 → fallback | ✅ |
| 4 | moving > duration → fallback | ✅ |
| 5 | Riegel T1 uses moving_duration_s | ✅ |
| 6 | VMA HR-speed uses same duration as Riegel | ✅ |
| 7 | activity J-41 → included | ✅ |
| 8 | activity J-42 → excluded | ✅ |
| 9 | activity J+1 → excluded | ✅ |
| 10 | old excellent performance hors fenêtre → aucun effet CURRENT | ✅ |
| 11 | CURRENT == snapshot today même données | ✅ |
| 12 | history.sessions = activités dans fenêtre uniquement | ✅ |
| 13 | trail_running plat → exclu VMA | ✅ |
| 14 | 10km +350m (35 D+/km) → exclu VMA | ✅ |
| 15 | 30km +350m (11.7 D+/km) → accepté | ✅ |
| 16 | D+ absent → pas de rejet | ✅ |
| 17 | relative_hr = 0.79 → rejet Riegel | ✅ |
| 18 | relative_hr = 0.80 → éligible | ✅ |
| 19 | relative_hr = 0.90 → éligible | ✅ |
| 20 | average_hr absente → rejet | ✅ |
| 21 | FCmax absente → rejet | ✅ |
| 22 | trail_running → rejet Riegel | ✅ |
| 23 | D+/km > 30 → rejet Riegel | ✅ |
| 24 | aucune source qualifiée → predictions vides | ✅ |
| 25 | aucune valeur synthétique | ✅ |
| 26 | activité J-41 → comptée total_sessions_6w | ✅ |
| 27 | activité J-42 → non comptée | ✅ |
| 28 | activité future → non comptée | ✅ |
| 29 | non-running → non comptée | ✅ |

---

## Ready Checklist

- [x] movingDuration Garmin arrive réellement dans DomainActivity
- [x] moving_duration utilisée pour vitesse + VMA + Riegel
- [x] fallback duration_s fonctionne
- [x] VMA CURRENT = fenêtre 42 jours
- [x] historique = même fenêtre
- [x] trail exclu VMA
- [x] D+/km appliqué VMA
- [x] Riegel exige relative_hr >= 0.80
- [x] Riegel sans HR ou FCmax = aucune source
- [x] VMA / Predictions indépendantes
- [x] total_sessions_6w = 42 jours réels, running only
- [x] aucun synthétique
- [x] frontend inchangé
- [x] tests 0 failed
- [x] aucun lockfile modifié
- [x] PR mergeable

---

```
MOVING_DURATION_PROPAGATED = YES
VMA_WINDOW_DAYS = 42
RIEGEL_MIN_RELATIVE_HR = 0.80
RIEGEL_WITHOUT_HR_ALLOWED = NO
TOTAL_SESSIONS_6W_FIXED = YES
TESTS = 63 passed / 0 failed / 0 errors
MERGEABLE = YES
READY = YES
```
