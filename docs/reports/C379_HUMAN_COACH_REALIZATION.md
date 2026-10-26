# C379 — Réalisation déterministe d'un commentaire de coach plus humain

## 1. Audit initial en lecture seule : où l'information se perdait

- **Base exacte** : `copilot/dev` à `d67313aec9afc56676c34fe1e91b1c482a4538d8`, correspondance locale/distante vérifiée au début du travail.
- Vérification finale communiquée : le `copilot/dev` distant reste à cette même base exacte.
- **HEAD exact de l'implémentation testée** : `3cbde97802d40c87973409b587595443e76904a9`.
- Les deux commits d'implémentation sont `d6dbb77` puis `3cbde97`. Le commit de ce rapport sera un successeur documentaire uniquement ; son SHA n'est pas inventé ici.
- Périmètre : prototype hybride interne, sans intégration de route, de front-end, ni déploiement. Aucun merge automatique.

Les ancres ci-dessous désignent **le contenu de la base exacte**, et non les numéros de ligne après modification.

| Point du chemin existant | Ancre à la base | Constat avant réalisation C379 |
|---|---|---|
| Admission scientifique | `backend/hybrid_coach_c359.py:381-415`, `build_admissible_facts` | Le catalogue est indépendant du texte sélectionné de Narrative V3 ; autorisation, permissions, valeurs finies, provenance et limites sont contrôlées avant toute réalisation. |
| Efforts enregistrés | `backend/hybrid_coach_c359.py:220-378`, `_recorded_effort_facts` | Les contrôles de source Garmin/`typed-splits`, ordre, identité, disponibilité et cohérence des chemins existent déjà (`234-280`). `effort.first`, `effort.last` et `effort.coverage` sont déjà construits (`345-377`) : durées et allures ne manquaient donc pas au catalogue. |
| Jugements V2 | `backend/hybrid_coach_c359.py:639-745` ; `backend/hybrid_coach_v2_c372.py:24-67`, `ScopedV2Evidence` / `approved_v2_regularity` | Lien user/workout, version, phases canoniques Garmin, effectif, couverture complète et jugement catégoriel sont exigés. C379 ne desserre pas ces conditions. |
| C365 : candidats | `backend/hybrid_coach_editorial_c365.py:95-107`, `allowed_forms` ; `120-217`, `primary_fact_candidates` | Les formes lexicales fermées et la hiérarchie contextuelle existent. Ce n'est pas un manque de nouveaux calculs ou d'un moteur de conseil libre. |
| C359 : sélection déterministe | `backend/hybrid_coach_c359.py:862-907`, `select_deterministic_synthesis` | Après choix du principal, une direction ou régularité ne prend comme support que l'intensité au-dessus de LT2 (`892-895`). Les endpoints pourtant admis sont écartés à cette étape. |
| C359 : texte brut | `backend/hybrid_coach_c359.py:850-859`, `_bounded_claims` ; `910-911`, `_render` | Les assertions existantes sont simplement jointes. La réalisation C374 n'est pas réutilisée par le fallback. |
| C374 : options | `backend/hybrid_coach_closed_c374.py:110-152`, `_validate_composition` ; `220-268`, `build_editorial_options` | Une direction peut être accompagnée d'une régularité ; l'association régularité/endpoints reste exclue et aucune option direction/groupes + endpoints concrets n'est préparée. |
| C374 : réalisation et conseil | `backend/hybrid_coach_closed_c374.py:155-191`, `_realize` ; `50-64`, `EditorialOption.text` | Une réalisation fermée avec réserves ciblées existe déjà, mais `text` ne joint que les observations ; le conseil structuré est séparé. |
| Entrée hybride et fallback | `backend/hybrid_coach_c359.py:1344-1374`, `generate_hybrid_coach` | Le résultat initial est déterministe et fermé, avant toute tentative fournisseur ; à `1361-1366`, il expose séparément `text`, `claims`, `advice` et `advice_reason`. |

**Diagnostic** : la perte éditoriale intervenait après admission, dans le choix des supports et l'assemblage du texte. Aucun motif pour recalculer la science, reconstituer une intention ou inventer une métrique.

## 2. C365 : candidats, options et contrat hérité

`primary_fact_candidates`, `editorial_scope`, `allowed_forms`, le validateur de sélection et le registre fermé `ADVICE_REGISTRY` restent les autorités existantes. `prescription.review` reste admis pour d'autres consommateurs mais exclu du commentaire Coach ; Training reste l'autorité de prescription, Garmin celle de l'observation effectuée.

- Fractionné : direction V2 quand admise, sauf priorité au jugement homogène couvrant les efforts comparables ; sinon régularité, puis observations descriptives disponibles.
- Continu : évolution admise des moitiés en distance, intensité interprétable par seuils personnels, historique autorisé ou type probable selon le contexte.
- Long : comparaison de durée avec l'habitude, sans inférence d'endurance ou de fatigue.
- Au maximum un principal et deux supports ; ni checklist systématique, ni second historique quand `session.long` constitue déjà une comparaison historique.

C379 ne remplace **pas** les formes lexicales de la sélection C365 réussie : celle-ci continue à passer par `realize_editorial_selection` et ses formes fermées historiques. L'unification porte sur le **fallback déterministe C359**, désormais réalisé avec C374. Les deux chemins ne doivent pas être présentés comme éditorialement identiques dans tous les cas.

## 3. C374 : options fermées et assemblage du texte

Dans le HEAD testé, les ancres courantes sont `backend/hybrid_coach_closed_c374.py:106-172` (candidats/composition), `175-332` (réalisation), `335-435` (construction/validation), `438-466` (sélection déterministe).

- La formulation de régularité porte désormais le nombre de répétitions comparables.
- La différence entre groupes extrêmes est explicitement **une moyenne**. Les premier et dernier efforts enregistrés peuvent l'illustrer sans transformer leur différence individuelle en delta de groupes.
- Une régularité seule peut disposer d'une option illustrée par **un** endpoint ; le déterministe peut néanmoins garder la version courte.
- Une option de direction peut disposer des deux endpoints si son scope est `equal_count_endpoint_groups_middle_excluded`. Une comparaison directe premier/dernier n'est pas répétée par ces mêmes endpoints.
- L'historique admissible peut mener devant une moyenne d'intensité ordinaire ; une moyenne au-dessus de LT2 conserve sa priorité utile en support.
- Les deltas historiques nuls restent dans les faits admis mais ne deviennent pas une information éditoriale mise en avant.
- Les supports restent limités à deux, les exclusions croisées sont revalidées et les options sont reconstruites depuis les faits admis. Aucun texte arbitraire de fournisseur n'est accepté.
- `EditorialOption.text` joint maintenant observations et conseil admissible **une seule fois** ; `claims` reste une liste d'observations, `advice` reste accessible séparément.

