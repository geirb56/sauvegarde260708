# RUNINDEX PR #137 — Daily Runtime Migration V2

## Résumé

Migration du chemin runtime de la recommandation quotidienne vers la chaîne V2 :

```
ReadinessResult V2
      ↓
ReadinessDecision V2
      ↓
DailyAdaptation V2
      ↓
/training/today
```

---

## 1. Ancien chemin /training/today

```
plan V2 (#135)
  ↓
sessions runtime dict (aujourd'hui)
  ↓
get_run_index()  ← appel complet run-index + Garmin
  ↓
recommendation string ("RUN HARD" / "EASY RUN" / "REST")
  ↓
adapt_session_to_readiness(planned_session, recommendation, …)  ← LEGACY training_engine.py
  ↓
adaptive_session dict
```

Problèmes du chemin legacy :

- `adapt_session_to_readiness` contient ses propres seuils numériques (`run_readiness < 40`) ;
- la décision était basée sur une chaîne texte ("RUN HARD"), pas sur un contrat V2 ;
- `get_run_index()` était appelé entier (charge complète) pour extraire un seul champ ;
- None était traité différemment de l'absence (risque de REST automatique) ;
- les recalculs de VMA/paces dans la fonction legacy étaient hors contrat V2.

---

## 2. Nouveau chemin /training/today

```
generate_dynamic_training_plan()   ← plan V2 (#135), caché selon son propre TTL
  ↓
sessions runtime dict (aujourd'hui)
  ↓
runtime_session_to_prescription()  ← helper pur training_v2/daily_runtime_helpers.py
  ↓
WorkoutPrescription V2
  ↓
garmin_daily_metrics + garmin_activities  ← fetch Garmin direct (date anchor = today)
  ↓
build_training_load(activities, today)  ← TrainingLoadSnapshot V2
  ↓
build_readiness_v2_from_garmin_data(…, load_snapshot=…)  ← ReadinessResult V2
  ↓
build_recent_training_response(activities, today)  ← RecentTrainingResponse V2 (#132)
  ↓
build_readiness_decision(readiness_result)  ← ReadinessDecision V2 (#133)
  ↓
build_daily_adaptation(workout, readiness_decision, training_load, recent_response)  ← moteur #133
  ↓
DailyAdaptationResult (action, original_workout, adapted_workout, reason_codes)
  ↓
prescription_to_runtime_session()  ← helper pur
  ↓
payload /training/today
```

---

## 3. Source de la séance originale

