# RUNINDEX — Audit runtime Garmin → MongoDB → Workout Analysis V2

> Audit **lecture seule**. Aucune donnée modifiée, aucun appel Garmin déclenché, aucun code touché, aucune PR/merge au titre de cet audit.
> Les sections distinguent explicitement **FAIT OBSERVÉ**, **CONCLUSION DÉMONTRÉE** et **HYPOTHÈSE NON CONFIRMÉE**.

---

## 1. Environnement et version du code audités

| Élément | Valeur |
|---|---|
| Dépôt / branche canonique | `geirb56/sauvegarde260708` @ `copilot/dev` |
| HEAD local audité | `2843283` (merge local sur `pr167`, parent canonique inclut PR #318/#319/#320) |
| Base MongoDB | base locale de l'environnement Emergent (preview), pas la production |
| Provider Garmin | `GARMIN_PROVIDER` défini dans `.env` ; binaire `gccli` **absent du PATH du pod au moment de l'audit** |
| Collections détail activité | `garmin_activities` (305 docs), `workouts` (309 docs) — **aucune** collection `garmin_activity`/`raw_payload`/laps dédiée ; `raw_payload` et `garmin_activity` sont des **sous-documents** de `garmin_activities` |

---

## 2. Identification de la séance (sans données personnelles sensibles)

| Attribut | Valeur |
|---|---|
| Nom | `Vannes - 4x4min @allure Z5` |
| Date / heure locale | `2026-10-10 10:10:04` |
| Garmin `external_id` / `activityId` | `24671804067` |
| `workouts.id` | `garmin-24671804067` |
| `workouts.external_id` | `None` (l'id Garmin est encodé dans le champ `id`, pas dans `external_id`) |
| Distance / durée | 14,26 km / 89 min (1h29) |
| FC moyenne / max | 138 / 175 bpm |
| Allure moyenne | 6:14/km (`avg_pace_min_km = 6.232`) |
| `synced_at` | `2026-10-10T10:23:46Z` (source `garmin`) |
| Doublons / versions | **Un seul** doc `garmin_activities` et **un seul** `workouts` pour cet `external_id`. Pas de versions multiples. |

**FAIT OBSERVÉ** : les deux documents (`workouts` et `garmin_activities`) correspondent à la même activité (même nom, même distance, même date, même id Garmin).

---

## 3. Inventaire des données Garmin réellement présentes

### 3.1 `garmin_activities.garmin_activity` (modèle normalisé — 25 champs)

| Champ | État | Valeur / remarque |
|---|---|---|
| `activity_id` | présent | `"24671804067"` |
| `activity_type` | présent | `"running"` |
| `average_hr` / `max_hr` | présent | 138.0 / 175.0 |
| `min_hr` | **None** | absent |
| `average_speed_mps` / `max_speed_mps` | présent | 2.674 / 4.059 |
| `average_run_cadence` / `max_run_cadence` | présent | 165.7 / 183.0 |
| `distance_m` / `duration_s` / `moving_duration_s` | présent | 14263.1 / 5333.5 / 5332.0 |
| `elevation_gain` / `elevation_loss` | présent | 41.6 / 49.4 |
| `calories` / `steps` | présent | 1120 / 14754 |
| `moderate_intensity_minutes` / `vigorous_intensity_minutes` | présent | 51 / 22 |
| **`lap_count`** | **None** | **absent** |
| **`has_splits`** | **None** | **absent** |
| **`has_hr_zones`** | **None** | **absent** |
| **`details_available`** | **None** | **absent** |

### 3.2 `garmin_activities.raw_payload` (7 clés uniquement)

`activityId`, `distance`, `duration`, `averageHR`, `averageSpeed`, `calories`, `elevationGain`.

### 3.3 Données détaillées recherchées (toutes collections)

| Champ attendu | État | Emplacement | Exploitable V2 |
|---|---|---|---|
| `km_splits` | **absent** (pas `[]`, pas `null` : clé inexistante) | — | Non |
| `splits` / `laps` | **absent** | — | Non |
| `split_analysis` / `pace_stats` | **absent** | — | Non |
| `hr_analysis` | **absent** | — | Non |
| `effort_zone_distribution` / `hr_zones` / `time_in_zones` | **absent** | — | Non |
| Séries temporelles vitesse/allure | **absent** | — | Non |
| Séries temporelles FC | **absent** | — | Non |
| Intervalles effort / récupération | **absent** | — | Non |
| Détails FIT / Garmin | **absent** | — | Non |

**CONCLUSION DÉMONTRÉE** : la seule information de granularité « séance » stockée est un **résumé agrégé**. Aucune donnée de lap, split, zone FC ou série temporelle n'existe nulle part en base pour cette activité. La distinction demandée est nette : ces champs ne sont pas `null` ni `[]` — **les clés n'existent tout simplement pas** (jamais écrites).

---

## 4. Audit de l'import Garmin

### 4.1 Chaîne réelle d'import (fichiers / fonctions)

| Étape | Fonction | Fichier:ligne | Comportement |
|---|---|---|---|
| Récupération activités | `GccliRunner.fetch_activities()` | `garmin/runner.py:229` | invoque **uniquement** `gccli activities list --limit N -j` (`runner.py:232`) |
| Sync | `GccliProvider.sync_activities()` / `fetch_all_activities()` | `garmin/providers/gccli_provider.py:95 / 109` | pagine l'endpoint **liste** ; aucune récupération de détails |
| Normalisation | `GccliProvider._normalize()` | `gccli_provider.py:219` | délègue à `GarminActivity.from_summary()` |
| Modèle | `GarminActivity.from_summary()` | `garmin/data_layer.py:128` | parse résumé + `metadataDTO` (lapCount/hasSplits/hasHrTimeInZones) **si présents** |
| Persistance | sous-docs `garmin_activity` + `raw_payload` | `gccli_provider.py:243-271` | `raw_payload` **figé à 7 clés codées en dur** (`:243`) ; `garmin_activity = normalized.model_dump()` (`:270`) |

### 4.2 Détails jamais demandés

**FAIT OBSERVÉ** : la seule sous-commande activité appelée est `["activities", "list", "--limit", str(limit)]` (`runner.py:232`). Il n'existe **aucune** fonction appelant un endpoint de détail d'activité (`activities get <id>`, laps, splits, typed-splits, time-series, time-in-zones) dans tout `garmin/`.

**CONCLUSION DÉMONTRÉE** : les détails ne sont **jamais demandés** par RunIndex. Ils ne sont donc ni perdus à la normalisation, ni stockés ailleurs — ils ne sont jamais récupérés.

**CONCLUSION DÉMONTRÉE (secondaire)** : même si l'endpoint liste exposait `metadataDTO.hasSplits`/`lapCount`, le flat item de la liste ici ne les contenait pas (`lap_count=None`, `has_splits=None`). Le modèle `GarminActivity` **ne possède de toute façon aucun champ** pour héberger laps/splits/séries/zones (`data_layer.py:103-125`).

**HYPOTHÈSE NON CONFIRMÉE** : savoir si le binaire `gccli` expose une commande de détail (laps/splits/zones) et si Garmin fournit ces données pour cette activité. Le binaire `gccli` étant absent du PATH du pod, je **ne peux pas** vérifier ses sous-commandes, et je n'ai pas déclenché d'appel Garmin (contrainte). À vérifier avant toute conclusion sur la disponibilité côté source.

---

## 5. Audit de l'enrichissement Workout Analysis V2

Fichier : `backend/workout_analysis_v2_service.py`, fonction `enrich_workout_from_garmin_activity()` (`:119`).

- La fonction fusionne les candidats : `candidates = {**raw_payload, **garmin_activity, **activity_doc}` (`:128`).
- Elle enrichit correctement **HR, vitesse, cadence, élévation** (présents dans le résumé).
- Pour les splits (`:179`) : `if enriched.get("km_splits") is None:` puis cherche `km_splits`/`splits` dans `candidates`. **Aucune de ces clés n'existe** → `km_splits` reste absent.
- Pour les zones (`:171`) : cherche `effort_zone_distribution`/`hr_zones`/`time_in_zones` → **absentes** → reste absent.
- Pour `split_analysis`/`hr_analysis`/`pace_stats` (`:187`) → **absentes** → rien.

### Réponse à l'hypothèse explicite sur `km_splits is None`

**CONCLUSION DÉMONTRÉE** : la ligne `if enriched.get("km_splits") is None:` (`:179`) n'est **pas** le point de blocage dans ce cas. Un `km_splits = []` (liste vide) empêcherait effectivement le ré-enrichissement (car `[] is not None`), mais ici le workout n'a aucune clé `km_splits` **et** la source `garmin_activities` ne contient aucun split exploitable. Le défaut est en amont (§4), pas dans la logique `is None`.
> Nuance défensive à retenir pour une future correction : si une étape antérieure écrivait `km_splits=[]`, elle masquerait des splits réellement disponibles. À durcir si l'on ajoute une source de splits.

### Remarques structure / unités
- Unités cohérentes dans le résumé (m, s, mps, bpm, spm). Pas de perte d'unité observée sur les champs présents.
- Provenance zones FC : **inexistante** (jamais importée).
- Champs détaillés ignorés : tous (laps/splits/séries/zones) — car absents en source.

---

## 6. Audit de la classification de séance

Fichier : `backend/workout_analysis_v2.py`.

| Fonction | Ligne | Comportement démontré |
|---|---|---|
| `_has_trusted_zone_provenance()` | `:837` | **`return False` codé en dur** — aucune provenance de zone n'est jamais considérée comme fiable |
| `_intensity_code()` | `:841` | garde `if not physiology.zone_distribution or not _has_trusted_zone_provenance(...)` → renvoie **toujours `None`** (double verrou : pas de zones **et** provenance False) |
| `_structural_size_code()` | `:856` | pour `type == "run"` : `long` si durée≥90 **ou** dist≥15 ; `short` si durée≤25 **ou** dist≤4 ; sinon **`standard`** |
| `_session_type_code()` | `:892` | si intensité ∈ {high, very_high}→`hard`, `low`→`easy`, **sinon `_structural_size_code()`** |

### Pourquoi « Séance standard »

**CONCLUSION DÉMONTRÉE** :
1. `zone_distribution = None` **et** `_has_trusted_zone_provenance = False` → `intensity_code = None` → intensité **indisponible** (confirmé API : `reason_unavailable = "classification d'intensité indisponible sans preuve physiologique individualisée"`).
2. Intensité étant `None`, `_session_type_code` retombe sur `_structural_size_code`.
3. Séance = `type="run"`, 89 min (< 90) et 14,26 km (< 15) → ni `long` ni `short` → **`standard`**.

Le moteur ne dispose d'**aucune** information fiable sur : séance planifiée, intervalles réalisés, périodes d'effort, récupérations, temps par intensité. La chaîne est purement heuristique durée/distance.

**Distinction intention / exécution / interprétation** :
- **Intention** (prévu) : « 4×4 min @ Z5 » — connue uniquement via le **titre** (texte libre), jamais via des données structurées.
- **Exécution observée** : seules preuves = résumé agrégé (dist, durée, FC moy/max, cadence). **Aucune preuve** des 4 répétitions.
- **Interprétation physiologique** : impossible à établir ; le moteur refuse — correctement — de conclure. Les 4 répétitions **ne doivent pas** être déduites du titre.

---

## 7. Audit des comparaisons historiques

Fichier : `backend/workout_analysis_v2.py`, `retrieve_similar_workouts()` (`:601`).

Critères de sélection (`:629-652`) : même `type` (minuscule), date strictement antérieure dans la fenêtre, distance dans une tolérance `±SIMILAR_DISTANCE_TOLERANCE_PCT`, cohérence d'un `_competition_flag`. Tri par date, `limit` résultats.

**CONCLUSION DÉMONTRÉE** : l'appariement est **distance + type générique**. Il ne distingue **pas** footing continu / fractionné / tempo-seuil / sortie longue. Un fractionné de 14 km est donc comparé à des footings de ~14 km.

**FAIT OBSERVÉ (API)** : le moteur **expose lui-même** cette limite : `comparison.similar = { available: true, comparable: false, sample_count: 5, limitations: ["session_nature_unknown"] }`. La comparaison est donc **descriptive**, pas sportivement comparable — et le moteur le signale.

---

## 8. Diagnostic API runtime

Appel lecture seule effectué : `GET /api/coach/workout-analysis/garmin-24671804067?language=fr` (HTTP 200), compte propriétaire `da8505ef…` (le seul porteur des activités Garmin et snapshots réels).

| Information | Garmin stocké | Workout stocké | API V2 | Interface |
|---|---|---|---|---|
| Distance | 14263 m | 14.26 km | 14,26 km | 14,26 km |
| FC (moy/max) | 138 / 175 | 138 / (max absent) | 138 / 175 | affichée |
| Laps | **absent** | **absent** | `has_splits=false` | — |
| Splits | **absent** | **absent** | `km_splits` absent, pacing splits `null` | « non disponible » |
| Séries temporelles | **absent** | **absent** | absent | — |
| Type de séance | `running` | `run` | `standard` | « Séance standard » |
| Zones FC | **absent** | **absent** | `zone_distribution=null`, `has_hr_zones=false` | « indisponible » |
| Intervalles | **absent** | **absent** | intensité `available=false` | « indisponible » |

`evidence` renvoyé par l'API : `has_heart_rate=true`, `has_cadence=true`, `has_elevation=true`, `has_baseline=true`, **`has_hr_zones=false`**, **`has_splits=false`**.

**Premier maillon où l'information exploitable disparaît** :
> **CONCLUSION DÉMONTRÉE** — Les laps/splits/séries/zones **n'entrent jamais dans le système** : l'import n'appelle que `gccli activities list` (§4). Le maillon rompu est l'**ingestion Garmin** (récupération des détails), en amont de MongoDB, de l'enrichissement et du moteur. Tous les maillons aval (enrichissement, classification, API, UI) se comportent correctement vu l'absence de données, et signalent honnêtement les indisponibilités.

---

## 9. Défauts confirmés (avec preuves)

| # | Défaut | Preuve | Gravité |
|---|---|---|---|
| D1 | Détails d'activité (laps/splits/zones/séries) **jamais récupérés** | `runner.py:232` n'appelle que `activities list` ; aucune fonction détail dans `garmin/` | **Bloquant** |
| D2 | Modèle `GarminActivity` **sans champs** pour laps/splits/séries/zones | `data_layer.py:103-125` | Structurel |
| D3 | `raw_payload` **figé à 7 clés** codées en dur | `gccli_provider.py:243-251` | Structurel |
| D4 | `_has_trusted_zone_provenance` **toujours `False`** → intensité jamais calculable même avec zones | `workout_analysis_v2.py:837-838` | Capacité verrouillée |
| D5 | Comparaison historique **par distance/type générique**, ne distingue pas la nature de séance | `workout_analysis_v2.py:601-652` ; API `comparable=false / session_nature_unknown` | Fonctionnel (déjà signalé par le moteur) |

---

## 10. Hypothèses non confirmées

- **H1** : Garmin/`gccli` exposent-ils réellement laps/splits/zones/séries pour cette activité ? Non vérifié (`gccli` absent du PATH ; aucun appel Garmin déclenché). À confirmer avant toute implémentation d'ingestion détaillée.
- **H2** : la version de `gccli` en production supporte-t-elle une commande de détail ? Inconnu.
- **H3** : le titre « 4×4 min » correspond-il à un plan structuré téléchargé sur la montre (workout structuré Garmin) récupérable via un endpoint dédié ? Inconnu.

---

## 11. Capacités actuellement absentes du moteur

1. Ingestion des **laps / splits kilométriques** Garmin.
2. Ingestion des **séries temporelles** (allure, FC) et détection d'**intervalles effort/récupération**.
3. Ingestion des **zones FC / time-in-zones** avec **provenance fiable** (verrou `_has_trusted_zone_provenance`).
4. Reconnaissance d'une **séance structurée** (fractionné) vs continue, indépendamment du titre.
5. Comparaison historique **par nature de séance** (fractionné vs footing vs tempo vs long).

---

## 12. Risques techniques

- **R1** : ajouter l'ingestion détaillée augmente le volume des appels `gccli`/Garmin (coût, rate-limit, latence de sync). Prévoir pagination/backfill borné.
- **R2** : les détails peuvent être **absents pour d'anciennes activités** → nécessité d'un backfill et d'une gestion gracieuse (champ présent mais vide ≠ non récupéré).
- **R3** : provenance des zones — risque physiologique si l'on active l'intensité sans zones individualisées fiables (contredirait l'invariant « pas d'intensité sans preuve »). Toute levée de D4 doit rester subordonnée à une provenance vérifiée.
- **R4** : ne pas confondre **intention (titre)** et **exécution** — risque de régression « 4 répétitions déduites du titre ». À interdire par test.

---

## 13. Corrections envisageables — par priorité (découpage minimal en PR indépendantes)

> Diagnostic uniquement. Aucune implémentation entreprise.

### PR-A (P0) — Ingestion des détails d'activité Garmin (laps + splits)
- **Problème démontré** : détails jamais récupérés (D1).
- **Cause racine** : `fetch_activities` n'appelle que `activities list` (`runner.py:232`).
- **Fichiers** : `garmin/runner.py`, `garmin/providers/gccli_provider.py`, `garmin/data_layer.py` (nouveaux champs modèle), `garmin/service.py`/sync worker (persistance).
- **Impact attendu** : `km_splits`, `laps`, `lap_count`, `has_splits` réellement stockés.
- **Régression** : moyenne (volume d'appels, schéma). Mitiger par flag + backfill borné.
- **Tests** : parsing d'un payload détail Garmin → `km_splits`/`laps` ; idempotence sync ; activité sans détail → champs vides non bloquants.
- **Récup. données supplémentaires** : **OUI** (nouvel appel détail Garmin + backfill). Nécessite autorisation explicite + vérification H1/H2.

### PR-B (P1) — Détection d'intervalles à partir des laps/séries
- **Problème** : pas d'analyse des répétitions même si laps disponibles (capacité absente §11.4).
- **Cause racine** : aucune logique de segmentation effort/récupération.
- **Fichiers** : `workout_analysis_v2_service.py` (mapping laps→segments), `workout_analysis_v2.py` (`_session_type_code` enrichi d'un code `interval`/`structured`).
- **Impact** : séance « 4×4 min » reconnue comme structurée **sur preuve** (exécution), titre non utilisé comme preuve.
- **Régression** : moyenne. Dépend de PR-A.
- **Tests** : laps synthétiques 4×(≈4 min rapide + récup) → classification `interval` ; absence de laps → reste `standard` ; titre seul → **jamais** `interval`.

### PR-C (P1) — Zones FC avec provenance fiable
- **Problème** : intensité jamais calculable (D4).
- **Cause racine** : `_has_trusted_zone_provenance` renvoie `False` en dur (`workout_analysis_v2.py:837`).
- **Fichiers** : `workout_analysis_v2.py` (provenance réelle basée sur zones individualisées importées), ingestion zones (dépend PR-A).
- **Impact** : intensité physiologique disponible **uniquement** avec zones individualisées vérifiées.
- **Régression** : **élevée** (invariant physiologique). Ne lever le verrou que si provenance prouvée.
- **Tests** : zones fiables → intensité ; zones absentes/non fiables → reste indisponible.
- **Récup. données supplémentaires** : OUI (time-in-zones Garmin).

### PR-D (P2) — Comparaisons par nature de séance
- **Problème** : comparaison distance-only (D5), déjà signalée `session_nature_unknown`.
- **Cause racine** : `retrieve_similar_workouts` filtre type générique + distance (`:629-652`).
- **Fichiers** : `workout_analysis_v2.py`.
- **Impact** : comparer fractionné à fractionné, footing à footing.
- **Régression** : faible/moyenne (dépend d'une classification fiable → après PR-B).
- **Tests** : un fractionné n'est comparé qu'à des séances de même nature ; sinon `comparable=false` maintenu.

**Ordre recommandé** : PR-A → (PR-B, PR-C en parallèle) → PR-D. PR-B/C/D sont inexploitables sans les données de PR-A.

---

## Réponses aux 4 questions

1. **Garmin a-t-il fourni à RunIndex les données des 4 intervalles ?**
   Non côté RunIndex : l'application **ne les a jamais demandées** (seul `activities list` est appelé). Qu'elles soient disponibles côté Garmin/`gccli` reste une **hypothèse à confirmer** (H1/H2) — binaire absent, aucun appel déclenché.

2. **Si oui, où sont-elles perdues / ignorées ?**
   En amont de tout : au stade de l'**ingestion** (`garmin/runner.py:232`). Elles ne sont ni stockées ailleurs ni perdues à la normalisation — elles n'entrent jamais. Le modèle (`data_layer.py`) n'a d'ailleurs aucun champ pour les accueillir.

3. **Pourquoi « Séance standard » sans analyse des répétitions ?**
   Parce que l'intensité est verrouillée (`_has_trusted_zone_provenance → False` + `zone_distribution=None`) et que `_session_type_code` retombe sur `_structural_size_code`, qui classe 89 min / 14,26 km (`type=run`, ni ≥90 min ni ≥15 km) en **standard**. Aucune donnée de lap/split/zone n'existe → aucune preuve d'intervalles. Le moteur refuse — correctement — d'inférer les répétitions depuis le titre.

4. **Corrections minimales pour une vraie analyse de séance structurée ?**
   **PR-A** (ingérer laps/splits Garmin) est le prérequis bloquant. Puis **PR-B** (détection d'intervalles sur preuve), **PR-C** (zones FC à provenance fiable pour l'intensité) et **PR-D** (comparaisons par nature). PR-A exige la récupération de données Garmin supplémentaires et donc une autorisation explicite.
