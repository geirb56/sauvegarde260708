# RUNINDEX_PR178_REPORT

## Metadata

```
BASE_BRANCH        = copilot/dev
HEAD_START         = 72d9bc4a4393159cb5a29b4223e9d70183f5fe8c  (post-merge #177)
HEAD_FINAL         = (see PR commit)
```

---

## Authority

```
READINESS_AUTHORITY              = /api/run-index
READINESS_FRONTEND_RECALCULATION = NO
```

---

## Invariants

```
NULL_READINESS_PRESERVED         = YES
  run_readiness == null → unavailable label displayed, not 0, not 100

ZERO_READINESS_PRESERVED         = YES
  run_readiness == 0 → score 0/100 displayed as real score

UNKNOWN_STATUS_DEFAULT           = gray
  hrv_status absent/unknown      → gray tile (was: || "green" → FIXED)
  rhr_status absent/unknown      → gray tile (already correct)
  sleep_status absent/unknown    → gray tile (was: || "green" → FIXED)
  training_load_status absent    → gray tile (was: || "green" → FIXED)

UNKNOWN_RECOMMENDATION_COLOR_DEFAULT = gray
  absent/unknown recommendation_color → REC_STYLES.gray
  (was: || REC_STYLES.green → FIXED)

UNKNOWN_NONEMPTY_STATUS_DEFAULT  = gray
  ReadinessTile: any status not in {green,yellow,red} → gray
  (was: implicit green fallback for unknown non-empty values → FIXED)

GRAY_STATUS_RED_ICON             = NO
  StatusIcon: status="gray" → null (no icon)
  (was: XCircle red icon → FIXED)
```

---

## History

```
READINESS_HISTORY_AUTHORITY = history[].run_readiness

Filtering:
  null/undefined entries filtered (not rendered in chart)
  score=0 entries KEPT — not filtered

No frontend recalculation of history values.
```

---

## Confidence / Sufficiency / Reasons

```
CONFIDENCE        = AVAILABLE_NOT_DISPLAYED
  Field returned by /run-index as metrics.confidence
  Not currently surfaced in Dashboard UI
  No UX redesign required to add it — deferred to #179

SUFFICIENCY_LEVEL = AVAILABLE_NOT_DISPLAYED
  Field returned by /run-index as metrics.sufficiency_level
  Not currently surfaced in Dashboard UI
  Deferred to #179

READINESS_REASONS = AVAILABLE_NOT_DISPLAYED
  Field returned by /run-index as metrics.readiness_reasons (array)
  Not currently surfaced in Dashboard UI
  Deferred to #179
```

---

## Legacy Constants Removed

```
LEGACY_CONSTANTS_REMOVED = YES

Removed from Dashboard.jsx (zero callers confirmed):
  - FATIGUE_REST_THRESHOLD  (1.5)
  - FATIGUE_EASY_THRESHOLD  (1.2)
  - LOAD_OPTIMAL_MIN        (0.8)
  - LOAD_OPTIMAL_MAX        (1.3)

These constants were defined at module-level but never referenced
in any expression, condition, or JSX in Dashboard.jsx.
Static scan: 4 occurrences = 4 definitions, 0 callers.
```

---

## Legacy Color Helpers Removed

```
LEGACY_COLOR_HELPERS_REMOVED = YES (from Dashboard.jsx only)

Removed from Dashboard.jsx component body (zero callers in Dashboard.jsx):
  - getAcwrColor(status)  — defined but never called in Dashboard.jsx
  - getTsbColor(status)   — defined but never called in Dashboard.jsx

NOTE: getAcwrColor and getTsbColor still exist in TrainingPlan.jsx
(legacy page, out of scope for #178) with active callers:
  - TrainingPlan.jsx:538  getAcwrColor(trainingMetrics?.acwr_status)
  - TrainingPlan.jsx:544  getAcwrColor(trainingMetrics?.acwr_status)
  - TrainingPlan.jsx:551  getAcwrColor(trainingMetrics?.acwr_status)
  - TrainingPlan.jsx:568  getTsbColor(trainingMetrics?.tsb_status)
  - TrainingPlan.jsx:574  getTsbColor(trainingMetrics?.tsb_status)
  - TrainingPlan.jsx:578  getTsbColor(trainingMetrics?.tsb_status)

These are NOT removed — they have active callers in TrainingPlan.jsx.
```

---

## Static Scan Results (post-fix, Dashboard.jsx only)

