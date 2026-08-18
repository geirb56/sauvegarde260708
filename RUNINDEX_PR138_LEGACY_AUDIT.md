# RUNINDEX PR138 — LEGACY CONSUMERS AUDIT + PERFORMANCE EXTRACTION

## Source de vérité

- HEAD `main` réel : `a94adc400934f9d4ac60cb34b7ae1410ec8b73c2`
- Merge PR #136 : `9c0adcc`
- Merge PR #137 : `a94adc400934f9d4ac60cb34b7ae1410ec8b73c2`
- Document canonique relu : `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`

## Résumé

- Fichiers qui importent directement `training_engine` trouvés : **10**
  - runtime : **2** (`backend/server.py`, `backend/llm_coach.py`)
  - test-only : **8**
- Aucun import direct trouvé dans `backend/workers/`, `backend/services/` ou `backend/jobs/`.
- `backend/garmin/insights.py` n'importe pas `training_engine`.
- Performance extraite en #138 : `vma_pace`, `vma_pace_range`, estimation legacy VMA/VO2max/paces compatibilité plan via `backend/training_v2/performance.py`.
- Aucune dépendance runtime **D — PERFORMANCE** ne pointe encore vers `training_engine.py` après extraction ; les consumers runtime restants relèvent de **E — TRAINING DECISION LEGACY**.

## Matrice exhaustive des consumers

| Consumer | Legacy symbol | Runtime path | Runtime / test | Rôle réel | Catégorie | Équivalent V2 existant ? | Action #138 | Action #139 | Supprimable #140 ? |
|---|---|---|---|---|---|---|---|---|---|
| `backend/server.py` | `compute_current_weekly_km`, `compute_cycle_dates`, `compute_target_km`, `apply_resume_guard`, `resolve_chronic_base`, `resolve_reprise_plan`, `determine_phase`, `get_phase_description`, `is_running`, `normalized_distance_km`, `GOAL_CONFIG`, `DEFAULT_WEEKLY_KM`, `REPRISE_STABLE_WEEKS`, `determine_target_load` | `/training/full-cycle`, `/training/week-plan`, `/training/goals`, `/training-plan/set-goal` | runtime | orchestration legacy encore active sur cycle complet, goal config et génération hebdo legacy | E | partiel | garder | migrer consumers runtime restants vers V2 dédiés | non avant preuve zéro consumer runtime |
| `backend/server.py` | `classify_training_state` | `/training/metrics` | runtime | fiabilité `acwr_reliable` via reprise legacy | E | `training_v2.training_state` oui | audit seulement | migrer vers état V2 explicite | non |
| `backend/server.py` | `compute_week_number` | aucun chemin actif | runtime | import direct non appelé ; dépendance morte | A | n/a | laisser inchangé en #138 | supprimer avec le reliquat legacy en #139/#140 | oui |
| `backend/server.py` | imports `adapt_session_to_readiness`, `vma_pace`, `vma_pace_range` | aucun chemin actif | runtime | imports morts après #137 | A | oui / extrait | supprimés en #138 | n/a | oui |
| `backend/llm_coach.py` | `DEFAULT_WEEKLY_KM`, `VOLUME_GOAL_CONFIG`, `compute_target_km`, `apply_resume_guard`, `compute_long_run_km`, `reprise_durations` | `generate_cycle_week()` via `/training/week-plan` | runtime | structure hebdo déterministe legacy + reprise ; LLM seulement pour texte | E | partiel (`WeeklyTarget`/`WorkoutGenerator` existent, reprise helpers non totalement migrés) | audit seulement | migrer génération hebdo restante / reprise compat | non |
| `backend/llm_coach.py` | `build_reprise_week_structure`, `REPRISE_DEEP_SESSION_MINUTES`, `reprise_deep_durations` | aucun chemin actif | runtime | imports directs non appelés dans `generate_cycle_week()` | A | n/a | laisser inchangé en #138 | supprimer avec le reliquat legacy en #139/#140 | oui |
| `backend/tests/test_training_engine_pr2.py` | `PHASE_VOLUME_MULTIPLIERS`, `VOLUME_GOAL_CONFIG`, `compute_long_run_km`, `compute_target_km`, `vma_pace` | n/a | test-only | non-régression PR2 volume/long run/VMA | B | n/a | conserver | adapter si module legacy supprimé | oui après migration tests |
| `backend/tests/test_resume_guard_pr76.py` | `apply_resume_guard`, `compute_target_km` | n/a | test-only | non-régression reprise guard | B | n/a | conserver | rebrancher sur couche finale #139/#140 | oui après migration tests |
| `backend/tests/test_cycle_dates.py` | `compute_cycle_dates` | n/a | test-only | caractérisation cycle dates | B | n/a | conserver | déplacer si fonction extraite un jour | oui après migration tests |
| `backend/tests/test_current_weekly_km_unification.py` | `DEFAULT_WEEKLY_KM`, `compute_current_weekly_km`, `compute_target_km`, `is_running`, `normalized_distance_km` | n/a | test-only | invariant volume hebdo legacy | B | n/a | conserver | migrer quand consumers runtime sortis du legacy | oui après migration tests |
| `backend/tests/test_training_metrics_pr127.py` | `determine_target_load`, `adjust_load_by_fatigue` | n/a | test-only | dette historique PR127 | B | partiel | conserver | reclasser/supprimer si plus de runtime target_load legacy | oui probable |
| `backend/tests/test_coach_load_context_pr128.py` | `build_training_context` | n/a | test-only | dette PR128 | B | partiel | conserver | reclasser/supprimer si helper legacy tué | oui probable |
| `backend/tests/test_plan_duration_decoupled.py` | `GOAL_CONFIG` | n/a | test-only | contrat durée du plan | B | n/a | conserver | migrer vers constante finale si extraite | oui |
| `backend/tests/test_run_index_r129_training_today_fallback.py` | `adapt_session_to_readiness` | n/a | test-only | caractérisation fallback legacy `/training/today` retiré du runtime | B | `DailyAdaptation V2` oui | conserver comme preuve de sortie du runtime | décider suppression ou déplacement | oui probable |

