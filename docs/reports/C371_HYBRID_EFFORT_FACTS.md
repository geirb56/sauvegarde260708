# C371 — Faits individuels d’effort du Coach hybride

## Traçabilité de livraison

- Base canonique exacte : `bb9f8914ac030fcd98ca5702f55b0a80a1321bbe`.
- HEAD livré de l’implémentation et des tests :
  `17f233672cd4f408912816fbb1e9c3ffe9ebc0b5`.
- CodeQL Python exécuté après ce commit : **0 alerte**.
- Ce complément de traçabilité est ajouté ensuite dans un commit documentaire
  uniquement. Le HEAD complet final, incluant ce complément, est donné dans la
  description de PR ; aucun autre changement de code n’est annoncé testé
  implicitement.
- Cible : `copilot/dev`. Pas de merge, de déploiement ni d’activation.

## 1. Audit préalable, avant implémentation

Le 24 octobre 2026, la base locale et le HEAD distant de `copilot/dev`,
vérifié avec `git ls-remote origin refs/heads/copilot/dev`, sont identiques :
`bb9f8914ac030fcd98ca5702f55b0a80a1321bbe`.
La branche de travail est
`copilot/c371-exploitation-allures-durees-individuelles`.
Les rapports historiques ont été traités comme des instantanés, non comme
une preuve du comportement courant.

### Contrats effectivement lus

- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_intelligence_v3_models.py:163-245`
  définit deux blocs indépendants. Leur `status` global vaut `available`,
  `partial` ou `unavailable`. L’état individuel est un booléen `available`,
  et non une chaîne `"available"`.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_intelligence_v3.py:151-225`
  recopie les mesures V2 admissibles, sans recalcul. L’allure utilise `s/km`,
  la durée `s`. Une valeur absente ou rejetée reste `None`, jamais zéro.
- Chaque observation possède son propre identifiant :
  `recorded_effort_pace:{order}` ou `recorded_effort_duration:{order}`.
  Ces identifiants locaux à la séance sont différents pour une même phase ;
  leur égalité littérale n’est donc pas une règle d’association.
- La provenance déclarée attendue est `source=garmin`, `endpoint=typed-splits`,
  avec les méthodes respectives `workout_analysis_v2._phase_pace` et
  `workout_analysis_v2._build_phase_analysis`, ainsi que les chemins vers
  la phase Garmin et le champ de l’effort V2.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_analysis_v2.py:1852-1926`
  numérote les efforts, indépendamment des récupérations et de la disponibilité
  des mesures. `order` désigne une phase ; `effort_number` désigne un effort.
  Ils ne sont pas interchangeables. Les ordres du sous-ensemble des efforts
  peuvent être non contigus.
- Les tests C369 conservent même des numéros d’effort `2, 7`, avec des ordres
  `5, 9` et des indices V2 `0, 1` :
  `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_workout_intelligence_v3.py:520-535`.
  Il ne faut donc pas supposer que l’indice de provenance vaut toujours
  `effort_number - 1`.

### Disponibilité, couverture et limites

Les deux blocs peuvent fournir des mesures différentes ou être indépendamment
indisponibles. Un effort reste dans le bloc lorsque sa mesure manque ; les efforts
suivants ne sont pas renumérotés. Le nombre d’efforts enregistrés ne prouve ni
la couverture complète de la séance, ni la comparabilité des répétitions.
L’ordre enregistré ne certifie pas une chronologie absolue.

La normalisation typed-splits peut remplacer une mesure brute invalide par
`None` ; cette perte d’information ne permet plus de distinguer une valeur
initialement absente d’une valeur rejetée. Le cache tolère zéro, mais le
prédicat de mesure exploitable V2 exige une valeur finie strictement positive :

- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/garmin/data_layer.py:199-204` ;
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_analysis_v2_service.py:211-263` ;
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_analysis_v2.py:721-731`.

