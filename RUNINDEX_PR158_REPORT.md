# RUNINDEX_PR158_REPORT.md

## Objectif

Retirer le consumer legacy `determine_target_load(...)` du chemin `GET /training/week-plan`.

---

## HEAD copilot/dev au départ

```
de22c78  Merge pull request #156 from geirb56/claude/copilotdev
```

---

## Confirmation #157 non reprise

**YES — aucun commit de #157 repris.**
Branche repart exclusivement de `de22c78` (post-#156 merge).

---

## DETERMINE_TARGET_LOAD_ROLE

**= DISPLAY_CONTEXT**

`target_load` n'était utilisé que pour alimenter `plan["planned_load"]` — un champ de
métadonnées de rendu. Il n'influence **jamais** :
- distances
- durées
- types de séances
- intensité
- long run
- TSS
- fréquence

La prescription réelle est pilotée exclusivement par `WeeklyTarget V2`
(`build_weekly_target_from_workouts` → `target_km_protected` ou `target_duration_minutes`).

---

## Inputs de determine_target_load

```python
context = {
    "load_7": km_7 * 10,   # volume brut 7j × 10
    "load_28": km_28 * 10, # volume brut 28j × 10
    "ctl": None,
    "atl": None,
    "tsb": None,
    "acwr": None,
    "weekly_km": ...,
}
phase = "build" | "deload" | "intensification" | "taper" | "race"
```

---

## Consumer de target_load

Avant PR158 :
```python
plan["planned_load"] = target_load   # dans generate_cycle_week et _generate_fallback_week_plan
```

`planned_load` n'est pas testé, n'est pas consommé par le frontend comme valeur prescriptive.

---

## Décision de migration

**Migration réalisée.**

Conditions remplies :
- `target_load` = DISPLAY_CONTEXT uniquement
- `planned_load → None` est sémantiquement correct (aucune cible legacy)
- Aucune prescription (distances/durées/types) modifiée
- WeeklyTarget V2 reste autorité

---

## Occurrences avant / après

### Avant PR158

| Occurrence | Fichier | Type |
|---|---|---|
| `def determine_target_load(...)` | `training_engine.py:783` | DEFINITION |
| `"determine_target_load"` | `training_engine.py:914` | DEFINITION (exports list) |
| `from training_engine import determine_target_load` | `server.py:4697` | **RUNTIME_WEEK_PLAN** |
| `target_load = determine_target_load(context, phase)` | `server.py:4698` | **RUNTIME_WEEK_PLAN** |
| tests × 5 | `test_training_metrics_pr127.py` | TEST |
| tests × 3 | `test_pr149_week_plan_v2.py` | TEST |
| test × 1 | `test_dynamic_plan_v2_pr135.py` | TEST |

**RUNTIME_WEEK_PLAN avant = 2 (import + appel)**

### Après PR158

| Occurrence | Fichier | Type |
|---|---|---|
| `def determine_target_load(...)` | `training_engine.py:783` | DEFINITION |
| `"determine_target_load"` | `training_engine.py:914` | DEFINITION (exports list) |
| commentaires PR158 | `server.py` | DOC/COMMENT |
| tests (inchangés) | `test_training_metrics_pr127.py` etc. | TEST |

**RUNTIME_WEEK_PLAN après = 0 ✅**

---

## WeeklyTarget V2 autorité = YES

`build_weekly_target_from_workouts` reste appelé dans `get_week_plan`.
`target_km_protected` et `target_duration_minutes` proviennent exclusivement de `weekly_target`.

---

## Prescription identique = YES

`generate_cycle_week` calcule distances/durées/types depuis :
- `context["target_km_protected"]` → depuis WeeklyTarget V2
- `context["training_state"]` → depuis WeeklyTarget V2
- `context["weekly_km"]` → depuis `compute_current_weekly_km`

Aucun de ces inputs n'est modifié par PR158.

---

## TSS inchangé = YES

- `estimated_tss` sessions actives = `None`
- `estimated_tss` sessions rest = `0`
- `total_tss` = `None`

Identique à baseline post-#156.

---

## Fichiers modifiés

| Fichier | Nature |
|---|---|
| `backend/server.py` | Retrait de l'appel `determine_target_load`, mise à jour signatures |
| `backend/llm_coach.py` | `target_load: int` → `target_load: int = None` (paramètre optionnel) |
| `backend/tests/test_pr158_remove_determine_target_load.py` | **NEW** — tests ciblés PR158 |
| `RUNINDEX_PR158_REPORT.md` | **NEW** — ce rapport |

---

## Changements de signature

### `generate_cycle_week` (llm_coach.py)

Avant :
```python
async def generate_cycle_week(context, phase, target_load: int, goal, user_id, ...)
```

Après :
```python
async def generate_cycle_week(context, phase, goal, user_id="unknown", target_load: int = None, ...)
```

`target_load` déplacé après les paramètres requis et rendu optionnel.
Tous les callers existants utilisent des keyword arguments — aucun impact.

### `_generate_fallback_week_plan` (server.py)

Avant :
```python
def _generate_fallback_week_plan(context, phase, target_load: int, goal, target_km_protected=None)
```

Après :
```python
def _generate_fallback_week_plan(context, phase, goal, target_km_protected=None)
```

---

## Tests

### PR158 (nouveaux)

```
13 passed
```

### Régression

| Suite | Résultat |
|---|---|
| `test_pr158_remove_determine_target_load.py` | 13 passed ✅ |
| `test_pr156_no_unvalidated_tss_generate_cycle_week.py` | 11 passed ✅ |
| `test_pr149_week_plan_v2.py` | 18 passed ✅ |
| `test_pr155_week_plan_no_legacy.py` | **1 error (env)** — `motor` non installé |
| `test_training_metrics_pr127.py` | inclus dans 83 passed ✅ |
| **Total** | **83 passed, 1 error environnemental préexistant** |

**Erreurs environnementales préexistantes (hors scope PR158) :**
- `motor` (MongoDB driver) absent → `test_pr155` ne peut pas importer `server.py`
- Ce n'est pas masqué : reporté ici séparément

---

## Mergeability

**READY ✅**

- Branche repart proprement de copilot/dev (HEAD `de22c78`)
- Aucun commit de #157 repris
- PR mono-objectif : retrait de `determine_target_load` du chemin week-plan
- RUNTIME_WEEK_PLAN = 0 après migration
- Aucune constante/fallback inventé
- Aucune modification de prescription
- WeeklyTarget V2 reste autorité
- TSS conforme à #156
- 13 tests PR158 = 0 failed
- 83 tests régression = 0 failed (1 error env préexistant)
- `mergeable = true`

---

## Dettes restantes hors scope #158

| Dette | Scope |
|---|---|
| Retirer `load_7`/`load_28` du `context` retourné dans la réponse API (utilisés nulle part) | PR future |
| Retirer `determine_target_load` de `training_engine.py` si aucun autre consumer runtime | Audit PR future |
| Installer `motor` dans l'environnement de test CI pour débloquer `test_pr155` | Infra |
