# RUNINDEX — Structured Phase Evidence Fix

## Références exactes

- Base cible : `copilot/dev`.
- SHA de base réel vérifié par `git ls-remote origin refs/heads/copilot/dev` avant modification : `535574fcf7431b2e6f522279e6fe3d54ddab6f6c`.
- Ce SHA contient le merge de la PR #326.
- HEAD du code testé et validé : `8523aab2d0aaf688dd8d5cad5b32db472ea31ef4`.
- Le commit contenant ce rapport est documentaire uniquement ; le HEAD final de livraison est indiqué dans la description de PR et la réponse de livraison, pour éviter une référence SHA autoréférentielle.
- Workspace audité : `/home/runner/work/sauvegarde260708/sauvegarde260708`.
- Une PR, un objectif ; aucun merge automatique, déploiement, accès aux activités réelles ou changement Mongo.

## Cause racine vérifiée

Dans `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_analysis_v2.py`, `_build_phase_analysis()` conserve toute liste non vide, y compris exclusivement `unknown`, avec `available=True`. Avant correction, `build_workout_analysis_v2()` recopiait directement ce booléen dans `evidence.has_structured_phases`. `_build_limitations()` pouvait donc sélectionner `limitations.phase_splits`, annonçant des phases structurées disponibles séparément sans aucune classification.

Les efforts/récupérations et leur régularité étaient déjà filtrés par type : la cause confirmée est la preuve, pas les calculs.

## Contrats et consommateurs audités avant modification

Recherche dans tous les fichiers Python/JS/JSX/TS/TSX du dépôt, puis lecture des consommateurs :

| Contrat | Consommateurs et invariant |
| --- | --- |
| `phase_analysis.available` | `_build_limitations()`, `_session_structure()`, `_phase_observations()` dans le moteur ; `WorkoutPhaseAnalysis` dans `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend/src/pages/WorkoutDetail.jsx:240-275` ; suites backend/frontend. Indique la présence de données de phases affichables, pas une preuve de classification. |
| `phase_analysis.phases` | Séquence observée dans `_session_structure()`, FC des phases dans `_phase_observations()` et construction d'evidence ; chronologie/frontend et lignes neutres `unknown` ; tests de conservation. |
| `evidence.has_structured_phases` | Choix de `limitations.phase_splits` dans `_build_limitations()` ; propagation du payload canonique et tests. Aucun consommateur frontend spécifique trouvé. |
| `signals.session_structure` | Construit par `_session_structure()` ; lu par `_phase_observations()` ; payload canonique et tests. Le code `other` conserve une catégorie observée sans établir une structure spécifique d'intervalles. |

Coach : `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/coach_context_v2.py:73-78,321-343,729-783` embarque `WorkoutAnalysisV2Response`, conserve l'analyse canonique et projette les allures pour le LLM sans reclassifier les phases. Les nouveaux tests vérifient preuve, types, signal et limitations dans cette projection.

Service : `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_analysis_v2_service.py:201-250,253-274` lit uniquement le cache normalisé validé et transmet les phases. Aucun changement apporté.

Normalisation : `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/activity_phases.py:12-33` définit un modèle gelé, les cinq types autorisés, `unknown` par défaut et les mesures optionnelles. Le chargeur valide l'ordre contigu, le type reconnu, la provenance et les mesures finies non négatives. `None` reste distinct de zéro. Ni modèle, schéma ni connecteur modifiés.

Les suites existantes auditées couvrent phases inconnues conservées, données manquantes/zéro, cache scoped, typage, structure continue, intervalles observés, Coach et rendu chronologique. Un test existant exige explicitement `available=True` pour une phase non classifiée inutilisable.

## Choix minimal et comportement avant/après

Option privilégiée retenue :

- **A — présence** : conserver `phase_analysis.available`, `analysis_type`, toutes les phases et mesures existantes.
- **B — preuve exploitable** : `evidence.has_structured_phases=True` uniquement si au moins un type appartient à `effort`, `recovery`, `warmup`, `cooldown`.
- **C — structure** : conserver intégralement `_session_structure()` ; intervalles uniquement avec récupération observée entre efforts. Aucune déduction depuis le titre.

| Phases synthétiques | `available` avant → après | Preuve avant → après | Structure inchangée | Limitations après, sans splits km |
| --- | --- | --- | --- | --- |
| Aucune | false → false | false → false | Indéterminée | `splits`, aucune fausse preuve |
| Une ou plusieurs `unknown` | true → true | true → false | Indéterminée | `splits` + `phase_classification` |
| Une phase classifiée | true → true | true → true | `other`, ou `continuous` si effort couvrant toute la séance | `phase_splits`, limites de mesures existantes |
| `unknown` + `effort` | true → true | true → true | `other` | `phase_splits` + `phase_classification_partial` |
| `unknown` + `recovery` | true → true | true → true | `other` | Idem, aucune régularité d'effort inventée |
| Effort + récupération | true → true | true → true | `other` | Pas d'intervalles inventés sur un seul effort |
| Effort + récupération + effort | true → true | true → true | `intervals` | Analyse existante conservée |
| Effort + `unknown` + effort | true → true | true → true | `other` | L'inconnue ne devient pas une récupération |

La structure continue explicitement renseignée sur une séance sans phases conserve également son contrat historique.

Les nouveaux textes `phase_classification` et `phase_classification_partial` sont localisés FR/EN/ES dans les limitations canoniques. Les phases inconnues restent affichables avec leur libellé frontend neutre existant. Les données manquantes et limites de qualité antérieures restent visibles ; les types inconnus ne sont jamais introduits dans les cohortes d'effort/récupération. La FC brute réellement disponible reste une observation, pas une classification.