## Audit endpoints demandés

### `/training/metrics`

- Dépendance legacy réelle restante : **`classify_training_state()` seulement**.
- Valeurs performance (`vma`, `vo2max`, `paces`) : **aucune**.
- Valeurs charge/physio legacy : `acwr_reliable` dépend encore de la classification reprise legacy ; `tsb` déjà `None`.
- Équivalent V2 : oui pour l'état (`training_v2.training_state`), mais pas encore branché ici.
- Contrat API inchangé en #138.

### `/training/today`

- Statut après #137 : **migré V2**.
- Chemin actif : `generate_dynamic_training_plan()` → `WorkoutPrescription` → `ReadinessResult` → `ReadinessDecision` → `DailyAdaptation`.
- `adapt_session_to_readiness` n'est **plus utilisé** dans le runtime ; seul un test legacy subsiste.

### `/training/plan`, `/training/refresh`, `/training-plan`, `/training/dynamic-plan`

- **Aucune dépendance runtime directe à `training_engine`** sur ce chemin après #135/#138.
- Call graph réel :
  - `server.py::{get_training_plan_v2, refresh_training_plan, get_training_plan, get_dynamic_training_plan_legacy}`
  - → `coach_service.generate_dynamic_training_plan()`
  - → `training_v2.performance.build_legacy_performance_compatibility()`
- Couche performance :
  - estimation compatibilité VMA/VO2max/paces via `training_v2.performance`
  - aucune décision weekly target / training state / daily adaptation relue depuis `training_engine`

### `/training/week-plan`

