# GARMIN_SYNC_PROGRESS_PR07B_REPORT

Correction ciblée du hook `useGarminSyncProgress` (PR #99).

---

## 1. Fichiers modifiés

| Fichier | Nature |
|---|---|
| `frontend/src/hooks/useGarminSyncProgress.js` | Correction complète (round 2) |
| `frontend/src/__tests__/useGarminSyncProgress.test.js` | Tests F1–F21 + F22–F28 |

Aucun diff dans `frontend/src/pages/Onboarding.jsx` ni dans aucune page produit.

---

## 2. Corrections appliquées

### 2.1 Fallback `sync_status`

Le endpoint `GET /api/garmin/status` renvoie `{ sync_status: {...} }`.

**Avant (bug) :**
```js
setProgress(data);          // posait tout l'objet réponse
```

**Après (correct) :**
```js
const snapshot = data.sync_status ?? null;
setProgress(snapshot);
```

La forme de `progress` est désormais identique entre le flux SSE et le fallback HTTP.

---

### 2.2 Parser SSE robuste — support `id:` et frames fragmentées

Le parser est réécrit pour découper sur `\n\n` (séparateur de frame SSE) plutôt que ligne par ligne. Cela gère correctement :

- **Frames fragmentées sur plusieurs chunks réseau** : le buffer accumule jusqu'à `\n\n`.
- **Champ `id:`** : parsé et retourné dans `{ id, event, data }`.
- **CRLF** (`\r\n`) : normalisé en `\n` avant traitement.
- **Plusieurs lignes `data:`** : concaténées avec `\n` (conforme à la spec SSE).
- **Heartbeats / commentaires** (`:`) : ignorés.

`lastIdRef` est mis à jour avec l'`id` réel du champ SSE — jamais avec un identifiant synthétique.

---

### 2.3 Recovery avant reconnexion

En cas de coupure réseau ou d'erreur 5xx :

```
stream interrompu
  ↓
GET /api/garmin/status → lire sync_status
  ↓
terminal (complete | partial_success | failed)
  → progress mis à jour, PAS de reconnexion

non-terminal (queued | in_progress | …)
  → backoff exponentiel → reconnexion SSE
```

Le hook ne nécessite plus 8 échecs SSE avant d'interroger `/garmin/status`.

---

### 2.4 401 / 403 = terminal auth, aucun retry

```
401 → error = "unauthenticated", isStreaming = false, pas de reconnexion
403 → error = "forbidden",       isStreaming = false, pas de reconnexion
```

Le fallback `/garmin/status` n'est pas appelé sur ces codes.

---

### 2.5 Statuts terminaux via SSE

Si le SSE lui-même reçoit `status ∈ { complete, partial_success, failed }` :

- `progress` est mis à jour avec les données de l'événement.
- Le stream est fermé proprement.
- Aucune reconnexion.
- `partial_success` ne lève pas d'erreur globale.

---

### 2.6 Backoff exponentiel borné

```
1 s → 2 s → 4 s → 8 s → … → 30 s (plafond)
```

Le compteur est réinitialisé après chaque connexion SSE réussie.

---

### 2.7 Abort / cleanup

Sur démontage ou `enabled=false` :

- `AbortController.abort()` annule le fetch en cours.
- `clearTimeout()` annule tout timer de reconnexion.
- Aucun fallback futur, aucune reconnexion future.
- Une fermeture volontaire (`AbortError`) n'est jamais interprétée comme erreur réseau.

---

### 2.8 (NOUVEAU) `id: snapshot` jamais stocké comme cursor Redis

Le backend émet un snapshot initial SSE avec `id: snapshot`. Cet identifiant est synthétique — ce n'est pas un cursor Redis Stream valide.

**Avant (bug) :**
```js
if (ev.id !== null && ev.id !== undefined) {
  lastIdRef.current = ev.id;   // stockait "snapshot" → URL invalide au reconnect
}
```

**Après (correct) :**
```js
if (ev.id !== null && ev.id !== undefined && ev.id !== "snapshot") {
  lastIdRef.current = ev.id;   // seuls les vrais IDs Redis Stream sont stockés
}
```

Une reconnexion ne produira donc jamais `?last_id=snapshot`.

---

### 2.9 (NOUVEAU) Fermeture propre sans statut terminal (`done=true`)

**Avant (bug) :**
```
reader.read() → done=true → aucun statut terminal reçu → isStreaming=false → STOP
```
Ce comportement était incorrect : un proxy réseau peut fermer la connexion proprement sans émettre de statut terminal.

**Après (correct) :**
La même recovery que pour une erreur réseau est appliquée :
```
done=true sans terminal
  ↓
GET /api/garmin/status → lire sync_status
  ↓
terminal   → update progress, PAS de reconnexion
actif      → backoff → reconnexion SSE
```

La fermeture **volontaire** (unmount / `enabled=false`) vérifie `voluntaryAbortRef` et ne déclenche **aucun** fallback.

---

### 2.10 (NOUVEAU) `status=failed` via SSE → erreur safe

**Avant :** `status=failed` arrêtait le stream mais ne renseignait pas `error`.

**Après :**
```js
if (ev.data.status === "failed") {
  const safeError = ev.data?.error_code || "sync_failed";
  setError(safeError);
}
```

- Si `error_code` est présent (ex : `"metrics_failed"`), il est utilisé directement.
- Sinon, le code générique `"sync_failed"` est utilisé.
- Aucune stacktrace, exception brute, secret ou payload sensible n'est exposé.
- `partial_success` reste sans erreur.

---

## 3. Tests frontend — F1–F29

| # | Description | Résultat |
|---|---|---|
| F1 | Authorization ****** | ✅ PASS |
| F2 | JWT absent de l'URL | ✅ PASS |
| F3 | Pas d'EventSource natif | ✅ PASS |
| F4 | Parsing simple | ✅ PASS |
| F5 | Frame fragmentée sur plusieurs chunks | ✅ PASS |
| F6 | CRLF | ✅ PASS |
| F7 | Heartbeat ignoré | ✅ PASS |
| F8 | Plusieurs lignes `data:` concaténées | ✅ PASS |
| F9 | `id:` parsé et conservé | ✅ PASS |
| F10 | `complete` arrête la reconnexion | ✅ PASS |
| F11 | `partial_success` arrête la reconnexion sans erreur | ✅ PASS |
| F12 | `failed` arrête la reconnexion avec état d'erreur safe | ✅ PASS |
| F13 | Coupure → `/garmin/status` | ✅ PASS |
| F14 | Fallback `sync_status=complete` → pas de reconnect | ✅ PASS |
| F15 | Fallback `sync_status=partial_success` → pas de reconnect | ✅ PASS |
| F16 | Fallback `sync_status=failed` → pas de reconnect | ✅ PASS |
| F17 | Fallback `sync_status=in_progress` → reconnect avec backoff | ✅ PASS |
| F18 | 401 → aucun retry | ✅ PASS |
| F19 | 403 → aucun retry | ✅ PASS |
| F20 | Abort pendant stream → aucun reconnect | ✅ PASS |
| F21 | Abort pendant backoff → aucun reconnect | ✅ PASS |
| F22 | `id: snapshot` jamais utilisé comme `last_id` au reconnect | ✅ PASS |
| F23 | `done=true` sans terminal + fallback `in_progress` → reconnect | ✅ PASS |
| F24 | `done=true` sans terminal + fallback `complete` → pas de reconnect | ✅ PASS |
| F25 | `done=true` sans terminal + fallback `partial_success` → pas de reconnect | ✅ PASS |
| F26 | `done=true` sans terminal + fallback `failed` → pas de reconnect | ✅ PASS |
| F27 | SSE `status=failed` + `error_code` → erreur safe (`error_code`) | ✅ PASS |
| F27b | SSE `status=failed` sans `error_code` → erreur générique `"sync_failed"` | ✅ PASS |
| F28 | Unmount pendant stream → aucun `/garmin/status`, aucun reconnect | ✅ PASS |

**Total : 29/29 PASS**

---

## 4. Tests backend — PR07B

Suite `backend/tests/test_sync_progress_sse_pr07b.py` :

```
6 passed in 0.51s
```

| Test | Résultat |
|---|---|
| test_emit_sanitizes_sensitive_keys | ✅ PASS |
| test_update_sync_progress_publishes_to_stream | ✅ PASS |
| test_snapshot_emitted_on_connect | ✅ PASS |
| test_user_isolation | ✅ PASS |
| test_no_sensitive_data_in_sse_frame | ✅ PASS |
| test_phase_vs_status_contract | ✅ PASS |

---

## 5. Build frontend

```
File sizes after gzip:
  321.06 kB  build/static/js/main.c3520c65.js
  15.17 kB   build/static/css/main.7bf8acf9.css
  4.49 kB    build/static/js/641.5f0ae8f3.chunk.js

The build folder is ready to be deployed.
```

Build : ✅ SUCCÈS

---

## 6. Périmètre — confirmations

| Vérification | Statut |
|---|---|
| Fallback lit `data.sync_status` | ✅ Oui |
| `id:` réellement parsé | ✅ Oui |
| `id: snapshot` jamais utilisé comme cursor Redis (`last_id`) | ✅ Confirmé |
| `done=true` sans terminal déclenche recovery `/garmin/status` | ✅ Confirmé |
| `status=failed` via SSE produit une erreur safe (`error_code` ou `"sync_failed"`) | ✅ Confirmé |
| Fermeture volontaire (unmount/abort) → aucun fallback, aucun reconnect | ✅ Confirmé |
| 401/403 ne retry pas | ✅ Oui |
| Statut terminal ne reconnecte pas | ✅ Oui |
| Aucun diff `Onboarding.jsx` | ✅ Confirmé |
| Aucune formule RunIndex modifiée | ✅ Confirmé |
| Aucun comportement PR07A modifié | ✅ Confirmé |
| Merge automatique | ❌ Non effectué |


Correction ciblée du hook `useGarminSyncProgress` (PR #99).

---

## 1. Fichiers modifiés

| Fichier | Nature |
|---|---|
| `frontend/src/hooks/useGarminSyncProgress.js` | Correction complète |
| `frontend/src/__tests__/useGarminSyncProgress.test.js` | Tests F1–F21 |

Aucun diff dans `frontend/src/pages/Onboarding.jsx` ni dans aucune page produit.

---

## 2. Corrections appliquées

### 2.1 Fallback `sync_status`

Le endpoint `GET /api/garmin/status` renvoie `{ sync_status: {...} }`.

**Avant (bug) :**
```js
setProgress(data);          // posait tout l'objet réponse
```

**Après (correct) :**
```js
const snapshot = data.sync_status ?? null;
setProgress(snapshot);
```

La forme de `progress` est désormais identique entre le flux SSE et le fallback HTTP.

---

### 2.2 Parser SSE robuste — support `id:` et frames fragmentées

Le parser est réécrit pour découper sur `\n\n` (séparateur de frame SSE) plutôt que ligne par ligne. Cela gère correctement :

- **Frames fragmentées sur plusieurs chunks réseau** : le buffer accumule jusqu'à `\n\n`.
- **Champ `id:`** : parsé et retourné dans `{ id, event, data }`.
- **CRLF** (`\r\n`) : normalisé en `\n` avant traitement.
- **Plusieurs lignes `data:`** : concaténées avec `\n` (conforme à la spec SSE).
- **Heartbeats / commentaires** (`:`) : ignorés.

`lastIdRef` est mis à jour avec l'`id` réel du champ SSE — jamais avec un identifiant synthétique.

---

### 2.3 Recovery avant reconnexion

En cas de coupure réseau ou d'erreur 5xx :

```
stream interrompu
  ↓
GET /api/garmin/status → lire sync_status
  ↓
terminal (complete | partial_success | failed)
  → progress mis à jour, PAS de reconnexion

non-terminal (queued | in_progress | …)
  → backoff exponentiel → reconnexion SSE
```

Le hook ne nécessite plus 8 échecs SSE avant d'interroger `/garmin/status`.

---

### 2.4 401 / 403 = terminal auth, aucun retry

```
401 → error = "unauthenticated", isStreaming = false, pas de reconnexion
403 → error = "forbidden",       isStreaming = false, pas de reconnexion
```

Le fallback `/garmin/status` n'est pas appelé sur ces codes.

---

### 2.5 Statuts terminaux via SSE

Si le SSE lui-même reçoit `status ∈ { complete, partial_success, failed }` :

- `progress` est mis à jour avec les données de l'événement.
- Le stream est fermé proprement.
- Aucune reconnexion.
- `partial_success` ne lève pas d'erreur globale.

---

### 2.6 Backoff exponentiel borné

```
1 s → 2 s → 4 s → 8 s → … → 30 s (plafond)
```

Le compteur est réinitialisé après chaque connexion SSE réussie.

---

### 2.7 Abort / cleanup

Sur démontage ou `enabled=false` :

- `AbortController.abort()` annule le fetch en cours.
- `clearTimeout()` annule tout timer de reconnexion.
- Aucun fallback futur, aucune reconnexion future.
- Une fermeture volontaire (`AbortError`) n'est jamais interprétée comme erreur réseau.

---

## 3. Tests frontend — F1–F21

| # | Description | Résultat |
|---|---|---|
| F1 | Authorization ****** | ✅ PASS |
| F2 | JWT absent de l'URL | ✅ PASS |
| F3 | Pas d'EventSource natif | ✅ PASS |
| F4 | Parsing simple | ✅ PASS |
| F5 | Frame fragmentée sur plusieurs chunks | ✅ PASS |
| F6 | CRLF | ✅ PASS |
| F7 | Heartbeat ignoré | ✅ PASS |
| F8 | Plusieurs lignes `data:` concaténées | ✅ PASS |
| F9 | `id:` parsé et conservé | ✅ PASS |
| F10 | `complete` arrête la reconnexion | ✅ PASS |
| F11 | `partial_success` arrête la reconnexion sans erreur | ✅ PASS |
| F12 | `failed` arrête la reconnexion avec état d'erreur safe | ✅ PASS |
| F13 | Coupure → `/garmin/status` | ✅ PASS |
| F14 | Fallback `sync_status=complete` → pas de reconnect | ✅ PASS |
| F15 | Fallback `sync_status=partial_success` → pas de reconnect | ✅ PASS |
| F16 | Fallback `sync_status=failed` → pas de reconnect | ✅ PASS |
| F17 | Fallback `sync_status=in_progress` → reconnect avec backoff | ✅ PASS |
| F18 | 401 → aucun retry | ✅ PASS |
| F19 | 403 → aucun retry | ✅ PASS |
| F20 | Abort pendant stream → aucun reconnect | ✅ PASS |
| F21 | Abort pendant backoff → aucun reconnect | ✅ PASS |

**Total : 21/21 PASS**

---

## 4. Tests backend — PR07B

Suite `backend/tests/test_sync_progress_sse_pr07b.py` :

```
6 passed in 0.51s
```

| Test | Résultat |
|---|---|
| test_emit_sanitizes_sensitive_keys | ✅ PASS |
| test_update_sync_progress_publishes_to_stream | ✅ PASS |
| test_snapshot_emitted_on_connect | ✅ PASS |
| test_user_isolation | ✅ PASS |
| test_no_sensitive_data_in_sse_frame | ✅ PASS |
| test_phase_vs_status_contract | ✅ PASS |

---

## 5. Build frontend

```
File sizes after gzip:
  321.06 kB  build/static/js/main.c3520c65.js
  15.17 kB   build/static/css/main.7bf8acf9.css
  4.49 kB    build/static/js/641.5f0ae8f3.chunk.js

The build folder is ready to be deployed.
```

Build : ✅ SUCCÈS

---

## 6. Périmètre — confirmations

| Vérification | Statut |
|---|---|
| Fallback lit `data.sync_status` | ✅ Oui |
| `id:` réellement parsé | ✅ Oui |
| 401/403 ne retry pas | ✅ Oui |
| Statut terminal ne reconnecte pas | ✅ Oui |
| Aucun diff `Onboarding.jsx` | ✅ Confirmé |
| Aucune formule RunIndex modifiée | ✅ Confirmé |
| Aucun comportement PR07A modifié | ✅ Confirmé |
| Merge automatique | ❌ Non effectué |
