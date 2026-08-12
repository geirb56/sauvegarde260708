# RunIndex — Master Roadmap & Decisions (canonique)

## 1. PURPOSE

Ce document est :

- le point de reprise canonique du projet RunIndex ;
- la synthèse des décisions métier et techniques validées ;
- la roadmap d'exécution ;
- un moyen d'éviter la perte de contexte entre sessions/outils.

Last verified against main: `3d03d99` (Merge PR #113)

Date: `2026-08-12`

---

## 2. Méthode de vérification (source de vérité)

Ce document est basé sur :

1. le HEAD réel de `main` (`3d03d99`) ;
2. l'audit des merges PR sur `main` (PR #39 → #113) ;
3. la vérification du code présent (backend, frontend, `training_v2`, Garmin SSE/sync, auth, paiements) ;
4. les rapports techniques déjà versionnés dans le dépôt (fichiers `*_REPORT.md`).

Règle appliquée : rien n'est marqué "fait" si ce n'est pas réellement mergé sur `main`.

---

## 3. Décisions canoniques validées (DONE / MERGED)

## 3.1 Sécurité, auth, isolation multi-utilisateur, paiements

- **DONE / MERGED**: durcissement auth/JWT et isolation des données utilisateur (PR #59, #60, #61, #66).
- **DONE / MERGED**: OAuth Google/Apple finalisé côté produit (PR #44, #45, #46, #48, #63).
- **DONE / MERGED**: suppression Stripe legacy + migration Paddle (PR #57, #58, #62).
- **DONE / MERGED**: protections admin/sécurité complémentaires (PR #51, #54).

## 3.2 Garmin ingestion + normalisation + capacités

- **DONE / MERGED**: fondation data layer Garmin (PR #81 / #84 / #88 + rapports PR01/PR03/PR04).
- **DONE / MERGED**: normalisation d'activité centralisée (PR #81, rapport PR02).
- **DONE / MERGED**: métriques quotidiennes Garmin routées par modèle dédié (PR #84).
- **DONE / MERGED**: capacités observées consolidées (HRV/VO2/etc.) (PR #88).

## 3.3 Pipeline Garmin async (phased sync + SSE)

- **DONE / MERGED**: sync Garmin phasée côté backend (PR #97, rapport PR07A).
- **DONE / MERGED**: streaming progression sync SSE + robustesse hook front (PR #99, #100, #101, #103, #104 ; rapports PR07B/PR07C).
- **DONE / MERGED**: activation RunIndex phasée pendant onboarding Garmin (PR #102).

## 3.4 Moteur entraînement historique (pré-V2)

- **DONE / MERGED**: corrections moteur plan d'entraînement (PR #70, #71, #72, #73, #74, #76).
- **DONE / MERGED**: retrait du faux `next_workout` des payloads (PR #79).
- **DONE / MERGED**: correctif `training_load` historique journalier (PR #78).

## 3.5 Couches pures `training_v2` (découplage métier)

- **DONE / MERGED**: `TrainingHistory` (fenêtres 7/30/90) (PR #89).
- **DONE / MERGED**: `TrainingLoadSnapshot` ACWR 7/28 (PR #90).
- **DONE / MERGED**: `RunnerProfile` (PR #93).
- **DONE / MERGED**: `TrainingState` (2 axes continuité/charge) (PR #94).
- **DONE / MERGED**: `PlanGoal` (PR #95).
- **DONE / MERGED**: `Periodization` (PR #96).
- **DONE / MERGED**: découplage provider via `DomainActivity` / `DomainCapabilities` (PR #106, #107, #109, #113).
- **DONE / MERGED**: `ReadinessSufficiency` + `ReadinessSignals` (PR #110, #112).

---

## 4. Roadmap d'exécution (état canonique)

## 4.1 NEXT

- Vérifier et fermer/superséder la PR draft **#98** (ouverte) pour éviter la divergence avec le flux déjà mergé en PR #99.
- Aligner la documentation de déploiement avec l'état réel du code Garmin/auth (voir divergences section 5).
- Finaliser la couche suivante de readiness V2 (scoring/valeurs), non visible aujourd'hui comme module V2 dédié sur `main`.

## 4.2 PLANNED

- Exécution de la roadmap de déploiement (`DEPLOYMENT.md`) : staging complet, puis production multi-utilisateurs, puis scale/observabilité.
- Validation opérationnelle complète Paddle en conditions réelles (webhook + cycle abonnement bout en bout).
- Campagne de tests de charge et d'exploitation (sync concurrente, workers, monitoring).

## 4.3 DEFERRED / FUTURE

- PR07D benchmark réel complémentaire / optimisations sync Garmin (explicitement laissé futur dans `GARMIN_PHASED_SYNC_PR07A_REPORT.md`).
- Signaux subjectifs de reprise (`recovery_red_flag`) explicitement reportés dans `REPRISE_PR77_REPORT.md`.
- Garmin OAuth officiel/multi-compte standard (documenté comme cible future dans les audits mémoire/déploiement).

---

## 5. Divergences constatées (documentées, non inventées)

1. **Métadonnée GitHub `merged=false` sur PR fermées**
   - L'API PR retourne parfois `merged=false` alors que `merged_at` est rempli.
   - La vérification canonique utilise les merges réels de `main` (commits `Merge pull request #...`).

2. **`DEPLOYMENT.md` vs état code Garmin**
   - `DEPLOYMENT.md` mentionne un modèle Garmin global/mono-compte.
   - Le code `main` contient un flux per-user explicite (`get_provider_for_user(... allow_global_account=False)`, onboarding avec credentials utilisateur, isolation par `user_id`).
   - Conclusion canonique: le document de déploiement est partiellement en retard sur ce point.

3. **Roadmap historique vs état actuel V2**
   - Les rapports historiques décrivent des étapes intermédiaires.
   - La vérité canonique doit être relue depuis les modules `backend/training_v2/*` présents sur `main`.

---

## 6. Périmètre de ce document

- Cette PR est **strictement documentaire**.
- Aucun code applicatif modifié.
- Aucune formule modifiée.
- Aucun refactor de code.
- Aucune configuration modifiée.
