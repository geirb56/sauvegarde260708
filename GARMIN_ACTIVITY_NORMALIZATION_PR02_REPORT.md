# GARMIN_ACTIVITY_NORMALIZATION_PR02_REPORT.md

## Objectif

Faire de `GarminActivity` (créé en PR01) la seule source de normalisation des activités Garmin.  
Supprimer la duplication de normalisation manuelle dans `GccliProvider._normalize`.

---

## Fichiers modifiés

| Fichier | Nature de la modification |
|---|---|
| `backend/garmin/providers/gccli_provider.py` | `_normalize` délègue à `GarminActivity.from_summary` + ajout du champ `garmin_activity` |

## Fichiers créés

| Fichier | Nature |
|---|---|
| `backend/tests/test_garmin_activity_normalization_pr02.py` | Tests PR02 |
| `GARMIN_ACTIVITY_NORMALIZATION_PR02_REPORT.md` | Ce rapport |

---

## Ancienne normalisation (`GccliProvider._normalize` avant PR02)

```python
@staticmethod
def _normalize(raw: Dict) -> Dict:
    atype = raw.get("activityType")
    if isinstance(atype, dict):
        atype = atype.get("typeKey")
    distance_m = raw.get("distance")
    duration_s = raw.get("duration")
    pace_spk = None
    if distance_m and duration_s and distance_m > 0:
        pace_spk = round(duration_s / (distance_m / 1000.0), 1)
    ext_id = raw.get("activityId") or raw.get("id")
    pace_str = None
    if pace_spk:
        m = int(pace_spk // 60)
        s = int(round(pace_spk % 60))
        if s == 60:
            m += 1
            s = 0
        pace_str = f"{m}:{s:02d}"
    return {
        "external_id": str(ext_id) if ext_id is not None else None,
        "source": "garmin",
        "name": raw.get("activityName"),
        "activity_type": atype or "running",
        "start_time": raw.get("startTimeLocal") or raw.get("startTimeGMT"),
        "distance": distance_m,
        "duration": duration_s,
        "avg_hr": int(raw["averageHR"]) if raw.get("averageHR") else None,
        "pace": pace_str,
        "pace_seconds_per_km": pace_spk,
        "raw_payload": {
            "activityId": ext_id,
            "distance": distance_m,
            "duration": duration_s,
            "averageHR": raw.get("averageHR"),
            "averageSpeed": raw.get("averageSpeed"),
            "calories": raw.get("calories"),
            "elevationGain": raw.get("elevationGain"),
        },
    }
```

La normalisation était **manuelle** : chaque champ extrait directement depuis le dict brut, sans modèle commun.

---

## Nouvelle normalisation (`GccliProvider._normalize` après PR02)

```python
@staticmethod
def _normalize(raw: Dict) -> Dict:
    # Delegate all field extraction to GarminActivity (PR01 model).
    normalized = GarminActivity.from_summary(raw)

    distance_m = normalized.distance_m
    duration_s = normalized.duration_s
    pace_spk = None
    if distance_m and duration_s and distance_m > 0:
        pace_spk = round(duration_s / (distance_m / 1000.0), 1)
    pace_str = None
    if pace_spk:
        m = int(pace_spk // 60)
        s = int(round(pace_spk % 60))
        if s == 60:
            m += 1
            s = 0
        pace_str = f"{m}:{s:02d}"

    ext_id = normalized.activity_id
    avg_hr = int(normalized.average_hr) if normalized.average_hr is not None else None
    activity_type = normalized.activity_type or "running"

    raw_payload = {
        "activityId": raw.get("activityId") or raw.get("id"),
        "distance": distance_m,
        "duration": duration_s,
        "averageHR": raw.get("averageHR"),
        "averageSpeed": raw.get("averageSpeed"),
        "calories": raw.get("calories"),
        "elevationGain": raw.get("elevationGain"),
    }

    return {
        "external_id": ext_id,
        "source": "garmin",
        "name": raw.get("activityName"),
        "activity_type": activity_type,
        "start_time": normalized.start_time,
        "distance": distance_m,
        "duration": duration_s,
        "avg_hr": avg_hr,
        "pace": pace_str,
        "pace_seconds_per_km": pace_spk,
        "raw_payload": raw_payload,
        # New field added in PR02: full normalized model
        "garmin_activity": normalized.model_dump(),
    }
```

L'extraction des champs est désormais **déléguée à `GarminActivity.from_summary`**. Le provider ne recalcule plus rien.

---

## Compatibilité du contrat historique

