# RUNINDEX — PR319 — Workout Analysis V2 : synthèse, conseil et limites

## 1. Base, HEAD initial et audit préalable

- Base cible : `copilot/dev`.
- HEAD initial local et distant vérifié : `102affacf3c46e248217b1239c56fb5df4fab22d`.
- Ce commit est le merge de #318 : `Merge pull request #318 from geirb56/copilot/restructuration-ux-workout-detail`.
- Branche de travail : `copilot/improve-workout-analysis-v2`.
- HEAD du code testé et validé : `f504e108dc62d438ca124111d9b7570686d57331`.
- Le commit suivant ajoute uniquement ce rapport ; le HEAD final de livraison figure dans les métadonnées de la PR. Le SHA ci-dessus désigne précisément le code validé, pas un SHA futur supposé.

L'audit a précédé toute modification : historique Git et HEAD distant, modèles Pydantic, fonctions éditoriales et scientifiques, recherches globales des consommateurs, tests existants et configuration pytest. Un seul objectif : le contrat éditorial. Aucun merge automatique ni déploiement effectué.

## 2. Cartographie des consommateurs et risques audités

| Consommateur | Utilisation réelle | Compatibilité |
|---|---|---|
| `backend/workout_analysis_v2_service.py:200-249` | Construit le modèle après enrichissement Garmin et recherche historique scoped | Inchangé ; le constructeur ajoute les champs éditoriaux |
| `backend/server.py:2081-2098` | Route `/api/coach/workout-analysis/{workout_id}` avec `response_model=WorkoutAnalysisV2Response` | Route, authentification et scoping inchangés ; nouveaux champs sérialisés par Pydantic |
| `backend/server.py:1874-1884,1996` | Charge la même analyse pour le coach | Pas de recalcul ni changement de source |
| `backend/coach_context_v2.py:25,78,720-774,1012` | Embarque le modèle dans `workout_detail.analysis` et le contexte canonique | Le modèle typé propage les champs ; les projections existantes des signaux/comparaisons ne changent pas |
| `frontend/src/pages/WorkoutDetail.jsx:251,392-405,560-598` | Affiche `meaning.text` et `advice.text`, garde les preuves/limites techniques en détails | Les chaînes restent non nulles ; pas de refonte, nouveau message explicite si conseil indisponible |
| `frontend/src/pages/DetailedAnalysis.jsx:48,161-177` | Affiche les mêmes textes, carte conseil conditionnée par la présence du texte | Compatible ; affiche le message d'indisponibilité au lieu d'une limitation |
| `frontend/src/pages/SessionDetail.jsx:80,199-212` | Sections alimentées par les textes ; conseil sous un ancien intitulé de prochaine séance | Compatible structurellement ; cet intitulé reste un risque éditorial frontend |
| Tests backend | `test_workout_analysis_v2.py`, `test_rag_enrichment.py`, `test_coach_context_v2.py` | Assertions éditoriales concernées adaptées ; garde-fous scientifiques et tests d'accès conservés |
| Tests frontend | `frontend/src/__tests__/workout-analysis-v2-pages.test.jsx` | Inspectés comme consommateurs de fixtures ; non modifiés, non exécutés |

Aucun consommateur applicatif identifié ne branche sur `meaning.code` ou ne valide un ensemble strict de clés JSON. Les tests backend qui imposaient cet ensemble ont été adaptés à l'extension. Les clients externes inconnus utilisant une validation stricte des clés additionnelles constituent un risque résiduel explicite.

## 3. Contrat avant / après

Tous les champs racine existants et `version="v2"` sont conservés :
`workout`, `summary`, `signals`, `physiology`, `pacing`, `comparison`, `meaning`, `advice`, `evidence`.

| Champ | Avant | Après |
|---|---|---|
| `summary` | `{code, text}` : faits distance/durée/allure ou vitesse et FC, éventuellement signal d'intensité | Identique ; déjà une synthèse factuelle courte, sans historique |
| `meaning` | `{code, text}` : concaténation de nombreuses observations et réserves historiques | Même forme ; une conclusion déterministe, une ou deux phrases, sans métriques chiffrées ni comparaison répétée |
| `advice.code` | Code d'observation ou de limite | Codes existants conservés, y compris les anciens codes d'indisponibilité |
| `advice.text` | Observation ou limitation, suivie éventuellement d'une autre limitation | Une observation exploitable, ou un message court d'indisponibilité ; jamais une limitation technique |
| `advice.available` | Absent | Booléen ajouté via `WorkoutAnalysisAdvice`, sous-classe de `AnalysisText` |
| `limitations` | Pas de liste racine ; réserves dispersées dans les textes ou données structurées | Liste ajoutée de `{code, text}` localisés, ordonnée et dédupliquée par code |

### Sémantique et valeurs par défaut

