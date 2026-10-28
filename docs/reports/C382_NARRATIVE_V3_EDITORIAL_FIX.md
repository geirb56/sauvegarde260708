# C382 — Correction éditoriale de Narrative V3

## A. HEAD et fichiers inspectés

- Dépôt : `geirb56/sauvegarde260708`.
- Base exacte : `copilot/dev`, `8b9c6ba20eb74535f3ec27f2bfb9fe4b11e28c87`.
- HEAD initial : identique à la base ; `git ls-remote origin refs/heads/copilot/dev`
  a confirmé ce SHA avant toute modification.
- C381 est présent : ce HEAD est le merge de PR #375 ; son historique immédiat
  contient `7703578` (« C381: finalize audit report with tested HEAD and security results »).
- Branche de travail : `copilot/geirb56-correction-du-jargon-narrative-v3`.
- HEAD exact du code validé : `239b5d8dcc2f3f9e34c40126fb86538ada31a918`.
  Le rapport est ajouté après ce commit ; les commits documentaires ultérieurs
  ne modifient pas le code testé.

Audit en lecture seule effectué avant les modifications. Fichiers inspectés
(lignes de la base pour les sources de production) :

- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/narrative_coach_v3.py` :
  admission du jugement, construction des claims, cinq formulations, sélection
  de pertinence, rendu et validation ; notamment lignes 73–108, 177–298, 470–533.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/hybrid_coach_c359.py` :
  imports et recherche exhaustive de leurs références.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_narrative_coach_v3.py`.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_hybrid_coach_c381.py`.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_hybrid_coach_c379.py`.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_workout_consistency_c358.py`.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/fixtures/coach_session_synthesis_c351.json` :
  provenance explicitement synthétique, notamment pour le 10/10.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/pytest.ini`,
  `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/requirements.txt`,
  `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/conftest.py`.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/docs/reports/C381_DETERMINISTIC_TEXT_SELECTION.md`,
  `/home/runner/work/sauvegarde260708/sauvegarde260708/docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`,
  `/home/runner/work/sauvegarde260708/sauvegarde260708/DEPLOYMENT.md`.

Les rapports historiques sont des preuves complémentaires, pas une certification
de l'état actuel ni des séances Garmin réelles.

## B. Diagnostic du défaut

C381 a exposé les termes d'architecture « verdict V2 validé » dans les réserves
destinées aux coureurs. Le cinquième texte utilise « jugement V2 » plutôt que
« verdict V2 » ; il appartient au même défaut. Chaque formulation existe en
FR/EN/ES, sans variante alternative pour ces cinq appels `add`.

Le défaut est éditorial. Aucune modification scientifique n'est nécessaire :
absence de jugement ne signifie pas irrégularité ; dispersion mesurable ne
signifie pas régularité ; échantillon partiel ne qualifie pas toute la série.

### Conditions et preuves conservées

Dans le tableau suivant, « jugement » désigne strictement le résultat existant
de `_approved_repetition_judgment`, jamais une nouvelle interprétation.

| Cas | Condition exacte de construction | Claim / section | Références inchangées |
|---|---|---|---|
| 1 | Classification `intervals`, jugement absent, `usable_spread` vrai | `interval.execution` / `interpretation` | `phase_analysis.effort_regularity` |
| 2 | Classification `intervals`, jugement absent, `usable_spread` faux | `interval.execution` / `interpretation` | `session_classification.type`, `session_classification.limitations` ; si phases fournies : `phase_analysis.available`, `phase_analysis.effort_regularity.available` |
| 3 | Jugement absent et `unavailable` vrai | `interval.regularity` / `limitations` | Sans phases : `session_classification.limitations` ; sinon : `phase_analysis.available`, `phase_analysis.effort_regularity.available` |
| 4 | Jugement absent, `unavailable` faux, objet `phase_analysis` fourni | `interval.regularity` / `limitations` | `phase_analysis.effort_regularity` |
| 5 | Jugement absent, `unavailable` faux, aucune phase fournie | `interval.regularity` / `limitations` | `session_classification.confidence`, `session_classification.limitations` |

`usable_spread` exige : phases et régularité disponibles, nombre d'efforts
valide et identique, au moins deux allures échantillonnées et au plus le nombre
total d'efforts, dispersion finie et **supérieure ou égale à zéro**.
`unavailable` lit `effort_regularity_unavailable` sans phases, sinon les deux
indicateurs de disponibilité. Le cas 4 n'ajoute pas de contrôle numérique :
sa condition existante reste exactement inchangée, y compris si l'allure manque.

**Distinction construction / exposition :** le filtre de pertinence existant
écarte déjà `interval.regularity` et `interval.partial` du catalogue retourné.
Les trois formulations de limitation sont donc construites puis non exposées
sur ce chemin actuel. C382 corrige aussi ces textes dormants, sans les réactiver,
sans changer la sélection ni ajouter une nouvelle réserve visible.
Les tests observent les variables locales au retour de la fonction pour
contrôler ces branches avant filtrage, sans changer le code de production.

`interval.judgment`, ses trois bandes, leurs traductions, métriques et références
restent inchangés. Son admission conserve version, portée de comparabilité,
nombre total/comparé, valeurs finies, métrique et unicité de la conclusion.

## C. Tableau avant/après FR/EN/ES

Les numéros correspondent aux cinq cas ci-dessus. « consistent » exprime
la régularité en anglais courant, sans déclarer les répétitions comparables.

| Cas | Langue | Avant | Après |
|---|---|---|---|
| 1 | FR | En l'absence de verdict V2 validé, l'écart-type des allures décrit les variations entre les répétitions évaluées, sans suffire à affirmer qu'elles étaient régulières. | La mesure porte sur les écarts d'allure entre les efforts analysés ; elle ne suffit pas à déterminer si les répétitions ont été régulières. |
| 1 | EN | Without a validated V2 verdict, the pace standard deviation describes variation within the assessed repetitions, but does not by itself establish that they were regular. | The measure describes pace differences between the efforts analysed; this alone is not enough to determine whether the repetitions were consistent. |
| 1 | ES | Sin un veredicto V2 validado, la desviación estándar de los ritmos describe la variación entre las repeticiones evaluadas, pero no demuestra por sí sola que fueran regulares. | La medida describe las diferencias de ritmo entre los esfuerzos analizados; por sí sola no basta para determinar si las repeticiones fueron regulares. |
| 2 | FR | En l'absence de verdict V2 validé, la comparaison disponible ne permet pas d'établir la régularité des répétitions ; cela ne signifie pas qu'elles étaient irrégulières. | Les données disponibles ne permettent pas d'évaluer la régularité des répétitions ; cela ne signifie pas qu'elles étaient irrégulières. |
| 2 | EN | Without a validated V2 verdict, the supplied comparison cannot establish how evenly the repetitions were executed; this does not mean they were irregular. | The available data does not allow us to assess the consistency of the repetitions; this does not mean they were inconsistent. |
| 2 | ES | Sin un veredicto V2 validado, la comparación disponible no permite establecer la regularidad de las repeticiones; esto no significa que fueran irregulares. | Los datos disponibles no permiten evaluar la regularidad de las repeticiones; esto no significa que fueran irregulares. |
| 3 | FR | La régularité des efforts est indisponible en l'absence de verdict V2 validé ; les répétitions ne peuvent pas être dites régulières. | Les données sont insuffisantes pour déterminer si les répétitions ont été régulières. |
| 3 | EN | Effort regularity is unavailable without a validated V2 verdict; the repetitions cannot be called regular. | There is not enough data to determine whether the repetitions were consistent. |
| 3 | ES | La regularidad de los esfuerzos no está disponible sin un veredicto V2 validado; no se puede afirmar que las repeticiones sean regulares. | No hay datos suficientes para determinar si las repeticiones fueron regulares. |
| 4 | FR | Aucun verdict V2 de régularité validé n'est fourni ; l'écart-type des allures seul ne confirme pas des répétitions régulières. | Les variations d'allure mesurées ne suffisent pas, à elles seules, à conclure sur la régularité des répétitions. |
| 4 | EN | No validated V2 regularity verdict was supplied; pace standard deviation alone cannot confirm regular repetitions. | The measured pace variations alone are not enough to draw a conclusion about the consistency of the repetitions. |
| 4 | ES | No se proporcionó un veredicto V2 de regularidad validado; la desviación estándar de los ritmos sola no confirma repeticiones regulares. | Las variaciones de ritmo medidas no bastan, por sí solas, para concluir si las repeticiones fueron regulares. |
| 5 | FR | Aucun jugement V2 de régularité des répétitions validé n'est fourni ; la disponibilité ne prouve pas leur régularité. | Les informations disponibles ne permettent pas de conclure sur la régularité des répétitions. |
| 5 | EN | No validated V2 repetition-regularity judgment is supplied; availability does not establish regular repetitions. | The available information is not enough to draw a conclusion about the consistency of the repetitions. |
| 5 | ES | No se proporciona un juicio V2 validado sobre la regularidad de las repeticiones; la disponibilidad no demuestra su regularidad. | La información disponible no permite concluir si las repeticiones fueron regulares. |

Deux adaptations des propositions sont nécessaires sans changer leur sens :

1. Cas 1 : ne pas écrire « les allures varient », car la branche accepte aussi
   une dispersion égale à zéro. Décrire ce que mesure la valeur reste exact
   sans affirmer une variation non nulle ni modifier le seuil d'émission.
2. Cas 1 et 2 : conserver une seule phrase avec un point-virgule plutôt que
   deux phrases, afin de préserver le budget existant de six phrases.
   Une première exécution avec les points proposés a détecté cette régression ;
   la ponctuation a été corrigée, pas le budget ni la sélection.

## D. Diff exact et justification des imports

Diff de production : exactement quinze littéraux de texte remplacés aux
lignes 262–264, 268–270, 282–284, 289–291 et 295–297 de Narrative.
Chaque ligne « Avant » du tableau C correspond au littéral supprimé ;
chaque ligne « Après » au littéral ajouté. Aucun autre caractère du fichier
de production Narrative ne change. Une comparaison AST confirme cette
propriété, et l'identité du reste de l'arbre après substitution des 15 valeurs.

Seul autre diff de production, dans
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/hybrid_coach_c359.py` :

