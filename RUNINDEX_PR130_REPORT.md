# RUNINDEX PR #130 — Weekly Target V2

## Statut

**IMPLEMENTED / PENDING MERGE**

Base : `main` HEAD = `4c6982b1239075dfafde81ab5a062950805a8dcd`
PR #129 = MERGED

---

## Fichiers modifiés

| Fichier | Type | Rôle |
|---|---|---|
| `backend/training_v2/training_history.py` | Modification minimale | Extension `PriorRunningWindow` |
| `backend/training_v2/weekly_target.py` | Nouveau | Couche WeeklyTarget V2 |
| `backend/training_v2/__init__.py` | Mise à jour | Export des nouveaux symboles |
| `backend/tests/test_weekly_target_v2.py` | Nouveau | Matrice de tests complète (43 tests) |
| `RUNINDEX_PR130_REPORT.md` | Nouveau | Ce rapport |
| `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md` | Mise à jour | Roadmap canonique |

**Non modifiés (confirmé) :**
- `backend/server.py` ✓
- `backend/coach_service.py` ✓
- `backend/training_engine.py` ✓
- `backend/llm_coach.py` ✓
- `backend/terra_integration.py` ✓
- `frontend/*` ✓

---

## Contrat WeeklyTarget exact

```python
class WeeklyTarget(BaseModel):
    model_config = ConfigDict(frozen=True)

    reference_date: date
    target_basis: str           # "duration" | "distance"
    target_km: Optional[float]
    target_duration_minutes: Optional[int]
    target_sessions: int
    allow_intensity: bool
    confidence: str             # "none" | "low" | "medium" | "high"
    reason_codes: tuple[str, ...]
```

