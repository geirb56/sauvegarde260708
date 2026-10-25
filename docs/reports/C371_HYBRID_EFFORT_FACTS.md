# C371 — Faits individuels d’effort du Coach hybride

**État courant avant merge : section 12, contre-vérification de la PR #367.**
Les sections précédentes conservent les preuves de la première livraison.

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

---

## 11. Patch de sécurisation avant merge — PR #367

**Cette section actualise la première livraison ci-dessus.** En particulier,
la conservation de précision n’autorise plus le développement arbitraire des
exposants extrêmes. Les mesures V3 restent intactes ; seule leur admissibilité
à l’affichage hybride est limitée.

### 11.1 Audit préalable et HEAD

Le 24 octobre 2026, avant modification, l’API GitHub et les références Git
confirment :

- PR #367 ouverte, non mergée ;
- branche exclusive de travail :
  `copilot/c371-exploitation-allures-durees-individuelles` ;
- HEAD avant correction : `91577d88a09eefd3e88fd7541adf1a409027b17a` ;
- HEAD après correction fonctionnelle et tests :
  `c1981b2d1e77db95c8a0c16f1b3bfa5d6e48a3fa` ;
- base de PR et HEAD `copilot/dev` :
  `bb9f8914ac030fcd98ca5702f55b0a80a1321bbe`.

Ce complément de résultats et de HEAD est documentaire uniquement ; le SHA
du dernier commit documentaire est précisé sur la PR existante. Aucun code
supplémentaire n’est implicitement annoncé testé.

Les deux modules hybrides et la totalité de la suite C371 ont été relus.
Les contrats ont été revérifiés dans :

- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_intelligence_v3_models.py:163-245` ;
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_intelligence_v3.py:151-225`.

Le transfert V2→V3 accepte les mesures positives finies sans budget de
représentation éditoriale. Les modèles Pydantic et `model_copy` ne garantissent
pas ce budget. Les mesures parviennent au catalogue hybride, puis à
`realize_clause`, **avant** l’appel provider et son bloc de gestion d’erreurs.
Une protection uniquement autour du provider ne corrigerait donc pas le risque.

Les protections déjà présentes sont conservées, sans duplication :

- admission individuelle, provenance, finitude et stricte positivité ;
- catalogue C371 borné à deux efforts et une couverture ;
- sélection d’une clause principale et de deux soutiens ;
- schéma fermé et refus des phrases/valeurs libres ;
- timeout provider de 8 s ;
- réponse provider limitée à 2 400 caractères, refus du marqueur
  `response_truncated`.

En revanche, cette limite concernait le **JSON reçu du provider**, pas les
affirmations préconstruites, le contexte JSON sortant ou le texte réalisé
côté backend. La vérification historique de longueur dans
`validate_generated_narrative` appartient à l’ancien chemin de prose et ne
protège pas la réalisation fermée C365.

### 11.2 Problèmes reproduits sur le HEAD intact

L’archive Git de `91577d88a09eefd3e88fd7541adf1a409027b17a`, testée dans
le même environnement que le patch, reproduit :

| Cas | Comportement avant correction |
|---|---|
| Durée `1e308`, EN | Développement en une chaîne de **316 caractères** |
| Allure `5e-324`, EN | Développement en une chaîne de **332 caractères** |
| Appel direct avec entier `10**5000` | `ValueError` pendant la conversion en chaîne |
| Appel direct avec `"oops"` | `decimal.InvalidOperation` |
| Quatre efforts + observation d’intensité admissible | Sélection `effort.first`, `effort.last`, `effort.coverage` ; l’intensité disparaît malgré une place utilisée pour la couverture |

La protection `_finite` rejetait déjà l’entier immense dans le parcours
normal d’admission. Le durcissement du formateur ne prétend pas réparer une
exception de cet entier dans ce parcours : il rend aussi l’appel direct sûr.
En revanche, `1e308` et `5e-324` passaient réellement l’admission précédente.
Des identifiants entiers immenses pouvaient également atteindre une conversion
en chaîne avant tout affichage ; leur contrôle est placé en amont.

### 11.3 Correctifs et justification des limites techniques

**Représentation d’une mesure :**

- types Python exacts `int` ou `float`, sans coercition des chaînes/booléens ;
- réserve d’affichage de **6 chiffres entiers de secondes** ;
- réserve de **18 positions décimales** au maximum dans la représentation
  décimale canonique de la valeur ;
