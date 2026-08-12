# RunIndex — PR R2A Readiness Subscores V2 — Report

## 1) HEAD de départ

- `38b677d419c2fe75d094e58cadf44c2f8c74a829`

## 2) Fichiers modifiés

- `backend/training_v2/readiness_subscores.py` (nouveau)
- `backend/tests/test_training_v2_readiness_subscores.py` (nouveau)
- `backend/training_v2/__init__.py`
- `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`
- `RUNINDEX_R2A_READINESS_SUBSCORES_V2_PR_REPORT.md` (ce rapport)

## 3) Contrats créés

- `PhysioSubscore(score, rhr_component, hrv_component)`
- `SleepSubscore(score)`
- `LoadSubscore(score)`
- `ReadinessSubscores(physio, sleep, load)`

## 4) Calibrations produit utilisées

`PRODUCT_CALIBRATION_V1` implémentée explicitement:

- RHR delta bpm:
  - `<= 0 -> 100`
  - `(0, 2] -> 90`
  - `(2, 4] -> 75`
  - `(4, 6] -> 55`
  - `(6, 8] -> 35`
  - `> 8 -> 20`
- HRV delta %:
  - `>= -5 -> 100`
  - `[-10, -5) -> 90`
  - `[-20, -10) -> 70`
  - `[-30, -20) -> 45`
  - `< -30 -> 25`
- Sleep duration (h):
  - `>= 8 -> 100`
  - `[7, 8) -> 90`
  - `[6, 7) -> 70`
  - `[5, 6) -> 45`
  - `< 5 -> 20`
- Load (`load_change_percent`):
  - `<= 10 -> 100`
  - `(10, 25] -> 90`
  - `(25, 40] -> 75`
  - `(40, 60] -> 55`
  - `> 60 -> 35`

## 5) Comportement `None`

- Aucun fallback neutre inventé.
- `None` reste `None` sur chaque composant et chaque subscore.
- `load_change_percent is None -> LoadSubscore.score is None`.

## 6) Tests exécutés

- `python -m pytest tests/test_training_v2_readiness_subscores.py -q`
- `python -m pytest tests/test_training_v2_readiness_signals.py -q`
- `python -m pytest tests/test_training_v2_readiness_sufficiency.py -q`
- `python -m pytest tests/test_training_intensity_r1_7b.py -q`

## 7) Résultats

- `tests/test_training_v2_readiness_subscores.py`: **44 passed**
- `tests/test_training_v2_readiness_signals.py` + `tests/test_training_v2_readiness_sufficiency.py` + `tests/test_training_intensity_r1_7b.py`: **94 passed**
- Exécution combinée ciblée (4 suites): **138 passed**

## 8) Confirmation qu'aucun consumer produit n'a été migré

- Aucun changement sur `/api/run-index`, dashboard, `/training/today`, frontend, recommandations, sync provider.
- PR strictement additive dans `training_v2` + tests + document canonique.

## 9) Confirmation qu'aucun fallback legacy n'a été repris

- Aucun fallback legacy réintroduit (`RHR=55`, `sleep=7h`, `sleep score=70`, `ACWR=1`, etc.).
- Aucune formule legacy de `backend/garmin/insights.py` ou `backend/engine/readiness_engine.py` copiée.

## 10) État du document canonique

- `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md` mis à jour avec:
  - `Last verified against main: 38b677d...`
  - `R1.7B: MERGED (PR #115)`
  - `R2A: IMPLEMENTED IN PR / PENDING MERGE`
  - `R2B: NEXT`
  - décision produit LT1/LT2 canonique ajoutée.

## 11) Limites connues du LoadSubscore V1

- V1 reste volontairement conservateur et centré sur `load_change_percent`.
- `TrainingIntensityProfile` est volontairement hors calcul du LoadSubscore R2A.
- Aucune relation entre minutes moderate/vigorous et récupération n'est inventée en V1.
- Aucune conversion physiologique (LT1/LT2/TRIMP/TSS/EPOC/Recovery Time) n'est faite.
- Des calibrations plus fines sont reportées à des phases ultérieures.