```diff
@@ -3,7 +3,6 @@
 from __future__ import annotations

 from dataclasses import dataclass
-import json
 import math
 import os
 import re
@@ -18,7 +17,7 @@
     format_recorded_seconds, RECORDED_WHOLE_DIGITS, realize_clause, validate_editorial_selection,
 )
-from narrative_coach_v3 import Transport, format_narrative_number
+from narrative_coach_v3 import Transport
 from hybrid_coach_v2_c372 import (
```

La recherche textuelle et l'analyse AST avant suppression trouvent **zéro**
référence de code à `json` et à `format_narrative_number` dans ce module.
`model_json_schema()` et `model_dump_json()` sont des méthodes de modèles :
elles n'utilisent pas le module `json`. `Transport` reste importé et utilisé.
Aucun import n'est supprimé dans Narrative, où ces outils restent nécessaires.

Commande reproductible pour le diff intégral exact, avec les deux SHA figés :

```bash
git -C /home/runner/work/sauvegarde260708/sauvegarde260708 diff \
  8b9c6ba20eb74535f3ec27f2bfb9fe4b11e28c87 \
  239b5d8dcc2f3f9e34c40126fb86538ada31a918 -- \
  /home/runner/work/sauvegarde260708/sauvegarde260708/backend/narrative_coach_v3.py \
  /home/runner/work/sauvegarde260708/sauvegarde260708/backend/hybrid_coach_c359.py
```

