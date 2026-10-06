# RUNINDEX 15B — Coach Context correctness

## Références vérifiées

- PR #309 : mergée le 5 octobre 2026, vérification via l'API GitHub.
- Base cible : `copilot/dev`, `d830a26ab005bbdd4e7c4ed9f38a9efdd086bef3`.
- HEAD réel de départ : `d830a26ab005bbdd4e7c4ed9f38a9efdd086bef3`.
- Remote re-fetché avant modification, puis ref `copilot/dev` fetchée explicitement et comparée au HEAD local.
- Branche de travail : `copilot/15b-coach-context-correctness`.
- HEAD code/tests validé : `e14702b10c5205c4d420ef206fc132db48001906`.
- Ce rapport est ajouté après ce HEAD ; le commit documentaire ne modifie pas le code/tests validé. Le HEAD de livraison est fourni dans la description de PR.
- `copilot/dev` encore à la base ci-dessus lors de la dernière vérification remote.
- Aucun merge effectué ; une seule PR demandée vers `copilot/dev`.

## Fichiers modifiés

- `backend/coach_context_v2.py`
- `backend/tests/test_coach_context_v2.py`
- `RUNINDEX_PR15B_REPORT.md`

## 1. Projection des allures vers le LLM

**Cause racine :** la liste explicite des clés reconnues ne couvrait pas les variantes canoniques de Training V2. La récursion conservait donc ces clés et leurs valeurs décimales brutes.

**Avant :** des champs tels que `planned_pace_min_per_km: 5.25` ou `pace_delta_min_per_km: 0.2` pouvaient atteindre le payload LLM.

**Après :** les six variantes suivantes sont projetées récursivement, y compris dans les objets `canonical`, les steps et les listes :

| Clé source supprimée du payload LLM | Clé lisible |
| --- | --- |
| `pace_min_per_km` | `pace_display` |
| `pace_min_per_km_min` | `pace_min_display` |
| `pace_min_per_km_max` | `pace_max_display` |
| `planned_pace_min_per_km` | `planned_pace_display` |
| `actual_pace_min_per_km` | `actual_pace_display` |
| `pace_delta_min_per_km` | `pace_delta_display` |

Les allures absolues utilisent exclusivement `_format_pace_min_km` ; les deltas utilisent `_format_pace_delta_min_km`. Aucune nouvelle logique d'arrondi :

- `6.81` → `6:49/km`
- `5.25` → `5:15/km`
- `0.20` → `+0:12/km`
- `-0.012` → `-0:01/km`
- `±0.001` et delta nul → `0:00/km`

`None`, NaN, ±Infinity, booléen, texte invalide, dict ou liste invalides sont omis pour ces clés, sans valeur fabriquée. Les sources restent intactes et les autres champs sont conservés. Les tests sérialisent le contexte final avec `allow_nan=False`, contrôlent les noms sémantiques, l'absence des clés/valeurs brutes et capturent également le prompt réellement transmis à `_call_gpt` mocké.

## 2. Historique selected-workout / no-lookahead

**Cause racine :** toute activité candidate devait avoir un timestamp exact lorsque la sélection en avait un. Une activité date-only d'un jour strictement antérieur était donc rejetée.

**Avant :** selected `2026-09-28T10:00:00Z`, candidate `2026-09-26` → exclue à tort.

**Après :**

| Candidat, pour selected `2026-09-28T10:00:00Z` | Résultat |
| --- | --- |
| Date-only `2026-09-26` | Inclus |
| `2026-09-28T09:59:59Z` | Inclus |
| `2026-09-28T10:00:00Z` | Exclu |
| `2026-09-28T10:00:01Z` | Exclu |
| Date-only `2026-09-28` | Exclu : ordre intra-journée inconnu |
| `2026-09-29` | Exclu |
| Même ID, quelle que soit la date | Exclu |
| Date invalide | Exclu |

Quand un timestamp candidat existe, la comparaison exacte reste obligatoire, même si sa date locale paraît antérieure. Exemple testé : `2026-09-27T23:45:00-12:00` correspond à `2026-09-28T11:45:00Z` et reste exclu. Le fallback « jour antérieur » est réservé aux candidats sans timestamp exact.

Pour une sélection date-only, la doctrine existante `date_inclusive` reste inchangée : même jour inclus sauf même ID, lendemain exclu. Les tests couvrent les dicts et `CoachRecentWorkout`, les sources non mutées, les métadonnées de précision et l'historique assemblé par l'endpoint Coach.

## Tests réellement exécutés

Environnement : Python 3.12, venv isolé `/tmp/pr15b-venv`, dépendances nécessaires déjà utilisées par le projet installées sans modification des manifests. Les commandes utilisent le runner configuré `-n 2 --dist loadscope`.

