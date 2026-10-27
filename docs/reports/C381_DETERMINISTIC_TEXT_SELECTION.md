# C381 — Sélection déterministe et cohérence scientifique

## A. Révisions et audit préalable

- Dépôt : `geirb56/sauvegarde260708`.
- Base exacte : `copilot/dev`, `43701db2695d94ea339112be8407eaf05dac4a83`.
- HEAD initial : même SHA ; branche de travail : `copilot/delete-llm-text-selection`.
- `origin/copilot/dev` a été récupérée et son SHA vérifié, sans merge ni changement de branche.
- HEAD du code validé et analysé par CodeQL :
  `ca16f671d82f792bb5cbcf784f58d04cab076f1e`.
- La finalisation du présent rapport est un commit documentaire seul,
  postérieur à ce HEAD ; aucun code n'a changé après la validation.

L'audit a précédé toute modification. Les chemins ci-dessous sont relatifs à
`/home/runner/work/sauvegarde260708/sauvegarde260708/` ; les références de lignes de
l'audit désignent la base exacte ci-dessus, pas les lignes déplacées par C381.

Fichiers inspectés :

- `backend/hybrid_coach_c359.py` : admission des faits, contrat, contexte,
  fallback, transport et générateur.
- `backend/hybrid_coach_closed_c374.py` : compositions fermées, réalisation,
  validation de chaque option, choix d'identifiant et sélection déterministe.
- `backend/hybrid_coach_editorial_c365.py` : priorités, exclusions, formes,
  registre des conseils et validation.
- `backend/hybrid_coach_v2_c372.py` : rattachement utilisateur/séance et
  admission des conclusions V2.
- `backend/narrative_coach_v3.py`, `backend/coach_language.py`,
  `backend/workout_analysis_v2.py` : sources scientifiques et leurs consommateurs.
- `backend/workout_intelligence_v3_service.py`, `backend/server.py`,
  `backend/llm_coach.py` : chargement, routes et fournisseur partagé.
- `backend/tests/test_hybrid_coach_c359.py`,
  `backend/tests/test_hybrid_coach_c372.py`,
  `backend/tests/test_hybrid_coach_c374.py`,
  `backend/tests/test_hybrid_coach_c378.py`,
  `backend/tests/test_hybrid_coach_c379.py`,
  `backend/tests/test_narrative_coach_v3.py`,
  `backend/tests/fixtures/coach_session_synthesis_c351.json`,
  `backend/pytest.ini`.
- `docs/reports/C379_HUMAN_COACH_REALIZATION.md`,
  `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`, `DEPLOYMENT.md`.

### Chemins de sélection à la base

1. `generate_hybrid_coach` (`hybrid_coach_c359.py:1314-1419`) construit d'abord
   un résultat déterministe C379, puis demande au fournisseur une sélection
   C365 de faits/formes. `_transport:1305-1311` appelle `_call_gpt`.
   Les sorties du fournisseur ne deviennent jamais directement du texte :
   schéma, identifiants, formes, intention et non-redondance sont contrôlés.
   En cas d'échec, le résultat déterministe initial reste disponible.
2. `generate_closed_choice_coach` (`hybrid_coach_closed_c374.py:550-638`)
   demande à un transport explicitement injecté un seul `option_id`.
   Chaque option est reconstruite avant l'appel, puis l'option choisie l'est
   de nouveau. Échec fermé sans texte si l'identifiant, le JSON ou l'option
   est invalide ; pas d'activation implicite du fournisseur.
3. Flag commun : `C359_HYBRID_COACH_ENABLED`. Les autorisations d'analyse,
   d'historique et de prescription restent distinctes ; le prototype fermé
   vérifie également `llm_access`.
4. Aucun consommateur de production n'appelle ces deux générateurs dans
   l'arbre inspecté : les références d'appel sont les tests. Le loader interne
   `load_scoped_workout_intelligence_v3_with_v2` transporte déjà V2 sans route
   hybride. La route Narrative existante est un autre consommateur.
5. Narrative V3 possède son propre transport optionnel et son propre flag
   `C355_NARRATIVE_LLM_ENABLED`. Le fournisseur partagé sert aussi d'autres
   usages du Coach : supprimer celui-ci globalement serait hors périmètre.

### Origine et fiabilité des options

