# Micro-validation runtime RÉELLE — Readiness CAUTION / LOW sur données historiques (post-PR #144)

Date: 2026-08-19 · Mode: **LECTURE SEULE** · Aucun code/Mongo/plan/planning/activité/DailyMetric/feedback modifié · Date système inchangée · Aucun monkeypatch · Aucune PR.
Compte réel: `da8505ef-…`. Toutes les bandes proviennent du **vrai calcul** Readiness V2 (aucune injection).

## 1) État
- **HEAD** = `97d6f1f` (contient PR#143 `0b6b6a0` + PR#144 `09a256f`). #143 ✓ · #144 ✓ · BUG-137-01 résolu · #132 actif.
- backend RUNNING · garmin-sync-worker RUNNING.

## 2) Période historique auditée
- Fenêtre exploitable = plage des daily metrics réels : **2026-07-05 → 2026-08-17** (43 jours exploitables).
- Activités réelles : 147 (2024-11-23 → 2026-08-18).
- Pour chaque date J : reconstruction avec `reference_date=J` et **filtrage strict** metrics `date ≤ J` (30 plus récents) + activités `start_time ≤ J`. Aucune donnée future dans TrainingLoad / TrainingHistory / Readiness / RecentTrainingResponse.

## 3) Distribution réelle des bandes (43 jours)
| Band | Occurrences |
|---|---|
| FAVORABLE | 37 |
| CAUTION | **6** (2026-07-19, 08-03, 08-04, 08-09, 08-15, 08-16) |
| LOW | **0** |
| VERY_LOW | 0 |
| UNAVAILABLE | 0 |

→ CAUTION réellement présent · **LOW absent** des données réelles sur toute la fenêtre.

---

## CAS CAUTION RÉEL — 2026-08-16 (dimanche)

### 4) Date retenue
- J = **2026-08-16** (dimanche → jour actif du plan V2 ; CAUTION réel, score 62.5). CAUTION dimanches disponibles : 07-19, 08-09, 08-16 ; retenu le plus récent (historique le plus riche).

### 5) Données Readiness (réelles, J=2026-08-16)
- Inputs : resting_hr=`53` · hrv=`None` (absent — non inventé) · sleep_hours=`9.1` · sleep_score=`None` (source Garmin absente — non inventé) · body_battery=`None` · stress=`None`.
- TrainingLoad ≤ J : acute_7d=`165.96` · chronic_weekly=`60.87` · ACWR=`2.727` · status=`high` · confidence=`high` (calculé, aucun fallback).
- **ReadinessResult** : score=`62.5` · confidence=`NORMAL` · sufficiency_level=`SUFFICIENT` · reasons=`(missing_hrv)`.
- **ReadinessDecision** : band=`CAUTION` · score=`62.5` · reason_codes=`(READINESS_CAUTION)`. → CAUTION issu du vrai calcul (55 ≤ 62.5 < 75).

### 6) Séance active (plan V2, dimanche)
- type=`long_run`→prescription `long_easy` · distance_km=`13.3` · duration_minutes=`None` · intensity_class=`low` · reason_codes=`(PLAN_V2)`.

### 7) RecentTrainingResponse historique (activités ≤ J)
- response_status=`sufficient` · available_running=`5` · selected_running=`5` · observed_runs=`5` · hr_coverage_count=`5` · average_hr_recent=`134.4`.
- trends : volume=`increasing` · frequency=`increasing` · long_run=`increasing` · cardiac_efficiency=`stable` · intensity_exposure=`increasing`.
- Aucune activité future (max activité ≤ J = 2026-08-15).

### 8) DailyAdaptation réelle
- action=`SHORTEN`
- reason_codes=`[READINESS_CAUTION, TRAINING_LOAD_HIGH, LONG_EASY_PROTECTED, WORKOUT_SHORTENED, INTENSITY_NOT_INCREASED]`
- original: long_easy · 13.3 km · None · low → adapté: long_easy · **9.3 km** · None · low
- SHORTEN_FACTOR=0.70 : 13.3 × 0.70 = 9.31 → **9.3 km** ✓ (distance-only : SHORTEN via distance, durée None conservée).
- *Note : ACWR réel 2.727 → status=high → `TRAINING_LOAD_HIGH` renforce la réduction en plus de READINESS_CAUTION. Cohérent.*

---

## CAS LOW RÉEL
- **NO HISTORICAL REAL CASE FOUND.**
- Période auditée : 2026-07-05 → 2026-08-17 (43 jours exploitables).
- Occurrences LOW réelles : **0** (distribution : FAVORABLE=37, CAUTION=6, LOW=0, VERY_LOW=0, UNAVAILABLE=0).
- Aucune bande LOW fabriquée. La bande LOW a déjà été validée de manière déterministe en mémoire (rapport LOW/CAUTION/VERY_LOW post-#144) mais reste **non reproductible sur les données Garmin réelles disponibles**.

---

## 14) Preuve d'absence de données futures (J=2026-08-16)
- metrics total=43 → **≤ J = 42** (1 exclu : 2026-08-17) · metrics > J = 1.
- activités total=147 → **≤ J = 146** (1 exclue : 2026-08-18) · activités > J = 1.
- max metric ≤ J = 2026-08-16 · max activité ≤ J = 2026-08-15. → aucune contamination future.

## 15) Monotonicité (CAUTION réel)
- distance 13.3 → 9.3 (↓) · durée None → None · intensité low → low (inchangée). Séance jamais durcie. Aucun MOVE/UPGRADE/CATCH_UP/compensation.

## 16) Absence legacy
- Chemin : DomainActivity → TrainingLoad V2 → ReadinessResult V2 (garmin.readiness_adapter) → ReadinessDecision V2 → RecentTrainingResponse V2 → DailyAdaptation V2.
- `daily_adaptation.py` pure V2. Aucun `training_engine`, `adapt_session_to_readiness`, `fatigue_ratio`, `fatigue_status`, `fatigue_physio`.

## None semantics
- Aucun `sleep_score` inventé (None conservé, source absente) · hrv=None conservé · aucun TSS=0 · aucun ACWR=1 (ACWR réel 2.727) · aucun score/bande fabriqués. `None != 0` respecté.

---

# VERDICTS

- **CAUTION REAL = PASS** — bande CAUTION issue de données réelles historiques (2026-08-16, score 62.5), aucune donnée future, vraie séance active (long_easy 13.3 km), RecentTrainingResponse historique réel (sufficient, 5 runs), DailyAdaptation exécutée (SHORTEN → 9.3 km), séance jamais durcie, aucune compensation, aucun legacy.
- **LOW REAL = NOT FOUND** — 0 occurrence sur 43 jours réels exploitables ; non fabriqué (LOW déjà validé déterministe en mémoire, non reproductible sur données réelles disponibles).

## VERDICT GLOBAL = PASS (CAUTION) + LOW NON REPRODUCTIBLE SUR DONNÉES RÉELLES
Les 8 critères PASS CAUTION sont réunis. La dette CAUTION réelle est levée. La dette LOW réelle ne peut être levée faute d'occurrence réelle (recommandation : re-scanner ultérieurement lorsque de nouvelles données Garmin seront synchronisées, ou conserver la validation déterministe en mémoire comme couverture).