- `advice.available=true` : une observation est soutenue par les signaux déjà existants : variation d'allure, negative split, régularité, dérive cardiaque, volume structurel long ou intensité si elle devient disponible selon les règles existantes. Cela **n'autorise aucune prescription**.
- `advice.available=false` : les anciens codes `advice.hr_without_intensity` et `advice.no_hr` restent présents, mais leur texte exposé devient un message d'indisponibilité, pas une explication technique.
- Lors du chargement d'un ancien payload sans ce booléen, sa valeur par défaut est `false`, conservatrice : on ne certifie pas rétroactivement la disponibilité d'un ancien conseil.
- `limitations` utilise `Field(default_factory=list)` : un ancien payload sans ce champ est accepté et reçoit sa propre liste vide. Vide signifie absence de limitations centralisées transmises, pas preuve de l'absence de limites.
- Les lecteurs anciens de `{code,text}` continuent de lire ces champs ; les nouveaux clients doivent utiliser `available`, et non déduire la disponibilité de la présence du texte.

### Codes et limites

Nouveaux codes d'interprétation : `meaning.pace_change`, `meaning.negative_split`, `meaning.consistent_pacing`, `meaning.hr_drift`. Les codes de repli antérieurs restent disponibles. La variation d'allure utilise une formulation neutre, compatible avec un écart signé positif ou négatif.

Codes centralisés : `limitations.intensity`, `limitations.heart_rate`, `limitations.splits`, `limitations.baseline`, `limitations.baseline_descriptive`, `limitations.comparability`, `limitations.no_comparable_reference`, `limitations.sample_too_small`, `limitations.pace_sample_too_small`, `limitations.hr_sample_too_small`, `limitations.session_nature_unknown`.

Ces limites proviennent des indicateurs existants, de `comparison.similar.limitations` et des métadonnées explicites de nature de séance. Les raisons d'indisponibilité et codes historiques imbriqués sont conservés pour les anciens consommateurs. La limite déterminante sur l'intensité reste aussi une phrase courte dans la conclusion quand nécessaire.

## 4. Causes racines et correction

- `_build_meaning()` empilait allure, dérive cardiaque, terrain/cadence et historique avant une conclusion : redondance avec les sections structurées.
- `_advice_primary_code()` pouvait sélectionner une limitation en l'absence de signal exploitable ; `_advice_complement_code()` en ajoutait une autre.
- Le contrat `AnalysisText` seul ne distinguait pas l'indisponibilité d'une observation réellement disponible.

La conclusion sélectionne désormais un seul fait démontré ; sinon elle reconnaît brièvement ce qui ne peut être interprété. Le complément technique du conseil est supprimé et remplacé par la liste centralisée. Les critères de sélection d'observations existants sont préservés.

`_intensity_code()`, sa provenance, les zones Garmin, le pacing, les comparaisons historiques et Training V2 sont inchangés. En particulier, `_has_trusted_zone_provenance()` reste toujours faux dans ce HEAD : même une séance complète avec zones enregistrées ne débloque pas une classification physiologique. Aucun LT1/LT2, récupération, charge ou prochaine séance n'est inventé ; aucun LLM n'est introduit.

## 5. Fichiers modifiés

1. `backend/workout_analysis_v2.py` : modèles additifs, traductions FR/EN/ES, conclusion courte, disponibilité du conseil et limitations centralisées.
2. `backend/tests/test_workout_analysis_v2.py` : assertions éditoriales adaptées, cas multilingues, compatibilité Pydantic/API et invariants numériques.
3. `RUNINDEX_PR319_REPORT.md` : présent rapport.

Aucun changement frontend, de route, d'authentification, de dépendance du dépôt ou de Training V2.

## 6. Exemples FR / EN / ES

Extraits réellement produits pour une séance avec allure moyenne et FC, sans zones fiables, sans fractions ni observation exploitable. Le code reste `meaning.hr_without_intensity_with_pacing`, avec `advice.code="advice.hr_without_intensity"` et `advice.available=false`.

| Langue | `meaning.text` | `advice.text` |
|---|---|---|
| FR | Des données d'allure et cardiaques sont enregistrées. L'intensité physiologique ne peut pas être déterminée de manière fiable. | Aucune observation coach exploitable n'est disponible avec ces données. |
| EN | Pacing and cardiac data are recorded. Physiological intensity cannot be reliably determined. | No usable coaching observation is available from these data. |
| ES | Hay datos de ritmo y cardíacos registrados. La intensidad fisiológica no puede determinarse de forma fiable. | No hay una observación útil de coaching disponible con estos datos. |

Les limites sur l'intensité, les fractions et l'historique sont présentes dans `limitations`, sans être intégrées au conseil.

Avec un `split_analysis.pace_drop=0.6` déjà calculé, l'observation devient disponible (`meaning.pace_change`, `advice.even_pacing`, `available=true`) :

| Langue | Conclusion | Observation exploitable |
|---|---|---|
| FR | Les fractions enregistrées montrent une variation marquée de l'allure pendant cette séance. L'intensité physiologique ne peut pas être déterminée de manière fiable. | La variation d'allure observée est un point utile à comparer avec les prochaines séances de distance similaire. |
| EN | The recorded splits show a marked pace change during this session. Physiological intensity cannot be reliably determined. | The recorded pace change is a useful data point to compare with future sessions of similar distance. |
| ES | Los parciales registrados muestran un cambio marcado de ritmo durante esta sesión. La intensidad fisiológica no puede determinarse de forma fiable. | El cambio de ritmo observado es un dato útil para comparar con las próximas sesiones de distancia similar. |

