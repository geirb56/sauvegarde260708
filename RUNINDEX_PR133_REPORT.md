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
| `backend/training_v2/daily_adaptation.py` | NEW: `DailyAdaptationAction`, `DailyAdaptationResult`, `build_daily_adaptation()` |
| `backend/training_v2/__init__.py` | Updated: exports PR133 |
| `backend/tests/test_daily_adaptation_pr133.py` | NEW: tests PR133 + conflits + garde-fous d’architecture |
| `RUNINDEX_PR133_REPORT.md` | NEW: ce fichier |
| `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md` | Updated: HEAD réel, états #129/#131/#132, PR133, NEXT=#134 |

---

## Contrat DailyAdaptationResult

```python
class DailyAdaptationAction(str, Enum):
    KEEP = "KEEP"
    EASY_DOWNGRADE = "EASY_DOWNGRADE"
    SHORTEN = "SHORTEN"
    REST = "REST"

class DailyAdaptationResult(BaseModel):
    model_config = ConfigDict(frozen=True)

    action: DailyAdaptationAction
    original_workout: WorkoutPrescription
    adapted_workout: WorkoutPrescription
    reason_codes: tuple[str, ...]
```

---

## Hiérarchie de décision V1

1. `rest` prévu → `KEEP` systématique.
2. Signal quotidien très défavorable (`ReadinessResult.score < 40`) → `REST`.
3. Réduction d’intensité si séance `quality|steady` et :
   - `40 <= readiness_score < 75`, ou
   - `TrainingLoad.status == "high"` avec readiness non favorable, ou
   - `TrainingLoad.status == "elevated"` avec readiness déjà prudent.
4. Protection `long_easy` : si réduction nécessaire → `SHORTEN` avant `REST`.
5. Séance `easy|recovery` : réduction de quantité uniquement (`SHORTEN`) si réduction nécessaire.
6. `RecentTrainingResponse` n’annule jamais un signal quotidien défavorable ; il sert surtout à ajouter des `reason_codes`.
7. Aucun chemin ne peut augmenter distance, durée ou intensité.

---

## Readiness / Load / Response

- **Readiness unavailable** (`score=None`) → jamais transformé en `REST` automatiquement ; `reason_code = READINESS_UNAVAILABLE`.
- **TrainingLoad unavailable** (`status="unavailable"` ou input absent) → jamais traité comme `0` ; `reason_code = TRAINING_LOAD_UNAVAILABLE`.
- **RecentTrainingResponse insufficient/unavailable** → pas de tendance inventée ; `reason_code = RECENT_RESPONSE_INSUFFICIENT|RECENT_RESPONSE_UNAVAILABLE`.

---

## Calibrations / règles

- `SHORTEN_FACTOR = 0.70`
- `quality|steady -> easy` conserve le jour et la quantité prévue
- `long_easy` réduit d’abord la quantité (`SHORTEN`) ; `REST` seulement si signal quotidien très défavorable
- `REST` requiert un signal quotidien fort (`readiness_score < 40`), jamais un simple manque de données

---

## Reason codes V1

- `PLANNED_REST_DAY`
- `PLAN_KEPT`
- `READINESS_UNAVAILABLE`
- `READINESS_CAUTION`
- `READINESS_LOW`
- `READINESS_VERY_LOW`
- `TRAINING_LOAD_UNAVAILABLE`
- `TRAINING_LOAD_ELEVATED`
- `TRAINING_LOAD_HIGH`
- `RECENT_RESPONSE_UNAVAILABLE`
- `RECENT_RESPONSE_INSUFFICIENT`
- `RECENT_RESPONSE_CAUTION`
- `QUALITY_DOWNGRADED`
- `WORKOUT_SHORTENED`
- `LONG_EASY_PROTECTED`
- `REST_RECOMMENDED`
- `INTENSITY_NOT_INCREASED`

---

## Immutabilité / preuve d’absence d’augmentation

- `WorkoutPrescription` n’est jamais muté : toutes les adaptations créent un nouvel objet.
- `KEEP` réutilise l’objet source inchangé.
- `EASY_DOWNGRADE` remplace seulement `workout_type`/`intensity_class` par `easy/low`.
- `SHORTEN` applique un facteur fixe `< 1.0`.
- `REST` remplace une séance par un `WorkoutPrescription` de type `rest`.
- Aucun code ne multiplie distance/durée par une valeur `> 1`, ne rajoute de séance, ni ne transforme `easy` en `quality`.

---

## Frontière roadmap

- **#133 DailyAdaptation** → aujourd’hui, adaptation locale, maintien/réduction uniquement.
- **NEXT = #134 Weekly Reconciliation V2** → adaptation structurelle future (volume, fréquence, long run).
- **V3 Flexible Schedule** conservé en roadmap ; aucun `MOVE` implémenté ici.

