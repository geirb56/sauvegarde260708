# RunIndex — Master Roadmap & Decisions (canonique)

## 1) PURPOSE

Ce document est :

- le point de reprise canonique du projet RunIndex ;
- la synthèse des décisions métier et techniques validées ;
- la roadmap d'exécution ;
- un moyen d'éviter la perte de contexte entre sessions/outils.

Last verified against main: `f9bada97d72d4e159c2e7f6cc86781b110efe82c` (Merge PR #116)

HEAD PR (R2B): see current branch HEAD

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

Status: **IMPLEMENTED IN PR / PENDING MERGE**

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

Status: **PLANNED**

Objectif:

Brancher Readiness V2 dans le vrai chemin produit `/run-index`.

Prévoir:

- comparaison legacy / V2;
- `reasons`;
- `confidence`;
- `score=None` si insuffisant;
- non-régression API;
- validation runtime;
- aucun fallback neutre.

---

## 9) R4 — Kill readiness legacy

Status: **PLANNED** (après validation R3)

Supprimer seulement après migration validée:

- ancien `readiness_engine`;
- formules concurrentes;
- fallback readiness `70`;
- RHR fictive `55`;
- sommeil fictif `7 h` / score neutre;
- ACWR neutre inventé;
- code mort associé.

---

## 10) Training Engine V2 — état réel de `main`

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
- [x] R2B Aggregation (IMPLEMENTED IN PR / PENDING MERGE)
- [ ] R3 /run-index migration
- [ ] R4 kill legacy

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
- R2B est **IMPLEMENTED IN PR / PENDING MERGE**.
- R3 est **NEXT**.

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