Ce sont des points d'observation, pas des prescriptions de séance future.

## 7. Tests et validations réellement exécutés

Répertoire d'exécution : `/home/runner/work/sauvegarde260708/sauvegarde260708`.
Interpréteur : `/tmp/backend_env/bin/python`, Python 3.12.15.

### Tests existants et nouveaux

Commande exécutée, puis répétée sur le code final :

`/tmp/backend_env/bin/python -m pytest backend/tests/test_workout_analysis_v2.py backend/tests/test_rag_enrichment.py backend/tests/test_coach_context_v2.py -q`

Résultat final : **301 passed, 14 warnings**, avec les deux workers et `--dist loadscope` imposés par `backend/pytest.ini`.

Couverture : données complètes, FC sans zones fiables, absence de FC/fractions, historique comparable/non comparable/insuffisant, dénivelé et cadence, absence de signal exploitable, observations de pacing dans les deux sens et dérive, FR/EN/ES, routes scoped, defaults Pydantic et lecteurs `{code,text}`. Les conclusions sont bornées à 240 caractères et deux phrases dans la matrice, sans métriques ou historique répétés.

### Invariants et contrôles

- Comparaison directe des moteurs initial et modifié, chargés séparément depuis le Git initial et le module courant : **855 réponses comparées** (285 fixtures existantes × FR/EN/ES). Tous les champs préexistants hors `meaning/advice` sont strictement identiques : `version`, `workout`, `summary`, `signals`, `physiology`, `pacing`, `comparison`, `evidence`.
- Comparaison AST initial/courant : seules la table de traduction, la construction éditoriale et l'assemblage du résultat ont changé ; les fonctions scientifiques et `_advice_primary_code()` restent identiques.
- `/tmp/backend_env/bin/python -m flake8 backend/workout_analysis_v2.py backend/tests/test_workout_analysis_v2.py --select E9,F63,F7,F82` : réussi.
- Compilation avec `python -m compileall -q` des deux fichiers Python : réussie.
- `git diff --check` : réussi.
- Scan de secrets des fichiers Python modifiés : aucun secret détecté.
- `parallel_validation`, exécuté après commit et répété : **CodeQL Python, 0 alerte**. Sa revue automatisée est indisponible à cause d'un modèle absent du registre ; le statut affiché « Success » ne constitue donc pas une revue réussie.
- Revue complémentaire read-only par l'agent `code-review` : aucun problème significatif identifié. La dernière correction supplémentaire est une neutralisation FR/EN/ES de la variation d'allure, avec tests dédiés.

### Environnement et limites de validation

FastAPI 0.110.1, Pydantic 2.13.4, pytest 9.1.1, pytest-xdist 3.8.0 et pytest-asyncio 1.4.0.
L'environnement local a restauré les dépendances existantes sans modifier leurs fichiers : le wheel privé litellm et emergentintegrations étaient indisponibles ; litellm public 1.104.2 a été utilisé, avec des contraintes transitives différentes. Les suites sélectionnées passent, mais cette restauration ne prouve pas la compatibilité d'intégrations LLM non exercées. Aucun besoin LLM dans ce moteur déterministe.

Les warnings sont les dépréciations existantes Starlette/multipart, passlib/crypt, Pydantic Config et FastAPI on_event. Aucun test/build frontend, test mobile visuel ni déploiement Emergent n'a été exécuté dans cette tâche.

## 8. Risques résiduels

- Les anciennes pages ignorent `advice.available` : elles affichent un message explicite d'indisponibilité, pas une limitation déguisée en conseil.
- La liste racine complète des limitations n'est pas encore affichée par le frontend ; les garde-fous historiques déjà consommés restent accessibles à leur emplacement actuel.
- Un client externe strict sur les clés JSON ou les codes `meaning` nouveaux devra accepter l'extension.
- La fiabilité de l'intensité reste volontairement indisponible avec la provenance actuelle ; cette PR ne tente pas de la débloquer.
- La validation est locale et ciblée, pas une preuve de déploiement ni de réussite de toute la suite du dépôt.
- La revue automatisée indisponible et les écarts d'environnement décrits ci-dessus restent des limites de validation, sans alerte CodeQL connue.

## 9. PR frontend complémentaire

Recommandée, séparée de cette PR : présenter la liste `limitations` dans les détails avancés, utiliser explicitement `advice.available` et corriger l'ancien intitulé « prochaine séance » de SessionDetail pour une observation de séance passée. Ne pas recalculer les signaux dans l'UI et conserver Training Today/Week comme seule autorité de prescription.

La présente PR reste une extension backend compatible ; elle ne refond pas `WorkoutDetail.jsx`.