`build_admissible_facts` ne fait pas confiance au texte du fournisseur :

- classification probable déjà publiée par V3, avec confiance et réserve
  d'historique lorsqu'elle en dépend (`c359:417-486`) ;
- position de FC seulement si FC, seuils personnels, sources, confiance et
  relation numérique sont cohérents (`c359:488-525`) ;
- historique seulement sous permission et avec comparabilité/échantillons
  admissibles ; les différences nulles ne sont pas promues en résultat ;
- observations d'efforts avec identités, unités, provenance et disponibilité
  vérifiées ; une donnée manquante ne devient pas zéro ;
- régularité seulement via `ScopedV2Evidence` rattachée au même utilisateur
  et à la même séance, phases Garmin complètes et conclusion V2 unique
  (`c372:32-64`, `c359:639-684`) ;
- direction seulement avec portée V2 explicite, valeurs finies et cohérentes
  (`c372:67-157`, `c359:685-745`).

Ces validations attestent la cohérence des sorties serveur disponibles, pas
une nouvelle mesure ni une revérification des données Garmin brutes.
La prescription reste exclue des options Coach.

### Règle de complétude réellement retrouvée

Le code de base contient déjà une fonction pure
`select_deterministic_option` (`c374:470-499`). Ce n'est pas « choisir le texte
le plus long » :

1. priorité contextuelle du fait principal ;
2. complément de seuil lorsqu'il est admissible ;
3. pour une direction : premier/dernier efforts enregistrés, sinon régularité ;
4. pour une sortie longue : comparaison des moitiés si disponible ;
5. autres compléments utiles : historique ou position de FC ;
6. départage par longueur **croissante**, puis contenu stable, sans identifiant
   ni position de présentation.

Les résultats « 21/21 » et « 16/21 » de C380 sont fournis par la demande.
Aucun artefact C380 ni transcription de ses 21 appels n'a été retrouvé dans
le checkout : cette PR ne prétend ni les avoir reproduits ni connaître une
autre règle de complétude que celle du code inspecté.

## B. Diagnostic de la divergence

### Deux entrées différentes, pas deux verdicts scientifiques opposés

`coach_language._repetition_judgment` (`coach_language.py:103-191`) exige des
mesures positives, un ordre cohérent et la comparabilité de **tous** les
efforts. La bande est calculée à partir de l'écart absolu moyen à la médiane,
avec les seuils et l'incertitude existants. Deux efforts seulement ne
permettent pas de juger une série. Les durées/distances comparables viennent
des fonctions V2 existantes ; C379 ne les redéfinit pas.

Narrative V3 lit cette même conclusion via
`_approved_repetition_judgment` (`narrative_coach_v3.py:73-108`).
L'admission hybride réutilise précisément cette fonction et ajoute des
vérifications de rattachement et de couverture. La dispersion historique
V2 (écart-type) est une observation distincte, pas un autre calcul de la
bande catégorielle.

- Avec conclusion V2 admissible : Narrative émet `interval.judgment`
  (« Allures homogènes… »), et C379 réalise `interval.regularity`
  (« allures proches »).
- Sans conclusion V2 admissible : Narrative émet `interval.execution` et
  explique l'absence de verdict ; l'écart-type seul n'autorise pas un jugement.
  C379 n'admet alors pas de fait `interval.regularity`.
- Le test existant `test_v2_v3_disagreement_is_missing_input_not_opposite_verdict`
  (`test_hybrid_coach_c379.py:137-150`) démontre la différence avec la même
  séance synthétique, en omettant puis transmettant `coach_language`.
- Le loader Narrative transmet **déjà** les phases et `coach_language`
  (`workout_intelligence_v3_service.py:208-216`). Aucun branchement manquant
  n'est démontré dans ce chemin de production.

La correction permise est rédactionnelle : rendre explicite l'absence d'un
verdict V2 validé, sans transformer l'absence de jugement en irrégularité.
Aucun motif démontré pour modifier un calcul ou un moteur physiologique.

**Limite de portée :** la cause d'une éventuelle paire de textes issue des
appels réels C380 ne peut pas être certifiée sans leurs entrées/artefacts.
Le diagnostic ci-dessus est démontré sur le code et ses fixtures ; il ne
constitue pas une expertise des séances Garmin absentes. Si des entrées
identiques et admissibles produisent réellement des verdicts opposés, il
faut arrêter et auditer ce cas dans une PR distincte.

