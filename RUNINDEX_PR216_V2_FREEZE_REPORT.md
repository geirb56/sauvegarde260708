BASE_SHA = f03babc69233b64536824d7e8d87d2a65d31728b
AUDITED_CODE_SHA = b743aac621954c77bcfd1536a007f3bcd8197d15

--------------------------------------------------
FINAL VERDICT
--------------------------------------------------

PR_NUMBER = 216
PR_MODE = DRAFT
V2_BLOCKERS_REMAINING = 0
V2_FREEZE_READY = YES

Validated preserved items from earlier #216 work:
- RUNINDEX_CURRENT_SINGLE_SOURCE = YES
- DASHBOARD_PROGRESS_EQUAL = YES
- TODAY_SNAPSHOT_EQUAL_CURRENT = YES
- PAGE_LOAD_ORDER_INDEPENDENT = YES
- RACE_PREDICTION_FORMULA_CHANGED = NO
- RACE_PREDICTION_TIMES_CHANGED = NO
- CONFIDENCE_V2_FINALIZED = YES
- APPLE_AUTH_FRONTEND_EXPOSURE = 0
- GOOGLE_AUTH_PRESERVED = YES
- EMAIL_PASSWORD_AUTH_PRESERVED = YES
- PLAN_START_DATE_WRITABLE = YES

--------------------------------------------------
RUNINDEX CURRENT / HISTORY
--------------------------------------------------

RUNINDEX_CURRENT_CANONICAL_SOURCE = garmin_activities -> DomainActivity -> calculate_run_index_from_domain()
RUNINDEX_HISTORY_STORAGE = run_index_scores
RUNINDEX_HISTORY_CURRENT_SOURCE = refreshed today snapshot from canonical Garmin DomainActivity path
SECOND_SOURCE_OF_TRUTH_FOR_CURRENT = NO
RUNINDEX_DB_WORKOUTS_RUNTIME_CONSUMER = NO

Notes:
- `/api/dashboard/insight` computes current RunIndex from canonical Garmin DomainActivity data.
- `/api/run-index/history` refreshes today's snapshot from the same canonical path before responding.
- `run_index_scores` remains historical storage only; its latest persisted point no longer becomes an implicit authority for current score.
- `backend/services/run_index_history.py::load_user_workouts()` was confirmed dead for RunIndex runtime and removed.

--------------------------------------------------
DB.WORKOUTS INVENTORY (POST-C216)
--------------------------------------------------

FILE = backend/server.py
FUNCTION = get_workouts / get_workout / create_workout
CALLER = REST API
ENDPOINT_OR_WORKER = /api/workouts, /api/workouts/{id}
PURPOSE = user workout CRUD and compatibility surfaces
SOURCE_UPSTREAM = user/workout records
CANONICAL_V2_SOURCE = N/A for Training V2 calculations
AFFECTS_TRAINING_CALCULATION = NO
STATUS = NECESSARY_COMPATIBILITY

FILE = backend/server.py
FUNCTION = get_training_metrics
CALLER = training metrics route
ENDPOINT_OR_WORKER = /api/training/metrics
PURPOSE = distance-based display cards (`load_7`, `load_28`, monotony/strain) plus canonical ACWR snapshot
SOURCE_UPSTREAM = db.workouts for display-only km cards; garmin_activities for ACWR / TrainingLoad V2
CANONICAL_V2_SOURCE = garmin_activities -> DomainActivity -> build_training_load()
AFFECTS_TRAINING_CALCULATION = NO for V2 decision logic; YES for display-only compatibility cards
STATUS = NECESSARY_COMPATIBILITY

FILE = backend/server.py
FUNCTION = get_week_plan
CALLER = TrainingPlanV2 frontend
ENDPOINT_OR_WORKER = /api/training/week-plan
PURPOSE = weekly target + generated week plan
SOURCE_UPSTREAM = garmin_activities
CANONICAL_V2_SOURCE = garmin_activities -> DomainActivity -> week_plan_bridge / WeeklyTarget / WorkoutGenerator
AFFECTS_TRAINING_CALCULATION = YES
STATUS = CANONICAL

