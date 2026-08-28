# RUNINDEX PR#214 — LEGACY FINAL CLEANUP REPORT
## VMA HR-speed + Dead Training Frontend

---

## 1. Base SHA / HEAD SHA

| Field | Value |
|-------|-------|
| Base branch | `copilot/dev` (after merge #213) |
| Base SHA | `80bfdbe0051d3884f731b7b731bbd3d9f4e63dd0` |
| HEAD SHA | `f5019a37d23faeb44642a8030cf15accd1edc136` |

---

## 2. Audit Résultats (avant modification)

### Occurrences identifiées par catégorie

| Pattern | Fichiers | Catégorie |
|---------|----------|-----------|
| `estimate_vma` | `backend/training_v2/performance_model.py`, `backend/server.py` (import + /vma-history endpoint), tests | A (runtime actif) / C (tests) |
| `vma_kmh` | `performance_model.py`, `server.py` (VMAEstimationResponse, helpers), `runner_profile.py` | A + D |
| `VMA_HISTORY` | `tests/test_performance_model_pr185.py` header | C |
| `vma-history` | `backend/server.py` (endpoint GET), `backend/access_control.py`, tests | A + C |
| `HR_SPEED_MODEL_SOURCE` | `performance_model.py`, tests | A + C |
| `VMAEstimate` (dataclass) | `performance_model.py`, tests | A + C |
| `_fit_hr_speed_model` | `performance_model.py` | A |
| `_linear_regression` | `performance_model.py` | A |
| `_is_usable_for_hr_model` | `performance_model.py` | A |
| `_hr_model_confidence` | `performance_model.py` | A |
| `_activities_in_vma_window` | `performance_model.py` | A |
| `VMA_WINDOW_DAYS` | `performance_model.py` | A |
| `VO2max = VMA × 3.5` | `server.py` (estimate_vma_from_race, estimate_vma_from_workouts, /vma-history endpoint), `performance_model.py` predict_races | A |
| `TrainingPlan.jsx` | `frontend/src/pages/TrainingPlan.jsx` | D (dead — not mounted in App.js) |
| `/training/full-cycle` | Only in dead `TrainingPlan.jsx` and existing structural tests | D (already removed from runtime in #212) |

### Consumers runtime actifs identifiés

| Endpoint / Chemin | Consumer frontend actif ? | Action |
|-------------------|--------------------------|--------|
| `GET /training/vma-history` | ❌ Non (TrainingPlan.jsx dead) | SUPPRIMÉ |
| `GET /user/vma-estimate` | ❌ Non (TrainingPlan.jsx dead) | SUPPRIMÉ |
| `estimate_vma()` in `predict_races()` | Interne à predict_races — sortie VMA dans athlete_profile | SUPPRIMÉ (VMA=None) |
| `TrainingPlan.jsx` | ❌ Non monté dans App.js | SUPPRIMÉ |

---

## 3. Fichiers supprimés

| Fichier | Raison |
|---------|--------|
| `frontend/src/pages/TrainingPlan.jsx` | Non monté, dead code — consumer du dead /training/full-cycle |

---

## 4. Endpoints supprimés

| Endpoint | Fichier | Raison |
|----------|---------|--------|
| `GET /training/vma-history` | `backend/server.py` | Aucun consumer frontend/runtime actif ; utilisait `estimate_vma()` et calculait `VO2max = VMA × 3.5` |
| `GET /user/vma-estimate` | `backend/server.py` | Aucun consumer actif (TrainingPlan.jsx supprimé) ; calculait `VO2max = VMA × 3.5` via `estimate_vma_from_race()` / `estimate_vma_from_workouts()` |

---

## 5. Code VMA HR-speed supprimé

### `backend/training_v2/performance_model.py`

Supprimé :
- `VMA_WINDOW_DAYS: int = 42` (constante)
- `REASON_HR_SPEED_MODEL_SOURCE`, `REASON_HR_RANGE_INSUFFICIENT`, `REASON_HR_LEVELS_INSUFFICIENT`, `REASON_HR_MODEL_POOR_FIT`, `REASON_EXTRAPOLATION_TOO_LARGE`, `REASON_NO_FCMAX`, `REASON_NO_DATA`, `REASON_INSUFFICIENT_ACTIVITIES`
- `MIN_DURATION_HR_MODEL_S`, `MIN_AVG_HR`, `MAX_AVG_HR`, `MIN_ACTIVITIES_HR_MODEL`, `MIN_DISTINCT_HR_LEVELS`, `MIN_HR_RANGE_BPM`, `MIN_R2`, `MAX_EXTRAPOLATION_RATIO`
- `_is_usable_for_hr_model()` — filtre HR-speed model
- `_linear_regression()` — régression speed = a × HR + b
- `_HRModelResult` dataclass
- `_fit_hr_speed_model()` — modèle HR-speed complet
- `_hr_model_confidence()` — confiance HR-speed
- `VMAEstimate` dataclass
- `_activities_in_vma_window()` / `activities_in_vma_window` alias
- `estimate_vma()` — fonction principale VMA estimation
- `PerformanceEstimate.vma` field (VMAEstimate)
- Dans `predict_races()` : appel `estimate_vma(...)`, calcul `VO2max = VMA × 3.5`, champs VMA dans `athlete_profile` → `None`
- Sections docstring spécifiques VMA

### `backend/server.py`

Supprimé :
- Import `estimate_vma` (ligne 86)
- `VMAEstimationResponse` dataclass
- `estimate_vma_from_race()` helper
- `estimate_vma_from_workouts()` helper
- `calculate_training_zones()` helper (utilisait `vma_kmh`)
- `GET /user/vma-estimate` endpoint complet
- `GET /training/vma-history` endpoint complet (~118 lignes)
- `result.vma.hr_model_n_activities` → `vma_efforts_count: 0`

### `backend/access_control.py`

Supprimé :
- `"/api/training/vma-history": RouteAccess.PREMIUM`
- `"vma_estimate"` from `FREE_FEATURES` frozenset

---

## 6. Preuve Race Predictions V2 reste indépendante/intacte

- `predict_races()` conservé dans son intégralité (`T(D) = A × D^k`)
- `_build_performance_curve()`, `_build_qualified_performance_pool()`, qualification V2 : **inchangés**
- `_resolve_fcmax()`, `_resolve_fcmax_robust()` : **conservés** (partagés avec qualification)
- `REASON_PERF_QUALIFIED_HR_SPEED` : **conservé** (utilisé dans `evaluate_performance_quality()`)
- `CONFIDENCE_HIGH_DAYS`, `CONFIDENCE_MEDIUM_DAYS` : **conservés**
- Tous les tests race predictions `test_performance_model_pr189.py` passent (27/27)
- Tous les tests `test_performance_model_pr190.py` passent (10/10)

---

## 7. Preuve Garmin VO2max reste intact

- `backend/garmin/service.py` : **aucune modification**
- Tests structurels PR214 vérifient que `garmin/service.py` parse correctement
- `test_garmin_vo2max_pipeline_unchanged` : PASSED

---

## 8. Tests supprimés / migrés et justification

### `backend/tests/test_performance_model_pr185.py`
Supprimés : `test_mandatory_1` à `test_mandatory_16`, `test_vma_*`, `test_vma_history_*`, `test_linear_regression_*`, `test_new_t3`, `test_new_t4`, `test_new_t6`, `test_new_t7`, `test_d1`–`test_d5` → exclusivement dédiés à `estimate_vma()` / HR-speed / fenêtre VMA.

Mis à jour : `test_athlete_profile_has_vo2max_note` → assertion mise à jour (`vo2max_note is None`)

Conservés : tous les tests race predictions, qualifications performances, FCmax robustesse, anti-régression.

### `backend/tests/test_performance_model_pr186.py`
Supprimés : `test_06` (vma moving duration), `test_07`–`test_11` (VMA window), `test_12` (trail VMA model), `test_25`–`test_27` (VMA window session counts)

### `backend/tests/test_performance_model_pr189.py`
Supprimé : `test_s_vma_output_mutations_do_not_change_race_predictions_architecture` — utilisait `pm.VMAEstimate` et `monkeypatch` sur `estimate_vma`. Le principe est désormais garanti structurellement.

### `backend/tests/test_data_isolation.py`
Supprimés :
- `_vma_history_app()`, `vma_history_client` fixture, `TestVmaHistoryIsolation` → endpoint `/training/vma-history` supprimé
- `_vma_estimate_app()`, `vma_estimate_client` fixture, `TestVmaEstimateIsolation` → endpoint `/user/vma-estimate` supprimé

### `backend/tests/test_progress_stats_v2_pr184.py`
Supprimé : `test_vma_history_endpoint_preserved` → endpoint supprimé, le test affirmerait une fausseté.

### Ajouté
`backend/tests/test_pr214_legacy_cleanup.py` — 13 tests structurels permanents :
- `test_legacy_hr_speed_vma_runtime_consumers_zero`
- `test_legacy_vma_history_endpoint_removed`
- `test_vma_history_not_in_access_control`
- `test_synthetic_vo2max_from_vma_runtime_consumers_zero`
- `test_legacy_training_plan_frontend_deleted`
- `test_legacy_training_plan_not_imported_in_active_pages`
- `test_legacy_full_cycle_active_consumers_zero`
- `test_performance_v2_formula_intact`
- `test_predict_races_vma_always_none_post_214`
- `test_performance_estimate_has_no_vma_field`
- `test_estimate_vma_not_importable`
- `test_vma_estimate_class_not_importable`
- `test_garmin_vo2max_pipeline_unchanged`

---

## 9. Tests exécutés + résultats — C214 Validation complète

### Garde-fous structurels

| Suite | PASS | FAIL | SKIP | Statut |
|-------|------|------|------|--------|
| `test_pr214_legacy_cleanup.py` | 13 | 0 | 0 | ✅ |
| `test_pr212_training_engine_runtime_consumers.py` | 5 | 0 | 0 | ✅ |

### Performance Model V2 — suite complète

| Suite | PASS | FAIL | SKIP | Statut |
|-------|------|------|------|--------|
| `test_performance_model_pr185.py` | 27 | 0 | 0 | ✅ |
| `test_performance_model_pr186.py` | 18 | 0 | 0 | ✅ |
| `test_performance_model_pr187.py` | 18 | 0 | 0 | ✅ |
| `test_performance_model_pr188.py` | 8 | 0 | 0 | ✅ |
| `test_performance_model_pr189.py` | 27 | 0 | 0 | ✅ |
| `test_performance_model_pr190.py` | 10 | 0 | 0 | ✅ |
| `test_performance_model_pr191.py` | 31 | 0 | 0 | ✅ |
| **Total** | **139** | **0** | **0** | ✅ |

### Training Paces V2 + API Contract

| Suite | PASS | FAIL | SKIP | Statut |
|-------|------|------|------|--------|
| `test_training_paces_v2_*.py` (all paces) | 55 | 0 | 0 | ✅ |

### Coach / LLM

| Suite | PASS | FAIL | SKIP | Statut |
|-------|------|------|------|--------|
| `test_pr211_coach_llm_cleanup.py` | 8 | 0 | 0 | ✅ |
| `test_coach_conversational.py` | — | 16 | — | PRE_EXISTING (live server requis) |
| `test_coach_load_context_pr128.py` | 11 | — | — | ✅ |

### Garmin VO2max / Progress

| Suite | PASS | FAIL | SKIP | Statut |
|-------|------|------|------|--------|
| `test_garmin_vo2max_pr195.py` | 56 | 0 | 0 | ✅ |
| `test_garmin_vo2max_history_endpoint.py` | 23 | 0 | 0 | ✅ |
| `test_progress_stats_v2_pr184.py` + Garmin queue | 22 | 0 | 0 | ✅ |
| **Total** | **101** | **0** | **0** | ✅ |

### Readiness V2

| Suite | PASS | FAIL | SKIP | Statut |
|-------|------|------|------|--------|
| Readiness V2 full (`test_readiness_v2_*.py`, etc.) | 181 | 0 | 0 | ✅ |

### Training V2

| Suite | PASS | FAIL | SKIP | Statut |
|-------|------|------|------|--------|
| `test_pr167_training_v2_week_api.py` | 54 | 0 | 0 | ✅ |
| `test_pr175_training_v2_cycle.py` | 43 | 0 | 4 | ✅ |
| `test_pr204_maintenance_endpoint.py` | 19 | 0 | 6 | ✅ |
| week plan V2 (pr149/155/162/163/165) | 66 | 0 | 0 | ✅ |
| Training V2 domain (load, domain_activity, workout_generator) | 187 | 0 | 0 | ✅ |

### Access Control / Sécurité

| Suite | PASS | FAIL | SKIP | Statut |
|-------|------|------|------|--------|
| `test_idor_authorization.py` | — | — | — | ✅ 39 passed |
| `test_demo_mode_security.py` | — | — | — | ✅ |
| `test_security_blockers_1.py` | — | — | — | ✅ |
| **Total** | **39** | **0** | **0** | ✅ |

### RunIndex Engine

| Suite | PASS | FAIL | SKIP | Statut |
|-------|------|------|------|--------|
| `test_run_index_r3_readiness_v2.py` | — | — | — | ✅ |
| `test_run_index_engine.py` | 54 | 0 | 0 | ✅ |
| `test_run_index_r3_5_load_alignment.py` + others | 77 | 0 | 0 | ✅ |
| `test_run_index_pr179_domain_source.py` | 23 | 4 | 0 | PRE_EXISTING (base SHA idem) |
| `test_run_index_r129_fatigue_removal.py` / `r5` | — | 21 | — | PRE_EXISTING (base SHA idem) |
| `test_run_index_screen.py` | — | 3 | — | PRE_EXISTING (live server requis) |

### Échecs PRE_EXISTING (base SHA `80bfdbe`)

| Test | Raison | Classification |
|------|--------|----------------|
| `test_run_index_pr179_domain_source.py` (4) | `ModuleNotFoundError: jobs.queue` + assert isinstance None int | PRE_EXISTING — idem sur base SHA |
| `test_run_index_r129_fatigue_removal.py` (21) | `TypeError: MagicMock can't be used in 'await'` | PRE_EXISTING — idem sur base SHA |
| `test_run_index_r5_history_fatigue_cleanup.py` (1) | `TypeError: MagicMock can't be used in 'await'` | PRE_EXISTING |
| `test_run_index_screen.py` (3) | `Connection refused localhost:8001` | PRE_EXISTING (live server) |
| `test_coach_conversational.py` (16) | `MissingSchema: Invalid URL` — live server requis | PRE_EXISTING |
| `test_cardio_coach_screen.py` (27) | `Connection refused localhost:8001` | PRE_EXISTING (live server) |

Aucun échec causé par PR#214.

---

## 10. Preuve non-régression PerformanceEstimate.vma

Recherche complète dans tout le runtime (hors tests et rapports) :

```
grep -rn "\.result\.vma\|perf\.vma\|PerformanceEstimate(.*vma=\|\.vma_kmh\b" backend/ frontend/src/
→ 0 résultats
```

Aucun consumer de `PerformanceEstimate.vma` ne reste dans le runtime.

### Training Paces V2 — preuve d'intégrité

- `test_training_paces_v2_*.py` : 55/55 PASSED
- Les allures V2 sont basées exclusivement sur VDOT (performances qualifiées)
- Garmin VO2max n'intervient pas dans le calcul des allures
- Aucun fallback VMA synthétique détecté

### Coach — preuve d'intégrité

- `test_pr211_coach_llm_cleanup.py` : 8/8 PASSED
- Patterns `perf.vma`, `result.vma`, `vma_kmh` : 0 occurrence dans `coach_service.py`
- VMA coach reste `None` (comportement volontaire)

### Garmin VO2max — preuve d'intégrité

- `test_garmin_vo2max_pr195.py` : 56/56 PASSED
- `test_garmin_vo2max_history_endpoint.py` : 23/23 PASSED
- `garmin/service.py` : aucune modification dans PR#214

### Access Control — preuve d'intégrité

- `test_idor_authorization.py` : 39/39 PASSED
- `"/api/training/vma-history"` supprimé de `PREMIUM_ROUTES` — aucune permission fantôme
- `"vma_estimate"` supprimé de `FREE_FEATURES` — aucun premium leak

---

## 11. Recherche exhaustive finale (post-C214)

| Pattern | Occurrences runtime | Catégorie |
|---------|--------------------|-----------| 
| `estimate_vma` | 0 | — |
| `VMAEstimate` | 0 | — |
| `_fit_hr_speed_model` | 0 | — |
| `HR_SPEED_MODEL_SOURCE` | 0 | — |
| `/training/vma-history` | 0 runtime | Mentions dans tests-garde et rapports uniquement |
| `/user/vma-estimate` | 0 runtime | — |
| `vma_kmh * 3.5` | 0 | — |
| `vma * 3.5` (runtime) | 0 | — |
| `TrainingPlan.jsx` | Supprimé | — |
| `/training/full-cycle` active consumer | 0 | Mentions historiques uniquement |
| `perf.vma` | 0 | — |
| `result.vma` | 0 | — |
| `estimated_vma_proxy * 3.5` | 1 (engine/run_index_engine.py:230) | Calcul RunIndex indépendant — PRE_EXISTING sur base SHA. N'utilise pas `estimate_vma()`. Utilise `avg_speed_kmh` réel. |

---

## Compteurs finaux

```
LEGACY_HR_SPEED_VMA_RUNTIME_CONSUMERS      = 0
LEGACY_VMA_HISTORY_ENDPOINT_EXISTS         = False
SYNTHETIC_VO2MAX_FROM_VMA_RUNTIME_CONSUMERS = 0
LEGACY_TRAINING_PLAN_FRONTEND_EXISTS       = False
LEGACY_FULL_CYCLE_ACTIVE_CONSUMERS         = 0
```

## Non-régression

```
PERFORMANCE_V2_FORMULA_CHANGED    = NO
TRAINING_PACES_V2_FORMULA_CHANGED = NO
READINESS_V2_FORMULA_CHANGED      = NO
TRAINING_V2_FORMULAS_CHANGED      = NO
GARMIN_VO2MAX_PIPELINE_CHANGED    = NO
```

---

*Généré par Copilot Task Agent — PR#214 RUNINDEX Legacy Cleanup + C214 Validation Non-Régression*