Répertoire pour les commandes ci-dessous : `/home/runner/work/sauvegarde260708/sauvegarde260708/backend`.

| Commande | Résultat exact |
| --- | --- |
| `/tmp/pr15b-venv/bin/python -m pytest tests/test_coach_context_v2.py -k 'canonical_paces_final or is_before_selected_workout_date_precision' -q` avant correction de production | **3 failed, 34 passed**, 14 warnings : fuite des six clés canoniques et rejet J-2 reproduits |
| `/tmp/pr15b-venv/bin/python -m pytest tests/test_coach_context_v2.py -k 'pace or is_before_selected_workout or selected_workout_recent_history' -q` après correction finale | **97 passed**, 14 warnings |
| `/tmp/pr15b-venv/bin/python -m pytest tests/test_coach_context_v2.py tests/test_coach_contract_unified.py -q` après correction finale | **150 passed**, 14 warnings ; suites complètes Coach Context et contrat |
| `/tmp/pr15b-venv/bin/python -m pytest tests/test_coach_contract_unified.py -q` avant l'ajout des cas de fuseaux horaires | **27 passed**, 14 warnings |
| `/tmp/pr15b-venv/bin/python -m pytest tests/test_coach_contract_unified.py tests/test_pr211_coach_llm_cleanup.py -q` | **1 failed, 32 passed**, 14 warnings ; 27 contrat et 5 PR211 réussis |

Le premier essai avec `python -m pytest` système a échoué car pytest était absent. Après création du venv, un essai a rencontré `ModuleNotFoundError: redis` ; la dépendance existante a été installée avant les exécutions effectives ci-dessus.

### Échec adjacent préexistant

`test_server_coach_analyze_no_hr_speed_vma_exposure` attend littéralement `predict_races(` dans `analyze_with_coach`, qui délègue déjà à `process_coach_message`.

Reproduction sur la base **inchangée** `d830a26ab005bbdd4e7c4ed9f38a9efdd086bef3`, extraite avec `git archive`, par l'agent de validation :

`cd /tmp/pr15b-baseline/backend && PYTHONPATH=/tmp/pr15b-baseline/backend /tmp/pr15b-venv/bin/python -m pytest tests/test_pr211_coach_llm_cleanup.py::test_server_coach_analyze_no_hr_speed_vma_exposure -q`

Résultat : **1 failed**, même assertion `assert 'predict_races(' in fn_src`. Ce test et `server.py` restent inchangés ; cet échec ne relève pas des deux défauts 15B.

### Revue et sécurité

- `git diff --check` : réussi.
- Scans de secrets sur les fichiers Python : aucun secret détecté.
- `parallel_validation` exécuté avant et après le correctif de fuseaux horaires : **0 alerte Python CodeQL** aux deux passages.
- Le composant Code Review de cet outil était indisponible (binaire absent), malgré son statut global « Success » : ce n'est pas présenté comme une revue réellement exécutée.
- Revue read-only de substitution par agent `code-review` : risque de fuseaux horaires identifié au premier passage, corrigé et couvert par tests ; deuxième passage : **aucun problème significatif trouvé**.
- P0=0 / P1=0 identifié sur les deux défauts après correction et revue finale, avec les preuves de tests ci-dessus.

## Périmètre et limites

- **Coach Voice, prompts/personnalité/longueur des réponses, Training V2, Workout Analysis V2, Readiness, Dashboard, frontend, Garmin, subscription/auth et architecture RAG inchangés.**
- `llm_coach.py` et les règles métier/prescription sont inchangés.
- Training V2 reste l'autorité de prescription ; Workout Analysis V2 reste l'autorité déterministe d'analyse ; le LLM reste uniquement explicateur.
- Aucun test frontend, build frontend, suite backend globale ni validation live contre un LLM n'a été exécuté ou revendiqué.
- L'échec PR211 préexistant et les warnings de dépréciation restent hors périmètre.
- La projection reste une reconnaissance explicite des clés canoniques ; toute nouvelle variante future devra être couverte par des tests avant son exposition au LLM.
- PR laissée non mergée ; 15C non commencée.

## Correctif résiduel P2 — priorité à la chronologie UTC

- PR existante : **#310**, branche `copilot/15b-coach-context-correctness`, vérifiée **OPEN / DRAFT / non mergée** avant modification.
- HEAD réel de départ du correctif, local et remote après re-fetch : `ce5c80faec4a95e89c753f0045c1006d4a0cd813`.
- Base `copilot/dev` vérifiée : `d830a26ab005bbdd4e7c4ed9f38a9efdd086bef3`.
- Le HEAD de livraison du correctif est communiqué dans le commentaire de suivi et la réponse finale ; les résultats ci-dessous remplacent les comptes précédents pour le code corrigé.

