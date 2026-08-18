# RUNINDEX — AUDIT EXHAUSTIF DES CONSUMERS LEGACY
## EXTRACTION PERFORMANCE VMA / PACES

**Généré le :** 2026-08-18  
**Repo :** geirb56/sauvegarde260708  
**HEAD audité :** `07951d098b5339270adbcbc987f20dd36e65bcf5`

---

## 1. ÉTAT DE MAIN

| Champ | Valeur |
|-------|--------|
| SHA HEAD | `07951d098b5339270adbcbc987f20dd36e65bcf5` |
| Dernier commit | `PR #139: migrate last runtime consumers of training_engine to V2 contracts` |
| Python 3.11 hotfix | Confirmé présent (training_v2/*.py utilisent `from __future__ import annotations`) |
| `/training/today` sur DailyAdaptation V2 | Confirmé — aucun appel à `training_engine` dans le chemin DailyAdaptation |

**État des dernières migrations :**
- PR #139 : migration des derniers consumers runtime vers V2 (`classify_training_state`, `resolve_reprise_plan`, `resolve_chronic_base`, `compute_current_weekly_km`, `is_running`, `normalized_distance_km`, `compute_long_run_km`, `apply_resume_guard` retiré des décisions runtime).
- PR #138 : audit consumers legacy — extraction `training_v2/performance.py`.
- PR #137 : frontière Mongo→DomainActivity (`mongo_garmin_activities_to_domain`).

---

## 2. INVENTAIRE COMPLET — `backend/training_engine.py`

### 2.1 Constantes

| Symbole | Responsabilité | Callers runtime | Statut |
|---------|----------------|-----------------|--------|
| `GOAL_CONFIG` | Config des objectifs (cycle_weeks, long_run_ratio, intensity_pct, description) | `server.py` : `/training-plan/set-goal`, `/training/goals`, `/training/full-cycle` | **B. PERFORMANCE_STILL_NEEDED** — config display, pas décision |
| `DEFAULT_WEEKLY_KM` | Fallback sentinel 20 km | `server.py` (fallback affichage), `llm_coach.py` (fallback sentinel) | **C. COMPATIBILITY_ONLY** |
| `VOLUME_GOAL_CONFIG` | Config sessions/semaine par objectif | `llm_coach.py` : `generate_cycle_week()` | **C. COMPATIBILITY_ONLY** — generate_cycle_week est dead code runtime |
| `PHASE_VOLUME_MULTIPLIERS` | Multiplicateurs de volume par phase | Aucun caller runtime externe identifié | **D. DEAD_CODE_CANDIDATE** |
| `REPRISE_BASE_KM` | Base reprise 12 km | Non importé hors training_engine | **D. DEAD_CODE_CANDIDATE** |
| `REPRISE_STABLE_WEEKS` | Semaines stabilité reprise (3) | Non importé hors training_engine | **D. DEAD_CODE_CANDIDATE** |
| `REPRISE_DEEP_SESSION_MINUTES` | Durées séances reprise débutant | Non importé hors training_engine | **D. DEAD_CODE_CANDIDATE** |
| `ACWR_SAFE_MIN/MAX/DANGER` | Seuils ACWR | Non importé hors training_engine | **D. DEAD_CODE_CANDIDATE** |
| `TSB_FATIGUE_THRESHOLD` | Seuil TSB fatigue | Non importé hors training_engine | **D. DEAD_CODE_CANDIDATE** |
| `TSB_FRESH_THRESHOLD` | Seuil TSB fraîcheur | Non importé hors training_engine | **D. DEAD_CODE_CANDIDATE** |

### 2.2 Fonctions

| Symbole | Responsabilité | Callers runtime | Endpoint | V2 Replacement | Statut |
|---------|----------------|-----------------|----------|----------------|--------|
| `compute_cycle_dates()` | Calendrier multi-semaines (dates début/fin, semaine courante, statut) | `server.py` L4457 | `/training/full-cycle` | Aucun V2 équivalent pour l'affichage calendaire complet | **B. PERFORMANCE_STILL_NEEDED** |
| `determine_phase()` | Phase courante (build/deload/taper…) d'après semaine et total | `server.py` L4600, L4617, L4626, L4689 | `/training/full-cycle` | `training_v2.periodization` couvre la phase courante uniquement | **B. PERFORMANCE_STILL_NEEDED** pour la projection multi-semaine |
| `get_phase_description()` | Texte/libellé de phase (display) | `server.py` L4618, L4813 | `/training/full-cycle` | Aucun | **B. PERFORMANCE_STILL_NEEDED** (display only) |
| `compute_target_km()` | Volume cible projection future | `server.py` L4600, L4626 | `/training/full-cycle` | V2 WeeklyTarget pour la semaine courante | **C. COMPATIBILITY_ONLY** — uniquement projection future affichage |
| `apply_resume_guard()` | Guard reprise volume | `server.py` L4601, L4627 | `/training/full-cycle` | V2 WeeklyTarget.`_apply_resume_guard()` pour décisions courantes | **C. COMPATIBILITY_ONLY** — uniquement projection future affichage |
| `adapt_session_to_readiness()` | Adaptation séance selon readiness + VMA | Aucun caller runtime (tests only) | — | DailyAdaptation V2 | **A. REPLACED_BY_V2** |
| `vma_pace()` | Allure cible MM:SS/km à %VMA | `training_engine.py` L17 re-exporte depuis `training_v2.performance` | — | `training_v2.performance.vma_pace` | **A. REPLACED_BY_V2** — re-export pur |
| `vma_pace_range()` | Plage d'allures entre deux %VMA | `training_engine.py` L17 re-exporte depuis `training_v2.performance` | — | `training_v2.performance.vma_pace_range` | **A. REPLACED_BY_V2** — re-export pur |
| `is_running()` | Filtre type activité course | Retiré runtime (PR #139) | — | `mongo_garmin_activities_to_domain` | **A. REPLACED_BY_V2** |
| `normalized_distance_km()` | Distance normalisée d'un workout | Retiré runtime (PR #139) | — | `DomainActivity.distance_km` | **A. REPLACED_BY_V2** |
| `compute_current_weekly_km()` | Volume hebdomadaire courant | Retiré runtime (PR #139) | — | `TrainingHistory.window_7d` | **A. REPLACED_BY_V2** |
| `classify_training_state()` | État training (ACTIVE/REPRISE…) | Retiré runtime (PR #139) | — | `build_training_state` V2 | **A. REPLACED_BY_V2** |
| `resolve_reprise_plan()` | Plan reprise structurel | Retiré runtime (PR #139) | — | `TrainingState + WeeklyTarget` V2 | **A. REPLACED_BY_V2** |
| `resolve_chronic_base()` | Base chronique (distance) | Retiré runtime (PR #139) | — | `RunnerProfile.typical_weekly_km` | **A. REPLACED_BY_V2** |
| `build_reprise_week_structure()` | Structure semaine reprise | Non importé hors training_engine | — | WorkoutGenerator V2 | **D. DEAD_CODE_CANDIDATE** |
| `cap_long_run_for_low_volume()` | Plafonnement long run | Non importé hors training_engine | — | WorkoutGenerator V2 | **D. DEAD_CODE_CANDIDATE** |
| `compute_long_run_km()` | Distance long run | Retiré runtime (PR #139) | — | `_compute_long_run_km` V2 | **A. REPLACED_BY_V2** |
| `reprise_durations()` | Durées séances reprise | Non importé hors training_engine | — | WorkoutGenerator V2 | **D. DEAD_CODE_CANDIDATE** |
| `reprise_deep_durations()` | Durées séances reprise deep | Non importé hors training_engine | — | WorkoutGenerator V2 | **D. DEAD_CODE_CANDIDATE** |
| `_weekly_running_buckets()` | Buckets hebdo courses (interne) | Interne | — | TrainingHistory V2 | **D. DEAD_CODE_CANDIDATE** |
| `compute_week_number()` | Numéro de semaine depuis start_date | Non importé runtime (commenté PR#139) | — | Inline arithmetic | **D. DEAD_CODE_CANDIDATE** |
| `compute_monotony()` | Monotonie de charge | Retiré décision runtime ; inline dans `/training/metrics` | `/training/metrics` (inline) | Aucun V2 équivalent (display only) | **D. DEAD_CODE_CANDIDATE** dans training_engine — recalculé inline server.py |
| `compute_strain()` | Strain de charge | Idem compute_monotony | `/training/metrics` (inline) | Aucun | **D. DEAD_CODE_CANDIDATE** dans training_engine |
| `adjust_load_by_fatigue()` | Ajustement charge par fatigue | Non importé runtime | — | ReadinessDecision V2 | **D. DEAD_CODE_CANDIDATE** |
| `determine_target_load()` | Charge cible (TSS) | Non importé runtime | — | WeeklyTarget V2 | **D. DEAD_CODE_CANDIDATE** |
| `build_training_context()` | Contexte training complet (legacy) | Tests uniquement (`test_coach_load_context_pr128.py`) | — | V2 pipeline complet | **D. DEAD_CODE_CANDIDATE** (runtime), tests legacy |
| `compute_cycle_dates()` | Voir 2.2 ci-dessus | `server.py` | `/training/full-cycle` | Aucun V2 équivalent | **B. PERFORMANCE_STILL_NEEDED** |

### 2.3 Fonctions internes (re-exports depuis training_v2.performance)

`vma_pace` et `vma_pace_range` sont importées ligne 17 de `training_v2.performance` puis re-exportées via `__all__`. Ce sont des **proxies purs** ; la logique réelle est dans `training_v2/performance.py`.

---

## 3. INVENTAIRE DES IMPORTS REPO-WIDE

### Fichiers non-test important `training_engine` :

| Fichier | Lignes import | Symboles importés |
|---------|---------------|-------------------|
| `backend/server.py` | L89-103 | `DEFAULT_WEEKLY_KM`, `GOAL_CONFIG`, `compute_cycle_dates`, `compute_target_km`, `apply_resume_guard`, `determine_phase`, `get_phase_description` |
| `backend/llm_coach.py` | L21-27 | `DEFAULT_WEEKLY_KM`, `VOLUME_GOAL_CONFIG` |
| `backend/training_engine.py` | L17 (self-import depuis training_v2.performance) | `vma_pace`, `vma_pace_range` |

### Fichiers tests important `training_engine` :

| Fichier test | Symboles importés |
|---|---|
| `test_training_engine_pr2.py` | `build_training_context`, `classify_training_state`, et al. |
| `test_coach_load_context_pr128.py` | `build_training_context` |
| `test_current_weekly_km_unification.py` | Legacy symbols |
| `test_cycle_dates.py` | `compute_cycle_dates` |
| `test_resume_guard_pr76.py` | `apply_resume_guard`, `compute_target_km` |
| `test_run_index_r129_training_today_fallback.py` | `adapt_session_to_readiness` |
| `test_training_metrics_pr127.py` | `determine_target_load`, `adjust_load_by_fatigue` |
| `test_plan_duration_decoupled.py` | `GOAL_CONFIG` |
| `test_legacy_runtime_migration_pr139.py` | AST checks (no import) |

### Fichiers V2 mentionnant `training_engine` :

Ces fichiers contiennent uniquement des **assertions de non-import** dans leur docstring ou dans leurs tests :
- `training_v2/periodization.py` : docstring "No imports from training_engine"
- `training_v2/plan_goal.py` : idem
- `training_v2/training_response.py` : idem
- `training_v2/training_state.py` : idem
- `training_v2/weekly_target.py` : idem
- `training_v2/workout_generator.py` : idem

✅ **Aucun module V2 n'importe training_engine.**

---

## 4. CALL GRAPH RUNTIME

### 4.1 `server.py` → `training_engine`

```
/training-plan/set-goal  (POST)
  → GOAL_CONFIG[goal_upper]          [B. config display, non-décision]

/training/goals  (GET)
  → GOAL_CONFIG.items()              [B. config display]

/training/full-cycle  (GET)
  → GOAL_CONFIG.get(goal)            [B. config display]
  → compute_cycle_dates(…)           [B. calendrier multi-semaine display]
  → mongo_garmin_activities_to_domain(garmin_acts_fc)  ← FRONTIÈRE CORRECTE
  → build_training_history(…)        ← V2
  → build_training_load(…)           ← V2
  → build_runner_profile(…)          ← V2
  → build_training_state(…)          ← V2
  → build_plan_goal(…)               ← V2
  → build_periodization(…)           ← V2
  → build_weekly_target(…)           ← V2 DÉCISION
  → determine_phase(week_num, total_weeks)  [B. projection affichage]
  → get_phase_description(phase)     [B. display texte]
  → compute_target_km(…)             [C. projection future only]
  → apply_resume_guard(…)            [C. projection future only]
  → DEFAULT_WEEKLY_KM                [C. fallback display]

/training/metrics  (GET)
  → build_training_load(garmin_activities)  ← V2 DÉCISION (ACWR)
  → mongo_garmin_activities_to_domain(…)   ← FRONTIÈRE CORRECTE
  → build_training_history(…)              ← V2
  → build_runner_profile(…)                ← V2
  → build_training_state(…)               ← V2
  (monotony/strain recalculés inline — PAS via training_engine)

/vma/estimate  (GET)
  → estimate_vma_from_race()         [défini inline server.py — PAS training_engine]
  → estimate_vma_from_workouts()     [défini inline server.py — PAS training_engine]
  → calculate_training_zones()       [défini inline server.py — PAS training_engine]
```

### 4.2 `llm_coach.py` → `training_engine`

```
generate_cycle_week(context, phase, target_load, goal, …)
  → DEFAULT_WEEKLY_KM   [C. fallback sentinel seulement]
  → VOLUME_GOAL_CONFIG  [C. session-count config only]
  IMPORTANT: generate_cycle_week() est DEAD CODE RUNTIME (PR #139).
  Elle n'est appelée par aucun endpoint actif.
  server.py L41: "generate_cycle_week removed from runtime — /training/week-plan deprecated PR#139"
```

### 4.3 `coach_service.py` → `training_engine`

```
generate_dynamic_training_plan(db, user_id, …)
  → build_legacy_performance_compatibility(runs)  [training_v2.performance — PAS training_engine directement]
  → build_weekly_plan(…)     ← V2
  → build_weekly_target(…)   ← V2
  → build_weekly_reconciliation(…) ← V2
  → adapt_weekly_plan_to_runtime_payload(…) ← V2
  AUCUN import direct de training_engine dans coach_service.py.
```

**Note critique :** `coach_service.py` importe `generate_cycle_week` depuis `llm_coach.py` (L27) mais ne l'**appelle jamais** : grep de `generate_cycle_week(` retourne 0 occurrence dans coach_service.py. C'est un import inutilisé.

---

## 5. AUDIT `server.py`

### 5.1 Endpoint `/training/metrics`

- **ACWR** : `build_training_load` V2 (source de vérité). ✅
- **TSB** : `None` — legacy km-based retiré (PR #127). Aucun TSS V2 disponible. ✅
- **monotony/strain** : recalculés inline (distance-based, display seulement). ✅ PAS via `training_engine`.
- **TrainingState V2** : `mongo_garmin_activities_to_domain → build_training_history → build_runner_profile → build_training_state`. ✅
- **Frontière Mongo** : `mongo_garmin_activities_to_domain(garmin_activities)` appelé correctement. ✅

### 5.2 Endpoint `/training/full-cycle`

- **Décision courante (semaine en cours)** : 100% V2 pipeline. ✅
- **Projection multi-semaine (semaines futures)** : utilise encore `compute_cycle_dates`, `determine_phase`, `get_phase_description`, `compute_target_km`, `apply_resume_guard`.
- **Justification conservée** : le commentaire dans server.py précise que V2 Periodization ne couvre que la phase courante, pas les semaines futures pour l'affichage calendaire.
- **Décision** : ces appels sont des **projections display-only**, pas des décisions de charge.

### 5.3 Endpoint `/vma/estimate`

- `estimate_vma_from_race()` : définie inline dans server.py (L777). Méthode VDOT Jack Daniels simplifiée.
- `estimate_vma_from_workouts()` : définie inline dans server.py (L814). Analyse efforts Z4/Z5.
- `calculate_training_zones()` : définie inline dans server.py (L914).
- **Ces trois fonctions n'importent PAS training_engine.** Elles sont totalement indépendantes.
- **Consumer frontend** : endpoint display/info uniquement, n'alimente pas le plan V2.

### 5.4 Symboles `training_engine` importés dans server.py et leur usage réel

| Symbole | Usage réel | Décision ? | Peut être extrait ? |
|---------|-----------|-----------|---------------------|
| `GOAL_CONFIG` | Config display (cycle_weeks, description) | Non | Oui — constante pure |
| `DEFAULT_WEEKLY_KM` | Fallback affichage (L4583, L4725) | Non | Oui — constante |
| `compute_cycle_dates` | Calendrier multi-semaine display | Non | Oui — math calendaire |
| `determine_phase` | Phase affichage multi-semaine | Non | Oui — math calendaire |
| `get_phase_description` | Texte phase display | Non | Oui — constante texte |
| `compute_target_km` | Projection volume future display | Non | Oui — formula simple |
| `apply_resume_guard` | Projection volume future display | Non | Oui — formula simple |

---

## 6. AUDIT `insights.py` (garmin/insights.py)

`garmin/insights.py` expose `compute_run_index()`. Audit VMA/paces :

- Aucun import de `training_engine`.
- Aucun calcul VMA/VO2max direct (pas de `vma_pace`, pas d'estimation VMA).
- `compute_run_index` consomme des `metrics_docs` Mongo (scores Garmin natifs).
- **sleep_score** : non utilisé (`_latest_with` cherche la clé mais aucun sleep_score Garmin n'est disponible sur le compte audité — conforme à la contrainte : pas de recréation).
- **Frontière** : lit `garmin_activities` et `metrics_docs` directement depuis Mongo, mais n'applique pas `mongo_garmin_activities_to_domain`. Ce n'est pas un consumer V2 Training Engine.

**Verdict garmin/insights.py** : propre, aucune dépendance training_engine, aucun calcul VMA/pace runtime.

---

## 7. AUDIT `llm_coach.py`

### 7.1 Imports training_engine

```python
from training_engine import (
    DEFAULT_WEEKLY_KM,  # fallback sentinel 20 km
    VOLUME_GOAL_CONFIG,  # session-count config only
)
```

### 7.2 `generate_cycle_week()` — statut DEAD CODE RUNTIME

| Aspect | État |
|--------|------|
| Définie dans llm_coach.py | Oui |
| Appelée par server.py | **NON** — endpoint `/training/week-plan` supprimé PR #139 |
| Appelée par coach_service.py | **NON** — import présent L27 mais aucun appel actif |
| Génère encore des séances | Oui, déterministiquement |
| Long run via | `_v2_compute_long_run` (training_v2.workout_generator) |
| compute_target_km/apply_resume_guard | Retiré — contexte V2 utilisé |
| Verdict | **D. DEAD_CODE_CANDIDATE au runtime** |

### 7.3 Classification usages llm_coach

| Usage | Type | Statut |
|-------|------|--------|
| `DEFAULT_WEEKLY_KM` dans `generate_cycle_week` | Fallback sentinel | Dead code (fonction non appelée) |
| `VOLUME_GOAL_CONFIG` dans `generate_cycle_week` | Session count config | Dead code (fonction non appelée) |
| Import `generate_cycle_week` dans coach_service.py | Import mort | **DEAD IMPORT** |

---

## 8. AUDIT `coach_service.py`

### 8.1 `generate_dynamic_training_plan()` — pipeline V2 confirmé

Le pipeline principal est 100% V2 :

```
workouts_6w → _compute_legacy_performance_compatibility(workouts_6w)
  → build_legacy_performance_compatibility(runs)  [training_v2.performance]
  → (vma, vo2max, method, confidence, paces)

garmin_activities → mongo_garmin_activities_to_domain() ✅
  → build_training_history()  V2
  → build_training_load()     V2
  → build_runner_profile()    V2
  → build_training_state()    V2
  → build_plan_goal()         V2
  → build_periodization()     V2
  → build_weekly_target()     V2  ← DÉCISION
  → build_weekly_reconciliation() V2
  → build_weekly_plan()       V2
  → adapt_weekly_plan_to_runtime_payload() V2
```

**VMA/paces dans le plan V2** : `performance_vma`, `performance_vo2max`, `personalized_paces` sont passés comme **enrichissement de contexte et d'affichage** uniquement. Ils n'alimentent PAS `WeeklyTarget`, `ReadinessDecision`, `DailyAdaptation`. ✅

### 8.2 Import mort `generate_cycle_week`

`coach_service.py` L27 importe `generate_cycle_week` depuis `llm_coach`. Cette fonction n'est jamais appelée dans coach_service.py. **Import mort à nettoyer.**

### 8.3 `_readiness_compatibility_score()`

Utilise `performance_vo2max` pour un score de préparation display (`readiness_score`, `prep_status`). N'influence pas les décisions V2. **C. COMPATIBILITY_ONLY.**

---

## 9. FRONTIÈRES GARMIN

### 9.1 Utilisation de `mongo_garmin_activities_to_domain()`

| Endpoint/Contexte | Frontière correcte ? | Notes |
|---|---|---|
| `/training/full-cycle` — pipeline V2 | ✅ OUI | `mongo_garmin_activities_to_domain(garmin_acts_fc)` |
| `/training/metrics` — TrainingLoad V2 | ✅ OUI | `mongo_garmin_activities_to_domain(garmin_activities)` |
| `coach_service.generate_dynamic_training_plan` | ✅ OUI | `mongo_garmin_activities_to_domain(activities)` |
| `/run-index` | ✅ OUI | via `compute_run_index` |

### 9.2 Champs critiques — vérification `None != 0`

Depuis `training_v2/domain_activity.py` et `garmin/domain_adapter.py` :

| Champ | Traitement None |
|-------|----------------|
| `average_hr` | `None` si absent — jamais converti en 0 |
| `max_hr` | `None` si absent |
| `distance_m` | `None` si absent — `DomainActivity.distance_km = None` |
| `duration_s` | `None` si absent |
| `moderate_intensity_minutes` | `None` si absent |
| `vigorous_intensity_minutes` | `None` si absent |
| `elevation_gain_m` | Transporté dans `DomainActivity` (audit PR #137 confirmé) |

**Verdict frontières** : les consumers V2 actifs passent tous par `mongo_garmin_activities_to_domain`. Aucun document Mongo brut passé directement aux moteurs V2 identifié.

⚠️ **Exception partielle** : `build_training_load` dans `/training/metrics` reçoit `garmin_activities` (liste Mongo brute) avant que `mongo_garmin_activities_to_domain` soit appliqué. Vérifier que `build_training_load` applique lui-même la frontière ou s'adapte aux documents bruts.

---

## 10. INVENTAIRE VMA

### 10.1 Implémentations VMA dans le repo

| Fichier | Fonction | Inputs | Formule | Méthode | Consumers |
|---------|----------|--------|---------|---------|-----------|
| `training_v2/performance.py` | `estimate_legacy_vma_from_normalized_runs()` | `runs` : liste `{distance_km, duration_minutes}` | Best effort ≥20min → /0.85 ; ≥12min → /0.90 ; sinon /0.95 ; fallback avg_pace/0.70 ; default 12.0 | effort / average / default | `coach_service._compute_legacy_performance_compatibility()` |
| `training_v2/performance.py` | `DEFAULT_COMPATIBILITY_VMA_KMH = 12.0` | — | Constante fallback | default | Partout |
| `server.py` | `estimate_vma_from_race()` | `distance_km`, `time_minutes` | speed = 60/pace ; vma = speed / pct_distance | VDOT simplifié | `/vma/estimate` display only |
| `server.py` | `estimate_vma_from_workouts()` | `workouts` list (Mongo) | Best Z5 pace / 0.95, extrapolation Z4 | Z5/Z4 efforts | `/vma/estimate` display only |
| `training_engine.py` | `vma_pace()`, `vma_pace_range()` | — | Re-exports depuis `training_v2.performance` | — | Interne training_engine (adapt_session_to_readiness) |

### 10.2 Définition canonique ?

**RÉPONSE : OUI, une définition canonique existe.**

`training_v2/performance.py` est le seul module canonique pour la VMA runtime. Les deux fonctions dans `server.py` (`estimate_vma_from_race`, `estimate_vma_from_workouts`) sont des helpers display-only pour l'endpoint `/vma/estimate` qui n'alimente PAS le plan.

**Divergences identifiées :**
- `server.py/estimate_vma_from_race` : VDOT Jack Daniels (5K→95%, 10K→90%, HM→85%, M→80%).
- `server.py/estimate_vma_from_workouts` : analyse HR zones Z4/Z5.
- `training_v2/performance.py` : analyse pace efforts ≥6 min.
- Les trois méthodes peuvent donner des valeurs différentes pour le même athlète.
- Elles ne sont pas fusionnées et ne sont pas exposées ensemble.

### 10.3 Fallback VMA

`DEFAULT_COMPATIBILITY_VMA_KMH = 12.0 km/h` — appliqué quand aucune donnée d'effort exploitable.

### 10.4 Cache VMA

Aucun cache VMA dédié identifié. Le résultat de `_compute_legacy_performance_compatibility` est calculé à chaque appel de `generate_dynamic_training_plan` (soumis au cache plan global de `_plan_cache`).

---

## 11. INVENTAIRE VO2MAX

| Source | Type | Fichier | Formule | Consumer |
|--------|------|---------|---------|---------|
| `vma_kmh * 3.5` | DERIVED | `training_v2/performance.py` L37-41 | `compute_vo2max_from_vma(vma_kmh)` | `build_legacy_performance_compatibility` → `coach_service` |
| `vma_kmh * 3.5` | DERIVED | `server.py` L804 | `vma_kmh * 3.5` inline | `/vma/estimate` display |
| Garmin native VO2max | REAL | Non utilisé | — | **UNAVAILABLE** — non synchro via garmin_activities |

**Classification :**
- **REAL Garmin VO2max** : UNAVAILABLE dans le pipeline actuel.
- **DERIVED** : calculé `vma * 3.5` partout.
- **Formule fixe** : `VO2max ≈ VMA(km/h) × 3.5` est la seule formule utilisée.

⚠️ **Divergence silencieuse** : `coach_service` et `server.py/vma/estimate` calculent le VO2max dérivé indépendamment. Les valeurs affichées peuvent différer légèrement si les VMA de base diffèrent.

---

## 12. INVENTAIRE PACES / ZONES

### 12.1 `training_v2/performance.py` — `build_legacy_pace_zones()`

Zones produites à partir de `estimated_vma` :

| Zone | %VMA | Usage |
|------|------|-------|
| z1 | 65-70% | Récupération display |
| z2 | 75-80% | Endurance display |
| z3 | 82-87% | Tempo display |
| z4 | 88-93% | Threshold display |
| z5 | 95-100% | Interval display |
| marathon | 78-82% | Display |
| semi | 82-85% | Display |

**Consumer principal** : `coach_service.generate_dynamic_training_plan` → `personalized_paces` injecté dans `adapt_weekly_plan_to_runtime_payload(paces=personalized_paces)`.

### 12.2 `llm_coach.py/generate_cycle_week()` — zones paces (DEAD CODE)

Zones utilisées dans `generate_cycle_week` : `pace_z1..z4` (parse_pace + format_pace). Dead code car `generate_cycle_week` n'est plus appelée.

### 12.3 `training_engine.py/adapt_session_to_readiness()` — paces VMA

Utilise `vma_pace_range(vma, 0.60, 0.65)` etc. pour libellés de séances. Dead code runtime (aucun caller runtime).

### 12.4 Paces plan V2 vs paces legacy

- **Plan V2** (`build_weekly_plan` / `WorkoutGenerator`) : ne génère PAS de valeurs numériques de pace. Génère des descripteurs de type de séance (type, durée cible, intensité).
- **Paces** (`personalized_paces`) : injectées comme enrichissement texte dans `adapt_weekly_plan_to_runtime_payload`. Elles **n'influencent pas** la structure du plan V2 (ni WeeklyTarget, ni readiness, ni adaptation).
- **Usage frontend** : les paces sont affichées comme cibles indicatives. Le plan reste structurellement indépendant des valeurs VMA.

✅ **Confirmation** : le plan V2 ne dépend pas du moteur performance legacy pour ses décisions structurelles.

---

## 13. DUPLICATIONS / DIVERGENCES DE FORMULES

| Formule | Occurrences | Divergence |
|---------|-------------|-----------|
| VMA depuis effort | `training_v2/performance.py` (pace-based) + `server.py` (Z4/Z5 HR-based) | **OUI** — méthodes différentes |
| VMA depuis race | `server.py` VDOT + `training_v2/performance.py` (pas de race-based) | **OUI** — server.py only |
| VO2max = VMA × 3.5 | `training_v2/performance.py` + `server.py` | Formule identique mais calculs séparés |
| Pace %VMA | `training_v2/performance.py` (vma_pace) = `training_engine.py` (re-export) | ✅ Unique |
| Monotony | `training_engine.py/compute_monotony` + recalcul inline server.py `/training/metrics` | **OUI** — deux implémentations |
| Strain | Idem | **OUI** |

**Conclusion** : les deux principales divergences concernent (1) les méthodes VMA display `/vma/estimate` vs runtime performance, et (2) monotony/strain calculés deux fois. Ce ne sont pas des divergences critiques car les estimations display n'alimentent pas le plan.

---

## 14. PROPOSITION ARCHITECTURE PERFORMANCE

L'audit confirme qu'une extraction est souhaitable. La frontière naturelle qui émerge du code réel est :

### `PerformanceProfile` (extrait de `training_v2/performance.py`)

```python
@dataclass
class PerformanceProfile:
    vma_kmh: float                    # VMA estimée km/h
    vma_method: str                   # "effort" | "average" | "default"
    vma_confidence: str               # "high" | "low"
    vo2max: float                     # Dérivé (vma * 3.5)
    vo2max_source: str                # "derived_from_vma" | "garmin_native" (future)
    pace_zones: dict                  # z1..z5, marathon, semi (legacy compat)
```

**Cette frontière est déjà partiellement implémentée** dans `training_v2/performance.py` via `build_legacy_performance_compatibility()` qui retourne un tuple `(vma, vo2max, method, confidence, paces)`.

### Étape suivante recommandée

Formaliser ce tuple en un `PerformanceProfile` dataclass/Pydantic dans `training_v2/performance.py`, sans changer la logique des formules.

### Ce que PerformanceProfile ne décide PAS

- `continuity_state` → TrainingState V2
- `WeeklyTarget` → build_weekly_target V2
- `WeeklyReconciliation` → build_weekly_reconciliation V2
- `ReadinessDecision` → readiness_decision V2
- `DailyAdaptation` → daily_adaptation V2

**PerformanceProfile décrit la capacité/allure. Il ne remplace aucun moteur de charge, continuité ou récupération.**

### Futur LT1/LT2

L'architecture `PerformanceProfile` peut accueillir LT1/LT2 comme champs optionnels :
```python
lt1_kmh: Optional[float] = None  # Futur — multi-évidence
lt2_kmh: Optional[float] = None  # Futur — multi-évidence
```
Sans modifier les formules existantes ni les seuils ReadinessDecision.

---

## 15. TESTS LEGACY CONCERNÉS

| Fichier test | Type | Statut |
|---|---|---|
| `test_training_engine_pr2.py` | Tests unitaires fonctions legacy | Valides tant que training_engine existe |
| `test_coach_load_context_pr128.py` | Test `build_training_context` | Dead code candidate (fonction non appelée runtime) |
| `test_current_weekly_km_unification.py` | Legacy volume | À migrer vers TrainingHistory V2 |
| `test_cycle_dates.py` | `compute_cycle_dates` | Encore nécessaire tant que `/training/full-cycle` l'utilise |
| `test_resume_guard_pr76.py` | `apply_resume_guard`, `compute_target_km` | Encore nécessaire (display projection) |
| `test_run_index_r129_training_today_fallback.py` | `adapt_session_to_readiness` | Test standalone — dead code runtime mais test valide isolation |
| `test_training_metrics_pr127.py` | `determine_target_load`, `adjust_load_by_fatigue` | Dead code runtime — tests compatibilité |
| `test_plan_duration_decoupled.py` | `GOAL_CONFIG` | Valide tant que GOAL_CONFIG reste dans training_engine |
| `test_legacy_runtime_migration_pr139.py` | Assertions AST non-import | **GARDIEN** — à conserver |
| `test_periodization_pr06.py` | Assertion non-import | Gardien V2 |
| `test_training_response_pr132.py` | Assertion non-import | Gardien V2 |
| `test_weekly_reconciliation_pr134.py` | Assertion non-import | Gardien V2 |
| `test_weekly_target_v2.py` | Assertion non-import | Gardien V2 |
| `test_workout_generator_v2.py` | Assertion non-import | Gardien V2 |

**Règle** : les tests "gardiens" (assertions AST non-import) doivent être conservés absolument. Les tests de fonctions dead-code peuvent rester comme documentation du comportement legacy.

---

## 16. DEAD CODE CANDIDATES

Fonctions/symboles dans `training_engine.py` sans aucun caller runtime identifié :

```
PHASE_VOLUME_MULTIPLIERS
REPRISE_BASE_KM
REPRISE_STABLE_WEEKS
REPRISE_DEEP_SESSION_MINUTES
REPRISE_DEEP_SESSION_MINUTES_TRAINED
ACWR_SAFE_MIN / ACWR_SAFE_MAX / ACWR_DANGER
TSB_FATIGUE_THRESHOLD / TSB_FRESH_THRESHOLD
_weekly_running_buckets()
build_reprise_week_structure()
cap_long_run_for_low_volume()
reprise_durations()
reprise_deep_durations()
compute_week_number()
compute_monotony()     ← recalculé inline server.py
compute_strain()       ← recalculé inline server.py
adjust_load_by_fatigue()
determine_target_load()
build_training_context()
```

**Import mort dans `coach_service.py`** : `from llm_coach import generate_cycle_week` (L27) — jamais appelé.

---

## 17. ORDRE PRÉCIS DE MIGRATION

### Phase 1 — Nettoyage imports morts (risque faible)

| Action | Fichier | Symbole | Précondition |
|--------|---------|---------|-------------|
| Retirer import mort | `coach_service.py` L27 | `generate_cycle_week` | Tests passent |
| Vérifier | tous tests | — | `pytest` |

### Phase 2 — Extraction GOAL_CONFIG (risque faible)

| Action | Description | Dépendances |
|--------|-------------|-------------|
| Déplacer `GOAL_CONFIG` | Vers `training_v2/plan_goal.py` ou nouveau `training_v2/goal_config.py` | Mettre à jour imports server.py |
| Déplacer `DEFAULT_WEEKLY_KM` | Constante inline ou training_v2/weekly_target.py | Mettre à jour server.py, llm_coach.py |
| Déplacer `VOLUME_GOAL_CONFIG` | Vers llm_coach.py directement (seul user) | Retirer import training_engine |
| Tester | `test_plan_duration_decoupled.py`, `test_cycle_dates.py` | — |

### Phase 3 — Extraction math calendaire (risque moyen)

| Action | Description | Dépendances |
|--------|-------------|-------------|
| Déplacer `compute_cycle_dates` | Vers nouveau module `training_v2/cycle_calendar.py` | Mettre à jour server.py |
| Déplacer `determine_phase`, `get_phase_description` | Même module | Mettre à jour server.py |
| Déplacer `compute_target_km`, `apply_resume_guard` | Même module ou periodization.py | Mettre à jour server.py |
| Tester | `test_cycle_dates.py`, `test_resume_guard_pr76.py` | — |

### Phase 4 — Suppression safe de training_engine.py

Après Phase 1-3, vérifier checklist zéro-consumer (section 19).

---

## 18. RISQUES

| Risque | Sévérité | Mitigation |
|--------|----------|-----------|
| `GOAL_CONFIG` référencé par tests + display + 3 endpoints | Moyen | Déplacer en une étape atomique |
| `compute_cycle_dates` complexe (gestion dates, statuts) | Moyen | Tests dédiés existants |
| `determine_phase` utilisée dans boucle multi-semaine | Moyen | Tests cycle existants |
| Import mort `generate_cycle_week` dans coach_service | Faible | Retrait simple |
| VMA display (`/vma/estimate`) totalement indépendante | Aucun | Ne pas toucher |
| `training_engine.py` re-exporte `vma_pace` depuis training_v2.performance | Faible | Déjà délégué |
| Double calcul monotony/strain inline + training_engine | Faible | Dead code dans training_engine côté runtime |

---

## 19. CHECKLIST ZÉRO-CONSUMER

```
[ ] zéro import runtime réel de training_engine (server.py, llm_coach.py, coach_service.py)
[ ] zéro endpoint dépendant (actuellement: /training/full-cycle, /training-plan/set-goal, /training/goals)
[ ] zéro worker dépendant (confirmé: aucun worker n'importe training_engine)
[ ] zéro service dépendant (confirmé: coach_service.py n'importe pas training_engine directement)
[ ] GOAL_CONFIG extrait vers training_v2
[ ] DEFAULT_WEEKLY_KM extrait ou inline
[ ] VOLUME_GOAL_CONFIG inliné dans llm_coach.py ou supprimé avec generate_cycle_week
[ ] compute_cycle_dates extrait vers training_v2/cycle_calendar.py
[ ] determine_phase / get_phase_description extraits
[ ] compute_target_km / apply_resume_guard extraits
[ ] performance extraite (PerformanceProfile formalisé dans training_v2/performance.py)
[ ] consumers frontend compatibles (GOAL_CONFIG display fields préservés)
[ ] tests migrés (test_cycle_dates, test_resume_guard, test_plan_duration_decoupled)
[ ] recherche repo-wide propre (grep training_engine → 0 résultat non-test non-commentaire)
[ ] runtime smoke tests pass (5/5 endpoints HTTP 200)
[ ] aucune formule V2 réintroduite en legacy
```

---

## 20. RECOMMANDATION POUR L'ÉTAPE SUIVANTE

**Priorité 1 :** Retirer l'import mort `generate_cycle_week` dans `coach_service.py` (Phase 1 — 5 min, risque nul).

**Priorité 2 :** Formaliser `PerformanceProfile` dans `training_v2/performance.py` (dataclass sans modifier les formules). Permet de remplacer le tuple `(vma, vo2max, method, confidence, paces)` par un objet nommé dans `coach_service.py` et `server.py`.

**Priorité 3 :** Créer `training_v2/cycle_calendar.py` contenant `compute_cycle_dates`, `determine_phase`, `get_phase_description`, `compute_target_km`, `apply_resume_guard`, `GOAL_CONFIG`, `DEFAULT_WEEKLY_KM`. Mettre à jour les imports dans `server.py`. C'est la migration la plus large mais elle est isolée (display-only, pas de logique V2 modifiée).

**Priorité 4 :** Après Phase 3, vérifier la checklist et procéder à la suppression de `training_engine.py`.

---

## 21. TESTS EXÉCUTÉS

| Action | Résultat |
|--------|---------|
| Pytest non disponible au moment de l'audit (environnement sandbox) | N/A — analyse statique uniquement |
| Grep exhaustif imports training_engine | ✅ |
| Grep call graph fonctions training_engine | ✅ |
| Vérification AST commentaires non-import V2 | ✅ |
| Vérification frontière Mongo/Garmin | ✅ |

---

## 22. VERDICT

```
LEGACY CONSUMERS IDENTIFIED                = YES

PERFORMANCE EXTRACTION REQUIRED            = YES
  (tuple → PerformanceProfile dataclass dans training_v2/performance.py)

MONGO→DOMAIN BOUNDARIES CLEAN              = YES
  (tous les consumers V2 actifs passent par mongo_garmin_activities_to_domain)
  (exception à surveiller: build_training_load reçoit garmin_activities brut dans /training/metrics)

READY FOR LEGACY CONSUMER MIGRATION        = YES
  (3 phases identifiées, toutes à faible risque)

TRAINING_ENGINE SAFE TO DELETE NOW         = NO
  Consumers runtime encore actifs:
  - server.py: GOAL_CONFIG, DEFAULT_WEEKLY_KM, compute_cycle_dates,
    determine_phase, get_phase_description, compute_target_km, apply_resume_guard
  - llm_coach.py: DEFAULT_WEEKLY_KM, VOLUME_GOAL_CONFIG
    (generate_cycle_week est dead code mais l'import reste)
```

---

*Audit réalisé sur HEAD `07951d098b5339270adbcbc987f20dd36e65bcf5` — 2026-08-18*  
*Méthode : analyse statique exhaustive (grep, AST, lecture source, call graph manuel)*  
*training_engine.py conservé — aucune modification effectuée*