| Clé | Présente avant | Présente après | Valeur inchangée |
|---|---|---|---|
| `external_id` | ✅ | ✅ | ✅ (string) |
| `source` | ✅ | ✅ | ✅ `"garmin"` |
| `name` | ✅ | ✅ | ✅ |
| `activity_type` | ✅ | ✅ | ✅ (défaut `"running"`) |
| `start_time` | ✅ | ✅ | ✅ |
| `distance` | ✅ | ✅ | ✅ |
| `duration` | ✅ | ✅ | ✅ |
| `avg_hr` | ✅ | ✅ | ✅ |
| `pace` | ✅ | ✅ | ✅ |
| `pace_seconds_per_km` | ✅ | ✅ | ✅ |
| `raw_payload` | ✅ | ✅ | ✅ (mêmes clés) |
| `garmin_activity` | ❌ | ✅ | N/A (nouveau) |

**Aucun endpoint public ne change. Aucune nouvelle commande gccli.**

---

## Tests exécutés

Fichier : `backend/tests/test_garmin_activity_normalization_pr02.py`

### `TestContractPreserved` — contrat historique

| Test | Description |
|---|---|
| `test_all_contract_keys_present` | Toutes les clés du contrat sont présentes |
| `test_external_id` | `external_id` == `"23821475753"` (string) |
| `test_source_is_garmin` | `source` == `"garmin"` |
| `test_name` | `name` == `"Vannes Course a pied"` |
| `test_activity_type` | `activity_type` == `"running"` |
| `test_start_time_present` | `start_time` est l'une des valeurs GMT ou Local |
| `test_distance` | `distance` ≈ 6769.92 |
| `test_duration` | `duration` ≈ 2787.479 |
| `test_avg_hr` | `avg_hr` == 146 |
| `test_pace_format` | `pace` est une string `"m:ss"` |
| `test_pace_seconds_per_km` | `pace_seconds_per_km` ≈ 411.8 |
| `test_raw_payload_keys` | `raw_payload` contient toutes les clés historiques |

### `TestGarminActivityAdded` — nouveau champ PR02

| Test | Description |
|---|---|
| `test_garmin_activity_key_present` | `garmin_activity` est présent dans le résultat |
| `test_garmin_activity_is_dict` | `garmin_activity` est un dict |
| `test_garmin_activity_matches_model` | `garmin_activity` == `GarminActivity.from_summary(raw).model_dump()` |
| `test_garmin_activity_source` | `garmin_activity["source"]` == `"garmin"` |
| `test_garmin_activity_distance` | `garmin_activity["distance_m"]` ≈ 6769.92 |
| `test_garmin_activity_average_hr` | `garmin_activity["average_hr"]` ≈ 146.0 |

### `TestDegenerateInputs` — cas limites `{}` / `[]` / `None`

| Test | Description |
|---|---|
| `test_empty_dict_does_not_raise` | `{}` → résultat valide, toutes les clés présentes |
| `test_empty_dict_has_garmin_activity` | `{}` → `garmin_activity` présent |
| `test_none_input_via_from_summary_does_not_raise` | `None` → `GarminActivity` valide sans exception |
| `test_empty_list_via_from_summary_does_not_raise` | `[]` → `GarminActivity` valide sans exception |
| `test_activity_type_fallback_to_running` | Sans `activityType`, défaut `"running"` |
| `test_missing_hr_gives_none` | Sans `averageHR`, `avg_hr` == `None` |
| `test_missing_distance_gives_none_pace` | Sans distance, `pace` et `pace_seconds_per_km` == `None` |
| `test_no_exception_on_garmin_activity_field_for_empty` | `{}` → `garmin_activity` est un dict valide |

---

## Résultats

```
26 passed in 0.51s
```

Tests de non-régression complémentaires :

```
test_garmin_data_layer.py   — 20 passed
test_garmin_deep_sync.py    — 14 passed
Total                       — 34 passed in 1.16s
```

**Aucune régression.**

---

## Confirmation : aucune logique métier modifiée

- `GarminDailyMetrics` : **non modifié**
- `GarminCapabilities` : **non modifié**
- Training Engine : **non modifié**
- RunnerProfile / TrainingHistory / TrainingState / PlanGoal : **non modifiés**
- WorkoutGenerator / Readiness / RunIndex Score : **non modifiés**
- Frontend / MongoDB / API / Workers / Queue : **non modifiés**
- Aucun nouvel appel gccli (activity summary, activity details, hr-zones, stress, body battery) : **confirmé**
- Diff minimal : seul `GccliProvider._normalize` est modifié dans le code de production

---

*Généré automatiquement — PR02 — branche `dev`*
