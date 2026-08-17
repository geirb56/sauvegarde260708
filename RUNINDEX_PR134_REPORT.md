# RUNINDEX PR #134 — Weekly Reconciliation V2

## Delivery

| Item | Value |
|---|---|
| PR | #134 — Weekly Reconciliation V2 |
| HEAD main au départ | `b2f1ead055bd601cd0f407cb8a16b9f17adcd0f9` |
| #133 | MERGED |
| Status | IMPLEMENTED / PENDING MERGE |

---

## Fichiers modifiés

- `backend/training_v2/weekly_reconciliation.py` (NEW)
- `backend/training_v2/__init__.py` (exports PR134)
- `backend/tests/test_weekly_reconciliation_pr134.py` (NEW)
- `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md` (roadmap/status correction)
- `RUNINDEX_PR134_REPORT.md` (NEW)

---

## Contrat `WeeklyReconciliationResult`

- `action`: `KEEP | REDUCE_VOLUME | REDUCE_FREQUENCY | REDUCE_BOTH`
- `original_target`: `WeeklyTarget`
- `reconciled_target`: `WeeklyTarget`
- `reason_codes`: `tuple[str, ...]`
- `observed_runs_per_week`: `Optional[float]`
- `observed_distance_km`: `Optional[float]`
- `observed_duration_minutes`: `Optional[float]`
- `response_status`: `str`
- `confidence`: `str`

Model immutable (`frozen=True`).

---

## Formules V1 (calibration produit, recalibrable)

### Fréquence

- `FREQUENCY_REDUCTION_MARGIN = 0.75`
- Candidate réduction si:
  - `observed_runs_per_week < target_sessions * 0.75`
- Nouvelle cible:
  - `max(1, round_half_up(observed_runs_per_week))`
  - plafonnée à `<= target_sessions`

### Volume distance

- `weekly_observed_km = observed_distance_km / 4`
- `VOLUME_REDUCTION_MARGIN = 0.80`
- Candidate réduction si:
  - `weekly_observed_km < proposed_target.target_km * 0.80`
- Cible réconciliée:
  - `reconciled_km = max(weekly_observed_km, proposed_target.target_km * 0.85)`
  - puis `min(reconciled_km, proposed_target.target_km)`

### Volume durée

- `weekly_observed_minutes = observed_duration_minutes / 4`
- logique identique à la distance, sur les minutes
- aucune conversion durée ↔ km

---

## Règles clés

- `recent_response is None` → `KEEP + RECENT_RESPONSE_UNAVAILABLE`
- `response_status = unavailable` → `KEEP + RECENT_RESPONSE_UNAVAILABLE`
- `response_status = insufficient` → `KEEP + RECENT_RESPONSE_INSUFFICIENT`
- Aucune augmentation possible:
  - `target_sessions` ne peut jamais augmenter
  - `target_km` ne peut jamais augmenter
  - `target_duration_minutes` ne peut jamais augmenter
- `allow_intensity` inchangé
- `continuity_state` inchangé
- `target_basis` préservé (`duration` reste `duration`, `distance` reste `distance`)
- `DailyAdaptation` inchangé
- `ReadinessDecision` inchangé
- `WeeklyTarget` (formules internes) inchangé
- `WorkoutGenerator` inchangé
- `training_engine.py` inchangé
- Aucun `MOVE`, aucun LT1/LT2, aucun trail/D+

---

## Roadmap corrigée

- `#132 = MERGED`
- `#133 = MERGED`
- `#134 Weekly Reconciliation V2 = IMPLEMENTED / PENDING MERGE`
- NEXT conservé: audit migration consumers V2 / suppression `training_engine.py` avant LT1/LT2
