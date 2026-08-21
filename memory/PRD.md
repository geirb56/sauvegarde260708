# RunIndex — Project Setup Record

## Problem Statement
Pull https://github.com/geirb56/sauvegarde260629 and set it up so it runs. Replace /app contents.

## 2026-08-19 — Pull copilot/dev (PR #165) — WeeklyPlan V2 = autorité UNIQUE du week-plan — MERGÉ, runtime OK, test-drift résiduel
- Fetch copilot/dev (be2b7ac→81eaa2d). Merge ORT propre, 0 conflit. .env intacts. Backend+worker+FRONTEND redémarrés.
- PR #165 = suppression de la double autorité de prescription: WeeklyPlan V2 (nouveau training_v2/week_plan_adapter.py) devient la SOURCE UNIQUE de /training/week-plan (generate_cycle_week retiré du chemin week-plan) + "durée inconnue → None (pas 0min)" (UNKNOWN != ZERO) + fix test_pr157 + changements frontend (Dashboard.jsx, TrainingPlan.jsx).
- Validation RUNTIME: smoke 7/7=200 (incl. week-plan + full-cycle). test_pr157 désormais VERT (corrigé par #165). 208 tests passed.
- ⚠️ TEST-DRIFT résiduel (NON runtime) introduit/laissé par PR165:
  1. test_pr155::test_happy_path + test_no_legacy_training_goals_access → ERROR setup: patch('server.generate_cycle_week') échoue car PR165 a retiré generate_cycle_week du chemin week-plan (AttributeError). Tests obsolètes (le week-plan est désormais V2-only, plus de generate_cycle_week).
  2. test_pr156::test_distances_and_types_preserved → assert distance_km>0 obsolète (inspecte l'ancien chemin generate_cycle_week).
  Runtime OK (smoke 7/7=200). Correctifs recommandés (PR future): réécrire/retirer test_pr155 (plus de generate_cycle_week dans week-plan) et assouplir test_pr156. NON corrigés (workflow: fixes via PRs utilisateur).
- État: migration full-cycle/cycle-week V2 aboutie côté week-plan (autorité unique WeeklyPlan V2). Frontend Dashboard/TrainingPlan mis à jour (à valider visuellement).


## 2026-08-19 — Pull copilot/dev (PR #163) — compute_long_run_km retiré (WorkoutGenerator V2 autorité long_easy) — MERGÉ, runtime OK, 2 test-drifts
- Fetch copilot/dev (068454f→be2b7ac). Merge ORT propre, 0 conflit. .env intacts. Backend+worker redémarrés.
- PR #163 = suppression de compute_long_run_km de generate_cycle_week (WorkoutGenerator V2 = autorité long_easy, long_run_km_v2 passé via context; None si duration-based, aucun km inventé) + déduplication pipeline week_plan_bridge (_build_weekly_context_from_workouts, appel renommé build_weekly_plan_from_workouts). Dernier gros helper legacy du cycle-week migré.
- Validation RUNTIME: compute_long_run_km plus appelé dans generate_cycle_week (commentaire seulement). Smoke 7/7=200.
- ⚠️ 2 TEST-DRIFTS introduits par PR163 (NON runtime): 
  1. test_pr156::test_distances_and_types_preserved: assert distance_km>0 sur séances actives, mais PR163 met distance=0/None (long_run_km_v2=None) sur semaines duration-based (pas de km inventé) → assert 0>0 échoue. Assertion obsolète.
  2. test_pr157::test_weekly_target_v2_used_in_week_plan_source: cherche littéral 'build_weekly_target_from_workouts', or PR163 a renommé l'appel en 'build_weekly_plan_from_workouts'. Inspection source obsolète.
  Runtime OK. Correctifs recommandés (PR future): (1) autoriser distance_km>=0/None sur actives duration-based; (2) mettre à jour le nom recherché → build_weekly_plan_from_workouts (ou check AST). NON corrigés (workflow: fixes via PRs utilisateur).
- Autres suites: 196 passed. Migration full-cycle/cycle-week V2 quasi complète (#157/#161/#162/#163). training_engine garde encore des helpers phase/reprise/cycle-dates.


## 2026-08-19 — Pull copilot/dev (PR #162) — week-plan utilise le weekly_km OBSERVÉ — MERGÉ & VALIDÉ
- Fetch copilot/dev (aaaa914→068454f). Merge ORT propre, 0 conflit. .env intacts. Backend+worker redémarrés.
- PR #162 = utilisation du weekly_km observé (volume réel) dans le chemin week-plan (server.py 2 lignes) + tests focalisés (test_pr162_week_plan_observed_weekly_km.py, test_current_weekly_km_unification.py). Avance la migration/unification de compute_current_weekly_km.
- Validation: smoke 7/7=200. Tests PR162 + régression = 178 passed, 0 failed.
- État: chaîne Training Engine V2 stable, suite verte. Migration full-cycle/cycle-week: double-guard résolu (#161), weekly_km observé unifié (#162). Reste: compute_long_run_km.


## 2026-08-19 — Pull copilot/dev (PR #161) — WeeklyTarget V2 découplé de apply_resume_guard dans generate_cycle_week — MERGÉ & VALIDÉ
- Fetch copilot/dev (b5de908→aaaa914). Merge ORT propre, 0 conflit. .env intacts. Backend+worker redémarrés.
- PR #161 = découplage de WeeklyTarget V2 du legacy apply_resume_guard dans generate_cycle_week (llm_coach.py, évite un double resume-guard). + test_pr161_no_double_guard.py (469 lignes).
- Validation: smoke 7/7=200 (today/plan/metrics/run-index/dashboard/week-plan/full-cycle). Tests PR161 + régression = 226 passed, 0 failed.
- État: chaîne Training Engine V2 stable, suite verte. Migration full-cycle/cycle-week en cours (double-guard résolu #161). Reste: compute_current_weekly_km, compute_long_run_km.


## 2026-08-19 — Pull copilot/dev (PR #159) — Fix test-drift PR153 (appels _generate_fallback_week_plan) — MERGÉ & VALIDÉ
- Fetch copilot/dev (e631d0c→b5de908). Merge ORT propre, 0 conflit. .env intacts. Aucun code applicatif (uniquement test_pr153 + rapport drift scan).
- PR #159 = mise à jour des appels _generate_fallback_week_plan dans test_pr153 (retrait de l'arg target_load obsolète, 5 args → 4) pour aligner sur la signature post-PR157. + PR159 drift scan report.
- Validation: régression complète 16 suites (PR132→159) = 387 passed, 0 failed. Le test-drift PR157 (test_pr155 via #158 + test_pr153 via #159) est ENTIÈREMENT RÉSOLU. Smoke 4/4=200.
- État: chaîne Training Engine V2 stable, suite ENTIÈREMENT VERTE, sémantique None uniforme sur tous les chemins week-plan, determine_target_load retiré du week-plan. Reste (migration future): compute_current_weekly_km, compute_long_run_km (cycle-week legacy).


## 2026-08-19 — Pull copilot/dev (PR #158) — Fix mock test_pr155 — MERGÉ, mais test-drift PR157 INCOMPLET (10 tests PR153 rouges)
- Fetch copilot/dev (51cc287→e631d0c). Merge ORT propre, 0 conflit. .env intacts. Aucun code applicatif (uniquement test_pr155).
- PR #158 = alignement du mock generate_cycle_week de test_pr155_week_plan_no_legacy.py sur la signature post-PR157. Les 2 tests PR155 précédemment rouges PASSENT désormais ✓.
- ⚠️ MAIS: 10 tests de test_pr153_fallback_no_unvalidated_tss.py ÉCHOUENT (TypeError: _generate_fallback_week_plan() takes from 3 to 4 positional arguments but 5 were given). Cause: PR157 a AUSSI retiré target_load de la signature de _generate_fallback_week_plan (nouvelle: (context, phase, goal, target_km_protected=None)), mais test_pr153 appelle encore avec 5 args incluant l'ancien target_load (ex: _generate_fallback_week_plan(ctx, phase, 100, "10k", 40.0)). PR157 a cassé test_pr155 ET test_pr153; PR158 n'a corrigé QUE test_pr155.
- Runtime INTACT: smoke today/week-plan/dashboard = 200. Fallback interne cohérent (endpoint appelle avec la bonne signature). Régression uniquement dans les tests (test-drift).
- Correctif recommandé (PR future): mettre à jour les appels de test_pr153 pour retirer l'arg target_load → _generate_fallback_week_plan(ctx, phase, "10k", 40.0). NON corrigé (workflow: fixes via PRs utilisateur).
- NOTE: ma validation PR157 précédente n'incluait pas test_pr153 dans le set exécuté, d'où la détection tardive.


## 2026-08-19 — Pull copilot/dev (PR #157) — determine_target_load retiré du chemin week-plan — MERGÉ & VALIDÉ RUNTIME (2 tests PR155 cassés par test-drift)
- Fetch copilot/dev (de22c78→51cc287). Merge ORT propre, 0 conflit. .env intacts. Backend+worker redémarrés.
- PR #157 (renommé de #158) = suppression de determine_target_load du chemin /training/week-plan (contexte d'affichage uniquement). server.py L4710 n'appelle plus generate_cycle_week avec target_load; llm_coach generate_cycle_week garde target_load: int = None (kwarg optionnel, affichage).
- Validation RUNTIME: aucun import/appel réel determine_target_load restant. Smoke 7/7=200 (incl. week-plan + full-cycle). 
- ⚠️ RÉGRESSION DE TEST introduite par PR157 (NON runtime): test_pr155_week_plan_no_legacy.py::test_happy_path et ::test_no_legacy_training_goals_access ÉCHOUENT. Cause: le MOCK _inner(context, phase, target_load, goal, user_id) (L129) exige target_load en positionnel requis, mais l'appel réel (PR157) ne le passe plus → TypeError. Test-drift: PR157 aurait dû mettre à jour ce mock. Runtime OK (week-plan=200). Correctif recommandé (PR future): rendre target_load optionnel dans le mock (_inner(context, phase, goal, user_id, target_load=None)). NON corrigé (workflow: fixes via PRs utilisateur).
- Autres suites: 133 passed. État: migration full-cycle legacy en cours (determine_target_load retiré du week-plan #157; compute_current_weekly_km/compute_long_run_km restent).


## 2026-08-19 — Pull copilot/dev (PR #156) — TSS/km non validés retirés de generate_cycle_week — MERGÉ & VALIDÉ
- Fetch copilot/dev (2438985→de22c78). Merge ORT propre, 0 conflit. .env intacts. Backend+worker redémarrés.
- PR #156 = suppression des coefficients TSS/km non validés du générateur déterministe generate_cycle_week (llm_coach.py) → estimated_tss=None sur séances actives, total_tss=None. + tests.
- Validation: week-plan primaire séances actives est_tss=None (avant 14/16/15/30), total_tss=None (avant 75); jours de repos est_tss=0 (structurel rest→0, distances réelles conservées). Smoke 6/6=200. Régression = 134 passed, 0 failed.
- État: sémantique None désormais UNIFORME sur TOUS les chemins week-plan (primaire generate_cycle_week #156 + fallback duration #149 + fallback km/pace #153). Observation résiduelle sur le chemin primaire (signalée post-#155) LEVÉE.


## 2026-08-19 — Pull copilot/dev (PR #155) — week-plan lit sources canoniques (fin legacy db.training_goals) — MERGÉ & VALIDÉ
- Fetch copilot/dev (761281f→2438985). Merge ORT propre, 0 conflit. .env intacts. Backend+worker redémarrés.
- PR #155 = remplacement du reader legacy db.training_goals du week-plan (conservé en #154) par les sources canoniques (training_cycles). Plus AUCUN reader db.training_goals collection dans server.py (seule une mention en commentaire L4575).
- Validation: /training/week-plan passe désormais à 200 pour le user réel (était 400 pré-#155), goal.type=MARATHON depuis training_cycles. Smoke 8/8=200. Régression PR132→155 = 194 passed, 0 failed.
- OBSERVATION (non bloquante, non régression): le chemin PRIMAIRE de week-plan est le générateur déterministe generate_cycle_week (generated_by=llm, model=deterministic, context_type=cycle_week). Il émet des estimated_tss calculés sur les séances actives (14/16/15/30, total_tss=75) et estimated_tss=0 sur les jours de REPOS (légitime: rest→0 TSS). Ce n'est PAS le chemin fallback ciblé par #149/#153 (qui restent None). Cohérent avec la migration full-cycle/cycle-week V2 encore à venir (determine_target_load/compute_long_run_km).
- État: nettoyage legacy db.training_goals TERMINÉ côté week-plan (#154+#155). Chaîne Training Engine V2 stable.


## 2026-08-19 — Pull copilot/dev (PR #154) — Suppression accès runtime legacy db.training_goals — MERGÉ & VALIDÉ
- Fetch copilot/dev (041de63→761281f). Merge ORT propre, 0 conflit. .env intacts. Backend+worker redémarrés.
- PR #154 = suppression des accès runtime à la collection legacy db.training_goals (delete-training-goal path) + tests. REVERT documenté: le reader db.training_goals du week-plan (server.py L4576) est INTENTIONNELLEMENT conservé pour scope #155.
- Validation: server.py L102=import config module (OK), L4576=reader week-plan conservé (#155). Autres accès runtime db.training_goals supprimés. Smoke 7/7=200. Régression PR132→154 = 238 passed, 0 failed.
- État: nettoyage legacy training_goals en cours (#154 partiel, week-plan reader → #155). Chaîne Training Engine V2 stable.


## 2026-08-19 — Pull copilot/dev (PR #153) — Fake TSS supprimé du fallback km/pace-based — MERGÉ & VALIDÉ
- Fetch copilot/dev (c583d44→041de63). Merge ORT propre, 0 conflit. .env intacts. Backend+worker redémarrés.
- PR #153 = suppression des estimated_tss hardcodés (0/25/…) du 2e fallback km/pace-based (_generate_fallback_week_plan) → tous estimated_tss=None (terminologie: "estimated TSS not from validated calculation"). distance_km/paces réels conservés (prescription légitime). + tests ciblés test_pr153_fallback_no_unvalidated_tss.py.
- Validation: fallback km/pace-based confirmé estimated_tss=None partout ✓ (distance_km réels 5/6/7 conservés). Smoke 6/6=200. Régression PR132→153 = 311 passed, 0 failed.
- État: sémantique None finalisée sur TOUS les fallbacks week-plan (duration-based #149 + km/pace-based #153). Chaîne Training Engine V2 validée #132→#153, suite verte.


## 2026-08-19 — Pull copilot/dev (PR #152) — Test non-portable réparé — MERGÉ & VALIDÉ
- Fetch copilot/dev (43ee9ec→c583d44). Merge ORT propre, 0 conflit. .env intacts. Aucun code applicatif modifié (uniquement le test + docs).
- PR #152 = correction de test_pr149_week_plan_v2.py::test_fallback_code_path_exists_in_server: chemin CI absolu codé en dur → pathlib.Path(__file__).resolve().parent.parent/"server.py" (portable).
- Validation: suite PR132→152 = 351 passed, 0 failed (le test précédemment non-portable passe désormais dans notre env). Smoke 3/3=200. Aucune régression.
- État: chaîne Training Engine V2 validée (#132→#149), week-plan migré WeeklyTarget V2 (#149), suite de tests entièrement verte (#152). Obs. résiduelle non bloquante: 2e fallback km/pace-based de _generate_fallback_week_plan garde des estimated_tss hardcodés (legacy, hors scope).


## 2026-08-19 — Pull copilot/dev (PR #148 + PR #149) — MERGÉ & VALIDÉ (1 test non-portable non bloquant)
- Fetch copilot/dev (e1a222c→43ee9ec). Merge ORT propre, 0 conflit. .env intacts, protégés préservés. Backend+worker redémarrés.
- PR #148 = durcissement test (test_fallback_still_exists → preuve AST-based, vérifie fallback avg_pace/0.70 + vma_method=average dans la même branche).
- PR #149 = migration prescription /training/week-plan vers WeeklyTarget V2 (nouveau training_v2/week_plan_bridge.py::build_weekly_target_from_workouts) + fix estimated_tss:0/total_tss:0 → None dans le fallback DURATION-based. Legacy determine_target_load + generate_cycle_week conservés pour rendu LLM (compat).
- Validation: fallback duration-based confirmé estimated_tss=None/total_tss=None/distance_km=None ✓. Smoke endpoints principaux 5/5=200. Régression PR132→149 = 350 passed (hors 1 test non-portable).
- ⚠️ 2 observations non bloquantes:
  1. test_pr149_week_plan_v2.py::test_fallback_code_path_exists_in_server ÉCHOUE sur chemin absolu CI codé en dur (L361 /home/runner/work/sauvegarde260708/.../server.py inexistant ici) → problème de PORTABILITÉ de test, pas une régression (intention satisfaite, confirmée par grep). Correctif recommandé: Path(__file__).resolve().parents[1]/"server.py".
  2. /training/week-plan renvoie 400 "No goal defined" pour le user réel car le goal vit dans training_cycles, pas dans la collection training_goals lue par cet endpoint (L4576) — comportement PRÉ-EXISTANT inchangé par #149; non smoke-able sans écriture destructive (set-goal). Validé via tests unitaires PR149 à la place.
  - Note: le second fallback km/pace-based (_generate_fallback_week_plan) garde des estimated_tss hardcodés (0/25/...) — hors scope PR#149 (fix limité au duration-based), legacy.
- Rapports upstream: RUNINDEX_PR148_REPORT.md, RUNINDEX_PR149_REPORT.md.


## 2026-08-19 — Pull copilot/dev (PR #147) — Test fragile réparé (AST-based) — MERGÉ & VALIDÉ
- Fetch copilot/dev (936c966→e1a222c). Merge ORT propre, 0 conflit. .env intacts. Aucun code applicatif modifié (uniquement le test + docs).
- PR #147 = remplacement de l'assertion d'inspection de source fragile test_plan_duration_decoupled.py::test_adjusted_weeks_is_base_weeks par une preuve AST-based (robuste à la forme dict vs assignation).
- Validation: suite complète PR132→147 = 328 passed, 0 failed (le test précédemment échouant passe désormais). Smoke 4/4=200. Aucune régression.
- État TrainingEngine V2: chaîne runtime complète validée (#132→#146), single-source-of-truth GOAL_CONFIG finalisé (#145/#146), test suite verte (#147).


## 2026-08-19 — Smoke runtime final post-PR#146 (pré-#147) — VERDICTS: POST146_RUNTIME=PASS, TEST_FRAGILE_CONFIRMED=YES, PR147_REQUIRED=YES
- Audit LECTURE SEULE. HEAD 93e6501 (#145+#146). Services RUNNING. Imports: config.training_goals.GOAL_CONFIG OK, training_engine.GOAL_CONFIG→ImportError ✓, import training_engine OK ✓.
- Smoke 7/7=200 (today/plan/metrics/run-index/dashboard/goals/full-cycle). /training/goals runtime == config.training_goals.GOAL_CONFIG (5 goals, égalité exacte). Daily V2 non régressé (build_recent_training_response/build_readiness_decision/build_daily_adaptation; aucun adapt_session_to_readiness/training_engine/fatigue_*).
- Tests PR132→146 = 327 passed, 1 failed (uniquement test_plan_duration_decoupled.py::test_adjusted_weeks_is_base_weeks). Invariants comportementaux du découplage tous verts.
- TEST_FRAGILE_CONFIRMED=YES: L73 attend l'assignation "adjusted_weeks = base_weeks", code utilise forme dict "adjusted_weeks": base_weeks (L678) / "adjusted_weeks": total_weeks (L851 chemin principal) — sémantique identique. Mismatch syntaxique, pas régression.
- PR147_REQUIRED=YES pour assouplir cette assertion (accepter forme dict ou check AST/comportemental). Aucune correction applicative requise.
- Rapport: /app/TRAINING_V2_RUNTIME_POST146_PRE147.md.


## 2026-08-19 — Pull copilot/dev (PR #146) — GOAL_CONFIG orphelin supprimé — MERGÉ & VALIDÉ (1 test fragile non bloquant)
- Fetch copilot/dev (5c22ac4→936c966). Merge ORT propre, 0 conflit. .env intacts, protégés préservés. Backend+worker redémarrés.
- PR #146 = suppression de la copie orpheline GOAL_CONFIG de training_engine.py (-39 lignes) + mise à jour tests (test_goal_config_pr145.py, import test_plan_duration_decoupled.py training_engine→config). Finalise le single-source-of-truth de #145.
- Validation: `from training_engine import GOAL_CONFIG` → ImportError (orphelin supprimé ✓). config/training_goals.py reste canonique. Smoke 7/7=200 (today/plan/metrics/run-index/dashboard/goals/full-cycle). env intact.
- Tests régression PR132-146 = 233 passed, 1 FAILED.
- ⚠️ ÉCHEC NON BLOQUANT: test_plan_duration_decoupled.py::test_adjusted_weeks_is_base_weeks. Cause: assertion d'inspection de SOURCE fragile qui cherche le littéral "adjusted_weeks = base_weeks" alors que coach_service.py L678 utilise la forme dict "adjusted_weeks": base_weeks (sémantique identique). 40/41 tests du fichier passent, TOUS les invariants comportementaux du découplage OK (durée indépendante readiness, prep_insufficient, no silent shrink, base_weeks inchangé). PAS une régression fonctionnelle; non causé par le changement réel de #146 (qui n'a touché que la ligne d'import). Correctif recommandé (PR future): assouplir l'assertion (accepter la forme dict) ou passer à un check AST/comportemental. NON corrigé (workflow: fixes via PRs utilisateur).


## 2026-08-19 — Validation runtime post-PR#145 + inventaire legacy pré-#146 — VERDICTS: PR145_RUNTIME=PASS, PRE146_LEGACY_AUDIT=COMPLETE
- Audit LECTURE SEULE. HEAD d985a66 (#145). Smoke 5/5=200. /training/goals=200 (valeurs = config.training_goals.GOAL_CONFIG exactement). /training/full-cycle=200 (total_weeks=16, no NaN, aucun contrat cassé). set-goal DESTRUCTIF → non appelé, validé par inspection (utilise GOAL_CONFIG de config).
- Parité: config.training_goals.GOAL_CONFIG == training_engine.GOAL_CONFIG (True). MAIS training_engine.py:22 garde une COPIE ORPHELINE de GOAL_CONFIG (aucun import runtime). Daily V2 non régressé (build_recent_training_response/build_readiness_decision/build_daily_adaptation; aucun adapt_session_to_readiness/training_engine/fatigue_*).
- Inventaire legacy (HEAD actuel): consumers runtime training_engine = server.py (L86: 13 symboles + L4632 determine_target_load) et llm_coach.py (L21: 10 symboles), TOUS dans le chemin full-cycle/cycle-week legacy. training_v2/* = commentaires seulement (aucun import). Tests: test_goal_config_pr145.
- determine_target_load = prescriptif (charge cible hebdo) ≠ TrainingLoad V2 (descriptif/observé) → NO; équivalent V2 = WeeklyTarget V2. compute_current_weekly_km (protégé): 2 consumers legacy (server L4460/L4611), équiv V2 = TrainingHistory window_7d, risque moyen-élevé. Dette long-run: NOT OBSERVED en V2 (WorkoutGenerator borne long run 20-45% du weekly target).
- Tests: 224 passed / 0 failed.
- RECOMMANDATION #146 (scope unique, risque FAIBLE): supprimer la copie orpheline GOAL_CONFIG de training_engine.py + adapter le test de parité (finalisation single-source-of-truth, zéro impact runtime). NE PAS inclure determine_target_load/compute_current_weekly_km/compute_long_run_km (migration sémantique risquée, PRs dédiées).
- Rapport: /app/TRAINING_V2_RUNTIME_POST145_PRE146.md.


## 2026-08-19 — Pull copilot/dev (PR #145) — GOAL_CONFIG extrait vers config/training_goals.py — MERGÉ & VALIDÉ
- Fetch copilot/dev (09a256f→5c22ac4). Merge ORT propre, 0 conflit. .env intacts, protégés préservés. Backend+worker redémarrés.
- PR #145 = migration GOAL_CONFIG vers backend/config/training_goals.py (source unique de vérité) + suppression de l'import mort GOAL_CONFIG depuis training_engine. Fichiers: config/training_goals.py (nouveau), server.py (L102 import + usages L3486/3527/4411), test_goal_config_pr145.py.
- Validation: smoke 5/5=200. GOAL_CONFIG servi depuis config/training_goals.py. Tests PR145+régression PR135/137/143/144 = 97 passed.
- NOTE factuelle: training_engine reste importé dans server.py (L86: 13 symboles dont compute_current_weekly_km, compute_target_km, determine_phase, resolve_reprise_plan, apply_resume_guard, etc. + L4632 determine_target_load). PR#145 n'a extrait que GOAL_CONFIG; la suppression complète de training_engine reste une étape future. compute_current_weekly_km NON modifié (protégé).


## 2026-08-19 — Micro-validation RÉELLE CAUTION/LOW sur données historiques post-PR#144 — VERDICT: CAUTION REAL=PASS, LOW REAL=NOT FOUND
- Audit LECTURE SEULE. HEAD 97d6f1f (#143+#144). Scan 43 jours réels (daily metrics 2026-07-05→08-17) avec filtrage strict metrics/activités ≤ J (aucune fuite temporelle).
- Distribution réelle bandes: FAVORABLE=37, CAUTION=6 (07-19,08-03,08-04,08-09,08-15,08-16), LOW=0, VERY_LOW=0, UNAVAILABLE=0.
- CAS CAUTION RÉEL J=2026-08-16 (dimanche): inputs réels RHR=53, HRV=None, sleep_hours=9.1, sleep_score=None (non inventés). TrainingLoad ACWR=2.727/status=high. ReadinessResult=62.5/NORMAL/SUFFICIENT/missing_hrv → ReadinessDecision=CAUTION (vrai calcul). Séance long_easy 13.3km low. RecentTrainingResponse ≤J=sufficient/5 runs/avg_hr=134.4. DailyAdaptation=SHORTEN→9.3km (13.3×0.70), reasons [READINESS_CAUTION, TRAINING_LOAD_HIGH, LONG_EASY_PROTECTED, WORKOUT_SHORTENED, INTENSITY_NOT_INCREASED]. Monotonicité OK (13.3→9.3, low→low). Preuve fuite: metrics ≤J=42/43, activités ≤J=146/147.
- CAS LOW RÉEL: NOT FOUND (0 occurrence sur 43 jours). Non fabriqué. LOW déjà validé déterministe en mémoire, non reproductible sur données réelles disponibles.
- Absence legacy confirmée (chemin V2 pur). None≠0 respecté.
- Rapport: /app/TRAINING_V2_RUNTIME_REAL_LOW_CAUTION_POST144.md.


## 2026-08-19 — Micro-validation déterministe LOW/CAUTION/VERY_LOW (DailyAdaptation V2) post-PR#144 — VERDICT: PASS (11/11)
- Audit LECTURE SEULE. HEAD 857f583 (#143+#144). Séance réf (ref 2026-08-23): long_easy 13.3km low. ReadinessDecision par bande construits DÉTERMINISTES en mémoire (pas de falsification Garmin). TrainingLoad (acwr=0.612, status=low, conf=high) et RecentTrainingResponse (sufficient, 6 runs, avg_hr=135) RÉELS et IDENTIQUES dans les 3 scénarios.
- Résultats: FAVORABLE→KEEP (13.3km); CAUTION→SHORTEN (9.3km, LONG_EASY_PROTECTED); LOW→SHORTEN (9.3km); VERY_LOW→REST. SHORTEN_FACTOR=0.70 (13.3×0.70=9.31→9.3). Séance distance-only: SHORTEN via distance, durée None conservée. REST sans compensation.
- Monotonicité physiologique VERY_LOW≤LOW≤CAUTION≤FAVORABLE respectée (intensité jamais augmentée). #132 identique/consommé dans les 3 (n'impose pas action différente). daily_adaptation.py pure V2 (aucun legacy). None≠0 (aucun TSS=0/ACWR=1/durée/distance inventés).
- 11/11 PASS. Rapport: /app/TRAINING_V2_RUNTIME_LOW_CAUTION_VERYLOW_POST144.md.


## 2026-08-19 — Micro-validation runtime SÉANCE ACTIVE post-PR#144 — VERDICT: PASS
- Audit LECTURE SEULE. HEAD 857f583 (#143+#144). Aujourd'hui=repos → reproduction déterministe de la chaîne /training/today avec reference_date=2026-08-23 (dimanche, seule séance active du plan V2: long_run 13.3km easy). Aucune modif code/plan/Mongo/planning.
- Chaîne (fonctions identiques à l'endpoint): plan V2 → runtime_session_to_prescription (long_easy, 13.3km, intensity_class=low) → build_training_load (acute7d=44.02, chronic_wk=71.87, ACWR=0.612, conf=high) → readiness_adapter (score=100, NORMAL, SUFFICIENT) → build_readiness_decision (FAVORABLE, READINESS_FAVORABLE) → build_recent_training_response (#132: sufficient, available=6, hr_cov=6, avg_hr=135, trends increasing/stable — SIGNAL VIVANT ET CONSOMMÉ) → build_daily_adaptation (KEEP, reasons READINESS_FAVORABLE/PLAN_KEPT/INTENSITY_NOT_INCREASED).
- Monotonicité KEEP: séance identique (13.3→13.3, low→low), aucune augmentation. #132 disponible+consommé (≠ action forcément différente, readiness favorable → KEEP légitime).
- Non-régression: aucun adapt_session_to_readiness/training_engine dans le chemin daily; daily_adaptation.py sans import legacy; fatigue block sans fatigue_ratio/status/physio; aucun TSS=0/ACWR=1 inventé; None≠0 (ctl/atl/tsb null).
- 8/8 critères PASS. Rapport: /app/TRAINING_V2_RUNTIME_ACTIVE_DAY_POST144.md.
- NOTE: #138 déjà mergée avant #143/#144 (ne PAS relancer/recréer). Suite = migration des consumers legacy restants dans une PR ultérieure.


## 2026-08-19 — Pull copilot/dev (PR #144) — FIX BUG-137-01 MERGÉ & VALIDÉ RUNTIME
- Fetch copilot/dev (0b6b6a0→09a256f). Merge ORT propre, 0 conflit. .env intacts, protégés préservés. Backend+worker redémarrés.
- PR #144 (8255c6f) = fix BUG-137-01: training_response._activity_date utilise désormais datetime.fromisoformat (gère T-séparé, tz-aware ET espace-séparé "YYYY-MM-DD HH:MM:SS") + normalise suffixe Z. Nouveau test test_bug_137_01_date_parsing.py (16 cas).
- RE-VALIDATION runtime (compte réel da8505ef, ref 2026-08-19): _activity_date exploite 147/147 (avant 0). RecentTrainingResponse #132 REVIVE dans /training/today: status=sufficient, available_running=6, selected=6, observed_runs=6, hr_coverage=6, average_hr_recent=135, trends peuplés (vol/freq/long=increasing, cardiac=stable, intensity=increasing). BUG-137-01 RÉSOLU.
- Smoke 5/5=200. Tests PR144+régression PR132-144 = 219 passed. Signal #132 opérationnel côté /training/today.
- Rapport bug (pré-fix): /app/TRAINING_V2_RUNTIME_BUG13701_PRE144.md · rapport PR144 upstream: RUNINDEX_PR144_REPORT.md.
- Chemin dégagé pour re-valider #137 puis GO #138.


## 2026-08-18 — Pull sauvegarde260708/copilot/dev (PR #143) — MERGÉ & VALIDÉ
- Fetch branche copilot/dev (cfa2d14→0b6b6a0). Merge ORT propre, 0 conflit. .env intacts, fichiers protégés préservés. Backend+worker redémarrés.
- PR #143 = migration /training/metrics acwr_reliable vers la chaîne TrainingState V2 (+ renforcement tests: fixtures continuity_state exactes, preuve AST no-legacy-import). Fichiers: backend/server.py (+30 lignes /training/metrics), test_training_metrics_pr143.py.
- Validation: smoke 5/5=200. /training/metrics: acwr=2.538, acwr_reliable=true (via TrainingState V2), tsb/ctl/atl=null. Tests PR143=14 passed. Non-régression suites clés PR132-143 = 203 passed.
- ⚠️ BUG-137-01 (RecentTrainingResponse #132 mort dans /training/today à cause du format date espacé) TOUJOURS PRÉSENT sur copilot/dev — non adressé par PR#143. training_response._activity_date inchangé (ne parse pas "YYYY-MM-DD HH:MM:SS"). Reste à corriger avant GO #138.


## 2026-08-18 — Micro-validation runtime PR#137 (/training/today V2) — AUDIT LECTURE SEULE — VERDICT: #137 runtime=PARTIAL, GLOBAL=NO-GO #138
- HEAD 6241020 (#136+#137 mergés). Backend+worker redémarrés. Smoke 5/5 = 200. Compte réel da8505ef.
- Chaîne /training/today CONFORME: Plan V2 → séance prévue → Mongo garmin_activities → mongo_garmin_activities_to_domain → DomainActivity → TrainingLoad V2 → ReadinessResult V2 → ReadinessDecision V2 → DailyAdaptation V2 → payload. Aucun adapt_session_to_readiness/training_engine/fatigue_ratio/status/physio.
- Jour de repos (mardi): action=KEEP, reason_codes=[PLANNED_REST_DAY, PLAN_KEPT]. readiness=FAVORABLE/80.5/NORMAL/SUFFICIENT. Mapping BAND→reco OK (FAVORABLE→RUN HARD/green mais KEEP → séance non durcie). estimated_tss/total_tss/ctl/atl/tsb=null. ACWR interne=2.538=/training/metrics (arrondi seul). Frontière Mongo→DomainActivity: HR/intensité/D+ préservés (avg_hr 138, mod/vig min, elev 35m).
- 🔴 BUG-137-01 (HIGH): RecentTrainingResponse #132 SILENCIEUSEMENT INOPÉRANT dans /training/today. Via garmin_activities → available_running=0, status=unavailable, trends=unknown, avg_hr=None (alors que 125 running dans domain, champs préservés). Cause racine: training_response._activity_date ne parse PAS le format Mongo Garmin espace-séparé "YYYY-MM-DD HH:MM:SS" (n'essaie que ISO-T/date), alors que training_history._activity_date le gère. mongo_garmin_activities_to_domain passe la chaîne telle quelle. Chemin #135 marche car _to_domain_activity_from_workout reformate en ISO-T. Contredit l'objectif #137 de préservation à la frontière Mongo. Tests 202/202 passent mais masquent le bug (fixtures datetime/ISO-T).
- Correction recommandée (NON appliquée): aligner training_response._activity_date sur training_history (ajouter fromisoformat + formats espace) OU normaliser start_time en datetime dans le domain_adapter; + fixture format Mongo espacé.
- Rapport complet: /app/TRAINING_V2_MICRO_VALIDATION_RUNTIME_PR137.md. AUCUNE modif code, aucune PR.


## 2026-08-18 — Pull sauvegarde260708/main (PR #136 + PR #137) — MERGÉ & VALIDÉ RUNTIME
- Fetch sauvegarde/main 6ef49f8→a94adc4 (+9 commits). Merge local (HEAD 9ee8304). 1 seul conflit sur coach_service.py (guillemets simples local vs doubles upstream = cosmétique) → résolu en gardant la version upstream canonique. .env backend/frontend INTACTS, fichiers protégés préservés.
- PR #136 = hotfix Python 3.11 cache-key (version canonique upstream de mon hotfix local → OBS-2 précédent RÉSOLU en amont).
- PR #137 = migration /training/today vers DailyAdaptation V2 (#133 désormais BRANCHÉ au runtime): plan V2 → WorkoutPrescription → ReadinessResult V2 → build_readiness_decision → build_daily_adaptation → payload. Proxy legacy adapt_session_to_readiness retiré du chemin /training/today. Nouveaux: training_v2/daily_runtime_helpers.py + domain_adapter boundary Mongo→DomainActivity.
- Runtime validé (compte réel da8505ef): backend+worker redémarrés, /run-index /training/metrics /training/today /training/plan /dashboard = 200. /training/today renvoie reason codes DailyAdaptation V2 (PLANNED_REST_DAY, PLAN_KEPT = KEEP sur jour repos, conforme #133 V1). estimated_tss=null.
- Tests ciblés PR132+133+134+135+137 + readiness_decision + mongo_boundary = **249 passed / 0 failed**.
- NEXT roadmap réordonné après #137: #138 (audit exhaustif consumers legacy + extraction VMA/paces + frontières Mongo→V2), #139 (migration/suppression callers legacy), #140 (kill training_engine.py après preuve zéro consumer runtime), puis LT1/LT2. training_engine.py NON supprimé.


## 2026-08-17 — Validation runtime globale Training Engine V2 (post-PR #135) — AUDIT LECTURE SEULE — VERDICT: GLOBAL = GO #136
- Audit read-only, aucun code/PR/injection DB. Compte réel da8505ef (146 act, 41 daily). JWT read-only via auth.jwt_utils.
- Git: HEAD local 5807c8a, sauvegarde/main 6ef49f8, local +14/-0 (contient tout + hotfix Py3.11). Merges: #132=beee570, #133=b2f1ead, #134=8564060, #135=6ef49f8.
- Chaîne V2 entièrement branchée & cohérente runtime. ACWR recalculé indépendamment = 2.272 vs endpoints 2.272-2.273 (arrondi seul, acute=138min/chronic_weekly=60.75min). ctl/atl/tsb=null propagés.
- #132: window 28j, trends présents. #134: REDUCE_VOLUME 13.1→11.1 (floor 85%), target_sessions inchangé, invariants OK. #135: sessions_per_week==reconciled_target.target_sessions=1, estimated_tss/total_tss=null sans casser consumers. AUCUN fallback legacy (training_engine absent du chemin). generate_cycle_week = enrichissement LLM (non structurel).
- #133 (readiness_decision/daily_adaptation) NON branché runtime = couche pure (attendu avant #136); /training/today utilise encore adapt_session_to_readiness legacy. Validé en mémoire (None→UNAVAILABLE).
- Tests: PR132-135 + readiness_decision = 172 passed/0 failed. Modules V2 = 530 passed; 5 failed/3 errors tous HORS PÉRIMÈTRE (calibration training_state pré-existante non modifiée par PR132-135; plan_goal flakiness xdist; sse/subscription BASE_URL env). reprise_pr77 7 failed = info compatibilité seulement (fixtures legacy + doctrine reprise_exit), NON critère GO/NO-GO.
- Rapport complet: /app/TRAINING_V2_GLOBAL_RUNTIME_VALIDATION_POST_PR135.md.
- Observations non bloquantes: OBS-1 calibration continuity_confidence/NORMAL↔REPRISE_EXIT (doctrine, indépendant #135); OBS-2 hotfix Py3.11 coach_service.py à répercuter upstream dans PR#135; OBS-3 reprise_exit sans intensité imposée = changement comportement V2 (décision produit).
- NON commencé (interdit par user pendant audit): #136, LT1/LT2, trail/D+, V3 flexible scheduling. training_engine.py non supprimé.


## Changelog — Reprise après arrêt / comeback (PR77, June 2026)
- Durées de reprise profonde calées sur le niveau antérieur (fenêtre 6 sem, jours 28-42) via reprise_deep_durations: plancher 30/35/40 min (débutant/inconnu) -> 35/45/55 min (ex-coureur ~40km/sem). 3 séances, facile-only, AFFICHÉ EN MINUTES (weekly_minutes), plus en km. prior_weekly_km calculé dans coach_service.
- Frontend TrainingPlan.jsx: bandeau "Mode reprise" (deep/partial), carte semaine courante en minutes ("~105 min • 3 séances"). i18n FR/EN/ES.
- HEAD pulled to sauvegarde/main d0612d4 (PR#76 resume guard). Then reprise work (not pushed; use Save to Github).
- REAL-PATH bug found & fixed in PR76 cache bypass: coach_service.generate_dynamic_training_plan read cached_plan.get("weekly_km") (top-level, always None) → stale plan served. Now reads cached_plan["plan"]["weekly_km"].
- Reprise logic centralized in training_engine.py (single source): resolve_chronic_base (active-weeks avg, no /4 dilution), classify_training_state (deep_reprise/partial_reprise/reprise_exit/normal), resolve_reprise_plan, build_reprise_week_structure, cap_long_run_for_low_volume (≤40% target below goal floor), REPRISE_BASE_KM=12, REPRISE_STABLE_WEEKS=3, REPRISE_DEEP_SESSION_MINUTES=[20,25,30].
- deep_reprise (0km/28d): duration-based easy sessions (run/walk), no imposed km. partial_reprise: easy-only, volume progresses, intensity frozen. reprise_exit: intensity reintroduced + volume HELD (never both at once). normal: unchanged.
- Adaptive exit driven by completed active weeks (not fixed calendar). recovery_red_flag hook present (default False) for a future alert-signals PR. compute_current_weekly_km (ACWR/readiness contract) UNTOUCHED.
- Wired into 3 paths: coach_service.generate_dynamic_training_plan, server.py /training/full-cycle, /training/week-plan. Long run consolidated through compute_long_run_km.
- Tests: backend/tests/test_reprise_pr77.py (7 mandatory scenarios) + test_real_cache_bypass_pr76.py. 150 passed across plan suites. e2e HTTP: new user → /training/plan state=deep_reprise, 20/25/30min. Report: /app/REPRISE_PR77_REPORT.md. Nothing deployed.


## Changelog — gccli session sharing via MongoDB (August 2, 2026)
- New backend/garmin/session_store.py: save/restore/ensure/delete per-user gccli session, encrypted (Fernet; key = GCCLI_SESSION_KEY or derived from JWT_SECRET_KEY). Collection garmin_sessions, keyed by user_id (strict isolation).
- garmin/service.py hooks: save_session after /connect; ensure_session before sync/incremental_sync (graceful "session_unavailable" if missing); re-save after successful sync/deep_sync/incremental; delete_session on disconnect.
- Enables workers on a separate host (Railway) to hydrate the gccli session created by the Emergent backend. Worker must share the same encryption key (GCCLI_SESSION_KEY or JWT_SECRET_KEY).
- Tests: test_garmin_session_store.py (5) + adapted deep_sync dispatch tests. Auth/Paddle/Stripe untouched. Nothing deployed.


## Changelog — Paddle sandbox configured & validated (August 2, 2026)
- Configured all 5 Paddle env vars in backend/.env (sandbox): PADDLE_API_KEY, PADDLE_CLIENT_TOKEN, PADDLE_PRICE_ID (pri_01kz18h08y4yq9pyh05axvaczj = RunIndex PREMIUM 4,99€/mo), PADDLE_WEBHOOK_SECRET (notif dest "PREMIUM", 4 events), PADDLE_ENVIRONMENT=sandbox.
- Paddle default payment link / domain approved in dashboard.
- Validated: /api/subscription/paddle/config → configured:true; /paddle/checkout creates real transaction (200); browser test → Paddle overlay opens with no error (fr-FR locale). The "en-US@posix" error was a headless-locale artifact only.
- Added data-testid="premium-subscribe-btn" to Subscription.jsx premium button.
- REMAINING: real test-card payment (webhook → Premium) to be done manually; for PRODUCTION, replicate the 5 PADDLE_* vars + webhook destination/domain on the prod URL.


## Changelog — Free trial button fix (August 1, 2026)
- Bug: "Démarrer mon essai gratuit" (Subscription.jsx) called handleSubscribe → Paddle checkout (card required) instead of activating a free trial.
- Backend: new `POST /api/subscription/start-trial` (auth JWT, user["id"] only) — activates 30-day trial, no card, no Paddle; refuses a 2nd trial (409 via `trial_used`).
- Frontend: hero button now calls start-trial for Free users (handleSubscribe/Paddle kept for premium subscribe). i18n keys `trialStarted`/`trialAlreadyUsed` (FR/EN).
- Tests: `backend/tests/test_start_trial.py` (3 passed): 401 no-JWT, Free→trial no-card, 2nd trial→409. E2E confirmed (free→trial, is_premium True).


## Changelog — Garmin per-user connection fix (August 1, 2026)
- Removed global .env credential fallback (`GARMIN_USERNAME`/`GARMIN_PASSWORD`) for user connections in `garmin/providers/gccli_provider.py` (new `allow_global_account` flag; only bootstrap may use env).
- `garmin/factory.py`: `get_provider_for_user` → `allow_global_account=False`; `get_provider` (bootstrap) → `True`.
- Frontend `Onboarding.jsx`: each user now enters their own Garmin email+password (fixes 422 empty-body call); password cleared after success. i18n keys added.
- Isolation: JWT-only identity (`current_user["id"]`), per-user `GCCLI_HOME/{user_id}`, all Mongo scoped by `user_id`; no creds in API responses/logs.
- Tests: `backend/tests/test_garmin_user_connection.py` (58 Garmin tests pass). E2E: 401 no-JWT, 422 no-creds, error on fake creds (never global data). `yarn build` OK.
- Report: `/app/GARMIN_FIX_REPORT.md`. Verdict: GARMIN READY (gccli unofficial; real login depends on user's Garmin/MFA — documented limitation).


## App Overview
RunIndex — running/cardio training coach. Garmin (gccli) integration, AI coach (LLM), RunIndex/readiness engines, training plans, Stripe subscriptions, Terra integration.

## Tech Stack
- Backend: FastAPI + Motor (MongoDB), emergentintegrations (Emergent LLM key), Stripe, Redis (jobs/queue/SSE/workers)
- Frontend: React 19 + CRACO + Tailwind + Radix UI + recharts
- Services (supervisor): backend:8001, frontend:3000, mongodb, redis:6379 (added)

## Setup Done (2026-07-07)
- Cloned repo into /app (preserved platform .git/.emergent, kept protected .env vars)
- Installed backend requirements + frontend yarn deps
- backend/.env: added EMERGENT_LLM_KEY, STRIPE_API_KEY=sk_test_emergent, FRONTEND_URL, REDIS_URL
- Added redis supervisor service using vendored /app/bin/redis-server (LD_LIBRARY_PATH=/app/lib)
- Fixed bug in frontend/plugins/visual-edits/babel-metadata-plugin.js (null parentPath.parentPath crash) that blocked webpack build (Coach.jsx)
- Verified: dashboard + Coach pages render, /api/stats /api/dashboard/insight return data, gccli auto-installed at startup

## Notes
- gccli Garmin login only triggers if GARMIN_PROVIDER=gccli (not set) — no Garmin creds required to boot
- Celery/worker processes (sync/monitor/scheduler) are separate; not started by API

## Backlog / Next
- Configure Garmin credentials (GARMIN_USERNAME/PASSWORD/GARMIN_PROVIDER) for real sync if desired
- Start worker processes if background sync/SSE features are needed

## Garmin Connected (2026-07-07)
- backend/.env: GARMIN_PROVIDER=gccli, GARMIN_USERNAME, GARMIN_PASSWORD set (account: mallegolbrieg@gmail.com)
- gccli one-time headless login succeeded; OAuth token persisted at /app/backend/.gccli_home (auto-refreshes)
- Added 4 worker supervisor services: garmin-sync-worker, garmin-event-worker, garmin-scheduler-worker, garmin-monitor-worker
- Verified end-to-end: 30 activities + 30 derived workouts + 7 daily metrics synced; RunIndex 390/1000, Run Readiness 77, RHR 47, Sleep 7.7h
- Scheduler auto-enqueues incremental syncs (~60s scan); event worker builds workouts layer + SSE feed

## Pull sauvegarde260708 — newer version (2026-07-08)
- Pulled commit 9fe9e8c (Merge PR #2). ~60 code files updated vs previous; deps unchanged; babel fix already included upstream.
- rsynced into /app preserving .git/.emergent/.env/.gccli_home/bin. Garmin creds + workers intact.
- API root now "RunIndex API" (rebrand); queue renamed runindex:garmin:queue.
- All services healthy; gccli session reused; Garmin still connected (30 activities). Dashboard renders (RunIndex 390, Readiness 77).

## Branding RunIndex (2026-07-08)
- New logo integrated: header (Layout.jsx) now uses /runindex-logo.png (background keyed out from original navy JPG -> transparent PNG via PIL)
- Full logo added to Onboarding welcome screen + new BrandSplash loading screen (LoadingSpinner.jsx) used on Dashboard initial load (pulse animation)
- Regenerated favicon/PWA icons (72-512px) with the green "R" mark on navy
- Created light-background logo variant /runindex-logo-light.png (dark navy "Run" text) for light surfaces / print / emails

## Pull sauvegarde260708 — Sessions tab (2026-07-09)
- Pulled commit 9909760 (Merge PR #3 "sessions tab"). New: pages/Sessions.jsx, pages/SessionDetail.jsx; modified App.js (routes /sessions, /sessions/:id), Layout.jsx (nav item), i18n.js (sessions translations en/fr/es).
- BUG in pulled code: `sessions` i18n block was nested under `workout` -> pages call t("sessions.*") -> raw keys shown. FIXED in lib/i18n.js by promoting workout.sessions to a top-level `sessions` alias per language (post-object normalization loop).
- Verified: Sessions list (30 Garmin activities, filters/sort/search translated) + SessionDetail (metrics + AI analysis sections) render correctly. Branding (logo) preserved.

## Pull sauvegarde260708 — PR #12 Garmin deep history sync (2026-07-10)
- Pulled commit d5fac75. runner.fetch_activities now supports --start pagination; gccli_provider.fetch_all_activities() paginates; garmin/service.deep_sync() imports full history once (gated by deep_sync_done, GARMIN_DEEP_SYNC_ENABLED default true), then RunIndex backfill. New test_garmin_deep_sync.py.
- 21/21 tests pass. Triggered one-time deep_sync for existing user default: imported ALL 141 activities (111 new), back to 2024-11-23 (was 30, oldest 2026-01-21). workouts=141.
- Re-ran RunIndex backfill: now 50 snapshots, oldest 2025-07-09 (365-day window); /run-index/history 12m returns 13 monthly pts, has_full_period_data=True. Progress graph richly populated across 6/12m.
- Note: history graph capped at 365 days by design (HISTORY_WINDOW_DAYS); activities stored back to Nov 2024 but curve shows max 12 months.

## Feature: race countdown in Training tab active state (2026-07-12)
- Found upcoming/completed cycle states already wired (banners + weeksToStart + daysToRace + plan start date). Only missing piece: countdown for ACTIVE cycles.
- Added i18n key trainingPlanExtended.raceCountdown (en "D-{days} to race" / fr "J-{days} avant la course" / es "F-{days} para la carrera").
- TrainingPlan.jsx: added amber J-X/D-X badge (data-testid="active-race-countdown") next to "Week X/Y • goal" when status active and days_to_race>=0.
- Verified live: active cycle (event +70d) shows "D-70 to race"; no compile errors. Default user goal restored to none.

## Bug fix: free trial not working (2026-07-12)
Reported: "activate free trial ... cela ne fonctionne pas". Two-layer root cause (found via testing_agent):
1. Backend /api/subscription/status only recognized Stripe status=='active' -> trial users showed tier='free' on Subscriptions page. FIX: added elif branch recognizing trial/early_adopter/premium (is_premium, unlimited, tier_name). Also reset-to-trial now uses TRIAL_DURATION_DAYS (30).
2. Backend subscription_middleware get_user_id_from_request (server.py:244) ignored the X-User-Id header the frontend sends -> attributed requests to IP user (free) -> 403 on /workouts, /training/* -> Training/Sessions paywalled. FIX: read X-User-Id header before IP fallback.
3. Frontend Sessions.jsx fetched /workouts without X-User-Id header -> empty list. FIX: pass headers {X-User-Id: USER_ID}.
Added trial banner on /subscription (data-testid=trial-active-banner) + i18n subscription.trialActive.
Verified: testing_agent iteration_26 (Training paywall gone, backend 8/8 pytest); self-test screenshot Sessions list populated with Garmin activities. default user on active 30-day trial.

## Bug fix: session AI analysis not displaying (2026-07-12)
Reported: "l'analyse IA de séance ne s'affiche pas". Root cause: WorkoutDetail.jsx 4 axios calls (/workouts/:id, /coach/workout-analysis, /coach/detailed-analysis, /rag/workout) sent NO X-User-Id header -> protected analysis endpoints returned 403 for the IP/free user -> analysis empty.
FIX: global axios request interceptor in src/index.js injecting X-User-Id=USER_ID('default') on all /api requests (also prevents recurrence app-wide, per testing_agent recommendation).
Verified by testing_agent iteration_27: 100% backend+frontend, analysis renders end-to-end, no regressions on sessions/training/progress/subscription. retest_needed=false.

## Pull sauvegarde260708 — PR #16 (subscription architecture) + latent chat bug fix (2026-07-12)
- Pulled commit 29fce67. Modified server.py, Subscription.jsx, i18n.js + test_subscription_chat.py. All my prior fixes (X-User-Id middleware, trial recognition in /subscription/status, global axios interceptor, trial banner, i18n aliases) were present in the backup (pushed via Save to GitHub) -> no regression.
- LATENT BUG found & fixed: POST /api/chat/send quota only recognized Stripe status=='active' -> trial users blocked after 10 messages ("reached your limit (Free)"). FIX (server.py ~4976): added elif for trial/early_adopter/premium -> unlimited chat (messages_limit=999, unlimited=True). Also relaxed a test assertion for unlimited plans.
- Verified: testing_agent iteration_28 -> 100% backend+frontend, 25/25 pytest, chat unlimited on trial, no paywall, no regressions. retest_needed=false.
- Backlog notes (non-blocking): extract a shared tier->is_unlimited resolver to avoid drift between /subscription/status and chat quota; don't increment messages_used for unlimited tiers; Settings Event Date could use shadcn Calendar instead of native picker.

## 2026-07-27 — Retour à la PR #16 (revert PR #17 Supabase)
- La PR #17 (auth Supabase obligatoire) a été retirée : insertion automatique corrompue de `user_id = user["id"]` (44 occurrences, dont une dans un corps de classe) faisait planter le backend au démarrage (NameError), + config Supabase manquante + risque de perte des données "default".
- Décision utilisateur : revenir à la PR #16.
- Action : re-sync du commit `29fce67` (PR #16) depuis GitHub dans /app, en préservant .env, .git, .emergent, session Garmin (.gccli_home), binaire gccli (bin/), node_modules et /app/memory. Fichiers Supabase supprimés (backend/auth, frontend supabase.js/AuthContext/Login/Signup). package.json sans @supabase.
- Vérifié : backend démarre proprement, session Garmin retrouvée, 141 workouts, run-index history 12m (12 points, current 352), abonnement trial 29 j, Dashboard s'affiche correctement (screenshot).
- auth_user (PR16) = auth flexible avec fallback "default" (non-bloquant).

## 2026-07-27 — Pull branche PR16Bis
- Synchronisé la branche PR16Bis (head 4d96cc3, PR #19) : retire le gate Supabase cassé, ajoute durcissement (demo_mode fail-fast en prod, vérif signature webhook Stripe via services/stripe_webhook_security.py, CORS strict en prod). yarn.lock régénéré.
- Vérifié : backend démarre, session Garmin OK, 141 workouts, run-index history OK, sub trial 29j, Dashboard rend correctement, aucun gate de login.
- ⚠️ 2 bugs détectés dans la branche (non corrigés, en attente décision user):
  1. /api/chat/send (server.py:5014) ne reconnaît que status=="active" → ignore trial/early_adopter/premium → limite Free imposée aux users en essai (régression vs PR16).
  2. /api/training/today (server.py:3549) crash 500 quand aucun plan (generate_dynamic_training_plan renvoie None, `plan.get` sur None).

## 2026-07-27 — Pull PR16Bis (PR #22, head 25835ec)
- Chat IA : trial → tier "pro" (illimité). VÉRIFIÉ OK (réponse coach retournée).
- ⚠️ training/today (server.py:3556) TOUJOURS cassé (500) : garde-fou incomplet, `plan["plan"]` peut être None. Fix restant: `sessions = (plan.get("plan") or {}).get("sessions", [])`. Non corrigé upstream.

## 2026-07-27 — Correctif local training/today (patch ciblé)
- server.py:3556 : `plan.get("plan", {})` -> `(plan.get("plan") or {})`. Corrige le crash 500 quand `plan["plan"]` est None (cycle upcoming/sans plan actif).
- VÉRIFIÉ via curl (URL externe) :
  - CASE 1 (aucun plan actif / upcoming) -> HTTP 200, réponse gracieuse, aucun traceback.
  - CASE 2 (plan actif, 7 séances) -> HTTP 200, status "success" avec planned_session + adaptive_session. (testé via objectif temporaire puis état restauré à l'identique).
- À COMMITTER côté GitHub via "Save to Github" (message: "Fix training today null plan guard") sinon écrasé au prochain pull.

## 2026-07-28 — Pull PR22 (auth JWT multi-utilisateurs, head 8155aa1)
- Ajoute module backend auth/ (JWT custom: register/login/me/forgot/reset), frontend Login/Register/ForgotPassword/ResetPassword + AuthContext, App.js gated (login obligatoire). Interceptor axios envoie Bearer JWT (plus de X-User-Id).
- backend auth_user: valide JWT (sub=UUID), garde fallback X-User-Id/query param (legacy Step2), sinon "unauthenticated".
- JWT_SECRET_KEY généré et ajouté à backend/.env. yarn.lock régénéré. Fix training/today présent upstream aussi.
- VÉRIFIÉ: register/login/me OK, login screen rendu.
- ⚠️ MIGRATION INCOMPLÈTE (Step 2 pending par design):
  - /subscription/info et d'autres endpoints gardent user_id="default" en dur -> ignorent le JWT.
  - /workouts utilise l'UUID JWT -> nouvel user bloqué "free" (pas de trial auto-créé).
  - 141 activités restent sous "default"; nouvel user voit une app vide.
  - Frontend n'envoie plus X-User-Id -> le propriétaire ne voit plus ses données via l'UI sans migration.
- Compte test: testrunner@runindex.app / Test1234! (voir test_credentials.md).

## 2026-07-28 — Pull PR22 mis à jour (PR #25 "ÉTAPE 2/3", head 72a77bb)
- auth_user exige désormais un JWT (fallbacks X-User-Id/query supprimés -> 401/403). Trial 30j auto-créé à l'inscription (auth/router.py). /subscription/info et handlers migrés vers JWT.
- VÉRIFIÉ: register->trial(29j, UUID), /subscription/info JWT OK, no-auth=403, X-User-Id=default=401.
- ⚠️ BUG RESTANT (dernier blocage): le middleware d'abonnement (server.py:397) utilise get_user_id_from_request (server.py:284) qui lit query param -> header X-User-Id -> IP, PAS le JWT. Donc /workouts, /training/*, /coach/* (routes protégées) sont bloquées 403 pour un user JWT-only (middleware résout l'IP au lieu de l'UUID).
  - Preuve: /workouts JWT seul=403 ; /workouts?user_id=<UUID> JWT=200 [].
  - FIX upstream: dans get_user_id_from_request, décoder le Bearer JWT en premier (comme auth_user) et retourner payload['sub'] avant les fallbacks query/header/IP.
- Comptes test créés: isotest_*@runindex.app / Test1234! (jetables).

## 2026-07-28 — Pull PR22 (PR #26, head 987dc26)
- PR #26 corrige le middleware: get_user_id_from_request décode le JWT en premier (fix recommandé appliqué upstream). Backend multi-user JWT VÉRIFIÉ 100%: workouts JWT=200[], training/today=200, subscription/info=trial+UUID, no-auth=403, chat trial illimité=reply.
- CORRIGÉ EN LOCAL: Subscription.jsx chaînes non terminées lignes 186 ET 198 (guillemets manquants) -> build frontend réparé. Scan de tous les .jsx/.js: aucun autre fichier affecté. VÉRIFIÉ: register via UI -> dashboard (compte isolé vide, "Connect Garmin", séance du jour), routes protégées OK. À COMMITTER sur GitHub (Save to Github).

## 2026-07-29 — Pull PR22 (PR #32, head 74ed67c)
- Nouveau backend/access_control.py: source unique de vérité pour les décisions d'accès (tiers FREE/TRIAL/PREMIUM, fail-closed sur erreur DB, identité toujours via JWT, guard DEMO_MODE+production à l'import). Intégré dans server.py (middleware, /subscription/status) + nouvel endpoint /api/user/features. subscription_manager.py modifié.
- La branche a intégré mon correctif Subscription.jsx (lignes 186/198 OK). Frontend inchangé vs état précédent.
- VÉRIFIÉ: register->trial, workouts JWT=200[], subscription/status=trial/premium(msg 999), /api/user/features renvoie plan+feature_access, no-auth=401, login screen rendu.
- AST syntax check OK sur access_control.py, server.py, subscription_manager.py.

## 2026-07-29 — Pull PR22 (PR #34, head a6034ba) — Migration Stripe→Paddle
- Backend: paddle_webhook_security.py + endpoints /subscription/paddle/checkout, /subscription/paddle/config, /webhook/paddle. Env vars (os.environ.get, défauts vides): PADDLE_API_KEY, PADDLE_WEBHOOK_SECRET, PADDLE_ENVIRONMENT(sandbox), PADDLE_PRICE_ID, PADDLE_CLIENT_TOKEN. Backend démarre sans clés; checkout->503 "Paddle not configured", config->configured:false, webhook->rejeté.
- Frontend: @paddle/paddle-js installé; Paywall/Subscription/Settings/SubscriptionContext MAJ. Backend AST OK.
- VÉRIFIÉ: register->trial, workouts/user/features JWT OK, subscription page rend, dashboard rend.
- BLOCAGE CORRIGÉ (local): Paywall.jsx:180 `PREMIUM_OFFER.features.map()` provoquait récursion infinie dans frontend/plugins/visual-edits/babel-metadata-plugin.js -> build cassé. Fix: propager garde skipArrayContext dans analyzeMemberExpression (appel getArrayIterationContext + appel analyzeIdentifier). Cache node_modules/.cache purgé, frontend recompile OK.
  - ⚠️ Plugin versionné dans la branche -> fix écrasé au prochain pull. Options: committer le fix plugin OU modifier Paywall.jsx (destructurer features avant .map).
- Paddle NON FONCTIONNEL tant que les clés sandbox ne sont pas fournies par l'utilisateur.

## 2026-07-30 — Paddle Sandbox E2E + Fix Paywall (périmètre Paddle uniquement)
- Paywall FIX PÉRENNE: Paywall.jsx refactorisé (destructuration `const {offer_name, features, cta_button} = PREMIUM_OFFER;` -> `features.map`), plugin visual-edits/babel-metadata-plugin.js RESTAURÉ à l'original (patch temporaire retiré). Build "Compiled successfully!" sans patch. Page rend.
- Backend Paddle audité: checkout (user_id via JWT, jamais frontend), config (aucun secret exposé, configured=bool(client_token&&price_id)), webhook (raw body -> vérif signature HMAC-SHA256 ts:body -> idempotence paddle_events sur event_id -> activate_premium via subscription_manager -> access_control). Frontend: client_token public only, env forcé sandbox sauf backend=production, onPaymentSuccess -> refreshSubscription() (aucun octroi local). SubscriptionContext FAIL-CLOSED (status:free + features false sur erreur).
- Tests: 48 PASS (tests/test_paddle_subscription.py) couvrant signature/tamper/malformed/idempotence/isolation/activation/renew/cancel/expiration/free-quota/fail-closed/legacy tiers.
- Live: trial=premium access+999msg, free=10msg+premium bloqué, unsigned webhook rejeté (500 car PADDLE_WEBHOOK_SECRET absent).
- ⚠️ BLOQUÉ: aucune clé PADDLE_ dans l'env -> config live=false, checkout overlay/paiement sandbox réel/webhook live depuis Paddle NON testables. Nécessite: PADDLE_CLIENT_TOKEN, PADDLE_API_KEY, PADDLE_WEBHOOK_SECRET, PADDLE_PRICE_ID (sandbox).
- NON déclaré "Sandbox Ready" ni "Production Ready".

## 2026-07-30 — Pull PR22 (PR #38 trial freemium + Garmin trial, head 44dc1c4) — BACKEND DOWN
- Paywall.jsx re-refactorisé en local (fix pérenne non committé upstream) -> frontend compile OK.
- ⚠️ BACKEND 502 (crash import): backend/api/garmin.py CORROMPU par PR#38:
  1. En-tête DUPLIQUÉ (2x docstring + 2x `from __future__ import annotations`); le 2e (ligne 44) est illégal -> SyntaxError.
  2. Ligne 61: `from auth.supabase_jwt import extract_user_id` -> module inexistant (auth/ = JWT jwt_utils.py). ModuleNotFoundError.
  - server.py:6014 `from api.garmin import garmin_router` non protégé -> toute l'API tombe.
- Fix upstream requis (dans api/garmin.py): (a) supprimer le bloc d'en-tête dupliqué (garder 1 seul, `from __future__` en tout début), (b) remplacer l'import supabase par: `from auth.jwt_utils import decode_access_token` et dans _resolve_user_id utiliser `decode_access_token(creds.credentials).get("sub")`.
- Toujours aucune clé PADDLE_ dans l'env.
- STOP + report (code Garmin protégé + décision requise). Fix local non appliqué sans accord.

## 2026-08-04 — Dashboard: encart Run Readiness aligné sur RunIndex
- Suppression du bloc comparatif "RunIndex vs état du jour" (Dashboard.jsx + i18n).
- Run Readiness transformé en encart identique à RunIndex (même dégradé/bordure/ombre): label vert "RUN READINESS", sous-titre blanc, grand chiffre `text-6xl font-black` coloré selon l'état de forme (vert/orange/rouge) suivi de "/ 100" vert, pastille de recommandation + refresh en haut à droite.
- Composantes VFC/FC/Sommeil/Charge/Ratio affichées en style piliers RunIndex (choix user: option b): barre pleine colorée selon le statut (vert/orange/rouge) + vraie valeur à droite (ex: +6 ms, 52 bpm, 7.2 h, 1.42, 1.18), SANS pourcentage inventé.
- Nouveau composant `ReadinessPillar` dans Dashboard.jsx; nouvelles clés i18n `dashboard.readinessPillars.{hrv,rhr,sleep,load,ratio}` FR/EN/ES. Anciens `MetricWidget`/decision-card retirés du rendu.
- data-testid: run-readiness-card, run-readiness-title, run-readiness-score, run-readiness-recommendation, run-readiness-refresh, run-readiness-pillars, readiness-pillar-{hrv,rhr,sleep,load,ratio}.
- Vérifié: frontend "Compiled successfully"; screenshot (données interceptées) confirme carte jumelle RunIndex, score 68/100 orange, 5 barres de statut + valeurs. Backend inchangé.

## 2026-08-04 — Run Readiness: TSB building, mini-historique 7j, tap-info
- **TSB « base en construction »**: backend `/api/training/metrics` renvoie `tsb_reliable` (= acwr_reliable) et `tsb_status="building"` en reprise (deep/partial). TrainingPlan.jsx affiche « — / Base en construction » (gris) comme l'ACWR. i18n `dashboard.tsb_status.building` FR/EN/ES. Vérifié: curl (tsb_reliable=false, tsb_status=building) + screenshot /training (— / Baseline building).
- **Mini-historique 7 jours**: backend insights.py ajoute `run_readiness` par jour dans `history` (100 - physio_penalty_jour - acwr_penalty). Dashboard.jsx affiche une courbe `MiniLineChart` sous les tuiles ("7-DAY READINESS" + score du jour + labels jours). data-testid `readiness-trend`.
- **Détail au tap**: chaque `ReadinessTile` est un bouton (icône ⓘ + point d'état) qui ouvre un `Dialog` (shadcn) avec explication courte de la composante. i18n `dashboard.readinessInfo.{hrv,rhr,sleep,load,ratio}` FR/EN/ES. data-testid `readiness-info-dialog`.
- ⚠️ LEÇON: NE PAS faire plusieurs `search_replace` en parallèle sur le MÊME fichier — une course a fait perdre l'import `Dialog` et créé un bloc dupliqué en fin de Dashboard.jsx (corrigé). Éditer un même fichier séquentiellement.
- Vérifié: frontend "Compiled successfully"; screenshots Dashboard (tuiles+courbe+dialog) et /training (TSB building). Backend inchangé sur ACWR/compute_current_weekly_km.

## 2026-08-04 — Run Readiness: 4 tuiles + courbe ACWR par jour
- Tuile "Ratio fatigue" retirée du front (Dashboard.jsx). Grille passée à `grid-cols-2 sm:grid-cols-4` → 4 tuiles (VFC, FC, Sommeil, Charge) sur une ligne.
- Courbe 7 jours plate corrigée: insights.py calcule désormais un **ACWR glissant par jour** (`_compute_acwr(activities, jour)`) au lieu de réutiliser l'ACWR global pour chaque jour. `run_readiness` par jour = 100 - physio_penalty_jour - acwr_penalty_jour. `history.training_load` = ACWR du jour.
- Données réelles confirmées: `garmin_daily_metrics` a ~8 jours/user (RHR+sommeil réels; HRV non enregistrée par l'appareil → affiche "—"). Après fix, readiness historique varie: ex default `[48,65,40,76,75,77,77]`, user reprise `[70,70,70,70,100,38,25]`.
- Note: platitude résiduelle possible = réelle (athlète frais ACWR~1 → ~100 ; surcharge continue → plancher). HRV manquante réduit la variation physiologique.
- Vérifié: compute_run_index (python), frontend "Compiled successfully" + screenshot (4 tuiles + courbe variée). ACWR "today" et compute_current_weekly_km inchangés.

## 2026-08-04 — Courbe readiness sur 30 jours
- Historique readiness passé de 7 à 30 jours: insights.py `metrics_docs[:30]`. Aucun sélecteur de période.
- Dashboard.jsx: label `dashboard.monthlyReadiness` (FR "Forme sur 30 jours" / EN "30-Day Readiness" / ES "Forma 30 días"). Labels d'axe = date début (history[0].date) et date fin (MM-DD), au lieu d'un libellé par jour (illisible à 30 points).
- Vérifié: frontend "Compiled successfully" + screenshot (courbe 30 pts variée, 07-01→07-30). Note: users réels ont ~8 jours de métriques -> la courbe se remplit jusqu'à 30 au fil du temps.

## 2026-08-04 — Courbe readiness: retrait score + hauteur
- Retiré le score "{n} / 100" à droite de l'en-tête de la courbe (Dashboard.jsx). En-tête = libellé seul.
- Platitude visuelle corrigée: `MiniLineChart` accepte désormais une prop `height` (défaut 60), la courbe readiness est passée à 110px. La platitude venait du ratio largeur/hauteur (très large, 60px) ; MiniLineChart normalise déjà min-max donc les variations ressortent nettement à 110px.
- Vérifié: screenshot (courbe 30j haute avec pics/creux visibles, plus de score à droite).

## 2026-08-04 — Fenêtre métriques Garmin: 7 → 30 jours
- Cause du "8 jours" identifiée: la synchro Garmin ne demandait que 7 jours de métriques bien-être (runner.fetch_daily_metrics days=7 ; service.get_daily_metrics days=7 aux 2 appels). Les activités remontent loin (limite 200), pas les métriques quotidiennes.
- Fix: `backend/garmin/service.py` → `provider.get_daily_metrics(user_id, days=30)` sur les 2 chemins (deep_sync ligne 225, sync régulière ligne 302). Le paramètre `days` transite jusqu'à runner.fetch_daily_metrics.
- ⚠️ Nécessite une NOUVELLE synchro Garmin (côté user) pour backfiller l'historique 30 jours. Upsert idempotent.
- ⚠️ Perf: 30 jours × 3 endpoints gccli = ~90 sous-process par sync (plus lent, risque rate-limit Garmin). Si trop lourd: garder deep_sync=30 et repasser la sync régulière à 7. À surveiller.
- Vérifié: backend health 200, code transmet bien days=30. NON testé en réel (nécessite session gccli live + vraie sync).

## 2026-08-04 — Courbe readiness: zones d'état + info-bulle
- Nouveau composant `ReadinessChart` (Dashboard.jsx) remplace MiniLineChart pour la readiness. Échelle ABSOLUE 0-100 (nécessaire pour aligner les zones).
- Zones de fond (bandes horizontales, opacity ~0.13): INTENSE vert ≥75, FACILE ambre 55-75, REPOS rouge <55, avec libellés i18n `dashboard.readinessZones.{rest,easy,intense}` FR/EN/ES et lignes de séparation à 55/75.
- Info-bulle au tap: cibles transparentes r=7 par point (data-testid readiness-point-{i}); tap affiche tooltip (score /100 + date MM-DD) + repère vertical vert. Re-tap ferme.
- Note: échelle 0-100 => courbe moins "étirée" que min-max mais lecture correcte grâce aux zones (design type Garmin/Whoop).
- Vérifié: frontend "Compiled successfully" + screenshot (bandes visibles, tooltip "90/100 · 07-17"). data-testid: readiness-chart, readiness-tooltip, readiness-point-{i}.

## 2026-08-04 — Pull sauvegarde/main (PR#78)
- `git fetch` + `git merge --ff-only sauvegarde/main` : FAST-FORWARD propre `b128c34 → b11b510`. Aucun conflit (mon commit b128c34 = base du remote).
- PR#78 (#78 runindex-history-7j-training-load) modifie UNIQUEMENT `backend/garmin/insights.py`: pré-calcule `_daily_load` par jour et met `history.training_load = charge d'activité du jour` au lieu de l'ACWR/jour. Conserve mon historique 30 jours et mes `run_readiness`. Champ non utilisé par mon UI → aucun impact visuel.
- Protégés intacts: backend/.env, frontend/.env, /app/memory (14 fichiers). Backup /tmp/pull_backup.
- Vérifié: backend health 200, compute_run_index OK (9 pts, run_readiness variés, training_load = charge réelle jour). Mes features readiness (tuiles/zones/tooltip/30j/TSB) préservées.

## 2026-08-04 — Pull sauvegarde/main (PR#79)
- Local avait divergé de 1 commit (fc92aa3, MAJ PRD.md) ; remote +2 commits (PR#79 remove-next-workout-faux-contenu). `git merge --no-edit sauvegarde/main` → merge propre (ort), AUCUN conflit (fichiers disjoints). HEAD=42f3b81.
- PR#79 retire `next_workout` (faux contenu) de insights.py + server.py, ajuste 2 tests, ajoute NEXT_WORKOUT_REMOVAL_PR_REPORT.md. N'impacte pas mon UI readiness.
- Protégés intacts (backend/.env, frontend/.env, memory). Vérifié: backend 200, compute_run_index OK (next_workout absent), frontend compiled.

## 2026-08-05 — PR N2: cleanup Dashboard (code mort chart/mock)
- Frontend only (Dashboard.jsx). Retirés: import recharts complet (inutilisé dans ce fichier), `TrendTooltip`, `MiniLineChart`, mock `chartData=[45,48,...]`. Tous prouvés MORTS (1 occurrence chacun, aucun JSX).
- Conservés intacts: ReadinessChart + garde `>= 2 points` + `history.run_readiness`, tiles, recommendation, zones 55/75, tooltip, i18n readinessZones/monthlyReadiness. recharts reste (utilisé par Progress.jsx, hors périmètre).
- Vérifié: grep sans résidu, `yarn build` PASS (14s), screenshot dashboard OK (courbe + zones). Backend non modifié. Rapport: /app/DASHBOARD_CHART_CLEANUP_PR_REPORT.md → READY TO MERGE.

## 2026-08-05 — PR N3: retrait adaptateur mort adapt_workout_advanced
- Backend only. `adapt_workout_advanced` prouvé MORT (import server.py:1 + def, aucun appel). Conclusion A.
- Retiré: import ligne 1 de server.py; supprimé backend/services/adaptation_engine.py (module orphelin); corrigé 2 mentions doc obsolètes dans demo_mode.py (commentaires seuls).
- Conservé: adapt_session_to_readiness (unique adaptateur vivant, appelé par /api/training/today server.py:3632). Non touché.
- Vérifié: grep 0 occurrence adapt_workout_advanced/adaptation_engine, backend startup OK, GET /api/training/today → 200 (adaptive_session/adaptation_applied/adaptation_reason présents). Frontend intact. Rapport: /app/ADAPT_WORKOUT_ADVANCED_REMOVAL_PR_REPORT.md → READY TO MERGE.

## 2026-08-08 — Benchmark Garmin réel (avant refonte Onboarding) — AUDIT READ-ONLY
- Aucune modif code applicatif, aucune donnée réelle touchée. Persistance mesurée sur base isolée jetable `<DB_NAME>_bench_tmp` (droppée). Data réelle user da8505ef intacte (143 activités / 31 daily / 143 workouts).
- Pipeline: /connect & /sync NON-BLOQUANTS (Redis queue → sync_worker hors-process → gccli → upsert Mongo → compute_run_index). RunIndex+Readiness = même fonction.
- Mesures (session WARM): session 11ms · activités fetch 161–588ms (143, ~3 pages) · **daily metrics days=30 = 12.3s / 90 appels gccli (3/jour) = GOULOT ~95%** · persist 54+19ms · compute RunIndex+Readiness 4.7ms · enqueue Redis 3ms.
- Total deep sync ≈ 13s (dominé par daily metrics). Incrémental < 1s. HRV absente (device). VFC/HRV ❌, sommeil ✅ RHR ✅.
- Cold onboarding NON TESTÉ (login à froid non mesurable sans mot de passe). Rapport: /app/GARMIN_ONBOARDING_BENCHMARK.md · JSON brut: /tmp/garmin_benchmark_result.json.

## 2026-06 — Pull copilot/dev — PR #166 (fermeture des test-drifts PR165)
- Fetch + merge `sauvegarde/copilot/dev` (81eaa2d→dcd3e77). Merge ORT propre, 0 conflit. `.env` intacts, rapports locaux + PRD préservés.
- PR #166 = ferme les 3 test-drifts introduits par PR#165 (aucun code runtime/frontend touché) :
  - `test_pr155_week_plan_no_legacy.py` : ne patche plus `server.generate_cycle_week` (symbole retiré du chemin par #165).
  - `test_pr156_no_unvalidated_tss_generate_cycle_week.py::test_distances_and_types_preserved` : assouplit l'assertion (accepte sémantique V2 duration-based, None/pas de km inventés).
  - `test_pr162_week_plan_observed_weekly_km.py` : réaligné sur WeeklyPlan V2.
- Validation RUNTIME (agent-tested) : smoke 7/7=200 (today, plan, metrics, run-index, dashboard, week-plan, full-cycle). Suites cœur Training V2 = 493 passed. Suites PR (test_pr*.py) = 158 passed. Les 3 tests corrigés = 23 passed.
- Suite globale : échecs env/legacy historiques persistants (Redis/SSE/checks env REACT_APP_BACKEND_URL) NON liés à #166 — cf. règle « pytest global ≠ preuve release ».
- Aucun redémarrage requis (PR166 = tests uniquement). Statut : agent-tested, non user-confirmed. Frontend inchangé depuis #165.

## 2026-06 — Pull copilot/dev — PR #167 (endpoint natif V2 GET /training/v2/week)
- Fetch + merge `sauvegarde/copilot/dev` (dcd3e77→af33c9f). Merge ORT propre, 0 conflit. `.env` intacts, rapports locaux + PRD préservés.
- PR #167 = nouvel endpoint natif V2 `GET /api/training/v2/week` :
  - Nouveau `backend/training_v2/training_week_response.py` (response models) + `backend/server.py` (+152, route + response_model), `access_control.py` (+1).
  - Sémantique V2 stricte : `target_km`/`distance_km`/`estimated_tss` = null quand basis=duration (UNKNOWN ≠ ZERO) ; `target_time_minutes→seconds`, horloge unique `now_utc`.
  - Aucun changement frontend/worker.
- Validation RUNTIME (agent-tested) : backend redémarré. Smoke **8/8 = 200** (dont nouveau `/training/v2/week` renvoyant goal/state/weekly_target/week+sessions avec null corrects). Tests PR167 = **54 passed**. Régression suites PR (test_pr*.py) = **212 passed**.
- Statut : agent-tested, non user-confirmed.

## 2026-06 — Pull copilot/dev — PR #173 (écran frontend Training V2)
- Fetch + merge `sauvegarde/copilot/dev` (af33c9f→3c1e605). Merge ORT propre, 0 conflit. `.env` intacts, PRD/rapports locaux préservés.
- PR #173 = nouvel écran frontend natif V2, consomme `GET /training/v2/week` (#167) :
  - Nouveau `frontend/src/pages/TrainingPlanV2.jsx` (+297), route `/training-v2` dans `App.js` (protégée), i18n `lib/i18n.js` (+81 clés trainingV2), test `__tests__/training-v2-page.test.jsx`.
  - Auth via interceptor axios global (`index.js`, localStorage `access_token`). Paywall FREE. UnitContext (km/miles). Sémantique V2 : distance/TSS/duration null masqués ; rest = 0 TSS structurel préservé ; pas de conversion UNKNOWN→0.
- Validation (agent-tested) : frontend redémarré, compile OK. **Screenshot authentifié PASS** (page rend Objective/State/Weekly target + grille 7 jours). Jest **10 passed**. Smoke backend V2 200. Régression suites PR = **212 passed**.
- Statut : agent-tested, non user-confirmed.

## 2026-06 — Pull copilot/dev — PR #175 (endpoint natif V2 GET /training/v2/cycle)
- Fetch + merge `sauvegarde/copilot/dev` (09a6eec→67b028d). Merge ORT propre, 0 conflit. `.env` intacts, PRD/rapports locaux préservés.
- PR #175 = nouvel endpoint natif V2 `GET /api/training/v2/cycle` (calendrier de cycle) :
  - Nouveau `backend/training_v2/training_cycle_response.py` (+465), route `server.py` (+177), `access_control.py` (+1). Mêmes sources canoniques que /training/v2/week.
- Validation RUNTIME (agent-tested) : backend redémarré. Smoke **6/6 = 200** (dont /training/v2/cycle → 12 semaines, phase base, current_week=4 is_current, days_to_race null, mode continuous). Régression suites PR = **254 passed, 1 failed**.
  - ⚠️ FAIL = `test_pr175::test_20b_endpoint_trial_http200` : attend 200 pour un cycle mocké goal=`MAINTENANCE`, endpoint renvoie 400 (gate `GOAL_CONFIG` sans MAINTENANCE). MAINTENANCE n'est JAMAIS écrit dans training_cycles.goal en runtime → état non atteignable. Incohérence interne (le `_GOAL_MAP` inline liste MAINTENANCE mais le gate GOAL_CONFIG le rejette). **Runtime intact** ; correctif à router upstream.
- Statut : agent-tested, non user-confirmed.

## Bugs ouverts (à router upstream)
- **PR#174 i18n** : clés `weeklyTarget/weeklyDone/minutes` placées dans `onboarding` au lieu de `dashboard` pour EN et FR (ES OK) → Dashboard EN/FR affiche `DASHBOARD.WEEKLYTARGET` / `105 dashboard.minutes`. Reproduit en screenshot authentifié. Décision utilisateur (fix local vs PR upstream) en attente.
- **PR#175** : incohérence GOAL_CONFIG vs _GOAL_MAP sur MAINTENANCE (voir ci-dessus). Non bloquant runtime.

## 2026-06 — Pull copilot/dev — PR #176 (hotfix post-175 : i18n dashboard + MAINTENANCE)
- Fetch + merge `sauvegarde/copilot/dev` (67b028d→7047ca2). Merge ORT propre, 0 conflit. `.env` intacts, PRD/rapports locaux préservés.
- PR #176 corrige les 2 items ouverts que j'avais reportés :
  - **i18n #174** : clés `weeklyTarget/weeklyDone/minutes` déplacées de `onboarding` vers `dashboard` en EN et FR. Vérifié (node) : en/fr/es.dashboard.weeklyTarget/minutes/weeklyDone tous résolus. Screenshot authentifié : Dashboard affiche « WEEKLY TARGET » + « 105 min » (plus de clés brutes).
  - **#175 MAINTENANCE** : retrait de MAINTENANCE du `_GOAL_MAP` du cycle endpoint (aligné sur gate GOAL_CONFIG) + fix du mock `test_20b`.
- Validation (agent-tested) : backend + frontend redémarrés. Smoke **6/6 = 200** (today, v2/week, v2/cycle, week-plan, run-index, dashboard). Régression suites PR = **255 passed, 0 failed**.
- ✅ Les 2 bugs ouverts sont RÉSOLUS upstream. Statut : agent-tested + smoke visuel vérifié ; non user-confirmed.

## 2026-06 — Pull copilot/dev — PR #177 (route canonique /training → Training V2 + Cycle V2)
- Fetch + merge `sauvegarde/copilot/dev` (7047ca2→72d9bc4). Merge ORT propre, 0 conflit. `.env` intacts, PRD/rapports préservés. Frontend redémarré.
- PR #177 = `/training` pointe désormais vers TrainingPlanV2 (Week V2 + section Cycle V2), `/training-v2` → Navigate("/training") (redirect), import legacy TrainingPlan retiré. TrainingPlanV2 consomme /training/v2/week ET /training/v2/cycle. Nouvelles clés i18n cycle (cycleModes, phases).
- SMOKE FRONTEND (agent-tested) :
  - /training : écran Training V2 visible, Week V2 (Objectif/État/Cible), Cycle V2 (Mode/Statut/Début/Fin/Semaine 4/12 + liste 12 semaines avec phases Base/Build). Semaine courante = 1 seule (Week 4 CURRENT) == current_week=4.
  - Aucune prescription future dans le calendrier cycle (pas de km/durée/TSS/allure/zones/intensité/séances).
  - Mode label EN "Continuous training" / FR "Entraînement continu" — pas de "Non disponible" ni clé brute.
  - /training-v2 → redirige vers /training. JS errors = 0.
  - Réseau depuis /training : uniquement /api/training/v2/week (200) + /api/training/v2/cycle (200). AUCUN appel legacy (plan/full-cycle/metrics/refresh).
  - FREE paywall : couvert par test jest (pas de compte FREE runtime ; mock runtime interdit). Jest training-v2-page = 17 passed.
- Statut : agent-tested + smoke visuel EN/FR vérifié ; non user-confirmed.

## 2026-06 — Pull copilot/dev — PR #178 + #179 + #180 (Run/Readiness V2 dashboard, RunIndex→DomainActivity, hotfix circular import)
- Fetch + merge en 2 temps : #178+#179 (56412ed), puis #180 hotfix (4c134bc). Merges ORT propres, 0 conflit. `.env` intacts, PRD/rapports préservés.
- **PR #179** = migration source RunIndex vers `garmin_activities → DomainActivity` (engine/run_index_engine.py, garmin/service.py, services/run_index_history.py, server.py). 
- **PR #178** = consolidation Dashboard Run Readiness V2 : statut inconnu → "gray" par défaut (unknown≠green), gray → pas d'icône rouge, retrait code legacy mort (Dashboard.jsx).
- 🔴 **BLOCKER post-#179 (résolu par #180)** : import circulaire déterministe. `garmin/service.py:26 from .backfill import backfill_user` + `garmin/backfill.py:18 from .service import activity_to_workout` (défini ligne 182) → backend + garmin-sync/event workers KO (app down). PR #180 = import paresseux de `activity_to_workout` dans `backfill_user` (backfill.py:25) → cycle cassé. `import garmin.service` = OK.
- Validation (agent-tested) : backend + frontend + 4 workers redémarrés, tous RUNNING. Smoke **7/7 = 200** (run-index, dashboard, today, v2/week, v2/cycle, week-plan, full-cycle). sync-worker tourne normalement. Tests PR179 domain source = **34 passed**. Régression suites PR = **255 passed**. Dashboard rend, **0 erreur JS**, tous appels API 200.
- ⚠️ Limitation connue : `dashboard-run-readiness-v2.test.jsx` (tests 16-22 de #178) ne s'exécute pas en jest local (résolution radix `.tsx` — problème env pré-existant depuis #174, tout test important Dashboard.jsx échoue). NON-régression : le runtime Dashboard est validé par screenshot + endpoints. Les couleurs de statut exactes (gray/red) pour un compte avec données n'ont pas pu être vérifiées visuellement (le compte test JWT n'a pas de données Garmin).
- Statut : agent-tested ; non user-confirmed.