Le choix déterministe suit la priorité contextuelle des options, recherche des détails complémentaires utiles, puis limite les répétitions ; il ne maximise ni la longueur, ni un nombre artificiel de mots.

**Correction issue de la revue** : filtrer d'abord les comparaisons à delta nul changeait le jeu de candidats primaires par rapport au snapshot utilisé pour valider, ce qui pouvait provoquer un échec de construction du fallback. `build_editorial_options:374-386` conserve maintenant le snapshot original pour générer les candidats et ne masque les zéros que pour l'affichage. La régression `test_hidden_zero_comparison_cannot_invalidate_the_deterministic_fallback` (`backend/tests/test_hybrid_coach_c379.py:235-257`) couvre une sortie continue avec comparaison nulle et comparaison non nulle.

## 4. C359 : fallback et conseil conditionnel

`backend/hybrid_coach_c359.py:862-877`, `select_deterministic_synthesis`, réutilise maintenant `build_editorial_options` et `select_deterministic_option` de C374, sans second système de templates ni appel externe supplémentaire. Le paramètre de langue est transmis explicitement.

L'advice reste sélectionné par `admissible_advice` et le registre C365, avec identifiant, fait déclencheur, références et raison d'admission ou d'abstention. Le texte complet comprend le conseil lorsqu'il est admis, mais les `claims` restent analytiques.

| Conseil fermé | Usage admissible, sans intention supposée |
|---|---|
| `advice.keep_consistency` | Régularité homogène couvrant les efforts comparables ; absence de contre-indication directionnelle. |
| `advice.stabilize_paces` | Variabilité admise, sans direction progressive contre-indiquant ce conseil ; objectif de régularité formulé conditionnellement. |
| `advice.effort_distribution` | Intention d'allure stable vérifiée requise ; elle n'est pas disponible ici, donc aucun conseil de ce type inventé. |
| `advice.continuous_pacing` | Moitié finale plus lente, couverture de séance complète, type easy/steady suffisamment fiable ; pas pour long ou tempo. |

Les raisons exactes de chaque scénario figurent en section 7. Pas de flatterie automatique, de « belle séance » générique, de recommandation de charge, de récupération ou d'intention reconstruite.

## 5. Pourquoi une réalisation éditoriale, et quelles limites

Le but est de relier des faits déjà calculés à une formulation compréhensible : « premier seuil » plutôt que jargon LT1, différence historique orientée plutôt qu'un signe technique, nombre de répétitions et endpoints quand ils précisent réellement le scope. Une FC moyenne sans seuils personnels ne suffit pas à qualifier l'effort ou la physiologie.

Les limites restent attachées aux faits et aux claims même lorsqu'elles ne sont pas répétées intégralement dans chaque phrase. Les réserves textuelles essentielles restent présentes pour les moyennes, les comparaisons historiques et l'incertitude d'interprétation.

**Légende commune des limites utilisée en section 7** :

- **E** : endpoints dans l'ordre enregistré, pas chronologie absolue vérifiée ; aucune déduction de régularité, fatigue, progrès physiologique ou conformité de prescription.
- **R** : jugement V2 limité aux efforts enregistrés comparables et à sa couverture ; pas stabilité physiologique, fatigue, cause ni jugement « bon/mauvais ».
- **D** : direction V2 et scope exact seulement ; moyenne de groupes distincte des endpoints individuels ; pas progression physiologique ou cause.
- **C** : moitiés de distance égales, couverture déclarée ; pas fatigue/endurance, causalité ou contrôle du terrain/de la météo.
- **I** : moyenne de FC ; si seuils validés, position de la moyenne uniquement, jamais chaque phase ni temps en zones ; sans seuils, aucune conclusion d'intensité.
- **H** : historique autorisé, références et scope déclarés ; terrain/météo non isolés, pas preuve de changement de forme ; `None != 0`.
- **T** : type probable et durée selon leur preuve disponible ; intention et objectif inconnus. Durée versus habitude est déjà une comparaison historique.
- **A** : données absentes, non comparables ou partiellement transportées : abstention ciblée, jamais remplacement par zéro.

Ces codes sont des repères de lecture, pas de nouvelles règles scientifiques. Les listes `limits` exactes de tous les faits admis sont reproduites avec les valeurs en section 7.

## 6. Fichiers modifiés et périmètre effectivement livré

Différence de la base exacte au HEAD testé :

1. `backend/hybrid_coach_c359.py` : fallback réalisé via C374 ; langue transmise ; conseil joint au texte complet sans l'ajouter aux claims analytiques.
2. `backend/hybrid_coach_closed_c374.py` : formulations fermées, supports contextualisés, sélection déterministe, composition du conseil et exclusion éditoriale des comparaisons nulles.
3. `backend/tests/test_hybrid_coach_c365.py` : attentes adaptées au nouveau fallback, sans remplacer le contrat C365 réussi.
4. `backend/tests/test_hybrid_coach_c371.py` : attentes de réalisation des faits d'effort.
5. `backend/tests/test_hybrid_coach_c372.py` : attentes sur le jugement V2 réalisé.
6. `backend/tests/test_hybrid_coach_c378.py` : attentes de commentaire et conseil complet.
7. `backend/tests/test_hybrid_coach_c379.py` : scénarios déterministes, limites, traçabilité, absence de recalcul/réseau et régressions.

Ce rapport ajoute uniquement `docs/reports/C379_HUMAN_COACH_REALIZATION.md`. Aucun changement de dépendance projet, moteur scientifique, calcul, seuil, admission scientifique, route de production ou front-end. Les adaptations de tests et le rapport ne prouvent pas une adoption par des utilisateurs.

## 7. Vingt-deux scénarios : preuves et commentaires complets avant/après

Le corpus est constitué de **fixtures synthétiques**, pas de séances d'utilisateurs recrutés. Les lignes sont générées par le code sur les mêmes entrées et permissions avant/après ; les commentaires ci-dessous ne sont ni reformulés ni raccourcis.

