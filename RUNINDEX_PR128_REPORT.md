# RUNINDEX — PR #128 — Training Load Metrics single source cleanup

## Résumé

- ACWR runtime unifié sur `training_v2.training_load.build_training_load()` / `TrainingLoadSnapshot.acwr`.
- `training_engine.build_training_context()` ne fabrique plus ACWR / CTL / ATL / TSB / risk legacy.
- `coach_service` injecte ACWR V2 réel quand `TrainingLoadSnapshot` existe, sinon `None`.
- `/api/dashboard` lit désormais la charge via le pipeline V2 aligné sur `/run-index`.
- `terra_integration.computeTrainingLoad()` est migré vers TrainingLoad V2.
- `backend/engine/training_load_engine.py` est supprimé après extinction des callers runtime.

## Contrat métier final

- ACWR : une seule implémentation métier en runtime.
- CTL / ATL / TSB : aucune implémentation réelle disponible, donc jamais calculés ni simulés.
- Zéro historique / zéro durée exploitable : `acwr = None`.
- Aucun fallback physiologique (`ACWR=1.0`, `CTL=40`, `ATL=45`, `TSB=-5/0`, distance→durée).

## Fichiers modifiés

- `backend/training_engine.py`
- `backend/coach_service.py`
- `backend/services/dashboard_service.py`
- `backend/engine/workout_selector.py`
- `backend/terra_integration.py`
- `backend/engine/training_load_engine.py` (supprimé)
- `backend/tests/test_dashboard_v2_pr128.py`
- `backend/tests/test_coach_load_context_pr128.py`
- `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`

## Tests ciblés

- `backend/tests/test_dashboard_v2_pr128.py`
- `backend/tests/test_coach_load_context_pr128.py`
- `backend/tests/test_training_metrics_endpoint.py`
- `backend/tests/test_training_metrics_pr127.py`
- `backend/tests/test_run_index_r3_5_load_alignment.py`

## Validation attendue

- `/run-index` = V2
- `/training/metrics` = V2
- `/api/dashboard` = V2
- coach = V2 ou `None`
- CTL / ATL / TSB jamais fabriqués
- multi-user non régressé
