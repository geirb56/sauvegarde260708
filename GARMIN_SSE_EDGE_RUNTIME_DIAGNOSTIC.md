# GARMIN_SSE_EDGE_RUNTIME_DIAGNOSTIC — PR07C.2 / A1

**Type** : diagnostic runtime uniquement. **Aucun code / config / PR** modifié. JWT masqué (`<JWT_MASKED>`).
**Date** : 2026-08-11 (UTC).

## HEAD testé
- **`9dafb27`** (branche `main`, inclut PR07A→PR07C + toolchain).

## URLs
- LOCALHOST : `http://localhost:8001/api/garmin/sync/stream` (auth `Bearer <JWT_MASKED>`)
- EDGE : `https://<preview-host>/api/garmin/sync/stream` (auth `Bearer <JWT_MASKED>`)

## Méthode
Même environnement, même endpoint, même JWT valide (compte WARM `da85…`). Comparaison de 4 combinaisons
(LOCAL/EDGE × `Accept-Encoding: identity`/`gzip`) via `curl -N -v` (headers) puis client de streaming
horodatant chaque frame, avec **déclenchement d'une sync Garmin réelle** pendant l'observation.

---

## Tableau headers — localhost vs edge
| Header | LOCAL identity | LOCAL gzip | EDGE identity | EDGE gzip |
|---|---|---|---|---|
| Status | `HTTP/1.1 200` | `HTTP/1.1 200` | `HTTP/2 200` | `HTTP/2 200` |
| Content-Type | `text/event-stream; charset=utf-8` | idem | idem | idem |
| **Content-Encoding** | *(absent)* | **`gzip`** | *(absent)* | **`gzip`** |
| Transfer-Encoding | `chunked` | `chunked` | *(non exposé HTTP/2)* | *(non exposé HTTP/2)* |
| Cache-Control | `no-cache` | `no-cache` | `no-store, no-cache, must-revalidate` | idem |
| Connection | `keep-alive` | `keep-alive` | *(non exposé HTTP/2)* | *(non exposé HTTP/2)* |
| **X-Accel-Buffering** | **`no`** | **`no`** | *(absent — strippé par l'edge)* | *(absent)* |
| Vary | *(absent)* | `Accept-Encoding` | `Accept-Encoding` | `Accept-Encoding` |
| Server / proxy | `uvicorn` | `uvicorn` | `cloudflare`, `via: 1.1 google`, `cf-ray`, `cf-cache-status: DYNAMIC` | idem |

> `X-Accel-Buffering: no` et `Cache-Control: no-cache` sont bien émis par l'app (visibles en localhost).
> L'edge (Cloudflare) réécrit `Cache-Control` et n'expose pas `X-Accel-Buffering`.

## Timings — première frame réellement reçue (sync réelle déclenchée pendant l'observation)
| Combinaison | 1er octet / `: connected` | 1re frame `sync_progress` | `run_index_ready` | `readiness_ready` | `complete` | Total frames en ~21 s |
|---|---|---|---|---|---|---|
| **LOCAL identity** | **~141 ms** | **~160 ms** | reçu (temps réel) | reçu | reçu | streaming immédiat |
| **LOCAL gzip** | **JAMAIS** (timeout) | — | — | — | — | **0** |
| **EDGE identity** | **JAMAIS** (timeout 8 s) | — | — | — | — | **0** |
| **EDGE gzip** | **JAMAIS** (timeout) | — | — | — | — | **0** |

## Premières lignes réellement reçues
- **LOCAL identity** :
  ```
  : connected
  id: snapshot
  event: sync_progress
  data: {"status":"complete","phase":"complete","run_index_status":"ready",...}
  ```
  (frames de sync suivantes livrées en temps réel — cf. validations PR07A/07C précédentes)
- **LOCAL gzip** : *(aucun octet de corps pendant ~21 s, y compris pendant une sync complète)*
- **EDGE identity / EDGE gzip** : *(aucun octet de corps)*

## Comportement pendant une sync réelle
- En **LOCAL identity**, les frames `activities_ready → run_index_ready → readiness_ready → complete`
  sont livrées progressivement en temps réel.
- En **LOCAL gzip** et **EDGE**, **aucune** frame n'est livrée même une fois la sync **terminée**
  (≥ 8 frames, > 1 KB cumulés) : le flux reste totalement retenu → bufferisation **totale**, pas un simple délai.

## Compression réellement présente ?
**OUI.** Dès que le client envoie `Accept-Encoding: gzip`, la réponse `text/event-stream` porte
`Content-Encoding: gzip` (visible en LOCAL gzip **et** EDGE gzip). Le flux SSE est donc réellement compressé.

## Localisation probable du buffering
**Le middleware `GZipMiddleware` de l'application** (`server.py:203` → `add_middleware(GZipMiddleware, minimum_size=1000)`).
Preuve : sur le **même serveur origin (localhost, sans edge)**, la seule variable qui bascule
« streaming instantané » ↔ « 0 frame » est l'en-tête `Accept-Encoding` :
- `identity` → pas de `Content-Encoding`, frames à ~141 ms ;
- `gzip` → `Content-Encoding: gzip`, **0 frame** (le compresseur n'est pas *flush* par frame et/ou retient
  les premiers `minimum_size` octets), donc les frames SSE ne sortent jamais.

Les navigateurs envoient **toujours** `Accept-Encoding: gzip` → le flux est retenu **à l'origine**,
avant même Cloudflare. Le cas `EDGE identity` échoue aussi car Cloudflare requête vraisemblablement
`gzip` en amont de l'origin (réécriture `Vary: Accept-Encoding` + `Content-Encoding: gzip` côté edge) —
mais **ce point edge n'est pas isolable proprement** ici (impossible de forcer l'Accept-Encoding
Cloudflare→origin sans modifier la config, interdit). Il est de toute façon **moot** : l'origin retient
déjà le flux pour tout client gzip.

