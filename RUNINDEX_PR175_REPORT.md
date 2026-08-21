# RUNINDEX PR175 REPORT — TRAINING V2 — CYCLE CALENDAIRE NATIF

```
BASE_BRANCH = copilot/dev
HEAD_START   = 09a6eecb0aa416818abfa565ba1038a3003ab96c
HEAD_FINAL   = (see PR commit)
```

---

## CYCLE_AUTHORITY

```
Periodization V2
```

Seules les briques V2 existantes ont été utilisées :
- `PlanGoal V2` (`training_v2/plan_goal.py`)
- `Periodization V2` (`training_v2/periodization.py`)
  - `_build_race_phase_schedule` — planning de phases race_calendar
  - Constantes : `TAPER_WEEKS`, `CONTINUOUS_*_WEEKS`

---

## FUTURE_WEEKLY_PRESCRIPTION

```
NO
```

Le calendrier décrit uniquement les semaines (dates + phase).
Aucun `WeeklyTarget`, aucune prescription de volume, aucune session future.

---

## FUTURE_SESSIONS

```
NO
```

Les entrées `weeks[]` ne contiennent aucun des champs suivants :
`target_km`, `target_duration_minutes`, `session_count`, `sessions`,
`long_run`, `estimated_tss`, `intensity`, `pace`, `zones`.

---

## LEGACY_IMPORTS

```
0
```

`training_cycle_response.py` n'importe rien depuis :
- `training_engine.py`
- `llm_coach.py`
- `generate_cycle_week`
- Tout code legacy full-cycle

---

## BACKEND_FILES_CHANGED

```
backend/training_v2/training_cycle_response.py  [CRÉÉ]
backend/tests/test_pr175_training_v2_cycle.py   [CRÉÉ]
backend/access_control.py                        [MODIFIÉ — ajout /api/training/v2/cycle PREMIUM]
backend/server.py                                [MODIFIÉ — ajout endpoint GET /api/training/v2/cycle]
```

---

## FRONTEND_MODIFIED

```
NO
```

Aucun fichier frontend modifié.
`Dashboard.jsx`, `TrainingPlan.jsx`, `TrainingPlanV2.jsx`, `Progress.jsx`,
`Settings.jsx` — intacts.

---

## ACCESS_CONTROL_UPDATED

```
YES
```

`/api/training/v2/cycle` ajouté dans `ROUTE_ACCESS_MAP` au même niveau PREMIUM
que `/api/training/v2/week` :

```python
"/api/training/v2/week":  RouteAccess.PREMIUM,  # PR167
"/api/training/v2/cycle": RouteAccess.PREMIUM,  # PR175
```

---

## ENDPOINT

```
GET /api/training/v2/cycle
```

**Contrat de réponse :**

```json
{
  "reference_date": "2025-01-15",
  "goal": {
    "goal_type": "marathon",
    "target_distance_km": 42.195,
    "race_date": "2025-06-01",
    "target_time_seconds": null
  },
  "cycle": {
    "mode": "race_calendar",
    "status": "active",
    "start_date": "2025-01-01",
    "end_date": "2025-06-01",
    "current_week": 3,
    "total_weeks": 22,
    "days_to_race": 137
  },
  "weeks": [
    {
      "week_number": 1,
      "start_date": "2025-01-01",
      "end_date": "2025-01-07",
      "phase": "base",
      "is_current": false
    },
    "..."
  ]
}
```

**Modes :**
- `race_calendar` : goal avec `race_date` + goal_type ∈ {5k, 10k, half_marathon, marathon, ultra}
- `continuous` : maintenance ou goal sans `race_date` — cycle fixe 12 semaines

**CONTINUOUS structure :**
- 4 semaines base
- 5 semaines build
- 3 semaines consolidation

---

## CURRENT_WEEK GLOBAL

`current_week` est la position **globale** 1-based dans le cycle complet.

Exemple :
- 4 semaines base + semaine 2 de build → `current_week = 6`
- **Pas** `cycle_week` de la phase (qui serait 2)

---

## COHÉRENCE WEEK / CYCLE

- `cycle.goal` utilise les mêmes sources canoniques que `/training/v2/week`
  (`db.training_cycles` + `db.user_goals`)
- La semaine contenant `reference_date` a `is_current = true`
- Exactement **une** semaine `is_current = true` pour un cycle actif
- La phase de la semaine courante correspond à la phase Periodization V2

---

## TESTS

```
28 passed / 0 failed / 0 skipped / 0 errors
```

**Tests couverts (test_pr175_training_v2_cycle.py) :**

| # | Description | Statut |
|---|-------------|--------|
| 1 | maintenance → continuous 12 semaines | ✅ passed |
| 2 | continuous = 4 base / 5 build / 3 consolidation | ✅ passed |
| 3 | race goal futur → race_calendar | ✅ passed |
| 4 | phases race : base/build/specific/taper/race | ✅ passed |
| 5 | préparation courte valide | ✅ passed |
| 6 | race day → active, phase race, days_to_race == 0 | ✅ passed |
| 7 | race passée → completed, no is_current | ✅ passed |
| 8 | current_week global correct | ✅ passed |
| 9 | exactement un is_current (continuous) | ✅ passed |
| 9b | exactement un is_current (race active) | ✅ passed |
| 10 | aucune session dans le payload | ✅ passed |
| 11 | aucun target_km futur | ✅ passed |
| 12 | aucun target_duration_minutes futur | ✅ passed |
| 13 | aucun estimated_tss | ✅ passed |
| 14 | aucun import training_engine (AST) | ✅ passed |
| 15 | aucun import llm_coach (AST) | ✅ passed |
| 16 | endpoint /training/v2/cycle → PREMIUM (access_control) | ✅ passed |
| 17 | access_control aligné avec /training/v2/week | ✅ passed |
| 18 | déterminisme same reference_date (continuous) | ✅ passed |
| 18b | déterminisme same reference_date (race) | ✅ passed |
| 19 | cohérence goal avec /training/v2/week | ✅ passed |
| + | marathon sans race_date → continuous | ✅ passed |
| + | 5k → taper 1 semaine | ✅ passed |
| + | total_weeks == len(weeks) (continuous) | ✅ passed |
| + | total_weeks == len(weeks) (race) | ✅ passed |
| + | phase semaine courante == Periodization V2 | ✅ passed |
| + | endpoint existe dans server.py | ✅ passed |
| + | datetime.now() exactement 1 fois dans l'endpoint | ✅ passed |

**Tests V2 existants conservés verts :**
- `test_periodization_pr06.py` : 51 passed
- `test_pr167_training_v2_week_api.py` : 54 passed

---

## VERDICT

```
READY FOR MERGE INTO copilot/dev
```

- ✅ base exacte copilot/dev post-#174
- ✅ endpoint /training/v2/cycle natif
- ✅ calendrier issu de Periodization V2
- ✅ aucune prescription future
- ✅ aucun training_engine
- ✅ aucun llm_coach
- ✅ goal cohérent avec /training/v2/week
- ✅ current_week global correct
- ✅ aucun frontend
- ✅ tests 0 failed

Ne pas merger automatiquement.
Ne pas commencer #176.

STOP.
