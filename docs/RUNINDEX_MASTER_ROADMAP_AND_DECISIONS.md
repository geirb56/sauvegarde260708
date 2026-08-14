# RunIndex — Master Roadmap & Decisions (canonique)

## 1) PURPOSE

Ce document est :

- le point de reprise canonique du projet RunIndex ;
- la synthèse des décisions métier et techniques validées ;
- la roadmap d'exécution ;
- un moyen d'éviter la perte de contexte entre sessions/outils.

Last verified against main: `f9bada97d72d4e159c2e7f6cc86781b110efe82c` (Merge PR #116)

HEAD PR (R2B): dec045016a7efa4499f4d9155f362bfed6fdf894

HEAD PR (R3): see current branch HEAD

Date: `2026-08-13`

---

## 2) Méthode de vérification canonique

Source de vérité utilisée pour ce document :

1. HEAD réel de `main` (`f9bada97`) ;
2. audit des merges PR sur `main` ;
3. audit du code réellement présent (`backend/`, `frontend/`, `backend/training_v2/`) ;
4. croisement avec les rapports versionnés (`*_REPORT.md`).

Règle: rien n'est marqué DONE/MERGED s'il n'est pas réellement présent sur `main`.

---

## 3) Foundations DONE / MERGED

### 3.1 Sécurité, auth, isolation, paiements

- DONE / MERGED: auth/JWT + isolation multi-user (PR #59, #60, #61, #66).
- DONE / MERGED: OAuth Google/Apple (PR #44, #45, #46, #48, #63).
- DONE / MERGED: migration Stripe -> Paddle (PR #57, #58, #62).
- DONE / MERGED: hardening admin/sécurité (PR #51, #54).

### 3.2 Garmin data foundations

- DONE / MERGED: Garmin Data Layer (PR #81 / #84 / #88 ; rapports PR01/PR03/PR04).
- DONE / MERGED: normalisation activité unifiée (PR #81 ; rapport PR02).
- DONE / MERGED: `DomainActivity` provider-neutral (PR #106/#109/#113).
- DONE / MERGED: `DomainCapabilities` provider-neutral (PR #107).
- DONE / MERGED: provenance minimale activité (`source`, `source_activity_id`) (PR #109).
- DONE / MERGED: correction data-quality history depth (PR #108).

---

## 4) Readiness V2 — état canonique R1 -> R1.7B

## R1 — Sufficiency layer — PR #110 — MERGED

Niveaux:

- `SUFFICIENT`
- `DEGRADED`
- `INSUFFICIENT`

Reason codes EXACTS (8):

- `missing_hrv`
- `missing_rhr`
- `missing_physio`
- `missing_sleep`
- `missing_load`
- `thin_baseline_rhr`
- `thin_baseline_hrv`
- `thin_load_history`

Règles canoniques:

- `missing_physio` ou `missing_load` => `INSUFFICIENT`.
- Un physio solide suffit: RHR solide **ou** HRV solide.
- Une baseline thin du second signal ne dégrade pas automatiquement si l'autre signal est solide.
- Aucun score 0-100 à ce stade.

Fichier réel: `backend/training_v2/readiness_sufficiency.py`

## R1.5 — Readiness values contract — PR #111 — MERGED

Contrats clés:

- `PhysioBaseline`: `value`, `valid_measures`
- `SleepRecord`: `duration_hours`, `score`

Règle canonique: `None` reste `None` (pas de fallback neutre inventé).

Fichier réel: `backend/training_v2/readiness_sufficiency.py`

## R1.6 — Readiness signals layer — PR #112 — MERGED

Fonctions:

- `compute_rhr_deviation()`
- `compute_hrv_deviation()`
- `extract_sleep_signal()`
- `extract_load_signal()`

Règle canonique: aucun score final dans R1.6.

Fichier réel: `backend/training_v2/readiness_signals.py`

## R1.7A — Activity intensity transport — PR #113 — MERGED

`DomainActivity` transporte:

- `moderate_intensity_minutes`
- `vigorous_intensity_minutes`

Sémantique canonique:

- `0` != `None`
- `0` = provider rapporte zéro minute
- `None` = information absente

Aucune formule de récupération à ce stade.

Fichier réel: `backend/training_v2/domain_activity.py`

---

## 5) R1.7B — TrainingIntensityProfile

Status: **MERGED** (PR #115)

Fichier réel: `backend/training_v2/training_intensity.py`

### Couche pure

`TrainingIntensityProfile` est une couche métier pure et provider-neutral.
Aucun import `garmin.*`, `terra.*`, `strava.*`.
Aucune interprétation physiologique.

### Contrat `TrainingIntensityProfile`

| Champ | Type | Rôle |
|---|---|---|
| `reference_date` | `date` | Date de référence J (explicite) |
| `window_days` | `int` | Largeur fenêtre (V1 = 2) |
| `duration_minutes` | `float` | Somme durées running valides / 60 |
| `moderate_minutes` | `Optional[float]` | Somme moderate connues (None = inconnu) |
| `vigorous_minutes` | `Optional[float]` | Somme vigorous connues (None = inconnu) |
| `activities_total` | `int` | Activités running dans la fenêtre |
| `activities_with_intensity` | `int` | Avec ≥ 1 champ intensité connu |
| `activities_without_intensity` | `int` | Sans aucun champ intensité connu |
| `intensity_coverage_ratio` | `Optional[float]` | with / total ; None si total == 0 |

### Fenêtre V1 : J-1 → J inclus

`window_days = 2`

Fenêtre : `[reference_date - 1 jour, reference_date]`

Ce n'est PAS un rolling 48 heures. C'est une fenêtre calendaire date-based.

`window_days` est conservé dans le contrat pour permettre l'évolution future.

### Durée

`duration_minutes = Σ(duration_s / 60)` pour les activités running de la fenêtre.

`duration_s` utilisable : numérique, non-bool, > 0.

Aucune estimation par distance.

### Règle fondamentale : None ≠ 0

- `None` = valeur inconnue / indisponible.
- `0` = valeur connue et nulle.

Conséquences:
- Si aucune activité de la fenêtre n'a de valeur `moderate` connue → `moderate_minutes = None`.
- `0 + None → 0` (pas None).

### Couverture

Activité "with_intensity" : au moins un champ (`moderate` ou `vigorous`) is not None.

`intensity_coverage_ratio = activities_with_intensity / activities_total`

Si `activities_total == 0` → `intensity_coverage_ratio = None` (pas 0.0).

### Aucune pondération, aucun LT1/LT2, aucun Recovery Time

Interdit dans R1.7B :

- `moderate + 2 × vigorous`
- LT1 / LT2
- TRIMP / TSS / EPOC
- Recovery Time Garmin/Firstbeat
- Score 0-100
- Pondération quelconque

`TrainingIntensityProfile` est une couche **parallèle** de signaux bruts.
Elle ne modifie pas `TrainingLoad`.

---

## 6) R2A — Subscores

Status: **MERGED** — PR #116

Architecture cible:

- RHR deviation -> RHR subscore
- HRV deviation % -> HRV subscore
- RHR + HRV -> PhysioSubscore
- Sleep duration -> SleepSubscore
- Load signal context (`load_change_percent`) -> LoadSubscore

Sorties:

- `Optional[float]`
- `0-100` ou `None`

Règle: **AUCUNE agrégation finale dans R2A**.

### Calibration V1 implémentée

- **PRODUCT CALIBRATION V1**
- **RECALIBRATABLE**
- **NOT SCIENTIFIC UNIVERSAL THRESHOLDS**

RHR delta:

- `<= 0` -> `100`
- `>0 à +2` -> `90`
- `>2 à +4` -> `75`
- `>4 à +6` -> `55`
- `>6 à +8` -> `35`
- `>8` -> `20`

Pas de bonus > 100.

HRV delta %:

- `>= -5 %` -> `100`
- `-5 à -10 %` -> `90`
- `-10 à -20 %` -> `70`
- `-20 à -30 %` -> `45`
- `< -30 %` -> `25`

Sleep duration:

- `>= 8 h` -> `100`
- `7-8 h` -> `90`
- `6-7 h` -> `70`
- `5-6 h` -> `45`
- `< 5 h` -> `20`

Ne pas pénaliser automatiquement `> 9 h`.

LOAD en R2A:

- calibration principale par `load_change_percent`:
  - `<= 10 %` -> `100`
  - `>10 à 25 %` -> `90`
  - `>25 à 40 %` -> `75`
  - `>40 à 60 %` -> `55`
  - `>60 %` -> `35`
- les valeurs négatives restent dans le cas `<= 10 %` (pas de pénalité automatique sur baisse de charge);
- aucun modificateur basé sur `TrainingIntensityProfile`;
- aucune formule `moderate + 2 × vigorous`;
- aucune conversion LT1/LT2, TRIMP, TSS, EPOC ou Recovery Time.

R2A LoadSubscore V1 utilise uniquement `load_change_percent`.
`TrainingIntensityProfile` n'entre pas dans le score R2A et reste une couche de faits indépendante pour une calibration future.

---

## 7) R2B — Aggregation

Status: **MERGED — PR #117**

Module: `backend/training_v2/readiness.py`

Contrat de sortie:

```python
class ReadinessConfidence(str, Enum):
    NONE = "NONE"
    NORMAL = "NORMAL"
    REDUCED = "REDUCED"

class ReadinessResult(BaseModel):
    score: Optional[float]           # 0–100 (1 décimale) ou None
    confidence: ReadinessConfidence  # catégoriel uniquement, jamais numérique
    sufficiency_level: SufficiencyLevel  # propagé depuis R1
    reasons: Tuple[ReasonCode, ...]      # propagé depuis R1
```

Poids produit V1 (PRODUCT_CALIBRATION_V1):

- Physio = 40%
- Sleep = 30%
- Load = 30%

> Product calibration V1, recalibratable, not a scientifically proven universal weighting.

Règles:

- R1 = `INSUFFICIENT` -> `readiness_score = None`, `confidence = NONE`
- R1 = `SUFFICIENT` + 3 sous-scores présents -> calcul normal, `confidence = NORMAL`
- R1 = `SUFFICIENT` + sous-score(s) manquant(s) -> calcul renormalisé, `confidence = REDUCED` (sufficiency_level reste SUFFICIENT)
- R1 = `DEGRADED` -> n'utiliser que les sous-scores disponibles, renormaliser les poids, `confidence = REDUCED`
- Cas défensif (SUFFICIENT/DEGRADED sans sous-score utilisable) -> `score = None`, `confidence = NONE`

`ReadinessConfidence`:
- `NORMAL` → sufficiency SUFFICIENT ET les 3 sous-scores sont effectivement disponibles
- `REDUCED` → sufficiency DEGRADED OU sufficiency SUFFICIENT mais un ou plusieurs sous-scores sont indisponibles
- `NONE` → INSUFFICIENT OU aucun sous-score exploitable

Aucun score fictif pour donnée manquante. None reste None.

Tests: 52 passés (`backend/tests/test_training_v2_readiness.py`).

---

## 8) R3 — Migration `/run-index`

Status: **MERGED — PR #118**

runtime validation = PASSED
E2E Dashboard = PASSED

Objectif: brancher Readiness V2 dans le vrai chemin produit `/run-index`.

### Implémentation (PR #118 — mergée)

Fichiers créés / modifiés:

- `backend/garmin/readiness_adapter.py` ← **CRÉÉ** — boundary Garmin/Mongo → V2 input contract
- `backend/garmin/insights.py` ← **MODIFIÉ** — `compute_run_index` branchée sur V2
- `backend/garmin/service.py` ← **MODIFIÉ** — `readiness_status` basé sur score V2
- `backend/tests/test_run_index_r3_readiness_v2.py` ← **CRÉÉ** — 17 tests déterministes

### Chaîne effective

```
garmin_daily_metrics + garmin_activities (MongoDB)
  → readiness_adapter.build_readiness_v2_from_garmin_data()
    → R1 build_readiness_sufficiency()
    → R1.6 compute_rhr_deviation / compute_hrv_deviation / extract_sleep_signal / extract_load_signal
    → R2A build_physio_subscore / build_sleep_subscore / build_load_subscore
    → R2B build_readiness_result()
  → ReadinessResult
  → /run-index metrics.run_readiness (float|null)
```

### Contrat API `/run-index` enrichi (R3)

```json
{
  "metrics": {
    "run_readiness": 72.3,          // float | null (null si INSUFFICIENT)
    "run_readiness_status": "green",
    "confidence": "NORMAL",         // NORMAL | REDUCED | NONE
    "sufficiency_level": "SUFFICIENT",  // SUFFICIENT | DEGRADED | INSUFFICIENT
    "readiness_reasons": []         // liste de ReasonCode strings
  }
}
```

### Règles respectées

- `training_v2` reste pur, sans DB/Garmin/I/O.
- Aucun fallback fictif : pas de RHR=55, sleep=7h, ACWR=1, readiness=5/70/100.
- `None` reste `None`.
- `metrics.run_readiness = ReadinessResult.score`.
- INSUFFICIENT → `run_readiness=null`.
- TrainingLoad V2 alimente le LoadSubscore (via `build_training_load`).
- Aucune formule R1/R2A/R2B dupliquée.

### Tests déterministes (17 passés)

| # | Scénario | Résultat attendu |
|---|----------|-----------------|
| 1 | Données complètes | score not None, SUFFICIENT, NORMAL |
| 2 | HRV absente | score computed from RHR, missing_hrv |
| 3 | RHR absente | score computed from HRV, missing_rhr |
| 4 | Sommeil absent | DEGRADED, score not None, missing_sleep |
| 5 | Charge absente (0 activités) | INSUFFICIENT, score=None, missing_load |
| 6 | load_change_percent=None | score still computed (REDUCED) |
| 7 | Données insuffisantes (no physio + no load) | INSUFFICIENT, score=None |
| 7b | Physio absent seul | INSUFFICIENT, missing_physio |
| 8 | Isolation user_id | adapter pur, résultats indépendants par user |
| 9 | Backward compat API | run_readiness key always present (float\|null) |
| 10 | No fallback RHR | missing_physio reason present |
| 10b | No fallback sleep | missing_sleep reason present |
| 10c | No fallback ACWR | missing_load reason present |
| + | Déterminisme | mêmes inputs → mêmes outputs |
| + | Immutabilité | ReadinessResult frozen |
| + | Bornes [0,100] | score always in range |
| + | Reason codes valides | all reasons are ReasonCode |

---

## 8.5) R3.5 — TrainingLoad V2 source unique dans `/run-index`

Status: **MERGED — PR #120 — runtime PASS**

HEAD de départ: `9d9074d40e589a45c35343b8395099540a334f01`

### Objectif R3.5

`TrainingLoadSnapshot` V2 devient source unique de vérité pour la charge exposée
dans `/run-index` ET pour Readiness V2.

- `/run-index` utilise désormais TrainingLoad V2 (`build_training_load()`) comme seule source de charge.
- `compute_load_metrics()` (legacy) reste encore utilisé par `/training/metrics`.
- Cette dette n'est **PAS** supprimée dans PR #120.
- NEXT = **R4A** : supprimer uniquement le current readiness legacy de `/run-index`.

### Implémentation (PR #120)

Fichiers modifiés :

- `backend/garmin/insights.py` — `build_training_load()` appelé exactement une fois ; snapshot partagé avec Readiness V2 via `load_snapshot=` ; suppression fallback ACWR=1.0 legacy ; `metrics.training_load_v2` exposé pour observabilité.
- `backend/garmin/readiness_adapter.py` — paramètre `load_snapshot` accepté ; skip double calcul.
- `backend/tests/test_run_index_r3_5_load_alignment.py` — 21 tests déterministes dont 9 appels réels à `compute_run_index(db, user_id, reference_date=...)` avec fake DB.
- `docs/RUNINDEX_R3_5_REPORT.md` — rapport R3.5.

### Chaîne effective R3.5

```
garmin_activities (MongoDB)
  → build_training_load(activities, today)       ← appelé UNE FOIS
      → TrainingLoadSnapshot                     ← source unique
  ↓
  compute_run_index:
    metrics.training_load       = snapshot.acwr  (None si unavailable)
    metrics.training_load_v2    = snapshot.*     (observabilité)
    metrics.training_load_status = acwr_status_to_color(snapshot.status)
  ↓
  build_readiness_v2_from_garmin_data(
      ..., load_snapshot=snapshot               ← réutilise, pas de second calcul
  )
```

### Contrat API `/run-index` enrichi (R3.5)

```json
{
  "metrics": {
    "training_load": 1.05,          // float (acwr arrondi 3 dp) | null
    "training_load_status": "green",
    "training_load_v2": {
      "acute_load_7d": 280.0,
      "load_28d": 1050.0,
      "chronic_weekly_load": 262.5,
      "previous_7d_load": 266.5,
      "load_change_percent": 5.1,
      "acwr": 1.067,
      "status": "balanced",
      "confidence": "high"
    }
  }
}
```

### Dette restante

`compute_load_metrics()` (legacy) reste encore utilisé par `/training/metrics`.
R3.5 garantit une source unique de vérité uniquement pour :
- `/run-index`
- Readiness V2

Pas encore pour toute l'application.
`/training/metrics` utilise encore `compute_load_metrics()` legacy.
Sa migration vers TrainingLoad V2 sera traitée dans une PR dédiée de consumer alignment,
séparée de R4 Readiness.

### Tests (21 passés — 100%)

| ID | Scénario | Résultat |
|----|----------|---------|
| A | `metrics.training_load == round(snapshot.acwr, 3)` via `compute_run_index` réel | PASS |
| B | `metrics.training_load_v2.acwr == snapshot.acwr` via `compute_run_index` réel | PASS |
| C | `metrics.training_load_v2.acute_load_7d == snapshot.acute_load_7d` | PASS |
| D | `metrics.training_load_v2.load_28d == snapshot.load_28d` | PASS |
| E | `metrics.training_load_v2.previous_7d_load == snapshot.previous_7d_load` | PASS |
| F | `metrics.training_load_v2.load_change_percent == snapshot.load_change_percent` | PASS |
| G | 0 activités → `training_load=None`, `acwr=None`, `status=gray` | PASS |
| H | distance sans duration → `training_load=None` (pas de charge inventée) | PASS |
| I | multi-user : `compute_run_index(userA)` n'utilise pas activités userB | PASS |
| + | no ACWR fallback 1.0 quand load absent | PASS |
| + | ACWR None quand pas de chronic load | PASS |
| + | distance-only → acwr None, loads 0.0 | PASS |
| + | distance-only (load=0) | PASS |
| + | durée drive load, pas la distance | PASS |
| + | readiness score identique avec snapshot shared vs calcul interne | PASS |
| + | déterminisme cross-calls | PASS |
| + | isolation multi-user (pure build_training_load) | PASS |
| + | snapshot.acwr None → training_load_response None | PASS |
| + | cohérence interne champs snapshot | PASS |
| + | snapshot zéro activités | PASS |
| + | _acwr_status_to_color mapping | PASS |

---


## 9) R4A — Current readiness legacy cleanup dans `/run-index`

Status: **MERGED — PR #121**

HEAD de départ: `522fbed01c14eff741bb72401bb697a56ea38d13`

### Objectif R4A

Supprimer uniquement le readiness current legacy encore exposé dans `/run-index`,
sans toucher :

- `history[].run_readiness`;
- `/training/metrics` legacy;
- la formule Readiness V2;
- LT1/LT2;
- migrations historiques.

### Implémentation R4A

- suppression de `metrics.legacy_run_readiness` dans `backend/garmin/insights.py`;
- suppression du calcul current legacy associé (`physio_penalty`, `acwr_penalty`, `_legacy_run_readiness`);
- conservation intacte de Readiness V2 comme source unique pour `metrics.run_readiness`;
- conservation de `fatigue_physio`, `fatigue_ratio`, `training_load_v2` et du snapshot partagé;
- conservation de l'historique readiness journalier existant.

### Dettes résolues par R4B

- `history[].run_readiness` migré vers Readiness V2 (voir section R4B ci-dessous).

### Dettes restantes après R4A+R4B

- `fatigue_ratio` dans `history[]` utilise encore la formule legacy (hors périmètre R4B) ;
- `history[].training_load` reste adossé à `_activity_load` (legacy) ;
- `/training/metrics` : migration TrainingLoad V2 mergée — PR #123 (CTL/ATL V2 incorrects retirés ; TSB legacy km temporaire ; ctl/atl → None) ;
- divergence baseline RHR / historique documentée et hors périmètre.

---

## 9b) R4B — history[].run_readiness migré vers Readiness V2

Status: **MERGED — PR #122**

### Objectif R4B

Remplacer uniquement le calcul legacy de `history[].run_readiness` par Readiness V2.

Pour chaque date historique J :
- `reference_date = J` ;
- uniquement les données disponibles à J (metrics date ≤ J, activités start_time ≤ J) ;
- données absentes / dates invalides → **exclues** (jamais de fallback) ;
- appliquer Sufficiency → Signals → Subscores → Readiness V2 ;
- `score = float 0–100` ou `None` (INSUFFICIENT → None).

### Implémentation R4B

- `backend/garmin/insights.py` : filtre strict (date valide ET ≤ J) sur metrics et activités ;
  docs sans date exclus du tableau `history[]` ;
- `backend/tests/test_run_index_r4b_history_readiness_v2.py` : 12 tests couvrant
  les 9 exigences originales + activité sans date exclue, metric sans date exclue,
  données futures exclues (strict).

### Dettes restantes après R4B

- `fatigue_ratio` dans `history[]` utilise encore la formule legacy (hors périmètre) ;
- `history[].training_load` reste adossé à `_activity_load` (legacy) — résolu par R4C ci-dessous ;
- `/training/metrics` : migration vers TrainingLoad V2 MERGED — PR #123
  (CTL/ATL v2 incorrects retirés, TSB legacy km conservé temporairement, ctl/atl → None) ;
- baseline RHR historique : divergence documentée et hors périmètre.

---

## 9c) R4C — history[].training_load migré vers TrainingLoad V2

Status: **MERGED — PR #125**

### Objectif R4C

Aligner uniquement `history[].training_load` sur TrainingLoad V2.

Pour chaque date historique J :
- `build_training_load(activités disponibles à J, reference_date=J)` ;
- `history[].training_load = snapshot.acwr` ;
- `None` reste `None` (pas de fallback, pas d'estimation distance→durée) ;
- aucune donnée future utilisée.

### Implémentation R4C

- `backend/garmin/insights.py` : suppression de `_activity_load()` et du bloc `_daily_load` ;
  dans la boucle history, appel à `build_training_load(hist_activities, hist_day).acwr`
  après filtrage strict des activités (start_time ≤ J) ;
- `backend/tests/test_run_index_r4c_history_load_v2.py` : 6 tests couvrant
  l'alignement ACWR V2, l'absence de fuite future, les activités distance-only → None,
  l'historique insuffisant, la non-régression de `metrics.training_load`, et la shape.

### Dettes restantes après R4C (résolues par #126)

- `fatigue_ratio` dans `history[]` utilise encore la formule legacy → **résolu en #126** ;
- baseline RHR historique : divergence documentée → **résolue en #126** ;
- TSB dans `/training/metrics` : legacy km conservé temporairement → **NEXT #127**.

---

## 9d) #126 — Final /run-index physiology legacy cleanup

Status: **IMPLEMENTED / PENDING MERGE — PR #126**

### Objectif #126

Finaliser l'alignement physiologique de `/run-index` avec Readiness V2.

Deux axes :

1. **HISTORY FATIGUE** — supprimer de `history[]` :
   - `fatigue_ratio` (clé et valeur)
   - formule legacy associée (`doc_sleep_penalty`, `doc_fp`, `doc_rhr_delta`, `doc_fatigue_ratio`)
   - fallback `sleep=7h` sur `doc.get("sleep_hours") or 7.0`
   - fallback `rhr_delta=0` sur doc absent

2. **RHR BASELINE** — unification source unique avec Readiness V2 :
   - `metrics.rhr_baseline` affiche désormais la même valeur que Readiness V2
     (fenêtre 14 jours, excluding today, via `get_rhr_v2_baseline()`) ;
   - suppression du fallback fictif `55.0` et du fallback `rhr_today` ;
   - `metrics.rhr_delta` : `None` quand `rhr_today` ou `rhr_baseline` absent ;
   - aucune modification de la calibration Readiness V2 (seulement une exposition
     de la logique existante via `get_rhr_v2_baseline()` dans `readiness_adapter.py`).

### Décisions exactes

- `metrics.fatigue_ratio` **CONSERVÉ** (toujours consommé par CardioCoach / server.py).
- `fatigue_status` **CONSERVÉ** (dérivé de `fatigue_ratio` courant).
- `TSB / CTL / ATL`, `TrainingLoad V2`, `LT1/LT2`, `Training Engine` : **NON MODIFIÉS**.
- La formule Readiness V2 n'a pas été modifiée — seule la surface d'exposition d'une
  valeur interne existante (`_baseline_for`) a été rendue publique.

### Legacy supprimé

| Élément supprimé | Fichier | Raison |
|---|---|---|
| `fatigue_ratio` dans `history[]` | `garmin/insights.py` | formule legacy hors V2 |
| `doc_sleep_penalty` dans boucle history | `garmin/insights.py` | fallback sleep=7h |
| `doc_rhr_delta` dans boucle history | `garmin/insights.py` | fallback delta=0 |
| `doc_fp` / `doc_fatigue_ratio` dans boucle history | `garmin/insights.py` | calcul fatigue legacy |
| `rhr_baseline = _mean(30 docs)` + fallback `55.0` | `garmin/insights.py` | diverge de V2 |

### Implémentation #126

- `backend/garmin/readiness_adapter.py` : ajout de `get_rhr_v2_baseline()` (wrapper public
  sur `_build_physio_signal` pour `resting_hr`) — source unique de vérité pour la baseline RHR.
- `backend/garmin/insights.py` :
  - import `get_rhr_v2_baseline` ;
  - `rhr_baseline` calculé via `get_rhr_v2_baseline(metrics_docs, today)` ;
  - suppression du fallback `55.0` / `rhr_today` ;
  - `rhr_delta : Optional[float]` — None quand baseline absente ;
  - `rhr_status` gère `rhr_delta=None` → **"gray"** (jamais "green" pour données absentes) ;
  - raison RHR uniquement affichée quand `rhr_delta is not None` ;
  - boucle history : suppression de toutes les variables fatigue legacy ;
  - `history[]` : clé `fatigue_ratio` supprimée.
- `frontend/src/pages/Dashboard.jsx` :
  - `ReadinessTile` gère explicitement le statut `"gray"` (couleur `#6b7280`) ;
  - tuile RHR : fallback `m.rhr_status || "gray"` (plus `|| "green"`) ;
  - valeur absente (`rhr_today=null`) affichée `"—"`, aucun signal positif fictif.
- `backend/tests/test_run_index_screen.py` / `test_cardio_coach_screen.py` :
  - `VALID_STATUSES` étendu à `{"green", "yellow", "red", "gray"}`.
- `backend/tests/test_run_index_r4b_history_readiness_v2.py` : shape mise à jour (sans `fatigue_ratio`).
- `backend/tests/test_run_index_r4c_history_load_v2.py` : assertion inversée (`fatigue_ratio` absent).
- `backend/tests/test_run_index_r5_history_fatigue_cleanup.py` : **nouveau** — 13 tests couvrant
  l'absence de `fatigue_ratio` en history, la shape, la non-régression readiness/load,
  l'alignement baseline RHR V2, `rhr_delta=None`, `rhr_baseline=None` sans données prior,
  la non-régression `metrics.fatigue_ratio`, l'isolation multi-user, et la sémantique
  **None ≠ green** pour `rhr_status` (tests 11-13).
- `frontend/src/__tests__/dashboard-run-readiness-null.test.jsx` : tests RHR absent → tuile grise,
  affichage `"—"`, absence de couleur verte, sans crash.

### Règle sémantique RHR — None ≠ green

> **`rhr_delta=None` → `rhr_status="gray"`, jamais `"green"`.**
>
> Une baseline ou valeur RHR absente n'est pas un signal positif. Le statut `"gray"` (indisponible)
> est le seul mapping correct pour l'absence de données. Le statut `"green"` est réservé aux cas
> où `rhr_delta` est présent et ≤ 3 bpm.

### Dettes restantes après #126

- TSB dans `/training/metrics` : legacy km → **SUPPRIMÉ en #127**.
- `fatigue_ratio` dans `metrics` (courant) : toujours legacy (CardioCoach), à évaluer post-#127.
- Frontend : adaptation null TSB/ACWR → **FAIT en #127**.

### #127 — Training metrics / TSB legacy cleanup (IMPLEMENTED / PENDING MERGE)

| Layer | Status | Fichier / PR |
|---|---|---|
| TrainingHistory | DONE | `backend/training_v2/training_history.py` — PR #89 |
| TrainingLoad | DONE | `backend/training_v2/training_load.py` — PR #90 |
| RunnerProfile | DONE | `backend/training_v2/runner_profile.py` — PR #93 |
| TrainingState | DONE | `backend/training_v2/training_state.py` — PR #94 |
| PlanGoal | DONE | `backend/training_v2/plan_goal.py` — PR #95 |
| Periodization | DONE | `backend/training_v2/periodization.py` — PR #96 |
| Weekly Target | PARTIAL | logique active en legacy `backend/training_engine.py` (`compute_target_km`, `resolve_reprise_plan`) — pas encore couche V2 dédiée |
| Workout Generator | PARTIAL | génération active legacy `backend/llm_coach.py` (`generate_cycle_week`) + `backend/coach_service.py` |
| Workout Analysis | PARTIAL | analyse active via `backend/analysis_engine.py`, `backend/rag_engine.py`, endpoints `/api/coach/*` |
| Daily Recommendation / Adaptation | PARTIAL | adaptation active `backend/training_engine.py` (`adapt_session_to_readiness`) + endpoint `/api/training/today` dans `backend/server.py` |

Conclusion canonique:

Après `Periodization`, les consommateurs métier (weekly target/génération/analyse/recommandation) restent majoritairement en pipeline legacy actif, pas encore migrés en couches V2 pures dédiées.

---

## 11) Principes physiologiques (cadre métier)

LT1 / LT2:

- sous LT1: domaine d'équilibre métabolique ;
- autour de LT1: travail submaximal pertinent ;
- entre LT1 et LT2: dérive cardiaque modérée ;
- au-dessus LT2: déséquilibre et dérive plus rapides.

Principe: ne pas réduire ce cadre à une logique simpliste de "zone grise".

Débutants / reprise:

Priorité à la base aérobie + tolérance mécanique avant une intensité LT2 importante.

---

## 12) Reprise (état canonique)

Règle produit:

**niveau réellement toléré -> progression -> objectif**

et non:

**objectif -> minimum kilométrique artificiel**.

États présents sur `main` (logique active):

- `deep_reprise`
- `partial_reprise`
- `reprise_exit`
- `normal`

Références code:

- `backend/training_engine.py` (`classify_training_state`, `resolve_reprise_plan`)
- consommation dans `backend/coach_service.py` et `backend/server.py`

---

## 13) Objectifs / plan (décisions produit)

Objectifs:

- 5K
- 10K
- Semi
- Marathon
- Maintien en forme

Deux types de plans:

1. avec course cible;
2. maintien / sans course cible.

Course cible -> périodisation + taper.

Sans course -> aucun faux taper.

Un plan doit pouvoir contenir:

- target weekly km;
- target time / performance.

Target time possible même sans date de course (contrat `PlanGoal`: `target_time_seconds` optionnel, `race_date` optionnelle hors maintenance).

---

## 14) Frontend / Onboarding (après stabilisation moteur)

Status: **PLANNED** pour l'orchestration finale produit bout-en-bout, avec base technique déjà présente.

Onboarding Garmin cible:

1. Garmin connecté
2. Sync en cours
3. Nombre d'activités importées
4. Première valeur utile rapidement
5. Readiness si données suffisantes
6. Recommandation du jour
7. Séance du jour
8. CTA: Voir mon tableau de bord
9. Secondaire: Ajuster mon objectif

Cas à couvrir:

- sync OK + activités
- sync OK + 0 activité
- sync en cours
- sync échouée

Règle: ne jamais afficher de faux score.

Validations déjà confirmées sur `main`:

- phased sync (PR #97)
- payload progressif sync (incluant `run_index`, `readiness`, `activities_count`) (PR #103/#104)
- `SSEAwareGZipMiddleware` / bypass gzip SSE (PR #104)
- validation streaming edge Cloudflare documentée (`GARMIN_SSE_EDGE_FINAL_VALIDATION.md`)
- hook frontend robuste `useGarminSyncProgress` + parcours onboarding (`frontend/src/pages/Onboarding.jsx`)

---

## 15) ADMIN AUDIT

Status: **PLANNED**

Scope futur:

- routes admin;
- auth;
- autorisation;
- endpoints sensibles;
- métriques;
- cache;
- données utilisateur;
- frontend admin;
- FREE/TRIAL/PREMIUM;
- isolation multi-user;
- endpoints legacy.

---

## 16) Subscription / Access (état canonique)

Si confirmé sur `main`:

- `FREE`
- `TRIAL Premium`
- `PREMIUM`

Règles:

- Trial: 30 jours sans carte (activation serveur, anti-abuse côté backend).
- Premium: 4,99 €/mois (Paddle).
- Anti-abuse: 1 compte Garmin = 1 trial (contrat `subscription_manager`).

Aucun changement paiement dans cette PR documentaire.

---

## 17) Legacy cleanup (phase finale)

Status: **PLANNED**

Inclure:

- cartographie callers;
- fonctions mortes;
- doublons;
- formules contradictoires;
- vieux adapters;
- vieux endpoints;
- Terra legacy;
- imports morts;
- tests obsolètes.

Règle canonique:

**migration -> validation runtime -> suppression legacy**

Jamais l'inverse.

---

## 18) Validation finale avant release readiness

Inclure:

- tests unitaires;
- intégration;
- runtime backend;
- worker;
- Garmin sync;
- SSE;
- onboarding;
- Readiness;
- plan;
- daily recommendation;
- subscriptions;
- admin;
- multi-user isolation;
- frontend.

Puis:

**kill legacy -> cleanup final -> release readiness**

---

## 19) Roadmap executive summary (checklist)

### FOUNDATIONS

- [x] Garmin Data Layer
- [x] DomainActivity
- [x] DomainCapabilities
- [x] provenance
- [x] data-quality history depth

### READINESS

- [x] R1 Sufficiency
- [x] R1.5 Values
- [x] R1.6 Signals
- [x] R1.7A Intensity transport
- [x] R1.7B TrainingIntensityProfile (MERGED, PR #115)
- [x] R2A Subscores (MERGED, PR #116)
- [x] R2B Aggregation (MERGED — PR #117)
- [x] R3 /run-index migration (MERGED — PR #118 — runtime validation PASSED — E2E Dashboard PASSED)
- [x] R3 validation runtime (PASSED)
- [x] R3.5 TrainingLoad V2 source unique /run-index (MERGED — PR #120 — runtime PASS)
- [x] R4A kill current readiness legacy (MERGED — PR #121)
- [x] R4B history[].run_readiness → Readiness V2 (MERGED — PR #122)
- [x] TrainingLoad /training/metrics alignment (MERGED — PR #123)
- [x] Cleanup helpers TrainingLoad legacy morts (MERGED — PR #124)
- [x] R4C history[].training_load → TrainingLoad V2 (MERGED — PR #125)
- [x] #126 history[] fatigue legacy cleanup + RHR baseline unification (MERGED — PR #126)
- [x] #127 Training metrics / TSB legacy cleanup (IMPLEMENTED / PENDING MERGE — PR #127)

### TRAINING ENGINE

- [x] TrainingHistory
- [x] TrainingLoad
- [x] RunnerProfile
- [x] TrainingState
- [x] PlanGoal
- [x] Periodization
- [ ] Weekly Target (couche V2 dédiée)
- [ ] Workout Generator (couche V2 dédiée)
- [ ] Workout Analysis (couche V2 dédiée)
- [ ] migration consumers
- [ ] kill legacy

### PRODUCT

- [ ] frontend adaptation
- [ ] onboarding adaptation
- [ ] admin audit
- [ ] E2E validation

### FINAL

- [ ] legacy cleanup
- [ ] runtime validation
- [ ] release readiness

---

## 20) SECONDARY CLEANUP / NON-BLOCKING

- PR #98: cleanup administratif (ne pas bloquer la roadmap Readiness V2).
- Mise à jour documentation déploiement: alignement doc/repo (ne pas bloquer R1.7B/R2).

Ces sujets restent secondaires et ne précèdent pas la roadmap principale Readiness V2.

---

## 21) Périmètre strict de la mise à jour canonique

Ce document suit l'état réel de `main` et des PR en cours:

- R1.7B est **MERGED** (PR #115).
- R2A est **MERGED** (PR #116).
- R2B est **MERGED — PR #117**.
- R3 est **MERGED — PR #118 — runtime PASS**.
- R3.5 est **MERGED — PR #120 — runtime PASS**.
- R4A est **MERGED — PR #121**.
- R4B est **MERGED — PR #122** (`history[].run_readiness` → Readiness V2).
- TrainingLoad `/training/metrics` alignment est **MERGED — PR #123**
  (CTL/ATL V2 incorrects retirés; TSB legacy km conservé temporairement; ctl/atl → None;
  `has_sufficient_history` commentaire non-reprise retiré).
- Cleanup helpers TrainingLoad legacy morts est **MERGED — PR #124**.
- R4C history[].training_load → TrainingLoad V2 est **MERGED — PR #125**
  (`history[].training_load = build_training_load(acts_at_J, J).acwr` ;
  `_activity_load` supprimé ; aucune fuite future ; aucun fallback distance→durée).
- #126 final physiology legacy cleanup est **MERGED — PR #126**
  (`fatigue_ratio` supprimé de `history[]` ; baseline RHR unifiée avec Readiness V2 via
  `get_rhr_v2_baseline()` ; fallback `55.0` supprimé ; `rhr_delta=None` quand absent ;
  `metrics.fatigue_ratio` conservé ; aucune modification calibration Readiness V2).
- #127 Training metrics / TSB legacy cleanup est **IMPLEMENTED / PENDING MERGE — PR #127**
  (voir section 23 ci-dessous pour le détail complet).
- Dettes restantes après corrections pré-merge : `fatigue_ratio` dans `metrics` : toujours
  legacy CardioCoach, à évaluer post-#127. `computeTrainingLoad` (terra_integration.py) reste
  en place mais n'est plus appelé par `/run-index` ; il peut être supprimé dans une PR dédiée.

---

## 23) PR #127 — Training metrics / TSB legacy cleanup + corrections pré-merge (IMPLEMENTED)

### Callers audités

| Consumer | Champ | Avant | Après |
|---|---|---|---|
| `server.py /training/metrics` | `tsb` | km-based `load_28/4 - load_7` | `None` (supprimé) |
| `server.py /training/metrics` | `ctl`, `atl` | déjà `None` (#123) | `None` inchangé |
| `server.py /training/metrics` | `acwr` | V2 `build_training_load` (#123) | V2 inchangé |
| `server.py /coach/analyze` | `ctl`, `atl`, `tsb` | km-based calculés | supprimés |
| `server.py /coach/analyze` | `acwr` | km-based `km_7/(km_28/4)` | `None` (V2 indisponible dans ce contexte) |
| `server.py /run-index` (Terra path) | `acwr` | `float(...) if not None else 0.0` + `max(0.1, acwr)` | TrainingLoad V2 (`build_training_load` sur `db.workouts`), `None` si pas de données durée |
| `server.py /training/week-plan` | `ctl`, `atl`, `tsb`, `acwr` | km-based avec fallbacks | `None`/`None`/`None`/`None` |
| `coach_service.py` | `ctl`, `atl`, `tsb`, `acwr` | km-based calculés explicitement | supprimés ; `load_7/load_28` conservés pour training engine |
| `llm_coach.py prompt` | `acwr` | `fitness.get('acwr', 1.0)` | `fitness.get('acwr')` None-safe |
| `llm_coach.py prompt` | `tsb` | `fitness.get('tsb', 0)` | `fitness.get('tsb')` None-safe |
| `frontend/TrainingPlan.jsx` | ACWR display | `\|\| "1.00"` fallback | `null`-safe (affiche "—") |
| `frontend/TrainingPlan.jsx` | TSB display | `\|\| "0.0"` fallback | `null`-safe (affiche "—") |
| `training_engine.determine_target_load` | `ctl`, `acwr`, `tsb` | crash si `None` | signaux absents ignorés : base calculée depuis `load_28/4`, `load_7` ou `weekly_km` si `ctl` absent ; `adjust_load_by_fatigue` sauté si `acwr` ou `tsb` absent |

### Champs supprimés

- `tsb` km-based dans `/training/metrics` → `None`
- `ctl`/`atl`/`tsb` km-based dans `/coach/analyze` context fitness
- `ctl`/`atl`/`tsb` km-based dans `coach_service.py` fitness_data
- Calcul km-based `km_7/(km_28/4)` dans `/coach/analyze` (remplacé par `None`)
- Calcul km-based `load_7/(load_28/4)` dans `/training/week-plan` (remplacé par `None`)
- Fallback `acwr=1.0` dans `/coach/analyze`, `coach_service.py`
- Fallback `acwr=1.0` et `tsb=0` dans `llm_coach.py` prompt
- `None→0.0→clamp 0.1` dans `/run-index` Terra path (remplacé par V2 propagation `None`)

### Champs conservés

- `load_7`/`load_28` en km dans `coach_service.py` (inputs volume pour training engine interne, non présentés comme métriques physiologiques)
- `/run-index` Terra path migré vers TrainingLoad V2 (`build_training_load` sur `db.workouts` adaptés) ; `acwr=None` si pas de durées disponibles

### Dettes réellement restantes

- `fatigue_ratio` dans `metrics` (CardioCoach / Terra path) : hors périmètre #127, à évaluer post-merge.
- `computeTrainingLoad` (terra_integration.py) n'est plus appelé par `/run-index` mais reste dans le code ; peut être supprimé dans une PR dédiée nettoyage.
- NEXT LT1/LT2 : aucun consumer ne produit plus de faux ACWR km-based exposé (condition remplie).

### Tests couverts (PR #127)

- `tests/test_training_metrics_pr127.py` (32 tests) :
  TSB=None, ACWR=None (no fallback), ACWR V2 alignment, acwr_reliable non-régressé,
  no duplicate km CTL/ATL/TSB dans coach_service, no fallback LLM, multi-user isolation,
  no km-based ACWR dans /coach/analyze, no km-based ACWR dans /training/week-plan,
  no None→0.0→0.1 clamp dans /run-index, V2 migration vérifiée, week-plan acwr=None supporté.
- `tests/test_training_metrics_endpoint.py` (non-régression, 8 tests PASSED).

### Décision NEXT

Aucune dette bloquante sur le contrat Training metrics V2. Aucun consumer ne produit de faux ACWR.
→ NEXT : **Threshold Estimator LT1/LT2** (voir section 22).

---

## 22) Décision produit canonique — LT1 / LT2 (phase grand public)

RunIndex est une application grand public.
La version LT1/LT2 initiale ne dépend pas de mesures laboratoire.

Cible produit:

- estimation automatique personnalisée LT1/LT2 basée sur les données d'entraînement disponibles.

Roadmap post-Readiness V2:

- P1 — enrichissement provider-neutral des faits activité (dont FC quand réellement disponible)
- P2 — ThresholdEvidence
- P3 — LT2 Estimator V1
- P4 — LT1 Estimator V1
- P5 — Confidence / Calibration

puis:

- Weekly Target V2
- Workout Generator V2
- Training Intensity Distribution LT1/LT2
- Workout Analysis V2
- Daily Adaptation V2

Principes:

- pas de laboratoire requis ;
- pas de `%FCmax` fixe présenté comme LT1/LT2 individuel ;
- pas de faux seuil quand les données sont insuffisantes ;
- LT1 peut être `None` alors que LT2 est estimable, et inversement ;
- estimation basée sur convergence de preuves historiques ;
- confidence explicite ;
- aucune assimilation automatique: `Garmin moderate/vigorous == LT1/LT2` ;
- les minutes Garmin R1.7B restent des faits provider-normalisés.
