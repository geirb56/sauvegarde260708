# Rapport R4A — suppression du Readiness CURRENT legacy dans `/run-index`

## HEAD de départ

`522fbed01c14eff741bb72401bb697a56ea38d13`

Branche : `copilot/runindex-r4a-supprimer-readiness-current-legacy`

---

## Fichiers modifiés

| Fichier | Nature |
|---------|--------|
| `backend/garmin/insights.py` | suppression du calcul current legacy `physio_penalty` / `acwr_penalty` / `_legacy_run_readiness` et retrait de `metrics.legacy_run_readiness` du payload `/run-index` |
| `backend/tests/test_run_index_compute_integration.py` | validation que `metrics.run_readiness` suit exactement Readiness V2, que le cas `DEGRADED` garde un score V2, et que `legacy_run_readiness` est absent |
| `frontend/src/__tests__/dashboard-run-readiness-null.test.jsx` | fixture alignée avec le contrat `/run-index` sans `legacy_run_readiness` |
| `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md` | R3.5 marqué MERGED + runtime PASS, R4A marqué IMPLEMENTED / PENDING MERGE, dettes restantes rappelées |
| `docs/RUNINDEX_R4A_REPORT.md` | ce rapport |

---

## Scope exact R4A

Suppression **uniquement** du readiness current legacy exposé par `/run-index`.

Retiré :

- `physio_penalty` current legacy;
- `acwr_penalty` current legacy;
- `_legacy_run_readiness`;
- `metrics.legacy_run_readiness`;
- commentaires transitoires associés.

Conservé :

- Readiness V2 comme source unique de `metrics.run_readiness`;
- TrainingLoad V2 et `metrics.training_load_v2`;
- `fatigue_physio` et `fatigue_ratio`;
- `history[].run_readiness`;
- `/training/metrics` legacy;
- helpers TrainingLoad legacy encore appelés.

---

## Contrat `/run-index` après R4A

```json
{
  "metrics": {
    "run_readiness": 72.3,
    "run_readiness_status": "green",
    "confidence": "NORMAL",
    "sufficiency_level": "SUFFICIENT",
    "readiness_reasons": []
  }
}
```

`legacy_run_readiness` n'est plus exposé.

---

## Vérifications couvertes

| Exigence | Vérification |
|----------|--------------|
| `run_readiness = V2` | `test_run_readiness_matches_v2_score_sufficient` compare le payload à `build_readiness_v2_from_garmin_data(...)` |
| `legacy_run_readiness` absent | `test_legacy_run_readiness_absent_from_metrics` |
| `SUFFICIENT / DEGRADED / INSUFFICIENT` | cas suffisants, dégradés, insuffisants dans `backend/tests/test_run_index_compute_integration.py` |
| `None → UNAVAILABLE` | `test_insufficient_score_none_recommendation_unavailable_gray` |
| R3 / R3.5 non régressés | tests ciblés `/run-index` + alignment TrainingLoad V2 |
| multi-user | `test_multi_user_isolation_via_db_layer` et `test_queries_filtered_by_user_id` |

---

## Dettes explicitement conservées

- `history[].run_readiness` garde son calcul historique actuel;
- `/training/metrics` garde un helper TrainingLoad legacy;
- la divergence baseline RHR / historique reste hors périmètre.

---

## Périmètre non modifié

- aucune migration `history`;
- aucun changement `/training/metrics`;
- aucun travail LT1/LT2;
- aucun changement de formule Readiness V2;
- aucun refactor hors scope.

---

## NEXT

Suivre la roadmap canonique après merge de R4A :

1. traiter séparément la dette `history[].run_readiness`;
2. aligner séparément `/training/metrics` sur TrainingLoad V2;
3. traiter séparément la divergence baseline RHR / historique;
4. garder le cleanup legacy final pour une phase dédiée après validations runtime.
