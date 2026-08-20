# RUNINDEX_PR167_REPORT.md

## PR #167 — API TRAINING V2 NATIVE — CONTRAT SEMAINE COURANTE

---

### Identifiants

```
HEAD départ (post-#166) : dcd3e77
HEAD final #167         : d26f13d (pre-commit; voir commit push)
```

---

### Endpoint créé

```
GET /api/training/v2/week
```

---

### Fichiers modifiés / créés

| Fichier | Nature |
|---|---|
| `backend/training_v2/training_week_response.py` | NOUVEAU — modèles Pydantic V2 natifs |
| `backend/server.py` | MODIFIÉ — route `GET /training/v2/week` ajoutée |
| `backend/access_control.py` | MODIFIÉ — route enregistrée comme PREMIUM |
| `backend/tests/test_pr167_training_v2_week_api.py` | NOUVEAU — 43 tests contrat + architecture |
| `RUNINDEX_PR167_REPORT.md` | NOUVEAU — ce rapport |

Aucune modification de `training_v2/` existant, `training_engine.py`, adaptateurs legacy, ni frontend.

---

### Checklist additive

| Critère | Résultat |
|---|---|
| additive only | **YES** |
| frontend modified | **NO** |
| legacy endpoints modified | **NO** |
| `/training/plan` intact | YES |
| `/training/week-plan` intact | YES |
| `/training/full-cycle` intact | YES |
| `week_plan_adapter.py` intact | YES |
| `generate_cycle_week` intact | YES |
| `training_engine.py` intact | YES |

---

### Architecture builder

| Critère | Résultat |
|---|---|
| canonical builder | **`build_weekly_plan_from_workouts`** (week_plan_bridge.py) |
| WeeklyTarget duplicated | **NO** |
| WeeklyPlan duplicated | **NO** |
| adapter legacy used (`adapt_weekly_plan_to_legacy`) | **NO** |
| `generate_cycle_week` used | **NO** |
| `compute_target_km` used | **NO** |
| `reprise_durations` used | **NO** |
| `compute_long_run_km` used | **NO** |
| `apply_resume_guard` used | **NO** |
| `training_engine` used | **NO** |

---

### Contrats métier

| Contrat | target | planned |
|---|---|---|
| NORMAL_DISTANCE | `target_basis="distance"`, `target_km > 0`, `target_duration_minutes=null` | `planned_km = WeeklyPlan.planned_km`, `planned_duration_minutes=null` |
| DEEP_REPRISE_DURATION | `continuity_state="deep_reprise"`, `target_basis="duration"`, `target_duration_minutes > 0`, `target_km=null` | `planned_duration_minutes = WeeklyPlan.planned_duration_minutes`, `planned_km=null` |
| PARTIAL_REPRISE_DISTANCE | `continuity_state="partial_reprise"`, `target_basis="distance"` | `planned_km exact (±0.11 km)` |
| PARTIAL_REPRISE_DURATION | `continuity_state="partial_reprise"`, `target_basis="duration"`, `target_km=null` | `planned_duration_minutes = target_duration_minutes = 120 min` |
| NO_HISTORY | `target_km=null`, `target_duration_minutes > 0` | `planned_km=null`, durée canonique |

---

### Sémantique NONE

| Cas | Résultat |
|---|---|
| active session distance-based → `duration_minutes` | `null` |
| active session → `estimated_tss` | `null` |
| rest session → `estimated_tss` | `0` |
| UNKNOWN_COERCED_TO_ZERO | **0** |

---

### TSS doctrine

```
active estimated_tss = None   ✓
rest    estimated_tss = 0     ✓
```

Aucun calcul TSS ajouté dans le nouvel endpoint.

---

### Résultats tests

#### PR167 (tests_pr167_training_v2_week_api.py)

```
passed  : 43
failed  : 0
skipped : 0
errors  : 0
```

#### Non-régression (test_pr165 + test_workout_generator_v2 + test_weekly_target_v2)

```
passed  : 213
failed  : 0
skipped : 0
errors  : 0
```

---

### Smoke runtime

| Endpoint | Statut attendu |
|---|---|
| `/training/today` | 200 |
| `/training/plan` | 200 |
| `/training/metrics` | 200 |
| `/run-index` | 200 |
| `/dashboard` | 200 |
| `/training/week-plan` | 200 |
| `/training/full-cycle` | 200 |
| `/training/v2/week` | 200 (auth + premium) |

**Legacy smoke : 7/7 attendu** (endpoints non modifiés)  
**Nouvel endpoint : 1/1 attendu** (auth/premium identique aux autres routes training)

---

### Protection accès

Route enregistrée `RouteAccess.PREMIUM` dans `access_control.py` — même protection que `/training/week-plan`.  
Auth via `Depends(auth_user)` identique aux autres endpoints training.  
Aucune route publique accidentelle.

---

### Dettes nouvelles

**NONE**

---

### Mergeable

**YES** — aucune modification des moteurs V2 existants, aucun frontend, aucun legacy supprimé, 0 test failed.

---

## VERDICT

```
READY FOR MERGE INTO copilot/dev
```
