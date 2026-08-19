HEAD départ: 51cc287 (branche copilot/fix-mock-in-test-pr155)

Cause du test-drift:
- Le mock PR155 exigeait encore `target_load` en 3e argument positionnel.
- Après PR157, `generate_cycle_week` est appelé sans `target_load` dans le chemin `/training/week-plan`.

Ancienne signature mock:
- `async def _inner(context, phase, target_load, goal, user_id):`

Nouvelle signature mock:
- `async def _inner(context, phase, goal, user_id="unknown", target_load=None, **kwargs):`

Fichiers modifiés:
- `backend/tests/test_pr155_week_plan_no_legacy.py`
- `RUNINDEX_PR158_REPORT.md`

Résultats des tests:
- `test_pr155_week_plan_no_legacy.py::TestWeekPlanPR155::test_happy_path` → passed
- `test_pr155_week_plan_no_legacy.py::TestWeekPlanPR155::test_no_legacy_training_goals_access` → passed
- `test_pr155_week_plan_no_legacy.py` → 5 passed
- `test_pr157_remove_determine_target_load.py` → 13 passed
- `test_pr156_no_unvalidated_tss_generate_cycle_week.py` → 11 passed
- `test_pr149_week_plan_v2.py::TestNoDefaultWeeklyKmFallback::test_no_history_no_invented_km` → 1 passed
- Totaux ciblés: passed=32, failed=0, skipped=0, errors=0

Erreurs d'environnement préexistantes:
- `pytest` absent au départ dans le sandbox.
- Import `pyOpenSSL` incompatible avec `pymongo` au départ (`AttributeError: module 'lib' has no attribute 'GEN_EMAIL'`).
- Résolu localement dans le sandbox pour exécuter les tests, sans modifier le dépôt.

Code applicatif modifié:
- NO

Mergeability:
- true
