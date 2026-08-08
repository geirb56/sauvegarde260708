# RunIndex — Benchmark Garmin réel (avant refonte Onboarding)

**Type** : audit read-only / mesures réelles. Aucune modification du comportement
métier, aucune optimisation, aucune donnée réelle modifiée ou supprimée.
**Date** : 2026-08-08 (heure hôte UTC : `2026-08-08T07:51Z`).
**Auteur** : E1 (agent) — mesures instrumentées via les modules backend réels.

---

## 1. Environnement testé

| Élément | Valeur |
|---|---|
| Binaire gccli | `/app/backend/bin/gccli` — `gccli 1.9.0 (0893b24) built 2026-06-15` |
| Provider actif | `gccli` (`GARMIN_PROVIDER=gccli`) |
| Session Garmin | **WARM** (session OAuth en cache, valide, non expirée) — compte réel de l'utilisateur (confirmé propriétaire) |
| Mongo mesures persistance | **base isolée jetable** `<DB_NAME>_bench_tmp` (créée puis droppée ; aucune donnée réelle touchée) |
| Redis / queue | preview (`REDIS_URL`), 1 worker actif, file vide au moment du test |
| Statut warm/cold | **WARM / incrémental** côté session ; côté données, mesures réalisées sur namespace isolé vierge (≈ coût d'un premier import de données) |

> Sécurité : aucun email / token / contenu de session Garmin n'est exposé dans ce rapport.

---

## 2. Cartographie du pipeline

```
Frontend
  │  POST /api/garmin/connect  (JWT)            POST /api/garmin/sync (JWT)
  ▼                                              ▼
api/garmin.py  ── connect(): auth check gccli ── enqueue_sync() ─┐   (NON-BLOQUANT :
  │  (session validée ~11 ms)                                    │    l'API répond
  │                                                              │    immédiatement)
  ▼                                                              ▼
garmin/service.connect()                              jobs/queue.py (Redis)
  │  save_session() (Mongo, chiffré Fernet)             LPUSH runindex:garmin:queue
  │  activate_garmin_trial()                                    │
  └──────────────── enqueue_sync() ────────────────────────────┘
                                                                ▼
                                        workers/sync_worker.py (hors-process)
                                          claim_job()  BLMOVE queue → processing (poll 5 s)
                                          lock par user (Redis) + cap concurrence global
                                                                │
                                                                ▼
                                        garmin/service.sync() / deep_sync()
                                          ├─ ensure_session() (hydrate depuis Mongo si besoin)
                                          ├─ provider.sync_activities / fetch_all_activities
                                          │     └─ runner.fetch_activities  → gccli `activities list --limit N`
                                          ├─ _ingest_activities()  → UPSERT garmin_activities
                                          │     └─ emit ACTIVITY_CREATED (Redis stream)
                                          ├─ provider.get_daily_metrics(days=30)
                                          │     └─ runner.fetch_daily_metrics : BOUCLE jour par jour
                                          │           for i in 1..days : gccli health hr / sleep / hrv  (3 appels/jour)
                                          ├─ UPSERT garmin_daily_metrics
                                          └─ _build_and_persist_capabilities()
                                                                │
                    ┌───────────────────────────────────────────┤
                    ▼                                            ▼
   workers/event_worker.py                       services/run_index_history
   ACTIVITY_CREATED → workouts (couche produit)   refresh_run_index_after_garmin_sync()
   + feed cache (Redis)
                                                                │
                                                                ▼
                              GET /api/run-index  → garmin/insights.compute_run_index()
                                 lit garmin_activities (≤200) + garmin_daily_metrics (≤30)
                                 → RunIndex + Run Readiness (même fonction) ~5 ms
```

**Points clés d'architecture**
- `/connect` et `/sync` sont **non-bloquants** : ils poussent un job Redis et répondent tout de suite ; tout le travail lourd gccli est exécuté par `sync_worker` hors-process.
- Le premier sync d'un user déclenche `deep_sync()` (import complet paginé) une seule fois (`deep_sync_done`), puis les syncs suivants passent par le chemin incrémental léger.
- RunIndex et Run Readiness sont produits par **la même fonction** `compute_run_index()` (source unique de vérité).

---

## 3. Mesures brutes (session WARM)

### 3.1 Validation de session — T0
| Métrique | Valeur |
|---|---|
| `session_validation_ms` | **11.2 ms** |
| authentifié / expiré | oui / non |
| Type | **WARM** (session en cache). ⚠️ Le login à froid — création de session — **n'est pas mesuré** (nécessite le mot de passe Garmin, non fourni/non autorisé). |

### 3.2 Récupération des activités (read-only, 1 appel gccli / requête)
| Requête | `activities_fetch_ms` | Activités | Appels gccli |
|---|---|---|---|
| `--limit 20` (feed récent) | **195.5 ms** | 20 | 1 |
| `--limit 50` (page standard) | **161.3 ms** | 50 | 1 |
| `--limit 100` | **275.4 ms** | 100 | 1 |
| Pagination complète (deep sync) | **587.5 ms** | **143** | ~3 pages |

### 3.3 Comparaison fenêtres d'activités (dérivé du set complet — 0 appel gccli en plus)
| Fenêtre | Nb activités |
|---|---|
| 7 derniers jours | 2 |
| 28 derniers jours | 2 |
| 90 derniers jours | 12 |
| Historique total disponible | 143 (depuis 2024-11-23) |

> Remarque : la récupération d'activités se fait par **`--limit N` (nombre)**, pas par fenêtre de jours. Les fenêtres ci-dessus sont un post-filtrage du set complet.

### 3.4 Récupération des métriques quotidiennes (read-only) — **LE GOULOT**
Chaque jour = **3 appels gccli séquentiels** (`health hr`, `health sleep`, `health hrv`), boucle jour par jour à partir d'hier.

| Requête | `daily_metrics_fetch_ms` | Jours avec données | Appels gccli | Sommeil | FC repos | VFC/HRV |
|---|---|---|---|---|---|---|
| `days=7` | **3 046.8 ms** | 7 | 21 | ✅ | ✅ | ❌ |
| `days=30` (valeur production) | **12 296.4 ms** | 29 | 90 | ✅ | ✅ | ❌ |

> ≈ **410 ms par jour** (3 sous-process gccli). **VFC/HRV absente** pour cet appareil/compte (les champs sont donc renvoyés `null` → UI « — »).

### 3.5 Persistance Mongo (base isolée jetable)
| Métrique | Valeur |
|---|---|
| `activities_persist_ms` (143 upserts) | **54.0 ms** |
| `daily_metrics_persist_ms` (29 upserts) | **18.7 ms** |

### 3.6 Calcul RunIndex + Run Readiness (warm compute, données réelles en base isolée)
| Métrique | Valeur |
|---|---|
| `runindex_compute_ms` (RunIndex **+** Readiness, même fonction) | **4.7 ms** |
| `readiness_compute_ms` | inclus dans les 4.7 ms |
| Run Readiness calculé | 39/100 · ACWR 4.0 · HRV indisponible · 29 points d'historique |

### 3.7 File / worker
| Métrique | Valeur |
|---|---|
| `enqueue_roundtrip_ms` (Redis LPUSH/LREM) | **3.2 ms** |
| Santé file | `healthy` · 1 worker actif · file vide · 0 orphelin · 0 échec |
| Latence de claim (BLMOVE) | poll `timeout=5 s` ; **BLMOVE étant bloquant, un worker en attente prend le job quasi-instantanément** — les 5 s sont seulement le cycle de repoll, pas une attente systématique |

---

## 4. T0 → T6 (reconstruction Time-to-First-Value)

Chronologie cumulée à partir du déclenchement du sync (session WARM déjà valide) :

| Étape | Description | Temps cumulé | Note |
|---|---|---|---|
| **T0** | Session utilisable | ~0.01 s | WARM (login à froid **non mesuré**) |
| **T1** | Premières données Garmin (1re page d'activités) | ~0.16–0.20 s | 1 appel gccli |
| **T2** | Activités persistées (143) | ~0.65 s | fetch complet 0.59 s + upsert 0.05 s |
| **T3** | Métriques quotidiennes persistées | **~13.0 s** | fetch 12.3 s (**goulot**) + upsert 0.02 s |
| **T4** | 1er RunIndex calculable | +0.005 s après T2 (activités suffisent) | ~0.66 s |
| **T5** | 1re Run Readiness *significative* (RHR/sommeil réels) | ~13.0 s | dépend de T3 (données physio) |
| **T6** | Sync courant terminé (deep sync) | **~13.0 s** | + latence file (~ms) |

**Total sync (premier import / deep sync)** : **≈ 13 s**, dont **≈ 12.3 s (95 %) sur les métriques quotidiennes**.
**Sync incrémental ultérieur** (activités uniquement, `--limit 10`, sans métriques quotidiennes) : **< 1 s**.

---

## 5. Volumes observés (compte réel, en base au moment du test)
- garmin_activities : **143** (deep_sync déjà effectué) — plage 2024-11-23 → 2026-08-07
- garmin_daily_metrics : **31 jours** (2026-07-05 → 2026-08-05)
- workouts (source garmin) : 143
- Séparation données existantes / écritures benchmark : **toutes les mesures de persistance ont été faites dans `<DB_NAME>_bench_tmp` (base isolée droppée en fin de run)** ; **aucune** écriture sur la base réelle.

---

## 6. Goulots d'étranglement (constat, sans prescription d'implémentation)

1. **Métriques quotidiennes = 95 % du temps d'onboarding.** Cause : boucle **séquentielle jour par jour**, **3 sous-process gccli par jour** (30 jours ⇒ **90 spawns de process**, ~410 ms/jour, ~12.3 s).
2. **Activités** : rapides (~0.16–0.59 s), non limitantes.
3. **Persistance Mongo** : négligeable (~0.05 s).
4. **Calcul RunIndex/Readiness** : négligeable (~5 ms).
5. **File Redis / worker** : négligeable (~3 ms enqueue ; claim quasi-instantané via BLMOVE bloquant).
6. **VFC/HRV absente** sur cet appareil/compte : le modèle de readiness se repondère (RHR + sommeil), mais 1/3 des appels quotidiens (`health hrv`) ne rapporte aucune donnée exploitable ici.

---

## 7. Conclusions A → E (strictement issues des mesures)

- **A — Time-to-First-Value.** Un premier **RunIndex** est calculable en **< 1 s** (dès les activités persistées, ~0.66 s). Une **Run Readiness significative** (basée sur RHR/sommeil réels) n'apparaît qu'**après ~13 s**, car elle dépend des métriques quotidiennes.

- **B — Goulot unique et dominant.** La récupération des métriques quotidiennes (**90 appels gccli séquentiels, ~12.3 s**) représente **~95 %** du temps d'onboarding. Tout le reste (session, activités, persistance, calcul, file) cumule **< 0.7 s**.

- **C — Warm vs cold.** Mesures réalisées avec une **session WARM** (cache valide) et des **données fraîchement récupérées** persistées en **namespace Mongo isolé**. L'onboarding **totalement à froid** (création de session par login + mot de passe) est **NON TESTÉ** (isolation non garantie sans le mot de passe Garmin, exclu par consigne). Le coût côté données (fetch+persist+compte à partir d'une base vide) est en revanche représentatif d'un premier import.

- **D — Disponibilité/qualité des données.** Sommeil ✅ et FC de repos ✅ présents sur tous les jours récents. **VFC/HRV ❌** (absente pour cet appareil/compte). Activités : historique riche (143) mais **peu d'activités récentes** (2 sur 7 j, 12 sur 90 j).

- **E — Portée (rappel).** Aucune optimisation ni refonte n'a été effectuée (audit read-only). Les données ci-dessus établissent la **base de référence** avant refonte Onboarding : la cible d'amélioration prioritaire est sans ambiguïté la phase « métriques quotidiennes ».

---

## 8. Limites de ce benchmark
- Login à froid (T0 réel de création de session) **non mesuré** (mot de passe non disponible/non autorisé) → T0 reporté = validation d'une session déjà en cache.
- Onboarding entièrement à froid **non testé** (choix utilisateur : « non testé si isolation non garantie »).
- Mesures effectuées sur **un seul compte** (multi-utilisateur non profilé).
- Timings gccli dépendants de la latence Garmin Connect à l'instant du test ; un seul run par requête (pas de moyenne multi-run).
- Fenêtres d'activités (7/28/90 j) obtenues par post-filtrage du set complet, non par requêtes gccli distinctes (l'API gccli récupère par `--limit`, pas par jours).

---

*Mesures produites par un harnais one-off read-only (`/tmp/garmin_benchmark.py`, hors code applicatif), utilisant les modules backend réels (`garmin/factory`, `providers/gccli_provider`, `runner`, `insights`). Résultat JSON brut : `/tmp/garmin_benchmark_result.json`.*
