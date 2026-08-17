# Validation runtime globale — Training Engine V2 (post-PR #135)

Date: 2026-08-17 · Mode: **AUDIT LECTURE SEULE** · Aucun code modifié · Aucune PR · Aucune injection synthétique DB
Compte réel audité: `da8505ef-…` (mallegolbrieg@…, admin) — 146 activités Garmin, 41 daily metrics.
Auth audit: JWT read-only généré via `auth.jwt_utils.create_access_token` (aucune mutation).

> Effet de bord runtime transparent: appeler `GET /api/training/plan` upsert `training_cycles.current_plan`
> pour le cycle **déjà existant** (comportement normal du endpoint, lignes coach_service.py 873+).
> Aucune activité Garmin, objectif, race date, état ou métrique n'a été modifié.

---

## 1) État Git & PRs — GO
- HEAD local `5807c8a` · `sauvegarde/main` `6ef49f8` · local **+14 / -0** → contient tout l'amont + hotfix local. Aucun pull nécessaire.
- SHA merges: **#132=`beee570`**, **#133=`b2f1ead`**, **#134=`8564060`**, **#135=`6ef49f8`**.
- Roadmap `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md` lu (contrats #133/#134/#135, ordre canonique #136→#139).

## 2) Startup backend/worker/health — GO
- Supervisor: backend + 4 workers Garmin + mongodb + redis = RUNNING.
- Hotfix **Python 3.11 préservé** (`_cache_payload` extrait → `_stable_hash(_cache_payload)`, coach_service.py 595-607) · `py_compile` OK.
- `/api/run-index`, `/api/training/metrics`, `/api/dashboard`, `/api/training/today`, `/api/training/plan` = **200** (mock=false, source=garmin).

## 3) TrainingHistory 7/30/90 j — GO
- 7d=2 act / 20.74 km · 30d=5 act / 35.82 km · 90d=14 act / 156.19 km. Concorde `debug_volume` (km_7=20.7, km_28=35.8) et `recent_response.observed_distance_km=35.82`.

## 4) TrainingLoad V2 + ACWR (recalcul indépendant) — GO
- Formule V2: acute J-6→J / (chronic J-27→J ÷ 4), charge = **minutes**.
- Recalcul indépendant: acute=138.0 min · chronic_weekly=60.75 min · **ACWR=2.272**.
- Endpoints: run-index/metrics/dashboard=2.273, plan.context=2.272 → **écart d'arrondi seul** ✓.
- `ctl=null · atl=null · tsb=null` (indisponibles, propagés sans faux positif) ✓.

## 5) RunnerProfile / TrainingState — GO
- Pipeline branché (build_runner_profile → build_training_state). `continuity_state=normal` cohérent (historique régulier).

## 6) PlanGoal — GO
- Réel: MARATHON. En mémoire: maintenance (no race/km) OK · ultra 80 km accepté (`ULTRA_MIN_DISTANCE_KM=42.195`).

## 7) Periodization / WeeklyTarget / cap préférence — GO
- Phase `base`. WeeklyTarget proposé target_km 13.1 / sessions 1. `_apply_sessions_preference_cap` appliqué avant reconciliation.

## 8) #132 RecentTrainingResponse — GO
- `window_days=28` (global) · `observed_runs_per_week=1.25` · selected vs available (sélection bornée).
- Trends présents: cardiac_efficiency_trend, volume_trend, long_run_trend, frequency_pattern, intensity_exposure_trend.

## 9) #134 WeeklyReconciliation — GO
- `action=REDUCE_VOLUME` : original target_km 13.1 → réconcilié **11.1** (floor 85% ≈ 11.135).
- `target_sessions` inchangé 1→1 (pas de trigger fréquence : 1.25 ≥ target×0.75=0.75).
- `allow_intensity` inchangé, `continuity_state` inchangé, aucune augmentation structurelle. Invariants respectés.

## 10) WorkoutGenerator / long run — GO
- 1 séance non-rest (`long_run` dimanche, 11.1 km), reste `rest`. Cohérent bas volume + ACWR danger.

## 11) Endpoints #135 réellement branchés — GO
- 5/5 endpoints 200, payload runtime V2.
- **`sessions_per_week` (top-level) == `reconciled_target.target_sessions` == 1** (coach_service.py:843) ✓.
- `estimated_tss=null` (chaque séance) · `total_tss=null` · `planned_load=null` — TSS unavailable **sans casser les consumers** (dashboard/today/plan tous 200) ✓.

## 12) Absence de fallback legacy — GO
- `grep training_engine` sur coach_service.py + api/ = **NONE**. `generate_dynamic_training_plan` = pipeline 100% V2 (lignes 692-812).

## 13) Rôle de `generate_cycle_week` — GO
- Importé depuis `llm_coach` (enrichissement LLM narratif), **non structurel**, hors chemin de génération du plan.

## 14) #133 (ReadinessDecision / DailyAdaptation) — GO (état attendu)
- **NON branché runtime** (couche pure) : aucun import dans server.py/coach_service/api. Conforme à la roadmap (branchement prévu en #136).
- `/training/today` utilise encore `adapt_session_to_readiness` (legacy daily) — attendu avant #136.
- Validation en mémoire uniquement: `build_readiness_decision(None) → band=UNAVAILABLE, conf=NONE, suff=INSUFFICIENT` ✓ (contrat respecté).

## 15) /training/today + frontend — GO (avec observation)
- `/training/today`=200, `planned_session.estimated_tss=null`, adaptation legacy sans crash.
- Frontend **up** (écran login RunIndex rend proprement, aucun crash JS). Screenshot authed non atteignable : injection token via l'outil screenshot **non fiable** (l'outil navigue avant le setItem — dead-end connu). UI authed validée précédemment (test_reports/iteration_28).

## 16) Suites automatisées ciblées — GO
- **PR132+PR133+PR134+PR135+readiness_decision = 172 passed / 0 failed.**
- Suites modules V2 (history/load/target/generator/periodization/profile/state/goal/domain) = **530 passed**, 5 failed / 3 errors, **tous hors périmètre PR132-135** :
  - `test_training_state_pr04` (2) : calibration `continuity_confidence` (89j→high vs medium) et NORMAL↔REPRISE_EXIT (single-run 27j→normal). `training_state.py` **non modifié par PR132-135** (daté Aug 7) → item doctrine pré-existant.
  - `test_plan_goal_pr05::test_27_no_legacy_imports` : flakiness d'isolation pytest-xdist (passe en isolation).
  - `test_sse` / `test_subscription_trial` : erreurs environnementales connues (ImportError / REACT_APP_BACKEND_URL).
- `test_reprise_pr77.py` : **7 failed — INFO COMPATIBILITÉ SEULEMENT** (fixtures legacy non domain-adaptées + doctrine `reprise_exit` sans intensité imposée). **Non retenu comme critère GO/NO-GO** (ajustement utilisateur #3).

---

# VERDICT FINAL

## GLOBAL = GO #136

**Justification** : la chaîne runtime Garmin/Mongo → DomainActivity → TrainingHistory → TrainingLoad → RunnerProfile → TrainingState → PlanGoal → Periodization → WeeklyTarget → RecentTrainingResponse (#132) → WeeklyReconciliation (#134) → WorkoutGenerator → runtime plan (#135) est **entièrement branchée et cohérente en conditions réelles** : ACWR recalculé indépendamment (arrondi seul), invariants #132/#134 respectés, TSS/CTL/ATL/TSB propagés `null` sans casser les consumers, `sessions_per_week == reconciled_target.target_sessions`, aucun fallback legacy (`training_engine` absent du chemin), et #133 correctement isolé en couche pure (branchement réservé à #136). 172/172 tests des briques #132-#135 passent. Les échecs résiduels sont soit hors périmètre (calibration training_state pré-existante), soit environnementaux, soit des fixtures legacy explicitement exclus du critère de release.

**Anomalies bloquantes** : aucune.

**Observations non bloquantes (aucune correction appliquée — audit lecture seule)** :
- OBS-1 : calibration `continuity_confidence` / NORMAL↔REPRISE_EXIT dans `training_state.py` — arbitrage doctrine à trancher (indépendant de #135).
- OBS-2 : hotfix Python 3.11 local de `coach_service.py` **à répercuter upstream** dans PR#135 (sinon re-cassera sur un autre environnement et entrera en conflit au prochain pull).
- OBS-3 : `test_reprise_pr77.py` reflète un changement de comportement V2 (reprise_exit sans intensité imposée) — décision produit, non un bug certain.
