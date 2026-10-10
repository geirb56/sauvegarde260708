# RUNINDEX — Audit runtime du contrat GCCLI pour la PR #321

> Audit **lecture seule** (Emergent). Aucun changement de code, aucune écriture MongoDB, aucune synchronisation Garmin, aucune PR, aucun merge, aucun déploiement.
> Aucun credential/cookie/token affiché. Coordonnées GPS exclues du rapport.

---

## 1. Version GCCLI

```
gccli 1.9.0 (0893b24) built 2026-06-15T09:38:05Z
```
Binaire réel : `/app/backend/bin/gccli` (environnement worker Emergent).

## 2. Commande exécutée / preuve réutilisée

- Preuve antérieure réutilisée : `/app/RUNINDEX_GCCLI_ACTIVITY_DETAILS_PROBE.md` (29 phases, 4×240 s + 4×180 s).
- **Un seul** appel runtime ciblé complémentaire effectué pour fixer les **types exacts**, les **unités**, la **chronologie** et la représentation de la FC min :
```
gccli activity typed-splits 24671804067 -j
```
Authentification : session existante de l'utilisateur propriétaire (`da8505ef…`), home isolé, keyring `file`. Succès (exit 0, 29 809 octets, aucun retry). Aucun compte global utilisé.

## 3. Structure JSON réelle

