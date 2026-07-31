# Rapport complet — Pull PR #41 (fix: restore FREE→Garmin onboarding + one-time trial eligibility)
_Date : 2026-07-31 — audit en lecture seule. Branche : `copilot/fix-trial-garmin-funnel-free-to-trial` → `PR34`. Mergée le 2026-07-30 par `geirb56`._

---

## 1. Ce qui a été récupéré

- **PR #41** — HEAD `ba1f81f` — *fix: restore FREE→Garmin onboarding and enforce one-time Garmin trial eligibility*
- **2 commits** :
  - `f9206bf` — fix: restore garmin free funnel and server-side trial eligibility
  - `ba1f81f` — test: harden garmin trial flow unit stubs
- **Ampleur** : +224 / −190 lignes, 8 fichiers

### Fichiers modifiés
| Fichier | Nature | +/− |
|---|---|---|
| `backend/access_control.py` | Reclassification endpoints Garmin FREE | +4 |
| `backend/garmin/bootstrap.py` | Ajustement bootstrap | +2 / −2 |
| `backend/garmin/providers/gccli_provider.py` | Suppression blocs dupliqués | +2 / −125 |
| `backend/garmin/runner.py` | Ajustement mineur | +1 / −1 |
| `backend/garmin/service.py` | Reconnexion flow trial + durcissement logs | +28 |
| `backend/subscription_manager.py` | Nouveau modèle d'identité trial (email serveur) | +22 / −17 |
| `backend/tests/test_garmin_connect_trial_flow.py` | **Nouveau** — tests flow trial complets | +127 |
| `backend/tests/test_garmin_trial_eligibility.py` | Mise à jour tests éligibilité trial | +38 / −45 |

---

## 2. Changements fonctionnels

### 2a. Contrôle d'accès — déblocage du funnel FREE→Garmin
Trois endpoints Garmin réclassifiés de `PREMIUM` vers `FREE` dans `backend/access_control.py` :
- `POST /api/garmin/connect`
- `GET /api/garmin/status`
- `POST /api/garmin/disconnect`

Le reste de `/api/garmin/` reste `PREMIUM` (données, métriques, activités).

**Avant PR41** : les utilisateurs FREE étaient bloqués dès la connexion Garmin → funnel trial cassé.  
**Après PR41** : onboarding Garmin accessible à tous ; les fonctionnalités premium restent protégées.

### 2b. Activation trial — flow reconnecté
Dans `backend/garmin/service.py`, sur succès de connexion Garmin :
```python
profile = provider.get_profile(user_id)  # GCCLI auth status — source de vérité
garmin_identity = str(profile["email"]).strip().lower()
await activate_garmin_trial(db, user_id, garmin_identity)
```
L'identité Garmin pour le trial est désormais dérivée côté serveur (profil GCCLI), **jamais** du frontend.

### 2c. Modèle d'identité trial — server-only, email normalisé
Dans `backend/subscription_manager.py` :
- Identité = email extrait de `gccli auth status` (normalisé : `strip().lower()`).
- Mécanisme "first claim wins" via `find_one_and_update + $setOnInsert` + `trial_claim_token` : atomique, une seule attribution par compte Garmin.
- En cas de reconnexion : pas de nouveau trial pour la même identité Garmin.
- Si pas d'abonnement existant pour un perdant : création d'un abonnement FREE fail-safe.

### 2d. Durcissement des logs sensibles
Suppression de la sortie PTY/GCCLI brute sur les surfaces d'échec d'auth. Remplacement par messages génériques pour éviter les fuites de credentials/tokens.

### 2e. Nettoyage provider
Suppression de blocs de méthodes dupliqués dans `backend/garmin/providers/gccli_provider.py` (−125 lignes) sans modification du comportement du provider.

---

## 3. Couverture de tests

| Scénario ajouté/modifié | Fichier |
|---|---|
| Classification FREE des routes onboarding Garmin | `test_garmin_connect_trial_flow.py` |
| Normalisation de l'identité email (collisions) | `test_garmin_connect_trial_flow.py` |
| Résistance au spoofing frontend pour l'identité trial | `test_garmin_connect_trial_flow.py` |
| Trial one-time + comportement concurrentiel | `test_garmin_connect_trial_flow.py` |
| Redaction des logs sensibles | `test_garmin_connect_trial_flow.py` |
| Scénarios d'éligibilité trial Garmin (précédemment bloqués) | `test_garmin_trial_eligibility.py` |

---

## 4. Points soulevés par la revue automatique (non résolus à la merge)

### ⚠️ Issue 1 — `backend/subscription_manager.py` ligne 61
> La docstring de module (et le texte de `NotImplementedError` dans `activate_garmin_trial`) contredit le nouveau modèle email dérivé côté serveur : elle indique encore que l'identité Garmin est indisponible / ne doit PAS être basée sur l'email.

**Impact** : risque de confusion pour les mainteneurs futurs.  
**Correctif recommandé** : mettre à jour la docstring et le message `NotImplementedError` pour documenter le modèle d'identité server-side actuel.

### ⚠️ Issue 2 — `backend/garmin/service.py` ligne 81
> Le gestionnaire d'exception large (`except Exception`) autour de l'activation trial avale toutes les erreurs (y compris les annulations de requête) et ne logue que la classe d'exception, rendant le debug en production difficile.

**Impact** : perte d'observabilité sur les échecs de trial ; les `asyncio.CancelledError` ne sont pas repropagées.  
**Correctif recommandé** : re-propager `asyncio.CancelledError`, et journaliser uniquement le nom de la classe d'exception (déjà fait) mais sans avaler silencieusement les annulations.

---

## 5. Ce qui fonctionne après PR41

| Fonctionnalité | État |
|---|---|
| Funnel FREE → connexion Garmin | ✅ Restauré |
| Activation trial côté serveur | ✅ Reconnectée |
| Identité trial = email GCCLI (server-only) | ✅ Implémentée |
| One-time trial (même compte Garmin) | ✅ Garanti atomiquement |
| Résistance spoofing frontend | ✅ |
| Suppression blocs dupliqués provider | ✅ |
| Logs sensibles GCCLI nettoyés | ✅ |
| Tests trial flow + éligibilité | ✅ |

---

## 6. Ce qui reste à faire

1. **Corriger la docstring** de `backend/subscription_manager.py` pour refléter le modèle email server-side (issue revue #1).
2. **Affiner le gestionnaire d'exception** dans `backend/garmin/service.py` pour re-propager `CancelledError` (issue revue #2).
3. **Garmin multi-compte** (GCCLI_HOME par user) : toujours en attente (non adressé par cette PR).
4. **Durcissement auth** (refresh token, rate-limit) : toujours en attente.
5. **Migration données `default`** : toujours en attente.

---

## 7. État global

| Axe | État |
|---|---|
| Funnel FREE→Garmin | ✅ Restauré |
| Sécurité trial (server-side identity) | ✅ |
| Atomicité one-time trial | ✅ |
| Observabilité exceptions | ⚠️ À améliorer (issue #2) |
| Docstring cohérente | ⚠️ À corriger (issue #1) |
| Garmin multi-compte (par user) | ⏳ Non adressé |
| Auth durcissement | ⏳ Non adressé |
