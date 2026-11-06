# RUNINDEX C403 — Audit et correctif post-merge C402

Instantané de preuve, pas une source de vérité courante.

## 1. SHA de départ

- Branche : `copilot/dev`, SHA `52c3fd3` (= `origin/copilot/dev`), `git status` propre.
- Version du commentaire : `c402-session-comment-v3` → `c403-session-comment-v4` (invalide le cache).

## 2. Verdicts (reproduits sur le HEAD 52c3fd3, sans modifier le code de production)

| # | Fichier / fonction | Entrée minimale | Observé | Attendu | Verdict | Gravité | Correction |
|---|---|---|---|---|---|---|---|
| A1 | `coach_context_v2._is_before_selected_workout` (par conception `date_inclusive`) ; `coach_session_comment.build_comment_context` | séance date seule 2026-01-10 ; historique 2026-01-10T18:00 et 2026-01-10 ; ou horodaté 07:30 avec séance 09:00 | les séances du même jour (et postérieures) étaient présentées comme « antérieures » | exclues sauf antériorité prouvée | **BUG CONFIRMÉ** | Haute | `_provably_prior` dans la sélection C402. Le contexte partagé est inchangé (ses tests encodent `date_inclusive`) |
| A2 | `build_comment_context` (`avg_km_per_session`) | 4 séances dont 2 sans distance | la division par `len(prior)` n'existe plus (`len(kms)`) ; mais portée implicite : `sessions_count=4`, moyenne sur 2 ; une seule distance connue suffisait | dénominateur explicite, pas de zéro implicite | **DÉJÀ CORRIGÉ** (arithmétique) + **défaut de contrat confirmé** (portée) | Moyenne | `sessions_with_distance_count` (présent seulement si ≠ `sessions_count`) ; total/moyenne seulement si ≥ 3 distances connues |
| A3 | `_GOAL_TERMS` | MARATHON × « demi-marathon », « media maratón » ; ULTRA × « ultra marathon » ; SEMI × « media maratón » | « demi-marathon » accepté pour MARATHON ; « media maratón » refusé pour SEMI ; « ultra marathon » (espace) refusé pour ULTRA | noms composés rattachés au bon objectif | **BUG CONFIRMÉ** (variantes FR/ES/espace) ; « ultramarathon » / « ultra-marathon » / 5K / 10K / HALF_MARATHON : **FAUX POSITIF** | Moyenne | `_GOAL_COMPOUND` replie les composés avant détection |
| A4 | `_PRESCRIPTION` | « Mañana descansa… » ; « Esta mañana corriste… » ; FR « ce matin » ; « demain » | ES « mañana » = demain non détecté ; « matin/morning/esta mañana » jamais rejetés | prescription ES rejetée, matin descriptif accepté | **BUG CONFIRMÉ (ES seulement)** ; FR/EN **FAUX POSITIF** | Moyenne | `mañana` nu = demain (lookbehind esta/la/una/cada…) |
| A5 | `_significant_gaps`, `_build_pools`, `_project_paces_for_llm` | écart réel projeté : `pace_difference_display: "-0:18/km"` | seuil lisait `pace_difference_sec…` (absent en prod) : écart d'allure jamais détecté ; `pace_difference_min_km=-0.3` comparé à 10 (unité) ; `delta` mélangeait min/km et s/km (0,3 min/km acceptait « 0,3 s/km », refusait « 18 s/km ») ; seuil 10 % global | seuil 10 s/km sur l'allure, 10 % sur les autres métriques | **BUG CONFIRMÉ** (la fixture de test synthétique masquait le défaut) | Haute | `_material_gaps` par métrique (affichage, `_sec_per_km`, `_min_km`→×60, signé→valeur absolue) ; pools en secondes |
| A6 | `_ENDURANCE`, `_NO_PROGRESS_CLAIM`, `_PROGRESS` | EN « do not show an improvement in endurance », ES « no demuestran una mejora de la resistencia », FR « n'a pas montré de progression » | rejetés à tort. Inversement, ES « progreso/progresado » et FR « une endurance meilleure » n'étaient pas détectés | abstentions acceptées, affirmations refusées | **BUG CONFIRMÉ** (dans les deux sens) | Moyenne | `_only_negated` (indice précis dans la même proposition, ≤ 6 mots) ; `progr[eè]s` ; `_ENDURANCE` adjectif/copule optionnelle |
| A7 | `_significant_gaps` + `minimized_gap` | écart d'allure 18 s/km, distance +2 % : « distance slightly longer than similar sessions » | rejeté (écart global) ; avec l'écart d'allure invisible en prod (A5), minimisation non détectée | minimiseur rattaché à la métrique de sa proposition | **BUG CONFIRMÉ** | Moyenne | `_minimized_material_gap` (découpe en propositions, métrique du segment ; sans métrique identifiable → conservateur) |
| A8 | `_GOAL_PAST`, `_NO_PROGRESS_CLAIM` | « You were already training for the marathon on that day » ; « relevant… does not show how you are progressing » | intention passée acceptée ; pertinence générale + abstention refusée | pertinence générale OK, intention passée / efficacité refusées | **BUG CONFIRMÉ** (2 cas) ; « conçue pour », « perfect for », « paying off » : déjà rejetés | Moyenne | `_GOAL_PAST` (imparfait/« that day »/« déjà »…), cue de non-affirmation élargi |
| A9 | `validate_session_comment` (`wording_ok = comparison_ok or history_ok`) | permission C388 fausse, historique présent : « faster than your similar sessions » / « faster than usual » | acceptés | refusés sans permission | **BUG CONFIRMÉ** | Haute | « séances similaires » (`_SIMILAR_BASELINE`) exige toujours la permission ; une comparaison doit s'appuyer sur une valeur historique citée |
| A10 | `_check_numbers`, date guard | « On 8 January you ran 8 km at 6:00 per km, earlier session » | toute date historique → `ungrounded_date` ; valeurs historiques sans vocabulaire comparatif → `comparison_value_as_session` | faits vérifiables acceptés, attribution fausse rejetée | **BUG CONFIRMÉ** | Haute | `_HISTORY_REF` (cadre historique sans comparer), dates rattachées à leur séance (`owner["date"]`) |

