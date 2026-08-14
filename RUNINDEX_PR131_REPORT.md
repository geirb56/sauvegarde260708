# RUNINDEX PR131 — WorkoutGenerator V2

**Status:** IMPLEMENTED / PENDING MERGE  
**Base:** main HEAD `658b50ec3733cd40ff9d993c9b8541abe3344af0` (#130 merged)  
**Branch:** PR131  

---

## 1. Fichiers livrés

| Fichier | Action |
|---|---|
| `backend/training_v2/workout_generator.py` | Créé (couche métier pure) |
| `backend/training_v2/__init__.py` | Mis à jour (exports PR131) |
| `backend/tests/test_workout_generator_v2.py` | Créé (87 tests) |
| `RUNINDEX_PR131_REPORT.md` | Ce fichier |
| `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md` | Mis à jour |

Fichiers **non modifiés** : `server.py`, `coach_service.py`, `training_engine.py`, `llm_coach.py`, `terra_integration.py`, tout le frontend.

---

## 2. Contrat WorkoutPrescription

```python
class WorkoutPrescription(BaseModel):
    model_config = ConfigDict(frozen=True)

    day: str                       # 'monday' … 'sunday'
    workout_type: str              # rest | recovery | easy | steady | quality | long_easy
    intensity_class: str           # rest | low | moderate | high
    distance_km: Optional[float]   # None si basis == "duration"
    duration_minutes: Optional[int] # None si basis == "distance"
    reason_codes: tuple[str, ...]
```

---

## 3. Contrat WeeklyPlan

```python
class WeeklyPlan(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_date: date
    target_basis: str              # "distance" | "duration"
    planned_km: Optional[float]    # None si basis == "duration"
    planned_duration_minutes: Optional[int]  # None si basis == "distance"
    session_count: int             # nombre de séances courantes (hors rest)
    sessions: tuple[WorkoutPrescription, ...]  # 7 entrées (lun→dim)
    allow_intensity: bool
    reason_codes: tuple[str, ...]
```

---

## 4. Signature de la fonction principale

```python
def build_weekly_plan(
    *,
    weekly_target: WeeklyTarget,
    runner_profile: RunnerProfile,
    plan_goal: PlanGoal,
    periodization: PeriodizationSnapshot,
    reference_date: date,
) -> WeeklyPlan:
```

Contraintes respectées :
- `reference_date` explicite, jamais `datetime.now()` ni `date.today()`
- Aucun I/O, MongoDB, Garmin, Terra, LLM, cache
- Aucun import `training_engine`
- Aucun import `llm_coach`

---

## 5. Structure des séances par nombre de sessions

| sessions | Lun | Mar | Mer | Jeu | Ven | Sam | Dim |
|---|---|---|---|---|---|---|---|
| 1 | rest | rest | rest | rest | rest | rest | long_easy |
| 2 | rest | easy | rest | rest | rest | rest | long_easy |
| 3 | rest | easy | rest | quality¹ | rest | rest | long_easy |
| 4 | rest | easy | rest | quality¹ | rest | easy | long_easy |
| 5 | recovery | easy | quality¹ | rest | easy | rest | long_easy |
| 6 | recovery | easy | quality¹ | recovery | rest | easy | long_easy |

¹ `quality` → `easy` si `allow_intensity == False` ou si déjà utilisé

---

## 6. Règle intensité V1

```
allow_intensity == False  →  0 quality (easy / recovery / long_easy uniquement)
allow_intensity == True   →  maximum 1 quality par semaine (V1 calibration produit)
```

Même avec 5 ou 6 séances : **une seule quality maximum**.  
NE PAS recopier le legacy qui peut générer threshold + tempo la même semaine.

---

## 7. Comportement deep_reprise

- Routage : `"continuity_deep_reprise"` dans `weekly_target.reason_codes`
- Base : `target_basis == "duration"` (WeeklyTarget #130)
- Split : `_split_durations(total_minutes, n=3)` — proportions `(27%, 33%, 40%)`
- Placement : mar (court) / jeu (moyen) / dim (long)
- Types : `recovery` (session courte) et `easy` (sessions moyennes/longues)
- Reason code : `run_walk_allowed` sur toutes les séances courantes
- Zéro quality, zéro steady, zéro long_easy
- Somme exacte : `sum(duration_minutes) == target_duration_minutes`

---

## 8. Comportement partial_reprise

- Routage : `"continuity_partial_reprise"` dans `weekly_target.reason_codes`
- Easy-only (aucun quality, aucun steady)
- Distance ou durée selon `target_basis`
- Split distance : `(28%, 32%, 40%)` pour 3 sessions
- Placement : mar / jeu / dim
- **Aucun run/walk** (reprise partielle, pas profonde)
- Somme exacte

---

## 9. Comportement reprise_exit

```
allow_intensity == True  →  plan normal, max 1 quality, volume identique à WeeklyTarget
allow_intensity == False →  easy-only, volume identique à WeeklyTarget
```

WorkoutGenerator ne redécide **jamais** si l'intensité est autorisée.  
Il respecte `WeeklyTarget.allow_intensity`.

---

## 10. Comportement normal

Plan standard basé sur le squelette de la semaine.  
Modulation légère selon la phase de périodisation (composition uniquement, jamais le volume).

---

## 11. Comportement taper / race / consolidation

| Phase | Action |
|---|---|
| taper | `quality` → `easy` dans le squelette |
| consolidation | `quality` → `easy` dans le squelette |
| race | Squelette minimal 2 sessions, reason code `race_week_conservative` |

**Le volume n'est PAS remodulé.** WeeklyTarget a déjà appliqué les multiplicateurs de phase.  
Pas de double taper.

---

## 12. Calibration long run V1

```python
LONG_RUN_FRACTION       = 0.35   # point de départ (35 % du volume hebdo)
LONG_RUN_MIN_FRACTION   = 0.20   # plancher (20 %)
LONG_RUN_MAX_FRACTION   = 0.45   # plafond (45 % — protection faible volume)
```

Ajustements par objectif (additifs) :
```
5k / 10k       : −0.05
half_marathon  :  0.00
marathon       : +0.05
ultra          : +0.08
maintenance    :  0.00
```

Caps absolus par objectif (ne s'appliquent qu'à haut volume) :
```
5k=8 km | 10k=12 km | half_marathon=18 km | marathon=28 km | ultra=35 km | maintenance=15 km
```

**Aucun plancher minimum obligatoire** (ni 16 km pour le semi, ni 28 km pour le marathon).  
Un faible volume hebdomadaire ne produit jamais une sortie longue disproportionnée.  
La contrainte binding à faible volume est `LONG_RUN_MAX_FRACTION = 0.45`.

---

## 13. Distribution distance / durée

### Basis distance

1. Long run = `_compute_long_run_km(target_km, goal_type)`
2. Remaining = `target_km - long_run_km`
3. Répartition pondérée par type (poids relatifs) :
   - `recovery` : 0.70
   - `easy` : 1.00
   - `steady` : 1.10
   - `quality` : 1.00
4. Correction du résidu d'arrondi sur la plus grande séance.

### Basis duration

1. Long run = `_compute_long_run_duration(total_minutes, goal_type)`
2. Remaining = `total_minutes - long_run_minutes`
3. Répartition pondérée (poids relatifs) :
   - `recovery` : 0.65
   - `easy` : 1.00
   - `steady` : 1.10
   - `quality` : 1.10
4. Correction du résidu d'arrondi sur la plus grande séance.

---

## 14. NO_ROUNDING_DRIFT

### Distance
```
sum(session.distance_km for running sessions) == weekly_target.target_km  (±0.1 km)
```

### Duration
```
sum(session.duration_minutes for running sessions) == weekly_target.target_duration_minutes  (exact)
```

Le résidu est ajouté à la plus grande séance (principe legacy PR77 préservé).

---

## 15. Aucune fausse précision

- `distance_km = None` si `target_basis == "duration"` (pas de pace inventé)
- `duration_minutes = None` si `target_basis == "distance"` (pas de pace inventé)
- Aucune FC hardcodée (120-135, 135-150, 150-165, 165-175)
- Aucun pace fallback (6:00/km, 7:00/km, 7:30/km)
- Aucun TSS/km legacy
- Aucun LT1/LT2
- Aucun `DEFAULT_WEEKLY_KM`
- Aucun `GOAL_CONFIG` / `VOLUME_GOAL_CONFIG`

---

## 16. Matrice legacy → V2

| Legacy (llm_coach / training_engine) | V2 (workout_generator.py) |
|---|---|
| `generate_cycle_week` (structure) | `build_weekly_plan` |
| `build_session` | `_make_running_session` / `_make_rest` |
| `build_reprise_week_structure` | `_build_reprise_sessions_duration` + `_build_reprise_sessions_distance` |
| `reprise_deep_durations` / `reprise_durations` | WeeklyTarget #130 (total) + `_split_durations` (split) |
| `compute_long_run_km` | `_compute_long_run_km` (proportionnel, sans planchers) |
| `cap_long_run_for_low_volume` | `LONG_RUN_MAX_FRACTION` dans `_compute_long_run_km` |
| Correction résidu d'arrondi | `_correct_rounding_drift_distance` / `_correct_rounding_drift_duration` |
| FC hardcodées 120-135 / 135-150 / 150-165 / 165-175 | **NON MIGRÉ** |
| Allures fallback 6:00, 7:00, 7:30/km | **NON MIGRÉ** |
| TSS estimé par km (`estimated_tss`) | **NON MIGRÉ** |
| Focus LLM / `advice` texte | **NON MIGRÉ** (reste dans llm_coach comme couche d'explication) |
| `GOAL_CONFIG` / `VOLUME_GOAL_CONFIG` | **NON MIGRÉ** |
| Structures figées (threshold+tempo la même semaine) | **NON MIGRÉ** |

---

## 17. Protections PR77 migrées

| Protection PR77 | Implémentation V2 |
|---|---|
| deep_reprise = duration-based | `target_basis == "duration"` depuis WeeklyTarget, split ici |
| run/walk possible | reason_code `run_walk_allowed` en deep_reprise |
| 3 séances maximum en reprise | `min(n_sessions, 3)` en deep_reprise |
| Séance la plus longue en fin de semaine | Split ascendant, dim = durée max |
| Récupération entre séances | Placement tue/jeu/dim avec repos entre |
| Somme exacte (NO_ROUNDING_DRIFT) | `_correct_rounding_drift_*` |
| Sortie longue proportionnée | `_compute_long_run_km` avec fraction, sans planchers |

---

## 18. Tests

**Total : 87 tests — 87 passés — 0 échoués**

| Classe | Sujet | N |
|---|---|---|
| `TestDeepRepriseEasyOnly` | A — easy-only, run/walk, no quality | 5 |
| `TestDeepRepriseDurationSum` | B — somme minutes exacte | 7 |
| `TestPartialRepriseDistance` | C — easy-only, somme km exacte | 6 |
| `TestRepriseExitAllowIntensity` | D — max 1 quality | 4 |
| `TestRepriseExitNoIntensity` | E — zéro quality | 2 |
| `TestNormalAllowIntensity` | F — max 1 quality, 2→6 sessions | 6 |
| `TestNormalNoIntensity` | G — zéro quality, 2→6 sessions | 5 |
| `TestLongRunProportionality` | H — proportionnalité, sans planchers | 9 |
| `TestNoRoundingDriftDistance` | I — somme km exacte (8 cas) | 9 |
| `TestNoRoundingDriftDuration` | J — somme minutes exacte (5 cas) | 5 |
| `TestPhaseModulation` | K — no double volume reduction | 9 |
| `TestNoFalsePrecision` | L — aucune FC/allure/import interdit | 9 |
| `TestDeterminism` | M — même inputs → même output | 3 |
| `TestNonRegression` | Non-régression WeeklyTarget / immutabilité | 5 |

---

## 19. Confirmations

- ✅ Aucun pace fallback arbitraire
- ✅ Aucune FC hardcodée
- ✅ Aucun TSS legacy
- ✅ Aucun import `training_engine`
- ✅ Aucun import `llm_coach`
- ✅ Aucun consumer runtime migré (server.py, coach_service.py inchangés)
- ✅ `WeeklyTarget` inchangé
- ✅ Readiness inchangée
- ✅ TrainingLoad inchangé
- ✅ `training_engine.py` intact
- ✅ NO_ROUNDING_DRIFT distance (42.0, 31.7, 17.3, 12.4, 50.1, 60.0 km testés)
- ✅ NO_ROUNDING_DRIFT duration (105, 120, 137, 90, 180 min testés)
- ✅ Marathon 20 km → long run ~7 km (pas 28 km)
- ✅ WeeklyPlan immutable (frozen Pydantic)
- ✅ WorkoutPrescription immutable (frozen Pydantic)
- ✅ `datetime.now()` / `date.today()` absents du code (vérifiés par AST)
- ✅ 324 tests training_v2 passés (non-régression #130 + PR131)

---

## 20. Dettes restantes

| Sujet | PR cible |
|---|---|
| `WorkoutAnalysis` (analyse de la semaine réalisée) | #132 |
| `DailyAdaptation` (modulation quotidienne sur la readiness) | #133 |
| Zones personnalisées LT1/LT2 | `thresholds.py` (futur) |
| Allures personnalisées par zone | `performance.py` (futur) |
| FC personnalisées par zone | `thresholds.py` (futur) |
| Distribution d'intensité V2 (au-delà de "1 quality max") | Post-#133 |
| Recalibration coefficients long run V1 | Post-#133 |
| Respect des préférences de jours RunnerProfile | V2 post-#133 |

---

## 21. NEXT

**#132 WorkoutAnalysis V2**
