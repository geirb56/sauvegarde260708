# RUNINDEX PR #215 — Cleanup RunIndex Score (remove synthetic VMA/VO2 proxy)

## 1) Base SHA

- `BASE_SHA = b5990b7a7856121f3a175713f34ddf7f7b86458e` (`origin/copilot/dev`, post-merge #214)

## 2) HEAD SHA

- `HEAD_SHA = 7d799df417cb42d5d533d35df3205c67741e2f94`

## 3) Audit avant modification (exhaustif sur termes demandés)

Source auditée en priorité : `backend/engine/run_index_engine.py`, puis recherche runtime/tests/reports sur :

- `estimated_vma_proxy`
- `vma_proxy`
- `speed_proxy`
- `* 3.5`
- `VO2`, `VO2max`, `VMA`
- `speed / 0.85`, `speed / 0.90`, `speed / 0.95`
- `calculate_speed`
- `performance pillar`
- `race_performance_score`
- `sustained_speed_score`

Classification des occurrences pertinentes:

| Occurrence | Emplacement | Classe |
|---|---|---|
| `estimated_vma_proxy = speed / 0.85` | `backend/engine/run_index_engine.py:225` (BASE) | A (runtime actif) |
| `estimated_vma_proxy = speed / 0.90` | `backend/engine/run_index_engine.py:227` (BASE) | A |
| `estimated_vma_proxy = speed / 0.95` | `backend/engine/run_index_engine.py:229` (BASE) | A |
| `speed_proxy_candidates.append((estimated_vma_proxy * 3.5, run))` | `backend/engine/run_index_engine.py:230` (BASE) | A |
| `speed_proxy_score` doc/code/weights/composants | `backend/engine/run_index_engine.py` (BASE) | A |
| `calculate_speed_score`, `race_performance_score`, `sustained_speed_score` | `backend/engine/run_index_engine.py` | A |
| `* 3.5` patterns (guards) | `backend/tests/test_pr214_legacy_cleanup.py` | B (test actif) |
| mentions `speed_proxy_score` / legacy proxy | `RUNINDEX_PR181_REPORT.md`, `RUNINDEX_PR214_REPORT.md` | D (historique/report) |
| termes `VO2`/`VO2max`/`VMA` hors moteur RunIndex (Garmin, Training Paces V2, docs, chat text) | `backend/garmin/*`, `backend/training_v2/training_paces.py`, `backend/server.py`, etc. | A/B/D selon fichier, sans consumer RunIndex speed proxy |

Dead code explicite détecté sur ce sujet: **aucun nouveau C identifié** dans ce scope.

## 4) Formule legacy supprimée

Chemin supprimé du moteur RunIndex Speed:

- `speed / 0.85`
- `speed / 0.90`
- `speed / 0.95`
- puis `* 3.5`

Suppression faite dans : `backend/engine/run_index_engine.py`.

## 5) Nouvelle composition exacte du pilier Speed/Performance

`calculate_speed_score()` repose désormais uniquement sur signaux observés:

- `race_performance_score`
- `sustained_speed_score`

Aucune conversion `%VMA`, aucune pseudo-VO2, aucun fallback physiologique.

## 6) Poids avant / après

### Speed pillar interne

- **Avant**: `race_performance_score=60%`, `speed_proxy_score=25%`, `sustained_speed_score=15%`
- **Après**: `race_performance_score=80%`, `sustained_speed_score=20%`

Choix retenu: **Option A** (suppression de la composante proxy et renormalisation des composantes observées restantes).

### Poids globaux RunIndex (inchangés)

- `Speed 40%`, `Endurance 25%`, `Consistency 20%`, `Efficiency 15%` (inchangé)

## 7) Justification

Le proxy supprimé simulait implicitement VMA/VO2 à partir de l’allure via une conversion `%VMA` puis `×3.5`, ce qui contrevient au principe produit demandé.  
La renormalisation conserve le pilier Speed/Performance sans introduire de nouvelle formule physiologique arbitraire, en gardant uniquement des signaux observés.

## 8) Preuve qu’aucun signal physiologique synthétique ne reste dans le runtime visé

Compteurs runtime (backend `.py` hors tests, hors commentaires) :

- `SYNTHETIC_VMA_PROXY_RUNTIME_CONSUMERS = 0`
- `SYNTHETIC_VO2_FROM_SPEED_RUNTIME_CONSUMERS = 0`
- `SPEED_PERCENT_VMA_CONVERSIONS = 0`

Vérification structurelle additionnelle:

- `backend/tests/test_pr215_runindex_speed_cleanup.py` ajouté
- `backend/engine/run_index_engine.py`: aucune occurrence de `estimated_vma_proxy`, `speed_proxy`, `speed/0.85|0.90|0.95`, `*3.5` liée vitesse/VMA.

## 9) Tests exécutés

### Pass

1. `python -m pytest tests/test_run_index_engine.py tests/test_pr215_runindex_speed_cleanup.py tests/test_pr214_legacy_cleanup.py`  
   → **55 passed**
2. `python -m pytest tests/test_performance_model_pr185.py tests/test_performance_model_pr186.py tests/test_performance_model_pr189.py tests/test_performance_model_pr190.py tests/test_pr191_slope_evidence.py tests/test_training_paces_pr194.py`  
   → **175 passed**

### Échecs observés (hors scope PR215)

3. `python -m pytest tests/test_run_index_compute_integration.py tests/test_run_index_r3_readiness_v2.py tests/test_run_index_r4b_history_readiness_v2.py tests/test_garmin_vo2max_pr195.py`  
   → **25 failed, 98 passed**

Types d’échec :
- `AttributeError: '_FakeDB' object has no attribute 'garmin_vo2max'`
- `TypeError: object MagicMock can't be used in 'await' expression`

## 10) Comparaison base vs HEAD si échec

Comparaison exécutée sur la base (`origin/copilot/dev`) pour les suites en échec:

- `python -m pytest tests/test_run_index_compute_integration.py tests/test_run_index_r4b_history_readiness_v2.py` sur BASE  
  → **25 failed** avec mêmes signatures d’erreur.

Classification:

- `CAUSED_BY_PR215 = 0`
- `PRE_EXISTING_BASELINE = 25`

## 11) Recherche exhaustive finale

Vérifications finales:

- runtime backend (hors tests): plus aucune occurrence de `estimated_vma_proxy`, `vma_proxy`, `speed_proxy`, `speed / 0.85`, `speed / 0.90`, `speed / 0.95`, `*3.5` lié au chemin speed/VMA.
- tests: occurrences conservées uniquement dans garde-fous structurels.
- reports/docs: occurrences legacy/historiques conservées en contexte documentaire.

Compteurs finaux:

- `SYNTHETIC_VMA_PROXY_RUNTIME_CONSUMERS = 0`
- `SYNTHETIC_VO2_FROM_SPEED_RUNTIME_CONSUMERS = 0`
- `SPEED_PERCENT_VMA_CONVERSIONS = 0`

Confirmations demandées:

- `RUNINDEX_GLOBAL_PILLAR_WEIGHTS_CHANGED = NO`
- `PERFORMANCE_V2_FORMULA_CHANGED = NO`
- `TRAINING_PACES_V2_FORMULA_CHANGED = NO`
- `READINESS_V2_FORMULA_CHANGED = NO`
- `GARMIN_VO2MAX_PIPELINE_CHANGED = NO`
