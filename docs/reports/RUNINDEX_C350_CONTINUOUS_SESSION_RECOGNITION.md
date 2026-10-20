# RUNINDEX C350 — Reconnaissance fiable des séances continues

- Base : `copilot/dev` @ `e425c086533cdce574f52531e9f83f9fa276e3c1`
- Head : branche `copilot/runindex-c350-reconnaissance-seances` (commit final de la PR)
- Statut : PR draft. Pas de merge, pas de déploiement.

## Verdict

**Les données disponibles ne prouvent pas qu’une course sans phases Garmin est continue.**
Les critères n’ont donc pas été assouplis. Le 12/10 et le 19/10 restent `unknown`.

Le livrable contient :

1. un diagnostic déterministe des laps, qui documente le blocage ;
2. l’application des critères actuels aux références historiques, en lecture seule ;
3. les tests demandés ;
4. **la correction C350-B (§ 7)** : une observation historique descriptive `distance_only` est autorisée sans structure prouvée, mais jamais une conclusion forte. Le 12/10 obtient ainsi une observation si le type Garmin précis est fiable pour la séance et ses références.

## 1. Audit

### `_session_structure()` (`backend/workout_analysis_v2.py`)

| Ordre | Condition | Résultat |
|---|---|---|
| 1 | Phases typed-splits avec une récupération entre deux efforts | `intervals` |
| 2 | Phases disponibles, une seule phase `effort` couvrant la durée du résumé (±1 %) | `continuous` |
| 3 | Phases disponibles avec au moins un type connu | `other` |
| 4 | Aucune phase disponible et `workouts.session_structure == "continuous"` | `continuous` |
| 5 | Sinon | `unknown` |

### Sources réellement disponibles

| Source | Contenu | Peut prouver la continuité ? |
|---|---|---|
| `activity_details` (typed-splits v2) | `INTERVAL_*` → effort/récupération/échauffement/retour au calme. Les lignes `RWD_*` sont filtrées et ne sont pas persistées. | **Oui**, uniquement pour un entraînement structuré à une seule étape. Pour une course libre, il n’y a aucune ligne `INTERVAL_*`, donc on observe une **absence** de phases, pas une preuve. |
| `activity_laps` (splits v1) | Agrégats par lap : distance, durées, horodatage, vitesse, FC, `intensity_type` opaque | **Non** (voir § 3) |
| `workouts.session_structure` | Champ explicite | Oui, mais il n’est jamais renseigné en production |
| Nom, allure, FC | — | Exclus par principe |

Le rapport `RUNINDEX_GARMIN_LAPS_PAYLOAD_VALIDATION.md` confirme deux points :

- une course continue réelle enregistre `intensityType = "ACTIVE"` sur 22 laps sur 22 ;
- le schéma ne contient **aucun champ de déclenchement** (`lapTrigger` manuel ou automatique).

## 2. Modifications

| Fichier | Changement |
|---|---|
| `backend/garmin_laps_analysis.py` | Ajout des constantes `CHRONOLOGY_TOLERANCE_S = 1`, `SUMMARY_DISTANCE_TOLERANCE_M = 5` et `SUMMARY_DURATION_TOLERANCE_S = 30`. Elles remplacent les littéraux, sans changer leurs valeurs. Ajout de `assess_lap_structure()` et de `LapStructureAssessment`, un diagnostic pur, sans mutation, dont le statut vaut toujours `unknown`. |
| `backend/workout_analysis_v2.py` | Ajout de `_reference_is_continuous()`. Chaque référence historique est jugée par **le même `_session_structure()`** que la séance courante, avec ses phases typed-splits si elles sont fournies. Ajout du paramètre optionnel `historical_phases` (keyword-only) à `build_workout_analysis_v2`. Aucun changement du contrat de réponse. |
| `backend/workout_analysis_v2_service.py` | Ajout de `_historical_activity_phases()`. Une seule requête `find` en lecture sur `garmin_activities`, avec la projection `{external_id, activity_details}`, limitée aux références retenues (≤ 5). Les phases passent par la validation `_cached_activity_phases`. En cas de documents ambigus, invalides ou d’erreur de lecture, aucune phase n’est retenue et le statut reste `unknown`. |
| `backend/tests/test_continuous_structure_c350.py` | 49 tests. |

