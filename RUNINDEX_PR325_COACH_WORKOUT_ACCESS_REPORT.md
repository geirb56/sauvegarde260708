# RUNINDEX — PR325 — Accès aux analyses de séances du Coach IA

## Références exactes et périmètre

- Base cible : `copilot/dev`, `2e9dfacae2d3c69f6e0273145cfdad86883f9acf`
  (identique au HEAD initial, vérifié par fetch).
- Head de code testé : `c9720f9801465e73f83ddaa362e9733a55ad5fef`.
- Branche : `copilot/c325-controle-acces-analyses-sessions`.
- Le commit ajoutant ce rapport est documentaire ; le HEAD final de livraison
  sera indiqué dans la description de la PR, sans référence circulaire dans ce fichier.
- Objectif unique : entitlement `coach_workout_analysis` dans le Coach backend.
  Aucun changement frontend, moteur scientifique, Training V2, ActivityPhase,
  ingestion, quota, migration, déploiement ou intégration de #324.
- PR à soumettre en attente de C325 ; ni merge ni déploiement.

## Audit préalable en lecture seule

L'audit du code réel, complété par un spécialiste sécurité en lecture seule,
a été terminé avant toute modification. Les positions « avant » ci-dessous
désignent la base exacte indiquée ci-dessus.

| Étape | Preuve avant correction |
|---|---|
| Réception | `backend/server.py:627-631`, `CoachRequest` : `message`, `workout_id` optionnel, `context` texte optionnel, `language`. Aucun identifiant utilisateur fourni par cette requête n'est utilisé. |
| Entrée | `backend/server.py:1731-1737`, `analyze_with_coach` délègue à `process_coach_message`, avec utilisateur authentifié. |
| Chargement | `backend/server.py:1870-1884`, `process_coach_message` appelle `load_scoped_workout_analysis_v2` avant la résolution d'accès. |
| Validation de propriété | `backend/workout_analysis_v2_service.py:253-265`, requête exacte `{id: workout_id, user_id: user_id}` ; absence ou séance étrangère donne `None`, puis 404. |
| Construction scientifique | Même service, `:267-305` : enrichissement existant, historique utilisateur borné, `build_workout_analysis_v2`. Aucun entitlement dans ce service. |
| Injection | `backend/server.py:1981-2018` transmet `workout` et `workout_analysis` au contexte, puis au LLM. `backend/coach_context_v2.py:720-775,1012`, `_normalize_workout_detail` conserve l'objet canonique dans `workout_detail.analysis`. |
| Permissions scientifiques | `backend/coach_context_v2.py:321-351`, `build_llm_coach_context` calcule `selected_workout_permissions` selon les preuves scientifiques, pas selon l'abonnement. |
| Abonnement | `backend/server.py:1890-1913` : accès utilisé pour quota seulement, sans `can("coach_workout_analysis")`. |
| Historique injecté | `backend/server.py:1916-1921,2016`, utilisateur + `workout_id`, cinq messages sélectionnés ; `backend/llm_coach.py:162-168` en expose au maximum quatre, tronqués à 200 caractères. |
| Historique affiché | `backend/server.py:2035-2044,2054-2064` stocke les analyses avec `workout_id`, puis GET history renvoie tous les messages utilisateur, même après expiration des droits. |
| Génération | `backend/llm_coach.py:148-254`, `enrich_chat_response` / `_call_gpt` : texte et système LLM uniquement, aucune résolution d'identifiant, outil, recherche de séances ou récupération RAG. |
| Pont secondaire | `backend/coach_service.py:66-104`, `chat_response` transmet contexte et historique à `enrich_chat_response` ; aucun appel runtime depuis `server.py`. |
| Frontend | `frontend/src/pages/Coach.jsx:31-61,71-164` charge history, transforme `?analyze=` en `workout_id`, et transmet celui-ci aux relances. `WorkoutDetail.jsx`, action Ask Coach, navigue vers cette route. Aucune modification. |

### Contournements établis

1. FREE avec quota disponible : POST analyze + identifiant de sa séance charge
   V2 et l'injecte au LLM malgré l'absence du droit.
2. Après downgrade/expiration : GET history réexpose les analyses sélectionnées
   déjà stockées. Protéger seulement le chargement ne ferme pas ce chemin.
3. Les réponses générales anciennes ou produites avec entitlement ne disposent
   pas toutes d'une provenance permettant de prouver leur innocuité pour FREE.
   Un contenu analytique ancien est simulé dans les tests ; ce n'est pas une
   affirmation qu'une telle donnée existe dans la base de production.

### Messages sans `workout_id`, autres endpoints et RAG

- Un identifiant dans `message` ne déclenche **aucun** chargement V2 réel.
  `request.context` n'est pas utilisé par le chemin actuel.
- Le contexte `recent_workouts` contient des observations factuelles bornées
  (`CoachRecentWorkout`, `coach_context_v2.py:27-44,862-940`), sans analyse V2.
  Elles restent disponibles à FREE.
