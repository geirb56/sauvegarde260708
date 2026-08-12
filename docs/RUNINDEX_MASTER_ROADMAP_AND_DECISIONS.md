# RunIndex — Master Roadmap & Decisions (canonique)

## 1) PURPOSE

Ce document est :

- le point de reprise canonique du projet RunIndex ;
- la synthèse des décisions métier et techniques validées ;
- la roadmap d'exécution ;
- un moyen d'éviter la perte de contexte entre sessions/outils.

Last verified against main: `3d03d99` (Merge PR #113)

Date: `2026-08-12`

---

## 2) Méthode de vérification canonique

Source de vérité utilisée pour ce document :

1. HEAD réel de `main` (`3d03d99`) ;
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

## 4) Readiness V2 — état canonique R1 -> R1.7A

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

## 5) NEXT canonique

## R1.7B — Acute Recovery Context

Status: **NEXT**

Objectif:

Agréger séparément sur **J + J-1** (date-based):

- `recent_duration_minutes_2d`
- `recent_moderate_minutes_2d`
- `recent_vigorous_minutes_2d`

Contraintes:

- J + J-1, pas vrai rolling 48h tant que le domaine est date-based;
- aucune formule de Recovery Time;
- aucun `moderate + 2 × vigorous`;
- aucune pondération;
- aucun score 0-100;
- aucune tentative de reproduire Garmin / Firstbeat.

---

## 6) R2A — Subscores

Status: **PLANNED** (immédiatement après R1.7B)

Architecture cible:

- RHR deviation -> RHR subscore
- HRV deviation % -> HRV subscore
- RHR + HRV -> PhysioSubscore
- Sleep duration -> SleepSubscore
- Weekly load context + Acute recovery context J/J-1 -> LoadSubscore

Sorties:

- `Optional[float]`
- `0-100` ou `None`

Règle: **AUCUNE agrégation finale dans R2A**.

### Calibration V1 envisagée

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

- ne pas figer une formule complète maintenant;
- utiliser `load_change_percent`, `recent_duration_minutes_2d`, `recent_moderate_minutes_2d`, `recent_vigorous_minutes_2d`;
- ACWR reste contexte/annotation;
- ne pas écrire `moderate + 2 × vigorous` comme formule de récupération.

---

## 7) R2B — Aggregation

Status: **PLANNED**

Règles:

- R1 = `INSUFFICIENT` -> `readiness_score = None`
- R1 = `SUFFICIENT` -> calcul normal
- R1 = `DEGRADED` -> n'utiliser que les sous-scores disponibles, renormaliser les poids, marquer confidence reduced

Poids produit V1 envisagés:

- Physio = 40%
- Sleep = 30%
- Load = 30%

Mention obligatoire:

> Product calibration V1, not a scientifically proven universal weighting.

Exemple:

- Physio = 70
- Sleep = None
- Load = 80

Score:

`(70×40 + 80×30) / 70 ≈ 74`

Aucun SleepScore fictif.

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
- [ ] R1.7B Acute Recovery Context
- [ ] R2A Subscores
- [ ] R2B Aggregation
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

## 21) Périmètre strict de cette PR

- Uniquement `docs/RUNINDEX_MASTER_ROADMAP_AND_DECISIONS.md`
- Aucun code applicatif
- Aucun refactor
- Aucune configuration
- Aucun test applicatif
- Aucun autre fichier
