# RUNINDEX PR303 — Restauration de l’analyse des séances

## Révision et périmètre validés

- Base ciblée : `copilot/dev` — `8f0b2e19c5a6e9c975a2a7a29f69ff7533e1c1f5`.
- Révision du code et des tests validée : `f9dde25838704fc0116e5dfb0296626760fbd436` (`copilot/runindex-pr303`).
- Recherche effectuée avant les changements : aucune PR ouverte trouvée pour cet objectif. Les PR #287 et #290 étaient fusionnées.
- Objectif : analyse automatique affichée par `WorkoutDetail`. Le Coach conversationnel, les prescriptions Training V2, le quota et la navigation ne sont pas modifiés.

## 1. Comparaison avant/après PR287 et PR290

La référence « avant PR287 » est le commit `9b7947ec2e1bcd40d520b775f6d4f14a5ef4bcff`. La colonne actuelle décrit le code de `copilot/dev` avant cette PR.

| Fichier | Avant PR287 | Après PR287/PR290, avant PR303 |
|---|---|---|
| `backend/analysis_engine.py` | `generate_session_analysis()` produisait summary, execution, meaning, recovery et advice. Les phrases étaient choisies aléatoirement et l’intensité pouvait être déduite de la distribution de zones sans provenance individualisée (`analysis_engine.py:370-490`). | Moteur supprimé lors de la convergence vers V2. Le contrat V2 conserve des champs d’analyse, mais summary, meaning et advice étaient principalement génériques. |
| `backend/rag_engine.py` | `retrieve_similar_workouts()` sélectionnait jusqu’à trois activités de même type dans une tolérance de distance de ±30 %, sans filtrage temporel strict dans cette fonction (`rag_engine.py:437-463`). L’analyse RAG produisait du texte sur les fractions, la dérive cardiaque, la cadence et une activité similaire (`rag_engine.py:962-1046`). | Le RAG et ses routes ont été retirés. Les données pacing/physiology existent dans V2 quand elles sont présentes, mais leur restitution narrative était perdue ou incomplète. |
| `backend/coach_service.py` | Le serveur enrichissait l’analyse RAG par `coach_analyze_workout()` (`server.py:2545-2554`). | L’enrichissement LLM n’est pas une autorité de l’analyse V2; aucun enrichissement n’est réactivé ici. |
| `backend/llm_coach.py` | Utilisé par l’ancien chemin d’enrichissement; il ne constituait pas une source déterministe des métriques. | Aucun appel LLM ajouté à l’endpoint canonique. Le Coach conversationnel reste hors périmètre. |
| `backend/server.py` | `/rag/workout/{id}` chargeait l’historique utilisateur puis appelait le générateur RAG et l’enrichissement. `/coach/detailed-analysis/{id}` calculait séparément un baseline (`server.py:2525-2583, 2768-2785`). | La route V2 unique `/coach/workout-analysis/{id}` conserve une recherche user-scoped, mais le baseline initial regroupait toutes les distances du même sport sur 14 jours (`server.py:2072-2095` avant PR303). |
| `frontend/src/pages/WorkoutDetail.jsx` | Plusieurs chemins d’analyse alimentaient les cartes; le chemin RAG affichait notamment fractions, dérive, cadence et comparaison (`WorkoutDetail.jsx:625-805`). | Un seul appel canonique V2. Les cartes narrative affichent bien `summary`, `meaning` et `advice`, mais les valeurs retournées ne contextualisaient pas suffisamment ces textes. |

Les PR #287 et #290 ont donc supprimé des capacités de restitution et de recherche historique, mais aussi des comportements qu’il ne fallait pas reprendre tels quels : sélection aléatoire, conclusions de progression sur une seule comparaison, appels LLM, conseils de cadence universels et interprétations physiologiques non établies.

## 2. Capacités perdues ou non exploitées, avec preuves

