# RUNINDEX_PR191_REPORT.md
## Performance Curve V2 — QUALIFIED vs SLOPE-EVIDENCE

---

## 1. Base exacte

Base : `copilot/dev`  
HEAD de base : post-PR #190 (`ec7b76b`)  
Branche : `copilot/pr191-slope-evidence-clean`  
Cible PR : `copilot/dev`

---

## 2. Séparation QUALIFIED / SLOPE-EVIDENCE

PR #191 introduit une distinction explicite entre deux concepts :

**QUALIFIED PERFORMANCE**  
> Toute performance évaluée comme `quality.qualified == True` par `evaluate_performance_quality()`.  
> Contribue à l'estimation de A (intercept de la courbe).  
> Inclut les niveaux de confiance : `high`, `medium`, `low`.

**SLOPE-EVIDENCE PERFORMANCE**  
> Sous-ensemble des performances qualifiées dont `quality.confidence == "high"`.  
> Seules celles-ci peuvent autoriser la personnalisation de k.

Invariant central :  
**A peut utiliser PLUS de données que k.**

---

## 3. Pourquoi `confidence == "high"` est utilisé

En PR #190, le critère d'identifiabilité de k utilisait `confidence in ("high", "medium")`.

Problème observé au runtime post-#190 :

```
qualified_performance_count = 18
high = 1
medium = 4
low = 13

k_raw = 1.017409
curve_method = robust_weighted_log_fit
```

Les 4/5 observations high/medium couvraient des distances de 7–21 km, avec un spread réel.  
Mais ces 4 `medium` étaient des **sorties soutenues**, pas des performances maximales comparables entre distances.

Le spread de distance ne suffisait pas à identifier k, car les observations medium ne reflètent pas une performance maximale comparative.

PR #191 corrige cela : seules les observations `HIGH` constituent une slope-evidence défendable.

---

## 4. Absence de signal Garmin natif de maximalité

Aucun champ Garmin ne permet d'identifier fiablement une activité comme étant :
- une course ou compétition
- un test de performance maximal
- une séance au seuil vs une sortie au tempo

Par conséquent, aucun classificateur de maximalité n'est inventé.  
La classification s'appuie uniquement sur les signaux de qualité existants :
- score de performance composite (HR + speed percentile)
- seuils de confiance déjà établis en PR #188/#189

---

## 5. Comportement N=1

**Méthode** : `single_performance_riegel`  
**k** : `RIEGEL_K = 1.06` (prior fixe)  
**Inchangé par rapport à #190.**

---

## 6. Comportement N=2

### CAS A — deux observations slope-evidence HIGH

```
method = "two_point_prior_shrinkage_fit"
k = shrinkage(k_raw, RIEGEL_K, evidence_strength)
```

Le shrinkage de PR #189 est conservé intégralement.

### CAS B — moins de 2 HIGH (HIGH+MEDIUM, deux MEDIUM, deux LOW, etc.)

```
method = "two_point_prior_k_low_slope_evidence_fallback"
k = RIEGEL_K = 1.06
A = intercept recalculé à pente fixe avec les DEUX observations qualifiées
k_raw = valeur OLS pré-fallback (disponible en diagnostic)
k_fallback_applied = True
```

> Deux medium ne doivent pas apprendre k.  
> Deux low speed-only ne doivent pas apprendre k.  
> Un high + un medium ne doivent pas apprendre k.

---

## 7. Comportement N≥3

