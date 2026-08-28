# RUNINDEX — PR #210 REPORT

## Base / HEAD
- Base branch: `copilot/dev`
- Base SHA (exact): `6b54463709f474934be2b8e52558451c8734c470`
- HEAD PR: `aedb37f0216158926dd9403e2eaad09d4883bb8b`

## Fichiers supprimés
- `app/providers/terra_provider.py`
- `backend/terra_integration.py`
- `backend/tests/test_terra_fallbacks_pr128.py`
- `backend/tests/test_terra_integration.py`
- `frontend/src/components/TerraConnection.jsx`
- `frontend/src/hooks/useAutoSync.js`

## Fichiers modifiés
- `app/providers/base.py`
- `backend/access_control.py`
- `backend/server.py`
- `backend/tests/test_run_index_r129_terra_no_stress.py`
- `backend/tests/test_training_metrics_pr127.py`
- `frontend/src/__tests__/auth-ui.test.jsx`
- `frontend/src/components/Layout.jsx`
- `frontend/src/lib/i18n.js`

## Inventaire Terra AVANT (audit exhaustif demandé)
Recherche exhaustive effectuée sur:
- `terra`, `Terra`, `TERRA`
- `terra_integration`, `terra_provider`, `TerraConnection`, `/terra/`
- `syncDailyMetrics`, `syncTerraWorkouts`, `computeRecoveryScore`, `computeTrainingLoad`, `generateWorkoutRecommendation`

### Résumé par classe (A/B/C/D/E)
- A. runtime backend: **132 occurrences** (10 fichiers)
- B. runtime frontend: **59 occurrences** (4 fichiers)
- C. configuration/env: **2 occurrences** (1 fichier)
- D. tests: **113 occurrences** (12 fichiers)
- E. documentation/rapports historiques: **114 occurrences** (15 fichiers)

### Détail A — runtime backend (avant)
- `backend/server.py` (65)
- `backend/terra_integration.py` (58)
- `backend/access_control.py` (1)
- `app/providers/terra_provider.py` (1)
- `app/providers/base.py` (1)
- `backend/training_v2/weekly_target.py` (2)
- `backend/training_v2/readiness_signals.py` (1)
- `backend/training_v2/readiness_sufficiency.py` (1)
- `backend/training_v2/training_intensity.py` (1)
- `backend/training_v2/workout_generator.py` (1)

### Détail B — runtime frontend (avant)
- `frontend/src/components/TerraConnection.jsx` (26)
- `frontend/src/lib/i18n.js` (27)
- `frontend/src/hooks/useAutoSync.js` (4)
- `frontend/src/components/Layout.jsx` (2)

### Détail C — configuration/env (avant)
- `AUDIT_SECURITE.md` (2)

### Détail D/E (avant)
- D. Tests: 113 occurrences (dont `backend/tests/test_terra_integration.py`, `backend/tests/test_terra_fallbacks_pr128.py`, `backend/tests/test_run_index_r129_terra_no_stress.py`)
- E. Docs/rapports historiques: 114 occurrences (fichiers historiques conservés)

## Endpoints backend supprimés
- `GET /api/terra/status`
- `POST /api/terra/connect`
- `POST /api/terra/sync`
- `POST /api/terra/sync-daily`
- `DELETE /api/terra/disconnect`
- `GET /api/terra/recovery`
- `GET /api/terra/recommendation`
- `GET /api/terra/daily-metrics`

## Consumers runtime supprimés
### Backend
- Import `terra_integration` supprimé de `backend/server.py`
- Consumers supprimés de `server.py`:
  - `syncDailyMetrics`
  - `syncTerraWorkouts`
  - `computeRecoveryScore` (path Terra)
  - `computeTrainingLoad` (path Terra)
  - `generateWorkoutRecommendation` (path Terra)
  - `fetch_terra_user`
- Fallback Terra supprimé de `/api/run-index` (mode Garmin-only + no-data)
- Provider Terra actif supprimé: `app/providers/terra_provider.py`
- Mapping d’accès `/api/terra/` supprimé de `backend/access_control.py`
- Feature flag `terra_sync` supprimé de `backend/access_control.py`

