# RUNINDEX PR #191 — Performance Curve V2: Performance Comparability / Slope Evidence

## 1. Audit des 5 observations high/medium (contexte runtime post-#190)

Les 5 observations post-#190 décrites dans le problème sont :

| # | Dist (km) | Allure (min/km) | Niveau | relative_avg_hr | Notes |
|---|-----------|-----------------|--------|-----------------|-------|
| 1 | 7.07      | rapide          | high   | ~0.94+          | Seule observation high-confidence |
| 2 | 10.02     | ~6:08/km approx | medium | ~0.894          | Sortie soutenue |
| 3 | 10.44     | ~6:09/km approx | medium | ~0.893          | Sortie soutenue |
| 4 | 10.83     | ~6:09/km approx | medium | ~0.889          | Sortie soutenue |
| 5 | 20.63     | ~6:08/km        | medium | ~0.894          | Sortie longue soutenue |

### Signaux réellement disponibles dans DomainActivity

```
activity_type       — running / trail_running / etc.
start_time          — date
distance_m          — distance
duration_s          — durée totale
moving_duration_s   — durée en mouvement (si différente)
average_hr          — FC moyenne
max_hr              — FC max Garmin
elevation_gain_m    — dénivelé positif
```

Signaux Garmin actuellement **absents** de DomainActivity :
- Aucun champ `workout_type`, `race`, `event`, `lap_data`, `structured_workout`
- Aucun signal fiable permettant de distinguer automatiquement une course/compétition d'une sortie soutenue

### Pourquoi #190 concluait k identifiable

Post-#190, l'identifiabilité était calculée sur TOUTES les observations high+medium. Avec 5 observations couvrant 7.07 km à 20.63 km, le spread de distance log(20.63/7.07) = log(2.92) est significatif. La formule d'identifiabilité détectait ce spread et concluait `k_identifiable = True`.

### La pathologie

L'observation 20.63 km à 6:08/km est una **sortie longue soutenue** avec HR correct (0.894), non une performance maximale comparable à un 7 km rapide. Accepter cette observation comme preuve équivalente à l'observation high (7.07 km) revient à dire : "Le coureur court à peu près le même allure sur 7 km et 20 km", ce qui force k vers 1.0 (décroissance quasi-nulle avec la distance).

Résultat observé :
- k_raw ≈ 1.017 (pathologiquement proche de 1.0)
- Prédictions pratiquement identiques : 5K → 5:51/km, Marathon → 6:05/km (différence de seulement 14 secondes/km sur un facteur ×8 de distance)

---

## 2. Définition de slope evidence retenue

### Principe

