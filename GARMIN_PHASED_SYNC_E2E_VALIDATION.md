# GARMIN_PHASED_SYNC_E2E_VALIDATION — PR07A

**Type** : validation E2E réelle, read-only / non destructif. Aucune modification de
code applicatif, aucune PR, aucune donnée supprimée.
**Date** : 2026-08-10 (heure hôte UTC).
**Session Garmin** : **WARM** (session OAuth en cache, valide). Aucun cold login / MFA / mot de passe mesuré.

---

## 1. Environnement testé
| Élément | Valeur |
|---|---|
| HEAD git | `fa68eef` (merge incluant **`a1bff68`** = PR#97 ; `a1bff68` confirmé ancêtre de HEAD) |
| Backend | RUNNING (redémarré après merge) |
| Worker sync | `garmin-sync-worker` RUNNING |
| Redis / Mongo | accessibles |
| Provider | gccli (embedded `backend/bin/gccli 1.9.0`) |
| Compte | compte réel de l'utilisateur (WARM), identité non exposée |
| Chemin testé | **vrai chemin production** : `POST /api/garmin/sync` (ingress → backend → enqueue Redis → worker). Aucune fonction interne appelée pour contourner. |

### État AVANT test (sans modification)
- garmin_activities : 143 → (144 après) · garmin_daily_metrics : 31 → (35 après)
- deep_sync_done : **true** (⇒ chemin sync standard, pas deep sync)
- run_index_scores : snapshot du jour présent (créé lors d'une 1re passe), `run_index=235`
- Accès : user PREMIUM (route `/api/garmin/sync` = PREMIUM, pas de 403)

---

## 2. ⚠️ Observation environnementale majeure (NON un défaut PR07A)
Le premier déclenchement E2E a mesuré **l'ANCIEN pipeline** : les logs worker montraient le bloc unique
`synced 50 activities, 29 daily metrics` **suivi** de l'ancienne ligne `[worker] run_index_history …`
(supprimée par PR07A). Cause : **le process `garmin-sync-worker` ne fait pas de hot-reload** ; démarré
avant le merge PR07A, il exécutait encore le code en mémoire d'avant. Après `supervisorctl restart
garmin-sync-worker` (action ops, ni code ni donnée modifiés), le code PR07A s'est chargé et le sync
phasé s'est comporté comme prévu.
→ **Implication déploiement** : tout déploiement de PR07A doit **redémarrer les workers**, sinon l'ancien
pipeline continue de tourner silencieusement.

---

## 3. Pipeline réel observé (après restart worker)
```
POST /api/garmin/sync (200 {"status":"queued"})
  → enqueue Redis (status "queued")
  → worker claim (BLMOVE)
  → activities_fetching → activities_ready
  → refresh_today_run_index (rebuild workouts + snapshot) → run_index_ready
  → metrics_7d_fetching (J-1→J-7) → readiness_ready
  → enriching (J-8→J-30) + backfill historique → complete
```

## 4. Timeline — timestamps serveur réels (source : logs worker)
| Évènement (log serveur) | Horodatage | Δ depuis sync_start |
|---|---|---|
| `sync_start` | 12:23:38.525 | 0 ms |
| `[backfill] workouts rebuilt (144)` | 12:23:38.832 | +307 ms |
| **`[run-index-history] upserted daily snapshot date=2026-08-10 run_index=235`** | 12:23:38.835 | **+310 ms** ← RunIndex persisté |
| `capabilities persisted` (fin metrics 7 j) | 12:23:42.143 | +3 618 ms ← Readiness |
| `capabilities persisted` (fin enrichissement) | 12:23:51.452 | +12 927 ms |
| `[run-index-history] backfill snapshots=33` | 12:23:51.483 | +12 958 ms |
| `sync_success status=complete duration=12.96s` | 12:23:51.487 | +12 962 ms |

## 5. Latences observées (poller Redis 30 ms, T0 = retour POST)
| Phase Redis observée | obs depuis T0 | run_index_status | daily_metrics_status | readiness_status |
|---|---|---|---|---|
| activities_fetching | 0.3 ms | pending | pending | pending |
| activities_ready | 243 ms | pending | pending | pending |
| metrics_7d_fetching | **304 ms** | **ready** | pending | pending |
| enriching | 3 615 ms | ready | **ready** | **ready** |
| complete | 12 955 ms | ready | ready | ready |

- `enqueue_ms` = 328 ms (round-trip HTTP via ingress ; l'enqueue Redis pur ≈ 3 ms mesuré au benchmark).
- `activities_ready_ms` ≈ **243 ms**
- `run_index_ready_ms` ≈ **304 ms (obs) / 310 ms (serveur)**
- `readiness_ready_ms` ≈ **3 615 ms (obs) / 3 618 ms (serveur)**
- `full_sync_ms` ≈ **12 955 ms (obs) / 12 962 ms (serveur)**

## 6. Critère principal PR07A
`run_index_ready (~310 ms) < readiness_ready (~3.6 s) < complete (~13 s)` → **VÉRIFIÉ**.
Le RunIndex devient disponible **AVANT** la récupération des 30 j de daily metrics (≈ 42× plus tôt).

## 7. RunIndex réellement présent (pas seulement statut Redis)
Log serveur : `upserted daily snapshot date=2026-08-10 run_index=235 confidence=69` à **+310 ms**,
AVANT la phase metrics. Vérif Mongo : `run_index_scores{date:2026-08-10} → run_index=235` présent.
**Un seul** upsert de snapshot du jour (aucun double calcul RunIndex par le worker ; l'ancienne ligne
`[worker] run_index_history` a bien disparu).

## 8. Daily metrics — nombre réel d'appels gccli (échantillonneur /proc)
- **91 spawns gccli** au total = **1 activités** + **90 metrics**.
- 90 = **30 jours uniques × 3 endpoints** (`health hr` + `health sleep` + `health hrv`).
- Découpage : **21 appels** (7 j : J-1→J-7) + **69 appels** (23 j : J-8→J-30).
- Répartition temporelle continue et régulière (~130 ms/appel), cohérente avec l'exécution séquentielle.

## 9. Readiness / HRV
- `has_hrv=False` (HRV toujours indisponible sur cet appareil/compte).
- `daily_metrics_status=ready`, `readiness_status=ready` grâce au sommeil + FC repos réels.
- **L'absence de HRV n'a PAS produit `failed`** — conforme au contrat PR07A.

## 10. Double fetch J-1→J-7 pendant l'enrichissement
**NON.** 90 appels metrics = exactement 30 jours uniques × 3 ; aucun jour refetché. Confirmé par le
code (`range(1,8)` puis `range(8,31)`, sans chevauchement) ET par le compte réel de spawns gccli.

## 11. Historique / backfill
Backfill (`snapshots=33`) exécuté **en phase `enriching`, APRÈS** `run_index_ready` (+310 ms).
Il n'est **pas** sur le chemin critique du premier RunIndex. Durée backfill ≈ 30 ms (12:23:51.452→.483).

## 12. Redis `runindex:garmin:sync_status:{user_id}`
- Isolation par `user_id` : OK. `updated_at` cohérent et croissant.
- **Aucun** champ sensible (password/token/session/secret/credential/cookie/email) : liste vide.
- Statut final : `{"status":"complete","phase":"complete","activities_status":"ready",
  "run_index_status":"ready","daily_metrics_status":"ready","readiness_status":"ready","error_code":null}`.

## 13. Comportement worker
- **Un seul job** traite le sync (1× `sync_start`, 1× `sync_success`).
- **Pas de double RunIndex refresh** (1 seul upsert snapshot ; ligne de double-refresh de l'ancien worker absente).
- **Pas de double backfill** (1 seule ligne backfill).
- **ACK correct** sur succès ; `sync_success status=complete duration=12.96s`.
- **pending key supprimée** après succès (vérifié : `sync_pending:{uid}` = None).
- **Aucun** retry, traceback, ni job orphelin. `attempt=1` unique.

## 14. partial_success
**Non déclenché** pendant ce benchmark réel (aucun échec metrics naturel ; Garmin n'a pas été cassé
volontairement, conformément à la consigne).

## 15. Comparaison AVANT / APRÈS PR07A
| Mesure | Avant PR07A | Après PR07A (mesuré) |
|---|---|---|
| Activities ready | ~0.16–0.59 s (fetch) | **~243 ms** |
| RunIndex ready | **après les daily metrics (~13 s)** | **~310 ms** |
| Readiness ready | après les daily metrics (~13 s) | ~3.6 s |
| Full sync | ~13 s | ~12.96 s |
| Daily metrics total | ~12.3 s (90 appels) | ~12.3 s (90 appels : 21 + 69) |

**KPI principal — temps jusqu'au premier RunIndex utilisable : ~13 s → ~0.31 s.**
Le `full_sync_ms` reste ~13 s (attendu : le volume total de daily metrics est inchangé, PR07A ne
réduit pas le coût total mais **déplace le RunIndex en tête de pipeline**).

## 16. Anomalies / observations (non bloquantes)
1. **Phases Redis `run_index_ready` et `readiness_ready` transitoires.** Elles sont bien écrites, mais
   immédiatement écrasées par la phase suivante (`metrics_7d_fetching` / `enriching`) car il n'y a
   **aucune I/O awaitée** entre les deux `update_sync_progress` consécutifs. Un consommateur qui poll
   verra de façon fiable les **champs de statut** (`run_index_status=ready`, `readiness_status=ready`)
   mais **pas** forcément la chaîne `phase` == `run_index_ready`/`readiness_ready` comme état stable.
   → Le contrat fonctionnel (champs `*_status`) est respecté ; un futur front doit s'appuyer sur les
   `*_status`, pas sur la string `phase`, pour ces 2 jalons. (Exposition front/SSE = périmètre PR07B.)
2. **`_build_and_persist_capabilities` exécuté 2×** par sync (après 7 j puis après enrichissement).
   By design, coût négligeable (aucun appel gccli). Légère redondance.
3. **Workers sans hot-reload** (cf. §2) : impératif de redémarrer les workers au déploiement.
4. `enqueue_ms` ≈ 328 ms = round-trip HTTP ingress, PAS l'enqueue Redis (≈ 3 ms).

## 17. Verdict
Le sync phasé fonctionne réellement : RunIndex disponible en ~0.31 s, bien avant les daily metrics et
le `complete`, sans double fetch, sans double RunIndex, worker propre (1 job, ACK, pending nettoyée,
pas de retry/orphelin/traceback), Redis sanitisé et isolé, HRV absente gérée sans `failed`.
Une observation non bloquante subsiste (phases `run_index_ready`/`readiness_ready` transitoires côté
Redis, pertinente pour l'intégration front PR07B) + le rappel ops "redémarrer les workers".

**PR07A E2E = PASS WITH OBSERVATIONS**