Les seuls autres changements de code sont des tests directement liés :
actualisation des assertions de vocabulaire, interdiction du jargon et 24 cas
paramétrés supplémentaires. Aucun test non lié n'est supprimé ou assoupli.

## E. Séances réelles : résultats et limites d'accès

| Séance demandée | Replay réel | Preuve accessible | Conclusion autorisée |
|---|---|---|---|
| 19/09/2026 | Non effectué | Aucun export authentifié de la séance retrouvé ; analogues synthétiques de données partielles dans les tests | Aucun verdict sur cette séance réelle |
| 10/10/2026 | Non effectué | Fixture C351 explicitement synthétique, et séances synthétiques avec jugement canonique | Aucun verdict sur cette séance réelle |

Le sandbox ne fournit pas de connexion déclarée via `MONGO_URL`,
`MONGODB_URI`, `MONGO_URI` ni de backend via `REACT_APP_BACKEND_URL`.
Aucun accès MongoDB/Garmin, appel réseau de replay ou changement de données
n'a été effectué. Les dates présentes dans les fixtures et rapports ne les
transforment pas en observations réelles. La phrase du 19/09 est donnée par
la demande ; son affichage runtime n'a pas été reproduit ici.

## F. Tests et non-régressions

### Environnement et exécutions

Python 3.12.3 ; configuration pytest existante inchangée :
`-n 2 --dist loadscope`. Dépendances locales de validation restaurées :
pytest 9.1.1, pytest-xdist 3.8.0, pydantic 2.13.4, requests 2.34.2,
python-dotenv 1.2.2, flake8 7.3.0 et pytest-asyncio 1.4.1.
Les dépendances vérifiées n'ont pas d'avis remonté par l'outil d'advisories.
Aucun fichier de dépendances n'a été changé.