FILE = backend/server.py
FUNCTION = get_training_v2_week
CALLER = Training V2 week API consumers
ENDPOINT_OR_WORKER = /api/training/v2/week
PURPOSE = weekly target + structured Training V2 week response
SOURCE_UPSTREAM = garmin_activities
CANONICAL_V2_SOURCE = garmin_activities -> DomainActivity -> week_plan_bridge / WeeklyTarget / WorkoutGenerator
AFFECTS_TRAINING_CALCULATION = YES
STATUS = CANONICAL

FILE = backend/coach_service.py
FUNCTION = generate_dynamic_training_plan
CALLER = coach/training plan runtime
ENDPOINT_OR_WORKER = dynamic training plan generation path
PURPOSE = canonical Training V2 runtime plan generation and cache keying
SOURCE_UPSTREAM = garmin_activities
CANONICAL_V2_SOURCE = garmin_activities -> DomainActivity -> TrainingHistory/Load/Profile/State -> Periodization -> WeeklyTarget -> WorkoutGenerator
AFFECTS_TRAINING_CALCULATION = YES
STATUS = CANONICAL

FILE = backend/training_v2/week_plan_bridge.py
FUNCTION = workouts_to_domain_activities / build_weekly_plan_from_workouts
CALLER = training/week-plan and training/v2/week builders
ENDPOINT_OR_WORKER = bridge layer
PURPOSE = adapter into canonical DomainActivity-based WeeklyTarget flow
SOURCE_UPSTREAM = canonical DomainActivity inputs or compatibility workout dicts
CANONICAL_V2_SOURCE = DomainActivity
AFFECTS_TRAINING_CALCULATION = YES
STATUS = NECESSARY_COMPATIBILITY

FILE = backend/services/dashboard_service.py
FUNCTION = get_dashboard
CALLER = dashboard orchestration
ENDPOINT_OR_WORKER = dashboard service layer
PURPOSE = last_runs list only
SOURCE_UPSTREAM = db.workouts
CANONICAL_V2_SOURCE = `/api/run-index` for readiness/load metrics
AFFECTS_TRAINING_CALCULATION = NO
STATUS = NECESSARY_COMPATIBILITY

FILE = backend/garmin/service.py
FUNCTION = sync/backfill/self-heal fan-out
CALLER = Garmin sync pipeline
ENDPOINT_OR_WORKER = sync runtime
PURPOSE = maintain compatibility mirror into db.workouts after canonical ingestion
SOURCE_UPSTREAM = garmin_activities
CANONICAL_V2_SOURCE = garmin_activities
AFFECTS_TRAINING_CALCULATION = NO
STATUS = MIRROR

FILE = backend/garmin/backfill.py
FUNCTION = backfill_user / backfill_all
CALLER = backfill jobs
ENDPOINT_OR_WORKER = Garmin backfill runtime
PURPOSE = re-derive workouts mirror from canonical Garmin activities
SOURCE_UPSTREAM = garmin_activities
CANONICAL_V2_SOURCE = garmin_activities
AFFECTS_TRAINING_CALCULATION = NO
STATUS = MIRROR

FILE = backend/workers/event_worker.py
FUNCTION = activity_created worker
CALLER = stream worker
ENDPOINT_OR_WORKER = workouts fan-out worker
PURPOSE = mirror newly ingested Garmin activity into db.workouts
SOURCE_UPSTREAM = garmin_activities stream event
CANONICAL_V2_SOURCE = garmin_activities
AFFECTS_TRAINING_CALCULATION = NO
STATUS = MIRROR

FILE = backend/services/run_index_history.py
FUNCTION = load_user_workouts
CALLER = none
ENDPOINT_OR_WORKER = none
PURPOSE = legacy helper removed
SOURCE_UPSTREAM = db.workouts
CANONICAL_V2_SOURCE = garmin_activities for RunIndex
AFFECTS_TRAINING_CALCULATION = NO
STATUS = DEAD_LEGACY

--------------------------------------------------
TRAINING V2 SOURCE OF TRUTH GRAPH
--------------------------------------------------