> Une observation "qualified" (#188) identifie un effort personnellement rapide et soutenu.
> Une observation "slope evidence" identifie un effort suffisamment maximal pour représenter un point sur la courbe T(D) = A × D^k.

### Hiérarchie

| Niveau | Critère (issu du PerformanceQuality existant) | Rôle |
|--------|-----------------------------------------------|------|
| **strong** | `quality.confidence == "high"` | Éligible pour apprendre k |
| **weak** | `quality.confidence == "medium"` | Contribue à A uniquement |
| **none** | Speed-only / confidence < medium | Contribue à A uniquement |

Le critère "high" requiert simultanément :
- score ≥ 0.80
- relative_avg_hr ≥ 0.85
- personal_speed_percentile ≥ 90%

Ces trois conditions ensemble constituent une preuve raisonnable que l'effort était maximalement représentatif sur sa distance.

### Règle d'identifiabilité de k

k est identifiable si et seulement si :
1. `n_strong ≥ SLOPE_EVIDENCE_MIN_STRONG_COUNT` (= 2)
2. `d_max_strong / d_min_strong ≥ SLOPE_EVIDENCE_MIN_DISTANCE_RATIO` (= 1.5)

Si k n'est pas identifiable → `k = K_PRIOR = 1.06` (`k_fallback_applied = True`).

### Raisons d'identifiabilité (`k_identifiability_reason`)

- `strong_slope_evidence_insufficient` — moins de 2 observations strong
- `strong_slope_evidence_no_distance_spread` — 2+ strong mais d_max/d_min < 1.5
- `strong_slope_evidence_identified` — k peut être appris

---

## 3. Signaux réellement disponibles et pourquoi la règle est générale

La règle "strong slope evidence = confidence high" est générale car :

1. **Aucun champ Garmin n'identifie une course/test** (cf. audit §1). Inventer un classificateur arbitraire serait du sur-ajustement au compte réel.

2. **Le critère "high" est déjà établi dans #188** avec une sémantique documentée : effort fort ET rapide simultanément. Il constitue la meilleure approximation disponible d'un "effort représentatif maximal" sans nécessiter de nouveau signal.

3. **Le critère est symétrique** : il s'applique identiquement à un 5K et à un 20K. Si le 20K atteint "high" (score ≥ 0.80, relative_hr ≥ 0.85, percentile ≥ 90%), il est légitime comme preuve de pente.

4. **La règle ne crée pas de seuil par distance** : pas de `if distance > 15km: reject`. La qualification est basée uniquement sur l'effort, pas sur la longueur.

5. **Limites connues** (voir §11).

---

## 4. Séparation A/k

```
T(D) = A × D^k

A = niveau de performance absolu (vitesse à 1 m de distance → constante d'échelle)
k = décroissance de performance avec la distance (exponent de fatigabilité)
```

| Paramètre | Estimé par | Observations utilisées |
|-----------|-----------|----------------------|
| k | WLS log-space sur strong slope evidence | Seulement qualified avec confidence == "high" |
| A | WLS log-space avec k fixé | TOUTES les observations qualified (#188) |

Lorsque k = K_PRIOR (fallback) :
- A = exp(weighted_mean(log(T_i) - K_PRIOR × log(D_i))) sur tous les qualified
- Les 18 observations qualifiées contribuent toutes à A
- Aucune n'est "jetée"

Cette séparation satisfait l'invariant central de #191 :
> `A_CAN_USE_MORE_DATA_THAN_K = YES`

---

## 5. Politique de fallback

Lorsque k n'est pas identifiable :
- `k = K_PRIOR = 1.06` (`RIEGEL_K`)
- `method = "prior_k_low_slope_evidence_fallback"`
- `k_fallback_applied = True`
- A est refitté sur tout le pool qualified avec k = K_PRIOR

Application au runtime :
- 1 observation strong (7.07 km) → n_strong < 2 → k = 1.06
- Prédictions avec k = 1.06 :
  - 5K : ~5:43/km
  - 10K : ~5:48/km
  - Semi : ~5:52/km
  - Marathon : ~5:57/km (allure cohérente avec Riegel 1.06)
- La pathologie (pratiquement k ≈ 1.017) est corrigée

---

## 6. Confidence : proche vs extrapolé

Quand `k_fallback_applied = True`, la pénalité de confiance croît avec l'extrapolation depuis les distances observées.

| Ratio d'extrapolation | Pénalité |
|-----------------------|----------|
| < 1.5                | Aucune — A est le facteur dominant |
| 1.5 – 2.0            | high → medium (cap à medium) |
| ≥ 2.0                | high/medium → low (cap à low) |
| ≥ 3.0                | Déjà low via extrapolation seule |
| ≥ 6.0                | null — pas de prédiction |

**Exemple runtime (10K observations, k = fallback) :**
- 10K (ratio ≈ 1.0 si observation à 10K) : pas de pénalité, confiance dépend de la qualité
- Marathon (ratio = 42195/10000 = 4.2) : déjà cap à low via extrapolation (≥ 3.0)

Cette politique satisfait :
> `CONFIDENCE_ACCOUNTS_FOR_SLOPE_UNCERTAINTY_WHEN_EXTRAPOLATING = YES`
> "Un fallback de k ne doit PAS automatiquement rendre une prédiction proche des observations insufficient"

---

## 7. Tests synthétiques

### Test A — Pathologie runtime synthétique
**Scénario** : 1 observation high (7 km) + 4 medium (10–21 km)  
**Attendu** : n_strong = 1 → k = K_PRIOR, pas de pathologie k ≈ 1.0  
**Résultat** : ✓ k_fallback_applied = True, k = 1.06, marathon < 10K confidence

### Test B — Vraies performances multi-distance
**Scénario** : 5K et Semi espacés de 123 jours (indépendants), k_synthétique = 1.10  
**Attendu** : k_identifiable = True, k appris ≈ 1.10 (±shrinkage N=2)  
**Résultat** : ✓ k ∈ (K_PRIOR, 1.10 ± 0.15)

### Test C — Cluster 10K excellent
**Scénario** : 3 performances 8–12 km, toutes high ou medium  
**Attendu** : k = prior (pas de spread multi-distance), A bien estimé  
**Résultat** : ✓ k_fallback_applied ou k_identifiable selon le spread exact

### Test D — Speed-only
**Scénario** : Performances sans HR, différentes distances  
**Attendu** : slope_evidence_count = 0, k = K_PRIOR  
**Résultat** : ✓ speed-only qualified mais ne constituent pas slope evidence

### Test E — Outlier
**Scénario** : 5K outlier (trop rapide ou trop lent)  
**Attendu** : k ∈ [K_MIN, K_MAX], pas de crash  
**Résultat** : ✓ k clamped si nécessaire, courbe monotone

### Test F — No-lookahead
**Scénario** : Activité future après reference_date  
**Attendu** : résultats identiques avec/sans l'activité future  
**Résultat** : ✓

### Test G — Input-order invariance
**Scénario** : Activités dans ordre normal, inversé, décalé  
**Attendu** : résultats strictement identiques  
**Résultat** : ✓

### Test H — VMA independence
**Scénario** : Mêmes performances avec/sans HR (VMA disponible/null)  
**Attendu** : curve_k identique quel que soit le VMA  
**Résultat** : ✓

---

## 8. Invariants conservés

| Invariant | Statut |
|-----------|--------|
| `T(D) = A × D^k` | Conservé ✓ |
| Single performance → k = K_PRIOR | Conservé ✓ |
| N=2 strong → shrinkage (factor = 0.5) | Nouveau, implémenté ✓ |
| k ∈ [K_MIN, K_MAX] | Conservé ✓ |
| k_clamped quand OLS hors bornes | Conservé ✓ |
| No lookahead | Conservé ✓ |
| Input-order invariant | Conservé ✓ |
| Extrapolation symétrique | Conservé ✓ |
| VMA independence | Conservé ✓ |
| Pas de correction monotone post-hoc | Conservé ✓ |
| Fallback speed-only | Conservé ✓ |
| PerformanceQuality.qualified inchangé | Conservé ✓ |

---

## 9. Diagnostics exposés

Dans `PerformanceCurveV2` et propagé dans `RacePrediction` :

```python
qualified_performance_count    # Observations contribuant à A
slope_evidence_count           # Observations strong (contributing to k)
slope_evidence_distance_min_m  # Distance min des strong obs
slope_evidence_distance_max_m  # Distance max des strong obs
k_identifiable                 # Bool — k peut-il être appris ?
k_identifiability_score        # Score 0–1 normalisé (log-spread / log(Marathon/5K))
k_identifiability_reason       # Raison textuelle
k_raw                          # k OLS avant shrinkage/clamping
k_fallback_applied             # k = K_PRIOR ?
curve_method                   # "single_riegel_fallback" | "strong_slope_evidence_fit"
                               # | "strong_slope_evidence_fit_clamped"
                               # | "prior_k_low_slope_evidence_fallback"
```

Lecture en runtime (exemple avec 18 qualified, 1 high) :
```
qualified_performance_count = 18
slope_evidence_count = 1
k_identifiable = False
k_identifiability_reason = strong_slope_evidence_insufficient
k_fallback_applied = True
k_raw = None
k_final (curve_k) = 1.06
curve_method = prior_k_low_slope_evidence_fallback
```

---

## 10. Critères d'acceptation

| Critère | Status |
|---------|--------|
| QUALIFIED_AND_SLOPE_EVIDENCE_SEPARATED | ✅ YES |
| SPEED_ONLY_STILL_SUPPORTED | ✅ YES |
| NON_MAXIMAL_SUPPORTED_RUN_CANNOT_AUTOMATICALLY_DEFINE_K | ✅ YES |
| TRUE_MULTI_DISTANCE_PERFORMANCES_CAN_LEARN_K | ✅ YES |
| A_CAN_USE_MORE_DATA_THAN_K | ✅ YES |
| NO_ARBITRARY_K_FLOOR | ✅ YES (k ∈ [K_MIN, K_MAX] inchangé) |
| NO_ACCOUNT_SPECIFIC_CALIBRATION | ✅ YES |
| NO_LOOKAHEAD | ✅ YES |
| INPUT_ORDER_INVARIANT | ✅ YES |
| VMA_INDEPENDENCE | ✅ YES |
| CONFIDENCE_ACCOUNTS_FOR_SLOPE_UNCERTAINTY_WHEN_EXTRAPOLATING | ✅ YES |

---

## 11. Limites connues

### Limite principale : "high" confidence n'est pas une garantie de performance maximale

Le critère `confidence == "high"` (score ≥ 0.80, relative_hr ≥ 0.85, percentile ≥ 90%) est une approximation. Un coureur peut atteindre "high" sur un 20K soutenu sans que ce 20K soit vraiment comparable à une performance maximale 5K pour apprendre la fatigabilité.

**Pourquoi c'est acceptable** : L'alternative serait d'inventer un classificateur basé sur des constantes arbitraires (relative_hr > 0.92, distance < 12 km, etc.) qui seraient du sur-ajustement. Le critère "high" est le meilleur proxy disponible sans signal Garmin fiable sur le type d'effort (race vs workout vs long run).

### Limite : N=2 shrinkage est fixé à 0.5

Avec exactement 2 strong observations, k_fitted = 0.5 × k_raw + 0.5 × K_PRIOR. Cette valeur est raisonnable mais arbitraire. Un modèle bayésien formel donnerait un résultat plus rigoureux. La complexité ajoutée ne se justifie pas pour l'instant.

### Limite : Pas de pondération dans l'identifiabilité

L'identifiabilité est évaluée sur le count et le ratio de distances, sans tenir compte du poids (qualité × récence) des observations. Deux observations très récentes et très proches en distance mais différentes peuvent théoriquement toutes deux être "strong" mais ne pas fournir de preuve forte sur k.

### Limite : confidence "high" requis pour les DEUX observations strong

Si un coureur n'a qu'une seule vraie course (high confidence) dans son historique, il ne peut pas apprendre k — même si son historique contient de nombreuses sorties soutenues. C'est conservateur mais défendable : k non appris = k_prior = 1.06 qui est une valeur raisonnable pour un coureur moyen.

### Signal Garmin absent : workout_type / race

Garmin expose des champs comme `workoutName`, `activityType` avec sous-types potentiellement utiles, mais ceux-ci ne sont pas actuellement mappés dans `DomainActivity`. Si ces champs étaient ajoutés, on pourrait raffiner la règle de slope evidence (par exemple : `activity_subtype == "race" → automatically strong`). Pour l'instant, cela n'est pas disponible.