Les modèles ne constituent pas une certification de provenance : les copies
Pydantic peuvent contourner la validation. Le catalogue doit donc contrôler les
valeurs, les identités et les métadonnées, sans relire Garmin ou MongoDB.
Le loader existant construit déjà V2 puis V3 ; C371 ne doit pas le modifier.

### Admission et sélection existantes

L’audit de
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/hybrid_coach_c359.py`
et
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/hybrid_coach_editorial_c365.py`
confirme :

- accès vérifié avant la construction du catalogue ;
- permissions distinctes pour l’historique et la prescription ;
- fait `interval.count` limité aux comptages de phases ;
- sélection structurée de `fact_id` et `form`, champs supplémentaires interdits ;
- validation des identifiants, formes, intentions et redondances ;
- réalisation backend, sans phrase ni valeur libre du provider ;
- au maximum une information principale et deux soutiens ;
- fallback déterministe et activation hybride désactivée par défaut.

Les suites C359/C362/C364/C365 couvrent la frontière fermée actuelle ; les
cas historiques C360/C361 sont inclus dans leurs fixtures. Les cas C368/C369
sont dans la suite Workout Intelligence V3. Aucun module autonome C363 n’a été
identifié dans les suites concernées.

### Contrôle de la base intacte

Une archive de la base exacte, sans les modifications C371, a été testée
séparément : **1 306 réussites, 3 échecs, 14 avertissements**.
Les trois échecs reproduits sont :

- `test_workout_analysis_v2.py::test_comparable_history_stays_separate_and_metrics_are_unchanged[en]` ;
- le même cas `[fr]` ;
- le même cas `[es]`.

Ils attendent `meaning.consistent_pacing` et reçoivent
`meaning.hr_without_intensity_with_pacing`. Ni ces tests ni le moteur V2 ne
sont modifiés par C371. Leur existence n’est donc pas seulement reprise
d’un ancien rapport.

Les outils GitHub Actions ont également été consultés : les exécutions
renvoyées pour `copilot/dev` sont anciennes et ne certifient pas cette base.
La lecture des journaux d’échec du run `32418652111` ne renvoie aucun job
échoué. La preuve de comparaison C371 repose sur les exécutions locales de
la base exacte et du code livré, pas sur un statut CI ancien.

## 2. Fichiers concernés et périmètre

- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/hybrid_coach_c359.py` :
  admission défensive, catalogue borné, contexte et fallback déterministe.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/hybrid_coach_editorial_c365.py` :
  réalisation fermée FR/EN/ES, formatage fidèle et contrôle de redondance.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_hybrid_coach_c371.py` :
  observations synthétiques et transport injecté.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/docs/reports/C371_HYBRID_EFFORT_FACTS.md` :
  présent rapport.

Les contrats C368/C369, les calculs V3 et V2, les seuils, les prédictions,
les prescriptions, le moteur d’entraînement, le Coach narratif, les loaders,
les routes, le frontend et les abonnements restent hors modification.
`C359_HYBRID_COACH_ENABLED` conserve sa valeur désactivée par défaut.
Aucune dépendance du dépôt n’est ajoutée ou mise à jour.

## 3. Nouveau catalogue et association

Le vocabulaire est limité à trois nouveaux identifiants :

- `effort.first` : numéro et mesure(s) admissible(s) du premier effort
  dans l’ordre enregistré ;
- `effort.last` : même description pour le dernier effort enregistré,
  uniquement s’il est distinct ;
- `effort.coverage` : total enregistré et nombres de mesures admissibles,
  lorsque les identités et la couverture permettent un comptage cohérent.

Une durée et une allure ne sont réunies qu’après vérification de l’identité
de phase, du numéro d’effort et de la provenance V2/Garmin correspondante.
Une égalité de position dans les listes n’est jamais suffisante. Les unités,
méthodes, codes et identifiants sont contrôlés ; une mesure doit être
individuellement disponible, finie, strictement positive et non booléenne.
Les conflits d’identité et les doublons ne produisent pas de fait combiné.
Une mesure sûre peut donner un fait partiel, explicitement limité à la mesure
admissible. Aucun remplacement par une moyenne, une valeur prescrite ou une
mesure de récupération n’est effectué.