## Classification
**Cas D** (avec composante A) : le problème est **également présent en localhost** dès `Accept-Encoding: gzip`
→ il faut regarder **l'implémentation backend SSE / la chaîne de middlewares** (et non uniquement l'edge).
L'edge n'est pas la cause première démontrée.

## Cause racine
**DÉMONTRÉE (in-repo)** : `GZipMiddleware(minimum_size=1000)` appliqué globalement compresse aussi les
réponses `text/event-stream` et ne *flush* pas par frame → les événements SSE sont retenus pour tout
client envoyant `Accept-Encoding: gzip` (tous les navigateurs). Reproduit sur localhost, sans edge.

## Correction possible dans le repo ?
**OUI** (à faire dans une **PR séparée** — non implémentée ici). Correction minimale envisagée :
**exclure les réponses `text/event-stream` de la compression GZip.** Options :
- ne pas appliquer `GZipMiddleware` aux routes SSE (`/api/garmin/sync/stream`, `/api/garmin/feed/stream`),
  p.ex. via un middleware conditionnel qui bypass quand `Content-Type == text/event-stream` ; ou
- monter les endpoints SSE sur un sous-app/routeur sans `GZipMiddleware`.
Aucune autre couche (X-Accel-Buffering déjà `no`, Cache-Control déjà `no-cache`) ne nécessite de changement.

## Recommandation (≤ 3 lignes)
1. Ouvrir **PR07C.2** : bypass GZip pour `text/event-stream` (ne pas toucher au reste de la config).
2. Re-tester : LOCAL gzip **et** EDGE gzip doivent livrer `: connected` + snapshot < ~200 ms.
3. Si l'edge continue de bufferiser *après* le fix origin, escalader alors seulement vers la config Cloudflare.

---

## VERDICT
# ROOT CAUSE CONFIRMED

*(Buffering démontré à l'origine par `GZipMiddleware` sur `text/event-stream` ; reproductible en localhost
sans edge. STOP — aucun code modifié, aucune PR.)*