**Contrat de comparaison** : `C378.text` contient l'analyse seule. `C378.advice` était un champ séparé et est donc montré également. `C379.text` contient déjà le conseil une fois quand il est admis. Le champ d'évaluation `c378_complete_comparison`, s'il est cité, est une jointure mécanique ancien texte + ancien conseil pour une comparaison équitable, **pas** le texte original C378. Il n'est pas un commentaire historiquement renvoyé dans `.text`.

Tous les IDs, valeurs et limites des faits admis sont reproduits, y compris ceux non sélectionnés : omission éditoriale ne signifie pas donnée manquante. Les IDs sélectionnés sont distingués du catalogue.

Les appréciations **Naturalité / Clarté / Utilité / Personnalisation / Concision** sont des jugements éditoriaux subjectifs de lecture : `+` amélioration, `=` équivalence, `-` recul ; aucun score numérique, sondage ou taux de satisfaction n'est déduit. **Fidélité** désigne seulement la conservation objective des valeurs, scopes, limites et liens de preuve contrôlés par les tests, pas une validation scientifique nouvelle.

### Limites exactes partagées du JSON

Pour éviter de recopier les mêmes listes 22 fois, chaque ligne de fait renvoie à une liste exacte ci-dessous. Les valeurs numériques brutes sont conservées : allures en s/km, durées d'effort en secondes, FC en bpm ; `session.long` est en minutes, `span` en jours.

| Code | Liste `limits` exacte |
|---|---|
| L1 | `["no_physiological_zone", "average_not_whole_effort"]` |
| L2 | `["recorded_order_not_verified_absolute_chronology", "no_regularity_or_fatigue", "no_progress_or_physiological_inference", "no_prescription_compliance"]` |
| L3 | `["recorded_comparable_efforts_only", "not_physiological_stability", "no_fatigue_progression_or_cause", "descriptive_not_good_or_bad"]` |
| L4 | `["recorded_comparable_efforts_only", "no_physiological_progression", "no_causal_inference"]` |
| L5 | `["no_repetition_durations", "regularity_verdict_unavailable"]` |
| L6 | `["probable_not_certain"]` |
| L7 | `["equal_distance_halves_only", "no_fatigue_or_endurance_inference", "no_causal_inference", "terrain_weather_not_controlled"]` |
| L8 | `["probable_not_certain", "duration_not_effort"]` |
| L9 | `["average_not_whole_effort", "no_time_in_zones", "no_physiological_cause", "no_progression_from_average"]` |
| L10 | `["unknown_not_easy", "threshold_interpretation_unavailable"]` |
| L11 | `["not_proof_of_fitness", "no_cause", "terrain_weather_not_controlled"]` |
| L12 | `["unknown_not_easy", "missing_average_hr"]` |

La comparaison du JSON confirme que l'ID, le texte et la raison du conseil sont identiques avant/après dans les 22 cas. Sa présence dans `C379.text` est un changement d'assemblage, pas une nouvelle admission. Les six appréciations ci-dessous sont toujours présentées dans l'ordre **Naturalité / Clarté / Utilité / Personnalisation / Concision / Fidélité** ; les cinq premières sont subjectives, la dernière est la conservation factuelle contrôlée.

### 7.1 `homogeneous` — FR

Faits admis complets :

```text
intensity.hr = {"average_hr":145.0} — L1
effort.first = {"effort_number":1,"recorded_pace":300.0,"recorded_duration":240.0} — L2
effort.last = {"effort_number":4,"recorded_pace":300.0,"recorded_duration":240.0} — L2
effort.coverage = {"recorded_total":4,"pace_count":4,"duration_count":4,"both_count":4} — L2
interval.regularity = {"regularity_band":"homogeneous","source":"workout_analysis_v2","status":"available","efforts":4,"comparability_basis":"duration"} — L3
```

Sélection C378 → C379 : `["interval.regularity"]` → `["interval.regularity"]`.
Conseil, aux deux versions : `advice.keep_consistency` ; raison exacte `advice_admitted`.

**C378.text intégral**
```text
Les allures des répétitions comparables sont homogènes.
```
**C378.advice.text intégral, séparé**
```text
Cette constance est un bon repère à retrouver lors de tes prochaines séries comparables.
```
**C379.text intégral**
```text
Sur tes 4 répétitions comparables, tu as couru à des allures proches. Cette constance est un bon repère à retrouver lors de tes prochaines séries comparables.
```

Différence : nombre et adresse directe ajoutés ; pas d'endpoint imposé pour remplir. Limites E/R/I : homogénéité d'allure, pas stabilité physiologique. Appréciation : **+ / + / = / + / - / =** ; le conseil était déjà disponible dans C378.

### 7.2 `irregular` — FR

```text
intensity.hr = {"average_hr":145.0} — L1
effort.first = {"effort_number":1,"recorded_pace":300.0,"recorded_duration":240.0} — L2
effort.last = {"effort_number":4,"recorded_pace":325.0,"recorded_duration":240.0} — L2
effort.coverage = {"recorded_total":4,"pace_count":4,"duration_count":4,"both_count":4} — L2
interval.regularity = {"regularity_band":"variable","source":"workout_analysis_v2","status":"available","efforts":4,"comparability_basis":"duration"} — L3
```

Sélection : `["interval.regularity"]` → `["interval.regularity"]`.
Conseil aux deux versions : `advice.stabilize_paces` ; `advice_admitted`.

**C378.text intégral**
```text
Les répétitions comparables présentent des variations d'allure importantes.
```
**C378.advice.text intégral, séparé**
```text
Sur une prochaine séance comparable où tu recherches la régularité, essaie de stabiliser davantage tes allures.
```
**C379.text intégral**
```text
Tes 4 répétitions comparables présentent des variations d'allure importantes. Sur une prochaine séance comparable où tu recherches la régularité, essaie de stabiliser davantage tes allures.
```

Différence : effectif précisé, conseil inchangé et conditionnel. Limites E/R : pas d'intention régulière attribuée à la séance réalisée. Appréciation : **+ / + / = / + / = / =**.

### 7.3 `faster` — FR