- contrôle avant `str` d’un entier immense et avant développement de
  l’exposant de `Decimal` ;
- retour `None` si la mesure n’est pas représentable, sans exception générique,
  arrondi, troncature ou valeur de remplacement.

Ces réserves bornent une mesure formatée à **34 caractères** au maximum :
5 chiffres de minutes, ` min `, 2 chiffres de secondes, un séparateur décimal,
18 positions décimales et ` s`. Une allure nécessite au plus 30 caractères.
Les valeurs admissibles conservent exactement la précision de `str(value)` ;
les zéros finaux non significatifs peuvent être omis comme auparavant.

Il s’agit d’un **budget d’interface**, pas d’un seuil de validité Garmin ou
physiologique : une mesure rejetée n’est pas déclarée scientifiquement
impossible, et une mesure affichable n’est pas certifiée plausible. Aucun
calcul V2/V3 ni contrôle scientifique n’est modifié. La frontière
`1 000 000 s` exclue découle des six emplacements entiers, et non d’une
prescription ou d’un seuil d’effort.

Le catalogue utilise ce résultat **avant** de construire son affirmation.
Seule la mesure concernée est exclue ; l’autre mesure de l’effort, les
identités cohérentes et les faits historiques indépendants restent disponibles.
Les compteurs de couverture sont recalculés sur les mesures ainsi admises.
Les numéros et ordres affichables sont également limités à six chiffres,
sans renumérotation ni remplacement d’une borne enregistrée.

**Faits et composition :**

- les trois faits C371 restent bornés avant le prompt ; aucun envoi de toutes
  les répétitions n’est ajouté ;
- les tests vérifient chaque forme FR/EN/ES à **256 caractères maximum par
  nouveau fait** et trois clauses C371 à **770 caractères maximum**, espaces
  compris ;
- le contexte JSON sortant est limité explicitement à **24 000 caractères**,
  soit dix fois le budget du commentaire, pour réserver de la place au
  catalogue, aux contraintes et au schéma ; au-delà, le provider n’est pas
  appelé et le fallback déjà construit est conservé ;
- ce budget porte sur le JSON de contexte, pas sur le message système fixe ;
  il n’est pas une estimation de tokens ;
- le texte Coach est limité explicitement à **2 400 caractères** : le fallback
  conserve les clauses indépendantes entières qui tiennent dans le budget ;
  une composition éditoriale trop longue est refusée en bloc, avec conservation
  du fallback. Aucun texte n’est coupé au milieu d’une mesure ou d’une unité.

Les essais aux frontières produisent au maximum **26 caractères par mesure**,
**126 par nouveau fait**, **338 pour trois faits C371** et **6 512 pour le
contexte JSON**. Ce sont des maxima observés sur la matrice de test, distincts
des budgets techniques garantis.

### 11.4 Priorisation : correction minimale démontrée

Le cas reproduit montrait une observation d’intensité évincée par les deux
autres descriptions d’effort. L’ordre de remplissage des places de soutien
privilégie maintenant `intensity.position`, puis `intensity.hr`, avant
`effort.last` et `effort.coverage`.

Pour la fixture à quatre efforts, le fallback devient
`effort.first`, `intensity.position`, `effort.last`.
Pour la fixture avec historique corroboré et sans prescription, il conserve
l’effort, la tendance et l’intensité. Les comparaisons historiques, tendances,
sorties longues et conclusions de prescription déjà prioritaires sont
conservées ; leurs permissions restent inchangées.

L’effort reste la première description lorsqu’il est admissible. Aucun moteur
de classement n’est créé. Lorsque effort, historique et prescription occupent
les trois places, une quatrième observation ne peut pas être ajoutée :
cette limite reste explicite, et la refonte de hiérarchisation est réservée
à C373.

### 11.5 Tests réellement exécutés

Environnement isolé `/tmp/c371-patch-venv`, sans modification de manifest :
Python 3.12.3, pytest 9.1.1, pytest-xdist 3.8.0, Pydantic 2.13.4,
FastAPI 0.110.1, httpx 0.28.1, flake8 7.3.0, Motor 3.7.1,
PyMongo 4.18.2, PyJWT 2.14.0 et cryptography 50.0.0.
Les dépendances de validation restaurées ont été contrôlées par advisories.
La configuration `-n 2 --dist loadscope` n’est pas modifiée.

Même commande de suites sur l’archive intacte puis dans le dépôt modifié :

