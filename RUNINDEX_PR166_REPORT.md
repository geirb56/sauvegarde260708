HEAD départ: 81eaa2d
HEAD #166: HEAD (current branch tip for PR166)

DRIFT_PR155 = CONFIRMED/FIXED
DRIFT_PR156 = CONFIRMED/FIXED
DRIFT_PR162 = CONFIRMED/FIXED

SCAN_RESULTS:
- server.generate_cycle_week patches before/after: 2 / 0
- build_weekly_target_from_workouts endpoint mocks before/after: 1 / 0
- stale week-plan source assumptions before/after: 4 / 0

Classification (backend/tests scan):
- CURRENT_CONTRACT:
  - test_pr149_week_plan_v2.py (build_weekly_target_from_workouts unit coverage)
  - test_pr163_long_run_v2_authority.py (bridge parity/unit contracts)
  - test_pr165_week_plan_v2_authority.py (runtime authority assertions)
- OBSOLETE_BY_PR165:
  - test_pr155_week_plan_no_legacy.py: patch("server.generate_cycle_week") in endpoint fixture
  - test_pr162_week_plan_observed_weekly_km.py: patch("server.generate_cycle_week") in endpoint fixture
  - test_pr162_week_plan_observed_weekly_km.py: patch("training_v2.week_plan_bridge.build_weekly_target_from_workouts") in endpoint fixture
  - test_pr162_week_plan_observed_weekly_km.py: D/E/F wording implied runtime week-plan authority
- LEGACY_UNIT_TEST:
  - test_pr153_fallback_no_unvalidated_tss.py
  - test_pr156_no_unvalidated_tss_generate_cycle_week.py
  - test_pr157_remove_determine_target_load.py
  - test_pr161_no_double_guard.py
  - test_pr162_week_plan_observed_weekly_km.py::test_d_distance_v2_target_protected_with_weekly_km_zero_no_legacy_calls
  - test_pr162_week_plan_observed_weekly_km.py::test_e_duration_reprise_valid_with_weekly_km_zero_no_fictive_baseline
  - test_pr162_week_plan_observed_weekly_km.py::test_f_tss_doctrine_unchanged_active_none_rest_zero_total_none
- DOC_ONLY:
  - test_pr162_week_plan_observed_weekly_km.py module docstring/classification text (updated)
- UNRELATED:
  - No unrelated runtime-path stale mocks found in backend/tests

OBSOLETE_BY_PR165 found = 4
OBSOLETE_BY_PR165 fixed = 4
OBSOLETE_BY_PR165 remaining = 0

code applicatif modifié = NO

PR155 semantic coverage = PASS
- canonical source = training_cycles
- db.training_goals consulted = never
- 400 no cycle = covered
- 400 unknown goal = covered
- 400 no start_date = covered
- happy path 200 = covered

PR156 TSS coverage = PASS
- active estimated_tss = None
- rest estimated_tss = 0
- total_tss = None
- no legacy TSS/km coefficients (AST)

PR156 distance test uses explicit valid distance context = YES
- target_km_protected > 0 and long_run_km_v2 > 0

PR162 observed weekly_km coverage = PASS
- positive observed weekly_km = km28_running/4
- zero history = 0.0 (not 20)
- non-running only = 0.0
- endpoint fixture migrated to build_weekly_plan_from_workouts + adapter

Tests run (backend):
- python -m pytest -q tests/test_pr1*.py tests/test_workout_generator_v2.py tests/test_weekly_target_v2.py

tests passed = 328
failed = 0
skipped = 0
errors = 0

mergeability = true