```text
intensity.hr = {"average_hr":145.0} — L1
effort.first = {"effort_number":1,"recorded_pace":330.0,"recorded_duration":240.0} — L2
effort.last = {"effort_number":4,"recorded_pace":300.0,"recorded_duration":240.0} — L2
effort.coverage = {"recorded_total":4,"pace_count":4,"duration_count":4,"both_count":4} — L2
interval.regularity = {"regularity_band":"noticeable","source":"workout_analysis_v2","status":"available","efforts":4,"comparability_basis":"duration"} — L3
interval.pace_direction = {"direction":"faster","scope":"equal_count_endpoint_groups_middle_excluded","pace_change_sec_per_km":-20.0,"comparability_basis":"duration","source":"workout_analysis_v2","efforts":4,"group_size":2} — L4
```

Sélection : `["interval.pace_direction"]` → `["interval.pace_direction","effort.first","effort.last"]`.
Conseil aux deux versions : **abstention** ; `condition_unmet:verified_steady_pacing_intent`. C378.advice : `null`.

**C378.text intégral**
```text
Les 2 dernières répétitions comparables sont 20 s/km plus rapides que les 2 premières.
```
**C379.text intégral**
```text
Les 2 dernières répétitions comparables sont 20 s/km en moyenne plus rapides que les 2 premières. Dans l'ordre enregistré, ton premier effort est à 5'30/km. Ton dernier effort est à 5'00/km.
```

Différence : « en moyenne » distingue les 20 s/km entre groupes des 30 s/km entre endpoints individuels. Les durées égales ne sont pas répétées. Limites E/D/R : pas progression physiologique ou objectif supposé. Appréciation : **+ / + / + / + / - / =**.

### 7.4 `slower` — FR

```text
intensity.hr = {"average_hr":145.0} — L1
effort.first = {"effort_number":1,"recorded_pace":300.0,"recorded_duration":240.0} — L2
effort.last = {"effort_number":4,"recorded_pace":330.0,"recorded_duration":240.0} — L2
effort.coverage = {"recorded_total":4,"pace_count":4,"duration_count":4,"both_count":4} — L2
interval.regularity = {"regularity_band":"noticeable","source":"workout_analysis_v2","status":"available","efforts":4,"comparability_basis":"duration"} — L3
interval.pace_direction = {"direction":"slower","scope":"equal_count_endpoint_groups_middle_excluded","pace_change_sec_per_km":20.0,"comparability_basis":"duration","source":"workout_analysis_v2","efforts":4,"group_size":2} — L4
```

Sélection : `["interval.pace_direction"]` → `["interval.pace_direction","effort.first","effort.last"]`.
Conseil aux deux versions : **abstention** ; `condition_unmet:verified_steady_pacing_intent`. C378.advice : `null`.

**C378.text intégral**
```text
Les 2 dernières répétitions comparables sont 20 s/km plus lentes que les 2 premières.
```
**C379.text intégral**
```text
Les 2 dernières répétitions comparables sont 20 s/km en moyenne plus lentes que les 2 premières. Dans l'ordre enregistré, ton premier effort est à 5'00/km. Ton dernier effort est à 5'30/km.
```

Différence : même clarification de groupes et illustration concrète, sans attribuer le ralentissement à la fatigue. Limites E/D/R. Appréciation : **+ / + / + / + / - / =**.

### 7.5 `non_comparable` — FR

```text
interval.count = {"efforts":3,"recoveries":3} — L5
intensity.hr = {"average_hr":145.0} — L1
effort.first = {"effort_number":1,"recorded_pace":300.0,"recorded_duration":60.0} — L2
effort.last = {"effort_number":3,"recorded_pace":300.0,"recorded_duration":600.0} — L2
effort.coverage = {"recorded_total":3,"pace_count":3,"duration_count":3,"both_count":3} — L2
```

Sélection : `["effort.first"]` → `["effort.first"]`.
Conseil aux deux versions : **abstention** ; `no_advice_for_primary`. C378.advice : `null`.

**C378.text intégral**
```text
Dans l'ordre enregistré par Garmin, le premier effort (n° 1) a duré 1 min, à 5'00/km.
```
**C379.text intégral**
```text
Dans l'ordre enregistré, ton premier effort a duré 1 min, à 5'00/km.
```

Différence : formulation allégée, même durée et allure. Des allures identiques sur des efforts de 60 et 600 s ne produisent pas ici de verdict homogène. Limites E/A : régularité et direction non admises. Appréciation : **+ / = / = / + / + / =**.

### 7.6 `easy` — FR

```text
session.kind = {"classification":"easy_run_probable"} — L6
intensity.hr = {"average_hr":145.0} — L1
```

Sélection : `["intensity.hr"]` → `["intensity.hr"]`.
Conseil aux deux versions : **abstention** ; `no_advice_for_primary`. C378.advice : `null`.

**C378.text intégral**
```text
Ta FC moyenne enregistrée est de 145 bpm ; elle ne suffit pas à établir une zone physiologique.
```
**C379.text intégral**
```text
Ta fréquence cardiaque moyenne est de 145 bpm, sans repère personnel validé pour interpréter cette valeur.
```

Différence : jargon réduit, réserve plus explicite, texte légèrement plus long. « Easy probable » ne permet pas d'inventer une zone ou une récupération. Limites I/T. Appréciation : **+ / + / = / = / - / =**.

### 7.7 `variable_easy` — FR

```text
session.kind = {"classification":"easy_run_probable"} — L6
intensity.hr = {"average_hr":145.0} — L1
continuous.pace_halves = {"direction":"slower","scope":"equal_distance_halves","pace_change_sec_per_km":30.0,"coverage":"whole_session","source":"workout_analysis_v2"} — L7
```

Sélection : `["continuous.pace_halves"]` → `["continuous.pace_halves"]`.
Conseil aux deux versions : `advice.continuous_pacing` ; `advice_admitted`.

**C378.text intégral**
```text
La seconde moitié en distance de ta séance est 30 s/km plus lente que la première.
```
**C378.advice.text intégral, séparé**
```text
Sur une prochaine sortie comparable où tu vises une allure régulière, essaie de répartir ton allure plus également entre les deux moitiés.
```
**C379.text intégral**
```text
La seconde moitié en distance de ta séance est 30 s/km plus lente que la première. Sur une prochaine sortie comparable où tu vises une allure régulière, essaie de répartir ton allure plus également entre les deux moitiés.
```

Différence : assemblage seulement ; analyse et conseil déjà disponibles sont inchangés. Limites C/I/T : distance, pas temps ; aucune fatigue ni intention attribuée. Appréciation à contenu complet comparable : **= / = / = / = / = / =**.

### 7.8 `long` — FR