- Les messages généraux peuvent demander une interprétation au LLM même sans
  résolution de séance. La politique système impose désormais un refus
  explicite de l'analyse personnalisée, y compris ID/nom/date/métriques copiées.
  Cela n'est pas une preuve mathématique du respect de cette règle par le modèle.
- `chat_engine.py` contient un ancien moteur statique ; aucune utilisation dans
  le chemin Coach serveur actuel. Les routes détaillées/guidance/digest/RAG
  historiques ne sont pas actives (`tests/test_rag_endpoints.py:217-240`).
- L'audit observe que le Coach général conserve son contexte actuel de
  Training/readiness/load/performance via appels internes. Une révision
  générale des autres droits Premium serait un autre objectif ; aucun
  chargement V2 par ce mécanisme n'a été établi et il n'est pas modifié.

## Cartographie des contrôles d'abonnement

- `access_control.py:85-109,187-205` :
  `coach_workout_analysis` est Premium ; `UserAccess.can()` est l'autorité.
- `get_user_access`, `:278-328` : erreur DB donne FREE ; `_resolve_access`,
  `:331-380` : TRIAL actif et PREMIUM valide autorisés, expiration/données
  invalides/statut inconnu refusés. La politique DEMO existante reste inchangée.
- `ROUTE_ACCESS_MAP`, `:396-441` : analyze/history restent FREE ;
  workout-analysis et autres routes Coach non explicitement FREE sont Premium.
- `server.py:461-535` : middleware Premium authentifié, refus 403 explicite
  `subscription_required` ou `subscription_check_failed`.
- Quotas canoniques conservés : FREE 10 messages/mois, plafond anti-abus 500 ;
  réservation atomique, bootstrap, restitution avant persistance et suppression
  d'historique sans réinitialisation du quota restent inchangés.

## Correction exacte

### Chargement et réponse

`server._coach_access` résout l'accès canonique et évalue exclusivement
`access.can("coach_workout_analysis") is True`. Une exception ou un objet
indéterminé donne une capacité refusée et les limites FREE existantes.

`process_coach_message` effectue ce contrôle **avant** chargement, quota,
historique, contexte, persistance et LLM. Toute demande sélectionnée sans droit
renvoie une `CoachResponse` déterministe FR/EN/ES mentionnant essai actif/Premium
et `/subscription`. HTTP 200 conserve le contrat consommé par le frontend
actuel, qui transformerait un 403 en indisponibilité générique.
`message_id=""` indique qu'aucun message n'a été persisté ; pas de faux ID.
Ce résultat est un refus, jamais une analyse réussie.
Un refus ne réserve ni ne consomme un message ; les quotas des conversations
réellement traitées ne changent pas.

`get_workout_analysis_v2` ajoute le même entitlement pour les appels internes,
en complément du middleware HTTP. En cas de refus, 403 avec convention
`subscription_required`. Le loader et tous les calculs restent inchangés.
Pour les accès autorisés, propriété toujours vérifiée ; aucune fuite interutilisateur.

### Frontière du contexte et historique

- `build_llm_coach_context(..., workout_analysis_allowed=False)` enlève
  `workout_detail` et les permissions dérivées de cette analyse avant injection ;
  conserve observations factuelles, historique d'activités et contexte général.
- Le backend transmet la capacité explicite au LLM ; `enrich_chat_response`
  ajoute une restriction système de l'analyse personnalisée pour FREE.
  Le chemin autorisé garde ses règles scientifiques et sa génération actuelle.
- `_coach_history_scope` filtre **avant pagination** : FREE ne voit que le
  scope général, ses messages utilisateur et les réponses assistant marquées
  serveur `coach_workout_analysis_allowed=False`.
- Même filtre pour GET history et historique transmis au LLM.
  L'entitlement vrai conserve l'historique existant.
- La provenance est écrite par le serveur lors de l'insertion des nouvelles
  réponses ; aucune valeur frontend ne peut la définir.
- Aucun enregistrement supprimé ou migré. **Compromis explicite** :
  les anciennes réponses assistant générales sans provenance, et les réponses
  générales produites avec entitlement, ne sont plus affichées à FREE.
  Elles restent stockées et accessibles avec droits actifs. Cette mesure
  conservatrice évite de reconstituer des analyses via un historique ambigu ;
  elle ne supprime pas tout l'historique général.

## Tests exécutés

Interpréteur : `/tmp/pytest_env/bin/python`, Python 3.12.3.
Environnement de validation restauré sans modification des manifests.
Il n'est **pas** identique au lock Emergent : notamment pytest 9.1.1,
pytest-xdist 3.8.0, pytest-asyncio 1.4.0, FastAPI 0.143.0,
Starlette 1.7.0, Pydantic 2.14.0, Motor 3.7.1, PyMongo 4.18.3.
Le système Python initial n'avait pas pytest.

Commande finale, depuis le répertoire absolu
`/home/runner/work/sauvegarde260708/sauvegarde260708/backend` :

