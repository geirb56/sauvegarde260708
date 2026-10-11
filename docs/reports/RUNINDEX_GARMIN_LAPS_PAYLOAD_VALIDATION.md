# RUNINDEX — P331 : Validation du payload Garmin `activity splits` (lapDTOs)

&gt; Audit **lecture seule**. Un seul appel GCCLI `activity splits`. Aucune écriture Mongo, aucun POST API, aucun worker, aucun réimport/backfill, aucun changement de code, aucune PR/commit. Caches `activity_details` non modifiés. Training V2 / Coach / WA V2 inchangés. Drift local `activity_day` préservé. Aucun secret ni GPS exposé. Fichiers temporaires supprimés après analyse.

---

## 1. Précontrôles et commande exécutée

| Contrôle | Résultat |
|---|---|
| Propriété activité A `24346252881` | `user_id=da8505ef…`, `source=garmin`, `external_id` **str** |
| Session Garmin (propriétaire) | authentifiée, non expirée (exp. 2026-10-12T08:23Z) |
| Tâche concurrente (queue/deferred/processing) | **0 / 0 / 0** — aucune |
| Payload brut déjà capturé réutilisable | **non** (temp du test #321 supprimé, rien persisté en Mongo) |

→ Précontrôles satisfaits, **un seul** appel de lecture exécuté :

`gccli activity splits 24346252881 -j     (HOME = home session du propriétaire, keyring file)`

Résultat : exit 0, 22 348 octets JSON, aucune erreur.

## 2. Schéma réel de l'enveloppe

Structure illustrative :

`{ "activityId": 24346252881, "lapDTOs": [22 objets], "eventDTOs": [3 objets] }`

| Élément | Type | Remarque |
|---|---|---|
| `activityId` | **int** | provenance = identifiant Garmin numérique (Mongo `external_id` est **str** → normalisation int↔str requise) |
| `lapDTOs` | `list` | **présent, non vide** (22 éléments) |
| `eventDTOs` | `list` | 3 éléments (hors périmètre laps) |

**Cas `lapDTOs` vide/nul/absent** : non observé sur cet échantillon (continue, 22 laps). À traiter défensivement en #331 (clé absente, liste vide, `null`) — comportement non vérifiable ici.

## 3. Inventaire des champs `lapDTOs` (union des 22 laps — tous présents, aucun null)

| Champ | Type JSON | Unité | Statut échantillon | Notes |
|---|---|---|---|---|
| `lapIndex` | int | — | obligatoire | 1…22, séquentiel, sans doublon |
| `messageIndex` | int | — | obligatoire | 0…21, ordre d'émission |
| `startTimeGMT` | str | ISO-8601 UTC | obligatoire | monotone croissant |
| `distance` | float | **mètres** (confirmé §4) | obligatoire | |
| `duration` | float | **secondes** (confirmé §4) | obligatoire | |
| `movingDuration` | float | secondes | obligatoire | |
| `elapsedDuration` | float | secondes | obligatoire | |
| `averageSpeed` | float | **m/s** (confirmé §4) | obligatoire | |
| `averageMovingSpeed` | float | m/s (inféré) | obligatoire | |
| `maxSpeed` | float | m/s (inféré) | obligatoire | |
| `averageHR` | float | bpm | obligatoire | |
| `maxHR` | float | bpm | obligatoire | |
| `averageRunCadence` | float | spm (inféré) | obligatoire | ~168 → cadence course |
| `maxRunCadence` | float | spm (inféré) | obligatoire | |
| `elevationGain` | float | mètres (inféré) | obligatoire | |
| `elevationLoss` | float | mètres (inféré) | obligatoire | |
| `maxElevation` / `minElevation` | float | mètres (inféré) | obligatoire | |
| `strideLength` | float | **cm (inféré)** | obligatoire | ~104 → cm plausible, unité non explicite |
| `maxVerticalSpeed` | float | m/s (inféré) | obligatoire | |
| `calories` / `bmrCalories` | float | kcal (inféré) | obligatoire | |
| `intensityType` | **str** | — | obligatoire | **"ACTIVE" pour les 22** — type d'effort, **pas** un mode de déclenchement |
| `startLatitude`/`Longitude`, `endLatitude`/`Longitude` | float | degrés | obligatoire | **GPS — exclus** du rapport/fixture |
| `connectIQMeasurement` | list | — | obligatoire (vide) | hors périmètre |
| `lengthDTOs` | list | — | obligatoire (vide) | hors périmètre |

**Champs absents** (à ne pas inventer) : `minHR`, et surtout **aucun champ de mode de déclenchement** (`lapTrigger`/`manual`/`auto`).

Extrait JSON anonymisé (lap complet + lap partiel) : voir `backend/tests/fixtures/garmin_laps_fixture.json`.

## 4. Contrôles de cohérence (22 laps)

| Contrôle | Résultat |
|---|---|
| Σ distance | **21 274,5 m** vs résumé A **21 270 m** → Δ ≈ 4,5 m (0,02 %) ✅ |
| Σ durée | **7 290,5 s = 121,5 min** vs résumé A ~122 min ✅ |
| Laps complets (~1000 m) | **21** |
| Lap partiel | **1** (274,53 m — dernier, `lapIndex=22`) |
| Ordre `lapIndex` | 1→22 strictement séquentiel |
| Ordre `messageIndex` | 0→21 strictement séquentiel |
| Doublons | **aucun** |
| `startTimeGMT` | monotone croissant ✅ |
| Valeurs manquantes/nulles/incohérentes | **aucune** sur l'échantillon |
| Cohérence allure↔distance/durée | ex. lap1 : 1000 m / 341,128 s → 2,931 m/s = `averageSpeed` ✅ (confirme unités m, s, m/s) |
| **Mode de déclenchement** | **non fourni** (pas de champ natif). La régularité ~1000 m est **compatible** avec un découpage auto par distance, **mais non prouvée** → ne pas qualifier « auto » ni « manuel ». |

## 5. Mapping source → contrat normalisé proposé (#331)

&gt; Valeurs absentes conservées à `null`. **Ne pas** convertir automatiquement en `km_splits`. **Ne pas** toucher `typed-splits`/`activity_details`.

| Champ normalisé (cible) | Source `lapDTOs` | Unité cible | Base |
|---|---|---|---|
| `lap_index` | `lapIndex` | — | **champ confirmé** |
| `order` | `messageIndex` | — | **champ confirmé** |
| `start_time_gmt` | `startTimeGMT` | ISO UTC | **champ confirmé** |
| `distance_m` | `distance` | mètres | **unité confirmée** (Σ = résumé) |
| `duration_s` | `duration` | secondes | **unité confirmée** (Σ = résumé) |
| `moving_duration_s` | `movingDuration` | secondes | champ confirmé, unité inférée |
| `elapsed_duration_s` | `elapsedDuration` | secondes | champ confirmé, unité inférée |
| `average_speed_mps` | `averageSpeed` | m/s | **unité confirmée** (cohérence dist/durée) |
| `average_moving_speed_mps` | `averageMovingSpeed` | m/s | unité inférée |
| `max_speed_mps` | `maxSpeed` | m/s | unité inférée |
| `average_hr` | `averageHR` | bpm | champ confirmé |
| `max_hr` | `maxHR` | bpm | champ confirmé |
| `min_hr` | *(absent)* | bpm | **null** (non fourni) |
| `average_cadence_spm` | `averageRunCadence` | spm | unité inférée |
| `max_cadence_spm` | `maxRunCadence` | spm | unité inférée |
| `elevation_gain_m` | `elevationGain` | mètres | unité inférée |
| `elevation_loss_m` | `elevationLoss` | mètres | unité inférée |
| `max_elevation_m` / `min_elevation_m` | `maxElevation`/`minElevation` | mètres | unité inférée |
| `stride_length` | `strideLength` | **cm (inféré, à confirmer)** | champ confirmé, unité **inconnue** |
| `calories` | `calories` | kcal (inféré) | champ confirmé |
| `intensity_type` | `intensityType` | — (str) | **champ confirmé** — sémantique = type d'effort, **pas** déclenchement |
| `trigger_mode` | *(absent)* | — | **inconnu** — ne pas dériver du titre ni de la distance |

Catégories :

- **Champs confirmés par le payload** : tous ceux listés (présents sur les 22 laps).
- **Unités confirmées par source explicite/cohérence numérique** : distance (m), durée (s), vitesse (m/s).
- **Unités inférées par cohérence** : cadence (spm), dénivelé (m), calories (kcal), vitesses verticales (m/s).
- **Inconnues** : unité `strideLength` (cm supposé), mode de déclenchement (absent), comportement quand `lapDTOs` est vide/null.

## 6. Inconnues et limites de généralisation

- Échantillon = **1 activité continue**. Non vérifié : séances où `lapDTOs` est vide/absent, laps manuels, laps avec champs manquants/nuls, activités multisport, unités sur d'autres profils.
- `intensityType` = "ACTIVE" uniquement ici ; d'autres valeurs (ex. `REST`) possibles sur d'autres activités — non observées.
- Mode de déclenchement (auto/manuel) **non exposé** par `activity splits` ; ne pas l'inventer.
- `strideLength` : unité non explicite (cm très probable).

## 7. Risques techniques pour #331

1. **Identifiant** : `activityId` int vs Mongo `external_id` str (+ `workouts.id` préfixé `garmin-`) → normalisation obligatoire à la jointure/persistance.
2. **`lapDTOs` vide/null** non observé → prévoir gestion défensive (≠ erreur).
3. **GPS / connectIQ / lengthDTOs** volumineux et personnels → exclure de la persistance (ou tronquer).
4. **Ne pas confondre** laps et `km_splits` (#332) ni avec `typed-splits`/`activity_details` (ne pas écraser le cache existant).
5. **Trigger mode absent** : toute logique « auto/manuel » est hors-contrat → interdite sans indicateur natif.
6. **Unité `strideLength`** à confirmer avant exposition.

---

## Verdict : **GO** pour l'implémentation du normaliseur #331

Le contrat `lapDTOs` est **vérifié sur un payload réel**, **cohérent** avec le résumé Garmin (distance/durée à 0,02 %), complet et sans valeurs manquantes sur l'échantillon. Les champs clés (index, ordre, distance, durée, allure, FC, cadence, dénivelé, heure de début) sont confirmés avec unités fiables.

**GO conditionné** au respect des limites : gérer `lapDTOs` vide/null défensivement, normaliser l'identifiant int↔str, exclure GPS/connectIQ/lengthDTOs, conserver `null` pour les champs absents (`min_hr`, `trigger_mode`), **ne pas** dériver de mode de déclenchement, **ne pas** auto-convertir en `km_splits`, **ne pas** toucher `typed-splits`/`activity_details`. La valeur « auto/manuel » et l'unité `strideLength` restent à lever sur d'autres échantillons.

*(STOP. Lecture seule. Aucune implémentation. En attente de validation explicite avant #331.)*
