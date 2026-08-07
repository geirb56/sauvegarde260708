# TRAINING_STATE_PR04_REPORT.md

## PR04 — TrainingState V2

### ⚠ TrainingState décrit. TrainingState ne prescrit pas.

---

## Rôle de TrainingState

`TrainingState` est une couche métier pure et déterministe qui répond à deux questions indépendantes sur l'état courant du coureur :

1. **Quelle est la continuité récente d'entraînement ?** → `continuity_state`
2. **Quel est l'état actuel de charge ?** → `load_state`

`TrainingState` ne décide pas de la séance du jour, du volume cible, de l'intensité autorisée, de la périodisation ou du plan d'entraînement. Ces décisions appartiennent aux couches futures.

---

## Architecture à deux axes

Un coureur peut simultanément avoir :

```
continuity_state = "partial_reprise"
load_state       = "elevated"
```

Les deux axes sont **strictement indépendants**. Aucun état unique fusionné (ex. `partial_reprise_elevated_load`) n'est créé.

---

## Valeurs de `continuity_state`

| Valeur | Signification |
|---|---|
| `no_history` | Aucun historique running exploitable. |
| `deep_reprise` | Historique antérieur présent, mais aucune sortie depuis ≥ 28 jours. |
| `partial_reprise` | Reprise commencée, mais volume récent < 50 % du volume habituel observable. |
| `reprise_exit` | Continuité revenue mais pas encore stabilisée (historique < 4 semaines ou activité 30j trop sparse). |
| `normal` | Aucune rupture significative de continuité détectée. |

---

## Valeurs de `load_state`

Miroir direct de `TrainingLoadSnapshot.status` — aucun seuil ACWR n'est recalculé ici.

| Valeur | Définition ACWR (dans training_load.py) |
|---|---|
| `unavailable` | ACWR absent |
| `very_low` | ACWR < 0.50 |
| `low` | 0.50 ≤ ACWR < 0.80 |
| `balanced` | 0.80 ≤ ACWR ≤ 1.30 |
| `elevated` | 1.30 < ACWR ≤ 1.50 |
| `high` | ACWR > 1.50 |

---

## Règle exacte de `deep_reprise`

```python
NO_RUN_DEEP_REPRISE_DAYS = 28
```

**Condition** : `has_any_running_history == True` ET `days_since_last_run >= 28`

`no_history` n'est jamais assimilé à `deep_reprise`.

---

## Règle exacte de `partial_reprise`

```python
PARTIAL_REPRISE_VOLUME_RATIO = 0.50
```

