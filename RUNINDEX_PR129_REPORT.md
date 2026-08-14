# PR #129 — Remove legacy fatigue_ratio / fatigue_status / fatigue_physio

**Branche :** `pr-129-remove-legacy-fatigue-ratio`
**Base :** `main` (après #128 runtime PASS)

---

## Objectif

Supprimer complètement `fatigue_ratio`, `fatigue_status` et `fatigue_physio` devenus
redondants avec Readiness V2. Aucune métrique fatigue parallèle à Readiness V2 ne subsiste.

---

## Audit préalable

| Fichier | Occurrences legacy |
|---|---|
| `backend/garmin/insights.py` | 9 |
| `backend/server.py` | 22 |
| `frontend/src/pages/Dashboard.jsx` | 6 |
| `frontend/src/pages/Onboarding.jsx` | 1 |
| `frontend/src/__tests__/dashboard-run-readiness-null.test.jsx` | 6 |
| `backend/tests/test_run_index_screen.py` | 6 |
| `backend/tests/test_cardio_coach_screen.py` | 6 |
| `backend/tests/test_run_index_r5_history_fatigue_cleanup.py` | 15 |
| `backend/tests/test_run_index_r4b_history_readiness_v2.py` | commentaire |
| `test_run_index_real_data.py` | 4 (scripts racine, non maintenus) |
| `test_cardio_coach_real_data.py` | 4 (scripts racine, non maintenus) |

---

## Suppressions effectuées

### backend/garmin/insights.py

- Supprimé : variables `w_hrv`, `w_rhr`, `w_sleep`, `hrv_term`
- Supprimé : calcul `fatigue_physio` (2 lignes)
- Supprimé : calcul `fatigue_ratio`
- Supprimé : calcul `fatigue_status`
- Supprimé : reason `"Ratio de fatigue {fatigue_ratio:.2f}"` (fr/es/en)
- Supprimé : champs `metrics.fatigue_physio`, `metrics.fatigue_ratio`, `metrics.fatigue_status`

### backend/server.py — Terra path (non-Garmin)

- Supprimé : calcul `fatigue_physio`, `fatigue_ratio`
- Supprimé : formule parallèle `_stress = 0.5 * hrv_delta + 0.3 * rhr_delta + 0.2 * sleep_score` et seuils `> 5.0` / `> 2.0`
- Supprimé : `fatigue_status`
- Supprimé : reason `f"Fatigue Ratio {fatigue_ratio:.2f}"`
- Supprimé : variables `doc_fatigue_physio`, `doc_fatigue_ratio` dans la boucle history
- Supprimé : `"fatigue_ratio"` dans les entrées history
- Supprimé : champs `metrics.fatigue_physio`, `metrics.fatigue_ratio`, `metrics.fatigue_status`
- Retenu : `recommendation = "UNAVAILABLE"` / `recommendation_color = "gray"` (Readiness V2 indisponible sur ce chemin — aucune formule physio inventée)

### backend/server.py — training-today (cardio-coach)

- Supprimé : lecture `fatigue_ratio` / `fatigue_status` depuis run-index
- Supprimé : fallback `fatigue_ratio = 1.0` / `fatigue_status = "green"`
- Supprimé : `"fatigue_ratio"` / `"fatigue_status"` du payload `fatigue`
- Conservé : `run_readiness`, `recommendation`, `recommendation_color`

### backend/server.py — docstring

- Mis à jour : suppression mention "fatigue ratio"
- Mis à jour : docstring adapt-session remplace `fatigue_ratio` par `recommendation`

### frontend/src/pages/Dashboard.jsx

- Remplacé : `fatigue_status` → `recommendation_color` (border + badge couleur)

### frontend/src/pages/Onboarding.jsx

- Remplacé : `fatigue_ratio` → `run_readiness` pour le calcul d'intensité

### frontend/src/__tests__/dashboard-run-readiness-null.test.jsx

- Supprimé : `fatigue_physio`, `fatigue_ratio`, `fatigue_status` des deux mocks

---

## Mises à jour tests

### backend/tests/test_run_index_screen.py

- Supprimé : `fatigue_physio`, `fatigue_ratio`, `fatigue_status` de `required_metric_keys`
- Supprimé : `fatigue_status` de `status_keys`
- Modifié : `test_history_entries_have_required_fields` — supprime assertion `fatigue_ratio`, ajoute assertion négative

### backend/tests/test_cardio_coach_screen.py

- Mêmes changements que `test_run_index_screen.py`

### backend/tests/test_run_index_r5_history_fatigue_cleanup.py

- Test 9 renommé `test_metrics_fatigue_ratio_absent` (anciennement `test_metrics_fatigue_ratio_non_regression`)
- Docstring mis à jour : `#129 — fatigue_ratio / fatigue_status / fatigue_physio fully removed`

---

## Nouveau fichier de tests

### backend/tests/test_run_index_r129_fatigue_removal.py

8 tests unitaires :

| # | Nom | Description |
|---|---|---|
| 1 | `test_metrics_no_fatigue_ratio` | `metrics` sans `fatigue_ratio` |
| 2 | `test_metrics_no_fatigue_status` | `metrics` sans `fatigue_status` |
| 3 | `test_metrics_no_fatigue_physio` | `metrics` sans `fatigue_physio` |
| 4 | `test_readiness_v2_still_present` | `run_readiness` / `confidence` toujours présents |
| 5 | `test_history_no_fatigue_ratio` | `history[]` sans `fatigue_ratio` |
| 6 | `test_recommendation_still_present` | recommendation_color valide |
| 7 | `test_reasons_no_fatigue_ratio_string` | pas de "Fatigue Ratio" dans les reasons |
| 8 | `test_multi_user_no_fatigue_fields` | isolation multi-user |

### backend/tests/test_run_index_r129_terra_no_stress.py

10 tests :

| # | Nom | Description |
|---|---|---|
| 1 | `test_no_stress_variable_assignment` | `_stress` absent du code Terra |
| 2 | `test_no_hrv_weighting` | `0.5 * hrv_delta` absent |
| 3 | `test_no_rhr_weighting` | `0.3 * rhr_delta` absent |
| 4 | `test_no_sleep_score_weighting` | `0.2 * sleep_score` absent |
| 5 | `test_no_physio_threshold_5` | seuil `> 5.0` absent |
| 6 | `test_no_physio_threshold_2` | seuil `> 2.0` absent |
| 7 | `test_garmin_path_recommendation_color_unchanged` | Garmin → green/yellow/red |
| 8 | `test_garmin_path_readiness_v2_intact` | Garmin → run_readiness/confidence/sufficiency_level |
| 9 | `test_terra_section_contains_unavailable` | Terra → UNAVAILABLE |
| 10 | `test_terra_section_contains_gray` | Terra → gray |

**Résultat : 18 tests PASSED (10 nouveaux + 8 r129 existants)**

---

## Conservé intact

- ✅ Readiness V2 (`run_readiness`, `run_readiness_status`, `confidence`, `sufficiency_level`, `readiness_reasons`)
- ✅ Sous-scores Readiness V2 (`physio`, `sleep`, `load`)
- ✅ TrainingLoad V2 (`training_load`, `training_load_status`, `training_load_v2`)
- ✅ Recommandations (RUN HARD / EASY RUN / REST / UNAVAILABLE)
- ✅ LT1/LT2 hors scope

---

## Documentation mise à jour

`docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md` :

- `#128` = MERGED + runtime PASS
- `#129` = IMPLEMENTED / PENDING MERGE
- `fatigue_ratio` legacy supprimé (metrics, history, reasons, frontend, coach)
- Aucune métrique fatigue parallèle à Readiness V2
- Aucune nouvelle formule physiologique parallèle à Readiness V2 n'est introduite
- Comportement Terra : `recommendation = "UNAVAILABLE"` / `recommendation_color = "gray"`
- NEXT = #130 migration consumers legacy + Weekly Target V2
- Section 24 mise à jour (comportement Terra documenté)
- Section 25 ajoutée (trajectoire canonique #130→#133→LT1/LT2, architecture training_v2/, interdiction planner monolithique)

---

## Résumé de validation

```
tests/test_run_index_r129_fatigue_removal.py          8 passed
tests/test_run_index_r129_terra_no_stress.py         10 passed
tests/test_run_index_r5_history_fatigue_cleanup.py   13 passed
Total: 31 passed, 0 failed
```

`/run-index` ne contient plus `fatigue_ratio` / `fatigue_status` / `fatigue_physio`.
Aucune nouvelle formule physiologique parallèle à Readiness V2 n'est introduite.
Terra : `recommendation = "UNAVAILABLE"` / `recommendation_color = "gray"`.
Dashboard / Onboarding migrent vers `recommendation_color` / `run_readiness`.
Readiness V2 inchangée. Multi-user OK.
