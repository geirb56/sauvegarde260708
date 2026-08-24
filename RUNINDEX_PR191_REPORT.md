# RUNINDEX — PR #191 (AUDIT PHASE) — Performance Comparability / Slope Evidence

**Statut : AUDIT LECTURE SEULE TERMINÉ — implémentation NON réalisée (barrière STOP de la tâche atteinte).**
Aucun code moteur, aucune donnée, aucune constante modifiés. Compte réel : `da85***e7e7`. HEAD `0c17a2d` (PR #189/#190 mergées).

---

## 1. Audit des 5 observations high/medium (runtime réel, no-lookahead)

| date | dist | pace | avgHR | maxHR | **avgHR/maxHR** | **speed reserve (max/avg−1)** | vigMin/dur | elev/km | rel_hr(FCmax hist) | pctl90 | quality | tier |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2025-12-14 | 10.02 | 5:01 | 163 | 174 | **0.937** | **11.8 %** | 47/50 | 6.0 | 0.916 | 100 | 1.00 | **high** |
| 2026-01-09 | 7.07 | 5:54 | 158 | 179 | 0.883 | 39.9 % | 33/42 | 2.5 | 0.888 | 85 | 0.887 | medium |
| 2026-02-28 | 20.63 | 6:08 | 160 | 182 | 0.879 | 28.7 % | 123/127 | 6.5 | 0.894 | 75 | 0.865 | medium |
| 2025-11-06 | 10.83 | 5:55 | 149 | 176 | 0.847 | 35.5 % | 41/65 | 3.0 | 0.842 | 87 | 0.728 | medium |
| 2026-04-20 | 10.44 | 6:21 | 153 | 172 | 0.890 | 15.3 % | 56/67 | 5.2 | 0.841 | 72.7 | 0.660 | medium |

**Lecture** : la seule observation ressemblant à un contre-la-montre maximal (2025-12-14) se distingue par `avgHR/maxHR ≈ 0.94` (couru près du max, faible réserve HR) **et** une allure très régulière (`speed reserve ≈ 12 %`). Les 4 medium sont des sorties soutenues à allure variable (`avgHR/maxHR 0.85–0.89`, `speed reserve 29–40 %`).

## 2. Pourquoi #190 juge k identifiable aujourd'hui
`_compute_k_identifiability` = variance pondérée de `log(distance)` sur le sous-ensemble **high+medium**. Ici ce sous-ensemble couvre 7.07 → 20.63 km ⇒ score 0.147 ≥ seuil 0.05 ⇒ `k_identifiable=true`. Mais 4 des 5 points sont des **sorties soutenues non maximales** dont la relation distance→temps est presque plate (20.63 km @ 6:08 ≈ 7.07 km @ 5:54). Le spread de distance est réel, mais la **comparabilité de performance** ne l'est pas. C'est le défaut résiduel visé par #191.

## 3. Signaux Garmin réellement disponibles (CONSTAT CENTRAL)
Champs présents sur `garmin_activity` : `activity_type, distance_m, duration_s, moving_duration_s, average_speed_mps, average_moving_speed_mps, max_speed_mps, average_hr, max_hr, min_hr, average/max_run_cadence, elevation_gain/loss, calories, moderate/vigorous_intensity_minutes, lap_count, has_splits, details_available`.

**Aucun signal fiable de maximalité / course n'existe :**
- `activity_type` = uniquement running/walking/cycling/indoor_cardio/breathwork — **pas de sous-type « race »**.
- **Absents** : `event_type`, `is_race`, `workout_type`, `trainingEffectLabel`, race predictor natif.
- `lap_count`, `has_splits`, `details_available` = **null sur 100 % des documents** ⇒ pas de laps structurés exploitables (impossible de détecter un test/intervalles).

Signaux **dérivés** discriminants observés (non natifs) : `avgHR/maxHR` (réserve HR intra-activité) et régularité d'allure (`max/avg speed`). Ils séparent bien le CLM du reste **sur ce compte**, mais il n'y a **qu'UN seul exemple maximal positif** ⇒ en faire un seuil général = calibration spécifique au compte, **explicitement interdite** par la tâche.

## 4. DÉCISION : STOP après audit (conforme à la RÈGLE ABSOLUE)
> « Si les données disponibles ne permettent PAS de distinguer proprement une performance maximale d'une sortie soutenue : NE PAS inventer un classificateur. STOP après l'audit et proposer les options architecturales les plus simples avec leurs limites. »

Les données Garmin **ne fournissent aucun marqueur natif de maximalité**, et les proxies dérivés ne peuvent pas être transformés en règle générale sans calibration mono-compte. On **ne code pas de classificateur**. On propose ci-dessous les options les plus simples, générales, sans seuils arbitraires.

## 5. Options architecturales (les plus simples, générales, sans calibration compte)

### OPTION 1 — slope_evidence = tier HIGH de #188 (RECOMMANDÉE)
- **Politique** : `slope_evidence = (quality.confidence == "high")`. L'identifiabilité #190 est recalculée **uniquement** sur le sous-ensemble slope-evidence. Si < seuil de spread (ou < 2 points) ⇒ `method = prior_k_low_slope_evidence_fallback`, `k = 1.06`, A recalculé à pente fixe sur **les 18 observations qualifiées**.
- **Général** : réutilise le tier HIGH existant de #188 (HR-appuyé + score combiné élevé) — **aucun nouveau seuil**. HIGH est déjà le plus proche d'un effort représentatif.
- **A vs k** : les 18 qualifiées informent A ; seules les HIGH informent k. Invariant central respecté.
- **Effet sur ce compte** : 1 seule HIGH ⇒ preuve de pente insuffisante ⇒ k=1.06 ⇒ courbe plus physiologique (5K plus rapide, marathon plus lent), et A conservé sur 18 obs.
- **Limite** : dépend de la couverture HR (le tier HIGH exige la FC) ; un athlète sans max_hr fiable n'aura jamais de slope-evidence ⇒ prior 1.06 permanent (acceptable et honnête).

### OPTION 2 — slope_evidence = HIGH + gate de représentativité intra-activité
- Ajoute un critère `avgHR/maxHR ≥ seuil` et régularité d'allure.
- **Rejetée pour l'instant** : introduit ≥2 nouveaux seuils calibrés sur 1 exemple ⇒ risque de sur-ajustement au compte, non démontrable comme général. À reconsidérer seulement avec un dataset multi-athlètes.

### OPTION 3 — poids de slope-evidence continu (élégante, sans cutoff dur)
- `slope_evidence_weight = map(confidence)` : high=1.0, medium=0.3, low/speed-only=0.0 (réutilise la hiérarchie #188, pas de nouveau seuil). L'identifiabilité et le fit de k sont pondérés par ce poids ; A garde ses poids actuels.
- **Général**, pas de booléen brutal, dégradé propre. Sur ce compte : la masse de slope-evidence (≈1.0 + 4×0.3 mais medium non maximaux) reste faible ⇒ identifiabilité faible ⇒ prior 1.06.
- **Limite** : le mapping high/medium/low reste un choix de conception (mais aligné sur #188, non spécifique au compte).

**Recommandation** : **Option 1** (la plus simple et la plus défendable), avec Option 3 en variante si l'on préfère un dégradé continu.

## 6. Correctif du gap de confidence (local, si implémenté)
`_curve_prediction_confidence()` doit ajouter une pénalité liée au **fallback de pente qui CROÎT avec l'extrapolation** : aucune pénalité pour une cible proche des observations (10K si obs autour de 10 km), pénalité croissante pour semi/marathon. Distinguer confiance(A) vs confiance(k) vs extrapolation. Ne PAS rendre « insufficient » une prédiction proche uniquement parce que k est en fallback.

## 7. Invariants à préserver lors d'une future implémentation
`T(D)=A·D^k` · single→prior 1.06 · N=2 shrinkage · k-conflict fallback #190 · Huber quality-aware #190 · refit robuste final · extrapolation symétrique · no-lookahead · input-order invariance · VMA independence · aucune correction monotone post-hoc · **aucun k-floor arbitraire** · **aucune calibration spécifique au compte**.

## 8. Limites connues
- Impossible de certifier « performance maximale » sans signal natif Garmin ⇒ toute slope-evidence reste un **proxy de qualité comparative**, pas une preuve de maximalité.
- Avec peu d'efforts HR-appuyés multi-distances, le modèle retombera souvent sur le prior 1.06 (comportement voulu et honnête).