**Condition** :
- Une baseline observable est disponible (`runner_profile.typical_weekly_km` issu de l'historique, non du profil déclaré seul)
- ET `recent_weekly_km < 0.50 × baseline_km`

Aucune valeur par défaut de volume n'est inventée. Si la baseline est `None`, cette règle ne s'applique pas.

---

## Règle exacte de `reprise_exit`

```python
REPRISE_EXIT_STABLE_WEEKS = 4
```

**Condition principale** : `available_history_days < 4 × 7 = 28` ET au moins une sortie dans la fenêtre 7j.

**Condition secondaire** (lorsque l'historique est plus long mais le volume reste en zone de récupération) : volume >= 50 % de la baseline MAIS < baseline ET activité 30j < 12 sorties (= 4 × 3).

La constante évite la réutilisation de l'ancienne `REPRISE_STABLE_WEEKS` legacy.

---

## Définition de `normal`

Aucune rupture significative de continuité détectée :
- Il existe un historique running
- La dernière sortie date de moins de 28 jours
- Le volume récent n'est pas significativement inférieur à la baseline
- L'historique est suffisamment profond et dense

`normal` ne signifie PAS : charge parfaite, bonne readiness, absence de fatigue, autorisation d'intensité.

---

## Gestion de `no_history`

`no_history` est déclenché si et seulement si `training_history.has_any_running_history == False`.

Un profil déclarant `weekly_km = 30` sans historique RunIndex reste `no_history`. Les données déclarées ne fabriquent pas de continuité observée.

---

## Calcul de `days_since_last_run`

Copié directement depuis `training_history.days_since_last_run` :

```
days_since_last_run = (reference_date - last_valid_run_date).days
```

Jamais calculé depuis `datetime.now()`. `None` si aucun historique.

---

## Confidence

### `continuity_confidence`

Basé uniquement sur la profondeur de l'historique observé (`available_history_days`) :

| Condition | Valeur |
|---|---|
| `available_history_days == 0` | `"none"` |
| `1 ≤ available_history_days ≤ 29` | `"low"` |
| `30 ≤ available_history_days ≤ 89` | `"medium"` |
| `available_history_days ≥ 90` | `"high"` |

Note : `available_history_days` dans `TrainingHistory` = `(reference_date - first_run_date).days`. Une seule sortie le jour même donne `available_history_days = 0` → confidence `"none"`. Ceci est cohérent avec la convention établie en PR05.

### `load_confidence`

Repris directement depuis `TrainingLoadSnapshot.confidence` — aucun recalcul.

### `overall_confidence`

```python
overall_confidence = minimum(continuity_confidence, load_confidence)
```

Ordre : `none < low < medium < high`. Pas de moyenne numérique.

---

## Reason codes

Codes déterministes, non traduits, indépendants de l'UI et du langage naturel :

| Code | Déclenchement |
|---|---|
| `NO_RUNNING_HISTORY` | `continuity_state = no_history` |
| `NO_RUN_LAST_28D` | `continuity_state = deep_reprise` |
| `RECENT_VOLUME_FAR_BELOW_BASELINE` | `continuity_state = partial_reprise` |
| `RECENT_VOLUME_RECOVERING` | `continuity_state = reprise_exit` |
| `CONTINUITY_STABLE` | `continuity_state = normal` |
| `LOAD_UNAVAILABLE` | `load_state = unavailable` |
| `LOAD_VERY_LOW` | `load_state = very_low` |
| `LOAD_LOW` | `load_state = low` |
| `LOAD_BALANCED` | `load_state = balanced` |
| `LOAD_ELEVATED` | `load_state = elevated` |
| `LOAD_HIGH` | `load_state = high` |

---

## Constantes et seuils

| Constante | Valeur | Fichier |
|---|---|---|
| `NO_RUN_DEEP_REPRISE_DAYS` | `28` | `training_state.py` |
| `PARTIAL_REPRISE_VOLUME_RATIO` | `0.50` | `training_state.py` |
| `REPRISE_EXIT_STABLE_WEEKS` | `4` | `training_state.py` |
| `CONTINUITY_CONF_LOW_MIN_DAYS` | `1` | `training_state.py` |
| `CONTINUITY_CONF_MEDIUM_MIN_DAYS` | `30` | `training_state.py` |
| `CONTINUITY_CONF_HIGH_MIN_DAYS` | `90` | `training_state.py` |

---

## Fichiers modifiés

| Fichier | Rôle |
|---|---|
| `backend/training_v2/training_state.py` | Nouveau module : modèle `TrainingState` + `build_training_state` |
| `backend/training_v2/__init__.py` | Export de `TrainingState` et `build_training_state` |
| `backend/tests/test_training_state_pr04.py` | 31 tests couvrant tous les cas requis |
| `TRAINING_STATE_PR04_REPORT.md` | Ce rapport |

Aucun fichier legacy (`training_engine.py`, `training_load_engine.py`, `llm_coach.py`, `coach_service.py`, `server.py`) n'a été modifié.

---

## Tests exécutés

### Nouveaux tests PR04

```
python -m pytest tests/test_training_state_pr04.py -q
```

**Résultat : 31 passed in 0.55s**

### Non-régression

```
python -m pytest tests/test_runner_profile_pr07.py tests/test_training_v2_training_load.py tests/test_training_history_pr05.py tests/test_garmin_data_layer.py -q
```

**Résultat : 155 passed in 0.77s**

### Vérification syntaxique

```
python -m py_compile training_v2/training_state.py training_v2/__init__.py
```

**Résultat : OK (aucune erreur)**

---

## Couverture des cas testés

1. ✅ Aucun historique → `no_history`, `days_since_last_run=None`, `continuity_confidence=none`
2. ✅ Profil déclaré mais sans historique → `no_history`
3. ✅ Deep reprise (y compris limite exacte à 28 jours)
4. ✅ Partial reprise (volume observé < 50 % baseline)
5. ✅ Reprise exit (frontière partial_reprise / reprise_exit / normal)
6. ✅ Normal
7. ✅ Normal + charge élevée (test architectural d'indépendance)
8. ✅ Partial reprise + charge élevée (axes indépendants)
9. ✅ ACWR absent → `None`, `load_state=unavailable`
10. ✅ Confidence aux frontières : 0, 1, 29, 30, 89, 90 jours
11. ✅ Overall confidence = minimum des deux
12. ✅ Reason codes pour chaque état
13. ✅ Immutabilité du modèle Pydantic
14. ✅ Déterminisme (deux appels identiques → résultat identique)
15. ✅ Absence d'imports legacy (AST check)
16. ✅ `load_state` et `acwr` reflètent exactement `TrainingLoadSnapshot`

---

## Limites connues

- **`reprise_exit` boundary**: La frontière entre `reprise_exit` et `normal` dépend de la densité d'activités sur 30 jours (`window_30d.activity_count < 12`). Ce seuil est conservateur et pourra être affiné avec des données réelles en PR suivante.
- **Baseline déclarée ignorée**: Si `runner_profile.typical_weekly_km` vient uniquement du profil déclaré (sans historique), aucune comparaison de volume n'est effectuée. La règle `partial_reprise` ne s'applique pas dans ce cas. Ceci est conforme au principe V2 : absence de données ≠ valeur normale.
- **`available_history_days` convention**: Héritée de PR05 : `(ref_date - first_run_date).days`. Une seule sortie le jour même = 0 jour → confidence `"none"`. Si la spec souhaite "1 sortie = low", il faudra ajuster cette convention dans `training_history.py` (hors scope PR04).
- **Load metrics (`acute_load`, `chronic_weekly_load`)**: Retournés `None` si `training_load.is_available == False`. Aucun fallback inventé.

---

## Corrections PR04 / PR #94 (2026-08-07)

### Correction 1 — Provenance de la baseline (BLOQUANT)

**Problème** : `_observable_baseline_km` utilisait `available_history_days > 0` pour décider si `typical_weekly_km` est observable. Cette heuristique était incorrecte : `available_history_days > 0` signifie seulement qu'il existe au moins une activité quelque part dans l'historique — elle ne garantit pas que `typical_weekly_km` a été calculé à partir des fenêtres `window_30d` ou `window_90d`.

Si ces deux fenêtres sont vides (toutes les activités sont plus vieilles que 90 jours), `_history_metric_or_declared` retombe sur la valeur déclarée, mais `available_history_days > 0` reste vrai → la valeur déclarée était utilisée comme baseline. Violation de "declared weekly km ≠ observed baseline".

**Correction** :

1. `RunnerProfile` expose maintenant un flag `typical_weekly_km_is_observed: bool` (champ Pydantic, documenté).  
   - `True` : valeur issue d'une fenêtre historique (30d ou 90d).  
   - `False` : valeur déclarée uniquement, ou `None`.  
   - Calculé dans `_history_metric_or_declared` qui retourne désormais `(value, is_observed)`.

2. `_observable_baseline_km` dans `training_state.py` utilise `runner_profile.typical_weekly_km_is_observed` au lieu de `available_history_days > 0`.

**Règle** : Si `typical_weekly_km_is_observed is False` → `_observable_baseline_km` retourne `None` → aucun test `partial_reprise` / `reprise_exit` basé sur le volume n'est effectué.

**Tests ajoutés** :
- `test_declared_baseline_no_history_no_partial_reprise` : profil déclaré 40 km/semaine, aucun historique → `no_history`, jamais `partial_reprise`.
- `test_declared_baseline_not_used_as_observable_baseline` : 1 sortie récente (5 km) + déclaré 40 km/semaine → `is_observed=True`, baseline = 1.17 km/week (observé), PAS 40 km/week (déclaré).
- `test_no_history_typical_weekly_km_is_observed_false` : aucun historique → `is_observed=False`.

---

### Correction 2 — Renommage `recent_28d_km` → `recent_30d_km`

**Problème** : Le champ `recent_28d_km` de `TrainingState` était alimenté par `training_history.window_30d.distance_km` (fenêtre de **30 jours**). L'étiquette était fausse.

**Correction** :
- `TrainingState.recent_28d_km` → `TrainingState.recent_30d_km` (modèle Pydantic, build function, commentaires).
- Aucune nouvelle fenêtre 28 jours n'est créée. La fenêtre `window_30d` existante est conservée.

---

### Correction 3 — Frontière `reprise_exit` déterministe

**Problème** : `test_partial_reprise_to_reprise_exit_boundary` testait `continuity_state in ("reprise_exit", "normal")` — un test non-déterministe qui ne valide pas la règle métier.

**Correction** : Le test est remplacé par `== "reprise_exit"` avec calcul arithmétique explicite démontrant pourquoi ce scénario produit exactement `reprise_exit`.

**Règle exacte `partial_reprise → reprise_exit → normal`** (inchangée, rendue visible) :

```
if recent_weekly < 50% × baseline_observed:
    → partial_reprise

elif available_history_days < REPRISE_EXIT_STABLE_WEEKS × 7:  # < 28 jours
    if w7.activity_count > 0:
        → reprise_exit

elif (recent_weekly < baseline AND w30.activity_count < 12):
    → reprise_exit

else:
    → normal
```

Cas de frontière testés avec `==` (scénario contrôlé : 10 runs jours 8–29, 10 km chacun) :
- `test_partial_reprise_volume_below_50pct` : récent = 12 km < 13.07 = 50% de 26.13 → `partial_reprise`.
- `test_reprise_exit_volume_above_50pct_sparse_w30` : récent = 15 km > 13.42, `w30.count = 11 < 12` → `reprise_exit`.
- `test_normal_volume_above_50pct_dense_w30` : récent = 15 km, `w30.count = 12 ≥ 12` → `normal`.

---

### Fichiers modifiés (corrections PR #94)

| Fichier | Modification |
|---|---|
| `backend/training_v2/runner_profile.py` | Nouveau champ `typical_weekly_km_is_observed: bool` + `_history_metric_or_declared` retourne `(value, is_observed)` |
| `backend/training_v2/training_state.py` | `_observable_baseline_km` utilise `is_observed`, `recent_28d_km` → `recent_30d_km` |
| `backend/tests/test_training_state_pr04.py` | 6 tests ajoutés, 1 test corrigé (`in` → `==`) |
| `TRAINING_STATE_PR04_REPORT.md` | Ce rapport |

---

### Résultats des tests (2026-08-07)

```
python -m pytest tests/test_training_state_pr04.py -q
```
**37 passed in 0.54s**  (31 originaux + 6 nouveaux)

```
python -m pytest tests/test_training_state_pr04.py tests/test_training_history_pr05.py tests/test_runner_profile_pr07.py -q
```
**129 passed in 0.58s**
