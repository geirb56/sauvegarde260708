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

## Arbitrage des comparaisons historiques directes

**Base :** PR #390 inchangée (HEAD précédent `6b93946`), `copilot/dev` = `52c3fd3`.

**Règle métier retenue.** Une comparaison descriptive exacte avec une séance antérieure identifiable est autorisée sans permission C388 `similar_comparison_available`, si : les deux séances existent, les valeurs et unités sont exactes, la séance historique précède prouvablement la séance analysée (C403/A1), l'attribution est vérifiable, et aucune conclusion (progression, efficacité, causalité, physiologie) n'est ajoutée. Les comparaisons statistiques (« que d'habitude », « séances similaires ») restent soumises à la permission C388.

**Comportement initial (code `6b93946`, sonde non committée) :**

| Cas | Résultat observé |
|---|---|
| A. exemple FR « …10 km à 5:32/km, contre 8 km à 6:00/km lors de ta sortie du 8 janvier » | **rejeté** (`history_misattribution`) : « contre » n'était pas reconnu comme vocabulaire comparatif → écart à la règle |
| A. équivalent ES « frente a » | **rejeté** (même cause) → écart |
| A. EN « compares with » | accepté |
| B. valeur attribuée à la mauvaise séance | rejeté |
| C. séance postérieure / D. même jour d'ordre inconnu | rejeté |
| E. même jour, antériorité prouvée | accepté |
| F, G. « plus vite que d'habitude », « séances similaires » (FR/EN/ES) | rejeté (`comparison_not_available`) |
| H. + progression, J. + physiologie | rejeté |
| I. + efficacité (« plus efficace à FC égale ») | rejeté |
| I. + « ton entraînement fonctionne / training works » (FR/EN/ES) | **accepté** → écart (`_EFFECTIVENESS` ne couvrait pas cette formulation) |
| K. permission C388 | accepté (préservé) |
| L. historique insuffisant | rejeté, aucune séance inventée |

**Corrections (`backend/coach_session_comment.py`, 2 regex existantes étendues, pas de nouveau mécanisme) :**
- `_COMPARISON` : ajout de `contre` et `frente a` (juxtaposition descriptive FR/ES). L'autorisation sans permission reste conditionnée à une valeur historique exacte et correctement attribuée (`_check_numbers` → `history_misattribution` sinon).
- `_EFFECTIVENESS` : ajout de « training/plan/entraînement/entrenamiento … works/fonctionne/marche/funciona ».

**Tests :** `tests/test_coach_c403_session_comment.py` + 22 cas (A–L, FR/EN/ES). Avant : 640 passés. Après : **662 passés, 0 échec** (C400, C402, C403, Context V2, C388, Narrative V3, voix C396). Aucune assertion existante modifiée. Cache, timeout, fallback et isolation utilisateur sont couverts par les suites C400/C402 incluses.

**Limites résiduelles :** « contre » / « frente a » comptent comme vocabulaire comparatif, donc exigent une valeur historique exacte pour être acceptés ; l'attribution à une séance *non datée* (« ta sortie précédente ») reste heuristique ; la suite backend complète n'a pas été exécutée (dépendances privées indisponibles).

**Niveaux de validation :** *déterministe* — tests ci-dessus (synthétiques) ; *runtime LLM* — non réalisée ; *humaine* — non réalisée. Le succès des tests ne prouve pas la qualité réelle des commentaires IA. C400 reste OFF ; C388, C396, Training V2 non modifiés.

## Revue Copilot de la PR #390 — sept alertes

**Base :** `copilot/dev` = `52c3fd3`. HEAD PR avant ce tour : `2382833`. Les sept alertes ont été reproduites sur ce code (sonde non committée) puis corrigées dans `backend/coach_session_comment.py` uniquement.

| # | Fonction | Reproduction (avant) | Après | Verdict |
|---|---|---|---|---|
| 1 | `_provably_prior` | sélection `2026-01-10T23:00:00Z`, historique `2026-01-11T00:30:00+02:00` (= 22:30Z) : exclu | conservé ; instants normalisés comparés d'abord, date calendaire seulement en repli ; naïf = UTC (convention de `_parse_exact_datetime`), jamais de comparaison naïf/aware ; postérieurs toujours exclus | BUG CONFIRMÉ, corrigé |
| 2 | `_build_pools` | `sessions_with_distance_count` rangé dans la métrique « distance » (`km`/`m`) avant la branche compteur | les clés `*count*` vont uniquement dans le pool `count` | BUG CONFIRMÉ (code), corrigé ; l'acceptation de « 3 km » n'a pas pu être reproduite telle quelle sur une phrase valide (rejet masqué par d'autres motifs) mais le classement fautif est démontré par le pool |
| 3 | `_GOAL_PAST` | « You were running at 5:32 per km over 10 km, … your current marathon goal » → `goal_history_claim` | accepté ; les marqueurs faibles (`were/was …ing`, `already`, `that day`, `déjà`, `ese día`…) ne comptent que dans la proposition qui nomme l'objectif ; les verbes d'intention (`were preparing/training/targeting…`, `préparais`, `preparabas`) et « at the time/à l'époque » restent rejetés partout | BUG CONFIRMÉ (EN ; FR/ES déjà acceptés), corrigé |
| 4 | `_NON_CLAIM_CUE`, `_NO_PROGRESS_CLAIM` | « We cannot deny that your endurance improved… » **accepté** ; aussi « We cannot deny your progress », et toute phrase contenant « We cannot determine… but you have progressed » (FR/EN/ES) via l'exemption `abstention` | « cannot/does not » ne vaut non-affirmation que suivi d'un verbe de preuve/inférence (show, demonstrate, prove, establish, indicate, confirm, support, conclude, determine, tell, say, assess, know ; `fail to`, `hesitate` exclus) ; équivalents FR/ES explicites ; `_NO_PROGRESS_CLAIM` supprimé et l'exemption `abstention` retirée du contrôle de progression : seul `_only_negated` décide | BUG CONFIRMÉ (+ interaction non signalée : abstention sur un autre sujet), corrigé |
| 5 | `_check_numbers` | « On 8 January you ran 10 km at 5:32 per km, compared with similar sessions » **accepté** (permission C388 vraie) | dans le segment (coupé aux mots de comparaison et aux propositions) qui porte la date, toute valeur doit appartenir à la séance datée ; l'autre côté de la comparaison peut citer la séance analysée ; deux dates dans un segment = ambigu, rejeté | BUG CONFIRMÉ, corrigé |
| 6 | `_check_numbers` (retour) | « Your run was faster than usual, and your previous run was on 8 January » **accepté** sans permission | les dates sont séparées des mesures (`date_hits`) ; seule une mesure historique ancre une comparaison | BUG CONFIRMÉ, corrigé |
| 7 | `_minimized_material_gap` | « The distance was slightly longer than similar sessions » rejeté (distance +2 %, durée +20 %) ; idem FR/ES | un nom de métrique explicite l'emporte ; « longer/plus long/más largo » seuls restent ambigus (distance ∪ durée) donc conservateurs | BUG CONFIRMÉ, corrigé |

**Refactor sans changement de comportement :** les boucles de chiffres de `_check_numbers` sont extraites dans `_figure_checks()` pour que la vérification par segment (alerte 5) réutilise exactement les mêmes contrôles de provenance ; `_segments()` est nouveau.

**Tests.** `tests/test_coach_c403_session_comment.py` : +72 cas (fuseaux, naïf/aware, compteurs, FR/EN/ES, négations, segments, dates seules, métriques distance/durée/allure/FC). Sur le code précédent, 15 de ces tests échouent (un par défaut au moins) ; les autres sont des contre-exemples légitimes qui passent avant et après. Aucune assertion existante modifiée.

| Suites (C400, C402, C403, Context V2, C388, Narrative V3, voix C396) | Avant (`2382833`) | Après |
|---|---|---|
| Passés / échecs | 662 / 0 | **713 / 0** |

Cache, timeout, fallback et isolation utilisateur sont couverts par les suites C400/C402 incluses. Suite backend complète non exécutée (`emergentintegrations` et `litellm` indisponibles) : aucune validation « complète » n'est revendiquée.

**Interactions contrôlées.** Date ≠ mesure (6) sans réintroduire l'attribution erronée (5) ; la comparaison directe autorisée sans permission (arbitrage précédent) reste acceptée en FR/EN/ES et le test avec et sans permission C388 passe ; une abstention sur un sujet ne couvre plus une affirmation de progression sur un autre (4) ; un compteur ne fonde plus de distance (2) tout en gardant les moyennes sur distances connues ; fuseaux (1) cohérents avec le contexte partagé (`date_inclusive` inchangé).

**Limites résiduelles / nouveaux risques.**
- Une phrase mêlant une date historique et les valeurs de la séance analysée sans mot comparatif (« Your previous run was on 8 January, … 10 km today ») reste rejetée par prudence.
- Sans permission C388, la comparaison est tolérée si la phrase cite une mesure historique ; la pertinence de la métrique (allure vs distance) et la proposition exacte ne sont pas vérifiées.
- Les verbes de la liste de non-affirmation sont fermés : une abstention rédigée autrement est rejetée (sens conservateur).
- Heuristique : le garde ne prouve pas la vérité du texte.

**Niveaux de validation.** Déterministe : tests ci-dessus (synthétiques). Runtime LLM : non réalisée. Humaine : non réalisée.

**GO/NO-GO merge :** GO conditionnel sur ces points techniques (sept alertes corrigées, suites ciblées vertes, C388/C396/Training V2 inchangés). **Avant activation de C400** : évaluation runtime indépendante sur les cinq séances réelles de référence, relecture humaine, décision sur les limites ci-dessus. `C400_SESSION_COMMENT_ENABLED` reste OFF. SHA final : indiqué dans le message de livraison (un SHA ne peut pas figurer dans le commit qui le produit).