Aucune écriture Mongo et aucune reclassification rétroactive. Le contrat V2, y compris les tests qui fixent ses clés, est inchangé. L’invariant C343 « sans laps, l’analyse est identique » est préservé.

### Non-régression de l’invariant C349-B

Une référence portant `session_structure = "continuous"` sans phases reste `continuous_recorded`, comme avant. Si des phases validées contredisent ce champ, les phases priment, comme pour la séance courante. Le résultat ne peut alors être que plus strict.

## 3. Critères examinés sur les laps (`assess_lap_structure`)

Les contrôles s’exécutent dans un ordre fixe. Le diagnostic ne lit ni l’allure ni la FC, et n’applique aucun seuil physiologique. L’homogénéité des laps n’est jamais retenue comme preuve.

| Raison | Condition |
|---|---|
| `not_garmin`, `activity_missing`, `laps_missing`, `laps_empty`, `laps_invalid`, `summary_missing` | Données insuffisantes ou invalides. Le contrôle s’arrête et cette raison est la seule renvoyée. |
| `chronology_missing` / `chronology_incomplete` / `chronology_incoherent` | Horodatages tous absents, partiels, ou incohérents au-delà de **1 s** (tolérance C349-A inchangée), en local comme en cumul |
| `pause_unverifiable` | `moving_duration_s` ou `elapsed_duration_s` absent |
| `pause_recorded` | `elapsed > duration` (chronomètre arrêté) |
| `stationary_time_recorded` | `moving < duration` |
| `time_incoherent` | `moving > duration` ou `elapsed < duration` |
| `intensity_missing` | Au moins un lap sans `intensity_type` |
| `intensity_variation_recorded` | Valeur explicite autre qu’`ACTIVE`. C’est un indice d’alternance, **jamais** traduit en effort ou en récupération. |
| `coverage_incomplete` | La somme des laps ne couvre pas le résumé (5 m / 30 s) |
| `intra_lap_alternation_unobservable` | **Toujours ajoutée en dernier** quand les laps sont lisibles |

### Pourquoi des laps parfaits ne suffisent pas

Un lap est un agrégat. Un fartlek libre enregistré en autolap au kilomètre produit lui aussi des laps `ACTIVE`, contigus, sans pause et couvrant toute la séance. Sans déclencheur de lap ni série infra-lap, aucune donnée ne permet d’exclure une alternance effort/récupération à l’intérieur d’un lap.

Distinguer les deux cas par l’allure exigerait un seuil, c’est-à-dire un jugement d’entraînement, ce qui est hors périmètre. Le diagnostic n’est donc **pas branché** sur la classification ni exposé par l’API. Il est appelable pour l’audit et les tests.

## 4. Cas acceptés et refusés

| Cas | Structure | Conclusion historique |
|---|---|---|
| Une seule phase typed-splits `effort` couvrant la séance, références prouvées continues | `continuous` | `strong` |
| Même séance, références sans preuve | `continuous` | `distance_only` (descriptive) |
| Séance enregistrée `continuous`, avec une référence en fractionné, en phase partielle ou en phase `unknown` | `continuous` | La référence fait passer le statut à `unknown` |
| Fractionné typed-splits (effort/récupération), même avec des références continues | `intervals` | Aucune |
| Effort unique ne couvrant pas la séance | `other` | Aucune |
| **12/10** synthétique : 9,33 km, 10 laps `ACTIVE` cohérents, sans pause, 5 références | `unknown` (`intra_lap_alternation_unobservable`) | Jamais `strong`. Depuis § 7 : une observation `descriptive` / `distance_only` si le type Garmin précis est fiable et identique ; sinon aucune |
| **19/10** tapis : aucune phase, aucune référence | `unknown` | **Aucune** conclusion Coach |
| Laps incomplets, pauses, temps immobile, chronologie incohérente (1,058 s / 2 s / −2 s), horodatages partiels, intensité absente ou variée | `unknown` (raisons dédiées) | Aucune |
| Nom « Footing continu », allure ou FC | Jamais promus | — |

