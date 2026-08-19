# RUNINDEX PR160 REPORT

## HEAD départ

```
b5de908  Merge pull request #159 from geirb56/copilot/correction-complete-test-drift-pr153
```

## HEAD #160

Branche : `copilot/fix-week-plan-weekly-km-pr160`

---

## CURRENT_WEEKLY_KM_ROLE_WEEK_PLAN

```
DISPLAY_ONLY
```

`context["weekly_km"]` est transmis au LLM et à `_generate_fallback_week_plan` comme
valeur de contexte observée. `WeeklyTarget V2` reste l'autorité prescriptive via
`target_km_protected`.

---

## Occurrences compute_current_weekly_km avant/après

### Avant PR160

| Fichier | Ligne | Classification |
|---------|-------|----------------|
| `training_engine.py:70` | `def compute_current_weekly_km(...)` | DEFINITION |
| `training_engine.py:889` | export `__all__` | DEFINITION |
| `training_engine.py:219,232` | docstring | DOC |
| `server.py:88` | import | IMPORT |
| `server.py:4460` | `base_weekly_km = compute_current_weekly_km(workouts_28)` | RUNTIME_FULL_CYCLE |
| `server.py:4677` | `"weekly_km": compute_current_weekly_km(workouts_28)` | RUNTIME_WEEK_PLAN |
| `tests/test_current_weekly_km_unification.py` | plusieurs | TEST |
| `tests/test_real_cache_bypass_pr76.py:150` | commentaire | DOC |

### Après PR160

| Fichier | Classification | Statut |
|---------|----------------|--------|
| `server.py:4460` | RUNTIME_FULL_CYCLE | **conservé** (PR161) |
| `server.py` (week-plan) | RUNTIME_WEEK_PLAN | **supprimé** → `km_28_running / 4` |

**RUNTIME_WEEK_PLAN = 0 ✓**
**RUNTIME_FULL_CYCLE = 1 (prochain consumer → PR161)**

---

## Source V2 choisie

`km_28_running` est déjà calculé dans `get_week_plan` (ligne ~4629) :

```python
km_28_running = sum(normalized_distance_km(w) for w in workouts_28 if is_running(w))
```

Formule observée finale :

```python
"weekly_km": km_28_running / 4,
```

Sémantiquement identique à `compute_current_weekly_km` pour historique positif,
sans fallback `DEFAULT_WEEKLY_KM`.

---

## Formule observée finale

```
observed_weekly_km = km_28_running / 4
```

Où `km_28_running = sum(normalized_distance_km(w) for w in workouts_28 if is_running(w))`.

---

## no-history : avant / après

| | Avant (legacy) | Après (PR160) |
|--|----------------|---------------|
| 0 activité running | `20.0` (DEFAULT_WEEKLY_KM) | `0.0` |
| Activités non-running seulement | `20.0` (DEFAULT_WEEKLY_KM) | `0.0` |

---

## WeeklyTarget autorité

**YES** — `WeeklyTarget V2` reste l'unique autorité prescriptive via `target_km_protected`.
`context["weekly_km"]` est une valeur **observée** de contexte, pas une cible.

---

## duration-based sans km inventé

**YES** — Prouvé par :
1. `target_km_protected = None` pour tout état `target_basis == "duration"`.
2. `compute_target_km(0, goal, phase) = 0` (pas de plancher artificiel).
3. `generate_cycle_week` branche duration-based via `training_state` (deep_reprise / partial_reprise) sans consommer `target_km`.

---

## full-cycle consumer restant

**YES** — `base_weekly_km = compute_current_weekly_km(workouts_28)` conservé dans
`/training/full-cycle`. Migration déléguée à **PR161**.

---

## DEFAULT_WEEKLY_KM consumers restants

Après PR160 :

| Fichier | Rôle | Action requise |
|---------|------|----------------|
| `training_engine.py:26` | DEFINITION | conserver |
| `training_engine.py:79` | RUNTIME dans `compute_current_weekly_km` | conserver (utilisé par full-cycle) |
| `server.py:87` | import | conserver (utilisé par llm_coach via context fallback) |
| `server.py:4734` | fallback display `context.get("weekly_km", DEFAULT_WEEKLY_KM)` | jamais atteint (weekly_km toujours set) |
| `server.py:4782` | fallback `_generate_fallback_week_plan` | jamais atteint (weekly_km toujours set) |
| `llm_coach.py:22` | import + `context.get('weekly_km', DEFAULT_WEEKLY_KM)` | jamais atteint (weekly_km set par week-plan) |

**Aucun nouveau consumer ajouté. ✓**

---

## Fichiers modifiés

```
backend/server.py                                    — 1 ligne modifiée (+ commentaire)
backend/tests/test_current_weekly_km_unification.py — test_source_unique_usage_in_plan_paths mis à jour
backend/tests/test_pr160_week_plan_weekly_km.py     — NOUVEAU (20 tests, cas A–E)
RUNINDEX_PR160_REPORT.md                             — NOUVEAU
```

---

## Tests passed/failed/skipped/errors

Environnement partiel (fastapi / dotenv non installés) :

```
tests/test_pr160_week_plan_weekly_km.py           : 20 passed / 0 failed
tests/test_current_weekly_km_unification.py       : 13 passed / 0 failed
tests/test_pr149_week_plan_v2.py                  : 22 passed / 0 failed
tests/test_pr153_fallback_no_unvalidated_tss.py   :  8 passed / 0 failed
───────────────────────────────────────────────────────────────────────
Total clean set                                   : 63 passed / 0 failed
```

Tests avec dépendances manquantes (dotenv / fastapi) : erreurs pré-existantes,
indépendantes de PR160.

---

## Mergeability

**mergeable = true**

- PR mono-objectif ✓
- RUNTIME_WEEK_PLAN compute_current_weekly_km = 0 ✓
- Valeur observée issue de V2 (km_28_running déjà calculé) ✓
- Aucun fallback 20 dans ce chemin ✓
- Historique positif conserve km_28/4 identique au legacy ✓
- Zéro historique produit 0 ✓
- Aucune cible km inventée pour duration-based ✓
- WeeklyTarget V2 reste autorité prescriptive ✓
- full-cycle non modifié ✓
- Aucune autre migration legacy ✓
- Tests pertinents = 0 failed ✓

---

## Dette suivante

**PR161** — Migrer le consumer restant dans `/training/full-cycle` :

```python
# server.py ~4460
base_weekly_km = compute_current_weekly_km(workouts_28)
```

Points d'attention pour PR161 :
- `base_weekly_km` alimente `resolve_chronic_base` et le contexte full-cycle.
- Audit complet de `resolve_chronic_base(workouts_28)` requis avant migration.
- Vérifier si `target_base_km` (ligne 4464) peut aussi être migré en PR161.
- Après PR161 : si `compute_current_weekly_km` n'est plus consommé dans server.py,
  la définition dans `training_engine.py` peut être dépréciée (PR162).
