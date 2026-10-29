# C388 — Restore factual workout insights in Narrative V3

## Périmètre et provenance

- Base exacte : `copilot/dev`, `b80bfb174a0e64150b597503e79835a11bf9079d`.
- Head code testé : `fd46bf6c8dcaf0e0e8d95c374ece94d62e571a50`.
- Le commit suivant ajoute uniquement ce rapport ; le head final exact figure dans la description de PR.
- Aucun déploiement, merge, appel Garmin ou changement de données.

**Sorties réelles : aucune nouvelle réponse Emergent collectée.** Aucun accès runtime authentifié n'est configuré dans cet environnement. Les rapports C386/C387/C387B ne sont pas présents dans les fichiers ou résultats GitHub consultés. La recherche d'une branche Git nommée `pr167` a renvoyé 404 ; la résolution du commit `b4fcb2d` a échoué. Ces recherches GitHub ne constituent pas une vérification du runtime Emergent mentionné dans la demande. La base effectivement disponible contient bien C382 (`b80bfb1`).

**Sorties déterministes :** les avant/après ci-dessous exécutent le code Narrative de cette base et le nouveau code sur les mêmes fixtures françaises. Ce ne sont pas des réponses sauvegardées des trois activités réelles.

Les fixtures historiques figent seulement les faits fournis dans la demande C388 : nombre de références et écarts de +25,3 et −70,7 s/km. Elles ne fabriquent ni séances de référence, ni allure historique de base, ni splits manquants. Leur contrat V2 est partiel, pas une reconstruction du payload réel complet. La classification probable est explicitement positionnée pour tester sa coexistence avec ces faits.

Le fractionné réutilise les mesures **synthétiques** déjà documentées dans `coach_session_synthesis_c351.json`. Elles reproduisent les allures arrondies et les écarts demandés ; les récupérations de cette fixture ne sont pas présentées comme des mesures runtime vérifiées.

**Exemples illustratifs supplémentaires : aucun.**

## Cause racine et contrats inspectés

Le parcours exécuté est `workout_intelligence_v3_service` → `build_workout_analysis_v2` → `build_coach_language` / `build_session_synthesis` → Narrative → `NarrativeWorkoutAnalysis`.

Le loader construisait déjà V2 dans le chargement utilisateur, mais transmettait uniquement `phase_analysis` et `coach_language` à Narrative. `session_synthesis` était ignorée. Narrative reconstruisait alors quelques phrases depuis V3 et une sélection restreinte des preuves de régularité V2. La répétition atypique, la proximité des extrémités et la FC descriptive étaient perdues. La comparaison historique V2 par distance n'entrait pas dans ce catalogue. Pour certaines classifications historiques, une phrase de méthode devenait l'analyse principale.

Structures réellement présentes :

| Structure | Champs et autorité |
|---|---|
| `session_synthesis` | `version="v2"`, `status=available/insufficient`, `primary` optionnel, au plus deux `supporting`, deux `limitations`, `abstention` optionnel |
| `primary` / `supporting` | `code`, `text`, `kind=observation/interpretation`, dictionnaire numérique `evidence` fini, `source_paths`, `replaces_factual_codes` |
| Réserve V2 | `code`, `text`, `source_paths` ; pas de champ numérique ou de confiance inventé |
| Conclusions V2 | `coach_language.conclusions[index]` : disponibilité, catégorie, priorité, type descriptif/conclusion, preuves numériques et métadonnées versionnées |
| Observations V2 | `meaning.factual_observations[index]` : code/texte/preuves finies/placement ; les sources de contexte répétitions/récupérations sont les phases V2 |

La synthèse ne possède **pas** de champ `confidence`. Une classification V3 de faible confiance ne rend pas une observation mesurée V2 inutilisable. En revanche, un jugement catégoriel de répétitions doit toujours satisfaire `_approved_repetition_judgment`. L'écart-type seul ne devient pas un jugement de régularité.

V2 reste propriétaire de l'admission des mesures, de la comparabilité, de l'environnement et des priorités. Ses historiques descriptifs portent notamment la réserve `synthesis.history_descriptive` ; sa FC descriptive porte `synthesis.hr_observation`.

## Sélection avant/après