```bash
cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend
/tmp/c371-patch-venv/bin/python -m pytest \
  tests/test_hybrid_coach_c359.py \
  tests/test_hybrid_coach_c362.py \
  tests/test_hybrid_coach_c364_audit.py \
  tests/test_hybrid_coach_c365.py \
  tests/test_hybrid_coach_c371.py \
  tests/test_historical_max_hr_c367.py \
  tests/test_workout_intelligence_v3.py \
  tests/test_workout_analysis_v2*.py \
  tests/test_narrative_coach_v3.py \
  tests/test_garmin_laps_analysis_c343.py -q
```

L’exécution de base utilise comme répertoire
`/tmp/c371-patch-base/backend`, extrait du HEAD avant correction.

| Exécution | Réussites | Échecs | Avertissements |
|---|---:|---:|---:|
| Base scientifique antérieure, documentée | 1 306 | 3 V2 | 14 |
| Première livraison C371, documentée | 1 431 | 3 V2 | 14 |
| HEAD C371 avant patch, reproduit ici | 1 431 | 3 V2 | 12 |
| Patch, suite C371 seule | **211** | **0** | 0 |
| Patch, ensemble complet | **1 517** | **3 V2** | **12** |

Les avertissements diffèrent de la livraison historique, pas les échecs.
La comparaison reproduite utilise le même environnement de validation.
Les trois échecs restent exactement
`test_comparable_history_stays_separate_and_metrics_are_unchanged[en/fr/es]`
dans Workout Analysis V2 : attendu `meaning.consistent_pacing`, obtenu
`meaning.hr_without_intensity_with_pacing`.
**La suite élargie n’est pas verte. Aucun nouvel échec ne subsiste.**

Les anciennes attentes C371 qui autorisaient l’affichage des exposants extrêmes
sont adaptées à la nouvelle politique demandée ; aucun test V2 ni autre test
historique n’est modifié. Le gain net est de 86 cas exécutés.

Nouveaux contrôles : extrêmes grands/petits, limites incluses/exclues,
malformations, booléens et non-finis, entiers immenses, mesure partielle,
toutes mesures exclues, absence d’efforts, exactitude décimale FR/EN/ES,
longueur maximale de chaque forme et composition, contexte à sa limite et
au-delà, réponse provider trop longue, maintien des clauses indépendantes,
fallback après échec provider et conservation de l’intensité.

Un premier essai a échoué en collecte parce que pytest cherchait à convertir
`10**5000` en identifiant de test. Des identifiants explicites de fixture
corrigent ce problème sans relever la limite Python de conversion et sans
modifier la protection applicative.

Contrôles complémentaires :

```bash
cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend
/tmp/c371-patch-venv/bin/python -m flake8 \
  hybrid_coach_c359.py hybrid_coach_editorial_c365.py \
  tests/test_hybrid_coach_c371.py --select=E9,F63,F7,F82
git diff --check
```

Résultat : **réussis**. Revue indépendante du patch : aucun défaut significatif
signalé. Les outils GitHub Actions ont été consultés ; le run précédent
`40128395471` ne comporte aucun job échoué et n’est pas présenté comme une
preuve des nouveaux tests. Les résultats ci-dessus sont les exécutions locales.
Le scan des quatre fichiers modifiés ne détecte aucun secret. CodeQL Python
après commit de toutes les corrections fonctionnelles : **0 alerte**.

### 11.6 Non-régressions, risques résiduels et verdict

Fichiers concernés uniquement :

- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/hybrid_coach_c359.py` ;
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/hybrid_coach_editorial_c365.py` ;
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_hybrid_coach_c371.py` ;
- `/home/runner/work/sauvegarde260708/sauvegarde260708/docs/reports/C371_HYBRID_EFFORT_FACTS.md`.

Aucun changement V2, V3 scientifique, modèle C368/C369, contrat Garmin,
seuil, prescription, prédiction, Coach narratif, API, frontend ou abonnement.
Aucun appel Garmin/GCCLI, MongoDB production ou LLM externe. Aucune dépendance
applicative ajoutée. `C359_HYBRID_COACH_ENABLED` reste désactivé par défaut.

Risques résiduels : un budget de représentation n’est pas une validation
physiologique ; des données affichables mais erronées restent du ressort de
l’ingestion. Certaines mesures exactes seront volontairement omises si elles
dépassent le budget, sans récupération ni arrondi. En situation de contexte
trop volumineux, la sélection éditoriale est abandonnée au profit du fallback.
La hiérarchisation globale et l’évaluation avec LLM réel restent hors périmètre.

**GO pour revue du patch de sécurisation sur la PR #367 existante. HOLD pour
activation produit.** Aucun merge ni déploiement, aucune nouvelle PR.

---

## 12. Contre-vérification et complément minimal — 25 octobre 2026

### 12.1 Base et HEAD exacts

L’API GitHub et Git local confirment avant modification :

- PR existante **#367**, ouverte, draft, non mergée ;
- branche exclusive : `copilot/c371-exploitation-allures-durees-individuelles` ;
- base exacte `copilot/dev` : `bb9f8914ac030fcd98ca5702f55b0a80a1321bbe` ;
- HEAD reçu avant cette intervention : `0b9c0c90acc34b06c94822bbb614028884a8155e` ;
- HEAD après correction fonctionnelle et tests :
  `340ec4ce75e375133cb5bd259aae52fe95c8a867`.

Le présent complément est un commit documentaire ultérieur ; le SHA ci-dessus
désigne précisément le code validé, pas le commit qui contient ce rapport.
Le durcissement de la section 11 était **déjà présent** au HEAD reçu :
il n’est ni réimplémenté ni attribué à cette nouvelle intervention.

### 12.2 Audit et problèmes effectivement reproduits

Les deux modules hybrides, l’ensemble de la suite C371 et les contrats
C368/C369 ont été relus dans les fichiers indiqués en sections 11.1 et 11.6.
Le parcours reste V2 → observations V3 → admission individuelle hybride →
affirmation backend → sélection → réalisation fermée. Les copies Pydantic
peuvent contourner la validation du modèle, mais pas les contrôles d’admission.

Les tests existants reproduisent le rejet de `1e308`, `5e-324`, des chaînes
malformées, non-finis et entiers immenses, **avant l’affirmation**. Ils vérifient
aussi les frontières admissibles, la précision décimale, une mesure rejetée
avec l’autre conservée, toutes les mesures rejetées et l’absence d’efforts.
Les faits indépendants et le fallback restent disponibles. Aucune protection
numérique supplémentaire n’est nécessaire sur ce HEAD.

Une régression éditoriale résiduelle a en revanche été reproduite :

| Même autorité V3, historique et prescription autorisés | Fallback avant complément |
|---|---|
| Sans observations C371, tendance corroborée et moyenne au-dessus de LT2 | `trend.probable_improvement`, `intensity.position`, `prescription.review` |
| Avec les observations C371 | `effort.first`, `trend.probable_improvement`, `prescription.review` |

L’observation d’intensité admise disparaissait donc au seul ajout des mesures
d’effort. Le même problème existe avec `effort.last` seul et une comparaison
historique sans tendance corroborée. **Les 12 nouveaux cas FR/EN/ES échouent
avant le correctif**, puis réussissent après.

### 12.3 Correctif exact et limites techniques conservées

Dans
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/hybrid_coach_c359.py`,
cinq lignes ajoutent une exception locale au choix du fallback : si historique,
prescription et `intensity.position` déjà admise avec `position=above_LT2`
occupent les trois places utiles, conserver ces trois faits plutôt que
d’évincer l’intensité pour une borne d’effort.

La comparaison/tendance principale utilise l’ordre historique existant.
Aucun seuil n’est recalculé : `above_LT2` est la position V3 déjà contrôlée.
Il n’y a ni nouveau moteur de classement, ni changement de la réalisation
provider, des permissions ou du maximum de trois clauses. Dans les autres
situations, les choix existants restent inchangés.

Les budgets de représentation de la section 11 sont revérifiés, sans doublon :

- six positions entières de secondes, dix-huit positions décimales ;
- exclusion sans arrondi ni remplacement au-delà du budget, indépendamment
  pour l’allure et la durée ;
- au plus **34 caractères par mesure**, budget de représentation et non
  seuil physiologique ;
- chaque nouveau fait C371 testé à **256 caractères maximum**, chaque forme
  FR/EN/ES comprise, trois faits à **770 caractères maximum** ;
- au plus deux bornes et une couverture dans le catalogue ;
- contexte JSON limité à **24 000 caractères** avant tout appel provider ;
- réponse provider limitée à **2 400 caractères** et texte Coach à
  **2 400 caractères**, clauses entières seulement, jamais de valeur tronquée.

Les limites de contexte, réponse et composition existantes suffisent ; elles
ne sont pas ajoutées une seconde fois. Les formes éditoriales restent fermées.
L’intention est celle du fait principal ; les soutiens indépendants peuvent
conserver leur propre catégorie sans autoriser de transition causale.

