# GARMIN_ACTIVITY_NORMALIZATION_PR02_REPORT.md

## Objectif

Faire de `GarminActivity` (créé en PR01) la seule source de normalisation des activités Garmin.  
Supprimer la duplication de normalisation manuelle dans `GccliProvider._normalize`.

---

## Fichiers modifiés

| Fichier | Nature de la modification |
|---|---|
| `backend/garmin/providers/gccli_provider.py` | `_normalize` délègue à `GarminActivity.from_summary` + ajout du champ `garmin_activity` |
| `backend/garmin/data_layer.py` | `from_summary` accepte désormais `id` comme alternative à `activityId` |

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
    ...
    return {
        "external_id": str(ext_id) if ext_id is not None else None,
        "source": "garmin",
        "name": raw.get("activityName"),
        "activity_type": atype or "running",          # fallback "running" si absent
        "start_time": raw.get("startTimeLocal") or raw.get("startTimeGMT"),  # Local prioritaire
        ...
    }
```

La normalisation était **manuelle** : chaque champ extrait directement depuis le dict brut, sans modèle commun.

---

## Nouvelle normalisation (`GccliProvider._normalize` après PR02)

**GarminActivity est la source unique des champs Garmin normalisés. Le provider conserve l'adaptation vers le contrat historique, notamment l'allure et le raw_payload compact.**

Points précis :

### Priorité historique Local → GMT conservée

Pour le champ `start_time` du contrat historique, le provider lit directement :

```python
start_time = raw.get("startTimeLocal") or raw.get("startTimeGMT")
```

`garmin_activity` (sous-document) conserve la convention du modèle PR01 (GMT d'abord) — différence résiduelle documentée et sans impact sur le contrat.

### Suppression du fallback `"running"`

```python
# Avant :
activity_type = normalized.activity_type or "running"

# Après :
activity_type = normalized.activity_type
```

Une activité dont Garmin ne fournit pas le type retourne `None`. Aucun type n'est inventé.

### Support de `id` en plus de `activityId`

`GarminActivity.from_summary` accepte désormais `raw.get("activityId") or raw.get("id")`, préservant le comportement historique du provider.

### Portée des cas dégénérés

- `GarminActivity.from_summary` : tolère `{}`, `[]`, `None` — aucune exception (garantie PR01 conservée).
- `GccliProvider._normalize` : robuste à `{}` (dict vide). `[]` et `None` ne font pas partie de son contrat documenté.

---

## Compatibilité du contrat historique

| Clé | Présente avant | Présente après | Comportement |
|---|---|---|---|
| `external_id` | ✅ | ✅ | String — accepte `activityId` ou `id` |
| `source` | ✅ | ✅ | `"garmin"` |
| `name` | ✅ | ✅ | Inchangé |
| `activity_type` | ✅ | ✅ | `None` si absent (plus de fallback `"running"`) |
| `start_time` | ✅ | ✅ | Local prioritaire, puis GMT |
| `distance` | ✅ | ✅ | Inchangé |
| `duration` | ✅ | ✅ | Inchangé |
| `avg_hr` | ✅ | ✅ | Inchangé |
| `pace` | ✅ | ✅ | Inchangé |
| `pace_seconds_per_km` | ✅ | ✅ | Inchangé |
| `raw_payload` | ✅ | ✅ | Mêmes clés, même forme compacte |
| `garmin_activity` | ❌ | ✅ | Nouveau — `normalized.model_dump()` |

**Aucun endpoint public ne change. Aucune nouvelle commande gccli.**

---

## Tests exécutés

Fichier : `backend/tests/test_garmin_activity_normalization_pr02.py`

### `TestContractPreserved` — contrat historique

| Test | Description |
|---|---|
| `test_all_contract_keys_present` | Toutes les clés du contrat sont présentes |
| `test_external_id` | `external_id` == `"23821475753"` |
| `test_source_is_garmin` | `source` == `"garmin"` |
| `test_name` | `name` == `"Vannes Course a pied"` |
| `test_activity_type` | `activity_type` == `"running"` quand fourni |
| `test_start_time_prefers_local_over_gmt` | `start_time` == `startTimeLocal` quand les deux sont présents |
| `test_start_time_falls_back_to_gmt_when_local_absent` | `start_time` == `startTimeGMT` quand Local absent |
| `test_distance` | `distance` ≈ 6769.92 |
| `test_duration` | `duration` ≈ 2787.479 |
| `test_avg_hr` | `avg_hr` == 146 |
| `test_pace_format` | `pace` est une string `"m:ss"` |
| `test_pace_seconds_per_km` | `pace_seconds_per_km` ≈ 411.8 |
| `test_raw_payload_keys` | `raw_payload` contient toutes les clés historiques |

### `TestActivityTypeNoFallback` — suppression du fallback

| Test | Description |
|---|---|
| `test_absent_type_is_none` | Sans `activityType`, `activity_type` est `None` |
| `test_explicit_type_preserved` | Type explicite (`"cycling"`) conservé |

### `TestAlternativeIdKey` — support de `id`

| Test | Description |
|---|---|
| `test_id_key_sets_external_id` | `{"id": 123}` → `external_id == "123"` |
| `test_id_key_sets_garmin_activity_id` | `{"id": 123}` → `garmin_activity.activity_id == "123"` |

### `TestGarminActivityAdded` — nouveau champ PR02

| Test | Description |
|---|---|
| `test_garmin_activity_key_present` | `garmin_activity` est présent |
| `test_garmin_activity_is_dict` | `garmin_activity` est un dict |
| `test_garmin_activity_matches_model` | `garmin_activity` == `GarminActivity.from_summary(raw).model_dump()` |
| `test_garmin_activity_source` | `garmin_activity["source"]` == `"garmin"` |
| `test_garmin_activity_distance` | `garmin_activity["distance_m"]` ≈ 6769.92 |
| `test_garmin_activity_average_hr` | `garmin_activity["average_hr"]` ≈ 146.0 |
| `test_garmin_activity_start_time_gmt_convention` | `garmin_activity["start_time"]` == GMT (convention modèle) |

### `TestDegenerateInputs` — cas limites

| Test | Cible | Description |
|---|---|---|
| `test_empty_dict_on_normalize_does_not_raise` | `_normalize` | `{}` → résultat valide |
| `test_empty_dict_on_normalize_has_garmin_activity` | `_normalize` | `{}` → `garmin_activity` présent |
| `test_none_on_from_summary_does_not_raise` | `from_summary` | `None` → modèle valide |
| `test_empty_list_on_from_summary_does_not_raise` | `from_summary` | `[]` → modèle valide |
| `test_empty_dict_on_from_summary_does_not_raise` | `from_summary` | `{}` → modèle valide |
| `test_missing_hr_gives_none` | `_normalize` | Sans HR → `avg_hr` est `None` |
| `test_missing_distance_gives_none_pace` | `_normalize` | Sans distance → `pace` et `pace_seconds_per_km` sont `None` |

---

## Résultats (après synchronisation avec `main`)

```
test_garmin_activity_normalization_pr02.py   — 31 passed
test_garmin_data_layer.py                    — 13 passed
test_garmin_deep_sync.py                     — 21 passed
Total                                        — 65 passed in 1.69s
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
- Aucun nouvel appel gccli : **confirmé**
- Diff minimal : seuls `GccliProvider._normalize` et `GarminActivity.from_summary` (support de `id`) sont modifiés

---

*Généré automatiquement — PR02 corrections — branche `dev`*
