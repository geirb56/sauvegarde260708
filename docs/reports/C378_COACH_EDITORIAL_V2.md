# C378 — Coach Editorial V2

- Base : `copilot/dev` @ `d4cc34b` (Merge PR #371, C374-C)
- Head : branche `copilot/c378-coach-editorial-v2` (code commit `0b10aad` + commits de tests/rapport de cette PR)
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
| `advice.effort_distribution` (C) | `interval.pace_direction` | direction V2 explicite ; efforts comparables | bande homogène | workout_analysis_v2 pace direction |
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
- Fractionné progressif : direction en tête (−20 s/km sur les groupes extrêmes, sans conclusion sur la séance entière), conseil C formulé conditionnellement.
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
- L'objectif réel de la séance reste inconnu ; les conseils restent conditionnels.
- La sortie longue n'a pas de conseil.
- Les valeurs sont affichées à la précision admise, sans arrondi éditorial.
- La sélection LLM existante (choix d'option fermée C374) est inchangée.
- Le Coach hybride reste derrière un flag, sans câblage en production.