```
hrv_status || "green"            → 0 occurrences  ✓
sleep_status || "green"          → 0 occurrences  ✓
training_load_status || "green"  → 0 occurrences  ✓
REC_STYLES[...] || REC_STYLES.green → 0 occurrences  ✓
FATIGUE_REST_THRESHOLD           → 0 occurrences  ✓
FATIGUE_EASY_THRESHOLD           → 0 occurrences  ✓
LOAD_OPTIMAL_MIN                 → 0 occurrences  ✓
LOAD_OPTIMAL_MAX                 → 0 occurrences  ✓
getAcwrColor (Dashboard.jsx)     → 0 occurrences  ✓
getTsbColor  (Dashboard.jsx)     → 0 occurrences  ✓
ReadinessTile implicit green fallback → 0 occurrences  ✓
StatusIcon implicit red fallback → 0 occurrences  ✓
```

---

## Scope Compliance

```
RUNINDEX_SCORE_MODIFIED = NO
  insight.run_index block unchanged
  RunIndex Score 0-1000 / Speed / Endurance / Consistency / Efficiency untouched

TRAINING_V2_MODIFIED    = NO
  TrainingPlanV2.jsx not modified
  Coach.jsx not modified

BACKEND_MODIFIED        = NO

LOCKFILES_MODIFIED      = NO
  package.json not modified
  package-lock.json restored from origin/copilot/dev (zero diff)
  yarn.lock restored from origin/copilot/dev (zero diff)

UNKNOWN_NONEMPTY_STATUS_DEFAULT = gray
GRAY_STATUS_RED_ICON            = NO
```

---

## Refresh Button

```
REFRESH_ENDPOINT = GET /api/run-index only
  fetchCardioData() calls axios.get(`${API}/run-index?language=${lang}`)
  No Garmin sync triggered
  No plan recalculation triggered
  No write operations
```

---

## Tests

```
Test file: src/__tests__/dashboard-run-readiness-v2.test.jsx

Scenarios:
  1.  run_readiness=null → unavailable label, not 0              PASSED
  2.  run_readiness=0    → 0/100 displayed                       PASSED
  3.  hrv_status absent  → gray tile                             PASSED
  4.  rhr_status absent  → gray tile                             PASSED
  5.  sleep_status absent → gray tile                            PASSED
  6.  training_load_status absent → gray tile                    PASSED
  7.  recommendation_color absent → gray style                   PASSED
  8.  recommendation_color unknown → gray style                  PASSED
  9.  recommendation_color green/yellow/red → correct styles     PASSED
 10.  history: null entry filtered out                           PASSED
 11.  history: 0 entry kept                                      PASSED
 12.  Refresh → GET /run-index only                              PASSED
 13.  No Readiness formula in React (static scan)                PASSED
 14.  RunIndex Score block untouched                             PASSED
 15.  Training V2 components untouched                           PASSED
 16.  hrv_status="purple" → gray, never green                    PASSED
 17.  sleep_status="unknown" → gray tile                         PASSED
 18.  training_load_status="unexpected" → gray tile              PASSED
 19.  rhr_status unknown value → gray tile                       PASSED
 20.  status="gray" → no red icon in tile                        PASSED
 21.  status="red" → red color preserved                         PASSED
 22.  green/yellow/red → correct tile colors preserved           PASSED

UNKNOWN_STATUS_TESTS = PASS
GRAY_ICON_TEST       = PASS

Total: 122 tests across all suites
Result: passed=122  failed=0  skipped=0  errors=0
```

---

## Files Modified

```
frontend/src/pages/Dashboard.jsx
  - Removed: FATIGUE_REST_THRESHOLD, FATIGUE_EASY_THRESHOLD, LOAD_OPTIMAL_MIN, LOAD_OPTIMAL_MAX
  - Removed: getAcwrColor(), getTsbColor() (dead in Dashboard, have callers in TrainingPlan.jsx)
  - Fixed:   hrv_status || "green"              → || "gray"
  - Fixed:   sleep_status || "green"            → || "gray"
  - Fixed:   training_load_status || "green"    → || "gray"
  - Fixed:   REC_STYLES[...] || REC_STYLES.green → || REC_STYLES.gray
  - Fixed:   ReadinessTile: unknown status → gray (explicit normalization, no green fallback)
  - Fixed:   StatusIcon: gray/unknown → null (no red XCircle fallback)

frontend/src/__tests__/dashboard-run-readiness-v2.test.jsx
  - New: 15-scenario test suite for Run Readiness V2 frontend consumer (original)
  - Added: 7 additional scenarios (tests 16–22) for unknown/nonempty status and gray icon

RUNINDEX_PR178_REPORT.md
  - This file
```