- **Narration factuelle trop générique :** avant PR303, `_build_summary()` choisissait une phrase structurelle, `_build_meaning()` décrivait surtout l’absence de classification, et `_build_advice()` renvoyait notamment la consigne répétée d’utiliser des zones individualisées (`backend/workout_analysis_v2.py`, anciennes lignes 746-915). Distance, durée, allure et FC étaient disponibles dans le contrat, mais pas intégrées de façon utile aux textes.
- **Mesures pacing/physiology sous-exploitées :** V2 exposait déjà fastest/slowest split, pace drop, negative split, consistency, variability et `hr_drift` (`backend/workout_analysis_v2.py`, modèles et anciens `_build_pacing()`/`_build_physiology()`). Une partie était visible dans des cartes, mais n’alimentait pas la lecture narrative; negative split et régularité n’étaient notamment pas présentés dans `WorkoutDetail`.
- **Recherche historique affaiblie :** l’ancienne recherche RAG utilisait ±30 % de distance et jusqu’à trois résultats; le baseline V2 initial ne filtrait pas la distance et acceptait un échantillon d’un seul workout. L’ancien helper, en revanche, ne garantissait ni antériorité stricte ni fenêtre temporelle : cette partie n’a pas été restaurée sans garde-fous.
- **Mesures Garmin disponibles mais perdues au mapping dérivé :** `GarminActivity` contient `max_hr`, `average_run_cadence` et `elevation_gain` (`backend/garmin/data_layer.py:82-123`), mais `activity_to_workout()` ne les copiait pas dans `workouts` (`backend/garmin/service.py`, ancienne implémentation). Les fractions et la dérive cardiaque ne sont pas fournies par ce modèle de résumé Garmin.
- **Nature entraînement/compétition :** le modèle Garmin courant expose le sport (`activity_type`), mais pas de classification entraînement/compétition; `activity_to_workout()` ne transporte aucun champ de ce type. Le nom et la distance ne sont donc pas utilisés pour inventer une nature de séance.

## 3. Capacités effectivement restaurées

- `summary` inclut les valeurs réellement disponibles de distance, durée, allure moyenne (ou calcul de secours uniquement pour une course si distance et durée sont présentes), vitesse, FC moyenne et FC maximale.
- `meaning` décrit les fractions fastest/slowest, pace drop, régularité, variabilité et dérive cardiaque déjà calculés; il ne signale un negative split que si le champ V2 vaut explicitement `true`. Cadence et dénivelé sont cités comme observations lorsqu’ils sont présents et exploitables.
- `advice` est déterministe, spécifique aux données présentes, et ne prescrit pas de prochaine séance. Une FC brute reste une mesure, pas une classification d’intensité.
- Les textes restent localisés FR/EN/ES. Le contrat V2 conserve exactement ses champs de premier niveau; `GET /api/coach/workout-analysis/{workout_id}` reste l’unique endpoint canonique.
- Les documents `workouts` dérivés des activités Garmin préservent désormais max HR, cadence moyenne et dénivelé déjà fournis par le résumé normalisé. Les valeurs absentes restent `None`; aucune fraction ni dérive n’est créée.
- L’historique de comparaison est borné à 90 jours et 200 candidats, limité au même `user_id`, sport et à une distance dans ±30 %. Le moteur exclut le workout courant et les dates non antérieures, retient au plus les trois références les plus récentes et exige au moins deux références. Le texte précise taille, période et tolérance; il présente les écarts comme comparaison descriptive, jamais comme preuve de progression.
- La récupération des champs Garmin supplémentaires et les tests sont couverts par `backend/tests/test_workout_analysis_v2.py`. Le frontend n’a pas nécessité de modification de production : un test vérifie que `WorkoutDetail` affiche le texte factuel V2 sans le réécrire.

## 4. Comportements historiques volontairement exclus

- Toute sélection aléatoire de phrases/conseils, réactivation d’un endpoint RAG ou création d’un second moteur d’analyse.
- Enrichissement LLM/localisation distante dans l’endpoint déterministe.
- Classification d’intensité à partir de la FC moyenne ou de zones sans provenance individualisée. `_has_trusted_zone_provenance()` reste `False`.
- Attribution de la dérive cardiaque à la fatigue ou à la déshydratation; seuils ou interprétations physiologiques historiques non validés.
- Cadence cible universelle, conseil de modifier la séance, ou classification entraînement/compétition inférée du nom ou de la distance.
- Statuts de charge/fatigue, moyennes de zones et autres métriques historiques qui ne sont ni nécessaires à cet objectif ni suffisamment fondées pour être réintroduites.
- Modifications de Training Today/Week V2, prescriptions, historique immuable, Coach conversationnel, quota ou navigation.

## 5. Fichiers modifiés et justification

| Fichier | Justification |
|---|---|
| `backend/workout_analysis_v2.py` | Textes déterministes FR/EN/ES fondés sur les valeurs V2; comparaison d’activités réellement proches et antérieures; protections pour données invalides/incomplètes. |
| `backend/server.py` | Requête historique user-scoped sur 90 jours, sport et intervalle de distance; nombre de candidats borné à 200. La route et son modèle de réponse restent inchangés. |
| `backend/garmin/service.py` | Copie les seules mesures présentes dans le résumé Garmin normalisé (max HR, cadence, dénivelé) vers le document dérivé utilisé par V2. |
| `backend/tests/test_workout_analysis_v2.py` | Fixtures A/B, analyses factuelles, langues, mesures disponibles, échantillon insuffisant, historique comparable, absence de lookahead, isolation/IDOR, contrat et mapping Garmin. |
| `frontend/src/__tests__/workout-analysis-v2-pages.test.jsx` | Vérifie le rendu intact du texte factuel par `WorkoutDetail` et l’utilisation de l’endpoint canonique. |
| `RUNINDEX_PR303_REPORT.md` | Présent rapport demandé. |

