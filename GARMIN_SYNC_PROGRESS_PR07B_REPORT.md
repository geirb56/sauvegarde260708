# GARMIN_SYNC_PROGRESS_PR07B_REPORT

1. **Architecture retenue**  
   Le worker Garmin continue à écrire l’état éphémère PR07A dans Redis via `update_sync_progress()`. Cette même fonction publie désormais un snapshot `SYNC_PROGRESS` sur un stream Redis dédié. Le SSE dédié lit ce stream pour le temps réel et renvoie aussi le dernier snapshot Redis à l’ouverture.

2. **Stream Redis retenu**  
   `runindex:events:sync_progress`

3. **Endpoint SSE**  
   `GET /api/garmin/sync/stream`

4. **Contrat événement**  
   Payload SSE/Redis snapshot :
   ```json
   {
     "type": "SYNC_PROGRESS",
     "user_id": "…",
     "status": "queued|in_progress|complete|partial_success|failed",
     "phase": "…",
     "activities_status": "pending|ready|failed",
     "activities_count": 0,
     "run_index_status": "pending|ready|failed",
     "daily_metrics_status": "pending|ready|failed|no_usable_data",
     "readiness_status": "pending|ready|unavailable",
     "error_code": null,
     "updated_at": "…"
   }
   ```

5. **Source de vérité**  
   La source de vérité reste la clé Redis PR07A `runindex:garmin:sync_status:{user_id}`. Le SSE ne fait qu’exposer le dernier snapshot connu.

6. **Gestion `phase` vs `*_status`**  
   `phase` reste l’étape courante du pipeline. Les champs `run_index_status`, `daily_metrics_status`, `readiness_status` restent les jalons durables utilisés par le frontend même si une phase transitoire a été manquée.

7. **Snapshot initial**  
   À l’ouverture du SSE, le backend lit immédiatement le dernier `sync_status` Redis de l’utilisateur authentifié et l’émet sans attendre un nouvel événement stream.

8. **Reconnexion**  
   La reconnexion relit Redis puis reprend l’écoute du stream Redis. Pas de replay historique complexe : le snapshot courant suffit à reconstruire l’état.

9. **Heartbeat**  
   Le SSE réutilise le pattern existant `: ping` avec blocage `XREAD` et heartbeat léger sans payload métier.

10. **Isolation user**  
    Le stream SSE est authentifié via le mécanisme JWT existant. Le fan-out SSE filtre strictement `user_id` et n’émet jamais les snapshots d’un autre utilisateur.

11. **Fallback HTTP**  
    Le fallback reste `GET /api/garmin/status`, qui expose déjà `sync_status` depuis le même état Redis.

12. **`partial_success`**  
    Les snapshots `partial_success` conservent `run_index_status=ready`, `daily_metrics_status=failed`, `readiness_status=unavailable|ready` selon l’état réellement acquis.

13. **Sécurité / sanitation**  
    `update_sync_progress()` continue à filtrer tout champ contenant `password`, `token`, `session`, `secret`, `credential`, `cookie` avant persistance et publication. Aucun secret Garmin n’est publié dans le stream ou le SSE.

14. **Tests**  
    Ajout de `backend/tests/test_garmin_sync_progress_pr07b.py` pour couvrir :
    - publication + sanitation ;
    - isolation utilisateur ;
    - snapshot initial ;
    - phases transitoires manquées (`run_index_ready`, `readiness_ready`) ;
    - reconnexion ;
    - `complete` ;
    - `partial_success` ;
    - `failed` safe ;
    - non-régression ACTIVITY_CREATED ;
    - auth SSE.

15. **Non-régression `ACTIVITY_CREATED`**  
    Le stream historique reste séparé : `runindex:events:activity_created` n’est pas modifié et son SSE dédié continue à fonctionner indépendamment.

16. **Limites**  
    Pas de replay historique exhaustif des snapshots SSE : le design repose volontairement sur le snapshot Redis courant comme mécanisme de recovery. Le frontend doit utiliser `sync_status` / SSE, pas la seule `phase`.

17. **Règle de restart worker**  
    Toute release modifiant le code exécuté par `garmin-sync-worker` nécessite un restart/redeploy du worker.

18. **Benchmark réel**  
    Aucun benchmark Garmin réel n’a été exécuté ici. Si l’environnement réel est disponible, il faut vérifier que `run_index_status=ready` apparaît avant `readiness_status=ready`, puis avant `status=complete`.
