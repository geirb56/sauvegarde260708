BASE_SHA = f03babc69233b64536824d7e8d87d2a65d31728b
HEAD_SHA = fac949173c8347d897af9c15e7ae2aab8864760d

--------------------------------------------------
RUNINDEX
--------------------------------------------------

RUNINDEX_CURRENT_CANONICAL_SOURCE = garmin_activities → DomainActivity → calculate_run_index_from_domain()
RUNINDEX_CURRENT_SINGLE_SOURCE = YES
DASHBOARD_CURRENT_SOURCE = /api/dashboard/insight → load_garmin_domain_activities() → calculate_run_index_from_domain()
PROGRESS_CURRENT_SOURCE_BEFORE = /api/run-index/history → run_index_scores latest snapshot → current_run_index
PROGRESS_CURRENT_SOURCE_AFTER = /api/run-index/history → refresh today's snapshot from garmin_activities → DomainActivity → calculate_run_index_from_domain() before responding; current_run_index now comes from the freshly computed canonical snapshot for the request
DASHBOARD_PROGRESS_EQUAL = YES
TODAY_SNAPSHOT_EQUAL_CURRENT = YES
PAGE_LOAD_ORDER_INDEPENDENT = YES
HISTORICAL_RUNINDEX_DATA_DELETED = NO
GLOBAL_MONGO_MIGRATION = NO

Diagnostic before/after:
- Before: Dashboard computed current RunIndex directly from garmin_activities, while Progress displayed current_run_index from /api/run-index/history backed by persisted run_index_scores. A stale latest snapshot could therefore diverge from Dashboard.
- After: /api/run-index/history always refreshes today's snapshot from the canonical Garmin DomainActivity engine before returning history, and exposes current_run_index from that freshly computed snapshot. Historical points remain sourced from run_index_scores only.
- Integration proof added: backend/tests/test_run_index_current_single_source_pr216.py and backend/tests/test_run_index_history_service.py cover Dashboard→Progress, Progress→Dashboard, stale historical Y != current X, and today snapshot == current X.

--------------------------------------------------
LEGACY
--------------------------------------------------

TERRA_RUNTIME_CONSUMERS = 0
TRAINING_ENGINE_RUNTIME_CONSUMERS = 0 runtime imports/consumers confirmed; remaining string mentions are comments/docstrings/tests only
FULL_CYCLE_RUNTIME_CONSUMERS = 0
HR_SPEED_VMA_RUNTIME_CONSUMERS = 0
VMA_HISTORY_RUNTIME_CONSUMERS = 0
USER_VMA_ESTIMATE_RUNTIME_CONSUMERS = 0
SYNTHETIC_VMA_PROXY_RUNTIME_CONSUMERS = 0
SYNTHETIC_VO2_RUNTIME_CONSUMERS = 0 confirmed in current RunIndex / Race Predictions / Garmin VO2max runtime; compatibility fields remain in race-predictions payload but Performance V2 returns null for estimated_vma / estimated_vo2max
OLD_TRAINING_PLAN_RUNTIME_CONSUMERS = 0 legacy TrainingPlan frontend route/file; TrainingPlanV2 remains active
DB_WORKOUTS_OCCURRENCES = runtime-active in server.py, coach_service.py, services/dashboard_service.py, garmin/service.py, garmin/backfill.py, workers/event_worker.py, training_v2/week_plan_bridge.py
DB_WORKOUTS_RUNTIME_CONSUMERS = YES
DEAD_LEGACY_CODE_REMOVED = Apple auth frontend exposure; stale RunIndex current/history divergence
NECESSARY_COMPATIBILITY_REMAINING = run_index_scores historical snapshots; race-predictions athlete_profile compatibility keys returning null; backend Apple auth endpoints left in place because frontend exposure was the scoped product requirement
ACTIVE_LEGACY_REMAINING = No confirmed Terra/training_engine/full-cycle/VMA legacy engine consumer; db.workouts remains a runtime compatibility surface and source-of-truth audit item in Training/Coach domains

