# R2B — Readiness Final Aggregation V2 — PR Report

## 1. HEAD de départ

```
f9bada97d72d4e159c2e7f6cc86781b110efe82c
Merge pull request #116 — R2A Readiness Subscores V2
```

## 2. Fichiers modifiés

| Action | Fichier |
|--------|---------|
| Créé | `backend/training_v2/readiness.py` |
| Modifié | `backend/training_v2/__init__.py` |
| Créé | `backend/tests/test_training_v2_readiness.py` |
| Modifié | `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md` |
| Créé | `docs/R2B_REPORT.md` (ce fichier) |

## 3. Contrat ReadinessResult

```python
class ReadinessConfidence(str, Enum):
    NONE = "NONE"
    NORMAL = "NORMAL"
    REDUCED = "REDUCED"

class ReadinessResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    score: Optional[float]            # 0–100 (1 décimale) ou None
    confidence: ReadinessConfidence   # catégoriel uniquement, jamais numérique
    sufficiency_level: SufficiencyLevel   # propagé depuis R1
    reasons: List[ReasonCode]             # propagé depuis R1 à l'identique
```

## 4. Poids produit V1

```python
PRODUCT_CALIBRATION_V1_WEIGHT_PHYSIO: float = 40.0
PRODUCT_CALIBRATION_V1_WEIGHT_SLEEP:  float = 30.0
PRODUCT_CALIBRATION_V1_WEIGHT_LOAD:   float = 30.0
```

> Product calibration V1, recalibratable, not a scientifically proven universal weighting.

## 5. Règles SUFFICIENT / DEGRADED / INSUFFICIENT

### CAS 1 — INSUFFICIENT

```
sufficiency.level == INSUFFICIENT
→ score = None
→ confidence = NONE
→ reasons = propagées depuis R1
```
Même si des sous-scores sont fournis, aucun calcul n'est tenté.

### CAS 2 — SUFFICIENT + 3 sous-scores présents

```
score = (physio×40 + sleep×30 + load×30) / 100
confidence = NORMAL
```

Exemple : physio=80, sleep=90, load=70
→ (80×40 + 90×30 + 70×30) / 100 = 80.0

### CAS 2b — SUFFICIENT + sous-score(s) manquant(s)

```
score = Σ(valeur_i × poids_i) / Σ(poids_i)   (renormalisé)
confidence = REDUCED
sufficiency_level = SUFFICIENT  (inchangé)
```

Exemple : physio=80, sleep=None, load=70
→ (80×40 + 70×30) / (40+30) = 5300/70 ≈ 75.7

### CAS 3 — DEGRADED

Renormalisation automatique sur les poids des sous-scores disponibles uniquement.

```
score = Σ(valeur_i × poids_i) / Σ(poids_i)
confidence = REDUCED
```

Exemple : physio=70, sleep=None, load=80
→ (70×40 + 80×30) / (40+30) = 5200/70 ≈ 74.3

### CAS DÉFENSIF

```
SUFFICIENT/DEGRADED + aucun sous-score utilisable
→ score = None
→ confidence = NONE
```
Jamais 0 par défaut.

## 6. Stratégie de renormalisation

- Seuls les sous-scores non-`None` participent au calcul.
- Le diviseur est la somme des poids effectivement utilisés (non le total 100).
- Aucune imputation : 0, 50, 70, 100 ou toute valeur fictive sont interdits.
- Le résultat est clampé `[0, 100]` puis arrondi à 1 décimale via `round(x, 1)`.

## 7. Comportement None

- `None` entre → `None` sort. Pas de valeur de remplacement.
- Un sous-score `None` est exclu du calcul (il ne contribue ni au numérateur ni au dénominateur).
- Un résultat `None` n'est jamais converti en `0`.

## 8. Confidence catégorielle

La confidence est **toujours** un `ReadinessConfidence` (str Enum).

| Niveau | Confidence |
|--------|-----------|
| INSUFFICIENT | NONE |
| SUFFICIENT + 3 sous-scores présents | NORMAL |
| SUFFICIENT + sous-score(s) manquant(s) | REDUCED |
| DEGRADED + score calculable | REDUCED |
| Défensif (pas de sous-score) | NONE |

Aucune valeur numérique (ex : `0.82`, `82`) n'est produite ni acceptée.

## 9. Tests exécutés

Suite : `backend/tests/test_training_v2_readiness.py`

Classes de tests :
- `TestInsufficient` (6 tests)
- `TestSufficient` (6 tests)
- `TestSufficientWithMissingSubscores` (5 tests)
- `TestDegraded` (5 tests)
- `TestDefensive` (3 tests)
- `TestArchitectureInvariants` (14 tests)

Total : **39 tests**

## 10. Résultats

```
39 passed in 0.49s
```

✅ Tous les tests passent.

## 11. Confirmation aucune migration produit

- `/api/run-index` : **non modifié**
- `/training/today` : **non modifié**
- Dashboard / Progress / Frontend : **non modifiés**
- Garmin sync / Terra : **non modifiés**
- Legacy Readiness : **non supprimé, non modifié**
- `TrainingLoad` / `ReadinessSubscores` (R2A) : **non modifiés**

R2B est strictement **additive**.

## 12. Confirmation aucun fallback legacy

- Aucun import de `backend/garmin/insights.py`
- Aucun import de `backend/engine/readiness_engine.py`
- Aucune valeur fictive : sleep=7h, RHR=55, ACWR=1, readiness=70/100
- Aucun champ : recommendation, status, color, fatigue_ratio, Recovery Time, TRIMP, TSS, EPOC, LT1/LT2

## 13. État du document canonique

Fichier : `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`

- **Last verified against main** : `f9bada97d72d4e159c2e7f6cc86781b110efe82c` ✅
- **R2A** : MERGED — PR #116 ✅
- **R2B** : IMPLEMENTED IN PR / PENDING MERGE ✅
- **NEXT** : R3 — Migration Readiness V2 into /run-index ✅
- **Threshold Estimator V1** : cibles explicites LT1/LT2 avec tolérance bpm et métrique coverage séparée ✅

---

*R2B n'est pas mergé. Ce rapport est produit au moment de l'ouverture de la PR.*