Suite ciblée Narrative / C379 / C381 avec les 24 nouveaux cas :
**404 tests réussis**. Après adaptation finale du libellé à la dispersion
nulle, ces mêmes tests sont inclus dans la suite élargie réussie ci-dessous.

Suite élargie : **2221 tests réussis**. Commande exacte équivalente à
l'exécution depuis le répertoire backend, avec chemins absolus :

```bash
ROOT=/home/runner/work/sauvegarde260708/sauvegarde260708
cd "$ROOT/backend"
python -m pytest \
  "$ROOT/backend/tests/test_narrative_coach_v3.py" \
  "$ROOT/backend/tests/test_hybrid_coach_c359.py" \
  "$ROOT/backend/tests/test_hybrid_coach_c362.py" \
  "$ROOT/backend/tests/test_hybrid_coach_c364_audit.py" \
  "$ROOT/backend/tests/test_hybrid_coach_c365.py" \
  "$ROOT/backend/tests/test_hybrid_coach_c371.py" \
  "$ROOT/backend/tests/test_hybrid_coach_c372.py" \
  "$ROOT/backend/tests/test_hybrid_coach_c374.py" \
  "$ROOT/backend/tests/test_hybrid_coach_c378.py" \
  "$ROOT/backend/tests/test_hybrid_coach_c379.py" \
  "$ROOT/backend/tests/test_hybrid_coach_c381.py" \
  "$ROOT/backend/tests/test_coach_repetition_judgment.py" \
  "$ROOT/backend/tests/test_workout_analysis_v2_phases.py" \
  "$ROOT/backend/tests/test_workout_analysis_v2_facts.py" \
  "$ROOT/backend/tests/test_workout_analysis_v2_unified.py" \
  "$ROOT/backend/tests/test_workout_intelligence_v3.py" \
  "$ROOT/backend/tests/test_workout_consistency_c358.py" \
  "$ROOT/backend/tests/test_coach_language.py" \
  "$ROOT/backend/tests/test_coach_session_synthesis_c351.py" \
  -k 'not test_c369_existing_http_response_serializes_both_observation_blocks and not test_v3_api_endpoint_is_additive' \
  -q
```

**Limites explicites de la suite élargie :** une tentative initiale incluant
le module `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_workout_analysis_v2.py`
a rencontré une erreur de collecte (`httpx` absent). Deux tests HTTP de
Workout Intelligence ont échoué sur des dépendances absentes (`httpx`,
`fastapi`) et sont exclus de la commande réussie. Ces tests serveur et le
module de routes V2 ne sont **pas validés** par C382. Les échecs initiaux liés
à l'absence du plugin asyncio et aux anciennes assertions de texte C358 ont
été résolus par restauration du plugin existant et actualisation des seuls
libellés concernés. Aucun échec HTTP n'est présenté comme résolu.

### Couverture des exigences

