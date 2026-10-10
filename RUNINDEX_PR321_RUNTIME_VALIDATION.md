# RUNINDEX — Validation runtime PR #321 (enrichissement ciblé des phases d'activité)

> Validation **runtime / lecture + parcours d'enrichithement normal uniquement**. Aucun changement de code, aucune PR, aucun commit, aucun import global, aucune synchronisation complète/incrémentale, aucun flush Redis/Mongo. Drift local `activity_day` préservé. Aucun secret exposé. Compte legacy `default` non utilisé.
> Seule écriture produite : celle du parcours d'enrichissement ciblé de #321 (un seul déclenchement). Ce rapport est la seule écriture manuelle.

---

## 1. HEAD et environnement (préflight)

| Contrôle | Résultat |
|---|---|
| HEAD local | `5234dae` (merge local, parent canonique **`3ad7596`** = PR #321) |
| Fichiers #321 présents | `backend/garmin/activity_details.py`, `backend/activity_phases.py`, `backend/garmin/activity_ids.py` ✅ |
| Backend | opérationnel (health `401`, auth requise) |
| Workers Garmin | 4/4 RUNNING (`sync`, `event`, `monitor`, `scheduler`) |
| Redis runtime | **accessible** — `/app/bin/redis-server` v7.0.15, `PING=True` (le binaire n'est pas dans le `PATH`, d'où les skips du harness de test, mais le service runtime fonctionne) |
| MongoDB | accessible |
| Endpoints montés | `POST`/`GET /api/garmin/activities/{activity_id}/phases` (router `garmin_router` préfixe `/garmin`, inclus dans `api_router` préfixe `/api`) |
| Auth compte réel | token émis pour le propriétaire (JWT HS256) — secrets non exposés |

## 2. Compte et activité vérifiés

- Propriétaire réel : `da8505ef…` (anonymisé), `source=garmin`, session GCCLI présente et valide.
- Activité `24671804067` : **appartient bien** à ce compte (`garmin_activities.user_id = da8505ef…`).
- Rapprochement d'identifiant : GCCLI `activityId` **int** `24671804067` ↔ Mongo `external_id` **str** `"24671804067"` — cohérent.
- Compte legacy `default` **non utilisé**.

## 3. État MongoDB avant / après

| Champ | AVANT | APRÈS |
|---|---|---|
| `user_id` | `da8505ef…` | `da8505ef…` (inchangé) |
| `external_id` | `str "24671804067"` | `str "24671804067"` (inchangé) |
| `source` | `garmin` | `garmin` |
| `activity_details` | **absent** | présent (`schema_version=2`, `source=garmin`, `endpoint=typed-splits`, `fetched_at`, `phases[10]`) |
| `activity_details_fetch` | **absent** | *(statut porté par `activity_details.status`)* `status=complete` |
| Phases persistées | 0 | **10** |
| Version de cache | — | `schema_version = 2` |

État initial **vierge** → le POST a donc déclenché une **vraie récupération GCCLI** (pas un cache-hit).

## 4. Résultat POST

```
POST /api/garmin/activities/24671804067/phases
→ HTTP 202  { "status": "queued" }
```
- Aucune erreur d'authentification, isolation par utilisateur respectée.
- Job `ACTIVITY_DETAILS` mis en file (pas de synchronisation Garmin générale).

## 5. Exécution worker et Redis

Logs worker (`sync_worker`) :
```
sync_start   type=ACTIVITY_DETAILS user=da8505ef… attempt=1
sync_success type=ACTIVITY_DETAILS user=da8505ef… duration=0.66s status=complete
```
| Contrôle | Résultat |
|---|---|
| Job pris par un worker | ✅ (sync-worker) |
| Appel GCCLI `typed-splits` déclenché (nécessaire) | ✅ (cache vide initialement) |
| Traitement concurrent de la même cible | ❌ aucun (attempt=1 unique) |
| ACK après traitement | ✅ (`status=complete`) |
| Réservation `pending` nettoyée | ✅ (aucune clé résiduelle `da8505ef`/activité) |
| Job bloqué en `processing` | ❌ liste `runindex:garmin:processing` **vide (0)** |
| Boucle de réinsertion | ❌ `queue=0`, `deferred=0` |

*(La clé `sync_pending:default` observée concerne la sync de fond du compte legacy `default`, sans rapport avec ce test.)*

## 6. Contrat des phases réellement persistées

10 phases normalisées — **1 warmup / 4 effort / 4 recovery / 1 cooldown**. **Aucune entrée `RWD_*`** persistée (filtrées). Ordre `order = 0…9` cohérent et chronologique.

Modèle neutre métier (`phase_type`) **séparé** du type natif Garmin (`native_type`). Champs par phase : `order`, `native_type`, `phase_type`, `duration_s`, `distance_m`, `average_speed_mps`, `average_hr`, `max_hr`, `min_hr`, `source`.

### Les 8 phases effort/récupération attendues

| Rép. | Durée effort | Distance effort | Allure effort¹ | FC moy. | FC max. | Durée récup. |
|---|---|---|---|---|---|---|
| 1 | 240,0 s | 832,07 m | 4:48/km | 151 | 160 | 180 s |
| 2 | 240,0 s | 851,11 m | 4:42/km | 157 | 165 | 180 s |
| 3 | 240,0 s | 885,81 m | 4:31/km | 159 | 175 | 180 s |
| 4 | 240,0 s | 825,41 m | 4:51/km | 159 | 166 | 180 s |

¹ Allure dérivée de `distance_m / duration_s` (le champ `average_speed_mps` est persisté à `None` — voir risques §10).

**Conformité avec l'audit GCCLI de référence** :
| Réf. attendue | Persisté | Verdict |
|---|---|---|
| E1 832 m / 4:48 / 151-160 | 832,07 m / 4:48 / 151-160 | ✅ |
| E2 851 m / 4:42 / 157-165 | 851,11 m / 4:42 / 157-165 | ✅ |
| E3 886 m / 4:31 / 159-175 | 885,81 m / 4:31 / 159-175 | ✅ |
| E4 825 m / 4:51 / 159-166 | 825,41 m / 4:51 / 159-166 | ✅ |

Chronologie correcte, `RWD_*` absents du résultat normalisé. ✅

## 7. Résultat GET (cache-only)

```
GET /api/garmin/activities/24671804067/phases
→ HTTP 200
{ activity_details: { schema_version:2, status:"complete", source:"garmin",
                      endpoint:"typed-splits", fetched_at, phases[10] },
  fetch_status: "complete", error_code: null }
```
| Contrôle | Résultat |
|---|---|
| Statut cache | `complete` |
| Nombre de phases | 10 (1/4/4/1) |
| Types natif + normalisé | `native_type` + `phase_type` présents |
| Durées / distances | présentes et cohérentes avec Mongo |
| FC disponibles | `average_hr` / `max_hr` ; `min_hr` null (GCCLI ne fournit pas minHR) |
| Ordre des phases | 0…9 |
| Cohérence avec MongoDB | **identique** |
| **Cache-only** | ✅ `fetched_at` **inchangé** avant/après GET (`2026-10-10T14:21:19.938Z`) → **aucun nouvel appel GCCLI** |

## 8. Contrôles de non-régression (lecture seule)

| Contrôle | Résultat |
|---|---|
| Activités historiques accessibles | ✅ `garmin_activities` user = **164 (inchangé)** |
| Résumés Garmin inchangés | ✅ (distance_m 14263, avg_hr 138, duration_s 5333 identiques) |
| Workouts non reconstruits | ✅ doc `garmin-24671804067` identique (clés résumé, `type=run`, **sans** phases/splits injectés) |
| Training V2 modifié | ❌ non (aucun traitement déclenché) |
| Readiness recalculée par cet enrichissement | ❌ non |
| Workout Analysis V2 exploite les phases | ❌ **non encore** — `session_type=standard`, `intensity.available=false`, `evidence.has_splits=false` (frontière de périmètre attendue : #321 = ingestion seule) |
| Événement `ACTIVITY_CREATED` artificiel | ❌ aucun (count d'activités inchangé) |

Séparation Garmin-spécifique / modèle métier neutre respectée (`native_type` vs `phase_type`).

## 9. Tests impossibles ou non observables

- **Tests d'intégration Redis du harness** (`test_activity_details_delayed_redis_c321`) : 34 cas **skipped** car le binaire `redis-server` n'est pas dans le `PATH` du harness (le Redis runtime, lui, fonctionne). Le chemin différé/watchdog n'a donc pas été exercé par ces tests — mais le chemin nominal a été validé en runtime réel.
- **Job différé** : non observé, car le traitement a été immédiat (`attempt=1`, 0,66 s). La temporisation n'a pas eu lieu à contourner.
- **Expiration/refresh de session GCCLI** : non testé (session valide jusqu'au 2026-10-11T08:49Z).

## 10. Risques résiduels

- **`average_speed_mps = None`** : GCCLI fournit `averageSpeed` mais il n'est pas mappé dans le modèle normalisé. **Non bloquant** (l'allure est dérivable exactement de `distance_m / duration_s`, valeurs vérifiées conformes), mais à corriger pour éviter une dérivation redondante côté consommateur.
- **`min_hr` toujours null** : conforme (GCCLI typed-splits n'expose pas de FC min) — à documenter côté consommateur.
- **Bruit de fond** : la sync de fond du compte legacy `default` émet `session_unavailable` (pas de session) — **pré-existant**, sans rapport avec #321.
- **WA V2 ne consomme pas encore les phases** : attendu (périmètre #321 = ingestion). La valorisation (analyse réelle des répétitions) reste une PR ultérieure.

---

## Verdict

# ✅ PASS

Parcours réel validé de bout en bout :
- **Récupération GCCLI** vérifiée (log worker `ACTIVITY_DETAILS` + `fetched_at` horodaté, cache initialement vide).
- **Persistance MongoDB** vérifiée (10 phases normalisées, versionnées `schema_version=2`, identifiant/propriétaire inchangés, pas de duplication, pas d'événement artificiel).
- **Lecture API** vérifiée (`GET` cache-only, cohérent avec Mongo, `fetched_at` inchangé).
- **Contrat conforme** : les 4 efforts (240 s) + 4 récupérations (180 s) correspondent exactement aux valeurs de référence ; `RWD_*` filtrés ; chronologie correcte.
- **Redis** sain (réservation nettoyée, aucun job bloqué, aucune boucle de réinsertion).
- **Aucune régression** observée.

Les seuls points résiduels (`average_speed_mps` non mappé, `min_hr` null, phases non encore consommées par WA V2) sont **non bloquants** et relèvent d'améliorations/étapes ultérieures, pas d'anomalies du parcours #321.

*(Aucune PR, aucune correction automatique. En attente de ta décision.)*