SOURCE = garmin_activities
NORMALIZATION = garmin.domain_adapter.mongo_garmin_activities_to_domain()
TRAINING_HISTORY = training_v2.training_history.build_training_history()
TRAINING_LOAD = training_v2.training_load.build_training_load()
RUNNER_PROFILE = training_v2.runner_profile.build_runner_profile()
TRAINING_STATE = training_v2.training_state.build_training_state()
PLAN_GOAL = training_v2.plan_goal.build_plan_goal()
PERIODIZATION = training_v2.periodization.build_periodization()
WEEKLY_TARGET = training_v2.weekly_target.build_weekly_target()
WORKOUT_GENERATOR = training_v2.workout_generator.generate_structured_week()
RUNTIME_PLAN = training_v2.week_plan_bridge.build_weekly_plan_from_workouts() / coach_service.generate_dynamic_training_plan()

DOUBLE_SOURCE_RISK_FOR_TRAINING_V2 = NO
PROOF = divergent test dataset A in garmin_activities vs dataset B in db.workouts drives TrainingHistory, TrainingLoad, WeeklyTarget, and generated plan from A only.

--------------------------------------------------
NAMED TEST FAMILY CLASSIFICATION
--------------------------------------------------

FILE = test_run_index_history_service.py
CAUSE = stale insufficient-data expectations (`None` vs legacy `0`) in history assertions
BASE_BEHAVIOR = stale failures previously present
HEAD_BEHAVIOR = corrected to canonical `None` semantics; suite passes
RUNTIME_BUG = NO
TEST_BUG = YES
FIX_REQUIRED_FOR_FREEZE = YES

FILE = test_run_index_pr179_domain_source.py
CAUSE = harness stubs missing `jobs.queue` and stale single-activity int expectations
BASE_BEHAVIOR = broken import / outdated expectation
HEAD_BEHAVIOR = harness fixed; insufficient single-activity cases now assert `run_index is None`; suite passes
RUNTIME_BUG = NO
TEST_BUG = YES
FIX_REQUIRED_FOR_FREEZE = YES

FILE = test_run_index_r4b_history_readiness_v2.py
CAUSE = async mock chain incomplete for `garmin_vo2max.find_one`
BASE_BEHAVIOR = harness failure (`MagicMock` awaited)
HEAD_BEHAVIOR = harness fixed; suite passes
RUNTIME_BUG = NO
TEST_BUG = YES
FIX_REQUIRED_FOR_FREEZE = YES

FILE = test_run_index_r4c_history_load_v2.py
CAUSE = async mock chain incomplete for `garmin_vo2max.find_one`
BASE_BEHAVIOR = harness failure (`MagicMock` awaited)
HEAD_BEHAVIOR = harness fixed; suite passes
RUNTIME_BUG = NO
TEST_BUG = YES
FIX_REQUIRED_FOR_FREEZE = YES

FILE = test_run_index_compute_integration.py
CAUSE = fake DB missing `garmin_vo2max`
BASE_BEHAVIOR = harness failure
HEAD_BEHAVIOR = fake DB updated; suite passes
RUNTIME_BUG = NO
TEST_BUG = YES
FIX_REQUIRED_FOR_FREEZE = YES

FILE = test_run_index_screen.py
CAUSE = localhost/live-server dependency
BASE_BEHAVIOR = live environment requirement
HEAD_BEHAVIOR = unchanged; excluded from deterministic freeze suite
RUNTIME_BUG = NO
TEST_BUG = NO
FIX_REQUIRED_FOR_FREEZE = NO

FILE = test_garmin_vo2max_pr195.py
CAUSE = prior environment/import instability during early follow-up runs
BASE_BEHAVIOR = not reliably runnable before env stabilization
HEAD_BEHAVIOR = deterministic suite passes after env stabilization
RUNTIME_BUG = NO
TEST_BUG = NO
FIX_REQUIRED_FOR_FREEZE = YES

FILE = test_garmin_vo2max_history_endpoint.py
CAUSE = prior environment/import instability during early follow-up runs
BASE_BEHAVIOR = not reliably runnable before env stabilization
HEAD_BEHAVIOR = deterministic suite passes after env stabilization
RUNTIME_BUG = NO
TEST_BUG = NO
FIX_REQUIRED_FOR_FREEZE = YES

FILE = test_auth.py
CAUSE = prior environment/import instability during early follow-up runs
BASE_BEHAVIOR = not reliably runnable before env stabilization
HEAD_BEHAVIOR = deterministic suite passes after env stabilization
RUNTIME_BUG = NO
TEST_BUG = NO
FIX_REQUIRED_FOR_FREEZE = YES