La séance prévue provient de `generate_dynamic_training_plan()` (plan V2, #135).

Chaîne interne de la fonction :
`TrainingHistory → RunnerProfile → TrainingState → PlanGoal → Periodization → WeeklyTarget → WeeklyReconciliation → WorkoutGenerator → WeeklyPlan → adapt_weekly_plan_to_runtime_payload → sessions dict`

La session du jour est trouvée par `session.get("day").lower() == day_name.lower()`.

Elle est ensuite convertie en `WorkoutPrescription` via `runtime_session_to_prescription()`.

**Aucune nouvelle séance n'est générée dans `/training/today`.**

---

## 4. Source ReadinessResult

`build_readiness_v2_from_garmin_data(metrics_docs, garmin_activities, today, load_snapshot=training_load)`

- `metrics_docs` : `garmin_daily_metrics` triés newest-first, limit 30
- `garmin_activities` : `garmin_activities` triés newest-first, limit 200
- `today` : déterminé à la frontière du runtime (pas de `now()` dans les couches pures)
- `load_snapshot` : calculé une seule fois, partagé avec ReadinessResult (pas de double computation)

Si pas de connexion Garmin : `readiness_result = None` → `ReadinessDecision.band = UNAVAILABLE`.

---

## 5. Mapping ReadinessDecision

`build_readiness_decision(readiness_result)` — aucun seuil numérique dans l'endpoint.

| ReadinessBand | Condition canonique #133 |
|---|---|
| UNAVAILABLE | score is None OR sufficiency == INSUFFICIENT |
| FAVORABLE | score >= 75 |
| CAUTION | 55 <= score < 75 |
| LOW | 40 <= score < 55 |
| VERY_LOW | score < 40 |

---

## 6. Appel DailyAdaptation V2

```python
build_daily_adaptation(
    workout=planned_prescription,        # WorkoutPrescription V2
    readiness_decision=readiness_decision,  # ReadinessDecision V2
    training_load=training_load,         # TrainingLoadSnapshot V2 (ou None)
    recent_response=recent_response,     # RecentTrainingResponse V2 (ou None)
)
```

Actions possibles : `KEEP | EASY_DOWNGRADE | SHORTEN | REST`

---

## 7. Mapping compatibility payload

| Champ frontend | Source V2 |
|---|---|
| `planned_session` | runtime dict du plan V2 (inchangé) |
| `adaptive_session` | `prescription_to_runtime_session(adaptation_result.adapted_workout)` (si action != KEEP) |
| `adaptation_applied` | `adaptation_result.action != DailyAdaptationAction.KEEP` |
| `adaptation_reason` | `", ".join(adaptation_result.reason_codes)` |
| `adaptation_action` | `adaptation_result.action.value` (NOUVEAU) |
| `reason_codes` | `list(adaptation_result.reason_codes)` (NOUVEAU) |
| `readiness.band` | `readiness_decision.band.value` (NOUVEAU) |
| `readiness.score` | `readiness_decision.score` (NOUVEAU) |
| `fatigue.run_readiness` | `readiness_decision.score` (dérivé V2) |
| `fatigue.recommendation` | `BAND_TO_RECOMMENDATION[readiness_decision.band][0]` (dérivé V2) |
| `fatigue.recommendation_color` | `BAND_TO_RECOMMENDATION[readiness_decision.band][1]` (dérivé V2) |
| `fatigue.data_source` | `"garmin"` ou `"unavailable"` |
| `vma` | `plan.get("vma")` (inchangé) |
| `vma_confidence` | `plan.get("vma_confidence")` (inchangé) |
| `recent_feedback` | DB `training_feedback` (inchangé) |

### Champs legacy supprimés du chemin décisionnel

Ces champs ne sont plus calculés dans `/training/today` :

- ~~`fatigue_ratio`~~ — supprimé (#129)
- ~~`fatigue_status`~~ — supprimé (#129)
- ~~`fatigue_physio`~~ — supprimé (#129)

### Champs legacy restants temporairement

- `fatigue.recommendation` et `fatigue.recommendation_color` — maintenus par compatibilité frontend.
  **Direction : ReadinessDecision V2 → adapter compat. Jamais legacy → V2.**
  Mapping exact :
  - `FAVORABLE` → `"RUN HARD"`, `"green"`
  - `CAUTION` → `"EASY RUN"`, `"yellow"`
  - `LOW` → `"EASY RUN"`, `"yellow"`
  - `VERY_LOW` → `"REST"`, `"red"`
  - `UNAVAILABLE` → `"UNAVAILABLE"`, `"gray"`

---

## 8. Comportement REST

Séance originale de type `"rest"` → `DailyAdaptationAction.KEEP`.
Aucune séance n'est ajoutée.
`PLANNED_REST_DAY` dans `reason_codes`.

---

## 9. Comportement UNAVAILABLE

`ReadinessResult.sufficiency_level == INSUFFICIENT` → `ReadinessDecision.band == UNAVAILABLE`.

`UNAVAILABLE` n'est pas `VERY_LOW`.
`build_daily_adaptation` ne produit pas `REST` pour une bande `UNAVAILABLE`.
`None ≠ 0` : absence de données ≠ mauvaise récupération.

---

## 10. Comportement bonne readiness

`score >= 75` → `ReadinessBand.FAVORABLE` → `DailyAdaptationAction.KEEP`.
La séance n'est jamais augmentée en difficulté.

---

## 11. Comportement mauvaise readiness

| Bande | Session | Action |
|---|---|---|
| VERY_LOW | n'importe | REST |
| LOW/CAUTION | quality/steady | EASY_DOWNGRADE |
| LOW/CAUTION | easy/long_easy | SHORTEN (×0.70) |
| LOW/CAUTION | rest | KEEP |

---

## 12. Preuve aucune augmentation

- `SHORTEN_FACTOR = 0.70` — réduction uniquement
- `adapted_duration <= original_duration` (vérifié par tests F, W)
- `adapted_distance <= original_distance` (vérifié par tests G, W)
- Aucune action `INCREASE / UPGRADE / HARDEN / CATCH_UP / MOVE` dans l'enum (tests I, J)

---

## 13. Stratégie cache quotidienne

Le plan hebdomadaire est caché par `generate_dynamic_training_plan()` (TTL 3600s, clé déterministe).

**L'adaptation quotidienne n'est pas cachée.** Elle dépend du readiness du jour, calculé à partir des données Garmin en temps réel.

Architecture :
- `_plan_cache[cache_key]` → plan caché (acceptable : structure hebdomadaire stable)
- Garmin metrics/activities → fetchés à chaque appel `/training/today` (fraîcheur readiness)
- Pas de cache d'adaptation dans cette PR

---

## 14. Fichiers modifiés

| Fichier | Type | Description |
|---|---|---|
| `backend/server.py` | Modification | Endpoint `/training/today` migré vers V2 |
| `backend/training_v2/daily_runtime_helpers.py` | Création | Helpers purs : conversion WorkoutPrescription ↔ runtime dict |
| `backend/tests/test_daily_runtime_pr137.py` | Création | 42 tests unitaires A–W |
| `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md` | Modification | #135 MERGED, #136 MERGED, #137 IMPLEMENTED/PENDING MERGE |

---

## 15. Tests

### Nouveaux tests #137 (42)

| Test | Description |
|---|---|
| A | REST prévu → KEEP |
| B | Readiness UNAVAILABLE → pas de REST automatique |
| C | Bonne readiness → KEEP, pas d'augmentation |
| D | Mauvaise readiness → downgrade conforme #133 |
| E | SHORTEN factor = 0.70 exact |
| F | Durée adaptée jamais supérieure (paramétrique) |
| G | Distance adaptée jamais supérieure (paramétrique) |
| H | allow_intensity=False → pas d'intensité ajoutée |
| I | Pas d'action MOVE |
| J | Pas d'action INCREASE/UPGRADE/HARDEN/CATCH_UP |
| K–N | Conversion runtime dict ↔ WorkoutPrescription |
| O | Garde-fou : pas de seuils numériques dans l'endpoint |
| P–R | Mapping BAND_TO_RECOMMENDATION complet et correct |
| S | Pas de fatigue_ratio/fatigue_status/fatigue_physio dans le payload |
| T | Pas d'appel adapt_session_to_readiness dans l'endpoint |
| U | None readiness → UNAVAILABLE (jamais VERY_LOW) |
| V | parse_duration_minutes (paramétrique) |
| W | Monotonicity sweep paramétrique |

### Tests existants

- `test_daily_adaptation_pr133.py` : 24 passent ✅
- `test_training_v2_readiness_decision.py` : passent ✅
- `test_training_response_pr132.py` : passent ✅

**Total tests exécutés : 106 passed (+ 42 nouveaux = 148)**

---

## 16. Limitations

- **Smoke test runtime non exécuté** : pas de base de données Garmin disponible dans l'environnement sandbox.
- **Frontend smoke test non exécuté** : aucun navigateur accessible.
- `fatigue.recommendation` et `fatigue.recommendation_color` maintenus temporairement pour compatibilité frontend (direction V2 → compat, jamais l'inverse).
- Le plan hebdomadaire étant caché, si les données Garmin changent intra-cache (< 1h), le plan reste le même mais l'adaptation est recalculée à partir du readiness frais.

---

## 17. Confirmation

- ✅ Aucune formule V2 modifiée
- ✅ Aucun seuil ReadinessDecision modifié
- ✅ Aucune règle DailyAdaptation modifiée
- ✅ Aucun fallback legacy ajouté
- ✅ `fatigue_ratio` / `fatigue_status` / `fatigue_physio` absents du payload
- ✅ Pas de MOVE, pas de INCREASE, pas de rattrapage
- ✅ None ≠ 0 tout au long du chemin
- ✅ SHORTEN_FACTOR = 0.70 non modifié
- ✅ `adapt_session_to_readiness` non appelé dans `/training/today`

## 18. NEXT après #137 (roadmap canonique)

1. **#138 — performance extraction/audit** : extraction de `performance.py`, audit des consumers VMA/paces
2. **#139 — kill `training_engine.py`** : suppression complète après audit consumers
3. Ensuite seulement : LT1/LT2 multi-évidence, Body Battery nocturne, V3 Flexible Schedule

---

## 19. Correction frontière Mongo → DomainActivity (correction ciblée PR137)

### Problème identifié à l'audit

Dans `/training/today`, les documents bruts de `garmin_activities` (MongoDB) étaient transmis directement à :

- `build_training_load(garmin_activities, today)`
- `build_readiness_v2_from_garmin_data(metrics_docs, garmin_activities, today, ...)`
- `build_recent_training_response(garmin_activities, today)`

La shape MongoDB réelle comporte un sous-document normalisé `garmin_activity` avec les champs canoniques (`average_hr`, `max_hr`, `moderate_intensity_minutes`, `vigorous_intensity_minutes`, `elevation_gain`), tandis que le niveau racine utilise des alias hérités (`avg_hr`, `distance`, `duration`).

La conversion `to_domain_activity()` de `training_v2/domain_activity.py` ne consultait pas ce sous-document. Conséquence : `average_hr`, `max_hr`, `moderate_intensity_minutes`, `vigorous_intensity_minutes`, `elevation_gain_m` étaient perdus pour `RecentTrainingResponse` (cardiac efficiency, intensity exposure, elevation comparability guard).

`build_training_load` n'était pas impacté car il n'utilise que `activity_type`, `start_time`, `distance_m`/`duration_s` (déjà couverts par les alias existants).

### Correction réalisée

**Fichier modifié :** `backend/garmin/domain_adapter.py`

Ajout de deux fonctions constituant la frontière explicite Mongo → Training V2 :

- `mongo_garmin_to_domain(doc: dict) -> DomainActivity`
- `mongo_garmin_activities_to_domain(docs: list) -> list[DomainActivity]`

**Fichier modifié :** `backend/server.py`

Dans `/training/today`, conversion explicite avant tout appel aux modules V2 :

```
garmin_activities (Mongo bruts)
    ↓
mongo_garmin_activities_to_domain(garmin_activities)
    ↓
domain_activities : list[DomainActivity]
    ↓
build_training_load(domain_activities, today)
build_readiness_v2_from_garmin_data(metrics_docs, domain_activities, today, load_snapshot=training_load)
build_recent_training_response(domain_activities, today)
```

### Mapping exact des champs (Mongo → DomainActivity)

| Source (subdoc `garmin_activity`) | Alias racine fallback | DomainActivity |
|---|---|---|
| `activity_type` | `activity_type` | `activity_type` |
| `start_time` | `start_time` | `start_time` |
| `distance_m` | `distance` | `distance_m` |
| `duration_s` | `duration` | `duration_s` |
| `average_hr` | `avg_hr` | `average_hr` |
| `max_hr` | `max_hr` | `max_hr` |
| `moderate_intensity_minutes` | `moderate_intensity_minutes` | `moderate_intensity_minutes` |
| `vigorous_intensity_minutes` | `vigorous_intensity_minutes` | `vigorous_intensity_minutes` |
| `elevation_gain` | `elevation_gain` | `elevation_gain_m` ← **renommage explicite** |

Priorité : sous-document `garmin_activity` > champ racine. None ≠ 0 respecté.

### Tests ajoutés

Fichier : `backend/tests/test_mongo_garmin_boundary_pr137.py` — 33 tests

| Cas | Description | Résultat |
|---|---|---|
| A | Document avec `garmin_activity` complet | 10 tests ✅ |
| B | Document legacy sans `garmin_activity` | 7 tests ✅ |
| C | Champ absent → None, jamais valeur inventée | 9 tests ✅ |
| D | `average_hr` de `garmin_activity` préservé | 1 test ✅ |
| E | Intensity minutes préservées | 1 test ✅ |
| F | Régression TrainingLoad (résultats identiques) | 1 test ✅ |
| G | `/training/today` utilise `mongo_garmin_activities_to_domain` | 1 test ✅ |
| Extra | List converter (vide, None, multiple) | 3 tests ✅ |

**Total nouveaux tests : 33 — 33 passed, 0 failed**

### Suite tests existants après correction

- `test_daily_runtime_pr137.py` : 50 passed ✅
- `test_training_metrics_pr127.py` : 33 passed ✅
- `test_mongo_garmin_boundary_pr137.py` : 33 passed ✅
- **Total combiné : 116 passed, 0 failed**

### Limitations restantes

- Smoke test runtime non exécuté (pas de base MongoDB Garmin disponible en sandbox).
- `insights.py` (`compute_run_index`) passe encore des Mongo bruts à `build_training_load` et `build_readiness_v2_from_garmin_data` : impact limité car `build_training_load` est robuste aux alias top-level et `build_readiness_v2_from_garmin_data` n'utilise `activities` que comme fallback load (ignoré quand `load_snapshot` fourni). Correction `insights.py` prévue en #138.

### Roadmap corrigée

1. **#138 — audit exhaustif des consumers legacy restants** : `server.py` (`/training/metrics`), `insights.py`, `llm_coach.py`, `training_engine.py` — appliquer la même frontière `mongo_garmin_activities_to_domain` partout
2. **#139 — migration/suppression des derniers consumers legacy identifiés**
3. **#140 — kill `training_engine.py` UNIQUEMENT après preuve zéro consumer runtime réel**
4. Ensuite : LT1/LT2 multi-évidence, Body Battery nocturne, V3 Flexible Schedule

### Confirmation

- ✅ Aucune formule métier V2 modifiée
- ✅ Aucun seuil ReadinessDecision modifié (75 / 55 / 40 inchangés)
- ✅ Aucune règle DailyAdaptation modifiée (SHORTEN_FACTOR = 0.70 inchangé)
- ✅ `training_engine.py` non supprimé dans #137
- ✅ `adapt_session_to_readiness` non réintroduit
- ✅ Pas de fabrication de données Garmin absentes
- ✅ None ≠ 0 respecté
- ✅ Frontend non modifié
- ✅ Architecture #137 conservée