- Dépendances legacy runtime restantes :
  - `server.py::get_week_plan()` → `determine_phase()`, `determine_target_load()`, `compute_current_weekly_km()`, `resolve_reprise_plan()`
  - → `llm_coach.generate_cycle_week()` → `compute_target_km()`, `apply_resume_guard()`, `compute_long_run_km()`, `reprise_durations()`
- C'est le second vrai chemin runtime legacy avec `/training/full-cycle`.

### `/run-index`

- Aucune dépendance directe à `training_engine`.
- Source : `backend/garmin/insights.py::compute_run_index()`.
- `sleep_score` dans le payload `metrics` est un **score/pénalité interne** dérivé du sommeil, pas un vrai Garmin sleep score synthétique.

### `/dashboard`

- Pas de dépendance directe `training_engine` trouvée.
- `backend/services/dashboard_service.py` s'appuie sur `garmin.insights.compute_run_index()`.

### Autre route réelle concernée : `/training/full-cycle`

- Plus gros consumer runtime legacy.
- Regroupe calendrier, phase, reprise, volume hebdo, descriptions de phase.
- PR cible : **#139**.

## Boundary data `garmin_activities`

- `/training/today` respecte la frontière canonique :
  - `db.garmin_activities`
  - → `mongo_garmin_activities_to_domain()`
  - → `build_training_load()` / `build_readiness_v2_from_garmin_data()`
- `/training/metrics` **bypasse encore** cette frontière :
  - `db.garmin_activities`
  - → `build_training_load(raw mongo docs, today_date)`
- Impact #138 :
  - observation documentée uniquement ;
  - pas de migration massive en #138 ;
  - correction ciblée reportée à **#139**.

## Audit `insights.py`

- Aucun import `training_engine`.
- Couche actuelle : calcul RunIndex / readiness / training load via Garmin + V2.
- `sleep_score_raw` = valeur Garmin si disponible ; `metrics.sleep_score` = pénalité interne, à ne pas confondre avec un Garmin sleep score.
- Aucune nouvelle décision training legacy issue de `training_engine`.

## Audit `llm_coach.py`

- `generate_cycle_week()` génère la **structure déterministe** hebdomadaire ; le LLM ne génère que le texte.
- Dépendances legacy restantes : volume cible, reprise, long run, zones/allures injectées par contexte.
- Rôle actuel du LLM : **formatting / texte**, pas source de structure.
- Migration restante #139 : découpler la structure legacy encore portée par `llm_coach.py`.

## Performance compatibility extraite en #138

- Nouveau module : `backend/training_v2/performance.py`
- Ancien module → nouveau module :
  - `training_engine.vma_pace` → `training_v2.performance.vma_pace`
  - `training_engine.vma_pace_range` → `training_v2.performance.vma_pace_range`
  - `coach_service._compute_legacy_performance_compatibility` → wrapper vers `training_v2.performance.build_legacy_performance_compatibility`
- Fonctions extraites :
  - `vma_pace()`
  - `vma_pace_range()`
  - `estimate_legacy_vma_from_normalized_runs()`
  - `compute_vo2max_from_vma()`
  - `build_legacy_pace_zones()`
  - `build_legacy_performance_compatibility()`

### Formules préservées à l’identique

- VMA effort :
  - effort ≥ 20 min → `speed / 0.85`
  - effort ≥ 12 min → `speed / 0.90`
  - effort ≥ 6 min → `speed / 0.95`
- Fallback VMA sans effort rapide :
  - `avg_speed / 0.70`
- VO2max :
  - `VMA * 3.5`
- Paces :
  - `pace_min_per_km = 60 / (VMA * pct)`

### Inputs / unités / hypothèses

- `distance_km` : kilomètres
- `duration_minutes` : minutes
- `vma_kmh` : km/h
- `pct` : fraction de VMA
- Hypothèse legacy conservée :
  - seules les allures réalistes `3 < pace < 10 min/km` sont retenues
  - effort VMA si `duration >= 6` et `pace < 5.5`
- Donnée absente :
  - `None` est ignoré
  - aucun `None -> 0` inventé
  - si aucun échantillon valide : VMA par défaut legacy = `12.0`

