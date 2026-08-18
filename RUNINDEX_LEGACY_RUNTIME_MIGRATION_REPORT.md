# RUNINDEX LEGACY RUNTIME MIGRATION REPORT — PR #139

## HEAD de départ

- HEAD `main` réel : `9d11656` (Merge pull request #138 from geirb56/copilot/audit-consumers-legacy)
- Document source relu : `RUNINDEX_PR138_LEGACY_AUDIT.md`
- Document roadmap relu : `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`

## Inventaire legacy avant migration (d'après audit PR #138)

| Symbole | Consumer principal | Runtime |
|---|---|---|
| `classify_training_state` | `server.py` `/training/metrics` | ✅ runtime actif |
| `resolve_reprise_plan` | `server.py` `/training/full-cycle`, `/training/week-plan` | ✅ runtime actif |
| `resolve_chronic_base` | `server.py` `/training/full-cycle` | ✅ runtime actif |
| `compute_current_weekly_km` | `server.py` `/training/full-cycle`, `/training/week-plan` | ✅ runtime actif |
| `is_running` | `server.py` `/training/full-cycle`, `/training/week-plan` | ✅ runtime actif |
| `normalized_distance_km` | `server.py` `/training/full-cycle`, `/training/week-plan` | ✅ runtime actif |
| `compute_target_km` | `server.py` `/training/full-cycle` (future weeks), `llm_coach.py` | ✅ runtime actif |
| `apply_resume_guard` | `server.py` `/training/full-cycle` (future weeks), `llm_coach.py` | ✅ runtime actif |
| `compute_long_run_km` | `llm_coach.py` `generate_cycle_week()` | ✅ runtime actif |
| `reprise_durations` | `llm_coach.py` `generate_cycle_week()` | ✅ runtime actif |
| `reprise_deep_durations` | `llm_coach.py` `generate_cycle_week()` (transitif) | ✅ runtime actif |
| `REPRISE_DEEP_SESSION_MINUTES` | `llm_coach.py` import | ✅ runtime actif |
| `build_reprise_week_structure` | `llm_coach.py` import | import mort |
| `VOLUME_GOAL_CONFIG` | `llm_coach.py` session config | session count seulement |
| `DEFAULT_WEEKLY_KM` | `llm_coach.py`, `server.py` fallback | fallback display |
| `determine_target_load` | `server.py` `/training/week-plan` | ✅ runtime actif |
| `REPRISE_STABLE_WEEKS` | `server.py` `/training/full-cycle` | ✅ runtime actif |
| `compute_week_number` | importé, jamais appelé | mort |
| `GOAL_CONFIG` | `server.py` display cycle config | display only — conservé |
| `compute_cycle_dates` | `server.py` calendrier | calendrier only — conservé |
| `determine_phase` | `server.py` display toutes semaines | display only — conservé |
| `get_phase_description` | `server.py` texte de phase | display only — conservé |

---

## Migrations effectuées

### A. `/training/metrics` — `classify_training_state` → V2 TrainingState

**Problème** : `acwr_reliable` était dérivé de `classify_training_state(activities_28)` (legacy), utilisant `db.workouts` (source incorrecte pour la décision de reprise).

**Migration** :
1. Import de `build_training_history`, `build_runner_profile`, `build_training_state` depuis `training_v2`
2. Fetch des activités Garmin (déjà en place pour `build_training_load`)
3. Construction du pipeline V2 : `mongo_garmin_activities_to_domain` → `TrainingHistory` → `RunnerProfile` → `TrainingState`
4. `acwr_reliable = _ts_metrics.continuity_state not in ("deep_reprise", "partial_reprise")`

**Équivalence V2** : `TrainingState.continuity_state` (source canonique)

**Contrat API** : inchangé — champs `acwr_reliable`, `acwr_status`, `acwr_label` identiques

---

### B. `/training/full-cycle` — Pipeline legacy → V2

**Problème** : Semaine courante utilisait `resolve_reprise_plan()` + `resolve_chronic_base()` + `compute_current_weekly_km()` + `is_running()` + `normalized_distance_km()` sur `db.workouts`.

**Migration** :
1. Fetch des activités Garmin via `db.garmin_activities`
2. Pipeline V2 complet : `mongo_garmin_activities_to_domain` → `TrainingHistory` → `TrainingLoad` → `RunnerProfile` → `TrainingState` → `PlanGoal` → `PeriodizationSnapshot` → `WeeklyTarget`
3. `reprise_state = _ts_fc.continuity_state` (V2)
4. `current_target_km_v2 = _weekly_target_fc.target_km` (V2) avec fallback compatibility si WeeklyTarget indisponible

**Équivalences V2 utilisées** :
| Symbole legacy | Équivalent V2 |
|---|---|
| `classify_training_state` / `resolve_reprise_plan` | `TrainingState.continuity_state` |
| `resolve_chronic_base` | `RunnerProfile.typical_weekly_km` |
| `compute_current_weekly_km` | `TrainingHistory.window_30d.distance_km / 4` |
| `is_running` + `normalized_distance_km` | `mongo_garmin_activities_to_domain()` + DomainActivity |
| `reprise["target_km"]` (semaine courante) | `WeeklyTarget.target_km` |
| `reprise["active_weeks"]` | `sum(1 for km in TrainingHistory.weekly_distance_buckets_28d if km > 0)` |
| `REPRISE_STABLE_WEEKS` | `REPRISE_EXIT_STABLE_WEEKS = 4` (training_state.py V2) |

**Champs des semaines futures** (`target_km` des semaines futures) :
- Statut : **compatibility projection**
- Raison : V2 `Periodization` ne fournit pas de planning multi-semaines pour affichage
- Solution : `compute_target_km` + `apply_resume_guard` conservés pour les projections futures (display-only, non-décision runtime de la semaine courante)
- Ces imports restent dans `server.py` avec annotation explicite

**Contrat API** : préservé — tous les champs JSON identiques

---

### C. `/training/week-plan` — Dépréciation (determine_target_load supprimé)

**Audit** : aucun caller frontend trouvé pour `/training/week-plan`. L'endpoint utilise `db.training_goals` (modèle legacy) + `determine_target_load()` + `resolve_reprise_plan()` + `generate_cycle_week()`.

**Décision** : dépréciation propre, redirection vers `generate_dynamic_training_plan(db, user_id)`.

**Raison** : `determine_target_load()` n'a pas d'équivalent V2 direct. La charge cible est exprimée via `WeeklyTarget.target_km` / `target_duration_minutes` dans le pipeline V2. Inventer un `determine_target_load_v2()` introduirait de la dette.

**Migration** :
- L'endpoint retourne désormais la réponse V2 complète de `generate_dynamic_training_plan`
- Flag `deprecated: true` ajouté dans la réponse pour signaler la dépréciation
- `generate_cycle_week` retiré de l'import dans `server.py`
- `determine_target_load` absent de server.py (aucun call AST)

---

### D. `llm_coach.generate_cycle_week()` — Pipeline legacy → V2

**Statut** : `generate_cycle_week()` est désormais **dead code runtime** (aucun endpoint ne l'appelle). Sa migration est effectuée pour satisfaire l'audit et pour rester compatible si un futur appelant l'utilise avec un contexte V2.

**Migrations** :

| Symbole legacy | Remplacement V2 |
|---|---|
| `compute_target_km(...)` | `context["weekly_target_v2"]["target_km"]` ou `target_km_protected` |
| `apply_resume_guard(...)` | **Supprimé** — V2 `WeeklyTarget` applique la garde en amont |
| `compute_long_run_km(target_km, goal)` | `training_v2.workout_generator._compute_long_run_km(target_km, v2_goal_type)` |
| `reprise_durations(prior, active_weeks)` | `weekly_target_v2["target_duration_minutes"]` + `_split_durations()` |
| `reprise_deep_durations`, `REPRISE_DEEP_SESSION_MINUTES` | **Supprimés** (transitifs via reprise_durations) |
| `build_reprise_week_structure` | **Supprimé** (import mort) |
| `DEFAULT_WEEKLY_KM` | Conservé comme constante inline fallback (20 km) |
| `VOLUME_GOAL_CONFIG` | Conservé pour le session count config seulement |

**Imports legacy restants dans llm_coach.py** :
- `DEFAULT_WEEKLY_KM` — fallback display sentinel
- `VOLUME_GOAL_CONFIG` — session count configuration (non-décision training)

---

## Rôle final de generate_cycle_week()

- **Statut runtime** : dead code (aucun endpoint ne l'appelle après PR #139)
- **Rôle si réutilisé** : formatting/texte uniquement, structure déterministe basée sur contexte V2
- **Source volume** : `weekly_target_v2.target_km` (V2) ou `target_km_protected` (garde amont)
- **Source sortie longue** : `training_v2.workout_generator._compute_long_run_km()` (V2)
- **Source reprise** : `weekly_target_v2.target_duration_minutes` + `_split_durations()` (V2)
- **Le LLM ne décide pas** : `generate_cycle_week` est déterministe, le LLM n'est appelé que pour le texte via `_call_gpt()`

---

## Source finale volume

- **Décision semaine courante** : `WeeklyTarget.target_km` (V2, via `/training/plan`)
- **Projection semaines futures** (display) : `compute_target_km` + `apply_resume_guard` (compatibility, annotés)
- **`/training/week-plan`** : redirigé vers `generate_dynamic_training_plan` (V2 WeeklyTarget)

---

## Source finale reprise

- **État de reprise** : `TrainingState.continuity_state` (V2, pipeline `build_training_state`)
- **Structure semaine reprise** : `WeeklyTarget` (durée) + `WorkoutGenerator` (sessions)
- **Doctrines conservées** :
  - `no_history` réel → `no_history` V2
  - historique ancien + arrêt → `deep_reprise` V2
  - `partial_reprise` → contrat V2
  - `reprise_exit` → intensité autorisée mais non forcée
- **TrainingState V2 non modifié**

---

## Source finale sortie longue

- **Source** : `training_v2.workout_generator._compute_long_run_km()` dans `generate_cycle_week`
- **Runtime principal** : `WorkoutGenerator.build_weekly_plan()` via coach_service
- **La formule legacy `compute_long_run_km` n'est pas copiée** dans les consommateurs runtime

---

## Statut performance compatibility

- Module : `backend/training_v2/performance.py`
- Statut : extraction de compatibilité — formules identiques à legacy, isolées des décisions
- Les modules V2 suivants ne l'importent **pas** : `training_state`, `weekly_target`, `weekly_reconciliation`, `workout_generator`, `readiness_decision`, `daily_adaptation`
- Vérifié par tests `test_performance_architecture_pr138.py` et `test_legacy_runtime_migration_pr139.py`

---

## Statut fallback VMA = 12.0

- Conservé dans `training_v2/performance.py` pour les consumers de compatibilité
- **Jamais injecté dans** : `TrainingState`, `WeeklyTarget`, `WeeklyReconciliation`, `WorkoutGenerator`, `ReadinessDecision`, `DailyAdaptation`
- Garde-fou architectural : aucun de ces modules n'importe `performance.py`
- Prouvé par tests statiques `TestVMAFallbackIsolated` (PR #139)

---

## Preuve performance isolée des décisions V2

Recherche exhaustive via AST :
- `training_state.py` : n'importe pas `performance`
- `weekly_target.py` : n'importe pas `performance`, pas de référence VMA/VO2max
- `weekly_reconciliation.py` : n'importe pas `performance`
- `workout_generator.py` : n'importe pas `performance`, pas de référence VMA/VO2max
- `readiness_decision.py` : n'importe pas `performance`
- `daily_adaptation.py` : n'importe pas `performance`

---

## Frontière Mongo → Domain utilisée

- `mongo_garmin_activities_to_domain()` (depuis `garmin.domain_adapter`)
- Utilisée dans `/training/metrics` et `/training/full-cycle` (PR #139)
- Déjà utilisée dans `/training/today`, `/run-index` (PRs précédents)
- **Aucune activité Mongo brute** transmise directement aux couches V2

---

## Inventaire training_engine après migration

| Symbole | Statut après PR #139 | Consumer runtime restant |
|---|---|---|
| `DEFAULT_WEEKLY_KM` | display/fallback | `llm_coach.py` (fallback), `server.py` (fallback) |
| `GOAL_CONFIG` | display config | `server.py` /training/full-cycle description |
| `compute_cycle_dates` | calendrier only | `server.py` /training/full-cycle |
| `compute_target_km` | compatibility projection | `server.py` /training/full-cycle semaines futures |
| `apply_resume_guard` | compatibility projection | `server.py` /training/full-cycle semaines futures |
| `determine_phase` | display text | `server.py` /training/full-cycle |
| `get_phase_description` | display text | `server.py` /training/full-cycle |
| `VOLUME_GOAL_CONFIG` | session count config | `llm_coach.py` (non-décision) |
| `classify_training_state` | **MIGRÉ** | aucun runtime |
| `resolve_reprise_plan` | **MIGRÉ** | aucun runtime |
| `resolve_chronic_base` | **MIGRÉ** | aucun runtime |
| `compute_current_weekly_km` | **MIGRÉ** | aucun runtime |
| `is_running` | **MIGRÉ** | aucun runtime |
| `normalized_distance_km` | **MIGRÉ** | aucun runtime |
| `REPRISE_STABLE_WEEKS` | **MIGRÉ** | aucun runtime |
| `compute_week_number` | mort | aucun |
| `determine_target_load` | **MIGRÉ (dépréciation /week-plan)** | aucun runtime |
| `reprise_durations` | **MIGRÉ** | aucun runtime |
| `reprise_deep_durations` | **MIGRÉ** | aucun runtime |
| `build_reprise_week_structure` | **MIGRÉ** | aucun runtime |
| `REPRISE_DEEP_SESSION_MINUTES` | **MIGRÉ** | aucun runtime |
| `compute_long_run_km` | **MIGRÉ** | aucun runtime |
| `adapt_session_to_readiness` | test-only | `test_run_index_r129_training_today_fallback.py` |
| `adjust_load_by_fatigue` | test-only | `test_training_metrics_pr127.py` |
| `build_training_context` | test-only | `test_coach_load_context_pr128.py` |
| `vma_pace`, `vma_pace_range` | re-export via performance.py | consumers performance compat |

---

## Consumers runtime restants (training_engine)

| Consumer | Symbole | Type | Raison |
|---|---|---|---|
| `server.py` /training/full-cycle | `compute_cycle_dates` | calendrier | pas d'équivalent V2 multi-semaine |
| `server.py` /training/full-cycle | `determine_phase` + `get_phase_description` | display | pas d'équivalent V2 pour toutes les semaines |
| `server.py` /training/full-cycle | `GOAL_CONFIG` | display config | description et cycle_weeks |
| `server.py` /training/full-cycle | `compute_target_km` + `apply_resume_guard` | **compatibility projection** | semaines futures display uniquement, pas semaine courante |
| `server.py` fallback | `DEFAULT_WEEKLY_KM` | fallback display | constante de sécurité |
| `llm_coach.py` | `DEFAULT_WEEKLY_KM`, `VOLUME_GOAL_CONFIG` | session count / fallback | non-décision training |

---

## Blockers éventuels

1. **`compute_target_km` + `apply_resume_guard` pour semaines futures** : Pas d'équivalent V2 pour une projection multi-semaines. La V2 `Periodization` donne la phase courante mais pas un schedule complet par semaine pour l'UI. Migration complète nécessiterait un nouveau V2 multi-week forecast engine.

2. **`compute_cycle_dates`** : Fonction calendrier pure (pas de décision training). Peut être extraite vers un module utilitaire dans un PR ultérieur.

3. **`determine_phase` + `get_phase_description`** : Display text pour le planning multi-semaines. L'équivalent V2 (`build_runtime_phase_info`) couvre la phase courante uniquement.

4. **`generate_cycle_week()` dead code** : La fonction reste dans `llm_coach.py` mais n'est plus appelée au runtime. Suppression possible dans PR #140 si zéro consumer prouvé.

---

## Tests

### Tests de migration (nouveaux)
- `tests/test_legacy_runtime_migration_pr139.py` — 24 tests statiques

### Couverture des tests de migration :
| Test | Assertion |
|---|---|
| A. /training/full-cycle | `resolve_reprise_plan` non appelé, `build_training_state` présent |
| B. /training/metrics | `classify_training_state` non importé, V2 `continuity_state` source |
| C. /training/week-plan | `determine_target_load` non appelé (AST), `generate_dynamic_training_plan` présent |
| D. generate_cycle_week | `compute_target_km` non importé, `weekly_target_v2` source |
| E. generate_cycle_week | `apply_resume_guard` non importé |
| F. generate_cycle_week | `compute_long_run_km` non importé, source V2 workout_generator |
| G. plan runtime | `build_weekly_plan` dans coach_service, `generate_cycle_week` non appelé |
| H. deep_reprise | `allow_intensity=False`, `target_basis=duration` |
| I. reprise_exit | `allow_intensity=True` mais non forcé |
| J. normal | V2 modules n'importent pas training_engine |
| K. performance | 6 modules V2 n'importent pas performance.py |
| L. VMA 12.0 | WeeklyTarget et WorkoutGenerator sans VMA |

---

## Confirmation training_engine.py NON supprimé

✅ `training_engine.py` est intact. Aucune suppression effectuée.

---

## Confirmation aucune formule V2 modifiée

✅ Les modules suivants sont non modifiés :
- `training_v2/training_state.py`
- `training_v2/weekly_target.py`
- `training_v2/weekly_reconciliation.py`
- `training_v2/workout_generator.py`
- `training_v2/readiness_decision.py`
- `training_v2/daily_adaptation.py`
- `training_v2/performance.py`

---

## Verdict

**NOT READY — RUNTIME CONSUMERS REMAIN (display/compatibility)**

Les consumers runtime de **décision** training_engine ont été migrés :
- `classify_training_state` ✅ → V2 TrainingState
- `resolve_reprise_plan` ✅ → V2 TrainingState + WeeklyTarget
- `resolve_chronic_base` ✅ → V2 RunnerProfile
- `compute_current_weekly_km` ✅ → V2 TrainingHistory
- `determine_target_load` ✅ → déprécié (/week-plan redirigé V2)
- `reprise_durations` ✅ → V2 WeeklyTarget duration
- `compute_long_run_km` ✅ → V2 WorkoutGenerator

Consumers restants **non-décision** (display + compatibility projection) :

| Symbole | Type | Condition suppression |
|---|---|---|
| `compute_target_km` (semaines futures display) | compatibility projection | nécessite V2 multi-week forecast engine |
| `apply_resume_guard` (semaines futures display) | compatibility projection | nécessite V2 multi-week forecast engine |
| `compute_cycle_dates` | calendrier | extraction module utilitaire PR #140+ |
| `determine_phase` | display | extraction ou V2 full-schedule PR #140+ |
| `get_phase_description` | display text | idem |
| `GOAL_CONFIG` | config display | migration PR #140+ |
| `DEFAULT_WEEKLY_KM`, `VOLUME_GOAL_CONFIG` | constants non-décision | suppression PR #140 |

**Condition READY FOR LEGACY KILL** :
→ Implémenter un V2 multi-week projection engine dans Periodization/WeeklyTarget
→ Extraire `compute_cycle_dates` en module utilitaire
→ Remplacer `determine_phase` + `get_phase_description` par V2 phase schedule
→ Prouver zéro consumer runtime → PR #140 suppression training_engine.py