```text
session.long = {"duration":100.0,"usual_duration":50.0} — L8
intensity.position = {"average_hr":140.0,"lt1":150.0,"lt2":170.0,"position":"below_LT1"} — L9
```

Sélection : `["session.long"]` → `["session.long","intensity.position"]`.
Conseil aux deux versions : **abstention** ; `no_advice_for_primary`. C378.advice : `null`.

**C378.text intégral**
```text
Ta sortie est probablement longue : 100 min, contre 50 min habituellement.
```
**C379.text intégral**
```text
Ta sortie est probablement longue : 100 min, contre 50 min habituellement. Ta FC moyenne est de 140 bpm, sous ton premier seuil de 150 bpm. Cette moyenne ne décrit ni chaque phase ni le temps en zones.
```

Différence : ajout d'une position de FC moyenne correctement bornée, mais commentaire nettement plus long. Limites T/H/I : comparaison de durée, pas développement d'endurance ; moyenne, pas toute la sortie. Appréciation : **= / + / + / + / - / =** ; utilité du support à confirmer humainement.

### 7.9 `tempo` — FR

```text
session.kind = {"classification":"tempo_probable"} — L6
intensity.hr = {"average_hr":145.0} — L1
```

Sélection : `["intensity.hr"]` → `["intensity.hr"]`.
Conseil aux deux versions : **abstention** ; `no_advice_for_primary`. C378.advice : `null`.

**C378.text intégral**
```text
Ta FC moyenne enregistrée est de 145 bpm ; elle ne suffit pas à établir une zone physiologique.
```
**C379.text intégral**
```text
Ta fréquence cardiaque moyenne est de 145 bpm, sans repère personnel validé pour interpréter cette valeur.
```

Différence : comme easy, réserve plus lisible et légère extension. Le type probable n'est pas un repère physiologique validé. Limites I/T : pas de conclusion d'effort tempo ni conseil de régularité. Appréciation : **+ / + / = / = / - / =**.

### 7.10 `hr_only` — FR

```text
intensity.hr = {"average_hr":140.0} — L1
session.unknown = {"classification":"unknown","average_hr_available":1,"average_hr":140.0} — L10
```

Sélection : `["intensity.hr"]` → `["intensity.hr"]`.
Conseil aux deux versions : **abstention** ; `no_advice_for_primary`. C378.advice : `null`.

**C378.text intégral**
```text
Ta FC moyenne enregistrée est de 140 bpm ; elle ne suffit pas à établir une zone physiologique.
```
**C379.text intégral**
```text
Ta fréquence cardiaque moyenne est de 140 bpm, sans repère personnel validé pour interpréter cette valeur.
```

Différence : vocabulaire moins technique, aucune nouvelle conclusion. `average_hr_available:1` signale une disponibilité, pas une intensité. Limites I/A : unknown n'est pas easy. Appréciation : **+ / + / = / = / - / =**.

### 7.11 `no_thresholds` — FR

```text
intensity.hr = {"average_hr":140.0} — L1
session.unknown = {"classification":"unknown","average_hr_available":1,"average_hr":140.0} — L10
```

Sélection : `["intensity.hr"]` → `["intensity.hr"]`.
Conseil aux deux versions : **abstention** ; `no_advice_for_primary`. C378.advice : `null`.

**C378.text intégral**
```text
Ta FC moyenne enregistrée est de 140 bpm ; elle ne suffit pas à établir une zone physiologique.
```
**C379.text intégral**
```text
Ta fréquence cardiaque moyenne est de 140 bpm, sans repère personnel validé pour interpréter cette valeur.
```

Différence : résultat identique au cas FC seule, comme attendu avec ces preuves. Aucun seuil remplacé par zéro ou dérivé du type. Limites I/A. Appréciation : **+ / + / = / = / - / =**.

### 7.12 `history` — FR

```text
session.kind = {"classification":"easy_run_probable"} — L6
intensity.position = {"average_hr":140.0,"lt1":150.0,"lt2":170.0,"position":"below_LT1"} — L9
comparison.pace = {"pace_difference":-14.4,"references":5} — L11
comparison.hr = {"hr_difference":0.0,"references":2} — L11
trend.probable_improvement = {"status":"probable_improvement","observations":6,"median_change":-24.0,"span":92} — L11
```

Sélection : `["intensity.position","trend.probable_improvement"]` → `["trend.probable_improvement"]`.
Conseil aux deux versions : **abstention** ; `no_advice_for_primary`. C378.advice : `null`.

**C378.text intégral**
```text
Ta FC moyenne est de 140 bpm, sous LT1 ; elle ne décrit pas tout l'effort. Ton historique suggère une amélioration probable : 6 observations sur 92 jours, variation d'allure médiane de −24 s/km (récente moins ancienne) ; ce n'est pas une preuve de changement de forme.
```
**C379.text intégral**
```text
Sur les 6 observations de ton historique, ton allure médiane récente est 24 s/km plus rapide qu'auparavant sur 92 jours. Cela suggère une amélioration probable, sans prouver un changement de forme ; les effets du terrain et de la météo restent mêlés.
```

Différence : historique distinctif en tête, signe traduit en direction lisible, moyenne ordinaire omise et réserve terrain/météo explicite. Limites H/I/T : statut probable conservé, pas preuve de forme. La comparaison nulle de FC reste admise mais non mise en avant. Appréciation : **+ / + / + / + / + / =**.

### 7.13 `no_history` — FR

```text
session.kind = {"classification":"easy_run_probable"} — L6
intensity.position = {"average_hr":140.0,"lt1":150.0,"lt2":170.0,"position":"below_LT1"} — L9
```

Sélection : `["intensity.position"]` → `["intensity.position"]`.
Conseil aux deux versions : **abstention** ; `no_advice_for_primary`. C378.advice : `null`.

**C378.text intégral**
```text
Ta FC moyenne est de 140 bpm, sous LT1 ; elle ne décrit pas tout l'effort.
```
**C379.text intégral**
```text
Ta FC moyenne est de 140 bpm, sous ton premier seuil de 150 bpm. Cette moyenne ne décrit ni chaque phase ni le temps en zones.
```

Différence : seuil admis chiffré et jargon expliqué ; réserve plus précise, plus longue. L'historique non autorisé n'entre pas au catalogue. Limites I/T/H. Appréciation : **+ / + / + / + / - / =**.

### 7.14 `partial` — FR