## C. Modifications exactes

Les deux points d'entrée hybrides sélectionnent désormais côté serveur :

- suppression du prompt et de l'appel au transport sur le chemin de
  sélection C379, y compris lorsqu'un transport est injecté ;
- conservation des paramètres, champs et modes existants, des flags et des
  contrôles d'accès ; les diagnostics distinguent désormais la sélection
  déterministe d'une sélection du fournisseur ;
- validation des compositions fermées avant le classement et reconstruction
  de l'option retenue ; échec fermé sans texte non validé si la construction
  ou la validation échoue ; aucune sortie libre n'est utilisée ;
- priorité contextuelle, puis compléments admissibles et départage sémantique
  stable ; la longueur du texte n'est plus un critère ;
- ordre stable des faits historiques, indépendant de l'ordre d'entrée ;
- classement « footing probable » en tête seulement pour une classification
  facile de confiance moyenne/haute, corroborée par la position de FC sous
  LT1 déjà admise, et sans fait plus distinctif d'intervalles, moitiés, durée
  longue ou historique ;
- suppression de `advice.keep_consistency` et de ses trois formulations ;
  les autres conseils restent soumis au registre et à leurs conditions ;
- conservation d'une illustration concrète `effort.first` pour la régularité,
  lorsqu'elle est admissible : durée et allure enregistrées, sans répéter
  artificiellement deux extrémités ;
- précision rédactionnelle FR/EN/ES dans Narrative : la réserve correspond
  à l'absence d'un verdict V2 validé, sans modifier la bande ni son admission.

Les valeurs observées et réserves attachées aux faits restent conservées.
Ni les moteurs V2/V3, ni le service de chargement, ni les routes, ni les
prescriptions, ni Garmin, MongoDB ou l'infrastructure ne sont modifiés.
Le transport partagé et le chemin optionnel Narrative restent disponibles
pour leurs autres usages.

Les quatre fichiers de production modifiés sont `hybrid_coach_c359.py`,
`hybrid_coach_closed_c374.py`, `hybrid_coach_editorial_c365.py` et
`narrative_coach_v3.py`, sous `backend/`. Leurs modèles conservent leurs
champs et enums. Le diagnostic de succès hybride devient
`deterministic_selection_validated` ; celui du chemin fermé reste
`option_validated`. Les métadonnées indiquent `provider_attempted=False`,
`transport_kind="none"` et aucune durée/coût fournisseur. Le blocage
obsolète de qualité LLM est remplacé par `production_wiring_not_validated`.

## D. Matrice des sept cas

Les sept catégories demandées sont rejouées avec les builders existants.
Ce sont des fixtures synthétiques reconstruites, pas les réponses archivées
de C380. Les conseils de ces sept cas sont absents (`None`).

| Cas | Fait principal | Compléments | Valeurs/conclusion C379 | Narrative avec les mêmes entrées |
|---|---|---|---|---|
| `easy` | `session.kind` | `intensity.position` | Footing probable ; FC 140 bpm sous LT1 150 bpm, réserve sur la moyenne | Footing probable ; même position de FC |
| `long` | `session.long` | `intensity.position` | 100 min contre 50 min habituelles ; FC 140 bpm, LT1 150 bpm | Sortie longue probable ; même position de FC |
| `comparable_history` | `trend.probable_improvement` | Aucun | Allure médiane récente 24 s/km plus rapide, 6 observations sur 92 jours ; pas de preuve de changement de forme, terrain/météo non isolés | Même tendance qualifiée et mêmes valeurs |
| `no_physiology` | `intensity.hr` | Aucun | FC 140 bpm sans repère personnel validé ; pas de zone inventée | Type incertain ; pas de zone confirmable sans LT1 fiable |
| `v2_regular_300x4` | `interval.regularity` | `effort.first` | 4 répétitions comparables à allures proches ; premier effort enregistré de 4 min à 5'00/km | Allures homogènes, écart absolu moyen à la médiane : 0 s/km |
| `v2_faster_330_300` | `interval.pace_direction` | `effort.first`, `effort.last` | 2 dernières répétitions en moyenne 20 s/km plus rapides ; premier effort 5'30/km, dernier 5'00/km | Variations perceptibles, écart absolu moyen à la médiane : 10 s/km |
| `v2_slower_300_330` | `interval.pace_direction` | `effort.first`, `effort.last` | 2 dernières répétitions en moyenne 20 s/km plus lentes ; premier effort 5'00/km, dernier 5'30/km | Variations perceptibles, écart absolu moyen à la médiane : 10 s/km |

