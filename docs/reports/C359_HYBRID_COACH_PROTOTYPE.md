# C359 — Coach hybride V1/V3, prototype contrôlé

## Correction après audit HOLD — PR #359 uniquement

La première version ci-dessous est conservée comme **instantané historique**,
pas comme description de la correction. Son gain de substitution lexicale ne
répondait pas à l'objectif de synthèse intelligente. Il ne suffit pas de
remplacer un catalogue de synonymes par un catalogue plus grand.

### Audit préalable de la correction, en lecture seule

Point de départ : `4466e3e0e79e5e86e41a4ce8124f045c6c4b0315`, sur la même
branche de la PR draft #359. Base d'intégration inchangée :
`copilot/dev`, `720fb5cd31faca5f9f6435bb0be4c7cbf0f3fcf6`.

Fichiers relus avant modification : prototype hybride, Narrative V3,
Workout Intelligence V3 et ses modèles, transport LLM, présent audit historique
et tests hybrides/V3. Aucune modification des autorités scientifiques n'est
nécessaire ni autorisée.

| Source à ce point de départ | Fait fiable disponible / frontière |
| --- | --- |
| `backend/workout_intelligence_v3.py:621–744` | Type de séance, confiance, règles et preuves. Une sortie longue porte déjà durée, durée habituelle, ratio et taille d'historique ; ne pas recalculer le seuil de classification. |
| `backend/workout_intelligence_v3_models.py:183–199` | FC moyenne, position **de cette moyenne** par rapport aux seuils personnels acceptés ; ni temps dans les zones, ni position de chaque répétition. |
| `backend/workout_intelligence_v3_models.py:202–231` | Référence d'effort relative à l'historique, explicitement non physiologique ; accès historique requis. |
| `backend/workout_intelligence_v3.py:919–974` | Tendance évaluée par le moteur, avec confiance/sensibilité. Une différence isolée ne crée pas une tendance. |
| `backend/workout_intelligence_v3_models.py:310–320` | Statut canonique de conformité, pas une autorisation de créer/modifier un entraînement. |
| `backend/workout_intelligence_v3.py:626–634` | Décompte des efforts/récupérations et **disponibilité** de régularité seulement. La confiance haute ne constitue pas un verdict « régulier ». |
| `backend/narrative_coach_v3.py:73–108,195–299` | Le verdict catégoriel de régularité utilisé par la narration actuelle vient des conclusions versionnées V2/CoachLanguage du même passage, pas du seul booléen V3. Pas de nouvelle déduction à partir de la dispersion. |
| `backend/llm_coach.py:209–299` | Transport existant, mais nettoyage générique à 700 caractères : risque de troncature du JSON structuré. Aucun changement du transport de production pour masquer ce blocage. |

Informations manquantes : objectif autorisé dans la sortie V3, durées
individuelles des répétitions, verdict de régularité V3 autonome, métadonnée
narrative spécifique tapis, preuve d'une cause de fatigue, service indépendant
de vérification sémantique générale. Le libellé de fixture « 4 × 4 min » n'est
pas une preuve permettant au narrateur d'énoncer les durées.

**Décision d'architecture avant la correction :** laisser le LLM proposer une
synthèse véritablement libre et structurée, mais ne jamais confondre cette
proposition avec du texte vérifié. Des références déclarées, des chiffres
corrects et des assertions structurées cohérentes ne prouvent pas l'équivalence
de leur formulation libre. Toute partie invérifiable doit être rejetée, pas
« validée » par une heuristique ou un second LLM. Sans solution fiable à cette
frontière, le verdict reste HOLD, même si la sélection déterministe des faits
devient plus utile.

### Protocole d'évaluation de la correction

Réutiliser les sept fixtures **sans changer leurs données** pour rendre un
résultat plus flatteur. La fixture fractionnée d'origine ne contient pas de
verdict de régularité. D'éventuels cas réguliers/irréguliers supplémentaires
doivent être identifiés séparément.

Pour chaque cas, distinguer :

1. Narrative V3 actuel à partir de la même preuve.
2. Proposition libre simulée (non assimilable à une réponse réelle du LLM).
3. Texte effectivement servi après contrôle ou repli.

Évaluer séparément exactitude, personnalisation, pertinence, naturel, concision,
conseil et fiabilité. Une meilleure sélection ou un meilleur repli déterministe
n'établissent pas un gain de qualité du LLM. Une phrase libre correcte refusée
doit compter comme une limite du prototype, pas être cachée du bilan.

Vérification des prérequis fournisseur dans le processus de cette correction :
clé de transport absente et SDK existant non installé dans le Python système.
Seuls ces booléens ont été vérifiés, sans lecture ni exposition de secrets.
Aucun appel LLM réel, aucun test de séance réelle ou accès aux données privées
n'a été effectué. Aucun coût ou temps fournisseur ne sera extrapolé à partir
des simulations. Le budget timeout est une limite, pas une latence mesurée.

### Architecture avant / après

| Couche | Première livraison, rejetée par l'audit | Correction |
| --- | --- | --- |
| Science | Moteurs V2/V3 existants | **Inchangés** ; aucun seuil, régularité, progrès ou prescription recalculé par le narrateur |
| Faits | Sous-ensemble du texte déjà présélectionné par Narrative V3 | `AdmissibleFact` construit depuis des champs structurés V3 : identifiant stable, valeurs/unités, conclusion autorisée, confiance, conditions, limites importantes, priorité et chemins de source locaux |
| Génération | Une phrase, substitutions prédéfinies | Demande de synthèse originale, choix/hiérarchie/relations des faits admissibles ; sortie structurée avec texte complet, affirmations et identifiants de preuves/conclusions |
| Contrôle | Grammaire de substitutions littérales | Reconstruction indépendante des assertions autorisées depuis V3 ; **aucun vérificateur d'entailment libre disponible** |
| Texte servi | Tout le catalogue rendu, une phrase éventuellement reformulée | Proposition invérifiable écartée ; sélection déterministe de faits utiles comme repli. Sous-ensemble littéral vérifiable distingué explicitement d'une synthèse libre validée |
| Verdict | Prototype prudent mais gain conversationnel non démontré | **HOLD explicite dans chaque résultat** ; pas de succès sémantique déclaré par défaut |