```sh
PYTHONPATH=/home/runner/work/sauvegarde260708/sauvegarde260708/backend \
/tmp/pytest_env/bin/python -m pytest \
  tests/test_coach_workout_access_pr325.py \
  tests/test_coach_contract_unified.py \
  tests/test_coach_context_v2.py \
  tests/test_llm_coach_voice.py \
  tests/test_subscription_middleware_a63.py \
  tests/test_subscription_status_quota_contract.py \
  tests/test_subscription_tiers_contract.py \
  tests/test_workout_analysis_v2.py \
  tests/test_workout_analysis_v2_phases.py \
  tests/test_rag_endpoints.py \
  tests/test_idor_integration.py -q
```

**Résultat : 535 passed, 12 avertissements de dépréciation, 2,66 s.**
Configuration existante : `-n 2 --dist loadscope`.
`git diff --check` réussi. Flake8 tenté : module absent, lint non exécuté.
Pas de build frontend : aucun frontend modifié.

Les **27 cas ciblés** de `test_coach_workout_access_pr325.py` couvrent :
FREE sélectionné/refus/aucun loader/contexte/LLM/quota/persistance ;
TRIAL actif/PREMIUM ; TRIAL expiré ; statut inconnu/expirations manquantes ;
objet d'accès inconnu/exception/erreur DB ; séance étrangère FREE/PREMIUM ;
général et identifiant dans message sans loader ; contexte préconstruit ;
directive système ; anciens historiques/expiration/pagination/isolation ;
quota de dix conversations après refus ; API dédiée interne et HTTP
FREE/TRIAL/PREMIUM avec payload scientifique identique au loader.

Les deux adaptations des tests existants reflètent le nouvel ordre :
la validation de propriété d'une séance absente/étrangère est exercée avec
entitlement valide ; l'historique complet est exercé avec entitlement valide.
Les assertions propriété/404/absence de quota et LLM restent présentes.
Le faux Mongo du contrat est étendu à `$or`, sans changement de test de quota.

### Tentatives supplémentaires et limites

- Premier essai ciblé : 415 passed, 2 failed ; corrigés :
  fixture historique sans résolution Premium et égalité d'ordre sur dates absentes.
- Essai élargi : 537 passed, 17 failed. Seize cas de
  `test_coach_conversational.py` nécessitent un backend runtime externe :
  URL sans schéma (`/api/...`), configuration absente.
- Le dernier échec, `test_pr211_coach_llm_cleanup.py::test_server_coach_analyze_no_hr_speed_vma_exposure`,
  recherche `predict_races(` directement dans `analyze_with_coach`, alors que
  cette fonction délègue déjà à `process_coach_message` à la base exacte.
  Assertion obsolète préexistante, laissée intacte hors périmètre.
- Ces suites ne sont pas présentées comme vertes ni supprimées ;
  la commande finale est la sélection offline explicitement listée.

## Validation sécurité et revue

- Scan des six fichiers Python modifiés : aucun secret détecté.
- Revue séparée en lecture seule : aucun problème significatif.
- `parallel_validation` sur le head de code : CodeQL Python, **0 alerte**.
- La revue intégrée annoncée « Success » n'a en réalité pas pu exécuter son
  modèle (modèle indisponible). Ce résultat n'est pas assimilé à une revue
  réussie ; la revue indépendante ci-dessus ne remplace pas C325.

## Risques résiduels et vérifications Emergent requises

1. Les tests mockent les réponses LLM et vérifient les entrées/contrôles, pas
   l'obéissance du modèle. Le refus backend sélectionné et l'absence de V2
   sont déterministes ; l'analyse demandée via texte arbitraire sans sélection
   dépend encore de la restriction système. **Aucune garantie générale de
   filtrage sémantique ou de résistance totale aux prompt injections.**
2. Les messages utilisateur généraux conservés peuvent contenir une analyse
   copiée. Ils sont du texte non fiable, pas une autorisation. Vérifier avec
   le vrai modèle que les demandes d'interprétation sont refusées, sans
   empêcher les questions factuelles et générales.
3. Vérifier le compromis de visibilité des anciens assistant turns en C325,
   et la requête `$or`/`workout_id:null` sur MongoDB réel avant intégration.
4. Tester FREE/essai actif/essai expiré/PREMIUM et panne de résolution en
   environnement Emergent : refus clair sélectionné, aucune génération ni
   lecture V2 ; payload et réponses scientifiques identiques avec droit.
5. Vérifier affichage frontend existant du refus 200, relances sélectionnées,
   historique après downgrade, pagination et absence de réexposition.
6. Vérifier messages sans sélection (ID, nom, date, analyse copiée,
   demande de comparaison), sans loader/outils et sans interprétation réservée ;
   préserver questions factuelles, motivation et autres usages Coach permis.
7. Vérifier compteurs quota (10/11, mois civil, suppression historique),
   isolation de deux comptes synthétiques et API dédiée 403/200/404.
8. Réexécuter avec dépendances et infrastructure Emergent réelles.
   Les tests de dépôt/GitHub **ne valident pas le runtime Emergent**.

Si une protection supplémentaire exige un classifieur sémantique général,
une migration de provenance ou une refonte des autres droits de contexte,
arrêter et demander un périmètre séparé. C325 et les vérifications runtime
restent des portes d'intégration ; ne pas merger ni déployer cette PR.