La revue a fait corriger deux cas limites avant livraison :

- l’indice V2 est extrait du chemin canonique et vérifié indépendamment du
  numéro d’effort ; les références locales conservent la position réelle dans
  chaque bloc V3, même si les listes sont réordonnées ;
- une identité malformée ne disparaît pas silencieusement du choix des bornes :
  son ordre connu est conservé, ou les bornes incertaines sont écartées
  du catalogue si aucun autre bloc fiable ne permet de les établir.
  Un effort intérieur ne devient donc pas artificiellement « premier » ou
  « dernier ».

Les comptages de mesures sont recalculés à partir de l’admission, pas déduits
du type de séance ni recopiés aveuglément depuis les compteurs globaux.
Un bloc absent n’autorise pas à afficher un compteur de disponibilité nul
pour cette mesure. Le nombre disposant des deux mesures exige des identités
associables ; la couverture n’est pas une certification de séance complète.

## 4. Politique de sélection

La politique descriptive ne cherche ni le plus rapide ni le plus lent :

1. Déterminer les bornes de l’ordre enregistré indépendamment des valeurs.
2. Proposer au maximum ces deux efforts, sans remplacer une borne inexploitable
   par une répétition intérieure « intéressante ».
3. Ajouter au plus un fait de couverture admissible.

Le provider ne reçoit donc jamais automatiquement toutes les répétitions.
Ces bornes sont des exemples descriptifs reproductibles, **pas un échantillon
statistiquement représentatif**, une preuve de chronologie absolue ou un
argument de fatigue. Aucun jugement de régularité, ralentissement,
accélération, intensité physiologique, conformité ou progression n’est créé.

Le fallback privilégie un effort distinctif et reste limité à trois clauses.
Les lectures historiques et la prescription déjà autorisées restent disponibles ;
elles sont prioritaires sur des soutiens supplémentaires d’effort.
La validation interdit la sélection simultanée de `effort.coverage` et
`interval.count`, qui répéterait le total d’efforts.
Sans observations exploitables, les faits et la sélection historiques restent
inchangés.

## 5. Réalisation et précision

L’architecture C365 est conservée :
**faits admis → identifiants/formes → validation → réalisation backend**.
Pour les nouveaux faits, seules les formes `direct` et `explain` sont admises.
Le LLM ne fournit ni phrase, ni valeur, ni unité, ni interprétation, ni liaison
causale. Les champs supplémentaires et les identifiants inconnus sont rejetés.

Le formatage part de la représentation décimale de la valeur admise et la
décompose en minutes/secondes sans arrondir à la seconde ou à la minute.
Les décimales significatives de cette représentation sont conservées, y
compris aux frontières de minute et pour les valeurs subsecondes.
Ce choix préserve la précision exposée par V3 ; il ne certifie pas la précision
physique du capteur. La virgule est utilisée en FR/ES, le point en EN.
Une allure est affichée sous la forme `4'48/km` en FR, `4:48/km` en EN/ES.

### Exemples FR/EN/ES issus des tests

Le test `test_natural_backend_sentence_preserves_recorded_order_scope`
vérifie exactement ces phrases, pour la fixture de durée `240 s` et
d’allure `288 s/km` :

- FR : « Dans l'ordre enregistré par Garmin, le premier effort (n° 1) a duré
  4 min, à 4'48/km. »
- EN : « In Garmin's recorded order, the first effort (no. 1) lasted 4 min
  at 4:48/km. »
- ES : « En el orden registrado por Garmin, el primer esfuerzo (n.º 1) duró
  4 min, a 4:48/km. »