**Absent (réservé #131) :** `long_run_km`, `pace`, `zone`, `workout_type`, `intervals`, `session_structure`.

Signature de la fonction principale :

```python
def build_weekly_target(
    *,
    runner_profile: RunnerProfile,
    training_history: TrainingHistory,
    training_state: TrainingState,
    plan_goal: PlanGoal,
    periodization: PeriodizationSnapshot,
    reference_date: date,
) -> WeeklyTarget
```

---

## Extension TrainingHistory — `PriorRunningWindow`

### Modèle

```python
class PriorRunningWindow(BaseModel):
    model_config = ConfigDict(frozen=True)
    days_ago_start: int = 28   # borne inférieure inclusive (plus loin)
    days_ago_end: int = 41     # borne supérieure inclusive (plus proche)
    distance_km: float
    duration_hours: float
    activity_count: int

    @property
    def weekly_km_equivalent(self) -> float: ...  # distance_km / 2
    @property
    def has_activity(self) -> bool: ...
```

### Définition exacte de la fenêtre pré-arrêt

```
days_ago >= 28  AND  days_ago < 42
→ [reference_date - 41 jours, reference_date - 28 jours]  (les deux bornes incluses)
```

- **J-28 inclusif** : activité le jour J-28 est dans la fenêtre.
- **J-41 inclusif** : activité le jour J-41 est dans la fenêtre.
- **J-42 exclu** : activité le jour J-42 ou au-delà N'EST PAS dans la fenêtre.
- **J-27 exclu** : activité le jour J-27 ou plus récent N'EST PAS dans la fenêtre.

La fenêtre couvre **14 jours = 2 semaines**. L'équivalent hebdomadaire = `distance_km / 2`.

### Rétro-compatibilité

`prior_running_window` a une valeur par défaut (fenêtre vide) pour ne pas casser les tests existants qui construisent `TrainingHistory` directement sans passer par `build_training_history`.

---

## Calibration durée V2 (V1 — recalibrable)

Source : constantes runtime PR77 (code + tests, pas les rapports documentaires).

| Constante | Valeur | Source |
|---|---|---|
| `DEEP_REPRISE_WEEKLY_MINUTES_FLOOR` | 105 min | Sum `REPRISE_DEEP_SESSION_MINUTES = [30, 35, 40]` |
| `DEEP_REPRISE_WEEKLY_MINUTES_TRAINED` | 135 min | Sum `REPRISE_DEEP_SESSION_MINUTES_TRAINED = [35, 45, 55]` |
| `PRIOR_TRAINED_KM_FLOOR` | 15.0 km/sem | Seuil bas "entraîné" (PR77 : `(p - 15) / (40 - 15)`) |
| `PRIOR_TRAINED_KM_TOP` | 40.0 km/sem | Seuil haut "entraîné" (interpolation linéaire) |

Les constantes de PR77 proviennent de `REPRISE_DEEP_SESSION_MINUTES` et `REPRISE_DEEP_SESSION_MINUTES_TRAINED`.
La V2 produit une **durée hebdomadaire totale** ; le WorkoutGenerator #131 répartit ensuite entre les séances.

---

## Calibration progression V1

| Constante | Valeur | Source |
|---|---|---|
| `REPRISE_PROGRESSION_FACTOR` | 1.12 | PR77 : +12 %/semaine active tolérée |
| `REPRISE_PROGRESSION_CAP` | 1.60 | PR77 : cap +60 % sur la baseline reprise |
| `NORMAL_MAX_PROGRESSION` | 1.10 | Legacy : +10 % max/semaine en état normal |
| `PARTIAL_REPRISE_DISTANCE_FACTOR` | 1.10 | Prudent, calibration V1 |

---

## Calibration phase V1

| Phase | Multiplicateur |
|---|---|
| `base` | 1.00 |
| `build` | 1.00 |
| `specific` | 1.00 |
| `taper` | 0.50 |
| `race` | 0.30 |
| `consolidation` | 0.85 |

Invariant garanti : `taper < build` et `taper < specific`.
Les phases `deload` et `intensification` du legacy n'existent pas en V2.

---

## Comportements par état de continuité

### `no_history`

- `target_basis = "duration"`
- `target_km = None`
- `target_duration_minutes = DEEP_REPRISE_WEEKLY_MINUTES_FLOOR` (105 min)
- `allow_intensity = False`
- Sessions ≤ `REPRISE_MAX_SESSIONS` (3)
- Aucun volume objectif fictif.

### `deep_reprise`

- `target_basis = "duration"`
- `target_km = None`
- `allow_intensity = False`
- Durée interpolée linéairement entre FLOOR et TRAINED selon `prior_running_window.weekly_km_equivalent`.
- Progression par semaines actives tolérées (+12 %/semaine, cap +60 %).
- Sessions ≤ `REPRISE_MAX_SESSIONS` (3).

### `partial_reprise`

- `allow_intensity = False`
- Avec baseline observable : `target_basis = "distance"`, progression prudente depuis volume récent.
- Sans baseline fiable : `target_basis = "duration"`, `target_km = None`, 120 min/semaine.

### `reprise_exit`

- **Cas A — baseline exploitable** (target_basis = "distance") :
  - `allow_intensity = True`
  - Volume **HOLD** : `target_km = chronic * phase_multiplier` (pas de progression).
  - Reason code : `REPRISE_EXIT_INTENSITY_RETURNS`
  - **JAMAIS volume ET intensité augmentés simultanément** (test I inclus).

- **Cas B — aucune baseline exploitable** (target_basis = "duration") :
  - `allow_intensity = False`
  - `target_km = None`, `target_duration_minutes = fallback prudent`.
  - Reason code : `REPRISE_EXIT_INTENSITY_WITHHELD_NO_BASELINE`
  - **Principe permanent : UNKNOWN BASELINE → NO INTENSITY RETURN.**

> L'intensité ne revient en reprise_exit que lorsqu'un volume observé fiable
> existe et est tenu. Sans baseline, la prescription bascule sur une durée
> de secours et l'intensité reste interdite.

### `normal`

- `target_basis = "distance"` (ou durée si pas de baseline).
- Progression depuis baseline chronic : max +10 %/semaine.
- Amortissement des pics (résume guard actif si chronic >= 5 km/sem).
- Aucun plancher minimum lié à l'objectif de course.

---

## Preuve ancien coureur vs débutant préservée

La distinction repose **exclusivement** sur `prior_running_window.weekly_km_equivalent` :

```
prior_km <= 15.0  →  DEEP_REPRISE_WEEKLY_MINUTES_FLOOR   (105 min)
prior_km >= 40.0  →  DEEP_REPRISE_WEEKLY_MINUTES_TRAINED (135 min)
entre les deux    →  interpolation linéaire
```

Source : activités observées dans `[reference_date - 41, reference_date - 28]`.
Jamais inventé. Jamais tiré de `experience_level` ou d'une déclaration.

Test C valide : `wt_trained.target_duration_minutes > wt_unknown.target_duration_minutes`.

---

## Résultat test S1 → S2 → S3

- **S1** (deep_reprise, pas d'historique récent) : durée = 105 min (FLOOR)
- **S2** (après 1 semaine ~10 km) : distance ~11 km (km_equiv ≥ 5.0 km, test valide)
- **S3** (après 2 semaines ~10 km) : S3 ≥ S2 − 1.0 km-equiv (pas d'effondrement)

Note : S1→S2 franchit la frontière durée/distance ; c'est attendu (deep_reprise → début reprise avec historique).

---

## Résultat test surcharge brutale

- Base chronique ~15 km/sem, pic à ~40 km la semaine suivante.
- Target résultant : **≤ 25 km** (amorti depuis la base chronique).
- Le pic n'est pas validé comme nouvelle baseline.

---

## Matrice legacy → V2 finale

| Fonction legacy | V2 | Statut |
|---|---|---|
| `classify_training_state` | `TrainingState V2` | Déjà migré |
| `resolve_chronic_base` | `WeeklyTarget._chronic_base_km` (active-weeks) | Migré ici |
| `apply_resume_guard` | `WeeklyTarget._apply_resume_guard` | Migré ici |
| `resolve_reprise_plan` | `build_weekly_target` | Migré ici |
| `reprise_deep_durations` | WeeklyTarget (durée hebdo) + WorkoutGenerator #131 (séances) | Partiel ici |
| `reprise_durations` | WeeklyTarget (progression durée hebdo) | Migré ici |
| `build_reprise_week_structure` | **WorkoutGenerator #131** | Réservé |
| `compute_long_run_km` | **WorkoutGenerator #131** | Réservé |
| `cap_long_run_for_low_volume` | **WorkoutGenerator #131** | Réservé |
| Rounding residual correction | **WorkoutGenerator #131** | Réservé |
| `recovery_red_flag` | Non migré — future DailyAdaptation / Readiness | Non migré |
| `DEFAULT_WEEKLY_KM` | **SUPPRIMÉ** — aucun équivalent V2 fictif | Supprimé |
| Plancher minimum objectif marathon | **Non migré** — goal ne crée pas de plancher | Supprimé |

---

## Protections réservées #131

```
# RESERVED FOR WorkoutGenerator #131
# =====================================
#
# 1. LONG RUN — jamais disproportionnée
#    - cap long_run_km selon volume hebdo
#    - pas de long_run_min objectif imposé brutalement
#    - ratio reprise prudent conservé
#
# 2. EASY-ONLY enforcement
#    - allow_intensity=False → toutes les séances doivent être faciles
#    - run/walk possible en deep_reprise
#    - aucune séance dure
#
# 3. NO ROUNDING DRIFT (migration obligatoire)
#    - sum(sessions) doit égaler exactement la cible hebdomadaire
#    - aucune dérive d'arrondi entre séances
#
# Ces trois protections sont documentées comme dette technique obligatoire
# à implémenter dans WorkoutGenerator #131.
```

---

## Tests — résultat final

| Catégorie | Total | Passed | Failed |
|---|---|---|---|
| `test_weekly_target_v2.py` | 43 | **43** | 0 |
| `test_training_history_pr05.py` | 61 | 61 | 0 |
| `test_training_state_pr04.py` | (pré-existant) | — | 3 pré-existants |
| `test_runner_profile_pr07.py` | (pré-existant) | — | 0 nouvelles régressions |
| `test_periodization_pr06.py` | (pré-existant) | — | 0 nouvelles régressions |

Les 3 échecs dans `test_training_state_pr04.py` sont **pré-existants** sur `main` et non liés à #130.

---

## Confirmations de non-régression

| Contrôle | Résultat |
|---|---|
| `DEFAULT_WEEKLY_KM` absent de `weekly_target.py` | ✓ Confirmé |
| `import training_engine` absent | ✓ Confirmé (test R) |
| Import Garmin / Terra absent | ✓ Confirmé (test S) |
| `datetime.now()` / `date.today()` absents | ✓ Confirmé (test T) |
| Aucun consumer runtime migré | ✓ Confirmé |
| `TrainingLoad` inchangé | ✓ Confirmé |
| Readiness inchangée | ✓ Confirmé |
| `training_engine.py` intact | ✓ Confirmé |
| Roadmap canonique mise à jour | ✓ Confirmé |
| NEXT = #131 Workout Generator V2 | ✓ Confirmé |

---

## NEXT : #131 Workout Generator V2

Responsable de :
- Structure de la semaine (répartition de la cible hebdo en séances)
- Easy-only en reprise (`allow_intensity=False`)
- Run/walk en `deep_reprise`
- Cap long run / proportionnalité
- Correction exacte des arrondis (`NO_ROUNDING_DRIFT`)
