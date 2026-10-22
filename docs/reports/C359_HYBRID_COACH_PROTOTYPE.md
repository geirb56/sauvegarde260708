# C359 — Coach hybride V1/V3, prototype contrôlé

## Périmètre et références

- Base : `copilot/dev`, `720fb5cd31faca5f9f6435bb0be4c7cbf0f3fcf6`.
- Branche de travail : `copilot/c359-prototype-controle`.
- Head et tests de livraison : à compléter après validation.
- Aucun branchement aux routes, aucune modification UI/science, aucun accès
  MongoDB/Garmin, aucune synchronisation, activation, livraison ou fusion.
- Ce rapport est un instantané C359, pas une nouvelle autorité scientifique.

## 1. Audit historique — consigné avant le premier changement de code

Le clone initial était superficiel. `git fetch --unshallow origin` a permis de
consulter les vraies versions historiques. Ne pas confondre le Coach
conversationnel historique avec `CoachLanguageV1`, couche déterministe récente
de conclusions V2.

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
en chaînes simples, sans auteur, publication, date de validation ni citation
scientifique par conseil. La provenance Git prouve l'existence d'un texte, pas
sa validité scientifique. **Aucun contenu de cette base n'est admis dans C359.**

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

À compléter avec le contrat effectivement implémenté.

## 3. Tests et comparaison synthétique

À compléter avec les résultats réellement exécutés ; coût, latence fournisseur
et qualité humaine non mesurés restent indisponibles, jamais remplacés par zéro.

## 4. Décision de livraison

PR **draft** uniquement. Flag désactivé par défaut. Attendre l'audit C359 avant
toute activation. Aucun déploiement, merge ou changement des écrans actuels.
