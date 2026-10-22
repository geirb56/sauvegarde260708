# C359 — Coach hybride V1/V3, prototype contrôlé

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