```text
intensity.hr = {"average_hr":145.0} — L1
effort.first = {"effort_number":1,"recorded_pace":300.0,"recorded_duration":240.0} — L2
effort.last = {"effort_number":4,"recorded_pace":300.0,"recorded_duration":240.0} — L2
effort.coverage = {"recorded_total":4,"pace_count":4,"duration_count":4,"both_count":4} — L2
interval.regularity = {"regularity_band":"homogeneous","source":"workout_analysis_v2","status":"available","efforts":4,"comparability_basis":"duration"} — L3
```

Sélection : `["interval.regularity"]` → `["interval.regularity"]`.
Conseil aux deux versions : `advice.keep_consistency` ; `advice_admitted`.

**C378.text intégral**
```text
Les allures des répétitions comparables sont homogènes.
```
**C378.advice.text intégral, séparé**
```text
Cette constance est un bon repère à retrouver lors de tes prochaines séries comparables.
```
**C379.text intégral**
```text
Sur tes 4 répétitions comparables, tu as couru à des allures proches. Cette constance est un bon repère à retrouver lors de tes prochaines séries comparables.
```

Différence : même réalisation que homogeneous. **Attention au nom** : la fixture met `effort_pace_observations.available` à faux côté V3 ; elle ne rend pas partielle la preuve V2, qui reste complète et admissible. Le JSON conserve les faits ci-dessus conformément aux contrôles effectifs. Ce n'est pas une dérogation à la couverture scientifique. Limites E/R/A/I. Appréciation : **+ / + / = / + / - / =**.

### 7.15 `insufficient` — FR

```text
session.unknown = {"classification":"unknown","average_hr_available":0} — L12
```

Sélection : `["session.unknown"]` → `["session.unknown"]`.
Conseil aux deux versions : **abstention** ; `no_advice_for_primary`. C378.advice : `null`.

**C378.text intégral**
```text
Le type de ta séance reste incertain ; aucune FC moyenne n'est disponible.
```
**C379.text intégral**
```text
Le type de ta séance reste incertain ; aucune FC moyenne n'est disponible.
```

Différence : aucune. Le zéro est ici un indicateur de disponibilité, pas une FC à 0 bpm ; aucune FC chiffrée inventée. Limites A/T. Appréciation : **= / = / = / = / = / =**.

### 7.16 `v2_v3_missing` — FR

```text
intensity.hr = {"average_hr":145.0} — L1
effort.first = {"effort_number":1,"recorded_pace":300.0,"recorded_duration":240.0} — L2
effort.last = {"effort_number":4,"recorded_pace":300.0,"recorded_duration":240.0} — L2
effort.coverage = {"recorded_total":4,"pace_count":4,"duration_count":4,"both_count":4} — L2
interval.regularity = {"regularity_band":"homogeneous","source":"workout_analysis_v2","status":"available","efforts":4,"comparability_basis":"duration"} — L3
```

Sélection : `["interval.regularity"]` → `["interval.regularity"]`.
Conseil aux deux versions : `advice.keep_consistency` ; `advice_admitted`.

**C378.text intégral**
```text
Les allures des répétitions comparables sont homogènes.
```
**C378.advice.text intégral, séparé**
```text
Cette constance est un bon repère à retrouver lors de tes prochaines séries comparables.
```
**C379.text intégral**
```text
Sur tes 4 répétitions comparables, tu as couru à des allures proches. Cette constance est un bon repère à retrouver lors de tes prochaines séries comparables.
```

Différence : précision de scope et assemblage du conseil ; la preuve V2 n'est pas manquante ici. Le défaut de transport `coach_language` vers l'autre contexte V3 est reproduit séparément en section 9, sans verdict scientifique opposé. Limites E/R/A/I. Appréciation : **+ / + / = / + / - / =**.

### 7.17 `faster_odd` — FR

```text
interval.count = {"efforts":5,"recoveries":5} — L5
intensity.hr = {"average_hr":145.0} — L1
effort.first = {"effort_number":1,"recorded_pace":340.0,"recorded_duration":240.0} — L2
effort.last = {"effort_number":5,"recorded_pace":300.0,"recorded_duration":240.0} — L2
effort.coverage = {"recorded_total":5,"pace_count":5,"duration_count":5,"both_count":5} — L2
```

Sélection : `["effort.first"]` → `["effort.first"]`.
Conseil aux deux versions : **abstention** ; `no_advice_for_primary`. C378.advice : `null`.

**C378.text intégral**
```text
Dans l'ordre enregistré par Garmin, le premier effort (n° 1) a duré 4 min, à 5'40/km.
```
**C379.text intégral**
```text
Dans l'ordre enregistré, ton premier effort a duré 4 min, à 5'40/km.
```

Différence : phrase plus légère, pas de direction ajoutée. **Malgré son nom**, ce cas n'admet ni `interval.regularity` ni `interval.pace_direction` : c'est une frontière d'admission, pas une démonstration de direction sur un nombre impair. Aucun calcul à partir des endpoints pour la contourner. Limites E/A/I. Appréciation : **+ / = / = / + / + / =**.

### 7.18 `three_slower` — FR

```text
intensity.hr = {"average_hr":145.0} — L1
effort.first = {"effort_number":1,"recorded_pace":300.0,"recorded_duration":240.0} — L2
effort.last = {"effort_number":3,"recorded_pace":330.0,"recorded_duration":240.0} — L2
effort.coverage = {"recorded_total":3,"pace_count":3,"duration_count":3,"both_count":3} — L2
interval.regularity = {"regularity_band":"noticeable","source":"workout_analysis_v2","status":"available","efforts":3,"comparability_basis":"duration"} — L3
interval.pace_direction = {"direction":"slower","scope":"first_last_of_three_efforts","pace_change_sec_per_km":30.0,"comparability_basis":"duration","source":"workout_analysis_v2","efforts":3} — L4
```

Sélection : `["interval.pace_direction"]` → `["interval.pace_direction","interval.regularity"]`.
Conseil aux deux versions : **abstention** ; `condition_unmet:verified_steady_pacing_intent`. C378.advice : `null`.

**C378.text intégral**
```text
La dernière répétition comparable est 30 s/km plus lente que la première.
```
**C379.text intégral**
```text
La dernière répétition comparable est 30 s/km plus lente que la première. Tes 3 répétitions comparables présentent des variations d'allure perceptibles.
```

Différence : scope premier/dernier inchangé ; ajout du jugement global de variations perceptibles. Les endpoints ne sont pas répétés et la comparaison n'est pas présentée comme une moyenne de groupes. Limites D/R/E. Appréciation : **= / + / + / + / - / =**.