## 5. Tests

- Nouveaux : `python -m pytest tests/test_continuous_structure_c350.py`, **49 passed**.
- Suites ciblées (incluant C350) : C349-B, coach language, C343, C342, workout_analysis_v2*, PR328, PR234 et coach context v2. Résultat : **1426 passed, 2 skipped, 3 failed**. Les 3 échecs sont préexistants et identiques sur la base : `test_comparable_history_stays_separate_and_metrics_are_unchanged[fr|en|es]`.
- Suite backend complète, avant et après : les échecs dépendent de l’environnement (absence de Redis/Mongo/serveur). Les différences observées concernent `test_trial_expiration_enforced.py` et `test_training_cycle_start_date_endpoint.py`, qui dépendent de l’ordre d’exécution xdist. Exécutés seuls, ces fichiers passent (10/10) avant comme après.

## 6. Limites et source supplémentaire nécessaire

Pour reconnaître une course libre comme continue, il faut au moins une **preuve positive** parmi les suivantes :

1. **Déclaration explicite de l’athlète**, persistée dans `workouts.session_structure`. Le chemin est déjà accepté par V2 et par C349-B ; il manque seulement la saisie produit (« séance continue, sans fractions ni arrêts : oui/non »).
2. **Entraînement structuré Garmin à une seule étape**. Il est déjà reconnu via typed-splits ; il suffit de l’utiliser pour les footings.
3. **Lignes typed-splits `RWD_*` persistées**, aujourd’hui filtrées. Elles permettraient seulement d’exclure la marche ou l’arrêt, pas une alternance de course. Elles sont donc insuffisantes seules.
4. **Série temporelle infra-lap** (endpoint Garmin activity details, vitesse par échantillon) ou **`lapTrigger` FIT**. Même avec ces données, une définition non physiologique et validée de l’« absence de récupération » resterait à établir avant tout usage.

Les payloads réels du 12/10 et du 19/10 n’étant pas dans le dépôt, la vérification porte sur des fixtures synthétiques de même forme. Aucune donnée réelle n’a été lue ni écrite.

## 7. Correction C350-B — observations factuelles sans structure connue

### Changements

| Fichier | Changement |
|---|---|
| `backend/coach_language.py` | `_history_choice(workout, similar, session_structure, environment)`. Sans structure `continuous` prouvée, seule la portée `distance_only` (`kind=descriptive`) reste possible. Elle est refusée si la structure est connue comme non continue : signal V2 `intervals`/`other`, ou `workouts.session_structure` ∈ {`intervals`, `other`}. Une métrique n’est admise que si `environment[metric] == "same_known"`. La portée `strong` exige toujours `continuous` + nature identique connue + références `continuous_recorded`. Ajout d’une métadonnée `session_structure` (`continuous`/`unknown`) sur les observations historiques. |
| `backend/workout_analysis_v2.py` | Ajout de `_metric_populations()`, qui factorise les populations allure/FC de C349-B, et de `_environment_status()` / `_history_environment()`, calculés par métrique sur sa propre population. Ajout du paramètre keyword-only `activity_types` de `build_workout_analysis_v2`. Ces informations sont transmises en interne à `build_coach_language` ; **le contrat API est inchangé**. |
| `backend/workout_analysis_v2_service.py` | Ajout de `_reliable_activity_type()`, qui lit le type Garmin précis (`activity_type` du document `garmin_activities`, cohérent avec `garmin_activity.activity_type`), sans jamais utiliser le nom. `_historical_garmin_sources()` remplace `_historical_activity_phases()` : même requête unique en lecture, avec la projection étendue au type. |
| `backend/tests/test_descriptive_history_c350.py` | 46 tests. |
| `backend/tests/test_continuous_structure_c350.py` | Adaptation au nouveau helper de service. |

### Critères de l’observation descriptive sans structure prouvée