Pour les cas directionnels, les paces enregistrées sont respectivement
`(330, 320, 310, 300)` et `(300, 310, 320, 330)` s/km. Les valeurs 20 s/km
proviennent de la comparaison V2 validée des deux groupes, pas d'une
soustraction des seuls premier et dernier efforts (30 s/km).
La bande globale et la direction des groupes décrivent des portées
différentes : « variations perceptibles » et « dernières répétitions plus
rapides/lentes » ne se contredisent pas.

Les conversions affichées sont vérifiées : 330 s/km = 5'30/km ;
300 s/km = 5'00/km. Aucune direction de groupe n'est admise lorsque les
preuves sont absentes, mal rattachées, contradictoires ou indisponibles.

## E. Séances réelles

| Séance demandée | Accès réel | Éléments disponibles | Conclusion autorisée |
|---|---|---|---|
| 10/10 | Non | Analogue synthétique 4 répétitions avec V2 | Pas de verdict sur la séance réelle |
| 19/09 | Non | Analogue synthétique 6 efforts sans conclusion V2 | Pas de verdict sur la séance réelle |
| 12/10 | Non | Analogue synthétique à historique relatif et confiance faible | Pas de verdict sur la séance réelle |
| 19/10 | Non | Analogue synthétique tapis/structure inconnue | Pas de métrique inventée |

Le processus ne dispose d'aucune configuration `MONGO_URL`, `MONGODB_URI`,
`MONGO_URI` ou `DB_NAME` ; seul `.env.example` est présent au niveau inspecté.
Aucun accès MongoDB/Garmin ni écriture de données n'a été effectué.
`test_narrative_coach_v3.py:1015-1032` qualifie explicitement les quatre cas
de **synthetic analogues only**. Le JSON C351 documente lui aussi sa
provenance synthétique. Ces données ne remplacent pas un replay réel.

## F. Tests, échecs et limites

Les tests backend utilisent le runner
existant `python -m pytest` ; `backend/pytest.ini` impose
`-n 2 --dist loadscope`. Aucun outil de test ni dépendance supplémentaire
n'a été ajouté.

La suite C381 exerce les deux points d'entrée avec et sans transport injecté,
et bloque le réseau ainsi que le transport par défaut. Pour chaque cas :
trois permutations des faits/options et renumérotations d'identifiants, avec
comparaison des textes, faits, conseils et réserves. Les builders
scientifiques sont interdits après constitution des entrées de référence ;
V2 et V3 ne doivent pas être mutés.

Les assertions portent aussi sur l'absence de V2, le mauvais propriétaire,
la direction contradictoire, une qualité insuffisante, les options vides,
les comparaisons nulles, et les conditions qui interdisent de promouvoir
« footing probable ». Les tests historiques de validation restent utiles
mais ne doivent plus exiger l'appel d'un fournisseur désormais supprimé :
leurs scénarios d'entrées malveillantes sont conservés au niveau des
validateurs ou vérifient que le transport est ignoré.

### Suites ciblées

Commande depuis `/home/runner/work/sauvegarde260708/sauvegarde260708/backend` :

```text
python -m pytest tests/test_hybrid_coach_c359.py tests/test_hybrid_coach_c362.py tests/test_hybrid_coach_c364_audit.py tests/test_hybrid_coach_c365.py tests/test_hybrid_coach_c371.py tests/test_hybrid_coach_c372.py tests/test_hybrid_coach_c374.py tests/test_hybrid_coach_c378.py tests/test_hybrid_coach_c379.py tests/test_hybrid_coach_c381.py tests/test_narrative_coach_v3.py tests/test_workout_intelligence_v3.py tests/test_coach_language.py tests/test_workout_analysis_v2_phases.py tests/test_workout_analysis_v2_facts.py tests/test_workout_analysis_v2_unified.py --tb=short -q --disable-warnings
```