DB.WORKOUTS INVENTORY
- FILE = backend/services/run_index_history.py
  FUNCTION = load_user_workouts
  RUNTIME_CALLER = none found for RunIndex runtime
  ENDPOINT_OR_WORKER = none
  PURPOSE = legacy helper only
  CANONICAL_SOURCE = garmin_activities for RunIndex
  STATUS = DEAD_LEGACY (kept but unused by current RunIndex runtime)
- FILE = backend/server.py
  FUNCTION = get_workouts / get_workout / create_workout
  RUNTIME_CALLER = REST API
  ENDPOINT_OR_WORKER = /api/workouts, /api/workouts/{id}
  PURPOSE = user workout CRUD
  CANONICAL_SOURCE = db.workouts
  STATUS = NECESSARY_COMPATIBILITY
- FILE = backend/server.py
  FUNCTION = chat_with_coach / get_adaptive_guidance / get_weekly_review / get_mobile_workout_analysis / get_detailed_analysis / rag dashboard/review/workout endpoints
  RUNTIME_CALLER = coach and RAG routes
  ENDPOINT_OR_WORKER = /api/coach/*, /api/rag/*
  PURPOSE = coaching context and workout analysis
  CANONICAL_SOURCE = db.workouts
  STATUS = NECESSARY_COMPATIBILITY
- FILE = backend/server.py
  FUNCTION = get_training_metrics / get_week_plan
  RUNTIME_CALLER = training routes
  ENDPOINT_OR_WORKER = /api/training/metrics, /api/training/week-plan
  PURPOSE = display metrics windows and feed week-plan bridge
  CANONICAL_SOURCE = mixed: db.workouts for windows/context, garmin_activities for V2 load snapshot in /training/metrics
  STATUS = SOURCE_OF_TRUTH_RISK
- FILE = backend/coach_service.py
  FUNCTION = build_plan_v2
  RUNTIME_CALLER = training planning flow
  ENDPOINT_OR_WORKER = Training plan generation path
  PURPOSE = convert db.workouts into DomainActivity for Training V2 planning context
  CANONICAL_SOURCE = db.workouts via week-plan bridge
  STATUS = NECESSARY_COMPATIBILITY / SOURCE_OF_TRUTH_RISK
- FILE = backend/services/dashboard_service.py
  FUNCTION = get_dashboard
  RUNTIME_CALLER = dashboard orchestration
  ENDPOINT_OR_WORKER = dashboard service layer
  PURPOSE = last_runs list
  CANONICAL_SOURCE = db.workouts for last_runs, /run-index for readiness/acwr
  STATUS = NECESSARY_COMPATIBILITY
- FILE = backend/garmin/service.py, backend/garmin/backfill.py, backend/workers/event_worker.py
  FUNCTION = Garmin sync/backfill fan-out
  RUNTIME_CALLER = sync/background workers
  ENDPOINT_OR_WORKER = Garmin ingestion workers
  PURPOSE = self-heal / maintain db.workouts for legacy-compatible consumers
  CANONICAL_SOURCE = garmin_activities upstream
  STATUS = NECESSARY_COMPATIBILITY

--------------------------------------------------
PERFORMANCE
--------------------------------------------------

RACE_PREDICTION_FORMULA_CHANGED = NO
RACE_PREDICTION_TIMES_CHANGED = NO
CONFIDENCE_V2_FINALIZED = YES

Notes:
- Formula remains qualified observed performances → T(D)=A×D^k.
- Change applied only to confidence semantics in backend/training_v2/performance_model.py: a defendable numeric prediction now floors at LOW instead of degrading to INSUFFICIENT purely through cumulative penalties.
- True INSUFFICIENT is preserved for no defendable curve / no anchor / beyond hard extrapolation guardrail.

--------------------------------------------------
AUTH
--------------------------------------------------

APPLE_AUTH_FRONTEND_EXPOSURE = 0
GOOGLE_AUTH_PRESERVED = YES
EMAIL_PASSWORD_AUTH_PRESERVED = YES

Notes:
- Removed Apple button, Apple frontend auth copy, and Apple-specific frontend error mapping.
- Backend Apple endpoints remain present and were not removed in this PR because the product requirement was frontend exposure only and the backend removal safety scope was not established here.

--------------------------------------------------
SETTINGS
--------------------------------------------------

PLAN_START_DATE_WRITABLE = YES
PLAN_START_DATE_BACKEND_CANONICAL = YES

Canonical contract added:
- POST /api/training/v2/cycle/start-date
- user isolation enforced by authenticated user_id filter on training_cycles
- explicit 400 when no user cycle exists
- validates YYYY-MM-DD
- rejects future plan_start_date
- rejects plan_start_date > race_date when a race date exists
- Settings now persists through this backend contract; no frontend-only simulation remains

--------------------------------------------------
SOURCES OF TRUTH
--------------------------------------------------

DOMAIN = RunIndex
CANONICAL_SOURCE = garmin_activities → DomainActivity → calculate_run_index_from_domain()
ALTERNATIVE_SOURCES = run_index_scores historical snapshots
RUNTIME_CONSUMERS = /api/dashboard/insight, /api/run-index/history refresh path, Progress, Dashboard
PERSISTED_CACHE_OR_HISTORY = run_index_scores, dashboard_insight_cache
DOUBLE_SOURCE_RISK = NO after PR216 refresh/current override

DOMAIN = Readiness
CANONICAL_SOURCE = garmin daily metrics + garmin_activities → build_readiness_v2_from_garmin_data() via backend/garmin/insights.py
ALTERNATIVE_SOURCES = none confirmed in V2 runtime
RUNTIME_CONSUMERS = /api/run-index, dashboard service mirrors /run-index metrics
PERSISTED_CACHE_OR_HISTORY = run_readiness_scores historical collection may exist, but /api/run-index computes V2 directly per request
DOUBLE_SOURCE_RISK = NO

DOMAIN = Race Predictions
CANONICAL_SOURCE = garmin_activities → DomainActivity → training_v2.performance_model.predict_races()
ALTERNATIVE_SOURCES = compatibility athlete_profile fields only; not used to compute times
RUNTIME_CONSUMERS = /api/training/race-predictions, Progress
PERSISTED_CACHE_OR_HISTORY = none
DOUBLE_SOURCE_RISK = NO

DOMAIN = Training Paces
CANONICAL_SOURCE = garmin_activities → DomainActivity → compute_training_paces()
ALTERNATIVE_SOURCES = none confirmed for V2 paces generation
RUNTIME_CONSUMERS = coach_service / plan runtime consumers
PERSISTED_CACHE_OR_HISTORY = none
DOUBLE_SOURCE_RISK = NO

DOMAIN = Training Load
CANONICAL_SOURCE = /api/run-index uses garmin_activities → DomainActivity → build_training_load()
ALTERNATIVE_SOURCES = /api/training/metrics display windows and training/week-plan context still read db.workouts
RUNTIME_CONSUMERS = /api/run-index, /api/training/metrics, training planning/coaching surfaces
PERSISTED_CACHE_OR_HISTORY = training_load collection exists for history/compatibility
DOUBLE_SOURCE_RISK = YES

DOMAIN = Weekly Target
CANONICAL_SOURCE = training_v2.weekly_target + weekly reconciliation/generator chain
ALTERNATIVE_SOURCES = none confirmed as a second active engine
RUNTIME_CONSUMERS = Training V2 generation path
PERSISTED_CACHE_OR_HISTORY = none identified beyond derived plan responses
DOUBLE_SOURCE_RISK = NO

DOMAIN = Training Plan
CANONICAL_SOURCE = Training V2 chain (TrainingHistory V2 → TrainingLoad V2 → RunnerProfile → TrainingState → PlanGoal → Periodization → WeeklyTarget / generator)
ALTERNATIVE_SOURCES = training/week-plan and coach_service still source workout windows from db.workouts before V2 conversion
RUNTIME_CONSUMERS = /api/training/week-plan, TrainingPlanV2/coaching consumers
PERSISTED_CACHE_OR_HISTORY = training_cycles, user_goals, plan caches
DOUBLE_SOURCE_RISK = YES

DOMAIN = Garmin VO2max
CANONICAL_SOURCE = db.garmin_vo2max observed Garmin signal
ALTERNATIVE_SOURCES = none used to synthesize Garmin VO2max in current V2 runtime
RUNTIME_CONSUMERS = /api/run-index, coach_service, some training/analysis payloads
PERSISTED_CACHE_OR_HISTORY = garmin_vo2max collection
DOUBLE_SOURCE_RISK = NO

DOMAIN = Subscription/access
CANONICAL_SOURCE = backend/access_control.py + subscriptions collection / subscription_manager
ALTERNATIVE_SOURCES = none allowed at route level
RUNTIME_CONSUMERS = premium route middleware and gated endpoints
PERSISTED_CACHE_OR_HISTORY = subscriptions collection
DOUBLE_SOURCE_RISK = NO

DOMAIN = Goal/Settings
CANONICAL_SOURCE = training_cycles + user_goals via /api/training/v2/cycle and POST /api/training/v2/cycle/start-date
ALTERNATIVE_SOURCES = pre-PR216 frontend local state simulation only
RUNTIME_CONSUMERS = Settings, Training V2 cycle consumers
PERSISTED_CACHE_OR_HISTORY = training_cycles, user_goals
DOUBLE_SOURCE_RISK = NO after PR216 contract

--------------------------------------------------
FALLBACKS
--------------------------------------------------

FALLBACK = Race prediction single-observation prior
TRIGGER = only one qualified observed performance
VALUE = k = 1.06 prior with A fitted from data
CANONICAL_OR_LEGACY = CANONICAL
JUSTIFIED = YES
STATUS = retained

FALLBACK = Race prediction low-slope / k-conflict fallback
TRIGGER = slope evidence too weak or learned k outside guardrails
VALUE = fallback k = 1.06 with re-estimated intercept; predicted times preserved by current model policy
CANONICAL_OR_LEGACY = CANONICAL
JUSTIFIED = YES
STATUS = retained; confidence semantics fixed only

FALLBACK = Readiness unavailable state
TRIGGER = insufficient Garmin physio / activity evidence
VALUE = null score + unavailable badge/state
CANONICAL_OR_LEGACY = CANONICAL
JUSTIFIED = YES
STATUS = retained

FALLBACK = Training load unavailable state
TRIGGER = no chronic load / insufficient valid duration history
VALUE = acwr = null, no invented 1.0/0.1 fallback
CANONICAL_OR_LEGACY = CANONICAL
JUSTIFIED = YES
STATUS = retained

FALLBACK = Settings no-cycle behavior
TRIGGER = POST /api/training/v2/cycle/start-date with no existing cycle
VALUE = explicit HTTP 400
CANONICAL_OR_LEGACY = CANONICAL
JUSTIFIED = YES
STATUS = added

FALLBACK = Subscription fail-closed
TRIGGER = subscription lookup error / invalid state
VALUE = FREE tier, no premium grant
CANONICAL_OR_LEGACY = CANONICAL
JUSTIFIED = YES
STATUS = retained

--------------------------------------------------
TESTS
--------------------------------------------------

TESTS_BASE =
- Frontend comparison suite: 11/11 suites passed, 143/143 tests passed.
- Backend comparison suite: 677 passed, 49 failed, 56 errors, 3 skipped.
- Pre-existing failure/error buckets on BASE include:
  - tests/test_run_index_history_service.py stale expectations around insufficient snapshots (`run_index == None` vs old `0` assumption)
  - tests/test_run_index_pr179_domain_source.py assumptions/imports (`jobs.queue` import path, int expectation on insufficient case)
  - tests/test_run_index_r4b_history_readiness_v2.py and tests/test_run_index_r4c_history_load_v2.py async mock misuse (`MagicMock` awaited)
  - tests/test_run_index_compute_integration.py incomplete fake DB (`garmin_vo2max` missing)
  - tests/test_run_index_screen.py expects live localhost server
  - import-time harness issues in tests/test_garmin_vo2max_pr195.py, tests/test_garmin_vo2max_history_endpoint.py, tests/test_auth.py family

TESTS_HEAD =
- Frontend comparison suite: 11/11 suites passed, 142/142 tests passed.
- Backend comparison suite: 680 passed, 49 failed, 56 errors, 3 skipped.
- Targeted backend PR216 suites:
  - tests/test_run_index_current_single_source_pr216.py, tests/test_dashboard_insight_pr182.py, tests/test_training_cycle_start_date_endpoint.py = 14 passed
  - tests/test_performance_model_pr190.py targeted new confidence test passed
  - tests/test_run_index_history_service.py still shows the same 3 pre-existing failures already present on BASE
- Targeted frontend PR216 suites passed:
  - auth-ui, settings-page, i18n, progress-race-predictions-v2, progress-v2-migration

NEW_FAILURES_CAUSED_BY_PR216 = NONE IDENTIFIED IN BASE vs HEAD COMPARISON
PRE_EXISTING_FAILURES = backend comparison suite failures/errors listed above; identical buckets remain on BASE and HEAD

Representative BASE vs HEAD matrix:
- TEST = frontend comparison suite (11 suites)
  BASE = PASS
  HEAD = PASS
  CAUSED_BY_PR216 = NO
- TEST = backend comparison suite aggregate
  BASE = FAIL/ERROR
  HEAD = FAIL/ERROR
  CAUSED_BY_PR216 = NO
- TEST = backend/tests/test_run_index_current_single_source_pr216.py
  BASE = N/A
  HEAD = PASS
  CAUSED_BY_PR216 = NO
- TEST = backend/tests/test_training_cycle_start_date_endpoint.py
  BASE = N/A
  HEAD = PASS
  CAUSED_BY_PR216 = NO

--------------------------------------------------
FREEZE
--------------------------------------------------

V2_BLOCKERS_REMAINING = 2
V2_FREEZE_READY = NO
BLOCKER_1 = Training / Training Load / Training Plan still have unresolved double-source risk: /api/run-index computes canonical load from garmin_activities while training planning/coaching surfaces still source runtime windows from db.workouts before V2 conversion.
BLOCKER_2 = The required backend freeze comparison suite is not green on BASE or HEAD because of pre-existing failing/erroring critical tests, so freeze proof remains incomplete even though PR216 did not introduce new failures.

Detailed files modified in PR216:
- backend/services/run_index_history.py
- backend/training_v2/performance_model.py
- backend/access_control.py
- backend/server.py
- backend/tests/test_run_index_history_service.py
- backend/tests/test_run_index_current_single_source_pr216.py
- backend/tests/test_performance_model_pr190.py
- backend/tests/test_training_cycle_start_date_endpoint.py
- frontend/src/components/OAuthButtons.jsx
- frontend/src/lib/authErrors.js
- frontend/src/lib/i18n.js
- frontend/src/pages/Settings.jsx
- frontend/src/lib/i18n.test.js
- frontend/src/__tests__/auth-ui.test.jsx
- frontend/src/__tests__/settings-page.test.jsx

Contracts/API changes:
- /api/run-index/history now refreshes today's RunIndex snapshot from the canonical Garmin DomainActivity engine before reading history and returns current_run_index from that fresh snapshot.
- POST /api/training/v2/cycle/start-date added as the canonical writable backend contract for plan_start_date.
- Auth frontend now exposes Google and email/password only.

Residual risks:
1. Training domain source-of-truth still mixes garmin_activities and db.workouts depending on route.
2. Backend freeze proof is limited by pre-existing failing/erroring suites.
3. Apple backend endpoints remain present; frontend exposure is removed, but backend removal safety was not proven in this PR.
