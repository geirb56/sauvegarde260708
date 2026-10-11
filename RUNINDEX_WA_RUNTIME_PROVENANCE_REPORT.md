# RUNINDEX — Audit runtime WA-Provenance (A = sortie longue, B = footing)

> Audit **lecture seule** (Emergent). Aucun changement de code/données, aucun réimport/sync Garmin, aucun worker démarré, aucun enrichissement déclenché pour A/B, aucun commit/push/PR. Drift local `activity_day` préservé. Aucune donnée personnelle ni secret exposé.

---

## 0. Environnement

| Élément | Valeur |
|---|---|
| HEAD local | `912ffdf` (merge local, parent canonique **`d81fb53`** = PR #329) |
| Compte réel | `da8505ef…` (anonymisé), `source=garmin` |
| Activité **A** (sortie longue) | `garmin-24346252881` · ext `24346252881` · « Pluneret » · 2026-09-13 · 21,27 km / 2h02 / 160 bpm |
| Activité **B** (footing) | `garmin-24532537854` · ext `24532537854` · « Séné » · 2026-09-28 · 10,18 km / 1h11 / 127 bpm |

Correspondance d'identifiant : GCCLI/int ↔ Mongo `external_id` **str** — cohérente pour les deux.

---

## 1. Documents MongoDB (couverture des champs)

**A et B ont une couverture strictement identique** (état « résumé seul », pré-enrichissement #321) :

| Champ | A (21,27 km) | B (10,18 km) |
|---|---|---|
| `raw_payload` | 7 clés résumé | 7 clés résumé |
| `garmin_activity.avg_hr` | 160.0 | 127.0 |
| `garmin_activity.average_run_cadence` | **170,3 spm (présent)** | **152,4 spm (présent)** |
| `garmin_activity.elevation_gain` | **186,9 m (présent)** | **37,4 m (présent)** |
| `garmin_activity.lap_count` / `has_splits` / `has_hr_zones` | None / None / None | None / None / None |
| `km_splits` | **None** | **None** |
| `split_analysis` | **None** | **None** |
| `pace_stats` | **None** | **None** |
| `hr_analysis` | **None** | **None** |
| `activity_details` (phases typed-splits) | **None** | **None** |

**CONCLUSION DÉMONTRÉE** : ni A ni B ne possèdent de splits kilométriques, d'analyse de splits/allure/FC, ni de phases structurées en base. Seules les métriques résumé existent — plus **cadence** et **dénivelé** (présents mais, voir §3, non transportés).

---

## 2. Enrichissement V2 — phases (état cache)

`GET /api/garmin/activities/{id}/phases` (cache-only, lecture) :

| Activité | `fetch_status` | `activity_details` |
|---|---|---|
| A | `not_requested` | None (jamais récupéré) |
| B | `not_requested` | None (jamais récupéré) |

**CONCLUSION DÉMONTRÉE** : l'enrichissement typed-splits (#321) n'a **jamais été déclenché** pour A/B (seule l'activité 4×4min `24671804067` l'avait été lors de la validation #321). Le chemin de récupération existe et est prêt ; il n'a pas tourné. Je ne l'ai **pas** déclenché (contrainte « aucun réimport/sync »).

**HYPOTHÈSE NON CONFIRMÉE** : le contenu exact des typed-splits de A/B. Comme A et B sont des courses **continues** (pas de séance à intervalles), un fetch retournerait vraisemblablement surtout des segments auto `RWD_*` + peu de laps structurés — donc une valeur ajoutée faible pour la détection d'intervalles. Non vérifié (non récupéré).

---

## 3. Réponses API WA V2 (lecture seule) et transport

`GET /api/coach/workout-analysis/{id}?language=fr` → HTTP 200 pour A et B.

| | A | B |
|---|---|---|
| `signals.session_type` | **`long` — « Séance longue »** | **`standard` — « Séance standard »** |
| `signals.intensity.available` | false | false |
| `phase_analysis.available` / `analysis_type` | false / `standard` | false / `standard` |
| `physiology.avg_hr` / `max_hr` | 160 / 174 | 127 / 144 |
| `physiology.zone_distribution` / `hr_drift` | null / null | null / null |
| `pacing` | `average_pace_min_km`, `average_speed_kmh` (moyennes) | idem |
| `summary` (texte factuel) | « 21.27 km en 2h02 à 5:43/km, FC 160 (max 174) » | « 10.18 km en 1h11 à 6:59/km, FC 127 (max 144) » |
| `evidence.has_cadence` / `has_elevation` | **true / true** | **true / true** |
| **Valeur cadence / dénivelé dans la réponse** | **ABSENTE** (flag booléen seulement) | **ABSENTE** (flag booléen seulement) |
| `km_splits` / `pacing.splits` | absent / absent | absent / absent |
| `limitations` | intensity, splits, baseline_descriptive, comparability, session_nature_unknown | idem |

**RUPTURE CONFIRMÉE** : `evidence.has_cadence=true` et `has_elevation=true` **reconnaissent** la présence des données (cadence 170/152 spm, dénivelé 186,9/37,4 m en base), mais leurs **valeurs ne sont pas transportées** dans la réponse (ni `physiology`, ni `summary`, ni ailleurs — seuls des booléens `has_*`). Donnée factuelle disponible → signalée présente → **non restituée**.

---

## 4. Diagnostic causal

1. **Pourquoi A = « séance longue » ?**
   **CONFIRMÉ.** Aucune phase/intensité fiable → `_session_type_code` retombe sur `_structural_size_code`. A = 21,27 km (≥15) et 122 min (≥90) → `long`. Classification **purement structurelle** (distance/durée).

2. **Pourquoi B = « séance standard » ?**
   **CONFIRMÉ.** B = 10,18 km (<15) et 71 min (<90, >25) → ni `long` ni `short` → `standard`. Même logique structurelle, aucune donnée de phase/split/zone pour l'affiner.

3. **Observations factuelles disponibles mais filtrées ?**
   **CONFIRMÉ, OUI.** La **cadence** (170,3 / 152,4 spm) et le **dénivelé positif** (186,9 / 37,4 m) sont en base et reconnus par `evidence`, mais ne sont **pas exposés** dans la réponse API. Ce sont des faits mesurés, non inventés, actuellement perdus à la restitution.

4. **Splits Garmin présents et correctement transportés ?**
   **CONFIRMÉ : NON présents.** `km_splits` absent en base ; phases typed-splits jamais récupérées (`not_requested`). Il n'y a donc aucun split à transporter. Le chemin de fetch #321 est disponible mais non exécuté pour A/B.

5. **Métriques profondes réellement produites ?**
   **CONFIRMÉ : NON.** `split_analysis`, `pace_stats`, `hr_analysis`, `zone_distribution`, `hr_drift` = absents/null. Non produites faute d'ingestion des détails/séries temporelles.

6. **Que peut-on restituer sans inventer d'intensité physiologique ?**
   Déjà restitué : distance, durée, allure moyenne, vitesse moyenne, FC moyenne, FC max.
   **Restituable immédiatement sans aucun calcul physiologique nouveau** : **cadence moyenne** et **dénivelé positif** (valeurs déjà en base, déjà reconnues par `evidence`). Aucune zone/intensité ne doit être inventée (provenance fiable absente — invariant respecté).

---

## 5. Matrice de provenance

Légende : ✓ présent/transporté · ✗ absent · ⚠ présent en amont mais non transporté.

| Métrique | Mongo | Enrichissement | API | Frontend | Diagnostic |
|---|---|---|---|---|---|
| Distance | ✓ | ✓ | ✓ (`summary`) | ✓ | OK (A & B) |
| Durée | ✓ | ✓ | ✓ | ✓ | OK |
| Allure moyenne | ✓ (dérivée) | ✓ | ✓ (`pacing`) | ✓ | OK |
| Vitesse moyenne | ✓ | ✓ | ✓ | ✓ | OK |
| FC moyenne | ✓ | ✓ | ✓ (`physiology.avg_hr`) | ✓ | OK |
| FC max | ✓ | ✓ | ✓ (`physiology.max_hr`) | ✓ | OK |
| **Cadence moyenne** | ✓ (170 / 152) | ⚠ reconnue (`has_cadence`) | ✗ valeur absente | ✗ | **RUPTURE — non transportée (A & B)** |
| **Dénivelé positif** | ✓ (187 / 37 m) | ⚠ reconnu (`has_elevation`) | ✗ valeur absente | ✗ | **RUPTURE — non transporté (A & B)** |
| km_splits | ✗ | ✗ | ✗ | ✗ | Jamais produit (détails non récupérés) |
| split/pace/hr analysis | ✗ | ✗ | ✗ | ✗ | Non produit |
| Phases structurées | ✗ (`activity_details=None`) | ✗ (`not_requested`) | `phase_analysis.available=false` | ✗ | Enrichissement jamais déclenché pour A/B |
| Zones FC / intensité | ✗ | ✗ | `zone_distribution=null` | indisponible | Correct — aucune intensité inventée |
| hr_drift | ✗ (pas de séries) | ✗ | null | ✗ | Non calculable (séries absentes) |

A et B donnent des résultats identiques sur cette matrice, **sauf** la classification structurelle (`long` vs `standard`) qui dépend uniquement de distance/durée.

---

## 6. Preuves (code + runtime)

- **Classification structurelle** : `workout_analysis_v2.py` → `_structural_size_code()` (seuils `long` ≥90 min / ≥15 km ; `short` ≤25 min / ≤4 km) ; `_session_type_code()` retombe dessus car `_intensity_code()` renvoie None (provenance zones verrouillée + `zone_distribution` null).
- **Runtime** : réponses API HTTP 200 citées au §3 ; `phases` cache `not_requested` au §2 ; cadence/dénivelé en base (`garmin_activity`) au §1 mais absents de la réponse (seuls `has_cadence/has_elevation` booléens présents).

## 7. Limites d'accès

- Enrichissement des phases pour A/B **non déclenché** (contrainte) → contenu typed-splits de A/B non observé (hypothèse §2).
- Aucune série temporelle disponible en base → impossible de vérifier hr_drift / splits reconstruits sans ingestion (hors périmètre).

## 8. Périmètre minimal recommandé pour #330

**P0 — Transport des faits déjà présents (aucun calcul physiologique nouveau)** :
- Exposer **cadence moyenne** (`garmin_activity.average_run_cadence`) et **dénivelé positif** (`garmin_activity.elevation_gain`) comme observations factuelles dans la réponse WA V2 (les flags `evidence.has_cadence/has_elevation` sont déjà à `true`).
- Fichiers probables : `workout_analysis_v2_service.py` (transport) + `workout_analysis_v2.py` (bloc d'observations) + i18n/affichage (`workoutAnalysis.js`, composants workout).
- Risque de régression : faible (ajout additif, pas de changement de classification ni d'intensité).
- Tests : présence des valeurs cadence/dénivelé quand `has_cadence/has_elevation=true` ; absence propre sinon.

**Hors P0 (à décider séparément)** :
- Récupération à la demande des phases pour les courses continues : **valeur faible** (A/B n'ont pas d'intervalles structurés) → ne pas inclure dans #330 sauf besoin explicite.
- Ne pas introduire de zones/intensité sans provenance fiable (invariant).

---

## Verdict

Les classifications **A = « longue »** et **B = « standard »** sont **correctes et déterministes** (heuristique structurelle), faute de données de phase/split/zone pour ces deux activités. Le seul défaut de restitution **confirmé** est la **non-exposition de la cadence et du dénivelé** pourtant présents en base et reconnus par `evidence`. C'est le périmètre minimal, factuel et sans risque physiologique, recommandé pour **#330**.

*(STOP. Lecture seule. Aucune implémentation. En attente de validation.)*
