# RUNINDEX PR #190 — Performance Curve V2: k Identifiability + Quality-Aware Huber

## 1. Cause exacte du défaut #189 runtime

Le compte runtime présentait 18 performances qualifiées dont 14 `quality_confidence="low"` (fallback speed-only #188), couvrant 6–21 km à une allure quasi-constante (~6:05/km). Une seule vraie performance HR-supportée à 10.02 km / 5:02/km portait l'information de pente.

Deux mécanismes concurrents ont conduit à `k=1.016` :

**A. Base weights insuffisamment différenciés**  
Le facteur `quality_confidence_weight` valorisait `low→0.75` contre `high→1.00`. Avec 14 points `low` à `score~0.65` et 1 point `high` à `score=0.55`, les poids agrégés penchaient collectivement vers le nuage plat.

**B. Huber aveugle à la confiance**  
Le point `high` à 10.02 km était ~50s/km plus rapide que le nuage. Dans l'espace log(T) vs log(D), ce résidu était grand par rapport à la médiane des résidus du nuage plat. Huber l'a donc traité comme outlier et l'a réduit de `base_weight=0.55` à `robust_weight=0.171` (facteur ÷3.2). Ce faisant, Huber a effacé précisément l'observation qui portait le signal de pente.

**C. Absence de vérification d'identifiabilité**  
Après ce Huber, le fit final produisait `k=1.016`, valeur dans `[1.0, 1.25]`, acceptée sans vérification de l'evidence réelle. Un `fit_quality=0.988` flatteur (le nuage quasi-plat se fitte parfaitement avec k≈1) a masqué le problème.

---

## 2. Définition mathématique retenue pour l'identifiabilité

### Mesure : variance pondérée par qualité du log(distance)

```
ident_weights_i = robust_weight_i  si confidence_i ∈ {high, medium}
                = 0                 sinon

W = Σ ident_weights_i
x̄ = Σ (ident_weights_i × log(Di)) / W

k_identifiability_score = Σ (ident_weights_i × (log(Di) − x̄)²) / W
```

**Seuil** : `K_IDENTIFIABILITY_MIN_WX_VAR = 0.05`

La pente du modèle log-linéaire `log(T) = log(A) + k·log(D)` est le coefficient de la régression de `log(T)` sur `log(D)`. La variance pondérée de `log(D)` mesure directement le *levier informatif* disponible pour identifier cette pente. Une variance nulle ou faible signifie que toutes les observations sont concentrées au même `log(D)`, rendant la pente non identifiable indépendamment de leur nombre.

### Restriction aux observations high/medium

Les observations `low` (speed-only #188) sont exclues du calcul d'identifiabilité même si elles couvrent une large plage de distances. Elles sont exclues parce que :
- leur temps n'est pas garanti représentatif d'un effort maximal à cette distance ;
- leur pente implicite reflète le profil d'entraînement de l'athlète, pas sa capacité physiologique ;
- permettre 14 observations `low` à allure plate de prétendre identifier une pente individualiserait un artefact.

---

## 3. Pourquoi cette mesure est préférable au simple nombre de points

| Scénario | contributors | k_identifiability_score | k_identifiable |
|----------|-------------|------------------------|----------------|
| 14 low (6–21 km) + 1 high (10 km) | 15 | ~0 | **False** |
| 6 high (8–12 km cluster) | 6 | ~0.013 | **False** |
| 3 high (5K / 10K / semi) | 3 | ~0.35 | **True** |
| 2 high (5K / marathon) | 2 | N/A (two_point_shrinkage) | — |

Un compteur de contributeurs (`contributors=15` dans le cas runtime) ne capte pas l'information réelle disponible sur la pente. La mesure `k_identifiability_score` répond directement à la question : *les observations de confiance suffisante couvrent-elles une plage de distances permettant d'apprendre k ?*

---

## 4. Politique de fallback

Quand `k_identifiable == False` (uniquement pour N≥3, méthode `robust_weighted_log_fit`) :

```
curve_method = "prior_k_low_identifiability_fallback"
k = RIEGEL_K = 1.06
log(A) = Σ robust_weight_i × (log(Ti) − 1.06 × log(Di)) / Σ robust_weight_i
```

L'intercept est recalculé sur les poids robustes finaux avec la pente imposée à 1.06. L'intercept du fit libre n'est PAS conservé (il serait cohérent avec k≈1.0, pas avec k=1.06).

Le champ `k_raw` conserve la valeur data-driven apprise avant le fallback (diagnostic observable).

Le fallback s'applique *avant* la vérification `k_conflict`, qui reste active et prend le dessus si la pente hors `[1.0, 1.25]` est détectée.

---

## 5. Modification Huber quality-aware

### Floors appliqués

```python
HUBER_QUALITY_FLOOR_HIGH   = 0.50
HUBER_QUALITY_FLOOR_MEDIUM = 0.25
```

Dans la boucle Huber (2 itérations) :

```
effective_weight_i = base_weight_i × max(huber_multiplier_i, floor_i)
```

où `floor_i` est `HUBER_QUALITY_FLOOR_HIGH` si `confidence="high"`, `HUBER_QUALITY_FLOOR_MEDIUM` si `"medium"`, `0.0` sinon.

### Compromis

| Propriété | Comportement |
|-----------|-------------|
| Un point `high` vraiment aberrant | Peut être réduit jusqu'à 50% de son base_weight |
| 14 low déclarent le `high` outlier | Le `high` ne peut pas tomber sous 50% |
| Un artefact `high` extrême | Réduit à 50%, non nul, toujours visible |
| Points `low`/speed-only | Protection Huber complète (floor=0) |
| Domination par un seul point | Impossible : floor ne supprime pas Huber, il le borne |

### Pourquoi pas "if high: no Huber"

Un observation `high` pathologique (artefact GPS, activité mal taguée) doit encore pouvoir être sous-pondérée. Un floor 50% maintient une réduction significative tout en évitant l'effacement complet.

---

## 6. Comportement des performances speed-only

Les performances speed-only `quality_confidence="low"` (fallback #188) :

- **Restent autorisées** : le fallback #188 n'est pas modifié.
- **Contribuent à l'intercept** : elles participent au calcul de `A` via les poids robustes finaux.
- **Contribuent aux prédictions** : une courbe `prior_k_low_identifiability_fallback` produit des prédictions valides via k=1.06.
- **Ne prouvent pas la pente** : leur `ident_weight = 0` dans le calcul d'identifiabilité.
- **Restent dans la confidence** : leur `quality_confidence="low"` est correctement répercuté dans les agrégats.

---

## 7. Nouveaux diagnostics

### Dans `race_curve_diagnostics`

| Champ | Type | Description |
|-------|------|-------------|
| `k_identifiable` | bool | True si le score dépasse `K_IDENTIFIABILITY_MIN_WX_VAR` |
| `k_identifiability_score` | float | Variance pondérée qualité de log(D) pour high/medium |
| `k_identifiability_reason` | str | `"sufficient_hm_distance_spread"` / `"insufficient_hm_distance_spread"` / `"no_hm_quality_observations"` / `"not_applicable"` (N<3) |
| `high_medium_quality_weight_share` | float | Part des base_weights portés par high+medium |
| `speed_only_low_weight_share` | float | Part des base_weights portés par low (speed-only) |

### Dans `_CurveModel` (interne)

Trois champs supplémentaires : `k_identifiable`, `k_identifiability_score`, `k_identifiability_reason` (avec valeurs par défaut pour N<3).

### Cas runtime post-#190

Avec les correctifs en place :
- Le point `high` à 10.02 km a son `robust_weight ≥ 0.50 × 0.55 = 0.275` (floor quality-aware).
- `k_identifiability_score ≈ 0` (le seul point high/medium est au centre de la plage → pas de levier).
- `k_identifiable = False`.
- `curve_method = "prior_k_low_identifiability_fallback"`.
- `curve_k = 1.06`.

---

## 8. Datasets synthétiques

| Test | Dataset | Vérification |
|------|---------|-------------|
| TEST 1 | 14 speed-only low (6–21 km, allure plate) + 1 high (10 km, 5:02/km) | Interdit : k≈1.0 via robust_weighted_log_fit |
| TEST 2 | 6 high (8–12 km cluster) | k_identifiable=False, method=prior_k_low_identifiability_fallback, k=1.06 |
| TEST 3 | 3 high (5K/10K/semi), k_true=1.08 | k_identifiable=True, k appris ≈ 1.08 ±0.12 |
| TEST 4 | Core cohérent (5K/10K/semi) + outlier impossible (5K en 9:40) | outlier robust_weight/base_weight < 0.90 |
| TEST 5 | Pool speed-only only | k_identifiable=False, prédictions via prior k si courbe |
| TEST 6 | Run futur (marathon 2h) | Aucune modification de k / A / prédictions |
| TEST 7 | Mêmes données, ordre shufflé | Résultats identiques |
| TEST 8 | Mêmes perfs, VMA-acts avec/sans HR (max_hr<benchmark) | curve_k / curve_a / prédictions identiques |

---

## 9. Tests exécutés + résultats

```
tests/test_performance_model_pr190.py::test_1_runtime_pathology_flat_speedonly_plus_one_high_quality  PASSED
tests/test_performance_model_pr190.py::test_2_narrow_distance_cluster_k_not_identifiable              PASSED
tests/test_performance_model_pr190.py::test_3_identifiable_true_curve_k_learned                       PASSED
tests/test_performance_model_pr190.py::test_4_true_outlier_still_reduced                              PASSED
tests/test_performance_model_pr190.py::test_5_speedonly_pool_still_predicts_via_prior_k               PASSED
tests/test_performance_model_pr190.py::test_6_no_lookahead                                            PASSED
tests/test_performance_model_pr190.py::test_7_input_order_invariant                                   PASSED
tests/test_performance_model_pr190.py::test_8_vma_independence                                        PASSED

8 passed in 0.53s
```

Tests PR #189, #188, #186, #185 : tous passent.

---

## 10. Invariants #189 conservés

| Invariant | Status |
|-----------|--------|
| T(D) = A×D^k, courbe unique | ✅ conservé |
| Single performance → Riegel k=1.06 | ✅ conservé |
| N=2 → prior shrinkage | ✅ conservé |
| k hors [1.0, 1.25] → prior_k_conflict_fallback | ✅ conservé |
| Refit final Huber (#189 bug fix) | ✅ conservé |
| Extrapolation symétrique | ✅ conservé |
| null au-delà CURVE_MAX_EXTRAPOLATION_RATIO | ✅ conservé |
| Déterminisme | ✅ conservé |
| Aucune I/O dans performance_model.py | ✅ conservé |

---

## 11. Absence de dépendance VMA

`estimate_vma()` et `predict_races()` opèrent en parallèle. La courbe de performance est construite dans `_build_performance_curve()` à partir uniquement des `qualified_pool` (activités qualifiées #188). Aucun chemin de code n'injecte `vma_kmh`, `fcmax`, ni aucune sortie VMA dans la construction de la courbe ou les prédictions de course.

Le test 8 vérifie cela en ajoutant des activités qui modifient la sortie VMA sans changer les prédictions ou la courbe (verrouillé par max_hr≤benchmark_max pour éviter que le FCmax historique ne change).

---

## 12. Absence de look-ahead

`_validate_activity()` rejette toute activité avec `activity_date > reference_date`. Aucun point futur ne peut contribuer à la qualification, aux poids, au fit, ou aux diagnostics. Vérifié par le test 6.

`_strictly_prior_activities()` exige `other_dt < activity_dt` (strict), garantissant que le calcul du percentile de vitesse personnel est causal.

---

## 13. Limites connues

1. **Seuil K_IDENTIFIABILITY_MIN_WX_VAR=0.05** : calibré sur des cas synthétiques, pas sur des données réelles. Il correspond à ~5km-15km de plage utile en high/medium confidence. Des datasets avec uniquement 5K + 6K high-quality auraient un score ≈ 0.006 (non identifiable) ; c'est correct car 1 km de plage est insuffisant pour identifier k.

2. **Floor Huber à 50%** : valeur conservative. Un artefact high-confidence très extrême sera réduit à 50% de son poids de base, pas davantage. Si ce point est solitaire, il peut encore influencer A même avec floor. L'identifiabilité check limite toutefois cet impact sur k.

3. **N=2 non concerné** : le two_point_prior_shrinkage reste inchangé. Deux observations proches pourraient produire un k shrunk vers 1.06 sans identifiabilité explicite. Acceptable car la shrinkage force déjà k vers 1.06 proportionnellement à l'evidence.

4. **La métrique d'identifiabilité est pré-Huber dans le sens des distances** : les distances sont fixes, seuls les poids changent. Une observation high au centre exact de la plage de distances aura ident_score=0 même si d'autres observations high sont aux extrêmes (mais avec poids nuls après Huber). Ce cas serait couvert par le floor quality-aware.