- Les cinq branches, en FR/EN/ES, sont contrôlées avant le filtre de pertinence,
  avec leur texte exact, section, identifiant et références.
- Huit scénarios × trois langues : dispersion mesurable, dispersion nulle,
  échantillon partiel, allure absente, analyse indisponible, régularité
  indisponible, absence de phases avec/sans disponibilité déclarée.
- Les données sources restent identiques après rendu ; recalculs de régularité
  interdits dans le nouveau test.
- Rendu déterministe et validation de la sélection fermée donnent le même texte
  et les mêmes preuves ; aucun conseil n'est ajouté.
- Les textes visibles et tous les variants du catalogue observé excluent
  `V2`, `V3`, `verdict`, `veredicto` (recherche insensible à la casse).
  Les métadonnées techniques de protocole ne sont pas du texte utilisateur.
- Les tests existants de jugement canonique couvrent les trois bandes dans les
  trois langues et interdisent leur recalcul.
- La limite existante de six phrases reste vérifiée, sans modifier ce test.
- Les tests C381 conservent les interdictions de fournisseur/réseau ;
  aucun nouvel appel LLM n'est introduit.

### Comparaison avant/après et contrôles

Comparaison directe avec le module chargé depuis la base Git, sans modifier
ses sources : **39 scénarios localisés**, dont **9 avec jugement valide**
(trois bandes × trois langues).

- Tous les identifiants, sections, ordre des claims, références de preuves et
  variantes non ciblées restent identiques, avant **et** après filtrage.
- Les réponses avec jugement valide sont intégralement identiques.
- Les valeurs d'entrée restent identiques ; les nombres affichés, y compris
  zéro et couverture partielle, ne sont ni recalculés ni remplacés.
- L'AST Narrative ne diffère que par les 15 constantes annoncées.
- `git diff --check` : réussi.
- `python -m py_compile` sur les cinq fichiers Python modifiés : réussi.
- `python -m flake8 --select=E9,F63,F7,F82` puis `--select=F` sur ces cinq
  fichiers : réussis ; il s'agit de contrôles ciblés, pas d'un lint global.
- Scan de secrets des cinq fichiers Python avant commit : aucun secret détecté.
- Relecture indépendante : une affirmation de variation non nulle a été
  détectée puis corrigée ; seconde relecture sans problème significatif.
- CodeQL demandé sur le code commité : **ignoré par l'outil**, changements
  classés triviaux (textes, imports inutilisés, tests). Aucun scan complet
  CodeQL n'est revendiqué.
- Vérification finale après ce contrôle : **422 tests réussis**, suites
  Narrative, C379, C381 et C358, avec la commande suivante :

```bash
ROOT=/home/runner/work/sauvegarde260708/sauvegarde260708
cd "$ROOT/backend"
python -m pytest \
  "$ROOT/backend/tests/test_narrative_coach_v3.py" \
  "$ROOT/backend/tests/test_hybrid_coach_c379.py" \
  "$ROOT/backend/tests/test_hybrid_coach_c381.py" \
  "$ROOT/backend/tests/test_workout_consistency_c358.py" -q
```

Le rapport a également été scanné avant commit : aucun secret détecté.

## G. Verdict GO/HOLD pour merge

**GO pour la correction éditoriale C382**, sous revue humaine et contrôles
de PR requis : périmètre de production strictement limité aux textes et aux
deux imports prouvés inutilisés ; invariants scientifiques vérifiés.

Ce GO ne certifie ni les deux séances réelles non accessibles, ni les tests
HTTP bloqués par l'environnement, ni une validation globale du serveur.
Pas de nouveau moteur, permission, route, appel LLM, écriture Garmin/MongoDB,
déploiement ou merge automatique.

## H. Verdict séparé pour intégration du Coach hybride

**HOLD pour une intégration runtime du Coach hybride.**

C382 n'effectue et ne valide aucun branchement de production du Coach hybride.
La réussite des suites déterministes ne remplace ni la validation de ce
branchement, ni les replays réels manquants, ni les tests d'intégration HTTP.
Ce verdict est distinct du GO éditorial ; aucune intégration ou activation
n'est autorisée par ce rapport. Arrêt après création de la PR et du rapport.
