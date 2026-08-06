# GARMIN_CAPABILITIES_PR04_REPORT.md

## PR04 — GarminCapabilities comme source unique des capacités observées

---

## 1. Cartographie du flux existant (audit)

### Commandes gccli déjà exécutées (avant PR04)

| Commande | Lieu | Résultat |
|---|---|---|
| `health hr <date>` | `GccliRunner.fetch_daily_metrics` | resting HR |
| `health sleep <date>` | `GccliRunner.fetch_daily_metrics` | sommeil |
| `health hrv <date>` | `GccliRunner.fetch_daily_metrics` | HRV |
| `activities list` | `GccliRunner.fetch_activities` | activités |
| `auth status` | `GccliRunner.auth_status` / `get_profile` | statut auth |

### Payloads disponibles après PR03

Les payloads HRV, HR, sleep sont déjà collectés quotidiennement dans `GccliRunner.fetch_daily_metrics` et normalisés via `GarminDailyMetrics.from_gccli`. Les champs résultants (`hrv`, `stress`, `body_battery`, `resting_hr`, `sleep_hours`) sont persistés dans la collection `garmin_daily_metrics`.

### Métriques quotidiennes stockées

Collection `garmin_daily_metrics` — documents plats avec :
- `user_id`, `date`, `resting_hr`, `sleep_hours`, `sleep_score`, `stress`, `body_battery`, `respiration`, `hrv`

### Notion de capabilities avant PR04

Aucune. Pas de détection de capacités, pas de document de statut capabilities, pas d'endpoint dédié.

### Document de statut Garmin existant

Collection `garmin_connections` — contient : `user_id`, `connected`, `provider`, `connected_at`, `garmin_username`, `deep_sync_done`, `last_sync`, `activity_count`, `last_activity_at`.

---

## 2. Méthode de détection utilisée

**Source unique : `GarminCapabilities.from_probe()`** (défini en PR01 dans `backend/garmin/data_layer.py`).

PR04 n'ajoute aucune logique de détection dans `service.py`, `runner.py` ou ailleurs. Les payloads déjà stockés en base sont reconstitués dans la forme attendue par `from_probe` :

```python
hrv_payload = {"hrvSummary": {"lastNightAvg": hrv_val}}  # si hrv_val is not None
stress_payload = {"avgStressLevel": stress_val}           # si stress_val is not None
# body_battery: valeur scalaire directe
capabilities = GarminCapabilities.from_probe(hrv=hrv_payload, body_battery=bb_val, stress=stress_payload)
```

---

## 3. Signification exacte d'un booléen True

Un champ `True` signifie : **une valeur métier réelle et non-nulle a été effectivement observée pour ce compte/appareil**.

Exemples de règles (héritées de PR01, non dupliquées) :

| Payload | Résultat |
|---|---|
| `hrv = {}` | `has_hrv = False` |
| `hrv = {"hrvSummary": {"lastNightAvg": 61}}` | `has_hrv = True` |
| `max_metrics = []` | `has_vo2max = False` |
| `max_metrics = [{"vo2MaxValue": None}]` | `has_vo2max = False` |
| `training_status = {"mostRecentVO2Max": None, "mostRecentTrainingStatus": None}` | `has_training_status = False` |
| `stress = {"avgStressLevel": -1}` | `has_stress = False` (sentinelle Garmin) |
| `body_battery = 75` | `has_body_battery = True` |

---

## 4. Emplacement de persistance

**Collection : `garmin_connections`** (document Garmin existant par utilisateur).

Nouveau sous-document ajouté par upsert ciblé ($set) :
```json
{
  "garmin_capabilities": {
    "has_hrv": false,
    "has_vo2max": false,
    "has_training_readiness": false,
    "has_training_status": false,
    "has_body_battery": false,
    "has_stress": false,
    "has_running_dynamics": false,
    "has_power": false,
    "has_race_predictions": false
  },
  "capabilities_updated_at": "2026-08-06T11:35:00+00:00"
}
```

Aucune nouvelle collection créée. Aucun index modifié.

---

## 5. Stratégie multi-utilisateur

