# RUNINDEX — Test runtime Garmin #321 (activité `garmin-24346252881`, 21,27 km)

> Test runtime sur **une seule activité**, **un seul POST**. Lecture seule hors écritures normales du pipeline #321. Aucun réimport/backfill, aucun worker démarré, aucun changement de code, aucun commit/PR. Drifts locaux préservés (`activity_day`). Training V2 / Coach / WA V2 non modifiés. Aucun secret ni GPS exposé.

---

## Étape 1 — Précontrôles (lecture seule) ✅

| Contrôle | Résultat |
|---|---|
| Propriété activité | `user_id = da8505ef…`, `source = garmin`, `external_id` **str** `24346252881` |
| `activity_details` / `activity_details_fetch` (avant) | **None** / **None** (jamais récupéré) |
| Queue `queue` / `deferred` / `processing` | **0 / 0 / 0** |
| Tâche ACTIVITY_DETAILS en attente/active pour l'utilisateur | **aucune** (pas de risque de concurrence) |
| Workers | `garmin-sync-worker` + `garmin-event-worker` RUNNING |
| Session Garmin (propriétaire) | authentifiée, **non expirée** (exp. 2026-10-12T08:23Z) |
| Quota | risque négligeable (appel ciblé unique) |

Précontrôles satisfaits → test autorisé.

## Étape 2 — Test ciblé (un seul POST)

```
POST /api/garmin/activities/24346252881/phases
→ HTTP 202  { "status": "queued" }
```
Observation via `GET` (aucun POST supplémentaire, aucun appel GCCLI parallèle) :
```
GET /api/garmin/activities/24346252881/phases → HTTP 200
fetch_status: complete | error_code: null
```
Log worker :
```
sync_start   type=ACTIVITY_DETAILS user=da8505ef… attempt=1
sync_success type=ACTIVITY_DETAILS user=da8505ef… duration=0.3s status=complete
```

## Étape 3 — Résultat

| Élément | Valeur |
|---|---|
| Exécution pipeline | **Succès** (`sync_success`, attempt unique) |
| Statut `activity_details.status` | **`no_data`** (`schema_version=2`, `endpoint=typed-splits`) |
| Durée de traitement | **0,3 s** |
| Nombre de phases reçues | **0** |
| Types de phases | aucun (0 `INTERVAL_*` après filtrage `RWD_*`) |
| Distance / durée / vitesse / FC | disponibles au **niveau résumé** (21,27 km / 2h02 / 5:43/km / FC 160, max 174) — déjà en base |
| Splits kilométriques (via pipeline typed-splits) | **absents** (`phases=0`) |
| Séries temporelles | non testées (commande `activity details` disponible, non appelée — un seul POST) |

### Contrôle anti-faux-négatif (lecture seule, commande distincte)

Conformément à la consigne « ne pas interpréter une réponse vide comme indisponibilité générale », vérification via `gccli activity splits 24346252881 -j` (≠ `typed-splits`, lecture seule, après fin du job, sans concurrence) :

| Résultat | Valeur |
|---|---|
| Racine | `{ activityId, lapDTOs, eventDTOs }` |
| **`lapDTOs`** | **22 segments** = splits **kilométriques** auto |
| Par segment | `distance` (1000 m), `duration`, `averageSpeed`, `averageHR`, `elevationGain/Loss` |
| Exemples | km1 : 1000 m / 341,1 s / FC 149 · km2 : 1000 m / 328,1 s / FC 159 · km3 : 1000 m / 311,0 s / FC 159 |

**FAIT DÉMONTRÉ** : Garmin dispose bien de **22 splits kilométriques** pour cette activité, récupérables via `activity splits`. Le `no_data` du pipeline #321 concerne **uniquement** les phases structurées `typed-splits` — **pas** les splits km, que le pipeline n'interroge pas.

## Étape 4 — Distinction : données / limites pipeline / défauts

### Données récupérées
- **Pipeline #321 (typed-splits)** : `status=no_data`, 0 phase. Résultat **correct** pour une course continue (aucun lap `INTERVAL_*`). Mise en cache versionnée d'un résultat vide (évite les re-fetch).
- **Hors pipeline (lecture diagnostique)** : 22 splits km réels existent via `activity splits` (`lapDTOs`).

### Limites du pipeline (non des défauts d'exécution)
- Le pipeline #321 n'appelle **que** `activity typed-splits`. Pour une course continue, cela renvoie légitimement `no_data`.
- Les **splits kilométriques** (`activity splits` / `lapDTOs`) ne sont **pas ingérés** par #321 → indisponibles pour Workout Analysis V2 (`km_splits` reste absent, `WorkoutKilometerSplits` ne peut rien afficher).
- Conséquence WA V2 : `phase_analysis.available=false` → classification structurelle « longue » conservée (comportement attendu, pas de régression).

### Défauts d'exécution
- **Aucun.** Pipeline, queue, worker, cache et endpoints se comportent correctement (POST 202 → worker 0,3 s → `complete` → GET cache-only cohérent). Réservation nettoyée, pas de job bloqué.

### Compatibilité réelle avec WA V2
- Pour les séances **à intervalles** (ex. 4×4min validé en #321) : ✅ pleinement exploitable.
- Pour les courses **continues** (A) : ❌ aucune valeur ajoutée via typed-splits ; la donnée exploitable (22 km splits) nécessiterait l'ingestion de `activity splits`, non couverte par #321.

---

## Conclusion

Le pipeline #321 fonctionne **correctement** et de façon idempotente sur cette activité : exécution réussie, cache `no_data` versionné, aucun défaut. La réponse vide n'est **pas** une indisponibilité générale — Garmin expose **22 splits kilométriques** via `activity splits`, non interrogés par #321.

**Piste minimale pour une évolution (type #330, non implémentée)** : ingérer les `lapDTOs` (`activity splits`) pour les courses continues afin de restituer les splits km dans WA V2, en complément des phases `typed-splits` pour les séances structurées. Sans aucune intensité physiologique inventée.

*(STOP. Un seul POST effectué. En attente de validation.)*
