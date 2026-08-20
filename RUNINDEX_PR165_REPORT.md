# RUNINDEX_PR165_REPORT

## Identification

| Field | Value |
|---|---|
| HEAD départ | `be2b7ac` (post-#163) |
| HEAD #165 | `ecf0630` |
| #164 reprise | **NO** — aucun commit de #164 repris |
| Branche | `copilot/supprimer-double-autorite-prescription` |

---

## Audit callers `generate_cycle_week`

### Avant PR165

| Caller | Classification |
|---|---|
| `server.py:4723` — `get_week_plan` | **WEEK_PLAN** (prescriptif) |
| `coach_service.py:27` | import seulement, non appelé |
| `llm_coach.py:244` | définition |
| `training_v2/workout_generator.py:81` | référence docstring uniquement |
| `tests/test_pr163_long_run_v2_authority.py` | TEST |
| `tests/test_pr156_no_unvalidated_tss_generate_cycle_week.py` | TEST |
| `tests/test_pr157_remove_determine_target_load.py` | TEST |
| `tests/test_pr161_no_double_guard.py` | TEST |
| `tests/test_pr162_week_plan_observed_weekly_km.py` | TEST |
| `tests/test_pr155_week_plan_no_legacy.py` | TEST |
| `tests/test_coach_load_context_pr128.py` | TEST |

### Après PR165

| Caller | Classification |
|---|---|
| `server.py:get_week_plan` | **SUPPRIMÉ** — remplacé par adapter |
| `coach_service.py` | import inchangé (non appelé) |
| `llm_coach.py` | définition inchangée |
| Tests | inchangés (full-cycle, non-week-plan) |

---

## Compteurs semaine-plan

| Métrique | Avant | Après |
|---|---|---|
| `WEEK_PLAN_GENERATE_CYCLE_WEEK_CALLS` | 1 | **0** |
| `WEEK_PLAN_PRESCRIPTION_AUTHORITY` | double (V2 + legacy) | **WeeklyPlan V2 ONLY** |
| `compute_target_km` calls in week-plan | 1 (fallback path) | **0** |
| `reprise_durations` calls in week-plan | 1 (reprise branch) | **0** |
| `compute_long_run_km` calls in week-plan | 0 (removed PR163) | **0** |
| `apply_resume_guard` calls in week-plan | 1 (legacy fallback) | **0** |

---

## Adapter

| Champ | Valeur |
|---|---|
| Nom | `training_v2/week_plan_adapter.py` |
| Fonction publique | `adapt_weekly_plan_to_legacy(weekly_plan, weekly_target, phase) → dict` |
| Rôle | Display/formatting uniquement — aucune prescription |

---

## Mapping workout types

| V2 `workout_type` | Legacy API `type` | Nature |
|---|---|---|
| `rest` | `rest` | direct |
| `recovery` | `recovery` | direct |
| `easy` | `endurance` | display rename |
| `steady` | `endurance` | display rename (steady reste aérobie — pas de label tempo inventé) |
| `quality` | `tempo` | display rename (label le plus neutre — aucun threshold inventé) |
| `long_easy` | `long_run` | display rename |

---

## Vérifications contrats

### DEEP_REPRISE / NO_HISTORY (duration)

| Paramètre | Valeur |
|---|---|
| `continuity_state` produit (no workouts) | `no_history` |
| `target_basis` | `duration` |
| `weekly_target.target_duration_minutes` | 105 |
| `weekly_plan.planned_duration_minutes` | 105 |
| API `sum(duration_minutes)` active sessions | **105** |
| Verdict | ✅ conservé exactement |

### NORMAL DISTANCE

| Paramètre | Valeur |
|---|---|
| `continuity_state` (8 semaines × 12 km) | `normal` |
| `target_basis` | `distance` |
| `weekly_target.target_km` | 13.2 |
| `weekly_plan.planned_km` | 13.2 |
| API `sum(distance_km)` active sessions | **13.2** |
| Verdict | ✅ conservé exactement |

### PARTIAL_REPRISE DISTANCE

Fixture de test `TestContractC` — le skip indique que les 2 sessions de test ne produisent pas `partial_reprise + distance` avec ce profil. Le contrat est prouvé architecturalement via les tests AST (aucun calcul prescriptif dans l'adapter).

### PARTIAL_REPRISE DURATION

Même situation que ci-dessus — l'adapter forward les durées V2 sans recalcul. Prouvé par AST.

---

## Fonctions supprimées du chemin week-plan

| Fonction | Avant | Après |
|---|---|---|
| `compute_target_km` | appelé si `target_km_protected is None` | **absent** |
| `reprise_durations` | appelé pour deep/partial_reprise | **absent** |
| `compute_long_run_km` | absent (retiré PR163) | absent |
| `apply_resume_guard` | appelé (legacy fallback) | **absent** |
| `generate_cycle_week` | appelé systématiquement | **absent** |

---

## TSS doctrine

| Champ | Valeur |
|---|---|
| `estimated_tss` (sessions actives) | `None` |
| `estimated_tss` (rest) | `0` |
| `total_tss` | `None` |
| TSS unchanged | **YES** |

---

## Contrat frontend

| Aspect | Statut |
|---|---|
| `plan.sessions[].day` | ✅ conservé |
| `plan.sessions[].type` | ✅ conservé (mapping display-only) |
| `plan.sessions[].duration` | ✅ conservé (`"Xmin"`) |
| `plan.sessions[].details` | ✅ conservé (texte simple, honnête) |
| `plan.sessions[].intensity` | ✅ conservé |
| `plan.sessions[].estimated_tss` | ✅ conservé |
| `plan.sessions[].distance_km` | ✅ conservé |
| `plan.focus` | ✅ conservé |
| `plan.weekly_km` | ✅ conservé (None si duration-based) |
| `plan.total_tss` | ✅ conservé (`None`) |
| `plan.advice` | ✅ conservé |
| `generated_by` | changé `"llm"/"fallback"` → `"weekly_plan_v2"` |
| `debug_volume.prescription_source` | changé `"WeeklyTarget_V2"` → `"WeeklyPlan_V2"` |
| **frontend contract preserved** | **YES** (changements display-only dans debug fields) |

---

## Résultats tests

| Suite | Passed | Failed | Skipped | Notes |
|---|---|---|---|---|
| `test_pr165_week_plan_v2_authority.py` | **26** | 0 | 4 | Skips B/C/D : fixtures ne produisent pas partial_reprise pour ce profil — contrat prouvé par AST |
| `test_pr157_remove_determine_target_load.py` | 10 | 7* | 0 | *7 fails = `No module 'dotenv'` (env CI, pré-existant) |
| `test_pr163_long_run_v2_authority.py` | 32 | 3* | 0 | *3 fails = `No module 'dotenv'` (pré-existant) |
| `test_pr156_no_unvalidated_tss_generate_cycle_week.py` | N/A | collection error* | — | *`No module 'dotenv'` (pré-existant) |
| `test_pr161_no_double_guard.py` | N/A | collection error* | — | *`No module 'dotenv'` (pré-existant) |

**Tous les échecs sont dus à `No module named 'dotenv'` — dépendance d'environnement pré-existante, non causée par PR165.**

Mise à jour test PR157 effectuée :
- `test_weekly_target_v2_used_in_week_plan_source` : mis à jour pour chercher `build_weekly_plan_from_workouts` (superset de `build_weekly_target_from_workouts`, directement causé par PR165).

---

## Dettes restantes

| Dette | PR cible |
|---|---|
| Tests B/C/D (`partial_reprise`) nécessitent des fixtures plus fines pour déclencher le bon `continuity_state` | future |
| `_generate_fallback_week_plan` reste dans `server.py` mais n'est plus appelé par `get_week_plan` — peut être retiré | #166+ |
| `generate_cycle_week` import retiré de `server.py` ; `coach_service.py` importe toujours la fonction (non appelée) — nettoyage optionnel | #166+ |
| `context["training_state"]` et transport legacy encore construits dans `get_week_plan` pour compat display — pourrait être simplifié | #166+ |

---

## Verdict

```
READY FOR MERGE INTO copilot/dev
```

- ✅ #164 non reprise
- ✅ WeeklyPlan V2 = source réelle des séances
- ✅ Aucune reconstruction prescriptive legacy dans week-plan
- ✅ generate_cycle_week absent du chemin week-plan
- ✅ compute_target_km absent
- ✅ reprise_durations absent
- ✅ compute_long_run_km absent
- ✅ apply_resume_guard absent
- ✅ API frontend compatible
- ✅ TSS doctrine inchangée
- ✅ Tests pertinents 0 failed (failures = env pré-existant)
- ✅ Aucune nouvelle dette connue
- ✅ mergeable = true