| Avant | Après |
|---|---|
| Synthèse V2 absente du contexte Narrative | Réponse V2 canonique du même chargement transmise par un argument interne, en génération normale et en fallback du service |
| Commentaire reconstruit autour de la classification ou du nombre de phases | `primary.text` entier en analyse ; observations complémentaires dans l'ordre choisi par V2 |
| Détails des répétitions écartés | Régularité autorisée, répétition atypique, comparaison des extrémités et FC descriptive conservées |
| Réserves V2 non transmises | Réserves V2 conservées, avec leurs références ; absence de réserve historique/FC requise → refus de cette synthèse |
| Phrase de méthode potentiellement principale | Phrase de méthode historique déplacée dans les limites |
| Catalogue pouvant fournir un conseil automatique | Pas de recommandation ajoutée dans le parcours synthèse |
| Décimales de certains textes V2 avec point | Formatage des seuls nombres d'affichage à leur production, FR/ES avec virgule, EN avec point ; aucune réécriture regex de la prose |

L'admission vérifie le type/version de la réponse, l'identité de séance, la disponibilité de la synthèse, les codes autorisés, les chemins sources, l'identité des preuves et le texte source autorisé. Le complément d'allure historique utilise le même petit formateur que la synthèse V2, extrait sans changer son comportement. Le contexte de durée conserve l'autorité V2, y compris sa tolérance existante sur les durées, sans imposer une nouvelle égalité stricte.

Sans synthèse admissible, le parcours V3 antérieur reste disponible, avec la correction de placement des phrases de méthode. La branche synthèse ne juxtapose pas à une comparaison V2 par distance une conclusion V3 de progression, de baisse ou d'intensité physiologique. Les évaluations de prescription existantes restent des limites, pas de nouveaux conseils.

Le format public Narrative est inchangé : `headline`, `analysis`, `interpretation`, `recommendation`, `limitations`, `evidence_refs`, `language`, `generation_mode`. Si V2 ne fournit pas de soutien, une FC globale disponible ou le nombre de phases fournit le contexte secondaire ; sinon une réserve descriptive existante complète `interpretation`.

La prose canonique est rendue localement et retourne avant l'éditeur LLM optionnel et son cache partagé. Aucun LLM n'est ajouté. Le chargement reste filtré par utilisateur, sans lecture supplémentaire, et aucun argument V2 n'est accepté depuis une requête publique.

## Avant/après déterministes

### Footing du 12/10/2026 — `garmin-24701222152`

Entrées fournies : 9,33 km, 7:21/km, 127 bpm, cinq références par distance, +25,3 s/km.

**Avant, analyse :**

> La classification est relative à l'historique personnel, pas à une zone physiologique.

**Après, analyse :**

> Par rapport à tes 5 sorties antérieures de distance comparable avec allure mesurée, sans garantie de même nature ni de même structure, ton allure moyenne est 25,3 s/km plus lente.

Interprétation : « Ta fréquence cardiaque moyenne sur cette séance était de 127 bpm. » Le titre « Probablement un footing facile » est conservé dans ce scénario. La réserve V2 reste explicite :

> Cet écart décrit ces séances ; il ne suffit pas à conclure à un changement de forme ni à juger l’exécution.

Les limites de zone physiologique sont conservées. Aucun split non sélectionné n'est repris, aucune baisse de forme n'est conclue.

### Fractionné du 10/10/2026 — `garmin-24671804067`

Allures arrondies : 4:48, 4:42, 4:31, 4:51/km.

**Avant, analyse :**

> Garmin a enregistré 4 phases d'effort et 4 phases de récupération.

L'interprétation ne conservait que le jugement de régularité et l'écart moyen de 6,6 s/km.

**Après, analyse complète :**

> Variations d'allure perceptibles sur tes 4 répétitions : écart moyen de 6,6 s/km par rapport à l'allure médiane. La répétition n° 3 se distingue à 4:31/km, 17,5 s/km plus rapide que l'allure centrale des autres répétitions. La première et la dernière restent proches (2,3 s/km d'écart). La FC moyenne passe de 151 à 159 bpm entre la première et la dernière.

Le contexte secondaire de cette fixture est « 4 × 3 min de récupération observées. » Sa provenance synthétique est rappelée plus haut. La réserve autorisée est conservée :

> Ces observations de FC ne suffisent pas à établir une dérive physiologique ni une efficacité cardiaque.

Aucune dérive, fatigue ou récupération insuffisante n'est inférée.