**Racine** = objet (pas une liste directe, pas d'enveloppe `splitDTOs`) :

```json
{
  "activityId": 24671804067,                // int
  "activityUUID": { "uuid": "<uuid>" },      // objet { uuid: str }
  "splits": [ /* 29 objets */ ]              // clé réelle = "splits"
}
```

**Objet split** — champ de type = **`type`** (pas `splitType`). Exemple représentatif d'un effort (anonymisé, GPS retiré) :

```json
{
  "type": "INTERVAL_ACTIVE",       // str
  "duration": 240.0,               // float — SECONDES
  "elapsedDuration": 240.0,        // float — secondes
  "movingDuration": 233.0,         // float — secondes (nullable)
  "distance": 832.07,              // float — MÈTRES
  "averageSpeed": 3.467,           // float — m/s
  "averageMovingSpeed": 3.571,     // float — m/s (nullable)
  "maxSpeed": 3.658,               // float — m/s
  "averageHR": 151.0,              // float — bpm
  "maxHR": 160.0,                  // float — bpm
  "averageRunCadence": 175.4,      // float
  "maxRunCadence": 180.0,          // float
  "strideLength": 118.57,          // float — cm
  "elevationGain": 10.0,           // float — m
  "elevationLoss": 15.0,           // float — m
  "calories": 61.0,                // float
  "bmrCalories": 6.0,              // float
  "startTimeGMT": "2026-10-10T08:30:05.0",   // str ISO (UTC)
  "endTimeGMT":   "2026-10-10T08:34:03.0",   // str ISO (UTC)
  "startTimeLocal":"2026-10-10T10:30:05.0",  // str ISO (local)
  "messageIndex": 2,               // int — ordre de phase
  "lapIndexes": [5],               // list[int] — nullable/absent (présent sur 10/29 phases)
  "totalExerciseReps": 0           // int
  // startLatitude/Longitude, endLatitude/Longitude : float (GPS, exclus ici)
}
```

**Types de phase réellement présents** (champ `type`) :
`INTERVAL_WARMUP` (×1), `INTERVAL_ACTIVE` (×4), `INTERVAL_RECOVERY` (×4), `INTERVAL_COOLDOWN` (×1), `RWD_RUN` (×10), `RWD_WALK` (×9).
→ Les phases structurées sont préfixées **`INTERVAL_`**. Les `RWD_*` sont les segments auto Run/Walk Detection de Garmin, superposés.

**FC min** : **aucun champ `minHR`/`minHeartRate`** dans la réponse (ni racine ni split).

**Chronologie** : chaque phase est rattachable via `messageIndex` (ordre), `startTimeGMT`/`endTimeGMT` (bornes absolues UTC) et `startTimeLocal`. `lapIndexes` relie aux laps bruts mais est **souvent absent/null** (19/29).

**Null / absents observés** : `lapIndexes` (19), et `movingDuration`/`averageMovingSpeed`/`avgElapsedDurationVerticalSpeed`/`endLatitude`/`endLongitude` (1 phase chacun — la phase finale tronquée).

## 4. Tableau de correspondance avec le parseur #321

| Hypothèse PR #321 | Réalité runtime | Verdict |
|---|---|---|
| Enveloppe `splitDTOs` **ou** liste directe | Racine = objet `{activityId, activityUUID, splits}` ; clé = **`splits`** | **INCORRECT** |
| Champ `splitType` | Champ réel = **`type`** | **INCORRECT** |
| `duration` en secondes | `duration` float, **secondes** | **CONFIRMÉ** |
| `distance` en mètres | `distance` float, **mètres** | **CONFIRMÉ** |
| `averageSpeed` en m/s | `averageSpeed` float, **m/s** | **CONFIRMÉ** |
| `averageHR` | `averageHR` float (bpm) | **CONFIRMÉ** |
| `maxHR` | `maxHR` float (bpm) | **CONFIRMÉ** |
| `minHR` | **absent** de la réponse | **INCORRECT** |
| Type `INTERVAL_ACTIVE` | présent tel quel | **CONFIRMÉ** |
| Type `INTERVAL_RECOVERY` | présent tel quel | **CONFIRMÉ** |
| Type `WARMUP` | réel = **`INTERVAL_WARMUP`** | **INCORRECT** |
| Type `COOLDOWN` | réel = **`INTERVAL_COOLDOWN`** | **INCORRECT** |
| (non prévu) segments `RWD_RUN`/`RWD_WALK` | présents (19/29 phases) | **À GÉRER** (filtrer) |

## 5. Unités vérifiées

| Champ | Unité confirmée |
|---|---|
| `duration` / `elapsedDuration` / `movingDuration` | secondes (float) |
| `distance` | mètres (float) |
| `averageSpeed` / `maxSpeed` / `averageMovingSpeed` | mètres/seconde (float) |
| `averageHR` / `maxHR` | bpm (float) |
| `strideLength` | centimètres (float) |
| `elevationGain` / `elevationLoss` | mètres (float) |
| `startTimeGMT` / `endTimeGMT` | ISO-8601 UTC (str) |

> Allure non fournie directement : à dériver de `averageSpeed` (`pace_min_km = 1000 / (averageSpeed × 60)`).

## 6. Résultats MongoDB (lecture seule)

Document `garmin_activities` de l'activité `24671804067` (utilisateur `da8505ef…`) :

| Champ | Valeur / type |
|---|---|
| `user_id` | `str` (`da8505ef…`) |
| `source` | `"garmin"` |
| **`external_id`** | **type BSON `str`** = `"24671804067"` |
| `garmin_activity.activity_id` | `str` = `"24671804067"` |
| Détails structurés persistés | **Aucun** (`lap_count=None`, `has_splits=None` ; pas de `km_splits`/`splits`/`laps`/`typed_splits`) |

Variantes historiques : sur les 164 activités de l'utilisateur, `external_id` est **toujours `str`** (distribution `{str: 164}`) — **aucune variante entière**.

Document `workouts` lié :

| Champ | Valeur |
|---|---|
| `id` | `"garmin-24671804067"` (str, **préfixé `garmin-`**) |
| `external_id` | `None` |
| `type` | `"run"` |

→ 164 workouts portent un `id` préfixé `garmin-`.

## 7. Incompatibilités exactes

1. **Racine JSON** : le parseur attend `splitDTOs`/liste directe ; la réalité est `splits` sous un objet racine.
2. **Clé de type** : `splitType` → doit être `type`.
3. **FC min** : `minHR` n'existe pas → tout champ dérivé doit être optionnel/null.
4. **Libellés warmup/cooldown** : `WARMUP`/`COOLDOWN` → réels `INTERVAL_WARMUP`/`INTERVAL_COOLDOWN`.
5. **Segments parasites** : `RWD_RUN`/`RWD_WALK` doivent être filtrés pour ne garder que les phases `INTERVAL_*` (sinon faux comptage d'efforts).
6. **Jointure d'identifiant (critique)** : GCCLI `activityId` est **int** ; MongoDB `external_id` est **str** et `workouts.id` est `"garmin-<id>"`. Le linker doit **normaliser int↔str** et **retirer le préfixe `garmin-`** pour relier correctement.
7. **`lapIndexes` nullable** (absent 19/29) : ne pas en dépendre pour l'ordre → utiliser `messageIndex` / `startTimeGMT`.

## 8. Corrections minimales à demander à GitHub (PR #321)

- Lire la racine `splits` sous l'objet `{activityId, activityUUID, splits}` (pas `splitDTOs`, pas liste directe).
- Utiliser le champ **`type`** (pas `splitType`).
- Reconnaître les libellés **`INTERVAL_WARMUP` / `INTERVAL_ACTIVE` / `INTERVAL_RECOVERY` / `INTERVAL_COOLDOWN`**.
- **Filtrer** les phases `RWD_RUN` / `RWD_WALK` (ne conserver que `INTERVAL_*`).
- Rendre **`minHR` optionnel** (absent) ; garder `averageHR`/`maxHR`.
- Dériver l'allure depuis `averageSpeed` (m/s) ; traiter `duration`/`distance` comme secondes/mètres.
- **Normaliser l'identifiant** : convertir `activityId` (int) ↔ `external_id` (str) et gérer le préfixe `garmin-` de `workouts.id` lors de la jointure/persistance.
- Utiliser `messageIndex` (+ `startTimeGMT`) pour l'ordre ; ne pas dépendre de `lapIndexes` (nullable).
- Gérer les champs nullables de la dernière phase (`movingDuration`, `averageMovingSpeed`, `endLat/Long`).

## 9. Verdict

**CORRECTIONS REQUISES.**

Les unités et la majorité des champs numériques sont **confirmés** (duration/distance/averageSpeed/averageHR/maxHR). Mais le parseur #321, tel que décrit, est **incompatible en l'état** sur 5 points structurants (enveloppe, `splitType` vs `type`, `minHR` inexistant, libellés `WARMUP/COOLDOWN`, segments `RWD_*` non filtrés) et 1 point critique de jointure (int `activityId` vs str `external_id` + préfixe `garmin-`). Ces corrections sont simples, ciblées et sans ambiguïté — la donnée source est pleinement exploitable une fois le contrat aligné.

*(Aucune correction appliquée dans Emergent. Aucune PR créée. Audit arrêté après remise.)*