Les listes de synonymes et les fonctions `_equivalent` et
`validate_hybrid_lead` sont retirées, pas agrandies. Le paquet fourni au LLM
ne contient pas de phrase à recopier : `provider_fact()` exclut l'assertion
locale et les chemins de source. Les identifiants de preuve sont du vocabulaire
fixe (`interval.count`, `session.long`…), jamais les identifiants de séances
ou d'utilisateurs. Les textes libres des champs coach, limites et sources
arbitraires ne sont pas transmis.

Les autorisations sont contrôlées **avant** la construction privilégiée et
l'appel fournisseur. FREE est refusé ; TRIAL/PREMIUM passent par `UserAccess`.
L'historique et la prescription nécessitent toujours le booléen explicite
`True` côté serveur. Une conformité dérivée d'un type dépendant de l'historique
ne contourne pas cette restriction. Le résultat d'une erreur n'est jamais un
V3 complet non filtré.

Le prompt demande une réponse naturelle dans la langue du paquet FR/EN/ES,
non limitée à une phrase ni à trois paragraphes, sans inventer de conclusion
ou de prescription. Le transport RunIndex existant reste inchangé. Il n'est
appelé qu'en opt-in avec le flag expérimental ; aucun appel réel n'a été
effectué pour cette correction.

### Méthode de contrôle factuel et frontière non résolue

La sortie demandée au fournisseur a la forme :

- `text` : synthèse complète.
- `claims` : affirmations factuelles, chacune avec son `text`, ses
  `evidence_ids` et ses `conclusion_ids`.

Ces déclarations **ne sont pas une preuve**. Le contrôle ne compare pas
seulement les nombres, ni les assertions structurées entre elles : il
reconstruit le catalogue autorisé depuis les valeurs V3 et les droits.
Pour l'unique cas démontrable aujourd'hui, le texte d'une affirmation doit
être exactement une assertion locale, ses identifiants doivent correspondre
à cette assertion, et le texte complet doit être exactement l'assemblage de
ces affirmations, sans connecteur ni phrase non couverte. Identifiant inconnu,
doublon, changement d'unité, de négation, de confiance ou omission d'une réserve
matérielle échouent à ce contrôle.

Ce sous-cas est nommé `literal_subset_verified`, avec
`verification_scope=literal_assertions_only`. Ce n'est **pas** un générateur
libre certifié ; le verdict reste HOLD. La sélection, l'omission et l'ordre de
faits littéraux peuvent être acceptés, mais une reformulation libre même
plausible, une relation causale ou une interprétation nouvelle sont refusées.
Le texte non vérifié n'est ni renvoyé dans le résultat ni journalisé.

Une réponse bien formée mais non démontrable produit
`reason=semantic_verification_unavailable` et le repli autorisé. Les réponses
invalides/tronquées, les erreurs et les timeouts ont aussi un repli ; une
annulation du demandeur se propage. Il n'existe ni juge LLM présenté comme
garantie, ni score heuristique baptisé « équivalence sémantique ».

**Limites résiduelles :**

- Le sous-cas littéral est trop restrictif pour démontrer l'objectif V1 :
  des formulations correctes sont rejetées. C'est un blocage documenté,
  pas une nouvelle solution par substitutions.
- Des champs structurés identiques ne prouvent pas le sens d'un texte libre ;
  les relations entre faits (cause, concession, évolution, conseil) restent
  particulièrement difficiles à vérifier indépendamment.
- Les assertions locales et leur pertinence sont du code de présentation
  auditable, pas une preuve universelle de complétude ou de qualité humaine.
- La confiance dans les données d'entrée suppose une sortie canonique V3
  déjà limitée au propriétaire ; cet appel interne n'est pas une API acceptant
  des preuves ou droits fournis par le navigateur.
- Le nettoyage partagé de 700 caractères peut couper le JSON, dont le texte
  est répété dans les affirmations. Une réponse rejetée pour cette raison
  n'évalue pas la qualité du modèle.
- Le verdict de régularité autonome manque dans V3. Ni le décompte, ni la
  confiance, ni la disponibilité ne peuvent combler ce manque.

### Connaissances scientifiques futures

L'audit historique de la première livraison est conservé plus bas : aucun des
190 conseils non sourcés n'est réintroduit. L'interface immuable
`ValidatedKnowledgeProvenance` réserve une URI source, une empreinte et une
révision relue. Le registre `VALIDATED_KNOWLEDGE` est vide ; il n'y a ni loader,
ni recherche, ni entrée de texte scientifique activable par un appelant.
Le nom du type et une provenance déclarée ne valent pas validation scientifique.
L'admission future nécessitera une politique séparée de revue et de pertinence.

### Comparaison qualitative des sept fixtures conservées

Référence : **texte complet** du rendu déterministe Narrative V3 actuel, pas
uniquement son champ `analysis`. Même sortie scientifique, droits historiques
et prescription explicitement autorisés pour les deux textes. Les propositions
libres du transport simulé ont été refusées ; la colonne hybride ci-dessous
est donc le **repli réellement servi**, pas une synthèse LLM prétendument validée.
Les phrases et valeurs sont issues exclusivement des fixtures synthétiques.