```python
await db.garmin_connections.update_one(
    {"user_id": user_id},          # filtre strict par utilisateur
    {"$set": {                     # upsert partiel, ne touche pas les autres champs
        "garmin_capabilities": capabilities.model_dump(),
        "capabilities_updated_at": datetime.now(timezone.utc).isoformat(),
    }},
    upsert=True,
)
```

- Le filtre `{"user_id": user_id}` garantit l'isolation.
- `$set` partiel : les autres champs (`connected`, `last_sync`, `activity_count`, etc.) ne sont pas écrasés.
- Pas de credentials dans le document.
- Pas de JSON bruts de probe stockés.

---

## 6. Absence de nouveaux appels gccli massifs

**Aucun nouvel appel gccli n'est ajouté.** PR04 lit uniquement les données déjà présentes dans la collection `garmin_daily_metrics` (peuplée par les syncs existants).

Les capacités non vérifiables avec les données disponibles restent `False` :
- `has_vo2max` : nécessiterait `health max-metrics` (non ajouté)
- `has_training_readiness` : nécessiterait `health training-readiness` (non ajouté)
- `has_training_status` : nécessiterait `health training-status` (non ajouté)
- `has_running_dynamics` : nécessiterait les détails d'activité (non ajouté)
- `has_power` : nécessiterait les métadonnées d'activité (non ajouté)
- `has_race_predictions` : nécessiterait `health race-predictions` (non ajouté)

---

## 7. Fréquence de mise à jour

Les capabilities sont recalculées à chaque `sync()` et `deep_sync()`, après la collecte des métriques quotidiennes. Le calcul lit les valeurs déjà en base et ne déclenche aucun appel gccli supplémentaire.

---

## 8. Fichiers modifiés

| Fichier | Nature de la modification |
|---|---|
| `backend/garmin/service.py` | Import `GarminCapabilities` ; ajout `_persist_capabilities()` ; hook dans `sync()`, `deep_sync()` ; ajout additif dans `get_status()` |
| `backend/tests/test_garmin_capabilities_pr04.py` | Créé (tests PR04) |
| `GARMIN_CAPABILITIES_PR04_REPORT.md` | Créé (ce rapport) |

Aucun autre fichier modifié.

---

## 9. Tests exécutés et résultats

```
python -m pytest tests/test_garmin_capabilities_pr04.py -q
→ 27 passed

python -m pytest tests/test_garmin_data_layer.py -q
→ passed

python -m pytest tests/test_garmin_daily_metrics_pr03.py -q
→ passed

python -m pytest tests/test_garmin_activity_normalization_pr02.py -q
→ passed

python -m pytest tests/test_garmin_deep_sync.py -q
→ passed

Total non-régression : 77 passed
```

Compilation :
```
python -m py_compile garmin/service.py  → OK
```

---

## 10. Risques résiduels

- **Capabilities partielles** : seuls `has_hrv`, `has_body_battery`, `has_stress` peuvent être déterminés à partir des données disponibles. Les 6 autres restent `False` jusqu'à ce qu'une future PR ajoute les appels gccli correspondants de manière contrôlée.
- **Ordre de mise à jour** : les capabilities sont calculées après le store des métriques dans le même `sync()` ; si le sync est interrompu après les métriques mais avant les capabilities, elles seront mises à jour au prochain sync.
- **Données historiques** : les utilisateurs déjà synchronisés ne verront leurs capabilities mises à jour qu'au prochain sync.

---

## 11. Confirmations

- ✅ `GarminCapabilities.from_probe()` est la source unique de décision
- ✅ Aucune logique de détection dupliquée dans `runner.py`, `service.py` ou ailleurs
- ✅ Faux positifs exclus (null, vide, sentinelles négatives)
- ✅ Persistance multi-utilisateur par upsert `$set` ciblé
- ✅ Aucun JSON brut volumineux stocké
- ✅ Aucun nouvel appel gccli massif ajouté
- ✅ Aucun moteur métier modifié (Training Engine, RunIndex Score, Readiness, etc.)
- ✅ Aucun frontend modifié
- ✅ Endpoint `/api/garmin/status` enrichi de manière additive uniquement
- ✅ Tous les tests passent (77 tests au total)
- ✅ Diff limité : 3 fichiers