Date ambiguë : mois seul (« In January ») non traité comme une date (accepté, sans valeur) ; deux séances le même jour sont départagées par leurs valeurs (test). **RISQUE NON DÉMONTRÉ** pour d'autres formats (« 8/1 »).

## 3. Interactions traitées

- A10 ouvre les dates historiques : sans garde, les valeurs de la séance sélectionnée pouvaient être attribuées à une date antérieure. Règle : une phrase ancrée sur une date historique et sans comparaison exige que *toutes* ses valeurs appartiennent à cette séance (`history_misattribution`).
- A9 retire « séances similaires/comparables » de `_COMPARISON` (`_SIMILAR_BASELINE`) ; `minimized_gap` l'inclut toujours (régression détectée par les tests C403 puis corrigée).
- A6 : lever le rejet « accidentel » d'une phrase négative exposait « …mais une endurance meilleure » ; `_ENDURANCE` complété.
- A1 réduit `prior` avant A2 (compte et moyenne sur les séances prouvées).

## 4. Fichiers modifiés

- `backend/coach_session_comment.py`
- `backend/tests/test_coach_c403_session_comment.py` (nouveau, 81 cas)
- `backend/tests/test_coach_c402_session_comment.py` : **un** test modifié, `test_history_date_is_not_matched_so_no_correspondence_is_invented`. Il encodait « toute date historique rejetée », contraire à A10 ; il utilise maintenant une date ne correspondant à aucune séance (« 9 January »), toujours rejetée. Aucun autre test C400/C402 modifié.
- `docs/reports/RUNINDEX_C403_REPORT.md`

Non modifiés : `server.py`, `llm_coach.py`, `coach_context_v2.py`, C388, Training V2, `SYSTEM_PROMPT_COACH`, contrats API, dépendances, migrations.

## 5. Tests (environnement : venv hors dépôt, dépendances de `requirements.txt` sauf `emergentintegrations`/`litellm` non installables hors réseau privé)

Commande : `python -m pytest tests/test_coach_c400_session_comment.py tests/test_coach_c402_session_comment.py tests/test_coach_c403_session_comment.py tests/test_coach_context_v2.py tests/test_narrative_c388.py tests/test_narrative_coach_v3.py tests/test_llm_coach_voice.py`

| | Avant (52c3fd3) | Après |
|---|---|---|
| C400+C402+Context V2+C388+Narrative V3+voix C396 | 559 passés, 0 échec | 640 passés, 0 échec |
| C403 sur le code de production d'origine | 46 échecs / 35 passés (les contre-exemples légitimes) | 81 passés |

FR/EN/ES, isolation utilisateur, cache, timeout et fallback : couverts par les tests C400/C402 existants, verts avant et après. Suite backend complète **non exécutée** (dépendances privées absentes) : pas d'affirmation de suite complète verte.

## 6. Régressions et limites résiduelles

- Comparaison directe avec une séance antérieure exacte (« plus rapide que votre sortie de 8 km à 6:00 ») reste acceptée sans permission C388 : c'est le comportement testé de C402 ; seules les comparaisons de base (similaires, « d'habitude » sans chiffre cité) sont fermées. **Arbitrage humain recommandé.**
- Phrase mixte ancrée sur une date historique sans comparaison (« Le 8 janvier 8 km, avant les 10 km d'aujourd'hui ») : rejetée (conservateur).
- « Votre sortie précédente a fait 10 km » (valeur de la séance sélectionnée attribuée à une séance non datée) n'est pas détectée : préexistant, non corrigeable sans heuristique fragile.
- « Useful/utile » reste refusé (efficacité) ; « relevant/pertinent » accepté.
- Garde heuristique par regex : ne prouve pas la véracité.

## 7. État fallback / flag / voix / Training V2

- Fallback C388 : inchangé (tests verts) ; tout rejet continue d'y mener.
- `C400_SESSION_COMMENT_ENABLED` : **OFF** (défaut, non modifié).
- C396 (voix, `SYSTEM_PROMPT_COACH`) et Training V2 : non touchés.

## 8. Recommandation

**GO pour merge** du correctif déterministe, sous réserve de revue humaine des limites ci-dessus.

Conditions avant activation de C400 :
1. Évaluation sur les cinq séances réelles de référence.
2. Arbitrage sur la comparaison directe de séance antérieure.
3. Validation runtime LLM (taux de fallback, latence).

## 9. Niveaux de validation

- **VALIDATION DÉTERMINISTE** : tests synthétiques ci-dessus (aucun LLM).
- **VALIDATION RUNTIME LLM** : **non réalisée**. Les tests mockés ne prouvent pas la fiabilité réelle.
- **VALIDATION HUMAINE** : **non réalisée**.
