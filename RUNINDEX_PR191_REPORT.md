# RUNINDEX — PR #191 — Performance Comparability / Slope Evidence (IMPLÉMENTÉ — Option 1)

**Statut : IMPLÉMENTÉ (Option 1).** Distinction QUALIFIED (niveau A) vs SLOPE-EVIDENCE (apprentissage de k).
Compte réel : `da85***e7e7`. Backend redémarré, endpoints 200, tests verts. `PerformanceQuality.qualified` inchangé.

## 1. Audit des 5 observations high/medium (rappel)
| date | dist | pace | avgHR/maxHR | speed reserve | rel_hr | tier |
|---|---|---|---|---|---|---|
| 2025-12-14 | 10.02 | 5:01 | **0.937** | **11.8 %** | 0.916 | **high** |
| 2026-01-09 | 7.07 | 5:54 | 0.883 | 39.9 % | 0.888 | medium |
| 2026-02-28 | 20.63 | 6:08 | 0.879 | 28.7 % | 0.894 | medium |
| 2025-11-06 | 10.83 | 5:55 | 0.847 | 35.5 % | 0.842 | medium |
| 2026-04-20 | 10.44 | 6:21 | 0.890 | 15.3 % | 0.841 | medium |
Seul le 2025-12-14 ressemble à un effort maximal (près de la FCmax, allure régulière). Les 4 medium sont des sorties soutenues.

## 2. Pourquoi #190 croyait k identifiable
Identifiabilité calculée sur high+medium (spread 7–20.6 km, score 0.147 ≥ 0.05). Or les medium sont des sorties non maximales à relation distance→temps quasi plate ⇒ k plat (1.0174). Défaut résiduel corrigé ici.

## 3. Signaux Garmin disponibles
**Aucun signal natif de maximalité/course** (`activity_type`=running seul ; pas d'`event_type`/`is_race`/`workout_type` ; `lap_count`/`has_splits`/`details_available`=null partout). Décision : ne PAS inventer de classificateur, réutiliser le tier `high` de #188 comme preuve de pente.

## 4. Définition retenue (slope evidence)
`slope_evidence = (PerformanceQuality.confidence == "high")`. Le tier `high` de #188 exige déjà un appui FC + score combiné élevé (proche d'un effort représentatif). Medium/low/speed-only **contribuent toujours à A** mais ne sont jamais, seuls, une preuve de pente. **Aucun nouveau seuil arbitraire** (réutilise la hiérarchie #188).

## 5. Politique d'apprentissage de k (générale)
Chemin N≥3 (`robust_weighted_log_fit`) :
1. Sous-ensemble slope-evidence = observations `high`.
2. `k_identifiable = (slope_evidence_count ≥ K_SLOPE_EVIDENCE_MIN_COUNT=2) ET (variance pondérée de log(distance) sur les high ≥ 0.05)`.
3. Si non identifiable ⇒ `method = prior_k_low_slope_evidence_fallback`, `k = RIEGEL_K (1.06)`, **A recalculé** à pente fixe sur les poids robustes de **toutes** les observations qualifiées. `k_raw` conserve la pente apprise (diagnostic).
4. Priorité inchangée : `k_conflict fallback` (#190) reste évalué en premier depuis `k_raw`.
5. N=1 (Riegel prior) et N=2 (shrinkage) inchangés.

Raisons possibles : `insufficient_slope_evidence_count`, `insufficient_slope_evidence_spread`, `sufficient_slope_evidence_spread`, `no_slope_evidence_observations`, `not_applicable`.

## 6. Séparation A / k (invariant central)
- **A** (niveau) = intercept estimé sur **toutes** les qualifiées (18 sur le compte réel).
- **k** (fatigabilité distance→temps) = appris **uniquement** depuis les slope-evidence high ; sinon prior 1.06.
- Les 18 observations ne sont jamais jetées.

## 7. Confidence — correctif du gap #190 (local)
Ajout dans `_curve_prediction_confidence` d'une pénalité liée au fallback slope **croissante avec l'extrapolation** :
- `extrapolation_ratio ≤ 1.2` (proche des observations) ⇒ +0 (une bonne prédiction 10K reste bonne).
- `1.2 < ratio ≤ 1.8` ⇒ +1 ; `ratio > 1.8` ⇒ +2 (marathon davantage pénalisé car il dépend fortement du prior k).
Distinction A / k / extrapolation respectée ; pas de pénalité uniforme aveugle.

## 8. Runtime réel post-#191 (compte da85***e7e7)
```
slope_evidence_count = 1 (10.018 km)  → < 2  → insufficient_slope_evidence_count
method = prior_k_low_slope_evidence_fallback   k = 1.06   k_raw = 1.017409 (conservé)
qualified_performance_count = 18 (A inchangé)
Prédictions : 5K 28:26 (5:41) · 10K 59:18 (5:55) · Semi 2h10 (6:12) · Marathon 4h32 (6:27)
Spread 5K→Marathon = 46 s/km (physiologique), vs 13 s/km pré-#191.
```
La pathologie de courbe plate est corrigée : faute de preuve multi-distance, k retombe honnêtement sur le prior 1.06 et le niveau A reste calibré sur les 18 observations.

## 9. Tests synthétiques (`tests/test_pr191_slope_evidence.py`, 7 passed)
- A : 1 high + medium/low étalés ⇒ pas d'apprentissage auto de k (fallback 1.06).
- B : 3 vraies perfs 5/10/21 km suivant k=1.11 ⇒ k appris ≈1.11 (pas Riegel permanent).
- C : cluster ~10 km high ⇒ A estimé, k reste prior (spread insuffisant).
- D : speed-only ⇒ contribue à A, ne définit pas k.
- E : outlier high absurde ⇒ Huber protège, k reste proche du vrai.
- F : no-lookahead (futur exclu). G : input-order invariance.
(#189 VMA-independence conservé dans sa suite.)

## 10. Invariants conservés
`T(D)=A·D^k` · single→prior 1.06 · N=2 shrinkage · k_conflict fallback #190 · Huber quality-aware #190 · refit robuste final · extrapolation symétrique · no-lookahead · input-order invariance · VMA independence · aucune correction monotone post-hoc · aucun k-floor arbitraire · aucune calibration spécifique au compte.

## 11. Limites connues
- Slope-evidence = proxy de qualité (tier high #188), pas une preuve certaine de maximalité (aucun signal natif Garmin).
- Dépend de la couverture FC : sans max_hr fiable, un athlète n'aura jamais de slope-evidence ⇒ prior 1.06 permanent (honnête).
- Sur ce compte, faute de perf multi-distance HR-appuyée, k reste au prior : c'est le comportement voulu, pas un bug.

## Critères d'acceptation
```
QUALIFIED_AND_SLOPE_EVIDENCE_SEPARATED = YES
SPEED_ONLY_STILL_SUPPORTED = YES
NON_MAXIMAL_SUPPORTED_RUN_CANNOT_AUTOMATICALLY_DEFINE_K = YES
TRUE_MULTI_DISTANCE_PERFORMANCES_CAN_LEARN_K = YES
A_CAN_USE_MORE_DATA_THAN_K = YES
NO_ARBITRARY_K_FLOOR = YES
NO_ACCOUNT_SPECIFIC_CALIBRATION = YES
NO_LOOKAHEAD = YES
INPUT_ORDER_INVARIANT = YES
VMA_INDEPENDENCE = YES
CONFIDENCE_ACCOUNTS_FOR_SLOPE_UNCERTAINTY_WHEN_EXTRAPOLATING = YES
```