| Séance | Narrative V3 actuel — texte complet | Hybride corrigé — repli déterministe |
| --- | --- | --- |
| Footing facile | Probablement un footing facile. Ta fréquence cardiaque moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone. La conformité à la prescription reste indéterminée. | Type probable de ta séance : footing facile. Ta FC moyenne est de 140 bpm, sous LT1 ; elle ne décrit pas tout l'effort. |
| Sortie longue | Probablement une sortie longue. Ta fréquence cardiaque moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone. La conformité à la prescription reste indéterminée. | Sortie longue probable : 100 min, contre tes 50 min habituelles. Ta FC moyenne est de 140 bpm, sous LT1 ; elle ne décrit pas tout l'effort. |
| Fractionné 4 × 4 min | Une séance fractionnée. Garmin a enregistré 4 phases d'effort et 3 phases de récupération. La comparaison disponible ne permet pas d'établir la régularité des répétitions ; cela ne signifie pas qu'elles étaient irrégulières. La conformité à la prescription reste indéterminée. | Garmin a enregistré 4 phases d'effort et 3 phases de récupération. |
| Séance peu documentée | Type de séance incertain. Les données disponibles ne permettent pas d'identifier le type de séance de façon fiable. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits ni LT1 fiable, les moyennes de séance ne permettent pas de confirmer une zone physiologique. La conformité à la prescription reste indéterminée. | Le type de ta séance reste incertain ; aucune FC moyenne n'est disponible. |
| Tapis roulant | Probablement un footing facile. Ta fréquence cardiaque moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone. La conformité à la prescription reste indéterminée. | Type probable de ta séance : footing facile. Ta FC moyenne est de 140 bpm, sous LT1 ; elle ne décrit pas tout l'effort. |
| Historique comparable | Probablement un footing facile. Ta fréquence cardiaque moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton allure médiane est plus rapide de 24 s/km à fréquence cardiaque comparable sur 6 observations sur 92 jours : un signe encourageant d'amélioration probable, pas une preuve de gain de forme. Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone. La conformité à la prescription reste indéterminée. | Ton historique suggère une amélioration probable : 6 observations sur 92 jours, variation d'allure médiane de −24 s/km (récente moins ancienne) ; ce n'est pas une preuve de changement de forme. Ta FC moyenne est de 140 bpm, sous LT1 ; elle ne décrit pas tout l'effort. |
| Physiologie insuffisante | Type de séance incertain. Les données disponibles ne permettent pas d'identifier le type de séance de façon fiable. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits ni LT1 fiable, les moyennes de séance ne permettent pas de confirmer une zone physiologique. La conformité à la prescription reste indéterminée. | Ta FC moyenne est de 140 bpm ; le type de ta séance reste incertain. |

Les réserves absentes du repli ne sont pas des assertions contraires : ne pas
parler de progrès quand aucune tendance n'est disponible n'exige pas une phrase
générique sur l'absence de progrès démontré. De même, ne pas qualifier la
régularité des quatre efforts évite d'affirmer aussi bien « réguliers » que
« irréguliers ». Les limites restent dans le paquet structuré pour empêcher le
générateur de dépasser ces droits d'interprétation.

Appréciation par cas, limitée aux **replis servis**, sans note chiffrée ni
attribution au LLM :

| Cas | Exactitude | Personnalisation | Pertinence | Naturel | Concision | Conseil | Fiabilité |
| --- | --- | --- | --- | --- | --- | --- | --- |
| Facile | FC/type autorisés | Type et moyenne propres au cas | Pas de réserve historique sans objet | Plus direct, début encore catégoriel | Deux faits | Aucun conseil nouveau | Réserve sur la moyenne maintenue |
| Longue | Durées déjà présentes dans V3 | 100 contre 50 min habituelles | Particularité de durée mise en tête | Comparaison compréhensible | Deux faits | Enseignement descriptif, pas de cible | Historique explicitement autorisé |
| Fractionné | Seulement 4 efforts/3 récupérations | Décompte spécifique | Pas de moyenne FC hors sujet | Simple mais peu explicatif | Un fait | Aucun gain de conseil | Ni régularité ni durées individuelles inventées |
| Peu documentée | Absence de moyenne, pas de toute FC | Limite propre au cas | Incertitude centrale seulement | Direct | Un fait | Abstention justifiée | Aucun type ou seuil inventé |
| Tapis | Identique au cas facile | Pas de particularité tapis exploitable | Aucun enseignement tapis démontré | Identique au cas facile | Deux faits | Aucun conseil nouveau | Aucune correction de tapis improvisée |
| Historique | −24 s/km, 6 observations, 92 jours | Tendance propre au cas | Tendance avant métrique secondaire | Plus dense, technique | Deux faits | Signal descriptif, pas de prescription | « Probable » et absence de preuve de forme maintenus |
| Sans physiologie suffisante | FC moyenne seule, type incertain | Valeur disponible utilisée | Pas de seuil fictif | Direct | Un fait | Abstention | Aucune zone ou intensité physiologique conclue |

| Critère | Observation sur ces textes servis | Limite / verdict partiel |
| --- | --- | --- |
| Exactitude | Valeurs et conclusions rattachées aux assertions locales ; pas de nouvelle mesure ou cause | Certification du sous-cas littéral uniquement, pas de validation sémantique libre |
| Personnalisation | La sortie longue expose maintenant 100 min contre 50 min habituelles ; FC disponible utilisée sans inventer de seuil absent | Aucun objectif, verdict de régularité ou contexte tapis ajouté ; pas de personnalisation supplémentaire démontrée pour tapis |
| Pertinence | La durée distinctive ou la tendance passe avant les métriques secondaires ; la moyenne de séance n'est plus utilisée pour commenter les répétitions | Règles de sélection de présentation, pas intelligence LLM démontrée |
| Naturel | Tutoiement et formulations moins administratives ; pas de rappel de conformité indisponible dans chaque séance | Appréciation de lecture, sans panel aveugle ; des formulations de type « Type probable » restent peu conversationnelles |
| Concision | Une ou deux assertions dans ces cas ; disparition des réserves répétitives sans rapport avec le fait retenu | Ne démontre pas à elle seule une meilleure analyse ni la complétude de la réponse |
| Conseil | Aucun entraînement/allure/zone conseillé sans autorité ; la comparaison de durée peut constituer un enseignement descriptif | Aucun gain de conseil personnalisé démontré ; ne pas inventer de recommandation pour remplir une structure |
| Fiabilité | Droits et dépendances indirectes fermés par défaut ; propositions libres refusées, erreurs et annulation testées | Fonction de synthèse libre toujours **HOLD** |

