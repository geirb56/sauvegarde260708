# PR #304 — Rapport final : Workout Analysis V2 redevient factuelle

> Document **final** de la PR GitHub **#304** (branche `copilot/runindex-pr303-reparer-analyse-sessions`,
> base `copilot/dev`). Le nom de fichier conserve `PR303` pour des raisons historiques ;
> la pull request concernée est bien **#304**.
>
> Ce rapport décrit **l'état final du code**, pas la succession des versions intermédiaires.
> Les contrats décrits ici sont ceux qui sont actifs aujourd'hui. Une courte section
> « Corrections pendant la review » rappelle ce qui a été corrigé en cours de route, sans
> reproduire les comportements supprimés comme s'ils étaient encore en vigueur.

---

## 1. État avant #304

`GET /api/coach/workout-analysis/{workout_id}` existait déjà et servait `WorkoutDetail`,
mais les PR #287/#290 avaient supprimé `analysis_engine.py` et `rag_engine.py` sans jamais
recâbler leurs capacités factuelles dans la V2.

Conséquences mesurées (comparaison avec `9b7947ec`, avant #287) :

| Capacité | Avant #287 | Sur `copilot/dev` avant #304 |
|---|---|---|
| Valeurs mesurées dans le texte | `analysis_engine.generate_session_analysis()` injectait distance, durée, allure, FC, cadence | `_build_summary/_build_meaning/_build_advice` appelaient `_template(language, key)` **sans aucun paramètre** |
| Recherche historique | `rag_engine.retrieve_similar_workouts()` : même sport, ±30 % de distance, séance courante exclue, tri par date, borné | Module supprimé. `_build_baseline()` ne filtrait que par `type` sur 14 jours, sans critère de distance |
| Exploitation des mesures déjà calculées | `pacing.*`, `physiology.hr_drift`, `comparison.*` étaient lus | Calculés et sérialisés, mais **lus par aucun générateur de texte** |

Résultat concret : des phrases fixes sans aucune valeur mesurée, et
« intensity classification is unavailable » servie comme explication principale, alors que
le payload transportait déjà splits, pace drop, consistency, dérive FC et écarts baseline.

---

## 2. Comportement final actuel

### 2.1 Analyse factuelle

- `summary` énonce distance / durée / allure (ou vitesse) et FC moyenne / max.
- `meaning` commence par les faits mesurés : amplitude des splits et **nombre réel** de splits,
  pace drop, consistency ou variabilité, `negative_split` uniquement quand `is True`, dérive FC
  **sans attribution causale**, dénivelé, cadence telle qu'enregistrée, puis les observations de
  comparaison, et se termine par la réserve sur l'intensité.
- Déterministe. Aucun `random`, aucun LLM, aucun appel réseau.

### 2.2 Non-prescription — point central

**Workout Analysis V2 ne prescrit rien.**

Il n'existe **aucune chaîne de conseils** disant à l'athlète quoi faire ensuite.
`advice` est composé d'une observation factuelle, éventuellement suivie d'une **limite explicite
de l'analyse** (`advice.complement.record_splits`, `build_history`, `use_hr`).

Les codes qui touchent à ce qui suit la séance renvoient explicitement à Training Today/Week :

> « what follows it is determined by Training Today/Week, not by this analysis. »

**Training Today/Week reste l'unique autorité de prescription.**

### 2.3 Exemples réellement générés (sortie du code final, sans historique)

Séance A — 21,27 km / 2h02 / 5:43 /km / FC 160, splits présents, zones non validées :

```
summary.long_structural
"Long-duration session completed. 21.27 km covered in 2h02 at 5:43/km.
 Average heart rate 160 bpm, peak 174 bpm."

meaning.hr_without_intensity_with_pacing
"Kilometre splits ran from 5:24/km to 6:00/km (10 splits recorded). Recorded pace drop of
 0:36/km across the session. Split consistency score: 88/100. Heart-rate drift measured at
 9 bpm between the start and the end; this measurement alone does not establish its cause.
 No earlier session of comparable distance (±30%) was found within 180 days, so no historical
 comparison is available. Heart-rate facts are available, but intensity classification is
 unavailable without trustworthy zone evidence, so this session is interpreted structurally."

advice.even_pacing
"The recorded pace drop is a useful data point to compare with future sessions of similar
 distance. Limit of this analysis: no earlier session of comparable distance is available as
 a reference point."
```

Séance B — 10,18 km / 1h11 / 6:59 /km / FC 127, sans splits :

```
summary.standard_structural
"Standard-duration session completed. 10.18 km covered in 1h11 at 6:59/km.
 Average heart rate 127 bpm, peak 140 bpm."

meaning.hr_without_intensity_with_pacing
"No earlier session of comparable distance (±30%) was found within 180 days, so no historical
 comparison is available. Heart-rate facts are available, but intensity classification is
 unavailable without trustworthy zone evidence, so this session is interpreted structurally."

advice.hr_without_intensity
"Limit of this analysis: without individualized heart-rate zones, the recorded heart-rate
 values cannot be read as intensity evidence. Limit of this analysis: no kilometre splits are
 recorded for this session, so its pace distribution cannot be described."
```

Les deux séances produisent bien des analyses distinctes, et aucun des deux textes ne prescrit
quoi que ce soit.

---

## 3. Comparaison historique restaurée

`retrieve_similar_workouts()` est réimplémentée **dans** `workout_analysis_v2.py`.
`rag_engine.py` n'est **pas** restauré, et aucun nouvel endpoint n'est créé.

Contraintes appliquées :

| Contrainte | Règle |
|---|---|
| Utilisateur | filtre `user_id` de la requête appelante, jamais élargi |
| Sport | `type` identique |
| Séance courante | exclue par `id` |
| Antériorité | strictement antérieure (`cutoff <= date < current_date`) — **zéro lookahead** |
| Distance | ±30 % de la distance courante |
| Fenêtre | 180 jours |
| Volume | 5 résultats maximum, triés par date décroissante |
| Nature entraînement/course | lue **uniquement** dans des clés de métadonnées explicites |

Rien n'est déduit du nom de la séance ni de sa distance. Si la nature entraînement/compétition
n'est pas enregistrée, la limitation `session_nature_unknown` est posée et `comparable` devient
`False`. Des métadonnées explicitement incompatibles (course vs entraînement) excluent le candidat.

Le résultat est exposé de façon additive dans `comparison.similar` : les dix clés racine du
contrat sont inchangées, donc `WorkoutDetail.jsx` n'a eu besoin d'aucune adaptation.

`backend/server.py` : la fenêtre de la requête d'historique passe de 14 à 180 jours pour
alimenter cette recherche. L'endpoint, le filtre `user_id` et le `limit 200` sont inchangés.

---

## 4. Garde-fous

- `_has_trusted_zone_provenance()` reste `False` : aucune zone n'est considérée comme fiable.
- Aucune intensité déduite de la FC moyenne.
- Aucun split inventé : le nombre annoncé est le nombre réellement enregistré.
- Aucune zone inventée.
- Aucune nature race/training inventée.
- Aucune causalité automatique sur la dérive FC : la mesure est donnée, la cause ne l'est pas.
- Aucune cadence « cible universelle ».
- Aucune conclusion de performance, aucun vocabulaire de progression.
- `None ≠ 0` : une donnée absente n'est jamais traitée comme une valeur nulle.
- Déterminisme complet, FR / EN / ES.
- Aucun `random`, aucun LLM dans Workout Analysis, pas de `rag_engine.py`, pas de second moteur.

---

## 5. Populations et couverture par métrique

C'est le point le plus délicat du correctif : **ne jamais mélanger deux populations dans une
même phrase**, et **ne jamais annoncer un effectif sur lequel la moyenne ne repose pas**.

### 5.1 Sous-ensembles explicites

`_build_similar_reference()` construit un sous-ensemble par métrique :

| Sous-ensemble | Contenu |
|---|---|
| `pace_matches` | séances comparables portant une allure **valide** |
| `hr_matches` | séances comparables portant une FC **valide** |
| `distance_matches` | séances comparables portant une distance **valide** |

### 5.2 Compteurs exposés

| Champ | Signification |
|---|---|
| `sample_count` | total des séances historiques comparables retrouvées |
| `distance_sample_count` | couverture distance générale |
| `pace_sample_count` | couverture réelle de l'allure |
| `hr_sample_count` | couverture réelle de la FC |
| `avg_distance_km` | distance moyenne de **toutes** les séances retrouvées |
| `pace_avg_distance_km` | distance moyenne **du seul sous-ensemble allure** |

`avg_distance_km` n'est jamais recyclé pour désigner autre chose que la moyenne générale.

### 5.3 Alignement strict des phrases

`fact.similar_pace` n'utilise que des nombres issus de `pace_matches` :
`pace_sample_count`, `avg_pace_min_km`, `pace_avg_distance_km`.

Exemple qui était faux avant ce correctif — 5 séances comparables, 2 avec allure
(9,0 km et 10,0 km), 3 sans allure (12,0 / 12,5 / 13,0 km) :

- ancien texte : « Sur 2 séances … moyenne **11.3 km** … » ← moyenne des 5 séances ;
- texte actuel : « Sur 2 séances … moyenne **9.5 km** … » ← moyenne des 2 séances réellement utilisées.

`fact.similar_hr` n'utilise que `hr_sample_count` et `avg_heart_rate`, issus de `hr_matches`.

### 5.4 Validité des valeurs

`_valid_positive_number()` remplace les tests `is not None`. Une valeur est exploitable
seulement si elle est un nombre réel **fini et strictement positif**.

Sont rejetés : `None`, `bool`, `NaN`, `+inf`, `-inf`, `0`, les négatifs et les types non
numériques. `_usable_metric()` applique la même règle à la séance courante : si l'allure ou la
FC de la séance analysée est invalide, **aucune différence correspondante n'est calculée** et
aucun texte de différence n'est produit.

**Aucune calibration physiologique n'est introduite** : pas de plancher ni de plafond de FC, pas
de bornes d'allure. Cette PR élimine les valeurs impossibles à moyenner honnêtement, elle
n'invente aucun seuil.

La même règle de validité s'applique au filtre de distance de `retrieve_similar_workouts()` :
une distance `NaN` ou nulle ne peut plus entrer dans l'ensemble comparable.

### 5.5 Couverture insuffisante

Une couverture inférieure à `SIMILAR_MIN_COMPARABLE_SAMPLE` pose une limitation explicite
(`pace_sample_too_small`, `hr_sample_too_small`) et déclenche une phrase qui énonce la limite
au lieu de laisser lire l'écart comme une comparaison :

> « That pace average rests on 1 of the 5 earlier session(s) found, below the 2 this analysis
> requires before reading the pace gap as anything more than a raw difference. »

`comparable` reste `False` dès qu'une limitation quelconque est enregistrée.

---

## 6. Baseline 14 jours : descriptive uniquement

La baseline générique sur 14 jours filtre par `type` sans critère de distance. Elle ne peut donc
pas fonder une lecture de performance.

- Son **allure** et sa **FC** ne sont **jamais verbalisées**.
- Sa **distance** est formulée au conditionnel : la moyenne **« peut inclure »** des séances de
  distances ou de nature différentes — l'ancienne formulation affirmait un mélange qui n'était
  jamais vérifié.
- La phrase précise explicitement qu'il ne s'agit pas d'une comparaison de performance.

FR : « cette moyenne **peut inclure** des séances de distances ou de nature différentes et ne
constitue pas une comparaison de performance. »
EN : « that average **may include** sessions of different distances or natures and is not a
performance comparison. »
ES : « esa media **puede incluir** sesiones de distancias o naturalezas diferentes y no
constituye una comparación de rendimiento. »

Seule `comparison.similar`, à distance comparable, peut soutenir une observation d'allure ou de FC.

---

## 7. Fichiers modifiés

| Fichier | Nature |
|---|---|
| `backend/workout_analysis_v2.py` | textes contextualisés, recherche comparable bornée, sous-ensembles et compteurs par métrique, helpers de validité |
| `backend/server.py` | fenêtre d'historique 14 → 180 jours (5 lignes) |
| `backend/tests/test_workout_analysis_v2.py` | tests de non-prescription, de bornes, de couverture, d'alignement de population et de validité |
| `RUNINDEX_PR303_REPORT.md` | ce rapport |

Aucun fichier hors périmètre. Ne sont modifiés ni Coach Context V2, ni `pages/Coach.jsx`, ni la
navigation WorkoutDetail → Coach, ni Training Today/Week, ni Readiness, ni les quotas, ni
429/503, ni l'abonnement, ni l'auth, ni Railway, ni Redis, ni l'ingestion Garmin, ni le
formatage d'allure du frontend, ni le branding.

---

## 8. Tests

`backend/tests/test_workout_analysis_v2.py` : **119 tests**.

Garanties couvertes :

- analyse strictement non prescriptive ; Training Today/Week seule autorité ;
- les deux fixtures 21,27 km / FC 160 et 10,18 km / FC 127 produisent des analyses distinctes ;
- aucune intensité déduite de la FC moyenne ; `_has_trusted_zone_provenance()` reste `False` ;
- aucun split, aucune zone, aucune nature race/training inventés ;
- baseline 14 jours : allure et FC non verbalisées, distance au conditionnel, cas distances
  identiques et cas distances différentes ;
- recherche comparable : isolation `user_id`, IDOR, même sport, exclusion de la séance courante,
  antériorité stricte, ±30 %, fenêtre 180 jours, maximum 5, zéro lookahead ;
- `session_nature_unknown` ⇒ `comparable=False` ;
- couverture partielle allure / FC, couverture nulle, limitations explicites ;
- déterminisme, FR/EN/ES, formats de date mixtes.

Tests ajoutés par ce dernier correctif :

| Sujet | Test |
|---|---|
| P1 — alignement de population allure (9,0 + 10,0 km ⇒ 9,5 km, jamais 11,3 km) | `test_pace_sentence_uses_the_distance_of_the_pace_population_only` |
| P1 — même garantie en FR/EN/ES | `test_pace_population_alignment_holds_in_every_language` |
| Validité allure (`None`, `0`, négatif) | `test_invalid_pace_values_are_excluded_from_coverage_and_average` |
| Validité allure (`NaN`, `inf`, `bool`) | `test_non_finite_and_bool_pace_values_are_excluded_too` |
| Validité FC (`None`, `0`, négatif) | `test_invalid_heart_rate_values_are_excluded_from_coverage_and_average` |
| Validité FC (`NaN`, `inf`, `bool`) | `test_non_finite_and_bool_heart_rate_values_are_excluded_too` |
| Allure courante invalide ⇒ aucune différence | `test_invalid_current_pace_produces_no_pace_difference` |
| FC courante invalide ⇒ aucune différence | `test_invalid_current_heart_rate_produces_no_hr_difference` |
| Helper de validité, sans calibration physiologique | `test_valid_positive_number_rejects_only_impossible_values` |
| Distance candidate invalide exclue du set comparable | `test_invalid_candidate_distance_never_enters_the_comparable_set` |
| Distance courante invalide ⇒ aucune référence | `test_invalid_current_distance_yields_no_comparable_reference` |

Le test d'alignement de population a été vérifié comme **régression réelle** : réintroduire
`avg_distance_km` dans `fact.similar_pace` le fait échouer dans les trois langues.

### Résultats exacts

| Suite | Commande | Résultat |
|---|---|---|
| Workout Analysis V2 | `python -m pytest tests/test_workout_analysis_v2.py -q` | **119 passed, 0 failed** |
| Workout Analysis + RAG + LLM cleanup + IDOR | `python -m pytest tests/test_workout_analysis_v2.py tests/test_rag_endpoints.py tests/test_pr211_coach_llm_cleanup.py tests/test_idor_integration.py -q` | **161 passed, 1 failed** |

L'unique échec est `test_pr211_coach_llm_cleanup.py::test_server_coach_analyze_no_hr_speed_vma_exposure`.
Il a été revérifié en restaurant `backend/server.py` depuis `copilot/dev` : il échoue à
l'identique sur la base. **Préexistant et hors périmètre.**

### Tests non exécutés

- La suite backend complète. `backend/requirements.txt` épingle `litellm` et
  `emergentintegrations` sur un hôte inaccessible depuis cet environnement ; les modules qui en
  dépendent ne peuvent pas être importés.
- Aucun Redis réel, aucun worker réel, aucun service partagé n'a été utilisé.
- **Aucune CI backend GitHub n'est invoquée comme preuve** : ce dépôt n'en expose pas pour ces
  suites. Netlify ne constitue en aucun cas une preuve des tests backend.

---

## 9. Corrections pendant la review

Trois audits successifs ont corrigé cette PR avant sa forme finale. Les comportements
ci-dessous **ne sont plus actifs** et ne doivent pas être lus comme le contrat courant :

1. une chaîne de conseils prescriptive a été **supprimée** au profit d'observations factuelles
   et de limites explicites ;
2. l'allure et la FC de la baseline générique 14 jours ont été **retirées** des textes ;
3. l'affirmation non vérifiée « cette moyenne mélange des séances de distances différentes » a
   été **remplacée** par une formulation au conditionnel ;
4. les textes d'allure et de FC quotaient `sample_count` alors que les moyennes reposaient sur
   moins de séances : les compteurs par métrique ont été **ajoutés** ;
5. la phrase d'allure quotait encore la distance moyenne de **toutes** les séances : elle utilise
   désormais `pace_avg_distance_km`, issu du seul sous-ensemble allure.

Trois assertions existantes ont été mises à jour pour suivre ces contrats ; aucune garantie de
test n'a été retirée.

---

## 10. Limites restantes et validation Emergent requise

- Le seuil `SIMILAR_MIN_COMPARABLE_SAMPLE = 2` est réutilisé comme seuil de couverture par
  métrique. Sa pertinence doit être mesurée sur de vrais historiques Garmin.
- La nature entraînement/compétition est absente des activités réelles synchronisées, donc
  `session_nature_unknown` et `comparable == False` resteront probablement la norme en pratique.
- Les zones cardiaques restent sans provenance fiable : la réserve sur l'intensité restera
  présente tant que cette provenance n'est pas établie ailleurs dans le produit.
- La tolérance ±30 % et la fenêtre de 180 jours sont des choix bornés, non calibrés sur données
  réelles.

**Validation Emergent encore nécessaire**, sur de vraies séances Garmin :

1. vérifier que `pace_sample_count`, `hr_sample_count` et `pace_avg_distance_km` correspondent
   aux données réellement synchronisées ;
2. vérifier que les textes restent lisibles dans `WorkoutDetail` dans les trois langues ;
3. vérifier qu'aucune séance réelle ne produit de texte prescriptif.

---

## 11. Périmètre

**#304 ne répare que Workout Analysis V2.**

Le Coach conversationnel n'est **pas** réparé par cette PR et ne doit pas être déclaré comme tel.
La restauration de son contexte reste l'étape suivante, après audit et merge éventuel de #304.
