# RUNINDEX PR #132 — Recent Training Response / Workout Analysis V2

## Delivery

| Item | Value |
|---|---|
| PR | #132 — Recent Training Response / Workout Analysis V2 |
| HEAD main au départ | `388bb650c4df5307a53eb488b4b3b6fb336af1c9` |
| #131 | MERGED |
| Status | IMPLEMENTED / PENDING MERGE |

---

## Fichiers modifiés

| Fichier | Action |
|---|---|
| `backend/training_v2/domain_activity.py` | Extended: `average_hr`, `max_hr`, `elevation_gain_m` |
| `backend/garmin/domain_adapter.py` | Updated: transport des 3 nouveaux champs depuis `GarminActivity` |
| `backend/training_v2/training_response.py` | NEW: `RecentTrainingResponse`, `WorkoutExecutionFacts`, `build_recent_training_response()`, `analyze_workout_execution()` |
| `backend/training_v2/__init__.py` | Updated: exports PR132 |
| `backend/tests/test_training_response_pr132.py` | NEW: 47 tests |
| `RUNINDEX_PR132_REPORT.md` | NEW: ce fichier |
| `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md` | Updated: sections 30–34 |

---

## Extension DomainActivity exacte

```python
average_hr: Optional[float] = None       # vitesse cardiaque moyenne ; None si absent/invalide/0
max_hr: Optional[float] = None           # FC max ; None si absent/invalide/0
elevation_gain_m: Optional[float] = None # dénivelé positif ; contexte terrain uniquement
```

Règles d'adaptation :
- Valeur 0 → None pour les champs HR (zéro cardiaque est physiologiquement impossible).
- Valeur négative → None pour les champs HR.
- `elevation_gain_m` accepte 0 (sortie plate valide).
- Aucun fallback, aucun zéro inventé.

L'adapter Garmin (`garmin/domain_adapter.py`) transporte `average_hr`, `max_hr`, `elevation_gain`
(déjà présents sur `GarminActivity`) vers les nouveaux champs de `DomainActivity`.

---

## Contrat RecentTrainingResponse

```python
class RecentTrainingResponse(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_date: date
    window_days: int                          # = 28

    available_running_activities: int
    selected_running_activities: int          # ≤ 10

    response_status: str                      # "unavailable"|"insufficient"|"sufficient"
    confidence: str                           # "none"|"low"|"moderate"

    observed_distance_km: Optional[float]
    observed_duration_minutes: Optional[float]
    observed_runs: int
    observed_runs_per_week: Optional[float]

    longest_run_km: Optional[float]
    longest_run_duration_minutes: Optional[float]

    hr_coverage_count: int
    intensity_coverage_count: int

    average_hr_recent: Optional[float]
    average_pace_recent_s_per_km: Optional[float]

    cardiac_efficiency_samples: tuple[Optional[float], ...]
    cardiac_efficiency_trend: str             # "increasing"|"decreasing"|"stable"|"unknown"

    volume_trend: str
    frequency_pattern: str
    long_run_trend: str
    intensity_exposure_trend: str

    reason_codes: tuple[str, ...]
```

---

## Contrat WorkoutExecutionFacts

```python
class WorkoutExecutionFacts(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_date: date

    planned_type: Optional[str]
    planned_distance_km: Optional[float]
    planned_duration_minutes: Optional[int]

    actual_distance_km: Optional[float]
    actual_duration_minutes: Optional[float]
    actual_average_hr: Optional[float]

    distance_ratio: Optional[float]    # actual/planned ou None
    duration_ratio: Optional[float]    # actual/planned ou None

    reason_codes: tuple[str, ...]
```

Exemple : prévu 10 km, réalisé 8 km → `distance_ratio = 0.8`. Point.

Aucun verdict, aucun score, aucun pass/fail.

---

## Règle fenêtre 28 jours

```
window_start = reference_date - timedelta(days=27)
Condition : window_start ≤ activity_date ≤ reference_date
Maximum : 10 activités les plus récentes
```

- Activité future → exclue.
- Activité J-29 → exclue (hors fenêtre).
- Activité J-27 → incluse (borne inclusive).

---

## Règle 5–10 activités

| Activités | response_status | confidence | Tendances structurelles |
|---|---|---|---|
| 0 | `"unavailable"` | `"none"` | `"unknown"` |
| 1–4 | `"insufficient"` | `"low"` | `"unknown"` |
| 5–10 | `"sufficient"` | `"moderate"` | calculées selon couverture |

Un signal particulier peut rester `"unknown"` même si `response_status="sufficient"`.
Exemple : 8 sorties mais seulement 2 avec FC → `cardiac_efficiency_trend = "unknown"`.

---

## Comportement < 5 activités

- Faits disponibles : `observed_distance_km`, `observed_duration_minutes`, etc.
- Tous les trends structurels : `"unknown"`.
- `reason_codes` inclut `"insufficient_activities_for_trends"`.

---

## Méthode Cardiac Efficiency V1

**TERRAIN INDICATOR — pas une mesure de LT1/LT2.**

```
speed_mps         = distance_m / duration_s
cardiac_efficiency = speed_mps / average_hr     [m·s⁻¹ / bpm]
```

Conditions requises : `distance_m > 0`, `duration_s > 0`, `average_hr > 0`. Sinon `None`.

`elevation_gain_m` est conservé comme contexte mais ne modifie pas le ratio en V1.

Comparabilité trend (PRODUCT CALIBRATION V1) :
- Trend calculé seulement si ≥ 4 samples valides.
- Autrement : `cardiac_efficiency_trend = "unknown"`.