### 12.4 Tests réellement exécutés et comparaison

Même environnement isolé de validation pour le HEAD reçu et le complément :
Python 3.12.3, pytest 9.1.1, pytest-xdist 3.8.0, pytest-asyncio 1.4.0,
Pydantic 2.13.4, FastAPI 0.110.1, httpx 0.28.1, flake8 7.3.0.
Les dépendances de test/import sont restaurées sans changer les manifests,
après vérification des advisories. `backend/pytest.ini` est inchangé.

Commande de l’ensemble demandé, identique avant/après pour les suites :

```bash
cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend
/tmp/c371-verification-venv/bin/python -m pytest \
  /home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_hybrid_coach_c359.py \
  /home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_hybrid_coach_c362.py \
  /home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_hybrid_coach_c364_audit.py \
  /home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_hybrid_coach_c365.py \
  /home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_hybrid_coach_c371.py \
  /home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_historical_max_hr_c367.py \
  /home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_workout_intelligence_v3.py \
  /home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_workout_analysis_v2*.py \
  /home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_narrative_coach_v3.py \
  /home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_garmin_laps_analysis_c343.py -q
```

| État | Réussites | Échecs | Avertissements |
|---|---:|---:|---:|
| Base antérieure documentée, non réexécutée ici | 1 306 | 3 V2 | 14 |
| Première livraison C371 documentée, non réexécutée ici | 1 431 | 3 V2 | 14 |
| HEAD reçu `0b9c0c90…`, réexécuté ici | **1 517** | **3 V2** | **14** |
| Complément : C371 seule | **223** | **0** | 0 |
| Complément : ensemble demandé | **1 529** | **3 V2** | **14** |

Les seuls échecs finaux sont toujours
`test_comparable_history_stays_separate_and_metrics_are_unchanged[en/fr/es]`
dans
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_workout_analysis_v2.py:1838` :
attendu `meaning.consistent_pacing`, obtenu
`meaning.hr_without_intensity_with_pacing`. **Suite élargie non verte** ;
aucun nouvel échec fonctionnel, aucun test V2 modifié.

Les essais préparatoires ont signalé des imports de validation absents :
premier essai **1 306 réussites, 2 échecs et 2 erreurs de collecte** ; deuxième
essai **1 344 réussites, 2 échecs et 1 erreur de collecte**. Ils ont été analysés
(`redis`, `pytest_asyncio`, `email_validator`, puis `passlib` manquants) et
résolus uniquement dans l’environnement de test, avant les résultats complets.
Ils ne sont pas présentés comme des régressions applicatives ou une suite verte.

Lint ciblé flake8 `E9,F63,F7,F82` sur les trois fichiers Python C371 et
`git diff --check` : réussis. Revue indépendante du diff : aucun problème
significatif. Scan de secrets : aucun secret détecté. CodeQL Python après
commit `340ec4ce75e375133cb5bd259aae52fe95c8a867` : **0 alerte**.
GitHub Actions consulté : le run précédent `40134411729` ne contient aucun job
échoué ; son succès n’est pas présenté comme une validation de ces nouveaux tests.

### 12.5 Non-régressions, risques résiduels et verdict

Seuls le sélecteur hybride, les tests C371 et ce rapport sont modifiés dans
cette intervention. Aucun changement au formatage déjà sécurisé n’a été requis.
Contrats Garmin/C368/C369, moteurs V2/V3, seuils, Coach narratif, API, frontend,
prescriptions, prédictions et abonnements restent intacts.

Les tests utilisent des données synthétiques et des transports injectés :
aucun appel Garmin/GCCLI, MongoDB production ou LLM externe.
`C359_HYBRID_COACH_ENABLED` reste désactivé par défaut.

Risques résiduels : le budget d’affichage ne certifie pas la plausibilité
physiologique d’une donnée ; les mesures non représentables restent omises.
L’exception éditoriale ne concerne que le fallback saturé avec position
`above_LT2` déjà admissible. Le classement général, les autres arbitrages
entre quatre faits admissibles et la qualité du choix par LLM restent réservés
à C373 et à une évaluation distincte. Les trois échecs V2 connus subsistent.

**GO pour revue du complément offline sur #367 ; HOLD pour activation produit.**
Aucune nouvelle PR, aucun merge, aucun déploiement ni activation. STOP après
ce rapport.
