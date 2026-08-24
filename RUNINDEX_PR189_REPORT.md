# RUNINDEX PR189 REPORT (POST-AUDIT FIXES)

## 1) ARCHITECTURE FINALE
- Pipeline conservé: `DomainActivity → qualification #188 → QualifiedPerformance[] → Performance Curve V2 → 5K / 10K / Semi / Marathon`.
- Courbe unique conservée: `T(D) = A × D^k`.
- Aucune correction monotone post-hoc target-to-target.
- Aucune dépendance directe à la sortie VMA/VO₂max pour calculer les prédictions de course (la qualification #188 peut dépendre de la FCmax via la FC relative).

## 2) COMPORTEMENT 1 PERFORMANCE
- Méthode: `single_performance_riegel`.
- Exposant fixé: `k = 1.06`.
- Paramètre: `A = T_source / D_source^1.06`.

## 3) COMPORTEMENT EXACTEMENT 2 PERFORMANCES
- Politique explicite: `two_point_prior_shrinkage_fit`.
- `k_raw` géométrique:
  - `k_raw = (log(T2) - log(T1)) / (log(D2) - log(D1))`
- Force de preuve déterministe:
  - poids d’observation: `w_i = quality_score_i × recency_weight_i × quality_confidence_weight_i`
  - `evidence_strength = sqrt(clamp(w1,0,1) × clamp(w2,0,1))`
  - donc `0 <= evidence_strength <= 1`
- Shrinkage:
  - `k = 1.06 + evidence_strength × (k_raw - 1.06)`
- Intercept cohérent avec la pente imposée:
  - `log(A) = sum_i w_i × (log(T_i) - k × log(D_i)) / sum_i w_i`

## 4) COMPORTEMENT >=3 PERFORMANCES
- Base: régression linéaire pondérée en espace log.
- Robustesse: reweighting Huber (2 itérations max) sur résidus log.
- **Refit final obligatoire appliqué** avec les poids robustes finaux.

## 5) ROBUST FITTING
- Résidus robustes: `r_i = y_i - (b0 + b1 x_i)`.
- Seuil Huber: `delta = 1.5 × median(|r_i|)`.
- Multiplicateur robuste:
  - `1` si `|r_i| <= delta`
  - `delta/|r_i|` sinon
- Poids robustes finaux: `w_i^robust = w_i^base × huber_mult_i`.

## 6) REFIT FINAL (BLOCKER HUBER)
- Après la dernière mise à jour des poids robustes, refit final effectué avec **ces poids finaux**.
- Les diagnostics (`fit_quality`), résidus implicites, contributors et poids robustes décrivent le même modèle final.
- Invariant visé: courbe/poids/résidus/diagnostics alignés.

## 7) FALLBACK DE k
- Guardrails conservés:
  - `CURVE_K_MIN = 1.0`
  - `CURVE_K_MAX = 1.25`
- Statut: garde-fous métier RunIndex conservateurs (pas des constantes physiologiques universelles).
- Si `k` hors borne: `prior_k_conflict_fallback`, avec `k = 1.06` et `k_conflict = true`.

## 8) RECALCUL DE A LORS D’UN FALLBACK k
- Quand `k` est forcé (fallback conflit), `A` est réestimé avec la pente forcée:
  - `log(A) = sum_i w_i × (log(T_i) - 1.06 × log(D_i)) / sum_i w_i`
- Le fallback ne réutilise pas l’intercept invalide.

## 9) POLITIQUE D’EXTRAPOLATION
- Ratio symétrique conservé:
  - `ratio = min_observed max(target/observed, observed/target)`
- Seuils conservés en politique RunIndex:
  - `> 4.5` zone très incertaine (confidence fortement réduite),
  - `> 6.0` rejet (prediction `null`).

## 10) CONFIDENCE
- La confidence est calculée sur **l’ensemble des contributeurs finaux** de la courbe, pondérés par `robust_weight`.
- Formules d’agrégats (contributeurs finaux `i`):
  - `w_i = robust_weight_i`
  - `p_i = w_i / Σw`
  - `weighted_recency = Σ p_i × recency_weight(days_ago_i)`
  - `weighted_quality_confidence = Σ p_i × quality_confidence_weight(confidence_i)`
  - `weighted_quality_score = Σ p_i × clamp(score_i, 0, 1)`
  - `effective_contributors = (Σw)^2 / Σ(w^2)`
- Politique des niveaux conservée: `high | medium | low | insufficient`.
- Signaux pris en compte: extrapolation, `fit_quality`, `k_conflict`, `weighted_recency`, `weighted_quality_confidence`, `weighted_quality_score`, `effective_contributors`.
- Invariants appliqués:
  - 1 seul contributor: jamais `high`.
  - Conflit `k` (`k_conflict=true`): dégradation.
  - Mauvais `fit_quality`: dégradation.
  - Extrapolation forte: dégradation.
  - Extrapolation excessive: `null` / `insufficient`.

## 11) CONTRAT API `/api/training/race-predictions`
- Compatibilité conservée: champs historiques principaux maintenus.
- Nouveaux champs exposés au niveau prédiction:
  - `predicted_time_s`,
  - `extrapolation_ratio`,
  - `is_strong_extrapolation`,
  - `curve_method`,
  - `curve_k`,
  - `contributors_count`.
- Diagnostics courbe exposés:
  - `curve_method`, `curve_a`, `curve_k`, `curve_k_raw`, `curve_k_prior`,
  - `curve_k_min`, `curve_k_max`,
  - `contributors_count`, `qualified_performance_count`,
  - `observed_distance_min(_km)`, `observed_distance_max(_km)`,
  - `fit_quality`, `k_conflict`, `k_fallback_applied`,
  - `weighted_recency`, `weighted_quality_confidence`, `weighted_quality_score`, `effective_contributors`,
  - `two_point_evidence_strength`, `contributors[]`.

## 12) ABSENCE DE DÉPENDANCE VMA
- Invariant exact:
  - « Les Race Predictions ne dépendent pas de la sortie du modèle VMA ni du VO₂max estimé. Elles sont calculées à partir du pool de performances qualifiées #188 et de la Performance Curve. La qualification #188 peut en revanche légitimement dépendre de la FCmax via la FC relative. »
- Le test d’indépendance VMA est architectural:
  - activités de qualification fixées,
  - FCmax fixé,
  - qualification #188 et pool qualifié inchangés,
  - courbe inchangée,
  - seule la sortie `estimate_vma()` est mutée (None / basse / élevée / confidence différente),
  - vérification d’invariance des chronos 5K/10K/Semi/Marathon + `curve_k` + `curve_method`.

## 13) ABSENCE DE CORRECTION MONOTONE POST-HOC
- Aucune logique type `max(previous_time, current_time)` ou clamp target-to-target.
- La monotonie provient de la courbe commune `T(D)=A×D^k` avec garde-fous de `k`.

## 14) LIMITES CONNUES
- Les bornes `k` et seuils extrapolation (4.5/6.0) sont des politiques produit RunIndex.
- Elles peuvent évoluer avec des audits supplémentaires multi-profils.
- `fit_quality` est un indicateur utile mais n’est pas, seul, une preuve de validité physiologique universelle.
