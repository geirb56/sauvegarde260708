# RUNINDEX — PR #162 REPORT

## Baseline
- HEAD départ: `aaaa914`
- HEAD #162 (après changements): tip courant de la branche PR162
- PR #160 reprise: **NO** (aucune trace `#160`/`PR160` dans `git log --all`)

## Micro-audit (avant code)
- Occurrences `compute_current_weekly_km` (classification):
  - **DEFINITION**: `backend/training_engine.py` (fonction conservée)
  - **RUNTIME_WEEK_PLAN (avant)**: `backend/server.py` (`"weekly_km": compute_current_weekly_km(workouts_28)`)
  - **RUNTIME_FULL_CYCLE**: `backend/server.py` (`base_weekly_km = compute_current_weekly_km(workouts_28)`) 
  - **TEST**: `backend/tests/test_current_weekly_km_unification.py` + nouveaux tests PR162
  - **DOC/REPORT**: fichiers `RUNINDEX_*.md`, `CURRENT_WEEKLY_KM_PR_REPORT.md`, etc.
- Consumers `context["weekly_km"]` dans `generate_cycle_week`:
  - lecture `current_weekly_km = context.get('weekly_km', DEFAULT_WEEKLY_KM)`
  - si `target_km_protected is not None` ⇒ `target_km = protected_target` (pas de recompute legacy)
  - sinon seulement: `compute_target_km(...)` puis `apply_resume_guard(...)`

**Conclusion audit:**
`WEEK_PLAN_WEEKLY_KM_ROLE_POST_161 = LEGACY_COMPAT_NON_AUTHORITATIVE` ✅

## Changement implémenté (mono-objectif)
Fichier modifié runtime:
- `backend/server.py` (route `GET /api/training/week-plan` uniquement)

Remplacement:
- Avant: `context["weekly_km"] = compute_current_weekly_km(workouts_28)`
- Après: `context["weekly_km"] = km_28_running / 4.0`

Aucun changement sur:
- `/training/full-cycle`
- `training_engine.py` definition `compute_current_weekly_km`
- `compute_long_run_km`
- `compute_target_km`
- `apply_resume_guard`
- WeeklyTarget V2 internals

## Formules
- **Avant (week-plan via helper legacy)**:
  - si `km_28_running > 0` ⇒ `km_28_running / 4`
  - sinon ⇒ `DEFAULT_WEEKLY_KM = 20`
- **Après (week-plan)**:
  - `observed_weekly_km = km_28_running / 4.0`

## Validation sémantique
- Historique running positif:
  - avant = `km_28_running/4`
  - après = `km_28_running/4`
  - **identique** ✅
- No-history / 0 running:
  - avant = `20`
  - après = `0.0`
  - **volontaire** ✅
- Non-running uniquement:
  - après = `0.0` ✅

## Protection prescriptive
- Distance V2 + `weekly_km=0` + `target_km_protected=X`:
  - `target_km final == X` ✅
  - `compute_target_km` appels = 0 ✅
  - `apply_resume_guard` appels = 0 ✅
- Duration/reprise + `weekly_km=0`:
  - prescription durée valide (reprise) ✅
  - pas de baseline km fictive injectée ✅

## Doctrine TSS
- active sessions: `estimated_tss=None`
- rest sessions: `estimated_tss=0`
- `total_tss=None`

**TSS inchangé: YES** ✅

## Scan après
- `compute_current_weekly_km`:
  - `RUNTIME_WEEK_PLAN = 0` ✅
  - `RUNTIME_FULL_CYCLE = 1` (`backend/server.py:4460`) ✅
  - définition conservée ✅
- `DEFAULT_WEEKLY_KM` consumers restants (code runtime):
  - `backend/llm_coach.py` fallback lecture context
  - `backend/server.py` debug/fallback context access
  - `backend/training_engine.py` constante + fallback helper legacy
- Aucun nouveau consumer de `DEFAULT_WEEKLY_KM` introduit ✅

## Tests exécutés
Commande:
- `python -m pytest -q` sur:
  - `tests/test_pr162_week_plan_observed_weekly_km.py`
  - `tests/test_pr161_no_double_guard.py`
  - `tests/test_pr157_remove_determine_target_load.py`
  - `tests/test_pr156_no_unvalidated_tss_generate_cycle_week.py`
  - `tests/test_pr153_fallback_no_unvalidated_tss.py`
  - `tests/test_pr149_week_plan_v2.py`
  - `tests/test_pr155_week_plan_no_legacy.py`
  - `tests/test_weekly_target_v2.py`
  - `tests/test_training_history_pr05.py`
  - `tests/test_current_weekly_km_unification.py`

Résultat:
- **passed: 221**
- **failed: 0**
- **errors: 0**
- warnings: 12

## Fichiers modifiés
- `backend/server.py`
- `backend/tests/test_pr162_week_plan_observed_weekly_km.py`
- `backend/tests/test_current_weekly_km_unification.py`
- `RUNINDEX_PR162_REPORT.md`

## Mergeability
- PR GitHub #162 non trouvée (404), donc mergeability GitHub non interrogable directement.
- Branche locale propre, tests ciblés/régression demandée: 0 failed.
- **mergeability (local gate): true**.

## Dette suivante exacte
- Retirer le consumer runtime restant `compute_current_weekly_km` de `/training/full-cycle` (hors scope PR162), puis envisager suppression import/usage legacy associés.