## 6. Exemples générés pour les fixtures obligatoires

Les deux fixtures sont des courses à pied sans zones validées ni fractions fournies.

**Séance A** — 21,27 km, 122 min, allure moyenne enregistrée 5,72 min/km, FC moyenne 160 bpm, maximale 178 bpm :

> **Summary:** Long-duration session completed. distance: 21.27 km; duration: 122 min; average pace: 5:43/km; average HR: 160 bpm; maximum HR: 178 bpm  
> **Meaning:** Recorded session observations: average HR: 160 bpm; maximum HR: 178 bpm  
> **Advice:** Treat the recorded heart-rate values (160 bpm average, maximum 178) as observations; this analysis does not assign an intensity zone.

**Séance B** — 10,18 km, 71 min, allure moyenne enregistrée 6,98 min/km, FC moyenne 127 bpm, maximale 145 bpm :

> **Summary:** Standard-duration session completed. distance: 10.18 km; duration: 71 min; average pace: 6:59/km; average HR: 127 bpm; maximum HR: 145 bpm  
> **Meaning:** Recorded session observations: average HR: 127 bpm; maximum HR: 145 bpm  
> **Advice:** Treat the recorded heart-rate values (127 bpm average, maximum 145) as observations; this analysis does not assign an intensity zone.

Les textes des deux séances diffèrent et citent uniquement leurs valeurs d’entrée. Aucune fraction, zone ou intensité physiologique n’est inventée.

## 7. Résultats exacts des validations

Validés sur la base `8f0b2e19c5a6e9c975a2a7a29f69ff7533e1c1f5`, code/test head `f9dde25838704fc0116e5dfb0296626760fbd436` :

| Commande | Résultat |
|---|---|
| `cd backend && python -m pytest tests/test_workout_analysis_v2.py -q` | **40 passed**, 12 avertissements (dépréciations `crypt`, Pydantic et FastAPI). Le test utilise une DB fake; aucun Redis, worker ou service Emergent réel n’est démarré. |
| `cd frontend && npx craco test --watchAll=false --forceExit --runInBand src/__tests__/workout-analysis-v2-pages.test.jsx` | **1 suite, 6 tests passés**. |
| `cd frontend && npm run build` | **Build réussi**, `Compiled successfully.` Avertissements non bloquants : données Browserslist anciennes et dépréciation Node `fs.F_OK`. |
| `python -m py_compile backend/workout_analysis_v2.py backend/server.py backend/garmin/service.py backend/tests/test_workout_analysis_v2.py` | Réussi. |
| `git diff --check` | Réussi. |

Les suites backend nécessitant Emergent, des workers ou Redis partagé n’ont pas été lancées. L’installation frontend n’a modifié aucun manifeste ni lockfile; npm a signalé 46 vulnérabilités dans l’arbre de dépendances préexistant, hors objectif de cette PR.

## 8. Validations restant à effectuer dans Emergent

- Rejouer le sync/backfill Garmin puis valider sur de vraies séances A et B que max HR, cadence et dénivelé sont bien présents quand le résumé Garmin les fournit.
- Vérifier sur les vraies activités l’existence des fractions, `hr_drift`, consistency et variability dans les documents `workouts`; le modèle de résumé Garmin actuel ne fournit pas les détails de fractions ni la dérive cardiaque.
- Confirmer les exemples et traductions FR/EN/ES dans `WorkoutDetail` sur données réelles, sans classifier l’intensité lorsque la provenance des zones manque.
- Exécuter uniquement les parcours d’intégration Emergent autorisés; ne pas lancer de tests connectés à Redis/workers partagés depuis cet environnement.

## 9. Risques et limites résiduels

- Les données de fraction et de dérive restent indisponibles lorsque les documents `workouts` ne les contiennent pas; cette PR ne télécharge pas d’échantillons Garmin détaillés.
- Le résumé Garmin actuel ne distingue pas entraînement et compétition. Les comparaisons sont donc limitées au sport, à la date et à ±30 % de distance, avec minimum deux références et sans conclusion de progression; leur pertinence devra être vérifiée sur le terrain.
- Une fenêtre de 90 jours, un maximum de trois références et un minimum de deux sont des bornes explicites de comparaison, pas une garantie d’équivalence des parcours, conditions ou intentions de séance.
- La validation Emergent sur véritables activités Garmin reste requise. Cette PR répare l’analyse automatique de `WorkoutDetail`; elle ne prétend pas réparer le contexte du Coach conversationnel, qui relève de la PR suivante.
