# Micro-validation runtime ciblée — BUG-137-01 (RecentTrainingResponse #132 dans `/training/today`)

Date: 2026-08-19 · Mode: **LECTURE SEULE** · Aucun code modifié · Aucune PR · Aucun bug corrigé · Aucune donnée Mongo modifiée · Aucune séance forcée.
Compte réel: `da8505ef-…` (mallegolbrieg@…) · Auth: JWT read-only.

---

## 1) État du code
- **HEAD** = `461f9e4` (merge local contenant PR#143 `0b6b6a0`). `sauvegarde/copilot/dev` = `0b6b6a0`.
- **PR #143 présente** ✓ (commits `671b00d` migrate /training/metrics acwr_reliable→TrainingState V2, `8b8100b` strengthen tests, `0b6b6a0` merge).
- **Comparaison des parseurs de date** (seul point comparé, rien modifié) :
  - `training_v2/training_history.py::_parse_date` (L230-267) : `datetime.fromisoformat(s)` **puis** fallback `strptime` avec `("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%Y-%m-%d")` → **gère le format espace-séparé**.
  - `training_v2/training_response.py::_activity_date` (L~156-171) : `strptime` uniquement avec `("%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%d")` → **PAS de `fromisoformat`, PAS de format espace-séparé**.
  - `garmin/domain_adapter.py::_domain_start_time` : retourne la valeur str/date/datetime **telle quelle** (les docs Mongo `garmin_activities` stockent `start_time` en chaîne espace-séparée).
  - `server.py` `/training/today` (L~3579-3739) : `mongo_garmin_activities_to_domain(garmin_activities)` → `build_training_load` / `build_readiness_v2` / `build_recent_training_response` / `build_daily_adaptation`.

## 2) Smoke — 5/5 HTTP 200
today=200 · plan=200 · metrics=200 · run-index=200 · dashboard=200.

## 3) Données réelles (28 derniers jours, lecture seule)
- total Mongo `garmin_activities` : **147**
- après adaptation `DomainActivity` : **147**
- `activity_type == running` (RUNNING_TYPES) : **125**
- date exploitable par TrainingHistory (`_parse_date`) : **147 / 147**
- date exploitable par RecentTrainingResponse (`_activity_date`) : **0 / 147**
- running dans les 28 j (via `_parse_date`) : **6**

4 runs récentes (champs techniques) :
| start_time | type | duration_s | distance_m | avg_hr | mod_min | vig_min | elev_m |
|---|---|---|---|---|---|---|---|
| 2026-08-18 05:11:14 | running | 2641.25 | 7065.24 | 138 | 17 | 17 | 35.07 |
| 2026-08-15 05:23:32 | running | 4934.50 | 11974.44 | 136 | 62 | 10 | 58.22 |
| 2026-08-13 05:05:02 | running | 3367.47 | 8773.61 | 142 | 14 | 33 | 36.52 |
| 2026-08-10 04:59:35 | running | 1655.83 | 3926.62 | 121 | 4 | 0 | 22.44 |

## 4) Comparaison directe (mêmes DomainActivity, même reference_date=2026-08-19)
| | résultat |
|---|---|
| **TrainingHistory** | 7d=3 · 30d=6 · 90d=15 (activités reconnues) |
| **RecentTrainingResponse** | status=`unavailable` · available_running=**0** · selected=0 · observed_runs=0 · hr_coverage_count=0 · average_hr_recent=None · trends: vol/freq/long/cardiac/intensity = **unknown** |

→ Divergence prouvée sur exactement les mêmes objets.

## 5) Preuve du parsing (mêmes start_time réels)
| input | TrainingHistory `_parse_date` | RecentResponse `_activity_date` |
|---|---|---|
| `"2026-08-18 05:11:14"` | 2026-08-18 | **None** |
| `"2026-08-15 05:23:32"` | 2026-08-15 | **None** |
| `"2026-08-13 05:05:02"` | 2026-08-13 | **None** |

→ Signature exacte attendue de BUG-137-01. Aucun monkeypatch.

## 6) Contrôle des autres filtres
- RUNNING_TYPES = {running, trail_running, treadmill_running} · distribution : running=125, walking=4, breathwork=5, indoor_cardio=10, cycling=3.
- runs avec `duration_s>0` : **125/125** · `distance_m>0` : **124/125**.
- runs sans `average_hr` : **0** · sans `elevation_gain_m` : 76 (HR/D+/intensité manquants **n'entraînent PAS** l'exclusion).
- Aucun autre filtre (type, fenêtre 28j, durée, distance, chronologie, cap) n'explique `available_running=0`. La cause unique est le rejet de la date par `_activity_date`.

## 7) `/training/today` (payload live, 2026-08-19)
- planned_session : `rest` (0 min, tss None) — jour de repos réel, planning NON modifié.
- readiness : band=`FAVORABLE`, score=80.5, confidence=`NORMAL`, sufficiency=`SUFFICIENT`, available=true, data_source=garmin.
- adaptation_action=`KEEP` · applied=false · reason_codes=`[PLANNED_REST_DAY, PLAN_KEPT]`.
- RecentTrainingResponse : **non exposé directement** dans le payload (consommé en interne par `build_daily_adaptation`). L'état interne réel est prouvé autoritairement en §4 (réplication exacte du pipeline endpoint) = `unavailable` / available_running=0 / trends unknown. Sur un jour de repos → KEEP quel que soit le recent_response, donc aucun symptôme visible aujourd'hui dans le payload, mais le signal #132 est mort en interne.

---

## VERDICT : **BUG-137-01 CONFIRMED**

Les 4 conditions requises sont réunies :
1. Des DomainActivity running récentes existent réellement (125 running, 6 dans 28j). ✓
2. TrainingHistory les reconnaît (30d=6, 90d=15). ✓
3. RecentTrainingResponse ne les reconnaît pas (available_running=0, status=unavailable, trends unknown). ✓
4. Le même `start_time` est accepté par `training_history._parse_date` (→ date valide) mais rejeté par `training_response._activity_date` (→ None). ✓

Cause racine unique : `training_response._activity_date` ne parse pas le format Mongo Garmin espace-séparé `"YYYY-MM-DD HH:MM:SS"` produit par `mongo_garmin_activities_to_domain` (transmis tel quel), alors que `training_history._parse_date` le gère. Non adressé par PR#143.

## Scope minimal recommandé pour PR #144 (NON appliqué)
1. **Correctif ciblé (1 fonction)** : dans `training_v2/training_response.py::_activity_date`, ajouter `datetime.fromisoformat` + les formats `"%Y-%m-%d %H:%M:%S(.%f)"` (aligner sur `training_history._parse_date`) OU, idéalement, factoriser un unique helper de parsing de date partagé entre `training_history` et `training_response` pour éliminer la divergence structurelle.
2. **Alternative/complément** : normaliser `start_time` en `datetime` (ou ISO-`T`) dans `garmin/domain_adapter._domain_start_time` afin que tous les consommateurs V2 reçoivent un format homogène.
3. **Couverture de test** : ajouter dans `test_training_response_pr132` / `test_mongo_garmin_boundary_pr137` une fixture au format Mongo Garmin espace-séparé `"YYYY-MM-DD HH:MM:SS"` (les fixtures actuelles utilisent datetime/ISO-`T`, ce qui masque le bug — 203 tests passent malgré le défaut runtime).
4. Périmètre strict : ne toucher ni au plan, ni à Readiness, ni à TrainingState, ni à la logique de sélection/trends de RecentTrainingResponse — uniquement le parsing de date.
