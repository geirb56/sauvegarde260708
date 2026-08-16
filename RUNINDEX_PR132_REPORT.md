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
| `backend/tests/test_training_response_pr132.py` | NEW: 65 tests (52 originaux + 13 nouveaux §14D/§15/§16/§17) |
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

### Garde-fou terrain comparabilité (PRODUCT CALIBRATION V1 — RECALIBRABLE)

```
elevation_rate = elevation_gain_m / distance_km   [m D+/km]
```

Condition pour calculer le trend :
- ≥ 4 samples ont à la fois une **efficiency valide** ET un **elevation_rate connu**
  (`elevation_gain_m is not None` et `distance_m > 0`).
- ET `terrain_max − terrain_min ≤ 30 m D+/km` parmi ces samples.

Sinon : `cardiac_efficiency_trend = "unknown"`.

**Seuil V1 : 30 m D+/km.**  Centralisé (`_TERRAIN_DISPERSION_THRESHOLD_M_PER_KM`),
documenté, recalibrable. PAS une loi physiologique.

**AUCUNE correction de vitesse par le D+ n'est appliquée** :
ni GAP, ni pace corrigée, ni coefficient trail.
Si terrain incompatible → `"unknown"`.

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

  Conditions pour calculer :
    - au moins 1 distance valide dans CHAQUE moitié
    - ET au moins 4 activités running avec distance valide sur les 28 jours
  Sinon → "unknown"
```

Le cap MAX_SELECTED = 10 ne doit jamais distordre les totaux de volume.
Aucun coefficient caché. Seuil = ±10 %, documenté et testé.

---

## Méthode Frequency Pattern V1

Split calendaire : fenêtre 28 j divisée en deux moitiés de 14 j.
**Utilise TOUTES les activités in-window (pas plafonné à 10).**
Nombre de runs dans chaque demi-fenêtre comparé avec seuil ±10 %.
Requiert ≥ 4 activités totales. Sinon `"unknown"`.

---

## Méthode Long-run Trend V1

**Calendaire : compare la plus longue sortie de l'ancienne moitié (14 j)
vs la plus longue sortie de la récente moitié (14 j).**
**Utilise TOUTES les activités in-window (pas plafonné à 10).**
Seuil ±10 %. Requiert ≥ 1 distance valide dans chaque moitié ET ≥ 4 au total.
Sinon `"unknown"`.

```
old_longest_km    = max des distances dans l'ancienne moitié (J-27 → J-14)
recent_longest_km = max des distances dans la récente moitié (J-13 → J)
```

---

## Méthode Intensity Exposure Trend V1

**Calendaire : compare le total de minutes (moderate + vigorous) de l'ancienne
moitié vs la récente moitié.**
**Utilise TOUTES les activités in-window (pas plafonné à 10).**
`moderate + vigorous` en somme simple — aucun coefficient de pondération.
Seuil ±10 %.  Requiert des données dans chaque moitié. Sinon `"unknown"`.

---

## Traitement moderate/vigorous

`moderate_intensity_minutes` et `vigorous_intensity_minutes` sont des **faits fournisseur**.
Ils alimentent :
- `intensity_coverage_count`
- `intensity_exposure_trend` (via totaux calendaires par moitié 14j)

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
| 66 | 66 | 0 |

Couverture : A–X (spec §18) + §14D/§15/§16/§17A–D ✓

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

---

## Corrections audit externe (PR #132 V2)

Corrections appliquées suite à l'audit externe sur HEAD `bd550bcec93415a38f0642f49870d4ff22f112e7` :

### 1. Séparation GLOBAL 28d FACTS vs RECENT 10 ANALYSIS

| Population | Champs concernés |
|---|---|
| **GLOBAL 28-day window** (toutes activités) | `observed_runs`, `observed_runs_per_week`, `observed_distance_km`, `observed_duration_minutes`, `volume_trend`, `frequency_pattern`, `long_run_trend`, `intensity_exposure_trend` |
| **RECENT SAMPLE** (≤ 10 dernières) | `cardiac_efficiency_samples`, `average_hr_recent`, `average_pace_recent_s_per_km` |

Le cap `MAX_SELECTED = 10` ne falsifie jamais les faits globaux.

### 2. volume_trend — volumes totaux (était : moyennes)

Corrigé : compare les **totaux** de distance des deux demi-fenêtres calendaires.
Garde-fou : ≥ 4 distances valides totales dans les 28 jours.

### 3. frequency_pattern — toutes les activités (était : selected_pairs capées)

Corrigé : utilise `in_window` complet, pas `selected_pairs`.

### 4. long_run_trend — calendaire (était : index-based sur 10 selected)

Corrigé : compare la plus longue sortie de chaque moitié calendaire (14d vs 14d)
sur toutes les activités in-window.

### 5. intensity_exposure_trend — calendaire (était : half-split index sur 10 selected)

Corrigé : compare le total de minutes (mod + vig) de chaque moitié calendaire
sur toutes les activités in-window.

### 6. cardiac_efficiency_trend — garde-fou terrain V1

Ajouté : `elevation_rate = elevation_gain_m / distance_km` (m D+/km).
Seuil : `_TERRAIN_DISPERSION_THRESHOLD_M_PER_KM = 30.0` m D+/km.
Si < 4 samples ont (efficiency valide + elevation_rate connu) → `"unknown"`.
Si terrain_max − terrain_min > 30 → `"unknown"`.
Aucune correction de vitesse inventée.

### Tests ajoutés

65 tests total (52 + 13 nouveaux) :
- §14-D : volume_trend unknown si couverture insuffisante
- §15 : frequency_pattern correct avec > 10 activités
- §16 : long_run_trend calendaire (increasing / decreasing / stable / unknown)
- §17A : terrain plat comparable → trend calculable
- §17B : terrain mixte plat + vallonné → unknown
- §17C : D+ majoritairement inconnu → unknown
- §17D : aucune correction GAP dans le code source
