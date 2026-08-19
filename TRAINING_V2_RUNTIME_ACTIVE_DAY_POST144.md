# Micro-validation runtime — SÉANCE ACTIVE post-PR #144 (`/training/today`)

Date: 2026-08-19 · Mode: **LECTURE SEULE** · Aucun code modifié · Aucune PR · Aucune donnée Mongo/plan/Readiness/feedback/activité modifiée · Planning NON modifié · Aucune séance forcée.
Compte réel: `da8505ef-…` (mallegolbrieg@…) · Auth: JWT read-only.

## 1) État
- **HEAD** = `857f583` (contient PR#143 `0b6b6a0` + PR#144 `09a256f`/`8255c6f`).
- **#143 présente** ✓ · **#144 présente** ✓ (BUG-137-01 résolu).
- backend RUNNING · garmin-sync-worker RUNNING.

## 2) Séance active testée
Aujourd'hui (2026-08-19, mercredi) = repos. Plan V2 réel (semaine 2, phase base, MARATHON) : une seule séance non-rest = **dimanche**. Prochaine date active = **2026-08-23 (dimanche)**.
- date=2026-08-23 · type=`long_run` · details=`13.3 km • allure 7:16-6:44` · intensity=`easy` · distance=13.3 km · estimated_tss=None.
- Reproduction déterministe de la chaîne métier en lecture seule avec `reference_date=2026-08-23` (aucune écriture, planning inchangé).

## 3) Chemin runtime reproduit (fonctions identiques à `/training/today`)
plan V2 → `runtime_session_to_prescription` → `build_training_load` → `build_readiness_v2_from_garmin_data` → `build_readiness_decision` → `build_recent_training_response` → `build_daily_adaptation`.

**Planned prescription** : workout_type=`long_easy` · duration_minutes=`None` · distance_km=`13.3` · intensity_class=`low` · reason_codes=`(PLAN_V2)` · estimated_tss non porté par WorkoutPrescription (None runtime).

**TrainingLoad** (ref 2026-08-23) : acute_7d=`44.02` min · chronic_weekly=`71.87` min · ACWR=`0.612` · confidence=`high` · load_status=None. Valeur réelle calculée (aucun fallback). *Note transparence : la reference_date étant future, les fenêtres se décalent — ACWR=0.612 ici vs 2.538 as-of 2026-08-18 — calcul déterministe sur les données réelles disponibles (≤ 2026-08-18), pas une valeur inventée.*

**ReadinessResult** : score=`100.0` · confidence=`NORMAL` · sufficiency_level=`SUFFICIENT`.

**ReadinessDecision** : band=`FAVORABLE` · score=`100.0` · reason_codes=`(READINESS_FAVORABLE)`.

**RecentTrainingResponse (#132)** : response_status=`sufficient` · available_running=`6` · selected_running=`6` · observed_runs=`6` · hr_coverage_count=`6` · average_hr_recent=`135.0` · trends: volume=`increasing`, frequency=`increasing`, long_run=`increasing`, cardiac_efficiency=`stable`, intensity_exposure=`increasing`. → **signal #132 réellement disponible et exploitable** (contraste net vs pré-#144 où tout était unavailable/unknown).

## 4) DailyAdaptation
- action=`KEEP`
- reason_codes=`(READINESS_FAVORABLE, PLAN_KEPT, INTENSITY_NOT_INCREASED)`
- adapted_workout : type=`long_easy` · duration_minutes=`None` · distance_km=`13.3` · intensity_class=`low`
- Action ∈ {KEEP, EASY_DOWNGRADE, SHORTEN, REST} ✓. Aucun MOVE/INCREASE/UPGRADE/HARDEN/CATCH_UP.

## 5) Monotonicité (SHORTEN_FACTOR=0.70)
- KEEP → séance **structurellement identique** : distance 13.3→13.3 · durée None→None · intensité low→low. Aucune augmentation. ✓
- (SHORTEN/EASY_DOWNGRADE non déclenchés car readiness FAVORABLE + ACWR<1 ne justifient aucune réduction — comportement attendu, couvert par tests auto pour les cas de réduction.)

## 6) Rôle du RecentTrainingResponse #132
- Signal `sufficient` disponible et **consommé** par `build_daily_adaptation` (passé en argument `recent_response`), sans crash.
- Conformément au critère : signal disponible et consommé ≠ action forcément différente. Ici readiness/TrainingLoad ne justifient pas de réduction → KEEP légitime malgré recent_response=sufficient. reason_code `INTENSITY_NOT_INCREASED` prouve la garde anti-upgrade.

## 7) `/training/today`
- Date testée (2026-08-23) ≠ aujourd'hui → chaîne métier reproduite en lecture seule avec la reference_date (aucun appel écrivant). L'endpoint live `/api/training/today` (aujourd'hui, jour de repos) reste 200, KEEP/[PLANNED_REST_DAY, PLAN_KEPT], readiness FAVORABLE — cohérent.
- Comparaison prévu/adapté : identique (KEEP). readiness=FAVORABLE. adaptation_action=KEEP. reason_codes=(READINESS_FAVORABLE, PLAN_KEPT, INTENSITY_NOT_INCREASED).

## 8) Non-régression legacy
- **Aucun** `adapt_session_to_readiness` dans le chemin `/training/today` (seul un commentaire documente son absence).
- **Aucune** décision legacy `training_engine` dans le chemin daily · `daily_adaptation.py` sans import legacy.
- Bloc `fatigue` = run_readiness (=readiness_decision.score), recommendation, recommendation_color, data_source — **aucun** `fatigue_ratio` / `fatigue_status` / `fatigue_physio`.
- Aucun `TSS=0` inventé (estimated_tss=None) · aucun `ACWR=1` inventé (0.612/2.538 calculés) · None≠0 (ctl/atl/tsb=null ailleurs).
- Compat : FAVORABLE → (RUN HARD, green) — champ frontend uniquement, action=KEEP → séance NON durcie.

---

## VERDICT : **PASS**

Les 8 critères sont réunis :
1. Une vraie séance active (`long_run` 13.3 km, low) est évaluée. ✓
2. RecentTrainingResponse est disponible (`sufficient`, 6 runs, trends peuplés). ✓
3. DailyAdaptation consomme le signal sans crash. ✓
4. action = `KEEP` ∈ {KEEP, EASY_DOWNGRADE, SHORTEN, REST}. ✓
5. Séance adaptée jamais plus dure (identique). ✓
6. Aucun catch-up / upgrade / increase (`INTENSITY_NOT_INCREASED`). ✓
7. Aucune dépendance legacy quotidienne réintroduite. ✓
8. Aucun fallback physiologique fictif (readiness/ACWR calculés, TSS/ctl/atl/tsb=null propagés). ✓

Note: la reference_date future (2026-08-23) est une reproduction déterministe en lecture seule imposée par le fait qu'aujourd'hui est un jour de repos ; les valeurs de charge/readiness reflètent les données réelles disponibles (≤ 2026-08-18) évaluées à cette date, sans injection ni fallback.