--------------------------------------------------
DETERMINISTIC FREEZE SUITE
--------------------------------------------------

BACKEND_FREEZE_SUITE = PASS
BACKEND_FREEZE_SUITE_RESULT = 604 passed
FRONTEND_FREEZE_SUITE = PASS
FRONTEND_FREEZE_SUITE_RESULT = 18 passed / 3 suites
NETWORK_REQUIRED = NO
LIVE_SERVER_REQUIRED = NO
PRODUCTION_SECRETS_REQUIRED = NO
REAL_GARMIN_ACCOUNT_REQUIRED = NO

Backend files included:
- tests/test_run_index_current_single_source_pr216.py
- tests/test_run_index_history_service.py
- tests/test_run_index_pr179_domain_source.py
- tests/test_run_index_compute_integration.py
- tests/test_run_index_r4b_history_readiness_v2.py
- tests/test_run_index_r4c_history_load_v2.py
- tests/test_training_v2_readiness.py
- tests/test_training_v2_readiness_decision.py
- tests/test_training_v2_readiness_signals.py
- tests/test_training_v2_readiness_subscores.py
- tests/test_training_v2_readiness_sufficiency.py
- tests/test_pr155_week_plan_no_legacy.py
- tests/test_pr165_week_plan_v2_authority.py
- tests/test_pr167_training_v2_week_api.py
- tests/test_training_source_of_truth_pr216.py
- tests/test_dynamic_plan_v2_pr135.py
- tests/test_pr211_coach_llm_cleanup.py
- tests/test_performance_model_pr190.py
- tests/test_training_paces_pr194.py
- tests/test_garmin_vo2max_pr195.py
- tests/test_garmin_vo2max_history_endpoint.py
- tests/test_training_cycle_start_date_endpoint.py
- tests/test_auth.py
- tests/test_unique_subscription.py

Frontend files included:
- src/__tests__/auth-ui.test.jsx
- src/__tests__/settings-page.test.jsx
- src/lib/i18n.test.js

Coverage summary against requested freeze domains:
- RunIndex = covered
- RunIndex history/current = covered
- Readiness V2 = covered
- TrainingHistory V2 = covered by source-of-truth and week-plan suites
- TrainingLoad V2 = covered
- Training Plan V2 = covered
- Weekly Target = covered
- Performance Model V2 = covered
- Race Predictions Confidence = covered
- Training Paces = covered
- Garmin VO2max = covered
- Settings plan_start_date = covered
- Auth Google/email contract = covered
- Subscription/access = covered

--------------------------------------------------
DEPENDENCY / LOCKFILE AUDIT
--------------------------------------------------

PACKAGE_CHANGE_RETAINED_IN_FOLLOWUP = NO
CURRENT_REPO_PIN = @testing-library/jest-dom 6.9.1
LOCKFILE_CHURN_ADDED_IN_THIS_FOLLOWUP = NO
ASSESSMENT = kept repository-supported frontend harness baseline; no new dependency or lockfile change was introduced in the C216 follow-up, and the targeted frontend freeze suite passes under the current pin.

--------------------------------------------------
FILES CHANGED IN C216 FOLLOW-UP
--------------------------------------------------

- backend/coach_service.py
- backend/server.py
- backend/services/run_index_history.py
- backend/tests/test_dynamic_plan_v2_pr135.py
- backend/tests/test_real_cache_bypass_pr76.py
- backend/tests/test_run_index_compute_integration.py
- backend/tests/test_run_index_history_service.py
- backend/tests/test_run_index_pr179_domain_source.py
- backend/tests/test_run_index_r4b_history_readiness_v2.py
- backend/tests/test_run_index_r4c_history_load_v2.py
- backend/tests/test_training_source_of_truth_pr216.py
- backend/training_v2/week_plan_bridge.py

--------------------------------------------------
CONCLUSION
--------------------------------------------------

- The critical Training V2 double-source blocker is resolved on the real runtime calculation paths.
- `db.workouts` remains only for compatibility, CRUD, display cards, and mirror/self-heal surfaces, not as the authority for Training V2 decisions.
- Previously failing critical V2 freeze tests were fixed as test-harness or stale-expectation issues without changing business formulas to satisfy legacy assumptions.
- The deterministic V2 freeze suite now passes locally without external services.