---

## Verdict

```
READY FOR MERGE INTO copilot/dev

Conditions met:
  ✓ base copilot/dev post-#177
  ✓ UNKNOWN never becomes GREEN (absent or non-empty unknown value)
  ✓ GRAY never displays red icon
  ✓ NULL never becomes 0
  ✓ true score 0 preserved
  ✓ history 0 preserved
  ✓ refresh = simple GET /run-index
  ✓ dead legacy constants removed (zero callers confirmed)
  ✓ dead legacy helpers removed from Dashboard.jsx (TrainingPlan.jsx callers documented)
  ✓ no backend formula modified
  ✓ RunIndex Score untouched
  ✓ Training V2 untouched
  ✓ no lockfile modified
  ✓ tests: 122 passed, 0 failed
```


## Metadata

```
BASE_BRANCH        = copilot/dev
HEAD_START         = 72d9bc4a4393159cb5a29b4223e9d70183f5fe8c  (post-merge #177)
HEAD_FINAL         = (see PR commit)
```

---

## Authority

```
READINESS_AUTHORITY              = /api/run-index
READINESS_FRONTEND_RECALCULATION = NO
```

---

## Invariants

```
NULL_READINESS_PRESERVED         = YES
  run_readiness == null → unavailable label displayed, not 0, not 100

ZERO_READINESS_PRESERVED         = YES
  run_readiness == 0 → score 0/100 displayed as real score

UNKNOWN_STATUS_DEFAULT           = gray
  hrv_status absent/unknown      → gray tile (was: || "green" → FIXED)
  rhr_status absent/unknown      → gray tile (already correct)
  sleep_status absent/unknown    → gray tile (was: || "green" → FIXED)
  training_load_status absent    → gray tile (was: || "green" → FIXED)

UNKNOWN_RECOMMENDATION_COLOR_DEFAULT = gray
  absent/unknown recommendation_color → REC_STYLES.gray
  (was: || REC_STYLES.green → FIXED)
```

---

## History

```
READINESS_HISTORY_AUTHORITY = history[].run_readiness

Filtering:
  null/undefined entries filtered (not rendered in chart)
  score=0 entries KEPT — not filtered

No frontend recalculation of history values.
```

---

## Confidence / Sufficiency / Reasons

```
CONFIDENCE        = AVAILABLE_NOT_DISPLAYED
  Field returned by /run-index as metrics.confidence
  Not currently surfaced in Dashboard UI
  No UX redesign required to add it — deferred to #179

SUFFICIENCY_LEVEL = AVAILABLE_NOT_DISPLAYED
  Field returned by /run-index as metrics.sufficiency_level
  Not currently surfaced in Dashboard UI
  Deferred to #179

READINESS_REASONS = AVAILABLE_NOT_DISPLAYED
  Field returned by /run-index as metrics.readiness_reasons (array)
  Not currently surfaced in Dashboard UI
  Deferred to #179
```

---

## Legacy Constants Removed

```
LEGACY_CONSTANTS_REMOVED = YES

Removed from Dashboard.jsx (zero callers confirmed):
  - FATIGUE_REST_THRESHOLD  (1.5)
  - FATIGUE_EASY_THRESHOLD  (1.2)
  - LOAD_OPTIMAL_MIN        (0.8)
  - LOAD_OPTIMAL_MAX        (1.3)

These constants were defined at module-level but never referenced
in any expression, condition, or JSX in Dashboard.jsx.
Static scan: 4 occurrences = 4 definitions, 0 callers.
```

---

## Legacy Color Helpers Removed

```
LEGACY_COLOR_HELPERS_REMOVED = YES (from Dashboard.jsx only)

Removed from Dashboard.jsx component body (zero callers in Dashboard.jsx):
  - getAcwrColor(status)  — defined but never called in Dashboard.jsx
  - getTsbColor(status)   — defined but never called in Dashboard.jsx

NOTE: getAcwrColor and getTsbColor still exist in TrainingPlan.jsx
(legacy page, out of scope for #178) with active callers:
  - TrainingPlan.jsx:538  getAcwrColor(trainingMetrics?.acwr_status)
  - TrainingPlan.jsx:544  getAcwrColor(trainingMetrics?.acwr_status)
  - TrainingPlan.jsx:551  getAcwrColor(trainingMetrics?.acwr_status)
  - TrainingPlan.jsx:568  getTsbColor(trainingMetrics?.tsb_status)
  - TrainingPlan.jsx:574  getTsbColor(trainingMetrics?.tsb_status)
  - TrainingPlan.jsx:578  getTsbColor(trainingMetrics?.tsb_status)

These are NOT removed — they have active callers in TrainingPlan.jsx.
```