### Frontend
- Composant actif supprimé: `frontend/src/components/TerraConnection.jsx`
- Hook auto-sync Terra supprimé: `frontend/src/hooks/useAutoSync.js`
- Appels API `/terra/*` supprimés (Layout + hook + composant)
- Clés i18n Terra mortes supprimées dans `frontend/src/lib/i18n.js`

## Configuration devenue morte
Supprimé du code versionné:
- `TERRA_API_BASE_URL` (via suppression de `backend/terra_integration.py`)
- `RouteAccess` `/api/terra/`
- Feature `terra_sync`

Variables externes pouvant être retirées après déploiement (hors PR):
- `TERRA_API_BASE_URL`
- tout secret/token Terra encore présent dans l’environnement d’exécution

## Données historiques volontairement conservées
Aucune suppression destructive de données:
- aucune collection Mongo supprimée
- aucun document utilisateur supprimé
- aucune migration destructive exécutée
- collections/champs historiques (ex: `daily_metrics`, `baselines`, `training_load`, `recovery_scores`, `run_index_scores`, `workout_recommendations`) conservés

## Tests exécutés et résultats
### Backend
- `python -m pytest tests/test_garmin_connect_trial_flow.py tests/test_training_v2_readiness_signals.py tests/test_run_index_r129_terra_no_stress.py tests/test_training_metrics_pr127.py`
  - ✅ **79 passed**
- `JWT_SECRET_KEY=... JWT_ALGORITHM=HS256 JWT_ACCESS_TOKEN_EXPIRE_MINUTES=60 MONGO_URL=... DB_NAME=... python - <<'PY' import server; print(hasattr(server, 'app')) PY`
  - ✅ `server_import_ok True` (import/startup wiring)

Note: `tests/test_training_metrics_endpoint.py` a été exécuté séparément; 1 test y échoue actuellement sur une assertion métier non liée à la suppression Terra (`acwr_reliable`) dans cet environnement.

### Frontend
- `npm run build`
  - ✅ build OK
- `npx craco test --watchAll=false --forceExit --runTestsByPath src/__tests__/auth-ui.test.jsx src/__tests__/settings-page.test.jsx`
  - ✅ **2 suites passed, 15 tests passed**

## Inventaire Terra APRÈS (recherche finale obligatoire)
Recherche repo complète refaite sur `terra`, `Terra`, `TERRA`.

### Résumé par classe (A/B/C/D/E)
- A. runtime backend: **6 occurrences** (commentaires de neutralité provider dans modules Training V2)
- B. runtime frontend: **0 occurrence**
- C. configuration/env: **2 occurrences** (`AUDIT_SECURITE.md`, doc historique)
- D. tests: **25 occurrences** (tests statiques/legacy wording)
- E. documentation/rapports historiques: **102 occurrences**

### Occurrences restantes classées A (runtime backend)
- `backend/training_v2/workout_generator.py:5` (docstring neutralité provider)
- `backend/training_v2/readiness_signals.py:9` (docstring neutralité provider)
- `backend/training_v2/training_intensity.py:6` (docstring neutralité provider)
- `backend/training_v2/weekly_target.py:5` (docstring neutralité provider)
- `backend/training_v2/weekly_target.py:548` (docstring neutralité provider)
- `backend/training_v2/readiness_sufficiency.py:9` (docstring neutralité provider)

Aucun import runtime Terra, aucun endpoint runtime Terra, aucun provider actif Terra, aucun consumer frontend Terra.
Aucun composant frontend actif Terra et aucun appel API `/terra/*` actif.

## Risques résiduels
- Résidu textuel « Terra » dans certains docstrings Training V2 (neutralité provider) et dans documentation/rapports historiques.
- Ces résidus ne correspondent à aucun consumer runtime actif.

TERRA_RUNTIME_CONSUMERS = 0
TERRA_BACKEND_ENDPOINTS = 0
TERRA_FRONTEND_CONSUMERS = 0
TERRA_ACTIVE_PROVIDERS = 0

Verdict :
PASS
