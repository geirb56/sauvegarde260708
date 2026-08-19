# Smoke runtime final post-PR #146 (pré-PR #147)

Date: 2026-08-19 · Mode: **LECTURE SEULE** · Aucun code/test/donnée/plan modifié · Aucune PR.
Compte réel: `da8505ef-…`.

## 1) HEAD & services
- **HEAD** = `93e6501` (contient PR#145 `5c22ac4` + PR#146 `936c966`). #145 MERGED ✓ · #146 MERGED ✓.
- backend RUNNING · garmin-sync-worker RUNNING.

## 2) Imports
- `from config.training_goals import GOAL_CONFIG` → **OK** (5 goals).
- `from training_engine import GOAL_CONFIG` → **ImportError** ✓ (orphelin supprimé par #146).
- `import training_engine` → **OK** ✓ (module toujours fonctionnel pour ses autres helpers).

## 3) Smoke endpoints — 7/7 HTTP 200
| Endpoint | HTTP |
|---|---|
| /training/today | 200 |
| /training/plan | 200 |
| /training/metrics | 200 |
| /run-index | 200 |
| /dashboard | 200 |
| /training/goals | 200 |
| /training/full-cycle | 200 |

## 4) GOAL_CONFIG runtime
- `/training/goals` sert les 5 goals (5K/10K/SEMI/MARATHON/ULTRA) avec cycle_weeks/long_run_ratio/intensity_pct/description.
- Parité vérifiée : valeurs runtime **== `config.training_goals.GOAL_CONFIG`** (égalité exacte sur les 3 champs pour les 5 goals). Source canonique confirmée.
- set-goal non appelé (POST destructif ; validé par inspection dans le rapport POST145 : utilise `GOAL_CONFIG` de config).

## 5) Non-régression daily V2
- `/training/today` (server.py L3655-3700) : `build_recent_training_response` → `build_readiness_decision` → `build_daily_adaptation`.
- **Aucun** `adapt_session_to_readiness` · **aucun** `training_engine` dans DailyAdaptation · **aucun** `fatigue_ratio/fatigue_status/fatigue_physio`. Chemin V2 intact.

## 6) Tests (suites PR132→146)
- test_goal_config_pr145, test_plan_duration_decoupled, test_dynamic_plan_v2_pr135, test_daily_runtime_pr137, test_mongo_garmin_boundary_pr137, test_training_metrics_pr143, test_bug_137_01_date_parsing, test_daily_adaptation_pr133, test_training_response_pr132, test_training_v2_readiness_decision, test_weekly_reconciliation_pr134.
- **passed=327 · failed=1 · skipped=0.**
- Unique failure = `test_plan_duration_decoupled.py::test_adjusted_weeks_is_base_weeks` (assertion fragile connue). Aucune autre failure. Invariants comportementaux du découplage tous verts (test_no_readiness_multiplier, test_no_silent_shrink, test_marathon_*, test_recommended_weeks_independent_of_readiness, test_prep_insufficient_*, test_prep_status_buckets — PASS).

## 7) Vérification du test fragile
- Test (L73) : `assert "adjusted_weeks = base_weeks" in src` (recherche d'une **assignation**).
- Code réel `coach_service.py` : forme **dict** — L678 `"adjusted_weeks": base_weeks`, L851 (chemin principal) `"adjusted_weeks": total_weeks` (= base_weeks/cycle_weeks). Sémantique identique, aucun multiplicateur readiness.
- **TEST_FRAGILE_CONFIRMED = YES** — mismatch purement syntaxique (assignation vs clé de dict), pas une régression fonctionnelle.

---

# VERDICTS

- **POST146_RUNTIME = PASS** — HEAD 93e6501 (#145+#146), imports canoniques OK, ImportError legacy confirmé, smoke 7/7=200, GOAL_CONFIG runtime == config canonique, daily V2 non régressé, 327 tests verts.
- **TEST_FRAGILE_CONFIRMED = YES** — unique failure = assertion d'inspection de source obsolète (attend `adjusted_weeks = base_weeks`, code en forme dict), invariants comportementaux tous verts.
- **PR147_REQUIRED = YES** — pour assouplir/mettre à jour `test_adjusted_weeks_is_base_weeks` (accepter la forme dict ou passer à un check AST/comportemental). Aucune correction de code applicative requise.