1. La structure courante est inconnue. Elle n’est ni `intervals` ni `other`, que ce soit d’après les phases ou d’après l’enregistrement.
2. La métrique est fiable : valeur courante positive, écart fini, au moins **2** références dans sa propre population (C349-B).
3. Les distances sont comparables : ±30 %, même type de séance, 180 jours, références strictement antérieures (règles inchangées).
4. La comparabilité de nature vaut `strong` ou `distance_only`, puis est **plafonnée** à `distance_only`. Une course avec nature inconnue reste exclue.
5. **Environnement** : le type Garmin précis est connu pour la séance **et** pour chaque référence de la population de la métrique, et il est **identique**. Par exemple, `treadmill_running` ≠ `running`. Un type manquant, ambigu ou différent entraîne l’abstention pour cette métrique.
6. Le texte est celui de la portée limitée de C349-B, en FR, EN et ES. Il mentionne explicitement l’absence de garantie : « sans garantie de même nature ni de même structure ». Il ne parle ni de progrès, ni de fatigue, ni de dérive, ni de qualité d’exécution ; un test vérifie l’absence de ces termes.
7. Les priorités sont inchangées : 50, ou 70 si l’écart est nul. Elles passent toujours après `strong` (40). Le maximum de conclusions C348-A et la règle d’une seule observation historique sont inchangés.

Ce qui reste conditionné à une structure prouvée, sans changement :

- la conclusion historique `strong` ;
- les conclusions allure/FC par kilomètre (`_continuous_structure`) ;
- les jugements de répétitions.

### Cas couverts

| Cas | Résultat |
|---|---|
| 12/10 : 5 références `running`, séance `running` | 1 observation `coach.history.pace`, `descriptive`, `distance_only`, 21 s/km, 5 références |
| 12/10 : type absent pour la séance ou une référence | Aucune observation |
| 19/10 tapis comparé à des sorties extérieures, ou l’inverse | Aucune observation |
| 19/10 sans référence | Aucune conclusion |
| Nom « Tapis de course » sans type Garmin | Aucune observation (le nom n’est jamais lu) |
| Fractionné sans phases avec `km_splits` alternés | Ni `pacing`, ni `execution`, ni `repetitions`. L’historique reste au plus descriptif. |
| `session_structure="intervals"` enregistré, ou phases `intervals`/`other` | Aucune observation |
| Une seule référence, métriques absentes, distance incomparable, autre sport, course de nature inconnue | Abstention |
| Population allure bloquée par le type, population FC valide (et l’inverse) | Seule la métrique valide est décrite |
| Séance continue prouvée sans types (C349-B) | Comportement identique (`strong`) |

### Tests

- `tests/test_descriptive_history_c350.py` : **46 passed**. `tests/test_continuous_structure_c350.py` : **49 passed**.
- Suites ciblées : C350, C349-B, coach language, C343, C342, workout_analysis_v2*, PR328, PR234, coach context v2. Résultat : **1472 passed, 2 skipped, 3 failed**. Les 3 échecs préexistants sont inchangés : `test_comparable_history_stays_separate_and_metrics_are_unchanged[fr|en|es]`.
- Suite backend complète : aucun nouvel échec par rapport au commit précédent de la PR. Les échecs restants relèvent de l’environnement (Redis/Mongo/serveur) ou de l’ordre xdist.

### Limites

- Le type précis est conservé dans `garmin_activities.activity_type`, mais **pas** dans `workouts`, où `treadmill_running` devient `run`. Les séances non Garmin, ou dont le document source est absent ou ambigu, restent donc sans observation descriptive lorsque la structure n’est pas prouvée.
- La garde d’environnement ne s’applique qu’au nouveau chemin sans structure prouvée. Le chemin `continuous` de C349-B n’a pas été modifié, afin de préserver sa non-régression.
- L’égalité stricte des types est conservatrice : `trail_running` n’est pas comparé à `running`.
- Le fonctionnement réel dépend de la présence de `activity_type` dans les documents `garmin_activities` des références. Cela n’a pas été vérifié sur les données réelles, qui ne sont pas dans le dépôt.
- Aucune modification de la tolérance chronologique des laps, des règles de prescription ni de la politique Garmin des 10 dernières activités.