Couverture de la fixture à quatre efforts : « Sur 4 efforts enregistrés par
Garmin : 4 avec allure, 4 avec durée, 4 avec les deux. » Les équivalents testés
sont « Of 4 Garmin-recorded efforts: 4 with pace, 4 with duration, 4 with both. »
et « De 4 esfuerzos registrados por Garmin: 4 con ritmo, 4 con duración,
4 con ambos. » Le cas d’un seul effort utilise le singulier dans les trois langues.

`test_localized_exact_realization` conserve également `288.125 s/km` en
`4'48,125/km`, `4:48.125/km` et `4:48,125/km`. Une durée `60.000001 s`
reste `1 min 00,000001 s` en FR/ES et `1 min 00.000001 s` en EN.
Il n’y a aucun arrondi implicite vers `1 min`.

## 6. Matrice de validation synthétique

Le nouveau fichier de tests couvre :

| Exigences | Vérification |
|---|---|
| Quatre efforts, un seul effort | Valeurs, couverture et absence de duplication d’un effort unique |
| Allure seule, durée seule | Faits partiels, aucun compteur inventé pour un bloc absent |
| Identités incohérentes, doublons | Quarantaine des conflits ; aucune association par simple position |
| Ordres non contigus, listes réordonnées | Bornes enregistrées et association indépendante de la position |
| `None`, zéro, négatifs, booléens, NaN, infinis | Rejet individuel et retrait des comptages admissibles |
| Couverture partielle, compteurs incohérents | Recalcul défensif et omission de couverture non démontrée |
| Absence de phases | Conservation du comportement historique |
| Provenance non admissible | Rejet de source, endpoint, méthode, unité, code, identifiant ou chemin incorrect |
| Doublons avec `interval.count` | Sélection redondante rejetée |
| Volume transmis et sélection | Catalogue d’efforts borné, au plus deux soutiens |
| FR/EN/ES et décimales | Formatage exact, frontières de minutes, sous-secondes et exposants |
| Identifiant inexistant, phrase ou valeur LLM | Rejet structuré, puis fallback |
| Fatigue, régularité, progression | Aucun fait ou champ libre n’autorise ces interprétations |
| Historique et prescription | Permissions inchangées et conservation des faits autorisés |
| Échec provider | Description déterministe disponible sans détail privé d’exception |
| Isolation et absence de nouveaux accès | Appels injectés, pièges réseau, absence de mutation et absence d’état partagé |
| Activation | Aucun appel provider quand le flag reste absent |

L’isolation de propriété de la séance reste celle du loader existant :
le catalogue reçoit un V3 déjà chargé dans le périmètre utilisateur.
Les essais C368/C369 et C367 existants couvrent également les identifiants Garmin
identiques entre utilisateurs ; C371 n’ajoute aucun chargement ni cache partagé.

## 7. Risques résiduels

- Validation synthétique et offline uniquement : aucun LLM réel, aucune donnée
  personnelle Garmin, aucune évaluation éditoriale en production.
- Les métadonnées V3 permettent de contrôler une provenance structurée ; elles
  ne certifient ni le capteur ni l’authenticité d’un objet entièrement forgé en
  mémoire. Les autorités d’ingestion et d’autorisation restent inchangées.
- Les bornes décrivent seulement les efforts enregistrés ; elles ne
  représenteraient pas à elles seules une séance complète ou une distribution
  statistique.
- L’absence d’une mesure exploitable ne permet pas d’identifier rétroactivement
  sa cause brute.
- Aucun verdict de régularité V2 n’est réutilisé : ce sujet reste réservé à C372.
- Les trois échecs V2 historiques restent visibles ; une suite contenant ces
  cas ne doit pas être annoncée verte.
- Aucun build frontend ni déploiement n’est réalisé, ces domaines n’étant pas
  modifiés. L’activation du Coach hybride demeure hors périmètre.

## 8. Environnement et exécution de référence