### 7.19 `long_history` — FR

```text
session.long = {"duration":100.0,"usual_duration":50.0} — L8
intensity.position = {"average_hr":140.0,"lt1":150.0,"lt2":170.0,"position":"below_LT1"} — L9
comparison.pace = {"pace_difference":-14.4,"references":5} — L11
comparison.hr = {"hr_difference":0.0,"references":2} — L11
```

Sélection : `["session.long"]` → `["session.long","intensity.position"]`.
Conseil aux deux versions : **abstention** ; `no_advice_for_primary`. C378.advice : `null`.

**C378.text intégral**
```text
Ta sortie est probablement longue : 100 min, contre 50 min habituellement.
```
**C379.text intégral**
```text
Ta sortie est probablement longue : 100 min, contre 50 min habituellement. Ta FC moyenne est de 140 bpm, sous ton premier seuil de 150 bpm. Cette moyenne ne décrit ni chaque phase ni le temps en zones.
```

Différence : même support FC que long, potentiellement verbeux. Les comparaisons d'allure et de FC sont bien admises mais non sélectionnées : `session.long` compare déjà la durée à l'habitude, et l'exclusion du second historique est maintenue. Limites T/H/I. Appréciation : **= / + / + / + / - / =**.

### 7.20 `zero_history` — FR

```text
session.kind = {"classification":"easy_run_probable"} — L6
intensity.position = {"average_hr":140.0,"lt1":150.0,"lt2":170.0,"position":"below_LT1"} — L9
comparison.pace = {"pace_difference":0,"references":5} — L11
comparison.hr = {"hr_difference":0,"references":2} — L11
trend.probable_improvement = {"status":"probable_improvement","observations":6,"median_change":-24.0,"span":92} — L11
```

Sélection : `["intensity.position","trend.probable_improvement"]` → `["trend.probable_improvement"]`.
Conseil aux deux versions : **abstention** ; `no_advice_for_primary`. C378.advice : `null`.

**C378.text intégral**
```text
Ta FC moyenne est de 140 bpm, sous LT1 ; elle ne décrit pas tout l'effort. Ton historique suggère une amélioration probable : 6 observations sur 92 jours, variation d'allure médiane de −24 s/km (récente moins ancienne) ; ce n'est pas une preuve de changement de forme.
```
**C379.text intégral**
```text
Sur les 6 observations de ton historique, ton allure médiane récente est 24 s/km plus rapide qu'auparavant sur 92 jours. Cela suggère une amélioration probable, sans prouver un changement de forme ; les effets du terrain et de la météo restent mêlés.
```

Différence : tendance plus lisible et commentaire plus court. Les deux deltas nuls restent des valeurs admises et ne sont ni promus ni remplacés par une absence. La tendance non nulle relève de son propre scope : elle ne signifie pas que les comparaisons nulles sont devenues positives. Limites H/I/T. Appréciation : **+ / + / + / + / + / =**.

### 7.21 `variable_easy_en` — EN

```text
session.kind = {"classification":"easy_run_probable"} — L6
intensity.hr = {"average_hr":145.0} — L1
continuous.pace_halves = {"direction":"slower","scope":"equal_distance_halves","pace_change_sec_per_km":30.0,"coverage":"whole_session","source":"workout_analysis_v2"} — L7
```

Sélection : `["continuous.pace_halves"]` → `["continuous.pace_halves"]`.
Conseil aux deux versions : `advice.continuous_pacing` ; `advice_admitted`.

**C378.text intégral**
```text
The second distance half of your session is 30 s/km slower than the first.
```
**C378.advice.text intégral, séparé**
```text
On a future comparable run where you aim for an even pace, try to spread your pace more evenly across both halves.
```
**C379.text intégral**
```text
The second distance half of your session is 30 s/km slower than the first. On a future comparable run where you aim for an even pace, try to spread your pace more evenly across both halves.
```

Différence : assemblage uniquement, aucun gain lexical prétendu ; la formulation anglaise mérite une revue humaine. Limites C/I/T. Appréciation à contenu comparable : **= / = / = / = / = / =**.

### 7.22 `faster_es` — ES

```text
intensity.hr = {"average_hr":145.0} — L1
effort.first = {"effort_number":1,"recorded_pace":330.0,"recorded_duration":240.0} — L2
effort.last = {"effort_number":4,"recorded_pace":300.0,"recorded_duration":240.0} — L2
effort.coverage = {"recorded_total":4,"pace_count":4,"duration_count":4,"both_count":4} — L2
interval.regularity = {"regularity_band":"noticeable","source":"workout_analysis_v2","status":"available","efforts":4,"comparability_basis":"duration"} — L3
interval.pace_direction = {"direction":"faster","scope":"equal_count_endpoint_groups_middle_excluded","pace_change_sec_per_km":-20.0,"comparability_basis":"duration","source":"workout_analysis_v2","efforts":4,"group_size":2} — L4
```

Sélection : `["interval.pace_direction"]` → `["interval.pace_direction","effort.first","effort.last"]`.
Conseil aux deux versions : **abstention** ; `condition_unmet:verified_steady_pacing_intent`. C378.advice : `null`.

**C378.text intégral**
```text
Las 2 últimas repeticiones comparables son 20 s/km más rápidas que las 2 primeras.
```
**C379.text intégral**
```text
Las 2 últimas repeticiones comparables son 20 s/km de media más rápidas que las 2 primeras. En el orden registrado, tu primer esfuerzo fue a 5:30/km. Tu último esfuerzo fue a 5:00/km.
```

Différence : moyenne des groupes et endpoints explicites ; plus long et plus personnel, sans conclusion d'amélioration physiologique. La qualité idiomatique espagnole reste à revoir humainement. Limites E/D/R. Appréciation : **+ / + / + / + / - / =**.

## 8. Déterminisme et comparaison avec l'expérience LLM

L'expérience antérieure rapportée par l'utilisateur indique **21 appels, 21 valides, médiane 0,68 s, 13/15 reproductibles**. Ce sont des nombres historiques **déclarés par l'utilisateur**, non remesurés par C379. Aucun nouveau vrai appel LLM n'a été effectué.

Les IDs d'options, prompts et choix bruts antérieurs n'ont pas été retrouvés dans le dépôt. Une comparaison exacte déterministe versus **les mêmes choix LLM historiques** ne peut donc pas être rejouée ; aucune préférence du LLM, égalité de résultat, économie mesurée, latence actuelle ou coût actuel n'est revendiqué.

