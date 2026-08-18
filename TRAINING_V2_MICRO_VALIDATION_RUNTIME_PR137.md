# Micro-validation runtime post-merge PR #137 — `/training/today` → ReadinessDecision V2 + DailyAdaptation V2

Date: 2026-08-18 · Mode: **AUDIT RUNTIME LECTURE SEULE** · Aucun code modifié · Aucune PR · Aucune écriture DB · #138 non commencé.
Compte réel: `da8505ef-…` (mallegolbrieg@…, admin) — 147 garmin_activities, 146 workouts, 41 daily metrics.
Auth: JWT read-only via `auth.jwt_utils.create_access_token`.

---

## 1) État de départ
- **HEAD main testé**: `6241020` (contient PR#136 `9c0adcc` + PR#137 `a94adc4`). Local 17/0 vs `sauvegarde/main` → tout l'amont présent.
- **#136 MERGED** (`9c0adcc` hotfix Python 3.11) ✓ · **#137 MERGED** (`a94adc4` daily runtime migration) ✓
- **backend startup**: RUNNING (redémarré proprement).
- **worker startup**: garmin-sync-worker RUNNING (redémarré).
- `.env` backend/frontend intacts, fichiers protégés préservés.

## 2) Endpoints smoke — 5/5 HTTP 200
| Endpoint | HTTP |
|---|---|
| /api/training/today | 200 |
| /api/training/plan | 200 |
| /api/run-index | 200 |
| /api/training/metrics | 200 |
| /api/dashboard | 200 |

## 3) `/training/today` — chaîne runtime — CONFORME
Code `server.py:3579-3739` confirme exactement:
plan V2 (#135) → séance prévue → Mongo `garmin_activities` → `mongo_garmin_activities_to_domain()` → DomainActivity → `build_training_load` (V2) → `build_readiness_v2_from_garmin_data` (ReadinessResult V2) → `build_readiness_decision` (ReadinessDecision V2) → `build_recent_training_response` (#132) → `build_daily_adaptation` (DailyAdaptation V2) → payload.
- **Aucun** `adapt_session_to_readiness` dans ce chemin (proxy legacy retiré). **Aucun** `training_engine`. **Aucun** `fatigue_ratio`/`fatigue_status`/`fatigue_physio`.

## 4) Séance originale — CONFORME
- `/training/plan` mardi = `rest`. `/training/today` `planned_session` mardi = `rest`. **Match** ✓. Aucune séance fabriquée dans `/training/today`.

## 5) ReadinessResult → ReadinessDecision — CONFORME
`/training/today.readiness`: band=`FAVORABLE`, score=`80.5`, confidence=`NORMAL`, sufficiency_level=`SUFFICIENT`, available=`true`, data_source=`garmin`. Cohérent (score≥75→FAVORABLE). None≠0 respecté (mapping INSUFFICIENT→UNAVAILABLE présent dans le contrat).

## 6) DailyAdaptation — CONFORME (jour de repos)
- action=`KEEP` · applied=`false` · reason_codes=`[PLANNED_REST_DAY, PLAN_KEPT]` · adaptive_session=`null`.
- Action ∈ {KEEP, EASY_DOWNGRADE, SHORTEN, REST} ✓. Aucun MOVE/INCREASE/UPGRADE/HARDEN/CATCH_UP.

## 7) Monotonicité — N/A live (KEEP)
- KEEP → séance structurellement identique (rest 0min). Pas d'adaptation à mesurer.

## 8) Jour de repos — CONFORME
- Aujourd'hui (2026-08-18, mardi) est un jour de repos réel → KEEP + PLANNED_REST_DAY/PLAN_KEPT ✓. Aucune séance ajoutée.
- **SHORTEN/EASY_DOWNGRADE/REST actif NON reproductibles live aujourd'hui.** Planning NON modifié pour forcer un cas. Ces cas sont couverts par les tests automatisés (PR#133/#137).

## 9) Jour de séance active — non applicable aujourd'hui (repos).

## 10) Frontière Mongo → DomainActivity — CHAMPS PRÉSERVÉS
Échantillons réels (garmin_activities → DomainActivity):
| start_time | activity_type | distance_m | duration_s | avg_hr | max_hr | mod_min | vig_min | elev_m |
|---|---|---|---|---|---|---|---|---|
| 2026-08-18 05:11:14 | running | 7065.24 | 2641.25 | 138 | 159 | 17 | 17 | 35.07 |
| 2026-08-15 05:23:32 | running | 11974.44 | 4934.50 | 136 | 160 | 62 | 10 | 58.22 |
| 2026-08-13 05:05:02 | running | 8773.61 | 3367.47 | 142 | 168 | 14 | 33 | 36.52 |
- HR / intensité (mod/vig) / D+ **préservés avec valeurs réelles**, aucune valeur inventée. ✓

## 11) RecentTrainingResponse #132 — 🔴 DÉFAUT (voir BUG-137-01)
- Via `garmin_activities` (chemin réel /training/today): `response_status=unavailable`, available_running=**0**, selected=0, observed_runs=0, hr_coverage_count=0, average_hr_recent=None, tous les trends=`unknown`.
- Alors que 125 activités `running` existent dans le DomainActivity et que les champs HR/intensité/D+ sont préservés (§10).
- **Contradiction directe avec l'objectif déclaré de #137** (« prouver que average_hr, intensity minutes, elevation ne sont plus perdus à la frontière Mongo »): les champs sont présents sur DomainActivity, mais RecentTrainingResponse ne peut consommer aucune activité.

## 12) TrainingLoad / ACWR — CONFORME (arrondi seul)
- ACWR interne `/training/today` (build_training_load sur garmin_activities domain) = **2.538**.
- `/training/metrics` acwr = **2.538**. Écart = 0 (arrondi seul) ✓.
- ctl=None, atl=None, tsb=None ✓.

## 13) Fatigue compatibility — CONFORME
- Bloc `fatigue`: run_readiness=80.5, recommendation="RUN HARD", recommendation_color="green", data_source="garmin".
- **Absence confirmée** de `fatigue_ratio`, `fatigue_status`, `fatigue_physio` ✓ (projections V2 uniquement).

## 14) Recommendation compatibility — CONFORME
Mapping `BAND_TO_RECOMMENDATION` (daily_runtime_helpers.py:63):
- FAVORABLE→(RUN HARD, green) · CAUTION→(EASY RUN, yellow) · LOW→(EASY RUN, yellow) · VERY_LOW→(REST, red) · UNAVAILABLE→(UNAVAILABLE, gray). ✓
- FAVORABLE aujourd'hui → "RUN HARD"/green, MAIS action=KEEP → la séance (rest) n'est PAS durcie ✓ (champ de compat frontend uniquement).

## 15) TSS / métriques legacy — CONFORME
- `estimated_tss=null` (planned/adapted/plan) · `total_tss=null` · `planned_load=null`. Aucun 0 artificiel. ctl/atl/tsb=null ✓.

## 16) Logs — RAS (hors bruit inoffensif)
- Pendant les appels: aucun Traceback/ValidationError/NoneType dans le chemin /training/today, aucun `adapt_session_to_readiness`, `training_engine fallback`, `legacy fallback`, `fatigue_ratio/status/physio`.
- Aucun `[TrainingToday] Garmin V2 readiness build failed` → la construction readiness a réussi (l'exception handler n'a pas été déclenché; RecentTrainingResponse renvoie unavailable **sans exception**, en filtrant silencieusement toutes les activités).
- Seul bruit: warning passlib/bcrypt `__about__` (détection de version, inoffensif, non lié au chemin).

## 17) Tests ciblés
`test_daily_runtime_pr137 + test_mongo_garmin_boundary_pr137 + test_daily_adaptation_pr133 + test_training_v2_readiness_decision + test_training_response_pr132 + test_dynamic_plan_v2_pr135`:
- **total=202 · passed=202 · failed=0 · skipped=0.**
- ⚠️ Ces tests **ne détectent PAS BUG-137-01** car leurs fixtures utilisent des `start_time` de type datetime/ISO-"T", pas le format Mongo Garmin espace-séparé.

## 18) Frontend smoke — LIMITATION honnête
- Endpoints valides (5/5 200). Screenshot authed non atteignable (injection token via l'outil non fiable — dead-end connu). Non bloquant. Frontend up (login rend proprement, validé antérieurement iteration_28).

---

## BUG-137-01 (HIGH) — RecentTrainingResponse #132 silencieusement inopérant dans `/training/today`

- **endpoint**: `GET /api/training/today` (chemin runtime PR#137).
- **entrée réelle**: 147 `garmin_activities` du compte da8505ef (dont 125 `running`), start_time Mongo = `"2026-08-18 05:11:14"` (espace-séparé).
- **résultat obtenu**: `RecentTrainingResponse.response_status=unavailable`, available_running_activities=0, observed_runs=0, average_hr_recent=None, tous trends=`unknown`.
- **résultat attendu**: available_running ≈ 5-6 sur 28 j (comme le chemin #135 via `workouts` qui renvoie available_running=6, status=sufficient, hr_coverage=6), trends/HR exploités.
- **logs**: aucun (échec silencieux — filtrage renvoie liste vide sans exception).
- **sévérité**: **HIGH** — pas de crash (HTTP 200), readiness/ReadinessDecision/TrainingLoad/DailyAdaptation fonctionnent, mais le signal #132 est **mort** dans le chemin migré, ce qui **annule l'objectif de préservation à la frontière Mongo revendiqué par #137**. Impact fonctionnel: DailyAdaptation perd le renfort `recent_response` (reason_codes) sur les jours de séance active.
- **cause probable (racine identifiée)**: incohérence entre deux parseurs de date:
  - `training_v2/training_history._activity_date` (utilisé par TrainingHistory/TrainingLoad/Readiness) gère `datetime.fromisoformat` **et** les formats espace-séparés `"%Y-%m-%d %H:%M:%S(.%f)"` → OK.
  - `training_v2/training_response._activity_date` (utilisé par RecentTrainingResponse #132, lignes ~156-171) n'essaie que `strptime` avec `("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d")` — **ne gère PAS le format espace-séparé** → renvoie `None` → toutes les activités exclues.
  - `mongo_garmin_activities_to_domain` / `_domain_start_time` transmettent la chaîne Mongo **telle quelle** (espace-séparée). Le chemin #135 fonctionne uniquement parce que `_to_domain_activity_from_workout` reformate en `strftime("%Y-%m-%dT%H:%M:%S")` (T-séparé), contournant fortuitement la faiblesse du parser.
- **correction recommandée (NON appliquée)**: harmoniser le parsing de date — soit ajouter `datetime.fromisoformat` + les formats `"%Y-%m-%d %H:%M:%S(.%f)"` dans `training_response._activity_date` (aligner sur `training_history._activity_date`), soit normaliser `start_time` en datetime/ISO-T dans `mongo_garmin_activities_to_domain`/`_domain_start_time`. Ajouter une fixture au format Mongo Garmin espace-séparé dans `test_mongo_garmin_boundary_pr137` / `test_training_response_pr132` pour couvrir ce cas.

---

# VERDICT

## #137 runtime = PARTIAL
Chaîne migrée correcte pour Plan V2 → séance prévue → frontière Mongo (champs préservés) → TrainingLoad V2 → ReadinessResult V2 → ReadinessDecision V2 → DailyAdaptation V2 → payload (KEEP jour de repos, mapping/compat/TSS null/absence fatigue legacy tous conformes). **MAIS** RecentTrainingResponse #132 est silencieusement inopérant dans ce chemin (BUG-137-01), ce qui contredit l'objectif de préservation à la frontière Mongo revendiqué par #137.

## GLOBAL = NO-GO #138
Motif: défaut fonctionnel HIGH (BUG-137-01) dans le chemin runtime précisément validé — le signal #132 est mort côté `/training/today`. #138 (audit/migration des consumers legacy) s'appuie sur une frontière Mongo→V2 supposée saine; corriger l'harmonisation du parsing de date (ou la normalisation start_time) avant d'avancer. Correction bornée et à faible risque, mais requise avant GO.

> Note: le jour de repos empêchant de reproduire SHORTEN/EASY_DOWNGRADE n'est PAS le motif du NO-GO (ces cas sont couverts par les tests). Le motif est exclusivement BUG-137-01.