---

## Méthode Volume Trend V1 (PRODUCT CALIBRATION V1)

```
Split calendaire — même frontière que Frequency Pattern :
  freq_boundary = reference_date - timedelta(days=13)

  ancienne moitié : window_start (J-27) → J-14 inclus  (date < freq_boundary)
  récente moitié  : J-13 → reference_date (J) inclus    (date >= freq_boundary)

Pour chaque moitié, utiliser TOUTES les activités running valides de la
fenêtre 28 jours (pas seulement les 10 sélectionnées) :

  old_total_km    = Σ distance_m / 1000 des activités de l'ancienne moitié
  recent_total_km = Σ distance_m / 1000 des activités de la récente moitié

Seuil = 10 % :
  recent_total > old_total × 1.10 → "increasing"
  recent_total < old_total × 0.90 → "decreasing"
  sinon                           → "stable"
  Si l'une ou l'autre moitié n'a aucune distance valide → "unknown"
```

Le cap MAX_SELECTED = 10 ne doit jamais distordre les totaux de volume.
Aucun coefficient caché. Seuil = ±10 %, documenté et testé.

---

## Méthode Frequency Pattern V1

Split calendaire : fenêtre 28 j divisée en deux moitiés de 14 j.
Nombre de runs dans chaque demi-fenêtre comparé avec seuil ±10 %.
Requiert ≥ 4 activités. Sinon `"unknown"`.

---

## Méthode Long-run Trend V1

Même half-split que volume_trend mais appliqué à la série des distances individuelles
(oldest → newest). Seuil ±10 %. Requiert ≥ 4 activités avec distance. Sinon `"unknown"`.

---

## Traitement moderate/vigorous

`moderate_intensity_minutes` et `vigorous_intensity_minutes` sont des **faits fournisseur**.
Ils alimentent :
- `intensity_coverage_count`
- `intensity_exposure_trend` (via half-split de la somme par session)

**INTERDIT :**
- `moderate + 2 × vigorous` (TRIMP)
- TSS / EPOC / Recovery Time
- LT1/LT2 conversion

`TrainingIntensityProfile` existant reste inchangé.

---

## Preuve : sorties hors plan incluses

`build_recent_training_response()` accepte TOUTES les activités running valides
de la fenêtre, sans vérification d'une prescription correspondante.

Test I :
```python
unplanned = _run(5, distance_m=12000.0)
acts = [_run(1), unplanned, _run(10)]
result = build_recent_training_response(acts, REF)
assert result.observed_runs == 3
assert result.observed_distance_km == pytest.approx(28.0)  # 8+12+8
```

---

## Preuve : None ≠ 0

- `average_hr = 0` → stocké `None` (test `test_domain_activity_zero_hr_becomes_none`)
- `average_hr = -10` → stocké `None` (test `test_domain_activity_negative_hr_becomes_none`)
- `cardiac_efficiency` avec HR manquant → `None` (tests K)
- `average_hr_recent` avec 0 activités avec HR → `None` (test J)

---

## Preuve : aucune dérive intra-run inventée

`RecentTrainingResponse` ne possède aucun champ :
- `cardiac_drift`
- `hr_drift`
- `cardiac_decoupling`

`DomainActivity` ne transporte pas de timeseries.
Vérifiés par tests Q.

---

## Preuve : aucun LT1/LT2

`RecentTrainingResponse` et `WorkoutExecutionFacts` ne possèdent aucun champ :
- `lt1`, `lt2`, `vt1`, `vt2`

Vérifiés par tests P.

---

## Preuve : aucun workout score / pass/fail

`WorkoutExecutionFacts` ne possède aucun champ :
- `verdict`, `score`, `passed`, `failed`

`distance_ratio = 0.8` = fait observable. Pas de jugement.
Vérifiés par test N.

---

## Tests

| Total | Passed | Failed |
|---|---|---|
| 47 | 47 | 0 |

Couverture spec §18 : A B C D E F G H I J K L M N O P Q R S T U V W X ✓

---

## Confirmations

| Vérification | Statut |
|---|---|
| Aucun consumer runtime migré | ✓ (server.py, coach_service.py, rag_engine.py, llm_coach.py inchangés) |
| Readiness inchangée | ✓ |
| TrainingLoad inchangé | ✓ |
| WeeklyTarget inchangé | ✓ |
| WorkoutGenerator inchangé | ✓ |
| training_engine.py intact | ✓ |
| Roadmap canonique mise à jour | ✓ (sections 30–34) |
| NEXT = #133 Daily Adaptation V2 | ✓ |

---

## Architecture future documentée

### #133 DailyAdaptation V2

Consommateurs :
```
WeeklyPlan
ReadinessResult
TrainingLoad V2
RecentTrainingResponse
     ↓
DailyAdaptation
```

Actions V1 envisagées : `KEEP`, `EASY_DOWNGRADE`, `SHORTEN`, `REST`.

#133 ne recalcule ni Readiness, ni TrainingLoad, ni RecentTrainingResponse, ni WeeklyTarget.

### Weekly Reconciliation V2 (future)

```
RecentTrainingResponse → WeeklyTarget semaine suivante
```

Adapte structurellement le plan aux comportements/capacités observés, sans culpabilisation.

### V3 — Flexible Schedule (future)

Permet à l'utilisateur de déplacer ses séances dans la même semaine.
Déplacer une séance ≠ adaptation physiologique.
