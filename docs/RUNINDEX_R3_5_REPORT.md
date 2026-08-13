# Rapport R3.5 — TrainingLoad V2 source unique dans /run-index

## HEAD de départ

`9d9074d40e589a45c35343b8395099540a334f01`

Branche : `copilot/runindex-pr-r35-alignement-training-load-v2`
PR : #120

---

## Fichiers modifiés

| Fichier | Nature |
|---------|--------|
| `backend/garmin/insights.py` | `build_training_load()` appelé une seule fois par requête ; snapshot partagé avec Readiness V2 ; suppression fallback ACWR=1.0 legacy ; ajout `metrics.training_load_v2` pour observabilité |
| `backend/garmin/readiness_adapter.py` | Paramètre `load_snapshot` accepté ; skip du second calcul `build_training_load()` quand le snapshot est fourni |
| `backend/tests/test_run_index_r3_5_load_alignment.py` | 21 tests déterministes dont 9 appels réels à `compute_run_index(db, user_id, reference_date=…)` avec fake DB |
| `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md` | R3 marqué MERGED (PR #118), R3.5 documenté, dette `/training/metrics` documentée, NEXT R4A |
| `docs/RUNINDEX_R3_5_REPORT.md` | Ce rapport |

---

## Ancienne divergence

Avant R3.5, `/run-index` utilisait deux formules concurrentes pour la charge :

1. `compute_load_metrics()` (legacy) — fenêtres 7j/28j, ACWR fallback=1.0 quand
   chronic=0, estimation de durée depuis la distance (`6 min/km`).
2. `build_training_load()` (V2) — appelé via `readiness_adapter` pour alimenter
   `LoadSubscore` dans Readiness V2.

Ces deux chemins pouvaient produire des valeurs ACWR différentes pour les mêmes
activités.  Le champ `metrics.training_load` du payload exposait la valeur legacy
(avec fallback artificiel), pendant que le LoadSubscore Readiness V2 utilisait la
valeur V2 (sans fallback).

---

## Nouvelle source unique dans /run-index

`build_training_load(activities, today)` est appelé **exactement une fois** dans
`compute_run_index()`.  Le `TrainingLoadSnapshot` résultant est :

- exposé directement dans `metrics.training_load` (`snapshot.acwr`, `None` si unavailable) ;
- exposé dans `metrics.training_load_v2` (tous les champs du snapshot) ;
- passé à `build_readiness_v2_from_garmin_data(…, load_snapshot=snapshot)` pour
  que Readiness V2 réutilise le même objet sans second calcul.

### Comportements supprimés de /run-index

| Comportement legacy | Statut |
|--------------------|--------|
| ACWR fallback = 1.0 quand chronic_weekly_load == 0 | Supprimé |
| Estimation durée depuis distance (`6 min/km`) | Supprimé |
| Formule 7j/28j via `compute_load_metrics()` pour le payload | Supprimé |
| Double appel `build_training_load()` (insights + adapter) | Supprimé |

---

## Tests compute_run_index réels (tests A–I)

Les 9 tests suivants appellent `compute_run_index(db, user_id, reference_date=_REF)`
avec un `_FakeDB` déterministe et vérifient le vrai payload :

| ID | Assertion | Résultat |
|----|-----------|---------|
| A | `payload["metrics"]["training_load"] == round(build_training_load(acts, ref).acwr, 3)` | PASS |
| B | `payload["metrics"]["training_load_v2"]["acwr"] == snapshot.acwr` | PASS |
| C | `payload["metrics"]["training_load_v2"]["acute_load_7d"] == snapshot.acute_load_7d` | PASS |
| D | `payload["metrics"]["training_load_v2"]["load_28d"] == snapshot.load_28d` | PASS |
| E | `payload["metrics"]["training_load_v2"]["previous_7d_load"] == snapshot.previous_7d_load` | PASS |
| F | `payload["metrics"]["training_load_v2"]["load_change_percent"] == snapshot.load_change_percent` | PASS |
| G | 0 activités → `training_load is None`, `acwr is None`, `training_load_status == "gray"` | PASS |
| H | activities avec distance mais sans duration → `training_load is None` | PASS |
| I | multi-user : `compute_run_index(userA)` n'utilise pas activités userB | PASS |

---

## Comportement ACWR null

Quand `chronic_weekly_load == 0` (aucune activité, ou activités sans durée valide) :

- `TrainingLoadSnapshot.acwr = None`
- `TrainingLoadSnapshot.status = "unavailable"`
- `metrics.training_load = None` (jamais 1.0)
- `metrics.training_load_status = "gray"`
- `metrics.training_load_v2.acwr = None`

Aucun fallback artificiel.

---

## Absence fallback distance

Les activités fournissant uniquement `distance_m` sans `duration_s` valide
ne contribuent **aucune charge** :

- `acute_load_7d = 0.0`
- `load_28d = 0.0`
- `acwr = None`

La distance n'est jamais utilisée pour estimer une durée dans `build_training_load()`.

---

## Dette /training/metrics restante

`compute_load_metrics()` (legacy) reste encore utilisé par l'endpoint `/training/metrics`.

R3.5 garantit une source unique de vérité **uniquement pour** :
- `/run-index`
- Readiness V2

La migration de `/training/metrics` vers `build_training_load()` est prévue en R4
(hors périmètre PR #120).  Ne pas supprimer `compute_load_metrics()` tant que
`/training/metrics` l'appelle.

---

## Nombre et résultats exacts des tests

Fichier : `backend/tests/test_run_index_r3_5_load_alignment.py`

```
21 tests collectés — 21 passés — 0 échec — 0 erreur
```

| # | Nom du test | Statut |
|---|-------------|--------|
| 1 | test_A_training_load_equals_snapshot_acwr | PASS |
| 2 | test_B_training_load_v2_acwr_matches_snapshot | PASS |
| 3 | test_C_training_load_v2_acute_load_7d | PASS |
| 4 | test_D_training_load_v2_load_28d | PASS |
| 5 | test_E_training_load_v2_previous_7d_load | PASS |
| 6 | test_F_training_load_v2_load_change_percent | PASS |
| 7 | test_G_no_activities_training_load_none_status_gray | PASS |
| 8 | test_H_distance_only_no_load | PASS |
| 9 | test_I_multi_user_isolation | PASS |
| 10 | test_no_acwr_fallback_when_no_activities | PASS |
| 11 | test_training_load_none_when_no_chronic_load | PASS |
| 12 | test_acwr_not_invented_when_distance_only | PASS |
| 13 | test_distance_only_produces_zero_load | PASS |
| 14 | test_duration_drives_load_not_distance | PASS |
| 15 | test_readiness_score_unchanged_with_shared_snapshot | PASS |
| 16 | test_readiness_score_deterministic_across_calls | PASS |
| 17 | test_multi_user_isolation | PASS |
| 18 | test_snapshot_acwr_none_means_no_load | PASS |
| 19 | test_training_load_v2_block_consistency | PASS |
| 20 | test_training_load_v2_block_no_activities | PASS |
| 21 | test_acwr_status_to_color_mapping | PASS |

---

## Périmètre strict R3.5

Ce qui a été fait dans PR #120 :

- [x] `build_training_load()` = source unique pour `/run-index`
- [x] snapshot partagé avec Readiness V2 (pas de double calcul)
- [x] suppression fallback ACWR=1.0 dans `/run-index`
- [x] suppression fallback distance→durée dans `/run-index`
- [x] `metrics.training_load_v2` exposé pour observabilité
- [x] 9 tests `compute_run_index` réels avec fake DB (A–I)
- [x] documentation R3 MERGED, R3.5 PENDING, dette /training/metrics

Ce qui n'a PAS été fait (hors périmètre) :

- [ ] migration `/training/metrics` vers V2
- [ ] suppression `compute_load_metrics()`
- [ ] modification seuils ACWR
- [ ] modification LoadSubscore
- [ ] modification poids Readiness
- [ ] suppression readiness legacy
- [ ] historique readiness
- [ ] LT1/LT2
- [ ] merge

---

*Rapport généré sur branche PR #120 — NE PAS MERGER avant validation runtime.*
