# C354 — Garmin Historical Phase Normalization

- Base : `copilot/dev` @ `ad5cce7cbfa6b8502054a68115832e97e3d49771` (merge PR #353)
- Head code : `1d7499420d46241dbe014fffc38417a13ba209f7` (le commit de ce rapport le suit sur la même branche `copilot/c354-garmin-historical-phase-normalization`)
- Périmètre : backend uniquement, lecture seule. Aucun appel Garmin/GCCLI, aucune synchronisation, migration ou écriture MongoDB, aucun changement frontend, modèle physiologique, tendances, moteur C352 ou prescription.

## 1. Cause racine

PR #353 a corrigé `INTERVAL_REST → recovery` **à l'import** (`normalize_typed_splits`).
Les phases déjà persistées avant #353 gardent `phase_type: "unknown"`.
`_cached_activity_phases` (`backend/workout_analysis_v2_service.py`) validait le
`phase_type` persisté puis le transmettait tel quel à V2 sans le recalculer à partir de
`native_type`. V2 ne voyait donc aucune `recovery` entre les efforts → structure `other`,
et V3 (qui lit la structure V2) ne pouvait pas classer en `intervals`.

## 2. Fichiers modifiés

| Fichier | Changement |
|---|---|
| `backend/activity_phases.py` | Ajout de `GARMIN_NATIVE_PHASE_TYPES` et `garmin_native_phase_type()` (mapping partagé). |
| `backend/garmin/data_layer.py` | `normalize_typed_splits` utilise le mapping partagé (dictionnaire local supprimé, comportement identique). |
| `backend/workout_analysis_v2_service.py` | `_cached_activity_phases` recalcule `phase_type` depuis `native_type` quand celui-ci est connu. |
| `backend/tests/test_workout_analysis_v2_phases.py` | Tests C354 (lecteur cache + loader V2). |
| `backend/tests/test_workout_intelligence_v3.py` | Test C354 chaîne cache → V2 → V3 via le loader V3 réel. |

## 3. Architecture du mapping partagé

`activity_phases.py` est le module provider-neutral déjà importé par
`garmin/data_layer.py` **et** `workout_analysis_v2_service.py` ; y placer le mapping
n'ajoute aucune nouvelle arête d'import (pas de dépendance circulaire,
`workout_analysis_v2_service` n'importe pas `garmin.data_layer`).

| Type Garmin | Type normalisé |
|---|---|
| `INTERVAL_ACTIVE` | `effort` |
| `INTERVAL_RECOVERY` | `recovery` |
| `INTERVAL_REST` | `recovery` |
| `INTERVAL_WARMUP` | `warmup` |
| `INTERVAL_COOLDOWN` | `cooldown` |

`garmin_native_phase_type(x)` renvoie le type canonique ou `None` (type absent, non-str ou
inconnu ; correspondance exacte, sensible à la casse). L'import conserve `or "unknown"`.

## 4. Comportement avant / après (`_cached_activity_phases`)

| Cas | Avant | Après |
|---|---|---|
| `INTERVAL_REST` persisté `unknown` (pré-#353) | `unknown` | `recovery` |
| Phase connue déjà correcte (post-#353) | inchangée | inchangée |
| `native_type` absent | `phase_type` persisté | identique |
| `native_type` inconnu | `phase_type` persisté | identique (jamais promu en effort/recovery) |
| `phase_type` persisté hors liste autorisée | rejet (`None`) | rejet (`None`) — validations existantes conservées |

Seul `phase_type` est substitué, sur une **copie** du dict ; durée, distance, vitesse, FC,
ordre, source et `native_type` ne sont pas touchés. Le document MongoDB n'est jamais réécrit.
Aucun critère de date d'import.

## 5. Résultats des tests

Commande (depuis `backend/`, un fichier par processus — l'exécution groupée échoue à la
collecte de `test_workout_analysis_v2.py` car un autre module de test stub `motor`, problème
d'isolation préexistant indépendant de C354) : `python -m pytest <fichier> -q`.

| Suite | Base `ad5cce7` | C354 |
|---|---|---|
| `test_garmin_data_layer.py` | 13 passed | 13 passed |
| `test_garmin_phased_sync_pr07a.py` | 12 passed | 12 passed |
| `test_workout_analysis_v2.py` | 171 passed, **3 failed** | 171 passed, **3 failed** (identiques) |
| `test_workout_analysis_v2_facts.py` | 145 passed | 145 passed |
| `test_workout_analysis_v2_phases.py` | 74 passed | 108 passed (+34 C354) |
| `test_workout_analysis_v2_unified.py` | 85 passed | 85 passed |
| `test_workout_intelligence_v3.py` | 89 passed | 90 passed (+1 C354) |

Autres suites consommant les phases (C354) : `test_activity_details_pr321` 90,
`test_typed_splits_chronology_c321` 17, `test_continuous_structure_c350` 49,
`test_descriptive_history_c350` 46, `test_historical_comparability_c349b` 73,
`test_coach_repetition_judgment` 81, `test_coach_session_synthesis_c351` 87,
`test_coach_language` 331, `test_workout_presentation_pr328` 82 — tous passed.

Les 3 échecs V2 sont les échecs préexistants documentés
(`test_comparable_history_stays_separate_and_metrics_are_unchanged[en|fr|es]`,
`meaning.hr_w…y_with_pacing` ≠ `meaning.consistent_pacing`) ; présents à l'identique sur la
base. **Aucun nouvel échec.**

Contrôle négatif : en retirant uniquement la correction de `_cached_activity_phases`,
3 tests C354 échouent (récupérations = 0).

Tests C354 :
1. `INTERVAL_REST`/`unknown`/180 s → `recovery`/180 s, document source intact.
2. Les 5 types connus déjà corrects restent strictement identiques (toutes mesures comprises).
3. `native_type` ∈ {absent, `INTERVAL_OTHER`, `interval_rest`, `RUN`, `""`} × 5 `phase_type` persistés → `phase_type` conservé.
4. Chaîne synthétique « 19 septembre » (1 warmup, 6 `INTERVAL_ACTIVE`, 5 `INTERVAL_REST` persistés `unknown`) via `_cached_activity_phases`, `load_scoped_workout_analysis_v2` et `load_scoped_workout_intelligence_v3` : 12 phases, ordre et durées inchangés, 6 efforts, 5 récupérations, structure V2 `intervals`, classification V3 `intervals`, confiance `medium`, diagnostic `diagnosis.intervals`.
   - Confiance `medium` et non `high` : les phases synthétiques n'ont pas d'allure, donc `effort_regularity_available = false` (règle existante de `classify_session`). Rien n'est forcé.

## 6. Validation réelle — séance du 19/09/2026

**Non mesurée dans cet environnement.** Le sandbox d'exécution de cette PR n'a ni accès à
la base MongoDB de production ni identifiants de connexion ; aucune valeur n'a donc été
lue et **aucune valeur n'est inventée** ci-dessous.

| Indicateur | Avant C354 (constaté, contexte PR) | Après C354 |
|---|---|---|
| Phases totales | 12 | non mesuré |
| Efforts | 6 | non mesuré |
| Récupérations | 0 | non mesuré (attendu : 5 d'après les `native_type` stockés) |
| Structure V2 | other | non mesuré (attendu : `intervals`) |
| Classification V3 | unknown | non mesuré (attendu : `intervals`) |
| Confiance | none | non mesuré (`high` si ≥ 2 efforts comparables ont une allure valide, sinon `medium`) |
| Diagnostic Coach | insuffisant | non mesuré (attendu : `diagnosis.intervals`) |

Raisonnement déterministe : avec la composition stockée (warmup, puis efforts séparés par
des `INTERVAL_REST`), V2 `_session_structure` renvoie `intervals` dès qu'une `recovery`
sépare deux efforts, et V3 `classify_session` renvoie `intervals` si
`structure == "intervals"`, `effort_count ≥ 2` et `recovery_count ≥ 1`. Si la mesure réelle
restait `unknown`, la condition bloquante à vérifier est le rejet complet du cache par
`_cached_activity_phases` (`schema_version`, `status`, `source`, `endpoint`, `order`,
`source` par phase ou mesure invalide), qui fait retomber V2 sans phases.

Procédure à exécuter par l'opérateur, lecture seule : appeler
`GET /api/coach/workout-analysis/{workout_id}` et `GET /api/coach/workout-intelligence/{workout_id}` pour la séance du 19/09/2026 après
déploiement, ou exécuter en local `_cached_activity_phases(doc)` sur le document
`garmin_activities` (requête `find_one` uniquement), puis reporter les valeurs ci-dessus.

## 7. Risques et limites

- La substitution s'applique à toute phase dont le `native_type` est connu, y compris si le
  `phase_type` persisté diverge pour une autre raison : `native_type` est volontairement la
  référence pour les types connus.
- Validation réelle non effectuée (cf. §6).
- Les documents MongoDB restent avec `unknown` ; tout consommateur lisant les phases sans
  passer par `_cached_activity_phases` verrait encore l'ancienne valeur (aucun identifié dans
  le backend : V2 et V3 passent par ce lecteur).
- Isolation de tests préexistante (`motor` stubbé) : exécuter les suites fichier par fichier.

## 8. Verdict

**GO conditionnel** — correction et non-régression validées par tests (aucun nouvel échec,
contrôle négatif OK). Condition : mesurer la séance réelle du 19/09/2026 en lecture seule
(§6) avant de considérer l'objectif « 5 récupérations historiques reconnues » vérifié en
production.