1. Calcul du fit robuste (Huber quality-aware #190) sur **toutes** les observations qualifiées.
2. Calcul de `slope_evidence_count` = nombre d'observations HIGH.
3. Calcul du score d'identifiabilité **uniquement sur les HIGH** (variance pondérée de log(distance)).
4. Si identifiabilité suffisante (`score >= 0.05`) ET `slope_evidence_count >= 2` :
   ```
   k = k_raw (data-driven)
   method = "robust_weighted_log_fit"
   k_identifiable = True
   ```
5. Sinon :
   ```
   k = RIEGEL_K = 1.06
   method = "prior_k_low_slope_evidence_fallback"
   A = recalculé à pente fixe avec les poids robustes de TOUTES les qualifiées
   k_fallback_applied = True
   k_identifiable = False
   k_raw = diagnostic (slope fit initial)
   ```

**Priorité k_conflict conservée** : si k_raw est hors `[1.0, 1.25]`, la détection de conflit s'applique en premier, avant le test slope-evidence.

---

## 8. Séparation A/k

| Chemin | k | A |
|--------|---|---|
| `single_performance_riegel` | 1.06 (prior) | 1 observation |
| `two_point_prior_shrinkage_fit` | shrinkage(k_raw, 1.06) | 2 HIGH |
| `two_point_prior_k_low_slope_evidence_fallback` | 1.06 | 2 observations qualifiées |
| `robust_weighted_log_fit` (identifiable) | k_raw | toutes qualifiées |
| `prior_k_low_slope_evidence_fallback` | 1.06 | toutes qualifiées |
| `prior_k_conflict_fallback` | 1.06 | toutes qualifiées (pénalisées) |

**Invariant** : dans les méthodes fallback, A utilise **toutes** les observations qualifiées, pas seulement les HIGH.

---

## 9. Confidence extrapolation-aware

Lorsque k est un prior fixe via `prior_k_low_slope_evidence_fallback` ou `two_point_prior_k_low_slope_evidence_fallback`, une pénalité est appliquée selon l'extrapolation :

| Extrapolation ratio | Pénalité |
|--------------------|----------|
| ≤ 1.8 (cible proche) | 0 étapes supplémentaires |
| 1.8 – 3.0 | +1 étape |
| > 3.0 | +2 étapes |

Seuils réutilisés depuis le système existant (`_curve_prediction_confidence`).  
Aucun système parallèle créé.

**Principe** : bonne information sur A + k prior → fiable près des données, moins fiable loin.

---

## 10. Diagnostics

Ajoutés / exposés dans `race_curve_diagnostics` :

```
slope_evidence_count            # nombre d'observations HIGH
slope_evidence_distance_min     # distance min (m) des observations HIGH
slope_evidence_distance_max     # distance max (m) des observations HIGH
slope_evidence_distance_min_km  # idem en km
slope_evidence_distance_max_km  # idem en km

k_identifiable                  # bool — k data-driven est-il défendable ?
k_identifiability_score         # score de variance pondérée (HIGH uniquement)
k_identifiability_reason        # "sufficient_slope_evidence_spread" | "insufficient_slope_evidence_spread" | ...

curve_k_raw                     # slope fit initial (diagnostic)
curve_k                         # k final utilisé
curve_method                    # méthode de fit
k_fallback_applied              # bool — fallback appliqué ?
```

Lecture runtime immédiate :

```
qualified_performance_count = 18
slope_evidence_count = 1
→ A utilise 18 observations, k ne peut pas être individualisé.
```

---

## 11. Tests

| # | Scénario | Attendu |
|---|----------|---------|
| 1 | N≥3 : 1 HIGH + MEDIUM + LOW, large spread | `slope_evidence_count=1`, k=1.06, fallback |
| 2 | N≥3 : 3 HIGH multi-distance k synthétique ≠ 1.06 | `k_identifiable=True`, k ≈ k_synthétique |
| 3 | N≥3 : cluster HIGH 8–12 km | spread insuffisant, k=1.06 |
| 4 | Speed-only LOW | `slope_evidence_count=0`, k=1.06 |
| 5 | N==2 deux HIGH distinctes | `two_point_prior_shrinkage_fit` conservé |
| 6 | N==2 HIGH + MEDIUM | k=1.06, fallback slope-evidence |
| 7 | N==2 deux MEDIUM | k=1.06 |
| 8 | N==2 deux LOW speed-only | k=1.06 |
| 9 | Huber outlier | Robustesse #190 préservée |
| 10 | No look-ahead | Activité future sans effet |
| 11 | Input-order invariance | Ordre shuffled → résultat identique |
| 12 | VMA independence | Changement VMA n'affecte pas les prédictions |

---

## 12. Runtime réel attendu (validation post-implémentation)

Ces valeurs ne sont PAS codées en dur. Elles servent uniquement de repère.

Le prototype #191 avait produit :

```
slope_evidence_count = 1
method = prior_k_low_slope_evidence_fallback
k_raw ≈ 1.0174
k_final = 1.06

Prédictions approximatives :
5K  → 28:26
10K → 59:18
Semi → 2h10
Marathon → 4h32
```

---

## 13. Limites

1. **Aucun signal Garmin de maximalité** : la classification HIGH dépend des seuils `PERFORMANCE_HIGH_CONFIDENCE_*`. Si un utilisateur ne court jamais au seuil de performance, `slope_evidence_count` reste à 0.

2. **slope_evidence_count = 1** : avec un seul HIGH, k reste au prior. La confiance dans l'extrapolation est renforcée par la pénalité d'extrapolation.

3. **Cluster HIGH** : si tous les HIGH sont à des distances similaires (8–12 km), l'identifiabilité échoue même si `slope_evidence_count >= 2`.

4. **Huber floor** : les floors HIGH (0.50) et MEDIUM (0.25) de PR #190 sont conservés sans modification dans cette PR. Ils s'appliquent toujours, indépendamment du chemin slope-evidence.

5. **k_conflict priority** : le conflit (k_raw hors [1.0, 1.25]) est détecté avant le test slope-evidence pour N>=3. Cette priorité est documentée et conservée.

---

## Critères d'acceptation

| Critère | Statut |
|---------|--------|
| QUALIFIED_AND_SLOPE_EVIDENCE_SEPARATED | ✅ YES |
| A_USES_ALL_QUALIFIED | ✅ YES |
| K_USES_ONLY_DEFENSIBLE_SLOPE_EVIDENCE | ✅ YES |
| N2_TWO_HIGH_CAN_SHRINK | ✅ YES |
| N2_HIGH_PLUS_MEDIUM_CANNOT_LEARN_K | ✅ YES |
| N2_TWO_MEDIUM_CANNOT_LEARN_K | ✅ YES |
| N2_SPEED_ONLY_CANNOT_LEARN_K | ✅ YES |
| N3_MEDIUM_SPREAD_CANNOT_ALONE_DEFINE_K | ✅ YES |
| TRUE_HIGH_MULTIDISTANCE_CAN_LEARN_K | ✅ YES |
| NO_NEW_MAXIMALITY_CLASSIFIER | ✅ YES |
| NO_ACCOUNT_SPECIFIC_CALIBRATION | ✅ YES |
| NO_ARBITRARY_K_FLOOR | ✅ YES |
| HUBER_PR190_PRESERVED | ✅ YES |
| K_CONFLICT_PRIORITY_PRESERVED | ✅ YES |
| CONFIDENCE_EXTRAPOLATION_AWARE | ✅ YES |
| NO_LOOKAHEAD | ✅ YES |
| INPUT_ORDER_INVARIANT | ✅ YES |
| VMA_INDEPENDENCE | ✅ YES |