**Ce qui est réellement amélioré :** choix déterministe de l'information
distinctive (notamment la durée relative déjà calculée par V3), hiérarchie et
concision. **Ce qui n'est pas démontré :** un gain de qualité d'analyse provenant
du LLM, ni la capacité à servir une explication originale avec fiabilité.

Exemple de faux négatif assumé : dans la fixture longue, le transport simulé
propose « Avec 100 minutes face aux 50 habituelles, cette sortie se distingue
probablement par sa longueur, sans indication de difficulté. » Cette phrase
peut paraître cohérente avec les valeurs, mais le contrôle ne sait pas en
démontrer automatiquement le sens complet : elle est rejetée, pas présentée
comme validée. Les références déclarées ne changent pas ce résultat.

### Tests, mesures et verdict de la correction

Validation exécutée par l'agent d'implémentation, avec les outils existants
restaurés dans `.git/c359-venv`, sans modification des dépendances du dépôt :

| Exécution | Résultat |
| --- | --- |
| Dernière exécution des suites hybride, Narrative V3 et Workout Intelligence V3 | **447 réussis**, 7 avertissements |
| Régression élargie V2, CoachLanguage, droits et synthèse de séance, avant les dernières régressions de présentation | **954 réussis, 3 échecs** préexistants |
| Flake8 ciblé `E9,F63,F7,F82` et vérification des espaces du diff | Réussis |

Commande ciblée, depuis `backend/` :

```sh
TMPDIR="$PWD/../.git/c359-venv" ../.git/c359-venv/bin/python -m pytest \
  tests/test_hybrid_coach_c359.py tests/test_narrative_coach_v3.py \
  tests/test_workout_intelligence_v3.py \
  --basetemp=../.git/c359-venv/pytest-target-final \
  --junitxml=../.git/c359-venv/results-target-final.xml \
  -o junit_family=xunit1 -q --tb=line
```

La régression élargie couvre `test_workout_analysis_v2.py`,
`test_workout_analysis_v2_unified.py`, `test_workout_analysis_v2_facts.py`,
`test_workout_analysis_v2_phases.py`, `test_coach_language.py`,
`test_coach_workout_access_pr325.py` et
`test_coach_session_synthesis_c351.py`. Les trois échecs concernent
`test_comparable_history_stays_separate_and_metrics_are_unchanged[en/fr/es]` :
attendu `meaning.consistent_pacing`, reçu
`meaning.hr_without_intensity_with_pacing`. Leur reproduction sur la base
intacte est établie dans la première livraison conservée ci-dessous ; elle
n'a pas été refaite pour cette correction. Ces tests et moteurs restent
inchangés ; aucune suppression pour obtenir du vert.

Les tests couvrent les assertions exactes acceptées **et** les refus :
invention/modification de chiffres ou unités, contradictions texte/preuve,
FC moyenne confondue avec intensité des répétitions, FC maximale présente
sans moyenne, LT1/LT2 absents, progression non démontrée, régularité non
autorisée, cause de fatigue, prescription inventée, historique interdit et
dépendances indirectes, texte caché, identifiants/doublons/JSON invalides,
troncature fournisseur, erreur, timeout, annulation, FREE/TRIAL/PREMIUM et
français/anglais/espagnol. Les sept fixtures initiales sont conservées.

**Mesures fournisseur : non disponibles.** Les sept comparaisons ont
`cost=None` et `provider_duration_sec=None`. Aucun coût nul ou temps LLM
n'est inféré d'un mock. Le timeout de 8 secondes n'est pas une latence mesurée.

**Traçabilité de validation :**

- Base exacte `copilot/dev` :
  `720fb5cd31faca5f9f6435bb0be4c7cbf0f3fcf6`.
- HEAD de la correction de code :
  `c6b9a2bc6ae89c6121f5b0a2b9fb00c9dd3b4fbe`.
  Les dernières sources testées et le code analysé sont ceux de ce commit ;
  la mise à jour ultérieure du présent rapport est documentaire uniquement.
  Le SHA de livraison documentaire final est consigné dans le commentaire de
  livraison de la PR #359 pour éviter un SHA autoréférentiel dans ce fichier.
- Contrôle de secrets des trois fichiers modifiés : aucune détection.
- Validation parallèle après commit : **CodeQL Python, zéro alerte**.
- Revue automatisée groupée **indisponible**, malgré l'enveloppe « Success » :
  modèle `claude-sonnet-4.6` absent du registre. Ce résultat ne constitue pas
  une revue réussie. Une revue indépendante en lecture seule n'a identifié
  aucun problème significatif dans la correction.

**Verdict : HOLD.** Le prototype démontre une meilleure sélection déterministe
de certains faits, pas une synthèse intelligente libre suffisamment fiable.
Trois blocages techniques sont explicites : vérification sémantique libre
indisponible, réponse structurée exposée à la troncature de l'adaptateur partagé,
et absence d'autorité de régularité autonome dans l'entrée V3. À cela s'ajoute
l'absence d'évaluation d'un vrai fournisseur. Ne pas activer sur la seule base
de la fluidité des phrases simulées.

Livraison sur la même PR #359, toujours draft. Flag désactivé par défaut ;
aucune route/UI branchée, aucun moteur scientifique modifié, aucun accès
Garmin/GCCLI, aucune écriture MongoDB, aucun test de séance réelle,
déploiement ou merge. **Attendre l'audit C359 avant toute suite.**

---

## Instantané de la première livraison — non applicable à la correction

<details>
<summary>Audit historique conservé et résultats de la première livraison (avant correction)</summary>

## Périmètre et références

- Base : `copilot/dev`, `720fb5cd31faca5f9f6435bb0be4c7cbf0f3fcf6`.
- Branche de travail : `copilot/c359-prototype-controle`.
- Head de code testé : `d2947d539e50999ed92b0aad4ff1370fc023c2a7`.
  Les commits suivants ne complètent que ce rapport ; le SHA final de livraison
  est également indiqué dans la description de la PR.