## Preuve d’équivalence #138

- Tests ajoutés :
  - `backend/tests/test_performance_extraction_pr138.py`
  - `backend/tests/test_performance_architecture_pr138.py`
- Couverture :
  - VMA legacy == nouveau module sur cas effort, fallback moyenne, entrées partielles, liste vide
  - VO2max legacy == nouveau module (`VMA * 3.5`)
  - paces legacy == nouveau module (`vma_pace`, `vma_pace_range`, zones)
  - garde-fou architecture : `TrainingState`, `WeeklyTarget`, `WeeklyReconciliation`, `ReadinessDecision`, `DailyAdaptation` n’importent pas `performance.py`

## TRAINING_ENGINE REMAINING INVENTORY

| Symbole restant dans `training_engine.py` | Statut | Consumer actuel |
|---|---|---|
| `is_running` | runtime actif | `server.py`, tests |
| `normalized_distance_km` | runtime actif | `server.py`, tests |
| `compute_current_weekly_km` | runtime actif | `server.py`, tests |
| `compute_target_km` | runtime actif | `server.py`, `llm_coach.py`, tests |
| `apply_resume_guard` | runtime actif | `server.py`, `llm_coach.py`, tests |
| `reprise_durations` | runtime actif | `llm_coach.py` |
| `reprise_deep_durations` | export legacy non consommé runtime | aucun consumer direct runtime |
| `resolve_chronic_base` | runtime actif | `server.py` |
| `classify_training_state` | runtime actif | `server.py /training/metrics` |
| `resolve_reprise_plan` | runtime actif | `server.py` |
| `build_reprise_week_structure` | export legacy non consommé runtime | aucun consumer direct runtime |
| `REPRISE_DEEP_SESSION_MINUTES` | export legacy non consommé runtime | aucun consumer direct runtime |
| `cap_long_run_for_low_volume` | helper interne/test legacy | indirect via `compute_long_run_km` |
| `compute_long_run_km` | runtime actif | `llm_coach.py`, tests |
| `adapt_session_to_readiness` | test-only | `test_run_index_r129_training_today_fallback.py` |
| `compute_cycle_dates` | runtime actif | `server.py`, tests |
| `compute_week_number` | export legacy non consommé runtime | aucun consumer direct runtime |
| `compute_monotony` | export legacy non consommé runtime | aucun consumer direct runtime |
| `compute_strain` | export legacy non consommé runtime | aucun consumer direct runtime |
| `determine_phase` | runtime actif | `server.py` |
| `get_phase_description` | runtime actif | `server.py` |
| `adjust_load_by_fatigue` | test-only | `test_training_metrics_pr127.py` |
| `determine_target_load` | runtime actif legacy | `server.py /training/week-plan` |
| `build_training_context` | test-only | `test_coach_load_context_pr128.py` |
| `vma_pace`, `vma_pace_range` | **performance extraite** ; re-export legacy | appelés via import depuis `training_v2.performance` |

## Migrations exactes prévues pour #139

1. Migrer `/training/full-cycle` hors `training_engine`.
2. Migrer `llm_coach.generate_cycle_week()` hors helpers reprise/volume legacy.
3. Remplacer `/training/metrics` `classify_training_state()` par contrat V2 explicite.
4. Décider le sort de `determine_target_load()` sur `/training/week-plan`.
5. Corriger `/training/metrics` pour passer par `mongo_garmin_activities_to_domain()`.
6. Reclasser ou supprimer les helpers legacy purement test-only une fois les consumers runtime éliminés.

## Candidats suppression #140

- `adapt_session_to_readiness`
- `adjust_load_by_fatigue`
- `build_training_context`
- `compute_week_number`
- `compute_monotony`
- `compute_strain`
- tests legacy associés

**Condition obligatoire #140 : zéro consumer runtime prouvé avant suppression de `training_engine.py`.**
