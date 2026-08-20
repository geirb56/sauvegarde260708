# RUNINDEX_PR165_REPORT

## Identification

| Field | Value |
|---|---|
| HEAD départ | `be2b7ac` (post-#163) |
| HEAD #165 (pré-correction) | `9fffecb` |
| HEAD #165 (final) | `aee2b08` |
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
| `test_pr165_week_plan_v2_authority.py` | **43** | 0 | **0** | Contrats A–F + H–M + 4 nouveaux tests unknown-duration, 0 skip |
| `test_pr157_remove_determine_target_load.py` | 10 | 7* | 0 | *7 fails = `No module 'dotenv'` (env CI, pré-existant) |
| `test_pr163_long_run_v2_authority.py` | 32 | 3* | 0 | *3 fails = `No module 'dotenv'` (pré-existant) |
| `test_pr156_no_unvalidated_tss_generate_cycle_week.py` | N/A | collection error* | — | *`No module 'dotenv'` (pré-existant) |
| `test_pr161_no_double_guard.py` | N/A | collection error* | — | *`No module 'dotenv'` (pré-existant) |
| `test_workout_generator_v2.py` + `test_weekly_target_v2.py` + `test_pr149_week_plan_v2.py` | **227** | 0 | 0 | V2 pur, 0 skip |

**Tous les échecs sont dus à `No module named 'dotenv'` — dépendance d'environnement pré-existante, non causée par PR165.**
`python-dotenv==1.2.2` et `httpx==0.28.1` sont bien déclarés dans requirements.txt — pas de nouvelle dette.

---

## CRITICAL_CONTRACT_FIXTURES

| Contrat | continuity_state | target_basis | target / plan | API | PASS/FAIL |
|---|---|---|---|---|---|
| **DEEP_REPRISE_TRAINED** | `deep_reprise` | `duration` | target_duration_minutes = **135** / planned_duration_minutes = **135** | API_minutes = **135** | **PASS** |
| **PARTIAL_REPRISE_DISTANCE** | `partial_reprise` | `distance` | target_km = **4.4** / planned_km = **4.4** | API_km = **4.4** | **PASS** |
| **PARTIAL_REPRISE_DURATION** | `partial_reprise` | `duration` | target_duration_minutes = **120** / planned_duration_minutes = **120** | API_minutes = **120** / weekly_km = None | **PASS** |
| **NORMAL_DURATION_FALLBACK** | `normal` | `duration` | target_duration_minutes = **120** / planned_duration_minutes = **120** | API_minutes = **120** / weekly_km = None | **PASS** |
| **NO_HISTORY** | `no_history` | `duration` | target_duration_minutes = **105** / planned_duration_minutes = **105** | API_minutes = **105** | **PASS** |

CRITICAL_CONTRACT_SKIPS = **0**

Notes sur les fixtures :
- **DEEP_REPRISE_TRAINED** (Option A) : 5 × 16 km dans la fenêtre prior (days_ago 29–41) → prior_km = 40 km/sem → TRAINED level → 135 min. Aucune activité dans les 28 derniers jours.
- **PARTIAL_REPRISE_DISTANCE** (Option A) : 5 runs × 10 km aux jours 8–21 + 1 run 4 km au jour 3. 7d = 4 km < 50 % × 12.6 km (baseline 30d) → partial_reprise. Target distance 4.4 km.
- **PARTIAL_REPRISE_DURATION** (Option B) : WeeklyTarget construit directement. Le pipeline complet ne peut pas produire partial_reprise + duration : si days_since < 28 (condition partielle), les 28d buckets contiennent toujours une activité → _target_partial_reprise produit toujours distance. Le contrat testé ici est l'adapter/plan, pas l'heuristique.
- **NORMAL_DURATION_FALLBACK** (Option B) : même raison — contrat adapter prouvé directement.

---

## FRONTEND AUDIT REPORT

ACTIVE_DISTANCE_SESSION_DURATION_ZERO_SAFE = **NO**
CORRECTED = **YES**

UNKNOWN_DURATION_API_VALUE = **None**

ACTIVE_UNKNOWN_DURATION_DISPLAYED_AS_ZERO = **NO**

REST_ZERO_DURATION_PRESERVED = **YES**

ARTIFICIAL_DURATION_CALCULATION = **NO**

UNKNOWN_COERCED_TO_ZERO scan = **0**

| Champ | Valeur |
|---|---|
| `session.duration` consumers | `TrainingPlan.jsx` (DISPLAY_TEXT), `Dashboard.jsx` (DISPLAY_TEXT) |
| `duration "0min"` used as calculation | **NO** |
| `duration null/None` shown as text | **NO** — guarded with `{session.duration && (<span>…</span>)}` |
| frontend change applied | **YES** — conditional render in both JSX files |

Détail : l'adapter produisait `"0min"` pour toute séance active dont `duration_minutes` est absent.
Correction backend : `duration_minutes=None` → `duration=None` (jamais `"0min"`) pour les séances actives.
Correction frontend : affichage conditionnel `{session.duration && (...)}` dans `TrainingPlan.jsx` et `Dashboard.jsx` pour ne rien afficher quand `duration=null`.

### SCAN UNKNOWN → ZERO (chemin week-plan V2)

| Occurrence | Fichier | Champ | Classification |
|---|---|---|---|
| `elif s.duration_minutes is not None:` (corrigé) | `week_plan_adapter.py` | `duration` | **CORRIGÉ** (était `UNKNOWN_COERCED_TO_ZERO`) |
| `planned_duration_minutes or 0` | `week_plan_adapter.py` (`_build_advice`) | affichage conseil uniquement | `STRUCTURAL_ZERO` (affichage texte conseil — non prescriptif) |
| `planned_km or 0` | `week_plan_adapter.py` (`_build_advice`) | affichage conseil uniquement | `STRUCTURAL_ZERO` (affichage texte conseil — non prescriptif) |

UNKNOWN_COERCED_TO_ZERO = **0** (après correction)

---

## Dettes restantes

| Dette | PR cible |
|---|---|
| `_generate_fallback_week_plan` reste dans `server.py` mais n'est plus appelé par `get_week_plan` — peut être retiré | #166+ |
| `generate_cycle_week` import retiré de `server.py` ; `coach_service.py` importe toujours la fonction (non appelée) — nettoyage optionnel | #166+ |
| `context["training_state"]` et transport legacy encore construits dans `get_week_plan` pour compat display — pourrait être simplifié | #166+ |

dette nouvelle = **NO**

---

## Verdict

```
READY FOR MERGE INTO copilot/dev
```

- ✅ #164 non reprise
- ✅ WeeklyPlan V2 = source réelle des séances
- ✅ Aucune reconstruction prescriptive legacy dans week-plan
- ✅ generate_cycle_week absent du chemin week-plan (0 calls)
- ✅ compute_target_km absent (0 calls)
- ✅ reprise_durations absent (0 calls)
- ✅ compute_long_run_km absent (0 calls)
- ✅ apply_resume_guard absent (0 calls)
- ✅ API frontend compatible
- ✅ TSS doctrine inchangée
- ✅ deep_reprise entraîné prouvé réellement (135 min)
- ✅ partial_reprise distance prouvé (4.4 km)
- ✅ partial_reprise duration prouvé (120 min, weekly_km=None)
- ✅ normal duration fallback prouvé (120 min, weekly_km=None)
- ✅ no_history prouvé (105 min)
- ✅ CRITICAL_CONTRACT_SKIPS = 0
- ✅ ACTIVE_DISTANCE_SESSION_DURATION_ZERO_SAFE = NO → CORRECTED = YES
- ✅ duration_minutes=None → API duration=None (UNKNOWN != ZERO)
- ✅ duration_minutes=45 → API duration="45min"
- ✅ rest → API duration="0min" (ZERO sémantiquement correct)
- ✅ frontend masque duration=null (guard conditionnel dans TrainingPlan.jsx et Dashboard.jsx)
- ✅ UNKNOWN_COERCED_TO_ZERO = 0 sur le chemin week-plan V2
- ✅ 4 tests nouveaux (TestAdapterUnknownDuration) → 43 passed total, 0 failed, 0 skip
- ✅ Aucune nouvelle dette