Python système ne disposait initialement pas de pytest. Les dépendances
nécessaires ont été restaurées dans un environnement isolé, sans modifier
les manifests du dépôt. Les vérifications d’advisories ont conduit à utiliser
des versions corrigées dans cet environnement, et non à changer les
dépendances applicatives livrées.

Environnement de référence : Python 3.12.3, pytest 9.1.1, pytest-xdist 3.6.1,
Pydantic 2.13.4, FastAPI 0.110.1, httpx 0.28.1, flake8 7.3.0,
Motor 3.7.1, PyMongo 4.19.0, PyJWT 2.14.0 et cryptography 50.0.0.
Ce n’est pas une installation à l’identique de toutes les versions du
manifest. La configuration existante `-n 2 --dist loadscope` est conservée.

Base extraite par `git archive bb9f8914ac030fcd98ca5702f55b0a80a1321bbe`,
puis :

```bash
cd /tmp/c371-baseline-repo/backend
/tmp/c371-venv/bin/python -m pytest \
  tests/test_hybrid_coach_c359.py \
  tests/test_hybrid_coach_c362.py \
  tests/test_hybrid_coach_c364_audit.py \
  tests/test_hybrid_coach_c365.py \
  tests/test_historical_max_hr_c367.py \
  tests/test_workout_intelligence_v3.py \
  tests/test_workout_analysis_v2.py \
  tests/test_workout_analysis_v2_facts.py \
  tests/test_workout_analysis_v2_phases.py \
  tests/test_workout_analysis_v2_unified.py \
  tests/test_narrative_coach_v3.py \
  tests/test_garmin_laps_analysis_c343.py -v --tb=short
```

Résultat exact : **1 306 passed, 3 failed, 14 warnings**.

| Suite de base | Réussites | Échecs |
|---|---:|---:|
| C359 | 60 | 0 |
| C362, incluant fixtures C360/C361 | 74 | 0 |
| C364 | 32 | 0 |
| C365 | 78 | 0 |
| C367 | 38 | 0 |
| Workout Intelligence V3, C368/C369 inclus | 145 | 0 |
| Workout Analysis V2 principal | 171 | 3 |
| Workout Analysis V2 facts | 145 | 0 |
| Workout Analysis V2 phases | 108 | 0 |
| Workout Analysis V2 unified | 85 | 0 |
| Narrative Coach V3 | 227 | 0 |
| Garmin laps C343 | 143 | 0 |

Ces nombres sont les cas effectivement exécutés après paramétrisation, et non
un décompte de fonctions de test.

Les essais préparatoires avec des dépendances serveur manquantes ont donné
**1 169 réussites, 9 échecs et 2 erreurs de collecte** ; ils ne sont pas présentés
comme une validation fonctionnelle. L’environnement a ensuite été complété.
Les résultats de livraison doivent être lus sur l’exécution complète finale,
avec les trois seuls échecs V2 reproduits sur base.

### Résultats finaux de livraison

L’exécution finale utilise un environnement isolé de validation supprimé après
usage. Python 3.12.3, pytest 9.1.1, Pydantic 2.13.4, FastAPI 0.110.1 et
httpx 0.28.1 sont communs aux exécutions ; pytest-xdist y est en **3.8.0**
et PyMongo en **4.18.2**, contre 3.6.1 et 4.19.0 pour l’environnement de base.
Cette différence est déclarée, pas présentée comme une reproduction binaire
identique des environnements.

Commande finale, depuis le dépôt réellement modifié, sans réexécuter
l’archive de base :