## Tests exécutés et résultats exacts

Depuis `/home/runner/work/sauvegarde260708/sauvegarde260708/backend` :

```text
python -m pytest tests/test_workout_analysis_v2.py tests/test_workout_analysis_v2_phases.py tests/test_workout_analysis_v2_unified.py tests/test_coach_context_v2.py tests/test_activity_details_pr321.py -q
536 passed, 14 warnings in 2.82s
```

Configuration existante inchangée : `-n 2 --dist loadscope`. Tests HTTP via transports/faux DB des suites existantes, sans service Mongo réel ni activité réelle. Les 14 avertissements concernent les dépréciations préexistantes multipart, crypt, Pydantic Config et FastAPI on_event.

**49 nouveaux cas synthétiques** : matrice de 14 scénarios × FR/EN/ES (42), conservation des observations classifiées avec phase inconnue et données manquantes (1), localisation complète/partielle × FR/EN/ES (6). Couverture : absence, unknown unique/multiple même avec mesures valides, chaque type classifié, mélanges effort/récupération, séquence complète, intervalles/structure indéterminée, cohérence evidence/limitations, aucune fausse régularité, conservation brute et propagation Coach/LLM.

Depuis `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend` :

```text
npm ci --legacy-peer-deps --no-audit --no-fund
CI=true npx craco test --watchAll=false --forceExit --runInBand src/__tests__/workout-analysis-v2-pages.test.jsx
Test Suites: 1 passed, 1 total
Tests: 250 passed, 250 total
Snapshots: 0 total
Time: 10.474 s
```

Suite existante non modifiée : rendu 4 efforts/récupérations, phases inconnues neutres et chronologiques, absence de fausses associations, métriques manquantes, limites localisées et payload absent/legacy. Aucune modification frontend, aucune nouvelle suite frontend : compatibilité validée par contrat préservé et tests existants. Avertissements existants : fallback URL backend, React/testing et sortie forcée Jest.

Vérifications supplémentaires réussies :

- `python -m flake8 workout_analysis_v2.py tests/test_workout_analysis_v2_unified.py --select E9,F63,F7,F82` : aucune erreur de syntaxe/nom ciblée ; pas une validation exhaustive du style.
- `python -m compileall -q workout_analysis_v2.py tests/test_workout_analysis_v2_unified.py` : succès.
- `git diff --check` : succès.
- Exécution différentielle en mémoire du moteur de base contre HEAD : matrice avant/après vérifiée ; payload JSON **complet** de la fixture synthétique 4 × 4 identique en FR, EN et ES.

Premières tentatives backend : `159 passed, 2 errors` (httpx absent), puis `159 passed, 4 warnings, 2 errors` (redis absent). Après restauration des dépendances de test, les cinq suites passent intégralement ; ces erreurs étaient des imports d'environnement, pas des assertions échouées.

Environnement uniquement : installation des dépendances existantes nécessaires. L'advisory check a signalé les versions épinglées PyMongo/PyJWT ; des versions corrigées `pymongo==4.18.3`, `PyJWT==2.15.1`, et `motor==3.7.1` compatible ont été utilisées localement. Aucun manifeste/lockfile modifié ; ces versions de test diffèrent donc des pins de déploiement.

## Compatibilité 4 × 4 minutes

Fixture exclusivement synthétique : quatre efforts de 240 s, récupérations de 180 s. Structure `intervals`, moyenne des allures `283.0313 s/km`, dispersion `7.6870 s/km`, variation FC moyenne `+8 bpm`, messages FR/EN/ES et limites identiques à la base. L'ajout d'une phase inconnue conserve également statistiques, régularité, résumé, sens et conseil classifiés.

## Validation et risques résiduels

- Secret scanning des deux fichiers Python modifiés : aucune détection.
- `parallel_validation` : CodeQL Python, **0 alerte**.
- La revue intégrée n'a pas réellement pu s'exécuter (modèle demandé absent du registre), malgré un statut agrégé « Success ». Revue read-only de remplacement par agent `code-review` : **aucun problème significatif trouvé**.
- Le sens historique de `available` et le titre frontend existant du bloc de phases restent inchangés pour conserver les données brutes. La preuve canonique et les limitations, et non ce booléen de présence, font autorité sur la classification. Pas d'amélioration UX #327 incluse.
- `other` reste une catégorie historique, sans promesse de structure spécifique ; règle des intervalles inchangée.
- Les vulnérabilités des pins de dépendances préexistants sont hors objectif de cette PR ; aucune correction de manifeste opportuniste. Les tests ne constituent pas une certification de ces pins.
- Pas de build frontend complet : frontend inchangé ; suite de rendu pertinente exécutée.
- Attendre la revue technique du propriétaire avant tout merge.

## Justification de chaque fichier modifié

1. `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/workout_analysis_v2.py` : découpler la preuve classifiée de la présence brute, ajouter des limitations canoniques FR/EN/ES et expliciter le contrat de présence. Aucun calcul ou autre moteur changé.
2. `/home/runner/work/sauvegarde260708/sauvegarde260708/backend/tests/test_workout_analysis_v2_unified.py` : 49 cas synthétiques ciblés, cohérence des contrats, projection Coach et non-régression des observations.
3. `/home/runner/work/sauvegarde260708/sauvegarde260708/RUNINDEX_STRUCTURED_PHASE_EVIDENCE_FIX_REPORT.md` : rapport demandé, preuve de l'audit différentiel, tests exacts et limites.