### Sortie longue du 13/09/2026 — `garmin-24346252881`

Entrées fournies : 21,27 km, 122 min, 5:43/km, 160 bpm, quatre références par distance, −70,7 s/km.

**Avant, analyse :**

> La classification est relative à l'historique personnel, pas à une zone physiologique.

**Après, analyse :**

> Par rapport à tes 4 sorties antérieures de distance comparable avec allure mesurée, sans garantie de même nature ni de même structure, ton allure moyenne est 70,7 s/km plus rapide.

Interprétation : « Ta fréquence cardiaque moyenne sur cette séance était de 160 bpm. » La réserve historique V2 citée pour le footing est également conservée. Le texte n'affirme ni progression, ni meilleure efficacité, ni intensité physiologique validée.

## Validation

**Backend : 968 tests réussis, sept avertissements de dépréciation**, sur le head code indiqué plus haut :

```bash
cd backend
python -m pytest \
  tests/test_narrative_c388.py tests/test_narrative_coach_v3.py \
  tests/test_coach_session_synthesis_c351.py tests/test_coach_language.py \
  tests/test_descriptive_history_c350.py tests/test_historical_comparability_c349b.py \
  tests/test_workout_intelligence_v3.py -q --tb=short
```

Exécution dans un environnement virtuel isolé après constat des dépendances de test absentes ; configuration xdist du dépôt conservée (`-n 2 --dist loadscope`).

Les tests vérifient l'égalité du texte sélectionné avec le texte V2 autorisé, ses preuves et ses réserves, pas seulement des mots-clés. Ils couvrent les trois scénarios FR/EN/ES, la non-mutation des chiffres, l'absence de synthèse/phases/historique, les données insuffisantes, une source indisponible, une mauvaise identité/version, un code/chemin/texte/preuve altéré, les réserves manquantes, un jugement non autorisé, plusieurs observations concurrentes, les splits non sélectionnés et les récupérations avec durées légèrement différentes déjà admises par V2.

Les tests du loader vérifient la réutilisation du même objet canonique sans lecture supplémentaire et l'isolation de deux utilisateurs ayant le même identifiant de séance. Les tests existants de fallback, d'API et de refus Premium passent également.

**Frontend : 319 tests réussis, deux suites**, sans modification de composant ni de contrat :

```bash
cd frontend
npm ci --legacy-peer-deps --no-audit --no-fund --quiet
CI=true npm test -- --watchAll=false --forceExit --runInBand \
  --runTestsByPath src/__tests__/analysis-format.test.js \
  src/__tests__/workout-analysis-v3-pages.test.jsx
```

Le composant existant affiche l'analyse/interprétation sans tronquer les phrases. Il montre la première limite, puis les autres dans les détails. Les contrôles de langue et de complétude ainsi que les règles d'accès restent inchangés. Les suites couvrent notamment les pages, les fallbacks et les accès. `git diff --check` passe.

## Fichiers et limites restantes

Fichiers de production : `backend/narrative_coach_v3.py`, `backend/workout_intelligence_v3_service.py`, `backend/coach_language.py` (affichage numérique seulement), `backend/coach_session_synthesis.py` (extraction du formateur existant).

Tests : nouveau `backend/tests/test_narrative_c388.py`, compléments dans `test_workout_intelligence_v3.py`, attentes décimales localisées dans `test_coach_language.py` et `test_coach_session_synthesis_c351.py`. Documentation : ce rapport.

Les calculs de `workout_analysis_v2.py`, Training V2, Garmin, le Coach conversationnel, les abonnements et le frontend ne sont pas modifiés. Les manifests de dépendances ne sont pas modifiés.

La sélection conserve les limites de V2 : pas de création d'observation absente, pas de recalcul des références historiques, pas de conclusion physiologique supplémentaire. La prose V2 entière peut être plus longue que l'ancien budget de six phrases ; c'est intentionnel pour ne pas supprimer son raisonnement. La synthèse canonique utilise toujours le mode public existant `deterministic_fallback`, même lorsque l'ancien éditeur optionnel est activé.

Le gate restant est la vérification authentifiée **en lecture seule** des trois réponses réelles dans Emergent et de leur affichage. Les fixtures ne le remplacent pas. Aucun résultat de production n'est revendiqué et aucune synchronisation n'a été effectuée.
