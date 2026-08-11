# GARMIN_ACTIVATION_PR07C_E2E_VALIDATION

**Type** : validation E2E réelle, read-only. Aucun code modifié, aucune PR, aucune correction, aucune donnée supprimée.
**Date** : 2026-08-11 (UTC). **Session Garmin** : **WARM** (aucun cold login / MFA / mot de passe).

---

## 1. HEAD testé & PRs
- HEAD : **`9dafb27`** (merge incluant tous les PR ci-dessous).
- Présents en historique : PR#97 (PR07A phased sync), PR#99 (PR07B SSE), PR#101 (PR07B.0 toolchain / jest-dom pinné), PR#100 (PR07B.1 login autofill), PR#102 (PR07C onboarding activation). ✅
- Worker **redémarré** avant test → exécute bien le code actuel de `main` (vérifié : logs montrent le pipeline phasé PR07A, plus l'ancien double-refresh).

## 2. Environnement
- Backend + `garmin-sync-worker` RUNNING (redémarrés), Redis + Mongo OK, provider gccli.
- Edge preview : **Cloudflare** (`server: cloudflare`, `cf-ray`, `via: 1.1 google`).
- Compte : compte réel WARM `da8505ef…` (déjà connecté Garmin), identité non exposée.

## 3. Parcours réellement exécuté (et limite)
⚠️ **Le parcours navigateur interactif (login RunIndex → onboarding → SAISIE des identifiants Garmin → connect) n'a PAS pu être exécuté** :
- le seul compte RunIndex avec identifiants de test (`testrunner…` / `08cafe9d…`) **n'a aucune session Garmin** ;
- le compte Garmin connecté (`da8505ef…`) n'a pas de mot de passe RunIndex en ma possession, et l'étape onboarding « Connexion Garmin » exige la saisie d'**identifiants Garmin** (état React local `garminStatus`), que je n'ai pas et ne dois pas utiliser/exposer.

Validation donc réalisée sur **le contrat de données réel que consomme l'UI** :
1. sync réelle déclenchée via **`POST /api/garmin/sync`** (vrai chemin : API → queue → worker, session warm) ;
2. **consommation réelle du SSE `/api/garmin/sync/stream`** (comme le hook `useGarminSyncProgress`) ;
3. vérification du binding UI (`Onboarding.jsx`) au niveau code ;
4. test de délivrance SSE via localhost **et** via l'edge preview.

## 4. Ordre réel des événements SSE (consommé sur localhost, temps réels)
| # | Frame SSE (`data.phase`) | Horodatage | Δ depuis sync_start | run_index_status | readiness_status |
|---|---|---|---|---|---|
| 0 | `: connected` + snapshot | — | — | — | — |
| 1 | `queued` | 09:51:31.028 | 0 | ready(*) | ready(*) |
| 2 | `activities_fetching` | 09:51:31.031 | +3 ms | pending | pending |
| 3 | `activities_ready` | 09:51:31.277 | **+248 ms** | pending | pending |
| 4 | **`run_index_ready`** | 09:51:31.335 | **+306 ms** | **ready** | pending |
| 5 | `metrics_7d_fetching` | 09:51:31.335 | +306 ms | ready | pending |
| 6 | **`readiness_ready`** | 09:51:34.060 | **+3 031 ms** | ready | **ready** |
| 7 | `enriching` | 09:51:34.061 | +3 032 ms | ready | ready |
| 8 | `complete` | 09:51:43.380 | **+12 351 ms** | ready | ready |

(*) le tout premier snapshot reflète l'état complet précédent (initial snapshot on connect).

✅ **Point positif majeur** : contrairement à la **clé** Redis (transitoire, où `run_index_ready`/`readiness_ready` étaient écrasés en <2 ms), le **stream** Redis conserve **chaque frame discret** — `run_index_ready` et `readiness_ready` sont bien livrés comme événements distincts. L'ordonnancement PR07A est donc parfaitement observable par le front.

## 5. Critère principal PR07A/07C
`run_index_ready (+306 ms) < readiness_ready (+3 031 ms) < complete (+12 351 ms)` → **VÉRIFIÉ**.
RunIndex disponible **avant** les daily metrics 30 j.

## 6. RunIndex affiché : ⚠️ NON (valeur), OUI (panneau/timing)
- Le panneau RunIndex **apparaît au bon moment** (UI ligne 58 : `runIndexReady = run_index_status === "ready"`). ✅ (visibilité)
- **MAIS la valeur affichée = `"—"`** : le payload SSE **ne contient PAS** `run_index` (seulement `run_index_status`). L'UI lit `syncProgress.run_index` (ligne 302) → `?? "—"`.
- Valeur backend réelle : `run_index_scores{2026-08-11}=**235**` (log worker : `upserted daily snapshot … run_index=235`). **Elle n'est jamais injectée dans le SSE.**

## 7. Readiness affichée : ⚠️ NON (valeur), OUI (panneau/timing)
- Panneau Readiness **s'ajoute** au RunIndex sans le remplacer (UI ligne 59, rendu additif). ✅
- **Valeur = `"—"`** : le SSE ne contient pas `readiness` (seulement `readiness_status`). UI lit `syncProgress.readiness` (ligne 309).

## 8. Activités affichées vs observées : ⚠️ incohérence de champ
- Sync réelle : `synced=50` (1 page limit=50), total DB=**144**, `activities_count=144` **présent dans le SSE**.
- **MAIS l'UI lit `syncProgress.synced_count`** (ligne 60), **absent du SSE** → fallback `garminCount`, lui-même alimenté par la réponse de `POST /garmin/sync` = `{"status":"queued"}` (pas de `synced_count`) → **0**.
- Conséquence : le compteur d'activités (`syncedCount > 0`) **reste caché / à 0** dans l'onboarding.

## 9. SSE — délivrance (coupure/edge)
- **localhost:8001** : SSE **streame parfaitement** en temps réel (tous les frames ci-dessus). ✅ → **le code PR07B est correct**.
- **Edge preview (Cloudflare)** : `HTTP/2 200`, `content-type: text/event-stream`, mais **0 octet de corps reçu en 20 s** (testé avec `curl -N` ET httpx). → **l'edge preview bufferise `text/event-stream`** et ne flushe pas les frames en direct.
- Test reconnexion : la reconnexion via l'edge **timeout** (aucun frame) ; via localhost, une nouvelle connexion réémet immédiatement le snapshot (`id: snapshot`) puis reprend — comportement reconnect-safe **correct côté app**.
- **Impact réel** : en preview, l'EventSource du navigateur **ne recevrait pas** les frames progressifs → l'écran d'activation onboarding **resterait bloqué sur « syncing »**. (Limitation infra/edge, **pas** un défaut du code applicatif.)

## 10. États intermédiaires / faux score
- Aucun faux score numérique affiché : tant que non prêt, l'UI montre `"—"` (pas de valeur fantaisiste). ✅ (mais voir §6–7 : la valeur reste `"—"` même une fois prête).

## 11. CTA Dashboard
- Code : bouton `data-testid="garmin-see-dashboard"` → `navigate("/dashboard")`. Présent et correct au niveau code.
- **PASS/FAIL : NON TESTÉ en navigateur** (écran d'activation non atteignable sans identifiants Garmin + SSE non délivré via edge). Non auditable end-to-end dans cet environnement.

## 12. Worker / backend / frontend
- Worker (compte `da8505ef`) : **1 seul job par sync**, `sync_start`(attempt=1) → `sync_success status=complete` (~12,2–13,0 s). **1 seul** upsert snapshot + **1 seul** backfill par sync. **Aucun retry inattendu, aucun traceback**, `pending` supprimée, ACK OK. ✅
- Backend/front : compilent et tournent sans erreur.
- `_build_and_persist_capabilities` exécuté **2×/sync** (by design, sans gccli) — mineur.
- Bruit pré-existant : le scheduler enfile en boucle `INCREMENTAL_SYNC user=default` qui échoue `session_unavailable` (compte fantôme sans session, dès 2026-08-02) — **sans rapport avec PR07**.

## 13. Mesures réelles (sync warm, localhost SSE)
- sync trigger → **RunIndex ready** : **~306 ms** (statut) ; snapshot Mongo `run_index=235` persisté à +305 ms.
- sync trigger → **Readiness ready** : **~3 031 ms**.
- sync trigger → **complete** : **~12 351 ms**.
- (« Garmin connect → … » non mesurable : étape connect non exécutée.)

## 14. Anomalies classées
- **BLOQUANTE (UX preview)** — **A1** : SSE non délivré via l'edge preview (Cloudflare bufferise `text/event-stream`). L'onboarding ne recevrait aucun frame progressif en preview → écran d'activation figé. *Infra/edge, pas code app (localhost OK).*
- **IMPORTANTE** — **A2** : valeur RunIndex affichée = `"—"` (SSE ne fournit pas `run_index`, seulement `run_index_status`).
- **IMPORTANTE** — **A3** : valeur Readiness affichée = `"—"` (SSE ne fournit pas `readiness`).
- **IMPORTANTE** — **A4** : compteur d'activités non affiché (UI lit `synced_count`, absent du SSE ; le SSE fournit `activities_count`).
- **MINEURE** — **A5** : `_build_and_persist_capabilities` exécuté 2×/sync.
- **OBSERVATION** — **O1** : parcours navigateur interactif non exécutable (contraintes d'identifiants Garmin) → CTA Dashboard & rendu visuel non validés end-to-end. **O2** : bruit scheduler `user=default` pré-existant. **O3** (positif) : le stream Redis préserve les frames discrets `run_index_ready`/`readiness_ready`.

## 15. Verdict
Le mécanisme **phasé** (ordre `run_index_ready < readiness_ready < complete`, RunIndex prêt ~0,3 s, statuts corrects, stream livrant les frames discrets, worker propre) **fonctionne et respecte le critère principal PR07A**. En revanche, l'**activation d'onboarding PR07C** présente des écarts de contrat importants : les **valeurs** RunIndex/Readiness et le **compteur d'activités ne s'affichent pas** (`"—"` / 0) car le payload SSE ne transporte que les statuts, et le **SSE n'est pas délivré via l'edge preview** (Cloudflare buffering). Le parcours navigateur complet n'a pas pu être exercé (contrainte d'identifiants Garmin).

### **PR07C E2E = PASS WITH OBSERVATIONS**

(Le pipeline backend n'a pas de régression et n'est pas « bloqué derrière les daily metrics » → pas FAIL au sens du critère. Mais A1–A4 doivent faire l'objet d'une décision produit avant de considérer l'activation onboarding utilisable en preview.)

*STOP — aucune correction appliquée, conformément à la consigne.*
