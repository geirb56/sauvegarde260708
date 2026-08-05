# PR01 — Garmin Data Layer (fondation RunIndex v2)

## Objectif
Créer la **couche de données Garmin normalisée** qui deviendra l'unique source de vérité du futur moteur RunIndex v2. **PR strictement additive** : aucune modification du Training Engine, du RunIndex Score, de la Readiness, du frontend, des endpoints publics, ni du comportement utilisateur.

---

## A. Fichiers créés
| Fichier | Rôle |
|---|---|
| `backend/garmin/data_layer.py` | Modèles + normaliseurs (pure normalisation, zéro logique métier) |
| `backend/tests/test_garmin_data_layer.py` | Tests sur JSON réels audités + cas `{}` / `[]` / `null` |
| `GARMIN_DATA_LAYER_PR01_REPORT.md` | Ce rapport |

## B. Fichiers modifiés
**Aucun fichier existant modifié.** Les changements hors périmètre initialement introduits par PR01 sur `memory/PRD.md` et `.emergent/emergent.yml` ont été **annulés** (restaurés à l'état pré-PR01). Le diff de PR01 contient donc uniquement les 3 fichiers ci-dessus.

---

## C. Nouveaux modèles (Pydantic v2, `extra="ignore"`)

### 1. `GarminActivity` — `GarminActivity.from_summary(raw, details_available=None)`
Accepte l'objet `activity summary` (avec `summaryDTO`/`metadataDTO`) **et** la forme plate d'un item `activities list`.

Champs : `activity_id, activity_type, start_time, distance_m, duration_s, moving_duration_s, average_speed_mps, average_moving_speed_mps, max_speed_mps, average_hr, max_hr, min_hr, average_run_cadence, max_run_cadence, stride_length, steps, elevation_gain, elevation_loss, calories, moderate_intensity_minutes, vigorous_intensity_minutes, lap_count, has_hr_zones, has_splits, details_available, source`.

### 2. `GarminDailyMetrics` — `GarminDailyMetrics.from_gccli(date, hr, sleep, stress, body_battery, hrv)`
Combine les payloads des endpoints `health` (hr / sleep / stress / body-battery / hrv).

Champs : `date, resting_hr, sleep_hours, sleep_score, stress, body_battery, respiration, hrv, source`.
- `sleep_hours` = `dailySleepDTO.sleepTimeSeconds / 3600` (arrondi 0,1)
- `body_battery` = dernière valeur de `bodyBatteryValuesArray`
- `hrv` = `hrvSummary.lastNightAvg` (sinon `weeklyAvg`)
- Sentinelle Garmin `avgStressLevel < 0` → `None`

### 3. `GarminCapabilities` — `GarminCapabilities.from_probe(...)`
Décrit ce que la montre produit réellement (pour afficher plus tard « Non disponible sur votre montre »).

**Sémantique (importante) :** un booléen `True` signifie **qu'une donnée exploitable (valeur non nulle) a été réellement observée pour ce compte/appareil** — *pas* seulement que la commande existe dans gccli. Un payload non vide dont toutes les valeurs métier sont nulles produit `False`.

Champs : `has_hrv, has_vo2max, has_training_readiness, has_training_status, has_body_battery, has_stress, has_running_dynamics, has_power, has_race_predictions`.
- Détection valeur-réelle via `_deep_has_positive_number(...)` :
  - `has_vo2max` : cherche une clé contenant `vo2` avec valeur > 0 (`[{"vo2MaxValue": null}]` → **False**).
  - `has_training_readiness` : cherche `score` > 0 (`[{"score": null}]` → **False**).
  - `has_race_predictions` : cherche une clé `time*` > 0 (`{"time5K": null, "time10K": null}` → **False**).
- Autres : `has_hrv` via `hrvSummary.lastNightAvg/weeklyAvg` ; `has_training_status` via `mostRecent*` non-null ; `has_stress` via `avgStressLevel >= 0` ; `has_power` via `metadataDTO.hasPowerTimeInZones` ; `has_running_dynamics` via marqueurs GCT / oscillation verticale ; `has_body_battery` via présence de contenu.
- `{}` / `[]` / `null` / `404` ⇒ `False`.

---

## D. Nouveaux champs (enrichissement vs normalisation actuelle)
La normalisation historique (`runner._normalize`) ne gardait que : `external_id, name, activity_type, start_time, distance, duration, avg_hr, pace`. La nouvelle couche **ajoute** notamment :
`max_hr, min_hr, moving_duration_s, average_moving_speed_mps, max_speed_mps, average_run_cadence, max_run_cadence, stride_length, steps, elevation_gain, elevation_loss, calories, moderate_intensity_minutes, vigorous_intensity_minutes, lap_count, has_hr_zones, has_splits, details_available` — tous prouvés disponibles dans gccli 1.9.0 lors de l'audit.

Côté daily : ajout de `sleep_score, stress, body_battery, respiration` (en plus de `resting_hr, sleep_hours, hrv`).

---

## E. Compatibilité avec l'existant
- **Zéro import** de ce module ailleurs ⇒ aucun effet de bord au démarrage (`import garmin.data_layer` OK, backend health `200`).
- **Aucun** champ, endpoint, collection ou comportement existant modifié.
- **Règle « no fallback »** respectée : tout champ absent côté Garmin ⇒ `None` (jamais 0/valeur inventée). `{}` / `[]` / `null` ⇒ modèle valide avec champs `None`.
- **Aucune logique métier** (pas de RunnerProfile / TrainingHistory / TrainingState / plan / générateur).

---

## F. Couverture de tests — `pytest tests/test_garmin_data_layer.py` : **13 passed**
| Test | Vérifie |
|---|---|
| `test_activity_from_summary_real` | `activity summary` réel → tous les champs |
| `test_activity_from_flat_list_shape` | forme `activities list` (cadence `*InStepsPerMinute`) |
| `test_daily_metrics_real` | `sleep` + `stress` + `body-battery` + `hr` réels |
| `test_daily_metrics_hrv_present` | HRV présent (`hrvSummary.lastNightAvg`) |
| `test_stress_negative_sentinel_is_none` | sentinelle stress négatif → `None` |
| `test_capabilities_real_probe` | montre auditée : body-battery/stress True, reste False |
| `test_capabilities_rich_watch` | montre complète : toutes capacités True |
| `test_activity_empty_inputs` | `{}` / `[]` / `null` → modèle valide |
| `test_daily_metrics_empty_inputs` | tous payloads vides → tous champs `None` |
| `test_capabilities_all_empty` | tous vides → toutes capacités `False` |
| `test_capabilities_vo2max_null_value_is_false` | `[{"vo2MaxValue": null}]` → **False** (positif → True) |
| `test_capabilities_training_readiness_null_score_is_false` | `[{"score": null}]` → **False** (score → True) |
| `test_capabilities_race_predictions_all_null_is_false` | `{"time5K": null, ...}` → **False** (temps → True) |

Les JSON de test proviennent des payloads **réellement audités** (activity summary/details, sleep, stress, body battery, hr-zones).

---

## G. Points bloquants éventuels
- **Aucun bloquant.**
- Note : `activity details` sert uniquement à la détection de capacités (Running Dynamics) ; la série temporelle brute (483 échantillons) n'est pas normalisée dans cette PR (hors périmètre — sera consommée par une PR TrainingHistory).
- Le branchement de cette couche dans le flux de sync (persistance `GarminDailyMetrics`/`GarminCapabilities` en base) est **volontairement laissé à une PR ultérieure**.

---

## Verdict : **READY TO MERGE**
Aucun changement fonctionnel visible, aucune régression, tous les anciens appels continuent de fonctionner, nouvelles données prêtes pour les futures PR.
