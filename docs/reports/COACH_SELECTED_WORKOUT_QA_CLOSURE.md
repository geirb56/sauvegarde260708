# Coach selected-workout QA closure

## Revision

- Requested base: `copilot/dev`
- Base fetched and verified before editing: `d5f25ad51b9289df61a4471969bbad3bc64f6945`
- Starting HEAD: `d5f25ad51b9289df61a4471969bbad3bc64f6945` (matched the fetched base)
- Final implementation HEAD before this documentation-only commit: `78800f22cbe523b88f69d82253cc9c648c19160c`
- No Training V2 prescription engine or WorkoutDetail UI files were changed.

## Root causes and corrections

| QA gap | Root cause | Correction |
| --- | --- | --- |
| Selected workout context disappeared on follow-up | `Coach.handleSubmit()` omitted `workout_id` from its request and locally appended messages. | `activeWorkoutId` is set only by the explicit `?analyze=<id>` flow, carried in follow-up requests and local user/assistant messages, and cleared with Coach history. History messages do not auto-select an old workout. |
| Other workouts contaminated selected-workout conversation | `process_coach_message()` fetched the user's most recent messages without a workout scope. | The LLM receives only messages with the exact selected `workout_id`, or only unscoped messages for general requests. GET `/coach/history` remains user-wide and chronological. |
| Future activity could enter selected-workout history | `recent_workouts` used the current `reference_date` even when an old workout was selected. | Selected-workout history uses a separate 30-day window ending at that workout. Exact activity timestamps are filtered strictly before the selected start; date-only data excludes later dates. The selected workout is excluded from `recent_workouts` and remains in `workout_detail`. Coverage dates remain date-granular; the LLM projection carries the timestamp/date cutoff and its precision. |
| Decimal pace could be read as `6:81` | The canonical context exposed decimal minutes/km to the model as a value it could misinterpret. | A separate LLM projection turns paces and pace deltas into deterministic strings (including `6.81` → `6:49/km`, `+0.2` → `+0:12/km`) and removes the corresponding raw pace values. The prompt instructs the model to use display strings verbatim. |
| Unsupported physiological interpretations | Raw HR/pace and numeric comparisons were present without a structural permission boundary; prompt text alone was insufficient. | The LLM projection includes explicit intensity, raw-metric, comparison, progress/regression, efficiency, and causal permissions derived from Workout Analysis V2 availability. Current Training V2/readiness/load/performance context is explicitly marked current, not historical evidence about a selected workout. |
| Summary sounded mechanical without reliable intensity | `_build_summary()` led with a generic structural label before useful facts. | When intensity is unavailable, the text starts with localized distance/duration/pace/HR facts; no intensity calculation, classification, or authority changed. The existing summary code and technical details remain available. |

## QA outcomes supplied with the task

These are the reported real-QA outcomes before this patch; no external LLM runtime was called as part of this validation:

1. **28/09 comparison:** FAIL before patch (the 01/10 workout could be cited). The selected-workout history is now cutoff before 28/09's selected timestamp/date.
2. **01/10 comparison:** FAIL before patch (pace could be verbalized incorrectly and HR could be turned into an effort judgment). Pace display and interpretation permissions are now supplied structurally.
3. **Today/Week next-session answer:** PASS before patch. The no-`workout_id` path and canonical Training V2 context remain in place; regression tests cover today, current-week sessions, readiness, load, and prescription authority.

These changes do not claim new real-world QA results or guarantee untested behavior from an external LLM.

## Files changed

- `frontend/src/pages/Coach.jsx`
- `frontend/src/__tests__/coach-page.test.jsx`
- `backend/server.py`
- `backend/coach_context_v2.py`
- `backend/llm_coach.py`
- `backend/workout_analysis_v2.py`
- `backend/tests/test_coach_context_v2.py`
- `backend/tests/test_workout_analysis_v2.py`
- `docs/reports/COACH_SELECTED_WORKOUT_QA_CLOSURE.md`

## Validation performed

- Backend: from `backend/`, `python -m pytest tests/test_coach_context_v2.py tests/test_coach_contract_unified.py tests/test_workout_analysis_v2.py -q` — **173 passed, 12 warnings**.
- Frontend: from `frontend/`, `npx craco test --watchAll=false --forceExit src/__tests__/coach-page.test.jsx src/__tests__/workout-analysis-v2-pages.test.jsx src/__tests__/chat-coach-subscription-status.test.jsx` — **3 suites passed, 42 tests passed**.
- Frontend production build: from `frontend/`, `npm run build` — **compiled successfully**.
- `git diff --check` — **passed**.
- No complete backend or frontend suite was run. No external LLM call was made; grounding tests assert the projection and prompt only.

## Scope and remaining limits

Training V2 prescription logic, WorkoutGenerator, DailyAdaptation, WeeklyTarget, WeeklyReconciliation, StructuredWorkoutPrescriptionEngine, Garmin workers/scheduling/queue, readiness calculations, subscriptions, Performance Curve, VMA, RAG legacy, and WorkoutDetail presentation were not modified. Workout Analysis V2 calculations and classifications were not modified.

When only a date is available, the history cutoff is date-granular and later dates are excluded; exact same-day ordering cannot be established without timestamps. Current Training V2 data are retained as current context and are explicitly not evidence of historical readiness or training state. External LLM behavior remains outside these deterministic tests.
