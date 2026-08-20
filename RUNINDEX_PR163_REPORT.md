# RUNINDEX PR163 — Suppression du consumer legacy compute_long_run_km dans generate_cycle_week

## Rapport

---

### HEAD départ
```
068454f Merge pull request #162 from geirb56/copilot/copilotdev
```

### HEAD #163
Commit pushed via this PR.

---

### compute_long_run_km occurrences avant

| Localisation | Classification |
|---|---|
| `training_engine.py:341` — `def compute_long_run_km(...)` | DEFINITION |
| `llm_coach.py:25` — `from training_engine import compute_long_run_km` | RUNTIME_GENERATE_CYCLE_WEEK |
| `llm_coach.py:302` — `target_long_run = compute_long_run_km(target_km, goal)` | RUNTIME_GENERATE_CYCLE_WEEK |
| `training_v2/workout_generator.py:86-87` — migration matrix doc | DOC |
| `training_v2/weekly_target.py:92` — migration matrix doc | DOC |
| `tests/test_training_engine_pr2.py` | TEST |
| `tests/test_dynamic_plan_v2_pr135.py:231` (forbidden list for coach_service) | TEST |
| `tests/test_workout_generator_v2.py` | TEST |

### compute_long_run_km occurrences après

| Localisation | Classification |
|---|---|
| `training_engine.py:341` — `def compute_long_run_km(...)` | DEFINITION (inchangée) |
| `training_v2/workout_generator.py:86-87` | DOC |
| `training_v2/weekly_target.py:92` | DOC |
| `tests/test_training_engine_pr2.py` | TEST |
| `tests/test_dynamic_plan_v2_pr135.py:231` | TEST |
| `tests/test_workout_generator_v2.py` | TEST |

**RUNTIME_GENERATE_CYCLE_WEEK = 0** ✅  
La définition legacy reste en place (d'autres tests/docs l'utilisent) — suppression possible en PR suivante.

---

### WORKOUT_GENERATOR_ALREADY_AVAILABLE = YES

WorkoutGenerator V2 (`build_weekly_plan`) était déjà utilisé dans `coach_service.py`.  
Dans le chemin `/training/week-plan`, seul `WeeklyTarget V2` était construit.  
Tous les objets V2 intermédiaires (`runner_profile`, `plan_goal`, `periodization`) étaient déjà
instanciés à l'intérieur de `build_weekly_target_from_workouts` — il suffisait d'exposer
`build_weekly_plan` depuis le même point d'entrée.

---

### Architecture avant

```
/training/week-plan
  → build_weekly_target_from_workouts (V2)
      → WeeklyTarget.target_km → context["target_km_protected"]
  → generate_cycle_week(context)
      → compute_long_run_km(target_km, goal)   ← LEGACY
      → build long_run session with legacy distance
```

### Architecture après

```
/training/week-plan
  → build_weekly_plan_from_workouts (V2 bridge, PR163)
      → WeeklyTarget V2 + WeeklyPlan V2
      → WeeklyPlan.sessions[long_easy].distance_km → context["long_run_km_v2"]
  → generate_cycle_week(context)
      → target_long_run = context.get("long_run_km_v2") or 0   ← V2
      → build long_run session with V2 distance
```

---

### Source finale long_run = WorkoutGenerator V2 ✅

### import privé _compute_long_run_km ajouté = NO ✅

### coefficients V2 dupliqués = NO ✅

---

### Cas faible volume marathon

| Métrique | Valeur |
|---|---|
| target hebdo (V2) | 22.0 km |
| long run legacy | 8 km |
| long run V2 | 8.8 km |

_Proportionnel, pas de minimum artificiel._

### Cas faible volume semi

| Métrique | Valeur |
|---|---|
| target hebdo (V2) | 22.0 km |
| long run legacy | 8 km |
| long run V2 | 7.6 km |

_Proportionnel, aucun minimum 16 km._

### Cas volume élevé marathon

| Métrique | Valeur |
|---|---|
| target hebdo (V2) | 66.0 km |
| long run V2 | 26.4 km (< cap 28 km) |
| legacy | 29 km (dépassait le cap !) |

---

### Conservation somme hebdomadaire = YES ✅

`sum(session.distance_km) ≈ weekly_target.target_km` (tolérance ±0.2 km), vérifiée par test F.

### Duration-based = PASS ✅

Pas de `distance_km` injectée pour les semaines duration-based.  
`long_easy.distance_km` est `None` dans ce cas.  
`generate_cycle_week` utilise `context.get("long_run_km_v2") or 0` — aucun calcul legacy.

### TSS inchangé = YES ✅

`estimated_tss = None` / `total_tss = None` — doctrine inchangée.

---

### Fichiers modifiés

| Fichier | Nature de la modification |
|---|---|
| `backend/training_v2/week_plan_bridge.py` | Ajout `build_weekly_plan_from_workouts` (retourne `WeeklyTarget + WeeklyPlan`) |
| `backend/server.py` | Remplacement de `build_weekly_target_from_workouts` par `build_weekly_plan_from_workouts` ; extraction `long_run_km_v2` ; injection dans context |
| `backend/llm_coach.py` | Suppression import `compute_long_run_km` ; `target_long_run = context.get("long_run_km_v2") or 0` |
| `backend/tests/test_pr163_long_run_v2_authority.py` | 16 tests métier + non-duplication + transport context |

---

### Tests passed/failed/skipped/errors

```
tests/test_pr163_long_run_v2_authority.py   16 passed
tests/test_workout_generator_v2.py         119 passed
tests/test_training_engine_pr2.py           12 passed
tests/test_dynamic_plan_v2_pr135.py         20 passed
Total (relevant)                           167 passed, 0 failed
```

---

### Mergeability = true ✅

---

### Consumers legacy restants

| Consumer | Classification | Statut |
|---|---|---|
| `training_engine.def compute_long_run_km` | DEFINITION | Reste en place — utilisée par tests legacy et docs |
| `tests/test_training_engine_pr2.py` | TEST | Inchangé |
| `tests/test_workout_generator_v2.py` | TEST | Inchangé |
| `tests/test_dynamic_plan_v2_pr135.py` | TEST (liste forbidden pour coach_service) | Inchangé |

Aucun consumer RUNTIME restant dans `generate_cycle_week` ou `generate_full_cycle`.

---

### Dette suivante exacte

| Item | PR suggérée |
|---|---|
| Supprimer la définition legacy `compute_long_run_km` dans `training_engine.py` si plus aucun test/doc ne s'y réfère | PR164 (nettoyage) |
| Migrer `/training/full-cycle` pour utiliser WorkoutGenerator V2 (utilise encore `compute_target_km` legacy) | Hors scope PR163 |