---

## Static Scan Results (post-fix, Dashboard.jsx only)

```
hrv_status || "green"            → 0 occurrences  ✓
sleep_status || "green"          → 0 occurrences  ✓
training_load_status || "green"  → 0 occurrences  ✓
REC_STYLES[...] || REC_STYLES.green → 0 occurrences  ✓
FATIGUE_REST_THRESHOLD           → 0 occurrences  ✓
FATIGUE_EASY_THRESHOLD           → 0 occurrences  ✓
LOAD_OPTIMAL_MIN                 → 0 occurrences  ✓
LOAD_OPTIMAL_MAX                 → 0 occurrences  ✓
getAcwrColor (Dashboard.jsx)     → 0 occurrences  ✓
getTsbColor  (Dashboard.jsx)     → 0 occurrences  ✓
```

---

## Scope Compliance

```
RUNINDEX_SCORE_MODIFIED = NO
  insight.run_index block unchanged
  RunIndex Score 0-1000 / Speed / Endurance / Consistency / Efficiency untouched

TRAINING_V2_MODIFIED    = NO
  TrainingPlanV2.jsx not modified
  Coach.jsx not modified

BACKEND_MODIFIED        = NO

LOCKFILES_MODIFIED      = NO
  package.json not modified
  package-lock.json not modified
  yarn.lock not modified
```

---

## Refresh Button

```
REFRESH_ENDPOINT = GET /api/run-index only
  fetchCardioData() calls axios.get(`${API}/run-index?language=${lang}`)
  No Garmin sync triggered
  No plan recalculation triggered
  No write operations
```

---

## Tests

```
Test file: src/__tests__/dashboard-run-readiness-v2.test.jsx

Scenarios:
  1.  run_readiness=null → unavailable label, not 0              PASSED
  2.  run_readiness=0    → 0/100 displayed                       PASSED
  3.  hrv_status absent  → gray tile                             PASSED
  4.  rhr_status absent  → gray tile                             PASSED
  5.  sleep_status absent → gray tile                            PASSED
  6.  training_load_status absent → gray tile                    PASSED
  7.  recommendation_color absent → gray style                   PASSED
  8.  recommendation_color unknown → gray style                  PASSED
  9.  recommendation_color green/yellow/red → correct styles     PASSED
 10.  history: null entry filtered out                           PASSED
 11.  history: 0 entry kept                                      PASSED
 12.  Refresh → GET /run-index only                              PASSED
 13.  No Readiness formula in React (static scan)                PASSED
 14.  RunIndex Score block untouched                             PASSED
 15.  Training V2 components untouched                           PASSED

Total: 113 tests across all suites
Result: passed=113  failed=0  skipped=0  errors=0
```

---

## Files Modified

```
frontend/src/pages/Dashboard.jsx
  - Removed: FATIGUE_REST_THRESHOLD, FATIGUE_EASY_THRESHOLD, LOAD_OPTIMAL_MIN, LOAD_OPTIMAL_MAX
  - Removed: getAcwrColor(), getTsbColor() (dead in Dashboard, have callers in TrainingPlan.jsx)
  - Fixed:   hrv_status || "green"              → || "gray"
  - Fixed:   sleep_status || "green"            → || "gray"
  - Fixed:   training_load_status || "green"    → || "gray"
  - Fixed:   REC_STYLES[...] || REC_STYLES.green → || REC_STYLES.gray

frontend/src/__tests__/dashboard-run-readiness-v2.test.jsx
  - New: 15-scenario test suite for Run Readiness V2 frontend consumer

RUNINDEX_PR178_REPORT.md
  - This file
```

---

## Verdict

```
READY FOR MERGE INTO copilot/dev

Conditions met:
  ✓ base copilot/dev post-#177
  ✓ UNKNOWN never becomes GREEN
  ✓ NULL never becomes 0
  ✓ true score 0 preserved
  ✓ history 0 preserved
  ✓ refresh = simple GET /run-index
  ✓ dead legacy constants removed (zero callers confirmed)
  ✓ dead legacy helpers removed from Dashboard.jsx (TrainingPlan.jsx callers documented)
  ✓ no backend formula modified
  ✓ RunIndex Score untouched
  ✓ Training V2 untouched
  ✓ no lockfile modified
  ✓ tests: 113 passed, 0 failed
```
