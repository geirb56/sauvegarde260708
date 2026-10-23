# C362 — Coach LLM pertinent, direct et personnalisé

## Périmètre et références exactes

- Base : `copilot/dev`, `0132fb031accc35cea59c08f785c0ae5ee400ab9` (merge C360).
- HEAD du code testé : `1f0533118f6f37122ee0f8a407de58f2b39da0bb`.
  Le commit contenant ce rapport est documentaire ; le HEAD de livraison est
  également indiqué dans la PR. Ces références ne désignent pas un déploiement.
- Branche de travail : `copilot/c362-improve-coach-llm`.
- Décision : **HOLD**, audit propriétaire requis, aucun merge automatique.
- Aucun appel réel LLM, Garmin ou MongoDB, aucune donnée utilisateur réelle.
- Aucun changement des moteurs V3, du transport `llm_coach._call_gpt`, des routes,
  de l'interface ou des dépendances déclarées. Aucun déploiement.

## Audit en lecture seule avant modification

Contrats inspectés : `backend/workout_intelligence_v3_models.py:176-348`,
`backend/workout_intelligence_v3.py:71-96,810-876,980-1025,1174-1190`,
`backend/hybrid_coach_c359.py` et ses tests C360 à la base ci-dessus.
Le rapport historique `C359_HYBRID_COACH_PROTOTYPE.md` n'est pas une autorité
sur le code courant.

| Information | Disponible dans la sortie V3 reçue par ce prototype | Admission C362 |
| --- | --- | --- |
| FC moyenne et position / seuils | `intensity_assessment` | Conservées ; valeurs finies, seuils fiables et cohérence de position |
| LT1 / LT2 personnels | Valeur, source, date, confiance des seuils retenus par V3 | Sources admissibles et confiance contrôlées ; aucun seuil créé |
| Durée et durée habituelle | Preuves de `long_run_probable` | Comparaison déjà établie par V3, seulement avec permission historique |
| Distance / durée / allure générales | Présentes dans l'entrée V3, pas dans une enveloppe générale de mesures de sa sortie | Pas de reconstruction depuis les noms, textes ou entrées non fournies |
| Splits kilométriques, durées/allures des répétitions, récupérations détaillées | Pas dans ce contrat de sortie | Exclus ; aucune extension V2 implicite |
| Structure fractionnée | Comptages d'efforts et récupérations | Conservés ; le nom `intervals_4x4` ne prouve pas quatre minutes |
| Régularité / dispersion des répétitions | Pas de verdict admissible dans ce contrat | Aucun jugement de régularité ni d'irrégularité |
| Dérive cardiaque | Pas dans ce contrat | Aucune interprétation de dérive |
| Comparaison historique | Écarts V3 d'allure à FC comparable et de FC à allure comparable | Ajout si `available`, comparabilité `strong`, références suffisantes et structure connue |
| Tendance | Médianes et statut V3 avec sensibilité | Conditions C360 conservées ; observation distincte de gain physiologique |
| Prescription | Statut et contexte du snapshot historique | Permission obligatoire ; statut `consistent` ajouté, limité à la correspondance du **type**, pas à la conformité intégrale |
| Objectif d'entraînement | Pas de champ d'objectif admissible dans cette sortie | Aucun objectif inventé |

Les comparaisons ne sont pas recalculées. Le minimum de deux références reprend
le minimum existant de comparaison V2/V3 ; les cohortes, écarts, médianes et
critères de sensibilité restent calculés par leurs autorités existantes.
Le choix de n'admettre que `strong` est conservateur : V3 peut aussi exposer une
comparaison `moderate`, mais C362 ne la transforme pas en preuve forte.

### Seuils

LT1 et LT2 désignent respectivement le premier et le second seuil lactique
personnel. Le paquet explicite leur identité et interdit de les remplacer par
des pourcentages de FCmax ou des synonymes de seuils ventilatoires.
Opérationnellement, seule la position V3 de la **FC moyenne** par rapport à ces
valeurs est admissible : ni zone numérotée, ni durée en zone, ni intensité de
chaque instant. V3 reste responsable de la validité scientifique des seuils.
Ces fixtures injectent des seuils synthétiques ; cela ne prouve pas leur
disponibilité dans les profils de production.

## Changements ciblés

### Evidence Pack

Chaque preuve expose valeurs, unités, signification des champs, confiance,
conclusion admissible, conditions, conclusions interdites et priorité indicative.
Les IDs, dates privées, textes V3 arbitraires et chemins de provenance ne sont
toujours pas transmis. La priorité n'oblige pas à commenter tous les champs.
Les provenances locales restent disponibles pour le fallback.

`comparison.pace` signifie **allure courante moins moyenne des références** :
un écart négatif est plus rapide. Il ne faut pas le confondre avec la variation
**médiane entre périodes** de `performance_trend`. Dans `comparable_history` :

- écart ponctuel d'allure V3 : **−14,4 s/km**, cinq références ;
- écart de FC à allure comparable : **0 bpm**, deux références ;
- variation médiane entre périodes : **−24 s/km**, six observations sur 92 jours.