- Tests : 390 réussis sur le périmètre hybride/Narrative V3/Intelligence V3 ;
  régression élargie : 919 réussis, 3 échecs V2 préexistants reproduits sur la base.
- Aucun branchement aux routes, aucune modification UI/science, aucun accès
  MongoDB/Garmin, aucune synchronisation, activation, livraison ou fusion.
- Ce rapport est un instantané C359, pas une nouvelle autorité scientifique.

## 1. Audit historique — consigné avant le premier changement de code

Le clone initial était superficiel. `git fetch --unshallow origin` a permis de
consulter les vraies versions historiques. Ne pas confondre le Coach
conversationnel historique avec `CoachLanguageV1`, couche déterministe récente
de conclusions V2.

L'introduction historique est retrouvée à
`fb0f68a253bcbf015e6dcccbab35d5fe82c40c3c`. À ce commit,
`backend/llm_coach.py:38–71` promettait un historique « COMPLETE », VO2max,
prédictions, ACWR et TSB, sans les bornes d'autorisation et d'incertitude
actuelles. Le prompt séance est à `:86–96`. Les imports historiques
`:20` et `backend/coach_service.py:28–37` dépendaient aussi de `training_engine`
(cibles de volume, semaine, phase, charge), dépendance à ne pas restaurer.
Ces observations portent sur cette version historique, **pas** sur le prompt
de chat actuel, qui a depuis reçu des garde-fous explicites.

### Chaîne historique retrouvée

| Version vérifiée | Mécanisme |
| --- | --- |
| `8f18c214d0907db92ab2090e25d4e30d83d326da:backend/rag_engine.py` | Dernière version avant suppression du RAG dans `794d77cbfa4af66963456ef10a3a0b20b8db244c`. `load_knowledge_base` (16), `retrieve_similar_workouts` (437), `retrieve_relevant_tips` (478), `generate_workout_analysis_rag` (942). |
| `15b6f0474f22dcc7af96db862971b39cb0539786:backend/coach_service.py` | Dernière version avant retrait de l'analyse legacy dans `968a604be519c39c2160ec2652818bbdbb9a9854`. `analyze_workout` (110) prépare résumé, splits, comparaison, forces/faiblesses ; enrichissement LLM (148), cache (158), repli déterministe. |
| Même commit, `backend/llm_coach.py` | `SYSTEM_PROMPT_SEANCE` (69–78) : réaction positive, analyse simple, point marquant, conseil pour la prochaine sortie, 4–5 phrases. `enrich_workout_analysis` (137–148) envoie le contexte au fournisseur existant. |
| Base C359, `backend/narrative_coach_v3.py` | Catalogue de faits typés (111–534), rendu déterministe (537), validation par indices/variantes exacts (564), appel optionnel (644). Ce n'est pas une rédaction libre : aucune nouvelle phrase n'est autorisée. |

Le RAG historique n'est pas un index vectoriel sourcé : récupération Python
de séances et sélection de conseils/templates avec `random.choice/sample`.
Le qualificatif « deterministic » de son en-tête n'est donc pas une garantie.
Ses dépendances directes sont la bibliothèque standard, les données d'activité
et `knowledge_base.json`. L'enrichissement ajoute `python-dotenv`,
`emergentintegrations.llm.chat`, la clé d'environnement existante et le modèle
configuré. Aucun de ces composants n'est réinstallé dans l'architecture produit.

### Base de connaissances et exclusions

À la base C359, `backend/knowledge_base.json` contient 19 catégories de conseils
en chaînes simples (190 conseils), sans auteur, publication, date de validation ni citation
scientifique par conseil. La provenance Git prouve l'existence d'un texte, pas
sa validité scientifique. **Aucun contenu de cette base n'est admis dans C359.**
Le fichier initial et celui de la base C359 ont le même SHA-256 :
`893cb8689955aa0dcce7772d521433c51c6bea7b481c3c72c98d65bb7c74dc1d`.

Exclusions concrètes dans le RAG historique :

- `rag_engine.py:492` : cadence manquante remplacée par 180.
- `:640`, `:1019`, `:1058` : cible universelle 170–180 pas/min.
- `:713` : tendance d'allure choisie aléatoirement.
- `:1025–1037`, `:1083–1084` : différence d'allure assimilée à une progression.
- `:1129` : « regular progression » comme texte prérempli.
- `:1167–1173` : conseil template pouvant devenir une prescription concurrente.
- Base de connaissances : « évacuer les toxines », ratio charge/récupération
  universel, règle des 10 %, cadence « optimale » : non réimportés.

### Fonctions encore utilisées à la base C359

- `coach_service.chat_response` → `llm_coach.enrich_chat_response` reste la
  chaîne de chat (`backend/coach_service.py:66–80`, `backend/server.py`).
- `llm_coach._call_gpt` reste le transport du chat et de Narrative V3 ;
  `_clean_response` tronque à 700 caractères (`backend/llm_coach.py:209–299`).
- `load_scoped_workout_intelligence_v3_with_narrative` est appelé par la route
  actuelle (`backend/server.py:2168`) et appelle **uniquement** Narrative V3.
- Le nom `retrieve_similar_workouts` existe dans V2, mais c'est une
  réimplémentation bornée actuelle, pas la remise en service de `rag_engine` :
  `backend/workout_analysis_v2.py:875,938,1067` et
  `backend/workout_analysis_v2_service.py:377`.
- `CoachLanguageV1` reste un contrat de conclusions typées consommé par V2
  et par la lecture versionnée de régularité de Narrative V3 ; ce n'est pas
  le LLM V1.
- `rag_engine.py`, `coach_service.analyze_workout`,
  `llm_coach.enrich_workout_analysis` et le prompt séance ont été supprimés.
  `chat_engine.py` et la base JSON subsistent, mais aucune importation runtime
  de `chat_engine` n'apparaît dans les modules backend non-tests à cette base.

### Comparaison et décision avant implémentation

