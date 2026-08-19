# Validation runtime post-PR #145 + inventaire legacy pré-#146

Date: 2026-08-19 · Mode: **LECTURE SEULE** · Aucun code/test/Mongo/plan/planning/Garmin/.env modifié · Aucune PR.
Compte réel: `da8505ef-…`.

## 1) État runtime
- **HEAD** = `d985a66` (merge local contenant PR#145 `5c22ac4`). #145 MERGED ✓.
- backend RUNNING · garmin-sync-worker RUNNING.
- `backend/config/training_goals.py` existe (source runtime canonique de GOAL_CONFIG).
- server.py : `from config.training_goals import GOAL_CONFIG` (L102) ✓ · **aucun** `from training_engine import GOAL_CONFIG`.

## 2) Smoke global — 5/5 HTTP 200
today=200 · plan=200 · metrics=200 · run-index=200 · dashboard=200.

## 3) `/training/goals` — HTTP 200
Valeurs (identiques à `config.training_goals.GOAL_CONFIG`) :
| goal | cycle_weeks | long_run_ratio | intensity_pct | description |
|---|---|---|---|---|
| 5K | 6 | 0.25 | 20 | 5 kilometers |
| 10K | 8 | 0.30 | 18 | 10 kilometers |
| SEMI | 12 | 0.35 | 15 | Half-marathon |
| MARATHON | 16 | 0.40 | 12 | Marathon |
| ULTRA | 20 | 0.45 | 10 | Ultra-trail |
→ correspondance exacte avec le module canonique. Source runtime = `config.training_goals`, pas `training_engine`.

## 4) `/training-plan/set-goal` — inspection (NON appelé, DESTRUCTIF)
- POST écrit `goal` dans `training_cycles` (`update_one … upsert=True`, L3488) → **destructif, non appelé** (objectif utilisateur réel préservé).
- Inspection code : utilise `GOAL_CONFIG[goal_upper]` (L3486) importé de `config.training_goals` ✓.

## 5) `/training/full-cycle` — HTTP 200
- goal=`MARATHON` · goal_description=`Marathon` · total_weeks=`16` (=GOAL_CONFIG["MARATHON"]["cycle_weeks"]) · status=active · sessions_per_week=4 · base_weekly_km=11.
- Aucune valeur `NaN` · aucune exception import/config · métadonnées cohérentes. L'extraction GOAL_CONFIG (#145) n'a cassé aucun contrat. (Ce test ne valide PAS la physiologie legacy de full-cycle.)

## 6) Parité GOAL_CONFIG
- `config.training_goals.GOAL_CONFIG` == `training_engine.GOAL_CONFIG` → **égalité exacte = True**.
- **Observation** : `training_engine.py:22` définit encore une **copie dupliquée** de GOAL_CONFIG. Aucun runtime ne l'importe (orpheline). Source canonique = `config.training_goals`.

## 7) Non-régression daily V2
- `/training/today` (L3660-3700) utilise : `build_recent_training_response` → `build_readiness_decision` → `build_daily_adaptation`.
- RecentTrainingResponse toujours actif · **aucun** `adapt_session_to_readiness` · **aucun** `training_engine` dans le chemin DailyAdaptation · aucun `fatigue_ratio/status/physio` · None≠0. Chemin V2 intact (aucune régression #145).

## 8-9) Consumers `training_engine` — server.py
Import réel (L86) — 13 symboles :
`DEFAULT_WEEKLY_KM, compute_current_weekly_km, compute_cycle_dates, compute_target_km, apply_resume_guard, resolve_chronic_base, resolve_reprise_plan, REPRISE_STABLE_WEEKS, compute_week_number, determine_phase, get_phase_description, is_running, normalized_distance_km`.
Import local (L4632) : `determine_target_load`.
- Responsabilité : chemin **cycle-week / full-cycle legacy** (`generate_cycle_week` LLM + fallback), calcul phase/volume/reprise. **Hors chemin daily V2.**
- Équivalents V2 : `determine_phase/get_phase_description` → Periodization V2 ; `compute_target_km/determine_target_load` → WeeklyTarget V2 ; `resolve_reprise_plan/apply_resume_guard` → TrainingState V2 ; `is_running/normalized_distance_km` → DomainActivity/domain_adapter.

## 10) Consumers `training_engine` — llm_coach.py
Import réel (L21) — 10 symboles :
`DEFAULT_WEEKLY_KM, compute_target_km, apply_resume_guard, compute_long_run_km, build_reprise_week_structure, REPRISE_DEEP_SESSION_MINUTES, reprise_deep_durations, reprise_durations, VOLUME_GOAL_CONFIG`.
- Responsabilité : `generate_cycle_week()` — construction de la semaine de cycle (LLM), long-run, structure reprise, durées. Mix calcul physiologique + construction de plan (legacy).
- **Hors chemin daily V2** (le daily/plan runtime utilise WorkoutGenerator V2 / WeeklyTarget V2).

### Autres fichiers runtime
- `training_v2/*` : ne référencent `training_engine` **qu'en commentaires** (matrice de migration), **aucun import réel**.
- Tests uniquement : `test_goal_config_pr145.py` (+ éventuels test_reprise/test_training_plan legacy).

## 11) Audit `determine_target_load`
- **Définition** (`training_engine.py`) : `determine_target_load(context, phase) -> int`.
- **Inputs** : context {ctl, atl, tsb, acwr, load_7, load_28, weekly_km} + phase.
- **Output** : charge cible hebdomadaire (unités TSS/TRIMP) — base = ctl si présent, sinon load_28/4, sinon load_7, sinon weekly_km, sinon 0 ; puis multiplicateur de phase + ajustement fatigue (acwr/tsb). Signaux absents ignorés (pas de substitution).
- **Consumer** : server.py L4633 (`target_load = determine_target_load(context, phase)`), utilisé par `generate_cycle_week(...)` et le fallback `_generate_fallback_week_plan(...)` (chemin full-cycle/cycle-week legacy). Consommé par le LLM de génération de plan.
- **Équivalent TrainingLoad V2 ?** — **NO** :
  - `determine_target_load` est **prescriptif** (combien de charge PRESCRIRE la semaine prochaine, ajusté phase/fatigue).
  - TrainingLoad V2 (`build_training_load`) est **descriptif/observé** (acute/chronic/ACWR = ce que l'athlète A FAIT).
  - Sémantiques différentes. L'équivalent V2 fonctionnel de `determine_target_load` est **WeeklyTarget V2** (`build_weekly_target`/périodisation), qui produit la cible. TrainingLoad V2 n'en fournit que des inputs (base).
  - Réponse explicite : **determine_target_load vs TrainingLoad V2 = NO** (mesurent des choses différentes ; PARTIAL uniquement au sens où TrainingLoad V2 alimente la base).

## 12) Audit `compute_current_weekly_km` (NON modifié)
- **Consumers** : server.py L4460 (`base_weekly_km = compute_current_weekly_km(workouts_28)`) et L4611 (`"weekly_km": compute_current_weekly_km(workouts_28)` dans le context de `determine_target_load`). Tous dans le chemin **full-cycle/cycle-week legacy**. **Hors chemin daily V2.**
- **Pourquoi encore nécessaire** : le chemin full-cycle legacy calcule le volume hebdo courant depuis workouts_28 pour alimenter le context legacy.
- **Équivalent V2** : `TrainingHistory V2` `window_7d.distance_km` (volume observé 7 j). Existe mais sémantique de fenêtre/adaptation à vérifier finement.
- **Risque de migration** : MOYEN-ÉLEVÉ — fonction protégée (ne pas modifier pour régler la logique retour-à-la-course) ; toute substitution doit préserver le comportement exact. À traiter dans une PR dédiée, pas comme cleanup opportuniste.

## 13) Dette long-run / reprise — classement : **NOT OBSERVED** (chemin V2)
- Chemin runtime plan/daily = WorkoutGenerator V2 avec garde-fous explicites : `LONG_RUN_FRACTION=0.35`, `LONG_RUN_MIN_FRACTION=0.20` (plancher), `LONG_RUN_MAX_FRACTION=0.45` (plafond). Le long run est une **fraction bornée (20-45 %) du weekly target**, lequel dérive de la capacité observée (WeeklyTarget V2).
- Conséquence : capacité observée très faible → weekly target faible → long run = fraction bornée de ce faible target → **pas de long run disproportionné** dans le chemin V2.
- Source du floor/ratio : `training_v2/workout_generator.py` (`_compute_long_run_km`, constantes calibration V1).
- Le chemin **full-cycle legacy** (`compute_long_run_km` de training_engine via llm_coach) conserve l'ancienne logique, mais n'est pas le chemin runtime principal (plan/daily V2). → classement global **NOT OBSERVED** dans le runtime V2 ; la logique legacy subsiste uniquement dans full-cycle/cycle-week LLM.

## 14) Tests
- `test_goal_config_pr145.py` + régression PR132/133/135/137/143/144 : **224 passed · 0 failed · 0 skipped**.

## 15/17) Classement des candidats #146
| Candidat | Type | Équivalent V2 | Migration autonome | Risque |
|---|---|---|---|---|
| `GOAL_CONFIG` (copie orpheline dans training_engine.py:22) | constante dupliquée | config.training_goals (déjà canonique) | OUI | **FAIBLE** |
| `VOLUME_GOAL_CONFIG` (training_engine.py:121) | constante | à extraire vers config/ | OUI | FAIBLE |
| `determine_phase`/`get_phase_description` | helper | Periodization V2 | OUI (mapping) | MOYEN |
| `determine_target_load` | prescriptif | WeeklyTarget V2 (≠ TrainingLoad V2) | NON (refonte full-cycle) | ÉLEVÉ |
| `compute_current_weekly_km` (protégé) | observé | TrainingHistory V2 window_7d | NON | MOYEN-ÉLEVÉ |
| `compute_long_run_km`/reprise durations | physiologique | WorkoutGenerator V2 / WeeklyTarget V2 | NON (full-cycle LLM) | ÉLEVÉ |

## 18) Recommandation — scope MINIMAL #146 (UN SEUL)
**#146 = finaliser le single-source-of-truth GOAL_CONFIG : supprimer la copie orpheline `GOAL_CONFIG` de `training_engine.py:22` (aucun consumer runtime) et adapter le test de parité pour asserter que `config.training_goals` est canonique.**
Justification : lowest-risk, poursuite directe et cohérente de #145 (élimine la divergence latente de deux copies), zéro impact runtime (aucun import runtime de `training_engine.GOAL_CONFIG`). Optionnellement étendre à l'extraction de `VOLUME_GOAL_CONFIG` vers `config/` (même pattern, risque faible) si un scope légèrement plus large est souhaité.
**À NE PAS inclure dans #146** : `determine_target_load`, `compute_current_weekly_km`, `compute_long_run_km`/reprise — migration sémantique vers WeeklyTarget/TrainingHistory/WorkoutGenerator V2, risque élevé, PR dédiées.

---

# VERDICTS

- **PR145_RUNTIME = PASS** — config/training_goals.py est la source runtime canonique de GOAL_CONFIG ; endpoints consommateurs (/training/goals, /training/full-cycle, set-goal par inspection) inchangés et cohérents ; smoke 5/5=200 ; parité exacte ; daily V2 non régressé ; 224 tests passent.
- **PRE146_LEGACY_AUDIT = COMPLETE** — inventaire refait sur le HEAD actuel : consumers runtime training_engine limités à server.py (L86 + L4632) et llm_coach.py (L21), tous dans le chemin full-cycle/cycle-week legacy ; training_v2 propre ; determine_target_load ≠ TrainingLoad V2 (NO) ; compute_current_weekly_km protégé (2 consumers legacy) ; dette long-run NOT OBSERVED en V2 ; GOAL_CONFIG orphelin identifié.

## Scope #146 recommandé (unique) : suppression de la copie orpheline `GOAL_CONFIG` dans `training_engine.py` (finalisation du single-source-of-truth), risque faible, zéro impact runtime.