Ces chiffres n'ont pas été produits par un calcul parallèle. Zéro reste une
valeur ; une absence de mesure reste une absence.

### Rédaction libre

Le prompt demande l'observation distinctive d'abord, une sélection utile plutôt
qu'un catalogue, un langage direct et aucune conclusion automatique.
Le quota indicatif de 60–110 mots et la barrière de 8–150 mots sont supprimés.
La limite technique de 2 400 caractères et le timeout de huit secondes restent.
Ni phrases à assembler, ni moteur physiologique supplémentaire, ni juge LLM.

Une classification probable ne devient jamais certaine. Le prompt préfère la
description établie lorsqu'une qualification incertaine ajouterait peu de valeur.
Les bénéfices génériques, félicitations et prescriptions finales sont interdits.

### Validation : corrections démontrées, pas objectif d'acceptation

Les tests C360 caractérisaient explicitement deux faux rejets :

1. Une FC moyenne décrite correctement était rejetée sans une réserve littérale
   sur chaque instant et le temps passé dans les zones.
2. Un comptage d'efforts/récupérations était rejeté sans réciter l'impossibilité
   de juger la régularité.

C362 n'exige plus ces clauses pour un **fait descriptif**. Les tests conservant
ces cas ont été actualisés ; la qualification des véritables conclusions
incertaines reste contrôlée. Un constat de prescription n'a plus besoin de
réciter qu'il ne remplace pas Training ; cela n'autorise aucune nouvelle consigne.
Une absence de FC n'impose pas non plus sa mention si aucune FC n'est affirmée.

Protections complémentaires testées : bénéfices génériques et intensité inventée,
impératifs sans chiffres, permissions historique/prescription, classification
absente ou contradictoire, échange LT1/LT2, unité incompatible et valeur de FC
moyenne lorsque « de moyenne » suit le nombre. La négation d'une phrase ne
neutralise plus une affirmation interdite dans la phrase suivante ou après
« mais ». Les nombres, signes et unités restent contrôlés.

La revue indépendante a démontré quatre contournements : généralisation de la
FC moyenne à toute la course, répétitions dites « homogènes », LT1 entre
parenthèses / comptages effort-récupération inversés, et impératif après une
virgule. Ils ont été corrigés avec neuf cas de non-régression vérifiant le
fallback. Le statut de prescription ne permet pas non plus d'affirmer une
conformité complète lorsque V3 ne vérifie que le type.

## Comparaison technique avec C361

Les chiffres C361 viennent de l'énoncé du propriétaire : 21 réponses réelles
avec `gpt-4.1-mini`, zéro acceptation, 21 fallbacks. Les réponses brutes et leur
ventilation détaillée des motifs ne sont pas présentes dans ce checkout :
aucune réattribution des 21 rejets à une cause précise n'est prétendue.

| Dimension | C361 rapporté / prototype C360 inspecté | C362 vérifié hors ligne |
| --- | --- | --- |
| Transport | 21 réponses réelles reçues | Inchangé ; indisponibilité, timeout, troncature et erreurs testés |
| Réserves | Clauses littérales provoquant des faux rejets démontrés dans les tests | Faits descriptifs acceptables sans récitation |
| Personnalisation | FC, classification et tendance ; comparaison ponctuelle non transmise | Écarts V3 ponctuels ajoutés, sous permissions et comparabilité forte |
| Style | Texte fluide mais générique, hésitations rapportées | Prompt direct et sélectif, absence de quota ; efficacité réelle non mesurée |
| Science | Bénéfices et prescriptions inventés rapportés | Cas adversariaux renforcés ; aucune garantie sémantique complète |
| Réponses réelles C362 | Sans objet | **Non exécutées** ; acceptations/fallbacks réels non mesurés, pas zéro |

Les sept textes directs de `backend/tests/test_hybrid_coach_c362.py` sont écrits
à la main et fournis par transport simulé. Ils passent les contrôles ; ce ne
sont **pas** sept succès produit d'un vrai modèle. Exemples de tests, non modèles
de phrases de production :

- `easy` : « Ta FC moyenne est de 140 bpm, sous ton LT1 de 150 bpm. »
- `long` : « 100 min de course, contre 50 min habituellement. »
- `intervals_4x4` : comptage de quatre efforts et trois récupérations, sans verdict.
- `sparse` : impossibilité de qualifier la séance, sans métrique inventée.
- `comparable_history` : variation médiane de −24 s/km, sans gain de forme affirmé.

## Tests et vérifications exécutés

Depuis `/home/runner/work/sauvegarde260708/sauvegarde260708/backend` :

```sh
python -m pytest tests/test_hybrid_coach_c359.py tests/test_hybrid_coach_c362.py tests/test_workout_intelligence_v3.py tests/test_narrative_coach_v3.py -q
python -m flake8 hybrid_coach_c359.py tests/test_hybrid_coach_c359.py tests/test_hybrid_coach_c362.py --select=E9,F63,F7,F82
```