```bash
cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend
set -o pipefail
TMPDIR=/home/runner/work/sauvegarde260708/sauvegarde260708/.env.c371-validation \
/home/runner/work/sauvegarde260708/sauvegarde260708/.env.c371-validation/bin/python -m pytest \
  tests/test_hybrid_coach_c359.py \
  tests/test_hybrid_coach_c362.py \
  tests/test_hybrid_coach_c364_audit.py \
  tests/test_hybrid_coach_c365.py \
  tests/test_hybrid_coach_c371.py \
  tests/test_historical_max_hr_c367.py \
  tests/test_workout_intelligence_v3.py \
  tests/test_workout_analysis_v2*.py \
  tests/test_narrative_coach_v3.py \
  tests/test_garmin_laps_analysis_c343.py -q 2>&1 | \
tee /home/runner/work/sauvegarde260708/sauvegarde260708/.env.c371-validation/c371-final-tests.txt
```

- Nouvelle suite C371 : **125 tests réussis**, aucun échec.
- Ensemble complet demandé, C343 ajouté en non-régression :
  **1 431 passed, 3 failed, 14 warnings**, en 3,51 s.
- Les trois échecs sont exactement les cas V2 `[en/fr/es]` identifiés plus haut :
  aucun nouvel échec ne subsiste.
- Les **1 306 cas existants réussis sur base réussissent encore**, auxquels
  s’ajoutent les 125 cas C371.
- C359–C365, C367, V3/C368/C369, Narrative Coach V3 et les trois autres
  fichiers V2 restent sans échec ; le fichier V2 principal garde ses
  171 réussites et ses 3 échecs historiques.
- Le contrôle flake8 ciblé `E9,F63,F7,F82` des trois fichiers Python modifiés
  et `git diff --check` réussissent.

Commande de lint effectivement exécutée :

```bash
cd /home/runner/work/sauvegarde260708/sauvegarde260708
/home/runner/work/sauvegarde260708/sauvegarde260708/.env.c371-validation/bin/python -m flake8 \
  /home/runner/work/sauvegarde260708/sauvegarde260708/backend/hybrid_coach_c359.py \
  /home/runner/work/sauvegarde260708/sauvegarde260708/backend/hybrid_coach_editorial_c365.py \
  /home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_hybrid_coach_c371.py \
  --select=E9,F63,F7,F82
git diff --check
```

La suite élargie est donc **non verte**, même si C371 ne crée aucun échec
supplémentaire. Aucun test historique n’a été supprimé, modifié ou neutralisé.

## 9. Revue de non-régression

La revue indépendante du diff a identifié le déplacement artificiel d’une borne
lorsqu’une identité invalide était omise d’un bloc unique. Ce défaut a été
corrigé, avec des régressions dédiées allure seule/durée seule, première/dernière
identité et listes réordonnées. La seconde revue confirme sa résolution et ne
signale aucun autre défaut de correction à forte confiance.

Un test de raccordement utilise également les extracteurs réels V2→V3 avec des
numéros d’effort non contigus ; les tests synthétiques ne reposent donc pas
uniquement sur une fixture reproduisant une hypothèse d’indice.
Les références d’évidence pointent vers les positions réelles des observations
V3 admises, sans transmettre les chemins ni les identifiants privés au provider.

Le scan de secrets des quatre fichiers livrés ne détecte aucun secret.
CodeQL Python, exécuté après le commit de l’ensemble du code modifié,
ne trouve **aucune alerte**. Les changements sont classés non triviaux :
ils modifient effectivement l’admission et la sélection des faits.
Les environnements, journaux et fichiers temporaires de validation ont été
retirés du workspace ; ils ne font pas partie de la livraison.

## 10. Verdict

**GO pour la revue de la PR C371, limitée à la description factuelle offline.**

Les critères synthétiques d’admission, d’association, de volume, de réalisation
fermée et de fallback sont satisfaits. Les trois échecs V2 préexistants restent
explicitement signalés. **HOLD pour toute activation ou généralisation
produit** : le verdict expérimental C365 reste inchangé, et aucun LLM réel
n’a été évalué.

Une seule PR cible `copilot/dev`. Aucun merge, déploiement ou changement
d’activation n’est effectué. C372 reste distinct.
