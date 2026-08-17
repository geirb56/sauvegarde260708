# RUNINDEX PR #133 — Daily Adaptation V2

## Delivery

| Item | Value |
|---|---|
| PR | #133 — Daily Adaptation V2 |
| HEAD main au départ | `beee570281920b4681e96d3559e8777121b6ffa9` |
| #132 | MERGED |
| Status | IMPLEMENTED / PENDING MERGE |

---

## Fichiers modifiés

| Fichier | Action |
|---|---|
| `backend/training_v2/readiness_decision.py` | NEW: couche canonique `ReadinessBand` / `ReadinessDecision` / `build_readiness_decision()` |
| `backend/training_v2/daily_adaptation.py` | Updated: consomme `ReadinessDecision`, aucun seuil local Readiness |
| `backend/training_v2/__init__.py` | Updated: exports readiness decision |
| `backend/tests/test_training_v2_readiness_decision.py` | NEW: tests seuils et métadonnées de la couche canonique |
| `backend/tests/test_daily_adaptation_pr133.py` | Updated: tests PR133 via la couche canonique + garde-fous d’architecture |
| `RUNINDEX_PR133_REPORT.md` | Updated: rapport corrigé |
| `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md` | Updated: architecture canonique `ReadinessResult -> ReadinessDecision -> DailyAdaptation` |

---

## Architecture canonique

```text
ReadinessResult
      ↓
ReadinessDecision
      ↓
DailyAdaptation
```

Décision permanente :

> Les consumers ne définissent jamais leurs propres bandes Readiness.

PR #133 introduit une calibration produit V1 canonique de bandes Readiness,
centralisée dans `ReadinessDecision` afin qu’aucun consumer ne recrée ses
propres seuils.

---

## Contrat ReadinessBand

```python
class ReadinessBand(str, Enum):
    UNAVAILABLE = "UNAVAILABLE"
    FAVORABLE = "FAVORABLE"
    CAUTION = "CAUTION"
    LOW = "LOW"
    VERY_LOW = "VERY_LOW"
```

## Contrat ReadinessDecision

```python
class ReadinessDecision(BaseModel):
    model_config = ConfigDict(frozen=True)

    band: ReadinessBand
    score: Optional[float]
    confidence: ReadinessConfidence
    sufficiency_level: SufficiencyLevel
    reason_codes: tuple[str, ...]
    readiness_reasons: tuple[ReasonCode, ...]
```

## Fonction canonique

```python
build_readiness_decision(
    readiness: Optional[ReadinessResult]
) -> ReadinessDecision
```

---

## Calibration produit V1 canonique

Seuils centralisés uniquement dans :

- `backend/training_v2/readiness_decision.py`

Constantes :

- `READINESS_FAVORABLE_MIN = 75.0`
- `READINESS_CAUTION_MIN = 55.0`
- `READINESS_LOW_MIN = 40.0`

Statut :

- PRODUCT CALIBRATION V1
- RECALIBRABLE
- NOT PHYSIOLOGICAL LAW

---

## Règles canoniques ReadinessDecision

- `readiness is None` → `UNAVAILABLE`
- `readiness.score is None` → `UNAVAILABLE`
- `readiness.sufficiency_level == INSUFFICIENT` → `UNAVAILABLE`
- `score >= 75` → `FAVORABLE`
- `55 <= score < 75` → `CAUTION`
- `40 <= score < 55` → `LOW`
- `score < 40` → `VERY_LOW`

### Règle INSUFFICIENT

`INSUFFICIENT` reste une règle de disponibilité de données, pas un état
physiologique :

- `INSUFFICIENT` → `UNAVAILABLE`
- jamais `VERY_LOW`

### Comportement DEGRADED

- si un score exploitable existe, la bande est calculée normalement ;
- `confidence` est préservée ;
- `sufficiency_level=DEGRADED` est préservé ;
- aucun recalcul de sufficiency.

---

## DailyAdaptation final

`DailyAdaptation` :

- consomme `WorkoutPrescription`, `ReadinessDecision`, `TrainingLoadSnapshot`,
  `RecentTrainingResponse` ;
- ne connaît aucun seuil numérique Readiness ;
- ne compare jamais directement `readiness.score` ;
- peut uniquement **garder** ou **réduire** (`KEEP`, `EASY_DOWNGRADE`,
  `SHORTEN`, `REST`) ;
- n’implémente aucun `MOVE` ;
- n’augmente jamais une séance.

### Matrice finale

- planned rest → `KEEP`
- `FAVORABLE` → généralement `KEEP`
- `CAUTION` / `LOW` + `quality|steady` → `EASY_DOWNGRADE`
- `CAUTION` / `LOW` + `easy|recovery` → `SHORTEN`
- `CAUTION` / `LOW` + `long_easy` → `SHORTEN`
- `VERY_LOW` → `REST`
- `UNAVAILABLE` → jamais `REST` automatique ; comportement conservateur
- `TrainingLoad` conserve son rôle actuel
- `RecentTrainingResponse` reste contextuel
- aucune augmentation

### SHORTEN_FACTOR

- `SHORTEN_FACTOR = 0.70`

---

## Garde-fous d’architecture

Les tests bloquants vérifient que `backend/training_v2/daily_adaptation.py` :

- ne contient plus `_READINESS_FAVORABLE_MIN`
- ne contient plus `_READINESS_CAUTION_MIN`
- ne contient plus `_READINESS_VERY_LOW_MAX`
- ne contient plus `ReadinessResult`
- ne contient plus de comparaison directe sur `readiness.score`

---

## Périmètre inchangé

Confirmé inchangé :

- agrégation `ReadinessResult`
- `ReadinessSubscores`
- `ReadinessSufficiency`
- `TrainingLoad`
- `TrainingResponse`
- `WeeklyTarget`
- `WorkoutGenerator`
- `PlanGoal`
- `Periodization`
- `TrainingState`
- `training_engine.py`

Aucun runtime consumer migré dans cette correction.

---

## Roadmap

- `#133` reste `IMPLEMENTED / PENDING MERGE`
- `NEXT = #134 Weekly Reconciliation V2`
- aucun `MOVE`
- aucun LT1/LT2
- aucun trail/D+