- **454 tests réussis**, six avertissements de dépréciation préexistants
  (`crypt`, configuration Pydantic et événements FastAPI).
- Flake8, sélection d'erreurs Python ci-dessus : aucune erreur.
- `git diff --check` : aucune erreur.
- Les premières tentatives ont rencontré des dépendances d'environnement
  absentes (`pytest`, `fastapi`, `email-validator`, `redis`), restaurées sans
  modifier les manifestes. Aucun test modifié pour contourner ces imports.
- Le test additif d'API utilise ses doublures existantes ; aucun service Garmin
  ou MongoDB n'est interrogé et les événements de démarrage ne sont pas lancés.
- Scan de secrets sur les fichiers modifiés : aucun secret détecté.
- Deux validations parallèles, dont une après les corrections de revue :
  **CodeQL Python, zéro alerte**.
  Le volet revue a signalé son modèle indisponible : ce n'est pas une preuve
  de revue réussie. Une revue indépendante en lecture seule a identifié les
  quatre points ci-dessus ; corrections et tests associés intégrés.
  Sa seconde lecture confirme ces corrections sans problème significatif
  supplémentaire ; elle n'a modifié aucun fichier ni exécuté de test.

## Évaluation Emergent préparée — à autoriser, pas exécutée

Utiliser les fonctions existantes `synthetic_case`, `CASES`, `_access` du module
de tests C360, puis `generate_hybrid_coach` avec son transport par défaut :
aucune connexion de route ou modification du transport n'est nécessaire.

1. Le propriétaire confirme explicitement le budget d'appels et l'accès Emergent.
   Proposition de comparaison : les sept fixtures inchangées, trois générations
   par fixture, soit 21 appels maximum, **sans retry automatique**.
2. Épingler le HEAD de la PR audité ; consigner base et HEAD effectifs.
   Vérifier les paramètres exacts C361 à partir de ses artefacts si disponibles.
3. Garder `gpt-4.1-mini`, français, données synthétiques uniquement, mêmes
   permissions explicites (`history=True`, `prescription=True`) et même ordre
   de fixtures : `easy`, `long`, `intervals_4x4`, `sparse`, `treadmill`,
   `comparable_history`, `no_physiology`.
4. Activer le flag uniquement dans le processus expérimental. Pour chaque appel,
   enregistrer le paquet effectivement envoyé, le texte brut synthétique, le
   texte retenu, `mode`, `reason`, `checks`, `provider_attempted`,
   `provider_duration_sec`, `elapsed_ms`, `cost` et les erreurs de transport.
   Une enveloppe d'observation autour de `_transport` peut capter le retour brut
   sans changer le transport ; ne journaliser aucune clé ni donnée personnelle.
5. Rapporter nombres reçus, acceptations et fallbacks avec leurs motifs,
   latences disponibles et coûts **seulement si réellement fournis**. Ne pas
   remplacer un coût absent par zéro ni confondre fallback et silence fournisseur.
6. Auditer manuellement pertinence, faits sélectionnés, style, fidélité et
   conclusions hors autorité, y compris les réponses acceptées. Comparer les
   réponses brutes C361 si elles sont disponibles, sinon annoncer cette limite.
7. Aucun seuil de succès produit prédéfini ; décision du propriétaire.
   Pas d'appel supplémentaire, de déploiement ou de merge sans autorisation.

## Risques résiduels et compromis

- Le validateur reste heuristique, **pas une preuve sémantique**. Les
  paraphrases inédites, nombres écrits en lettres, permutations de rôles autres
  que celles testées, langue incorrecte ou conseils indirects peuvent échapper
  aux contrôles. Un résultat accepté reste `HOLD`.
- L'omission de clauses automatiques réduit le bruit, mais augmente l'importance
  du contrôle des affirmations réellement faites. Les tests adversariaux ne
  couvrent pas tout le langage naturel.
- Les qualifications de classification/tendance gardent des contrôles lexicaux
  conservateurs ; certaines reformulations équivalentes peuvent encore tomber
  en fallback. Les corrections démontrées ne justifient pas leur suppression globale.
- L'absence de splits/répétitions détaillées et de mesures générales dans cette
  sortie V3 limite fortement la richesse du cas fractionné. Aucun « 4 × 4 min »
  ne peut être affirmé à partir du seul nom de fixture.
- Le fallback déterministe est conservé, y compris ses formulations historiques
  parfois prudentes. C362 ne prétend pas réécrire l'autorité scientifique.
- Aucune amélioration réelle de pertinence ou du taux d'acceptation n'est encore
  mesurée dans Emergent. Les résultats C361 ne sont pas transposés aux tests simulés.
- Aucune régression observée dans les suites ciblées ; la suite entière du
  dépôt et les tests de production connectés n'ont pas été exécutés.

**STOP :** PR destinée à l'audit du propriétaire ; aucune autorisation de merge
ou de validation réelle supplémentaire n'est déduite de ces résultats.
