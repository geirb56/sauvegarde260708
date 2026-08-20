# RUNINDEX_PR161_REPORT.md

## PR #161 — Découplage WeeklyTarget V2 / apply_resume_guard legacy dans generate_cycle_week

---

### HEAD départ

```
b5de908  Merge pull request #159 from geirb56/copilot/correction-complete-test-drift-pr153
```

### Confirmation #160 non reprise

`#160` était FERMÉE / NON MERGÉE. La branche PR161 part de `copilot/dev` post-`#159`.  
Aucun commit de `#160` n'est présent dans l'historique.

---

### DOUBLE_GUARD_CONFIRMED = YES

**Avant PR161**, le code dans `generate_cycle_week` était :

```python
target_km = context.get("target_km_protected") or compute_target_km(...)
target_km = apply_resume_guard(target_km, context.get("km_7", ...), current_weekly_km)
```

`apply_resume_guard` était **toujours** appelé, y compris quand `target_km_protected` venait de
WeeklyTarget V2.

---

### Exemple numérique avant / après

| | Valeur |
|---|---|
| `current_weekly_km` | 40 |
| `km_7` | 10 |
| `target_km_protected` V2 | 45 |
| Guard legacy : `recent < chronic × 0.5` → `10 < 20` → cap = `40 × 1.05` | **42** |

| | Avant PR161 | Après PR161 |
|---|---|---|
| V2 propose | 45 | 45 |
| `apply_resume_guard` appelé sur cible V2 | **OUI** | **NON** |
| `compute_target_km` appelé sur cible V2 | **NON** | **NON** |
| `target_km` final entrant dans WorkoutGenerator | **42** ❌ | **45** ✅ |

---

### apply_resume_guard appelé sur cible V2

- **Avant PR161** : OUI (0 → N appels selon paramétrage)
- **Après PR161** : NON (0 appels prouvé par spy test)

### compute_target_km appelé sur cible V2

- **Avant PR161** : NON (logique `or` court-circuitait)
- **Après PR161** : NON (0 appels prouvé par spy test)

---

### Comportement legacy fallback conservé

**YES** — quand `target_km_protected` est absent ou `None`, le chemin legacy
`compute_target_km → apply_resume_guard` est intégralement conservé.  
Prouvé par `test_c_legacy_path_still_called_when_no_v2_target` et
`test_spy_legacy_path_calls_both`.

### Duration-based inchangé

**YES** — les chemins `deep_reprise` et `partial_reprise` (durée) ne sont pas touchés.
PR161 ne modifie que les lignes 289-292 de `llm_coach.py`.  
Prouvé par `test_d_deep_reprise_duration_based` et `test_e_partial_reprise_no_artificial_km`.

### TSS inchangé

**YES** — `active=None`, `rest=0`, `total=None` conservés sur les deux chemins.  
Prouvé par `test_f_tss_non_regression_v2_protected` et `test_f_tss_non_regression_legacy_path`.

---

### Fichiers modifiés

| Fichier | Nature |
|---|---|
| `backend/llm_coach.py` | Fix : branche explicite `is not None` sur `target_km_protected` |
| `backend/tests/test_pr161_no_double_guard.py` | 12 nouveaux tests (régression + cas A–F + spy) |
| `RUNINDEX_PR161_REPORT.md` | Ce rapport |

---

### Diff minimal (llm_coach.py)

```diff
-    # PR76: honour target_km_protected if the resume guard was triggered upstream.
-    target_km = context.get("target_km_protected") or compute_target_km(current_weekly_km, goal, phase)
-    target_km = apply_resume_guard(target_km, context.get("km_7", current_weekly_km), current_weekly_km)
+    # PR161: if WeeklyTarget V2 has already computed and protected a target, use it
+    # as-is — do NOT reprocess through the legacy apply_resume_guard (double guard).
+    # Only the legacy fallback path goes through compute_target_km + apply_resume_guard.
+    protected_target = context.get("target_km_protected")
+    if protected_target is not None:
+        target_km = protected_target
+    else:
+        target_km = compute_target_km(current_weekly_km, goal, phase)
+        target_km = apply_resume_guard(target_km, context.get("km_7", current_weekly_km), current_weekly_km)
```

---

### Tests passed / failed / skipped / errors

**PR161 tests** (12/12 passed, 0 failed, 0 skipped, 0 errors) :

- `test_regression_v2_target_preserved_over_legacy_cap` ✅
- `test_regression_v2_target_km_value` ✅
- `test_a_v2_target_below_legacy_cap_unchanged` ✅
- `test_b_v2_target_above_legacy_cap_unchanged` ✅
- `test_c_legacy_path_still_called_when_no_v2_target` ✅
- `test_c_explicit_none_is_treated_as_absent` ✅
- `test_d_deep_reprise_duration_based` ✅
- `test_e_partial_reprise_no_artificial_km` ✅
- `test_f_tss_non_regression_v2_protected` ✅
- `test_f_tss_non_regression_legacy_path` ✅
- `test_spy_v2_path_zero_guard_zero_compute` ✅
- `test_spy_legacy_path_calls_both` ✅

**Subset PR149→PR161** (pytest tests/test_pr16*.py tests/test_pr15*.py tests/test_weekly_target_v2.py) :
48 passed, 1 pre-existing error (httpx missing — infrastructure, non lié à PR161)

---

### Mergeability

mergeable = **true**  
Pas de conflits. Branch part de `copilot/dev` post-#159.

---

### Scan apply_resume_guard

| Occurrence | Classification |
|---|---|
| `training_engine.py` (définition) | DEFINITION |
| `llm_coach.py` branche `else` (legacy fallback) | RUNTIME_LEGACY_FALLBACK |
| tests/test_pr161_*.py (spy) | TEST |

`RUNTIME_V2_PROTECTED_TARGET = 0` ✅

---

### Dette suivante

- Migrer `compute_current_weekly_km` vers TrainingHistory V2 (hors scope PR161)
- Refactorer entièrement le chemin duration-based (hors scope PR161)
- Supprimer l'import `apply_resume_guard` de `llm_coach.py` une fois le chemin legacy retiré

---

## VERDICT

**READY FOR MERGE INTO copilot/dev**
