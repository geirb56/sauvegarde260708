# RUNINDEX_PR167_REPORT.md

## PR #167 — API TRAINING V2 NATIVE — CONTRAT SEMAINE COURANTE

---

### Identifiants

```
HEAD départ (post-#166) : dcd3e77
HEAD audité #167        : aee446326962abbf0f0806f5f14a9756cfdac3d0
HEAD final #167         : voir commit post-correction
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
| `backend/tests/test_pr167_training_v2_week_api.py` | MODIFIÉ — 54 tests (43 contrat + 11 ciblés blocker 1/2) |
| `RUNINDEX_PR167_REPORT.md` | MIS À JOUR — ce rapport |

Aucune modification de `training_v2/` existant, `training_engine.py`, adaptateurs legacy, ni frontend.

---

### CORRECTIONS POST-AUDIT

#### BLOCKER 1 — SOURCE CANONIQUE TARGET TIME

```
TARGET_TIME_SOURCE          = target_time_minutes  (champ DB user_goals)
TARGET_TIME_CONVERSION      = YES
TARGET_TIME_SECONDS_EXAMPLE = 120 min → 7200 sec
```

Le POST `/api/user/goal` persiste uniquement `target_time_minutes` dans la collection `user_goals`.
Le champ `target_time_seconds` n'existe pas en DB.

Correction appliquée dans `get_training_v2_week` :
```python
target_time_minutes_raw = user_goal.get("target_time_minutes") if user_goal else None
if isinstance(target_time_minutes_raw, (int, float)) and not isinstance(target_time_minutes_raw, bool) and target_time_minutes_raw > 0:
    target_time_seconds = int(target_time_minutes_raw * 60)
else:
    target_time_seconds = None
```

Règles :
- chrono présent et valide (int/float > 0) → `target_time_seconds = valeur * 60`
- chrono absent (None) → `None` (jamais 0)
- valeur invalide (0, négatif, bool, string) → `None`

#### BLOCKER 2 — HORLOGE UNIQUE

```
NOW_CALLS_IN_GET_TRAINING_V2_WEEK = 1
REFERENCE_DATE_SOURCE             = now_utc.date()
LOOKBACK_SOURCE                   = same now_utc
```

Correction appliquée :
```python
now_utc = datetime.now(timezone.utc)          # résolu UNE SEULE FOIS
reference_date = now_utc.date()
...
ninety_days_ago = now_utc - timedelta(days=90)
```

Aucun second `datetime.now()` dans l'endpoint.

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
| target_time absent → `target_time_seconds` | `null` (jamais 0) |

---

### TSS doctrine

```
active estimated_tss = None   ✓
rest    estimated_tss = 0     ✓
```

Aucun calcul TSS ajouté dans le nouvel endpoint.

---

### Résultats tests

#### PR167 (test_pr167_training_v2_week_api.py)

```
passed  : 54  (43 contrat + 11 ciblés blocker 1/2)
failed  : 0
skipped : 0
errors  : 0
```

Nouveaux tests ciblés inclus :
- `TARGET_TIME_MINUTES_TO_SECONDS` — 120 min → 7200 sec ✓
- `TARGET_TIME_ABSENT` — None → None ✓
- `TARGET_TIME_INVALID` — 0 / négatif / bool / string → None ✓
- `SINGLE_NOW_BOUNDARY` — exactement 1 appel datetime.now() ✓

#### Non-régression (test_pr165 + test_workout_generator_v2 + test_weekly_target_v2)

```
passed  : 213
failed  : 0
skipped : 0
errors  : 0
```

#### Total 4 fichiers requis

```
passed  : 267
failed  : 0
skipped : 0
```

---

### Smoke runtime

```
PRE_MERGE_RUNTIME_SMOKE         = NOT EXECUTABLE IN CURRENT ENVIRONMENT
POST_MERGE_EMERGENT_SMOKE_REQUIRED = YES
```

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

**YES** — deux blockers corrigés, 267 tests verts, aucune modification des moteurs V2 existants, aucun frontend, aucun legacy supprimé.

---

## VERDICT

```
READY FOR MERGE INTO copilot/dev
```