**Cause du P2 :** le rejet `workout_date > selected_date` précédait encore la comparaison exacte. Un candidat portant une date locale du lendemain pouvait donc être rejeté alors que son instant UTC était antérieur à la sélection.

**Avant :** selected `2026-09-28T11:00:00Z`, candidate `2026-09-29T00:00:00+14:00` → exclu à tort.

**Après :** exclusion du même ID, rejet des dates invalides, puis priorité à la comparaison stricte des deux timestamps exacts. Le candidat `+14:00` correspond à `2026-09-28T10:00:00Z` et est donc inclus. Les timestamps égaux ou ultérieurs restent exclus, indépendamment de leur date locale.

Les candidats date-only restent autorisés uniquement sur un jour strictement antérieur lorsque la sélection est horodatée. Pour une sélection date-only, `workout_date <= selected_date` préserve exactement `date_inclusive`, sauf même ID.

**Nouveau test explicite :** `test_is_before_selected_workout_uses_utc_not_local_date` couvre les dicts et `CoachRecentWorkout`, avec selected à `11:00Z`, et vérifie la non-mutation :

- `2026-09-29T00:00:00+14:00` → `10:00Z` → **inclus**.
- `2026-09-27T23:45:00-12:00` → `11:45Z` → **exclu**.

Le test existant `-12:00` avec sélection à `10:00Z` est également conservé inchangé.

### Résultats réellement exécutés pour le P2

Depuis `/home/runner/work/sauvegarde260708/sauvegarde260708/backend`, avec le même runner pytest configuré (`-n 2 --dist loadscope`), après restauration du venv isolé et sans modification de dépendances du dépôt :

| Commande | Résultat exact |
| --- | --- |
| `/tmp/pr15b-venv/bin/python -m pytest tests/test_coach_context_v2.py -k 'uses_utc_not_local_date' -q` avant correction de production | **2 failed, 2 passed**, 14 warnings ; cas `+14:00` reproduit pour dict et modèle |
| `/tmp/pr15b-venv/bin/python -m pytest tests/test_coach_context_v2.py -k 'is_before_selected_workout or selected_workout_recent_history' -q` après correction | **49 passed**, 14 warnings |
| `/tmp/pr15b-venv/bin/python -m pytest tests/test_coach_context_v2.py tests/test_coach_contract_unified.py -q` après correction | **154 passed**, 14 warnings |

**Périmètre :** seuls `_is_before_selected_workout`, son nouveau test symétrique et ce rapport sont modifiés par le correctif P2. La projection des allures et tout le reste de #310 sont inchangés : `llm_coach.py`, Voice/prompts, Training V2, Workout Analysis V2, frontend, Dashboard/Readiness, Garmin, auth/subscription et autres règles métier. Aucune nouvelle PR ni merge ; 15C non commencée.

### Revalidation du correctif déjà livré — 5 octobre 2026

- Base exacte de #310 : `copilot/dev`, `d830a26ab005bbdd4e7c4ed9f38a9efdd086bef3`.
- HEAD code/tests revalidé : `b3259f6f78edb49e16f47bdb1b8f8cb85eb472c6`, déjà présent sur la branche distante au début de cette vérification.
- Le correctif et le test symétrique sont déjà présents à ce HEAD : aucune nouvelle modification du code ou des tests n'est nécessaire. Seul ce rapport est complété ; le reste de #310 est inchangé.
- Environnement recréé : Python 3.12.3, venv `/tmp/pr15b-venv`, sans modification des manifests ni de `pytest.ini` (`-n 2 --dist loadscope`).

Depuis `/home/runner/work/sauvegarde260708/sauvegarde260708/backend`, les deux commandes ont été relancées successivement avec le Python du venv :

| Commande | Résultat exact de cette revalidation |
| --- | --- |
| `/tmp/pr15b-venv/bin/python -m pytest tests/test_coach_context_v2.py -k "is_before_selected_workout or selected_workout_recent_history" -q` | **49 passed, 12 warnings in 1.40s** |
| `/tmp/pr15b-venv/bin/python -m pytest tests/test_coach_context_v2.py tests/test_coach_contract_unified.py -q` | **154 passed, 12 warnings in 1.83s** |

Les warnings concernent les dépréciations passlib/crypt, Pydantic et FastAPI. Les résultats historiques ci-dessus restent des preuves de leurs exécutions initiales, pas les résultats de cette revalidation.

PR #310 vérifiée OPEN / DRAFT / non mergée. Aucun merge, aucune nouvelle PR et aucun travail 15C. Le nouveau HEAD documentaire de livraison est communiqué dans le commentaire de suivi et la réponse finale.
