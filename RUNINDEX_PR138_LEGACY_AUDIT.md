# RUNINDEX PR138 — LEGACY CONSUMERS AUDIT + PERFORMANCE EXTRACTION

## Source de vérité

- HEAD `main` de départ (après merge #137) : `a94adc400934f9d4ac60cb34b7ae1410ec8b73c2`
- HEAD PR #138 : `9d11656` (merge `copilot/audit-consumers-legacy`)
- Merge PR #136 : `9c0adcc`
- Merge PR #137 : `a94adc400934f9d4ac60cb34b7ae1410ec8b73c2`
- Document canonique relu : `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`

## Résumé

- Consumers directs `training_engine` trouvés : **10**
  - runtime : **2** (`backend/server.py`, `backend/llm_coach.py`)
  - test-only : **8**
- Aucun import direct trouvé dans `backend/workers/`, `backend/services/` ou `backend/jobs/`.
- `backend/garmin/insights.py` n'importe pas `training_engine`.
- Performance extraite en #138 : `vma_pace`, `vma_pace_range`, estimation legacy VMA/VO2max/paces compatibilité plan via `backend/training_v2/performance.py`.

## Matrice exhaustive des consumers

| Consumer | Legacy symbol | Runtime path | Runtime / test | Rôle réel | Catégorie | Équivalent V2 existant ? | Action #138 | Action #139 | Supprimable #140 ? |
|---|---|---|---|---|---|---|---|---|---|
| `backend/server.py` | `compute_current_weekly_km`, `compute_cycle_dates`, `compute_target_km`, `apply_resume_guard`, `resolve_chronic_base`, `resolve_reprise_plan`, `classify_training_state`, `determine_phase`, `get_phase_description`, `is_running`, `normalized_distance_km`, `GOAL_CONFIG`, `DEFAULT_WEEKLY_KM`, `REPRISE_STABLE_WEEKS` | `/training/full-cycle`, `/training/metrics`, `/training/plan`, `/training/refresh`, aliases `/training-plan`, `/training/dynamic-plan` | runtime | orchestration legacy encore active sur full-cycle + métriques de reprise | D | partiel | garder, retirer imports performance inutiles | migrer consumers runtime restants vers V2 dédiés | non avant preuve zéro consumer runtime |
| `backend/server.py` | `classify_training_state` | `/training/metrics` | runtime | fiabilité `acwr_reliable` via reprise legacy | D | `training_v2.training_state` oui | audit seulement | migrer vers état V2 explicite | non |
| `backend/server.py` | imports `adapt_session_to_readiness`, `vma_pace`, `vma_pace_range` | aucun chemin actif | runtime | imports morts après #137 | E | oui / extrait | supprimés en #138 | n/a | oui |
| `backend/llm_coach.py` | `compute_target_km`, `apply_resume_guard`, `compute_long_run_km`, `build_reprise_week_structure`, `reprise_deep_durations`, `reprise_durations`, `REPRISE_DEEP_SESSION_MINUTES`, `VOLUME_GOAL_CONFIG`, `DEFAULT_WEEKLY_KM` | `generate_cycle_week()` via `/training/plan` et `/training/refresh` | runtime | structure hebdo déterministe legacy + reprise ; LLM seulement pour texte | D | partiel (`WeeklyTarget`/`WorkoutGenerator` existent, reprise helpers non totalement migrés) | audit seulement | migrer génération hebdo restante / reprise compat | non |
| `backend/tests/test_training_engine_pr2.py` | `PHASE_VOLUME_MULTIPLIERS`, `VOLUME_GOAL_CONFIG`, `compute_long_run_km`, `compute_target_km`, `vma_pace` | n/a | test-only | non-régression PR2 volume/long run/VMA | F | n/a | conserver | adapter si module legacy supprimé | oui après migration tests |
| `backend/tests/test_resume_guard_pr76.py` | `apply_resume_guard`, `compute_target_km` | n/a | test-only | non-régression reprise guard | F | n/a | conserver | rebrancher sur couche finale #139/#140 | oui après migration tests |
| `backend/tests/test_cycle_dates.py` | `compute_cycle_dates` | n/a | test-only | caractérisation cycle dates | F | n/a | conserver | déplacer si fonction extraite un jour | oui après migration tests |
| `backend/tests/test_current_weekly_km_unification.py` | `DEFAULT_WEEKLY_KM`, `compute_current_weekly_km`, `compute_target_km`, `is_running`, `normalized_distance_km` | n/a | test-only | invariant volume hebdo legacy | F | n/a | conserver | migrer quand consumers runtime sortis du legacy | oui après migration tests |
| `backend/tests/test_training_metrics_pr127.py` | `determine_target_load`, `adjust_load_by_fatigue` | n/a | test-only | dette historique PR127 | F | partiel | conserver | reclasser/supprimer si plus de runtime target_load legacy | oui probable |
| `backend/tests/test_coach_load_context_pr128.py` | `build_training_context` | n/a | test-only | dette PR128 | F | partiel | conserver | reclasser/supprimer si helper legacy tué | oui probable |
| `backend/tests/test_plan_duration_decoupled.py` | `GOAL_CONFIG` | n/a | test-only | contrat durée du plan | F | n/a | conserver | migrer vers constante finale si extraite | oui |
| `backend/tests/test_run_index_r129_training_today_fallback.py` | `adapt_session_to_readiness` | n/a | test-only | caractérisation fallback legacy `/training/today` retiré du runtime | F | `DailyAdaptation V2` oui | conserver comme preuve de sortie du runtime | décider suppression ou déplacement | oui probable |

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

### `/training/plan` et `/training/refresh`

- Dépendances legacy runtime restantes :
  - `llm_coach.generate_cycle_week()` pour `compute_target_km`, `apply_resume_guard`, `compute_long_run_km`, reprise helpers.
- Couche performance :
  - `coach_service.generate_dynamic_training_plan()` utilise désormais `training_v2.performance.build_legacy_performance_compatibility()`.
- Mélange encore présent : structure/reprise legacy + pipeline V2 runtime.

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
| `reprise_deep_durations` | runtime actif | `llm_coach.py` |
| `resolve_chronic_base` | runtime actif | `server.py` |
| `classify_training_state` | runtime actif | `server.py /training/metrics` |
| `resolve_reprise_plan` | runtime actif | `server.py` |
| `build_reprise_week_structure` | runtime actif | `llm_coach.py` |
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

## Audit frontières Mongo → Training V2

### Frontière canonique attendue

```
db.garmin_activities  →  mongo_garmin_activities_to_domain()  →  DomainActivity  →  Training V2
```

Règle : aucun module Training V2 ne doit recevoir de document Mongo brut.

### Violations identifiées

| Fichier | Ligne | Caller | Données potentiellement perdues | Correction #139 ? |
|---|---|---|---|---|
| `backend/server.py` | ~3787 | `/training/metrics` → `get_training_metrics()` | `build_training_load(garmin_activities, today_date)` reçoit des documents Mongo bruts. `to_domain_activity()` dans `domain_activity.py` lit les champs top-level `"distance"` et `"duration"` (alias) mais pas le sous-document `garmin_activity`. Les champs `average_hr`, `max_hr`, `moderate_intensity_minutes`, `vigorous_intensity_minutes`, `elevation_gain_m` sont perdus. Pour ACWR uniquement `duration_s` compte — alias `"duration"` est présent au top-level → ACWR fonctionne en pratique mais par duck-typing, pas via la frontière canonique. | **OUI** — remplacer par `mongo_garmin_activities_to_domain(garmin_activities)` avant appel à `build_training_load`. |

### Violations non trouvées

- `backend/server.py` lignes 3659 et 3661 : **CONFORME** — `mongo_garmin_activities_to_domain(garmin_activities)` est utilisé correctement avant `build_training_load(domain_activities, today)`.
- `backend/garmin/readiness_adapter.py` : reçoit volontairement des documents Garmin bruts (c'est son rôle d'adaptateur) et les passe à `build_training_load`. Acceptable car c'est la couche d'adaptation intentionnelle.
- `backend/garmin/backfill.py` : lit `garmin_activities` pour reconstruction, pas pour Training V2 direct.
- `backend/coach_service.py` : aucun appel direct à `garmin_activities`.
- `backend/llm_coach.py` : aucun accès Mongo direct.
- `backend/training_v2/*` : aucun import Mongo.

### Champs à risque pour la violation server.py:3787

| Champ DomainActivity | Présent top-level garmin_activities ? | Alias top-level lu par to_domain_activity ? | Perte effective ACWR ? |
|---|---|---|---|
| `activity_type` | oui (`"activity_type"`) | oui | non |
| `start_time` | oui (`"start_time"`) | oui | non |
| `distance_m` | non (top-level = `"distance"`) | oui via `activity.get('distance')` | non |
| `duration_s` | non (top-level = `"duration"`) | oui via `activity.get('duration')` | **non (ACWR ok en pratique)** |
| `average_hr` | non (top-level = `"avg_hr"`, non mappé par `to_domain_activity`) | non | oui (mais pas utilisé par ACWR) |
| `max_hr` | non | non | oui (mais pas utilisé par ACWR) |
| `moderate_intensity_minutes` | non (sous-document uniquement) | non | oui (mais pas utilisé par ACWR) |
| `vigorous_intensity_minutes` | non (sous-document uniquement) | non | oui (mais pas utilisé par ACWR) |
| `elevation_gain_m` | non | non | oui (mais pas utilisé par ACWR) |

**Conclusion** : la violation est réelle mais son impact sur ACWR est nul en pratique (les champs `duration` et `activity_type` sont présents au top-level). La correction reste nécessaire pour garantir la robustesse à long terme et le respect de la frontière canonique.

---

## Audit intégrité des champs Garmin

### Champs clés audités dans mongo_garmin_to_domain (domain_adapter.py)

| Champ DomainActivity | Source sous-document | Alias top-level fallback | Règle None/0 | Statut |
|---|---|---|---|---|
| `distance_m` | `garmin_activity.distance_m` | `doc.distance_m` ou `doc.distance` | `_opt_float_positive` (zéro → None) | ✅ correct |
| `duration_s` | `garmin_activity.duration_s` | `doc.duration_s` ou `doc.duration` | `_opt_float_positive` (zéro → None) | ✅ correct |
| `average_hr` | `garmin_activity.average_hr` | `doc.average_hr` ou `doc.avg_hr` | `_opt_float_positive` (zéro → None) | ✅ correct |
| `max_hr` | `garmin_activity.max_hr` | `doc.max_hr` | `_opt_float_positive` (zéro → None) | ✅ correct |
| `moderate_intensity_minutes` | `garmin_activity.moderate_intensity_minutes` | `doc.moderate_intensity_minutes` | `_domain_intensity_minutes` (négatif → None) | ✅ correct |
| `vigorous_intensity_minutes` | `garmin_activity.vigorous_intensity_minutes` | `doc.vigorous_intensity_minutes` | `_domain_intensity_minutes` (négatif → None) | ✅ correct |
| `elevation_gain_m` | `garmin_activity.elevation_gain` | `doc.elevation_gain_m` ou `doc.elevation_gain` | `_opt_float_any` (zéro valide) | ✅ correct — renommage explicite `elevation_gain` → `elevation_gain_m` |

### Règles None / 0

- `None != 0` : aucun champ absent n'est converti en `0`. ✅
- Champs avec valeur `0` physiologiquement invalide (distance, durée, FC) → `None`. ✅
- `elevation_gain = 0` est valide (plat) → `0.0` conservé via `_opt_float_any`. ✅
- Données réellement absentes du document → `None` dans `DomainActivity`. ✅

### Intégrité VO2max

- VO2max Garmin natif : extrait de `garmin_daily_metrics` via `insights.py` si disponible.
- VO2max dérivé : calculé par `training_v2.performance.compute_vo2max_from_vma(vma)` → `VMA * 3.5`.
- **Les deux provenance ne sont jamais confondues.** La présence de l'un ne masque pas l'autre.
- `None` Garmin VO2max ≠ `0`. La formule dérivée n'est jamais utilisée pour remplacer une valeur Garmin absente.

---

## Migrations exactes prévues pour #139

1. Migrer `/training/full-cycle` hors `training_engine`.
2. Migrer `llm_coach.generate_cycle_week()` hors helpers reprise/volume legacy.
3. Remplacer `/training/metrics` `classify_training_state()` par contrat V2 explicite.
4. Décider le sort de `determine_target_load()` sur `/training/week-plan`.
5. Reclasser ou supprimer les helpers legacy purement test-only une fois les consumers runtime éliminés.

## Checklist obligatoire #140 — kill training_engine.py

| Critère | Description | Statut actuel |
|---|---|---|
| Zéro import runtime | Aucun module runtime n'importe `training_engine` | ❌ `server.py`, `llm_coach.py` importent encore au runtime |
| Zéro caller runtime | Aucun chemin d'exécution runtime n'appelle une fonction de `training_engine` | ❌ `/training/full-cycle`, `/training/metrics`, `/training/plan`, `/training/refresh`, `/training/week-plan` dépendent encore du legacy |
| Zéro endpoint dépendant | Tous les endpoints sont servis par Training V2 ou couches extraites | ❌ Non — voir liste ci-dessus |
| Performance extraite | VMA / VO2max / paces dans un module dédié sans dépendance inverse | ✅ `training_v2/performance.py` — FAIT en #138 |
| Tests nécessaires migrés | Les tests contractuels ont un équivalent V2 ou sont rebranché sur le module final | ❌ Tests legacy encore accrochés à `training_engine` directement |
| Frontend consumers compatibles | Aucun contrat API cassé par le retrait du legacy | ⚠️ Non vérifié — dépend des migrations #139 |
| Smoke runtime passé | Tests d'intégration bout-en-bout sur les endpoints impactés | ❌ À valider après #139 |
| Frontière Mongo corrigée | Violation `server.py:3787` corrigée (`mongo_garmin_activities_to_domain` appliqué) | ❌ Correction prévue #139 |

**Condition obligatoire #140 : TOUS les critères ci-dessus doivent être vrais avant de commencer #140.**

### Candidats suppression lors de #140

- `adapt_session_to_readiness`
- `adjust_load_by_fatigue`
- `build_training_context`
- `compute_week_number`
- `compute_monotony`
- `compute_strain`
- Tests legacy associés uniquement si aucun consumer runtime ne leur correspond encore