L'entrée C374 à sélecteur injecté, l'adaptateur C359, les flags et fournisseurs restent existants et inchangés dans leur responsabilité. Les tests couvrent notamment ordre des options inversé, répétabilité, transport indisponible avec une seule tentative, absence de nouvel appel réseau et refus de texte altéré. Ce sont des contrôles de contrat, pas une mesure de qualité d'un LLM réel.

## 9. V2/V3 et validation : ce qui est établi et ce qui ne l'est pas

### Reproduction à preuve comparable

Le cas homogène utilise la **même fixture calculée**. C378 reçoit un `ScopedV2Evidence` rattaché au même utilisateur/workout, avec `coach_language` versionné, phases canoniques, efforts, effectifs, couverture et source admis.

V3 sans `coach_language` expose `interval.execution` avec une formulation de type « …ne permet pas… », ou une dispersion descriptive seule : ce n'est **pas** un verdict négatif opposé à « homogène ». En fournissant exactement le même `phase_analysis` **et** le même `coach_language`, V3 expose `interval.judgment` homogène et n'émet plus le `interval.execution` concurrent. Voir `narrative_coach_v3.py:73-108`, `196-267` et `test_v2_v3_disagreement_is_missing_input_not_opposite_verdict` (`backend/tests/test_hybrid_coach_c379.py:136-149`).

Les deux formulations prudentes existantes sont précisément « L'écart-type des allures décrit les variations entre les répétitions évaluées, sans suffire à affirmer qu'elles étaient régulières. » (`263`) et, sans comparaison exploitable, « La comparaison disponible ne permet pas d'établir la régularité des répétitions ; cela ne signifie pas qu'elles étaient irrégulières. » (`269`). Absence de verdict et verdict négatif ne sont pas interchangeables.

C379 précise la compréhension du scope dans C374 (nombre comparable, moyenne des groupes, endpoints enregistrés), sans changer admission ou calcul. **Aucune contradiction scientifique bloquante n'est reproduite dans ce cas.** Une vraie contradiction à preuves strictement identiques serait bloquante et exigerait un chantier scientifique séparé ; elle n'est pas résolue par un changement de prose.

### Résultats effectivement obtenus sur le HEAD testé

Résultats communiqués pour l'exécution d'implémentation ; la création du présent rapport n'a relancé ni tests, ni lint, ni build.

```text
cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && /tmp/c379-venv/bin/python -m pytest tests/test_hybrid_coach_c359.py tests/test_hybrid_coach_c362.py tests/test_hybrid_coach_c364_audit.py tests/test_hybrid_coach_c365.py tests/test_hybrid_coach_c371.py tests/test_hybrid_coach_c372.py tests/test_hybrid_coach_c374.py tests/test_hybrid_coach_c378.py tests/test_hybrid_coach_c379.py -q
=> 853 passed
```

- Flake8 existant, sélection de correction `E9,F63,F7,F82`, vérification finale sur **les sept fichiers Python modifiés** : **propre**.
- `git diff --check` : **propre**.
- CodeQL après chacun des deux commits de code : **zéro alerte**.
- Après CodeQL, vérification finale communiquée sur le même HEAD : **853 tests Coach réussis**, contrôle Flake8 des sept fichiers Python et `git diff --check` propres.
- Scan de secrets : **propre**.
- Les requirements existants et épinglés ont été restaurés pour les tests ciblés ; aucune dépendance projet n'a été ajoutée ou modifiée.

Suite supplémentaire optionnelle exécutée :

```text
tests/test_narrative_coach_v3.py tests/test_coach_language.py tests/test_workout_intelligence_v3.py
=> 701 passed, 2 failed
```

Les **deux échecs d'environnement** sont :

1. `tests/test_workout_intelligence_v3.py::test_c369_existing_http_response_serializes_both_observation_blocks`
2. `tests/test_workout_intelligence_v3.py::test_v3_api_endpoint_is_additive`

L'environnement isolé ne disposait pas de `fastapi` et des dépendances du serveur. Ces deux comportements API restent **non validés dans cet environnement** ; ils ne sont ni cachés, ni assimilés à des succès. La suite complète n'est pas déclarée verte.

## 10. Appréciation qualitative et recommandation

| Dimension | Lecture synthétique, sans métrique d'utilisateurs |
|---|---|
| Naturalité | Subjectivement meilleure pour les comparaisons historiques et plusieurs formulations d'effort ; certains commentaires restent identiques. Ce n'est pas une amélioration universelle. |
| Clarté | Le nombre de répétitions, « en moyenne » et les endpoints rendent les scopes plus explicites ; la FC seule reste volontairement prudente. |
| Utilité | Davantage d'illustrations concrètes quand admises, conseil conditionnel accessible dans le texte complet ; abstention quand la preuve ou l'intention manque. |
| Personnalisation | Uniquement les données, permissions et repères déjà admis ; aucun profil, objectif ou ressenti inventé. Corpus synthétique, donc pertinence vécue non démontrée. |
| Concision | Historique plus direct ; FC seule légèrement plus longue ; comparaison de groupes plus longue mais illustrée ; long parfois plus verbeux avec une moyenne de FC contextualisée. Pas de quota artificiel. |
| Fidélité | Valeurs/scopes/limites et traçabilité contrôlés par les tests ciblés ; pas de nouveau calcul ni d'inférence physiologique. Cela ne remplace pas une validation terrain. |

Limites résiduelles importantes : `faster_odd` s'abstient réellement sur la direction, malgré son nom ; `partial` désactive le bloc V3 d'allures sans invalider le jugement V2 à couverture complète ; easy/tempo/FC seule ne prouvent pas une intensité physiologique en l'absence de repères ; `long_history` conserve l'exclusion du second historique. Ces limites ne doivent pas être masquées par une formulation plus chaleureuse.

**Recommandation : HOLD avant intégration.** Les tests ciblés de l'implémentation sont verts et aucune contradiction scientifique n'est reproduite, mais il reste à archiver les choix expérimentaux bruts antérieurs pour les rendre rejouables, à effectuer une revue éditoriale humaine FR/EN/ES et à valider les deux tests API dans un environnement serveur complet. Ne pas confondre cette réalisation interne avec une intégration de production. **Aucun merge ni déploiement.**