V1 apporte un ton direct et une sélection de l'information, mais ses conseils,
ses comparaisons et ses déductions ne constituent pas des preuves. V3 lie au
contraire les phrases aux faits, incertitudes et limites des moteurs, au prix
d'une liberté rédactionnelle très faible.

Réutiliser **le style** (point utile d'abord, phrases courtes, pas de récitation),
le transport existant et les preuves typées V3. Ne restaurer ni le moteur RAG,
ni ses valeurs par défaut, ni ses prescriptions, ni ses conclusions
physiologiques. Une paraphrase libre ne peut pas être déclarée fiable par une
simple vérification des nombres ou une seconde opinion LLM. Le prototype
choisira donc une liberté **bornée et vérifiable**, avec repli pour toute
paraphrase dont l'équivalence ne peut être démontrée localement.

## 2. Architecture expérimentale

Un seul nouveau module produit : `backend/hybrid_coach_c359.py`. Il n'est
importé par aucune route, aucun loader ni aucune page. Aucun fichier produit
préexistant n'est modifié.

### Contrat

1. `generate_hybrid_coach` reçoit un `WorkoutIntelligenceV3` déjà calculé et
   limité au propriétaire, ainsi qu'un `UserAccess` résolu côté serveur.
   Ce n'est pas un endpoint et ce contrat ne doit jamais devenir un corps de
   requête autorisant lui-même l'accès.
2. FREE est refusé avant construction du contexte/appel fournisseur.
   TRIAL/PREMIUM passent par `UserAccess.can("coach_workout_analysis")`.
   `llm_access` est également requis avant tout appel LLM.
3. `C359_HYBRID_COACH_ENABLED` absent ou faux → résultat `disabled`, sans texte
   personnalisé ni appel fournisseur. Les tests ne changent cette variable
   que dans leur processus.
4. `HybridPermissions.history` et `.prescription` sont des restrictions
   supplémentaires **désactivées par défaut**, pas de nouvelles offres
   commerciales. Seul le booléen explicite `True` les ouvre dans l'appel
   interne de confiance. Pas de permission implicite par nom de séance,
   formule commerciale fournie par le navigateur ou message conversationnel.
5. Le catalogue vient du builder Narrative V3 actuel, puis d'une allowlist
   fermée. Toute nouvelle catégorie inconnue est exclue par défaut. Les
   dépendances indirectes sont filtrées : une sortie longue utilise
   l'historique même si son `decision_tier` est `personal_thresholds`. Son
   titre et son jugement de conformité sont donc masqués sans autorisation
   historique. Le V3 original n'est jamais modifié/recalculé.
6. Objectifs : le contrat de sortie V3 ne fournit pas d'objectif contextualisé
   et autorisé ; aucun objectif n'est inventé ni injecté depuis du texte libre.
   Prescription : seul le statut V3 autorisé est expliqué. Le seul conseil
   admis est la revue canonique d'un écart de type ; le conseil de confort
   générique de V3 n'est pas repris pour éviter une prescription concurrente.
7. Aucune connaissance RAG scientifique n'est chargée. Seuls le style
   conversationnel historique et le transport LLM existant sont réutilisés.

### Rédaction et contrôle factuel

Le LLM existant (`llm_coach._call_gpt`, modèle configuré par RunIndex) peut
réécrire **une phrase d'observation/interprétation**. Le prompt demande un JSON
compact avec l'indice de cette phrase et son texte rédigé, et fournit les
substitutions linguistiques admissibles FR/EN/ES. Par exemple, « Ta fréquence
cardiaque moyenne » peut devenir « Ta FC moyenne ». Contrairement au sélecteur
V3, le candidat est du texte, mais sa liberté reste volontairement bornée.

Le validateur reconstruit une grammaire à partir de la phrase autorisée :
substitutions exactes composables, tous les autres caractères littéraux.
Il ne vérifie pas seulement la présence des chiffres ou de références
existantes, n'utilise ni score de similarité ni juge LLM. Les nombres, signes,
unités, négations et réserves ne peuvent pas être remplacés librement. Une
phrase plausible extérieure à cette grammaire est rejetée. Les autres phrases
et leurs réserves obligatoires sont rendues localement. Le titre redondant
« type incertain » est supprimé quand l'explication porte déjà cette information.
Une classification non inconnue mais de confiance faible reste accompagnée
d'une réserve explicite.

Chaque phrase du résultat porte ses `evidence_refs` locaux. Le fournisseur ne
reçoit ni identifiant utilisateur/séance, date, chemin de preuve, conseil
arbitraire, historique brut ou texte libre issu du RAG. Les références ne sont
jamais acceptées du fournisseur. Les valeurs physiologiques viennent des faits
V3 ; aucun calcul de LT1/LT2, zone, progrès ou nouvelle prescription n'est ajouté.

Un seul appel, timeout externe de 8 s, aucune relance, aucun cache partagé,
aucune persistance. JSON dupliqué/invalide, unité/chiffre/confiance modifiés,
phrase non démontrable, erreur ou timeout → repli déterministe sur **le même
catalogue autorisé**, jamais sur le V3 complet non filtré. L'annulation du
demandeur se propage. Aucun contenu/exception fournisseur n'est journalisé ici.
Une seule phrase maintient la réponse sous la limite actuelle de nettoyage
de 700 caractères, sans changer le transport de production.

**Limite assumée : ce prototype n'est pas un générateur libre fiable.** Il
teste une liberté rédactionnelle limitée et auditable ; il ne prétend pas
avoir retrouvé toute la richesse conversationnelle V1 ni garantir une
équivalence sémantique générale. Une activation sur cette seule base ne serait
pas justifiée.

## 3. Tests et comparaison synthétique

### Protocole

Fixtures dans `backend/tests/test_hybrid_coach_c359.py:synthetic_case`.
Les deux textes partent de la même sortie du moteur déterministe V3.
Les seuils de laboratoire présents dans certaines fixtures sont **synthétiques** :
ils ne signifient pas que la production persiste ces données.

- Référence : `deterministic_fallback` de Narrative V3 actuel, flag C355 éteint.
- Hybride : flag C359 ouvert uniquement dans le processus de test ; historique
  et prescription explicitement autorisés pour cette comparaison à droits égaux.
- Le transport de test applique une substitution admissible au premier fait.
  Ce sont des **sorties de transport simulé validées**, pas des réponses
  réellement obtenues du modèle. Les tests couvrent aussi le nettoyage réel
  du transport partagé, via un fournisseur simulé.
- Aucun appel réseau LLM, MongoDB ou Garmin. Les tests de route préexistants
  emploient leurs doubles ; aucun cycle startup/synchronisation n'est lancé.
- Lecture qualitative ci-dessous : inspection des sorties, pas une notation
  humaine aveugle. Aucune supériorité conversationnelle n'est démontrée.

### Exactitude, pertinence, conseil et incertitudes — évalués séparément

| Cas | Exactitude factuelle V3 / hybride | Pertinence des observations | Utilité du conseil V3 / hybride | Incertitudes V3 / hybride |
| --- | --- | --- | --- | --- |
| Footing facile | Même position de FC moyenne sous LT1 synthétique ; pas de temps en zone déduit | Fait central conservé ; pas de nouveau fait | Pas de prescription exploitable : aucun conseil ajouté | « Probablement », comparaison historique insuffisante et limites de FC moyenne conservées |
| Sortie longue | Même type probable, dérivé de 100 min contre un historique habituel à 50 min | Le ratio n'est pas exposé dans le texte actuel : limite inchangée | Aucun conseil nouveau | Type probable et limites conservés ; type masqué si historique non autorisé |
| 4 × 4 min | Même décompte de 4 efforts / 3 récupérations | Le contrat V3 ne porte pas les durées individuelles : **ne pas affirmer 4 minutes dans la narration** | Pas de nouvelle allure/charge/récupération prescrite | Ne pas confondre régularité indisponible et irrégularité, dans les deux versions |
| Insuffisamment documentée | Aucun chiffre ni type inventé | Explication de l'abstention, pas une analyse physiologique | Pas de conseil personnalisé démontrable | Incertitude identique, redondance supprimée dans l'hybride |
| Tapis roulant | Aucune référence extérieure comparable utilisée dans cette fixture | Le V3 fourni ne porte pas un fait narratif spécifique « tapis » : aucune extrapolation ajoutée | Aucun conseil spécifique tapis inventé | Même prudence ; absence de comparaison valide conservée |
| Historique comparable | Même gain médian de 24 s/km, 6 observations sur 92 jours | Tendance V3 conservée, pas déduite par le LLM | Pas de prescription modifiée sur la base du gain | « amélioration probable, pas une preuve de gain de forme » conservé |
| Physiologie insuffisante | Aucun LT1/LT2 créé malgré une FC moyenne disponible | Abstention sur le type et la zone, comme V3 | Aucun conseil de zone/allure inventé | Absence de LT1 fiable explicite ; redondance supprimée |

### Lisibilité, naturel et répétitions

| Cas | Mots V3 / hybride¹ | Lecture qualitative et répétitions |
| --- | --- | --- |
| Footing facile | 58 / 57 | Abréviation FC plus directe ; pas de changement conversationnel substantiel |
| Sortie longue | 58 / 57 | Même constat ; contextualisation de la durée encore limitée |
| 4 × 4 min | 40 / 40 | Reformulation du constat Garmin ; réserve de régularité inchangée |
| Insuffisamment documentée | 61 / 53 | Une seule explication de l'incertitude au lieu du titre + explication |
| Tapis roulant | 58 / 57 | Pas de gain de pertinence spécifique au tapis |
| Historique comparable | 71 / 70 | Même phrase de tendance ; pas de répétition numérique supplémentaire |
| Physiologie insuffisante | 61 / 53 | Même déduplication de l'incertitude que pour la séance pauvre en données |

¹ Comptage mécanique par `split()`, pas un indicateur validé de qualité.
Le gain mesuré est surtout la déduplication déterministe et une reformulation
locale. La pertinence et l'utilité restent bornées par les preuves V3 ; il serait
incorrect d'attribuer ces écarts à une amélioration constatée du LLM.

### Coût et latence

30 répétitions locales par fixture, même processus Python 3.12.3, Pydantic
2.13.4. La construction scientifique V3 est exclue des deux chronométrages.
V3 mesure son rendu déterministe ; hybride mesure contexte, coroutine de
transport **simulé**, validation et rendu (son `elapsed_ms`, hors création
de la boucle de test). Pas un benchmark fournisseur ni un résultat production.

| Cas | Médiane locale V3 (ms) | Médiane locale hybride simulé (ms) | Latence LLM réelle | Coût LLM réel |
| --- | ---: | ---: | --- | --- |
| Footing facile | 0,025 | 0,147 | non mesurée | non mesuré |
| Sortie longue | 0,024 | 0,142 | non mesurée | non mesuré |
| 4 × 4 min | 0,020 | 0,133 | non mesurée | non mesuré |
| Insuffisamment documentée | 0,020 | 0,100 | non mesurée | non mesuré |
| Tapis roulant | 0,024 | 0,143 | non mesurée | non mesuré |
| Historique comparable | 0,031 | 0,151 | non mesurée | non mesuré |
| Physiologie insuffisante | 0,022 | 0,102 | non mesurée | non mesuré |

`cost=None` : aucun tarif/compteur de tokens fiable n'est renvoyé par le
transport actuel. `provider_duration_sec=None` pour ces simulations sans
métadonnée de durée. Les chemins désactivé/refusé ne simulent pas une latence
mesurée : `elapsed_ms=None`. L'exécution de cette évaluation n'a effectué aucun
appel fournisseur payant ; cela ne signifie pas que le coût futur est zéro.

### Exemples comparatifs anonymisés

Toutes les données sont synthétiques ; aucune identité ni séance réelle.

**Footing facile — V3 :**

> Probablement un footing facile. Ta fréquence cardiaque moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone. La conformité à la prescription reste indéterminée.

**Hybride simulé validé :**

> Probablement un footing facile. Ta FC moyenne (140 bpm) se situe sous LT1, selon tes seuils personnels. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits, la FC moyenne ne décrit pas le temps passé dans chaque zone. La conformité à la prescription reste indéterminée.

**4 × 4 min — V3 :**

> Une séance fractionnée. Garmin a enregistré 4 phases d'effort et 3 phases de récupération. La comparaison disponible ne permet pas d'établir la régularité des répétitions ; cela ne signifie pas qu'elles étaient irrégulières. La conformité à la prescription reste indéterminée.

**Hybride simulé validé :**

> Une séance fractionnée. L'enregistrement Garmin montre 4 phases d'effort et 3 phases de récupération. La comparaison disponible ne permet pas d'établir la régularité des répétitions ; cela ne signifie pas qu'elles étaient irrégulières. La conformité à la prescription reste indéterminée.

**Séance insuffisamment documentée — V3 :**

> Type de séance incertain. Les données disponibles ne permettent pas d'identifier le type de séance de façon fiable. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits ni LT1 fiable, les moyennes de séance ne permettent pas de confirmer une zone physiologique. La conformité à la prescription reste indéterminée.

**Hybride simulé validé :**

> Avec les données disponibles, le type de séance reste incertain. Ton historique comparable ne permet pas encore de savoir avec confiance si tu progresses ou si tes performances baissent. Sans splits ni LT1 fiable, les moyennes de séance ne permettent pas de confirmer une zone physiologique. La conformité à la prescription reste indéterminée.

**Historique comparable — V3 / hybride :**

Le début est respectivement « Ta fréquence cardiaque moyenne (140 bpm)… »
et « Ta FC moyenne (140 bpm)… ». La phrase spécifique est identique :

> Ton allure médiane est plus rapide de 24 s/km à fréquence cardiaque comparable sur 6 observations sur 92 jours : un signe encourageant d'amélioration probable, pas une preuve de gain de forme.

Les cas sortie longue et tapis reprennent le texte footing ci-dessus, avec
respectivement le titre « Probablement une sortie longue » et le titre footing.
Le cas sans physiologie reprend exactement le couple « séance insuffisamment
documentée ». Ces identités sont un résultat de la comparaison, pas des exemples
de personnalisation supplémentaire.

### Validation exécutée

Répertoire de travail des commandes :
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend`.
Environnement de test isolé : `/tmp/c359-venv/bin/python` ; aucune modification
des dépendances du dépôt. Configuration pytest existante conservée
(`-n 2 --dist loadscope`).

| Vérification au head de code indiqué | Résultat |
| --- | --- |
| `python -m pytest tests/test_hybrid_coach_c359.py tests/test_narrative_coach_v3.py tests/test_workout_intelligence_v3.py -q --tb=short` | **390 réussis**, 7 avertissements préexistants de dépréciation |
| Même commande, plus `tests/test_workout_analysis_v2.py tests/test_coach_language.py tests/test_coach_workout_access_pr325.py` | **919 réussis, 3 échecs**, 14 avertissements |
| Base exacte extraite par `git archive 720fb5cd31faca5f9f6435bb0be4c7cbf0f3fcf6 backend`, puis `python -m pytest tests/test_workout_analysis_v2.py -k test_comparable_history_stays_separate_and_metrics_are_unchanged -q --tb=short` | Les **mêmes 3 échecs** en EN/FR/ES, sans code C359 |
| `python -m flake8 hybrid_coach_c359.py tests/test_hybrid_coach_c359.py --select E9,F63,F7,F82` | Réussi : contrôles de correction ciblés, pas une prétention de lint global |
| `git diff --check` | Réussi |
| Scanner de secrets sur chaque fichier modifié avant commit | Aucun secret détecté |
| CodeQL Python, deux passages dont le dernier après le head de code final | **0 alerte** |
| Revue automatisée incluse dans `parallel_validation` | **Indisponible** : modèle demandé absent du registre ; le statut global « Success » ne prouve pas son exécution |
| Revue indépendante read-only du diff et de la déduplication | Aucun problème significatif relevé |

Les 3 échecs existants sont à
`backend/tests/test_workout_analysis_v2.py:1838` :
`test_comparable_history_stays_separate_and_metrics_are_unchanged[en/fr/es]`
attend `meaning.consistent_pacing`, mais le moteur de base rend
`meaning.hr_without_intensity_with_pacing`. Aucun test ni moteur existant n'a
été modifié pour masquer cette divergence. La suite élargie n'est donc **pas
verte** ; la reproduction sur base distingue ce problème de C359.

Les premiers essais locaux ont nécessité de restaurer les dépendances de test
existantes (pytest, xdist, FastAPI/JWT, puis pytest-asyncio pour les anciennes
suites). Les résultats finaux ci-dessus sont ceux obtenus après restauration,
avec les versions centrales du dépôt (pytest 9.1.1, Pydantic 2.13.4,
flake8 7.3.0, python-dotenv 1.2.2).

Couverture nouvelle : sept fixtures, FREE/TRIAL/PREMIUM et flag, dépendances
indirectes historique/conformité, booléens stricts, références résolubles,
absence de mutation, unités/chiffres/signes/confiance/négations, LT1 inventé,
progrès/efficacité/récupération et prescriptions hallucinés, injection de texte
libre, nouvelles catégories inconnues, JSON malformé/dupliqué, exceptions,
timeout réel, annulation, absence de télémétrie et aucun branchement production.

## 4. Décision de livraison

PR **draft** uniquement. Flag désactivé par défaut. Attendre l'audit C359 avant
toute activation. Aucun déploiement, merge ou changement des écrans actuels.

Points non démontrés restant à l'audit : naturel réellement produit par le LLM,
taux de rejet en conditions réelles, pertinence/utilité jugées en aveugle, coût
et latence fournisseur, admission éventuelle de connaissances historiquement
sourcées. Le prototype n'autorise pas à déclarer ces critères satisfaits.

</details>