Résultat final après corrections de revue : **2013 réussites**, 6 avertissements.
La commande dédiée
`python -m pytest tests/test_hybrid_coach_c381.py -q --disable-warnings`
donne **39 réussites**, déjà comprises dans les 2013 (ne pas additionner).
Les quatre cas avec perte d'accès, preuves insuffisantes ou contradictoires
et les réserves de confiance restent couverts.

La suite `test_workout_intelligence_v3.py` couvre également le loader
Narrative, notamment la réutilisation de `coach_language` et des phases du
même chargement sans lectures supplémentaires.

### Non-régression étendue : échecs préexistants

Commande depuis `/home/runner/work/sauvegarde260708/sauvegarde260708/backend` :

```text
python -m pytest tests/test_workout_analysis_v2.py --tb=line -q --disable-warnings
```

Résultat : **171 réussites, 3 échecs** dans
`test_comparable_history_stays_separate_and_metrics_are_unchanged[en/fr/es]`
(ligne 1838 à la base). Le test attend `meaning.consistent_pacing`, alors que
le moteur renvoie `meaning.hr_without_intensity_with_pacing`.
Les trois échecs ont été reproduits avec la source du test à HEAD initial ;
les fichiers des moteurs `workout_analysis_v2.py` et `coach_language.py`
sont inchangés. Aucun test n'est supprimé/ignoré et aucune correction de
ce comportement scientifique préexistant n'est incluse dans C381.

Vérification de base effectuée avant commit, à
`43701db2695d94ea339112be8407eaf05dac4a83` : comparaison octet par octet des
deux moteurs avec `git show HEAD:<chemin>`, puis chargement en mémoire de
`git show HEAD:backend/tests/test_workout_analysis_v2.py` et invocation du
test original pour `en`, `fr`, `es`. Les trois assertions échouent également
à cette base. Il ne s'agit donc pas d'un verdict « toute la suite V2 verte ».

### Revue et contrôles

- Revue indépendante en lecture seule : perte d'une illustration concrète
  détectée puis corrigée en faveur de `effort.first`.
- Deux couvertures devenues inopérantes après retrait du fournisseur ont
  été rétablies : rejet direct d'une sélection historique interdite en
  séance inconnue, et exercice direct de l'adaptateur pour la confidentialité
  des erreurs. Le non-appel de cet adaptateur par le générateur est testé
  séparément.
- Revue finale du code de production : aucun problème significatif restant
  signalé.
- `git diff --check` : réussi lors de la validation.
- Scan de secrets de l'ensemble des 16 fichiers modifiés/créés avant commit :
  **aucun secret détecté**.
- CodeQL après commit `ca16f671d82f792bb5cbcf784f58d04cab076f1e` :
  analyse Python, **0 alerte**. Changement déclaré non trivial, car les
  chemins de sélection et leur traitement d'échec changent.
- Vérification finale Git : arbre propre après le commit du code,
  `git diff --check` réussi ; diff nul par rapport à la base pour
  `workout_analysis_v2.py`, `coach_language.py`, `workout_intelligence_v3.py`,
  `workout_intelligence_v3_service.py` et `server.py`.

### Limites explicites

- Pas de replay MongoDB/Garmin réel ; dates et métriques des séances réelles
  non vérifiées.
- Pas de transcription C380 disponible : comparaison avec les sept
  catégories et fixtures du dépôt, pas avec les 21 réponses originales.
- Pas de campagne de qualité éditoriale humaine ni d'appel réel au LLM
  pour cette PR ; l'absence d'appel est précisément testée.
- Pas de build frontend : aucun fichier frontend ni contrat routé modifié.
- Les 6 avertissements pytest ne sont pas des échecs ; les trois échecs V2
  ci-dessus restent une limite explicite de la campagne étendue.

## G. Verdicts séparés

- **PR : GO pour revue du correctif ciblé**, avec contrôles secrets/CodeQL
  réussis et les trois échecs V2 préexistants explicitement signalés.
  Ce verdict n'affirme ni un replay réel ni une suite V2 intégralement verte.
- **Branchement en production : NO-GO dans cette PR.** Aucun branchement,
  déploiement ni validation sur les quatre séances réelles.
- Aucun merge automatique ; arrêt après rapport et contrôles.
