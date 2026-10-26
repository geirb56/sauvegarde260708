# C378 — Coach Editorial V2

- Base : `copilot/dev` @ `d4cc34b` (Merge PR #371, C374-C)
- Head : branche `copilot/c378-coach-editorial-v2` (commits `0b10aad`, `1d9919e`, puis corrections d'audit pré-merge, section 11)
- Statut : PR ouverte, **non mergée, non déployée**. STOP avant C379.

## 1. Audit initial

| Point | Constat |
|---|---|
| HEAD `copilot/dev` | `d4cc34b`, identique à la base de la branche de travail. |
| C377 (PR #372 Session Coaching Intelligence) | Absent de `copilot/dev` : aucun module `session_coaching*` ni de référence C377. Il n'y a pas de conflit architectural. |
| Chemin de production réel | `server.py` → `workout_intelligence_v3_service` → `narrative_coach_v3.generate_narrative_coach_v3`. Le chemin n'est pas modifié. |
| Coach hybride C359/C365/C372/C374 | Prototype interne protégé par le flag `C359_HYBRID_COACH_ENABLED`, sans route. C378 ne modifie que cette couche. |
| C359 | `build_admissible_facts()` reste l'autorité des faits : provenance, liaison user/workout V2, permissions historiques (`HybridPermissions`), données manquantes → abstention. |
| C365 | `primary_fact_candidates()` faisait gagner la direction d'allure sur toute régularité et laissait `prescription.review` mener. |
| C374-C | `_realize()` ajoutait systématiquement 1 à 2 phrases de réserve par fait, ce qui rendait les textes répétitifs. Les supports privilégiés réintroduisaient la prescription. |
| Jugements V2 (`coach_language`) | Disponibles et réellement produits : bande de régularité (homogeneous/noticeable/variable), direction d'allure (groupes extrêmes), comparabilité (durée), couverture, **direction d'allure continue par moitiés de distance égales** (`coach.pacing` / `coach.execution.pace_hr`, scope `equal_distance_halves`). Ce dernier n'était pas admis par C359. |
| Jugements absents | Pas de verdict de régularité pour une sortie continue. Pas d'objectif de séance mesuré. |

## 2. Architecture existante réutilisée

Aucun nouveau module, moteur, service, route, LLM ou appel externe n'est ajouté.

- `hybrid_coach_v2_c372.py` : nouveau validateur de transport `approved_v2_continuous_pacing()`, sur le même modèle que les validateurs C372 existants (liaison user/workout, cohérence signe/valeur, seuil d'affichage existant `PACE_DISPLAY_CHANGE_SEC_KM`).
- `hybrid_coach_c359.py` : nouveau fait admissible `continuous.pace_halves`. Extensions minimales de contrat : `HybridClaim.limits` et `HybridResult.language` / `advice` / `advice_reason`.
- `hybrid_coach_editorial_c365.py` : règles de sélection, `EDITORIAL_EXCLUDED_FACTS`, `editorial_scope()`, registre fermé `ADVICE_REGISTRY` et `select_advice()`.
- `hybrid_coach_closed_c374.py` : `_realize()` avec des réserves allégées, conseil validé par option, et champs `language` / `advice` sur `ClosedChoiceResult`.

`narrative_coach_v3.py` et les moteurs scientifiques V2/V3 (`workout_analysis_v2`, `workout_intelligence_v3`, `coach_language`) ne sont pas modifiés. Leurs seuils sont inchangés.

## 3. Fichiers modifiés

- `backend/hybrid_coach_v2_c372.py`
- `backend/hybrid_coach_c359.py`
- `backend/hybrid_coach_editorial_c365.py`
- `backend/hybrid_coach_closed_c374.py`
- `backend/tests/test_hybrid_coach_c365.py`, `test_hybrid_coach_c371.py`, `test_hybrid_coach_c372.py`, `test_hybrid_coach_c374.py` : adaptés à la nouvelle politique (prescription exclue, réserves allégées, intensité devant l'historique).
- `backend/tests/test_hybrid_coach_c378.py` : nouveau fichier (72 tests).
- `docs/reports/C378_COACH_EDITORIAL_V2.md` : ce rapport.

## 4. Règles de sélection éditoriale (`primary_fact_candidates`)

Contraintes communes :
- une observation principale, au plus deux secondaires ;
- un même constat n'est jamais répété ;
- une métrique seule (FC sans seuils, couverture, effort isolé) ne mène pas s'il existe un jugement V2 ;
- `prescription.review` est hors périmètre.

**Fractionné**
1. Direction d'allure V2 significative (`interval.pace_direction`). Si la bande V2 est *homogeneous*, la régularité passe devant : une accélération n'est pas automatiquement plus intéressante qu'une constance remarquable.
2. Régularité ou variabilité V2 (`interval.regularity`).
3. Observations des répétitions (`effort.first` / `effort.last` / `interval.count`).
4. Structure de la séance, puis description générale.

En support, `intensity.position` est retenu uniquement s'il est au-dessus de LT2.

**Sortie continue**
1. Évolution d'allure mesurée sur des moitiés de distance égales (`continuous.pace_halves`).
2. Régularité : non admise, car V2 ne produit pas de verdict continu.
3. Intensité relative à des seuils fiables (`intensity.position`).
4. Une seule comparaison historique admissible.
5. `session.kind` / `session.unknown`.

**Sortie longue**
- Mène avec `session.long` (durée par rapport à l'historique autorisé), puis `continuous.pace_halves`, puis l'intensité si elle dépasse LT2.
- Le fait halves porte `no_fatigue_or_endurance_inference` et il n'y a aucun conseil.

## 5. Matrice des conseils autorisés (`ADVICE_REGISTRY`, fermé)

| Id | Fait déclencheur | Conditions (toutes) | Contre-indications | Provenance |
|---|---|---|---|---|
| `advice.keep_consistency` (B) | `interval.regularity` | bande `homogeneous` ; tous les efforts enregistrés sont comparables | direction progressive V2 admise | workout_analysis_v2 regularity band |
| `advice.stabilize_paces` (A) | `interval.regularity` | bande `variable` ; tous les efforts enregistrés sont comparables | direction progressive V2 admise (séance possiblement progressive) | idem |
| `advice.effort_distribution` (C) | `interval.pace_direction` | **intention d'allure stable vérifiée** (`verified_steady_pacing_intent`, toujours fausse aujourd'hui → jamais admis) ; direction V2 explicite ; efforts comparables | bande homogène | workout_analysis_v2 pace direction |
| `advice.continuous_pacing` (D) | `continuous.pace_halves` | seconde moitié plus lente ; mesure sur toute la séance ; type easy/steady fiable (confiance medium/high) | sortie longue | workout_analysis_v2 coach.pacing |

Principes communs :
- formulation conditionnelle (« où tu recherches… »), donc l'objectif inconnu n'est jamais supposé ;
- textes courts FR/EN/ES ;
- prédicats en vocabulaire fermé ; un nom inconnu échoue en mode fermé.

Le conseil est une `HybridClaim` séparée (`section="advice"`), avec :
- `evidence_ids` = fait déclencheur ;
- `evidence_refs` = chemins sources du déclencheur ;
- `limits` = limites du déclencheur.

Il n'est **pas** concaténé au texte, ce qui préserve le contrat `text` / `claims` existant. C379 le composera.

## 6. Conditions d'abstention

`advice_reason` vaut :
- `no_primary_fact` ;
- `no_advice_for_primary` (comptage, intensité, historique, sortie longue…) ;
- `condition_unmet:<condition>` ;
- `contraindicated:<contre-indication>` (prioritaire, car plus informative) ;
- `size_limit` (taille maximale du texte Coach).

`AdviceDecision.rejections` garde la raison par règle.

Cas d'abstention :
- accélération progressive dans une sortie continue (negative split : jamais présentée comme une erreur) ;
- type de séance inconnu ou non fiable ;
- tempo ;
- répétitions non comparables ;
- bande « noticeable » ;
- données partielles ;
- absence de V2.

## 7. Exemples de sorties réelles

Sorties générées par `generate_hybrid_coach()` en fallback déterministe (transport indisponible), via les fixtures V2/V3 calculées des tests (`calculated_case`, `continuous_case`, `synthetic_case`). Le texte est copié tel quel depuis la sortie du script ; il n'est pas réécrit.

```text
### Fractionné régulier 4×300 s/km (fr)
Faits admis: intensity.hr, effort.first, effort.last, effort.coverage, interval.regularity
Fait principal: interval.regularity | conclusion: v2_repetition_pacing_band | limites: ['recorded_comparable_efforts_only', 'not_physiological_stability', 'no_fatigue_progression_or_cause', 'descriptive_not_good_or_bad']
Valeurs: {'regularity_band': 'homogeneous', 'source': 'workout_analysis_v2', 'status': 'available', 'efforts': 4, 'comparability_basis': 'duration'}
Secondaires: []
Conseil: advice.keep_consistency — Cette constance est un bon repère à retrouver lors de tes prochaines séries comparables. | raison: advice_admitted
Mode: deterministic_fallback provider_unavailable
Texte: Les allures des répétitions comparables sont homogènes.

### Fractionné régulier 4×300 s/km (en)
Faits admis: intensity.hr, effort.first, effort.last, effort.coverage, interval.regularity
Fait principal: interval.regularity | conclusion: v2_repetition_pacing_band | limites: ['recorded_comparable_efforts_only', 'not_physiological_stability', 'no_fatigue_progression_or_cause', 'descriptive_not_good_or_bad']
Valeurs: {'regularity_band': 'homogeneous', 'source': 'workout_analysis_v2', 'status': 'available', 'efforts': 4, 'comparability_basis': 'duration'}
Secondaires: []
Conseil: advice.keep_consistency — This consistency is a useful reference for your next comparable sets. | raison: advice_admitted
Mode: deterministic_fallback provider_unavailable
Texte: The comparable repetitions have homogeneous paces.

### Fractionné régulier 4×300 s/km (es)
Faits admis: intensity.hr, effort.first, effort.last, effort.coverage, interval.regularity
Fait principal: interval.regularity | conclusion: v2_repetition_pacing_band | limites: ['recorded_comparable_efforts_only', 'not_physiological_stability', 'no_fatigue_progression_or_cause', 'descriptive_not_good_or_bad']
Valeurs: {'regularity_band': 'homogeneous', 'source': 'workout_analysis_v2', 'status': 'available', 'efforts': 4, 'comparability_basis': 'duration'}
Secondaires: []
Conseil: advice.keep_consistency — Esta constancia es una buena referencia para tus próximas series comparables. | raison: advice_admitted
Mode: deterministic_fallback provider_unavailable
Texte: Los ritmos de las repeticiones comparables son homogéneos.

### Fractionné progressif 330→300 s/km (fr)
Faits admis: intensity.hr, effort.first, effort.last, effort.coverage, interval.regularity, interval.pace_direction
Fait principal: interval.pace_direction | conclusion: v2_repetition_pace_direction | limites: ['recorded_comparable_efforts_only', 'no_physiological_progression', 'no_causal_inference']
Valeurs: {'direction': 'faster', 'scope': 'equal_count_endpoint_groups_middle_excluded', 'pace_change_sec_per_km': -20.0, 'comparability_basis': 'duration', 'source': 'workout_analysis_v2', 'efforts': 4, 'group_size': 2}
Secondaires: []
Conseil: advice.effort_distribution — Pour une prochaine séance où tu recherches une allure stable, essaie de trouver ton rythme dès les premières répétitions. | raison: advice_admitted
Mode: deterministic_fallback provider_unavailable
[SORTIE HISTORIQUE @1d9919e — comportement corrigé, voir section 11 : conseil désormais absent]
Texte: Les 2 dernières répétitions comparables sont 20 s/km plus rapides que les 2 premières.

### Fractionné irrégulier 300/330/295/325 (fr)
Faits admis: intensity.hr, effort.first, effort.last, effort.coverage, interval.regularity
Fait principal: interval.regularity | conclusion: v2_repetition_pacing_band | limites: ['recorded_comparable_efforts_only', 'not_physiological_stability', 'no_fatigue_progression_or_cause', 'descriptive_not_good_or_bad']
Valeurs: {'regularity_band': 'variable', 'source': 'workout_analysis_v2', 'status': 'available', 'efforts': 4, 'comparability_basis': 'duration'}
Secondaires: []
Conseil: advice.stabilize_paces — Sur une prochaine séance comparable où tu recherches la régularité, essaie de stabiliser davantage tes allures. | raison: advice_admitted
Mode: deterministic_fallback provider_unavailable
Texte: Les répétitions comparables présentent des variations d'allure importantes.

### Footing (easy_run_probable, confiance high) 5×5:48 + 5×6:18 (fr)
Faits admis: session.kind, intensity.hr, continuous.pace_halves
Fait principal: continuous.pace_halves | conclusion: v2_continuous_half_pace_direction | limites: ['equal_distance_halves_only', 'no_fatigue_or_endurance_inference', 'no_causal_inference', 'terrain_weather_not_controlled']
Valeurs: {'direction': 'slower', 'scope': 'equal_distance_halves', 'pace_change_sec_per_km': 30.0, 'coverage': 'whole_session', 'source': 'workout_analysis_v2'}
Secondaires: []
Conseil: advice.continuous_pacing — Sur une prochaine sortie comparable où tu vises une allure régulière, essaie de répartir ton allure plus également entre les deux moitiés. | raison: advice_admitted
Mode: deterministic_fallback provider_unavailable
Texte: La seconde moitié en distance de ta séance est 30 s/km plus lente que la première.

### Sortie continue sans type fiable 5×5:48 + 5×6:18 (fr)
Faits admis: intensity.hr, session.unknown, continuous.pace_halves
Fait principal: continuous.pace_halves | conclusion: v2_continuous_half_pace_direction | limites: ['equal_distance_halves_only', 'no_fatigue_or_endurance_inference', 'no_causal_inference', 'terrain_weather_not_controlled']
Valeurs: {'direction': 'slower', 'scope': 'equal_distance_halves', 'pace_change_sec_per_km': 30.0, 'coverage': 'whole_session', 'source': 'workout_analysis_v2'}
Secondaires: []
Conseil: None | raison: condition_unmet:trusted_easy_or_steady_type
Mode: deterministic_fallback provider_unavailable
Texte: La seconde moitié en distance de ta séance est 30 s/km plus lente que la première.

### Données insuffisantes (synthetic intervals_4x4, sans V2) (fr)
Faits admis: interval.count, intensity.position
Fait principal: interval.count | conclusion: recorded_intervals_without_regularity | limites: ['no_repetition_durations', 'regularity_verdict_unavailable']
Valeurs: {'efforts': 4, 'recoveries': 3}
Secondaires: ['intensity.position']
Conseil: None | raison: no_advice_for_primary
Mode: deterministic_fallback provider_unavailable
Texte: Garmin a enregistré une séance fractionnée avec 4 phases d'effort et 3 phases de récupération. Ta FC moyenne est de 160 bpm, entre LT1 et LT2 ; elle ne décrit pas tout l'effort.
```

Lecture :
- Fractionné régulier : régularité en tête, conseil B.
- Fractionné progressif : direction en tête (−20 s/km sur les groupes extrêmes, sans conclusion sur la séance entière). À `1d9919e` le conseil C était admis ; **corrigé** : abstention `condition_unmet:verified_steady_pacing_intent` (section 11).
- Fractionné irrégulier : variabilité, conseil A.
- Sortie continue : seconde moitié plus lente.
  - Conseil D seulement quand le type easy/steady est fiable.
  - Sinon abstention `condition_unmet:trusted_easy_or_steady_type`.
- Données insuffisantes : comptage plus intensité, abstention `no_advice_for_primary`.

Dans chaque cas, les limites (`no_fatigue_…`, `no_causal_inference`…) restent attachées aux faits et aux claims.

## 8. Résultats des tests

Commandes (depuis `backend/`) :

- `python -m pytest tests/test_hybrid_coach_c378.py -q` → **72 passed**
- `python -m pytest tests/test_hybrid_coach_c3*.py -q` → **796 passed**
- Suite backend complète `python -m pytest tests -q` :
  - base `d4cc34b` : 263 failed, 5085 passed, 136 errors ;
  - head : 263 failed, **5157 passed**, 136 errors.
  - L'ensemble des tests en échec ou en erreur est **identique** (diff vide). Ces échecs sont préexistants et liés à l'environnement : Redis, MongoDB et binding `cryptography` (`lib.GEN_EMAIL`). Les +72 sont les nouveaux tests C378.

Couverture C378 :
- les 15 scénarios obligatoires ;
- l'intégrité du registre ;
- un conseil validé et le rejet d'une falsification dans les options fermées ;
- le fait que les réserves allégées n'admettent aucune affirmation interdite : la prose du provider est rejetée (`invalid_editorial_selection`) et une clause falsifiée lève `scientific_violation` pour les 6 formulations interdites de la section 6 ;
- la visibilité des limites indispensables ;
- le déterminisme ;
- l'absence de sélection sur la seule présence d'une métrique.

## 9. Régressions vérifiées

- Routes, frontend, entitlements, modèle LLM et seuils : aucun n'est modifié.
- `narrative_coach_v3` : les tests passent et le module n'est pas modifié.
- C359 admet toujours `prescription.review` : la prescription n'est exclue que du périmètre éditorial Coach (`editorial_scope`, `_validate_composition`, `validate_editorial_selection`).
- Le texte et les claims existants gardent le même contrat. Les nouveaux champs sont optionnels avec une valeur par défaut.
- Réserves : seules restent visibles celles qui empêchent une lecture trompeuse :
  - FC moyenne par rapport à chaque phase ;
  - terrain/météo et non-preuve de forme pour les comparaisons et tendances.

  Les autres restent dans `important_limits` / `claim.limits` et dans les validations.
- Absence d'accès réseau vérifiée par un mock de socket dans les tests.

## 10. Limites restantes pour C379

- Le texte d'observation et le conseil sont séparés ; C379 doit composer le commentaire de 70 à 110 mots à partir de `claims` + `advice` + `limits`, sans recalcul.
- Aucun verdict de régularité continue n'est admis, car V2 ne le produit pas.
- L'objectif réel de la séance reste inconnu ; les conseils restent conditionnels, et `advice.effort_distribution` n'est jamais admis tant qu'aucun fait admis n'établit une intention d'allure stable.
- `continuous.pace_halves` : contrôle de cohérence avec les références `pacing` de la réponse V2, pas une re-validation des splits Garmin (voir section 11).
- La sortie longue n'a pas de conseil.
- Les valeurs sont affichées à la précision admise, sans arrondi éditorial.
- La sélection LLM existante (choix d'option fermée C374) est inchangée.
- Le Coach hybride reste derrière un flag, sans câblage en production.

## 11. Corrections d'audit avant merge (PR #373, audit de `1d9919e`)

Le périmètre est inchangé : C365 et C372, la provenance du fait dans C359 (`build_admissible_facts`), plus les tests. Les fichiers suivants ne sont pas touchés :
- calculs V2/V3 et seuils ;
- routes, frontend, entitlements, flags ;
- LLM ;
- `narrative_coach_v3`.

Aucun nouveau module n'est ajouté.

### 11.1 Correction 1 — conseil sur répétitions progressives

**Cause.** La règle `advice.effort_distribution` ne demandait que deux conditions : une direction V2 explicite et des efforts comparables. Toute accélération ou décélération significative déclenchait donc un conseil de stabilisation. Or une progression peut être voulue. L'intention d'allure stable n'est portée par aucun fait admis, et la prescription est hors du périmètre Coach : elle ne doit pas servir à deviner cette intention.

**Modification.** Dans `backend/hybrid_coach_editorial_c365.py`, la règle C du registre `ADVICE_REGISTRY` reçoit une première condition, `verified_steady_pacing_intent`. Le prédicat de `_advice_predicate()` en vocabulaire fermé l'évalue à `False`, faute de signal fiable, ce qui revient à désactiver l'admission. L'identifiant est conservé pour la compatibilité.

`select_advice()` n'est pas modifié. Il renvoie désormais `condition_unmet:verified_steady_pacing_intent` et garde le détail dans `rejections`.

| Cas | Avant (`1d9919e`) | Après |
|---|---|---|
| Fractionné plus rapide | observation + `advice.effort_distribution` | observation conservée, pas de conseil, `condition_unmet:verified_steady_pacing_intent` |
| Fractionné plus lent | observation + `advice.effort_distribution` | observation conservée, pas de conseil, même raison |
| Fractionné homogène | `advice.keep_consistency` | inchangé |
| Fractionné irrégulier | `advice.stabilize_paces` (comparabilité + contre-indication direction) | inchangé |
| Prescription présente (`consistent` / `deviation`) | exclue du commentaire | exclue ; elle ne fournit pas l'intention, toujours abstention |

### 11.2 Correction 2 — validation de `continuous.pace_halves`

**Audit du contrat.** `WorkoutAnalysisV2Response` ne transporte **pas** les splits kilométriques bruts : `km_splits` reste dans le document `workouts` qui alimente V2. Les moitiés (`first/second_half_pace_sec_per_km`) sont calculées par `coach_language.build_coach_language` à partir de ces splits.

`approved_v2_continuous_pacing()` ne vérifiait que la cohérence interne de la conclusion. Une conclusion modifiée mais cohérente avec elle-même pouvait donc être admise, par exemple avec des moitiés 333/393 s/km et une différence de +60.

**Références disponibles dans la même réponse, hors de la conclusion.** Ce sont trois champs de `analysis.pacing`, issus du document `workouts` par `_build_pacing` et arrondis à 0,001 min/km :
- `fastest_split_min_km` ;
- `slowest_split_min_km` ;
- `average_pace_min_km`, qui est l'allure moyenne Garmin de la séance.

**Validation ajoutée.** Elle vit dans `_within_pacing_reference()`, dans `backend/hybrid_coach_v2_c372.py`. Aucune allure n'est recalculée : la fonction vérifie deux identités des moitiés à distance égale.

1. Chaque moitié est une moyenne de splits, donc elle doit se situer entre le split le plus rapide et le plus lent.
2. La moyenne des deux moitiés doit être égale à l'allure moyenne de la séance.

Tolérances : la constante V2 existante `MEASUREMENT_RECONCILIATION_REL_TOL` (1 %), plus 0,03 s/km pour l'arrondi d'affichage.

Si une référence manque, si `pacing.available` est faux ou si la plage est inversée, la conclusion n'est pas admise : c'est une abstention.

Le fait C359 ajoute :
- la condition `consistent_with_v2_session_pacing_reference` ;
- les trois chemins `workout_analysis_v2.pacing.*` dans `source_paths`.

Le dictionnaire approuvé expose `reference_check = "v2_pacing_split_range_and_session_average"`.

**Ce n'est pas une validation indépendante des données sources.** C'est un contrôle de cohérence entre deux parties de la même réponse V2. Elle détecte :
- une conclusion exagérée qui sort de la plage des splits ;
- une conclusion décalée qui contredit l'allure moyenne.

Elle ne détecte pas, et ces cas sont testés comme limites explicites :
- une inversion symétrique des deux moitiés, qui garde la plage et la moyenne (la réponse n'a pas de splits ordonnés) ;
- un décalage plus petit que la tolérance de réconciliation.

Effet de bord connu : si l'allure moyenne Garmin est calculée sur le temps en mouvement alors que les splits couvrent le temps écoulé, avec des pauses, la moyenne peut sortir de la tolérance. Le Coach s'abstient alors de ce fait ; il ne s'expose pas à une fausse admission.

### 11.3 Tests ajoutés ou modifiés (`backend/tests/test_hybrid_coach_c378.py`)

- `test_02_03_progressive_intervals_keep_observation_and_abstain_without_verified_intent` :
  - plus rapide et plus lent, en FR/EN/ES ;
  - l'observation est conservée et localisée ;
  - pas de conseil, raison et `rejections` explicites ;
  - les autres conditions V2 sont bien satisfaites, donc l'abstention tient uniquement à l'intention ;
  - pas de conseil de régularité ;
  - les options fermées n'ont pas de conseil ;
  - le fallback est déterministe.
- `test_02b_prescription_never_supplies_the_missing_pacing_intent` : prescription `consistent` / `deviation`.
- Pour `continuous.pace_halves` :
  - `test_continuous_halves_original_v2_conclusion_is_admitted_with_reference_provenance` ;
  - `test_continuous_halves_tampered_conclusions_are_rejected`, qui couvre :
    - une différence incohérente ;
    - une direction incohérente ;
    - une couverture partielle ;
    - une mauvaise portée ;
    - des moitiés cohérentes entre elles mais hors de la plage des splits ;
    - des moitiés cohérentes mais contraires à la moyenne de séance ;
  - `test_continuous_halves_contradicted_by_reference_measurements_are_rejected` ;
  - `test_continuous_halves_abstain_when_reference_measurements_are_missing` ;
  - `test_continuous_halves_reject_wrong_user_activity_or_structure` ;
  - `test_continuous_halves_within_rounding_of_references_remain_admitted` ;
  - `test_continuous_halves_residual_limit_is_explicit_not_hidden` (inversion symétrique, décalage sous la tolérance).
- Les tests 01 (homogène → `keep_consistency`) et 04 (irrégulier → `stabilize_paces`) sont inchangés et passent.

### 11.4 Résultats exacts

Commandes lancées depuis `backend/` :

| Suite | Résultat |
|---|---|
| `tests/test_hybrid_coach_c359.py` | 60 passed |
| `tests/test_hybrid_coach_c362.py` | 74 passed |
| `tests/test_hybrid_coach_c364_audit.py` | 32 passed |
| `tests/test_hybrid_coach_c365.py` | 99 passed |
| `tests/test_hybrid_coach_c371.py` | 223 passed |
| `tests/test_hybrid_coach_c372.py` | 128 passed |
| `tests/test_hybrid_coach_c374.py` | 108 passed |
| `tests/test_hybrid_coach_c378.py` | 94 passed (72 à `1d9919e`) |
| `+ narrative_coach_v3*, coach_language*, workout_intelligence_v3*` | 1519 passed, 2 failed |

Les 2 échecs sont préexistants et d'environnement : `lib.GEN_EMAIL`, identiques à la base.

Suite complète `python -m pytest tests -q` :
- base `1d9919e` : 263 failed, 5157 passed, 136 errors ;
- après : 263 failed, **5179 passed**, 136 errors.

L'ensemble des tests en échec ou en erreur est identique (diff vide). Les échecs viennent de l'environnement : Redis, MongoDB et `cryptography`.

### 11.5 Limites résiduelles

- `advice.effort_distribution` reste dans le registre mais n'est jamais admis. Le réactiver demandera un fait admis qui établit l'intention de régularité, sans utiliser la prescription.
- `advice.continuous_pacing` (D) s'appuie encore sur une classification V3 probable easy/steady à confiance moyenne ou haute, en plus d'une formulation conditionnelle. Cette règle n'est pas modifiée ici, hors du périmètre de l'audit, et reste à réévaluer avant C379.
- `continuous.pace_halves` passe un contrôle de cohérence avec `analysis.pacing`, mais il n'y a pas de re-validation contre les splits sources : inversion symétrique et décalage sous la tolérance restent possibles (voir 11.2).

### 11.6 Exemples réellement produits par le code (après correction)

Script `/tmp` qui appelle `generate_hybrid_coach()` en fallback déterministe (transport indisponible) avec les fixtures V2/V3 des tests. Sortie copiée sans modification :

```text
### Fractionné progressivement plus rapide 330→300 s/km (fr)
Faits admis: intensity.hr, effort.first, effort.last, effort.coverage, interval.regularity, interval.pace_direction
Fait principal: interval.pace_direction
Conseil: None | raison: condition_unmet:verified_steady_pacing_intent
Texte: Les 2 dernières répétitions comparables sont 20 s/km plus rapides que les 2 premières.

### Fractionné progressivement plus rapide 330→300 s/km (en)
Faits admis: intensity.hr, effort.first, effort.last, effort.coverage, interval.regularity, interval.pace_direction
Fait principal: interval.pace_direction
Conseil: None | raison: condition_unmet:verified_steady_pacing_intent
Texte: The final 2 comparable repetitions are 20 s/km faster than the opening 2.

### Fractionné progressivement plus rapide 330→300 s/km (es)
Faits admis: intensity.hr, effort.first, effort.last, effort.coverage, interval.regularity, interval.pace_direction
Fait principal: interval.pace_direction
Conseil: None | raison: condition_unmet:verified_steady_pacing_intent
Texte: Las 2 últimas repeticiones comparables son 20 s/km más rápidas que las 2 primeras.

### Fractionné progressivement plus lent 300→330 s/km (fr)
Faits admis: intensity.hr, effort.first, effort.last, effort.coverage, interval.regularity, interval.pace_direction
Fait principal: interval.pace_direction
Conseil: None | raison: condition_unmet:verified_steady_pacing_intent
Texte: Les 2 dernières répétitions comparables sont 20 s/km plus lentes que les 2 premières.

### Fractionné homogène 4×300 s/km (fr)
Faits admis: intensity.hr, effort.first, effort.last, effort.coverage, interval.regularity
Fait principal: interval.regularity
Conseil: advice.keep_consistency — Cette constance est un bon repère à retrouver lors de tes prochaines séries comparables. | raison: advice_admitted
Texte: Les allures des répétitions comparables sont homogènes.

### Fractionné irrégulier 300/330/295/325 (fr)
Faits admis: intensity.hr, effort.first, effort.last, effort.coverage, interval.regularity
Fait principal: interval.regularity
Conseil: advice.stabilize_paces — Sur une prochaine séance comparable où tu recherches la régularité, essaie de stabiliser davantage tes allures. | raison: advice_admitted
Texte: Les répétitions comparables présentent des variations d'allure importantes.

### Footing 5×5:48 + 5×6:18, V2 original (fr)
Faits admis: session.kind, intensity.hr, continuous.pace_halves
Fait principal: continuous.pace_halves
Conseil: advice.continuous_pacing — Sur une prochaine sortie comparable où tu vises une allure régulière, essaie de répartir ton allure plus également entre les deux moitiés. | raison: advice_admitted
Texte: La seconde moitié en distance de ta séance est 30 s/km plus lente que la première.

approved_v2_continuous_pacing (moitiés 333/393, cohérentes entre elles, hors plage des splits 348–378): None
### Footing, conclusion V2 modifiée (333/393 s/km, +60) (fr)
Faits admis: session.kind, intensity.hr
Fait principal: intensity.hr
Conseil: None | raison: no_advice_for_primary
Texte: Ta FC moyenne enregistrée est de 145 bpm ; elle ne suffit pas à établir une zone physiologique.

### Footing, référence V2 pacing.average_pace_min_km absente (fr)
Faits admis: session.kind, intensity.hr
Fait principal: intensity.hr
Conseil: None | raison: no_advice_for_primary
Texte: Ta FC moyenne enregistrée est de 145 bpm ; elle ne suffit pas à établir une zone physiologique.
```

