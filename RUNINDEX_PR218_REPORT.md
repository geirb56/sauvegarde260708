# RUNINDEX PR218 — A36 GLOBAL GARMIN BACKFILL SECURITY

## Base

| Field | Value |
|---|---|
| Repo | https://github.com/geirb56/sauvegarde260708 |
| Branche source | `copilot/dev` |
| SHA départ réel | `8f2a9f4f370fac698ee3ea21dbed35e0b9c571c7` |
| Branche PR réelle | `copilot/pr218-garmin-backfill-admin-only` |
| SHA final réel | *(voir git log après merge)* |

---

## Finding

### A36 — P0 SECURITY

**Route :** `POST /api/garmin/backfill?scope=all`  
**Fichier :** `backend/api/garmin.py` — handler `garmin_backfill_endpoint`

---

## Cause racine

L'endpoint `/api/garmin/backfill` acceptait le paramètre `scope=all` sans vérifier
si l'utilisateur authentifié était administrateur. Toute personne ayant un JWT valide
pouvait déclencher `backfill_connected_users_run_index_history(db)`, une opération
d'écriture globale multi-utilisateur qui recalcule les snapshots RunIndex de **tous**
les utilisateurs Garmin connectés.

---

## Comportement avant

```
NORMAL USER (JWT valide)
  → POST /api/garmin/backfill?scope=all
  → HTTP 200
  → asyncio.create_task(backfill_connected_users_run_index_history(db))
  → réécriture des snapshots RunIndex de TOUS les utilisateurs Garmin
```

---

## Comportement après

```
NORMAL USER (JWT valide, non-admin)
  → POST /api/garmin/backfill?scope=all
  → HTTP 403 {"detail": "Admin access required for global backfill"}
  → aucune tâche globale créée
  → aucune écriture multi-user déclenchée

ADMIN (JWT valide, email dans ADMIN_EMAILS ou role=admin en DB)
  → POST /api/garmin/backfill?scope=all
  → HTTP 200 {"status": "started", "scope": "all"}
  → opération globale autorisée

NORMAL USER (JWT valide)
  → POST /api/garmin/backfill (scope=user par défaut)
  → HTTP 200 {"status": "ok", ...}
  → backfill strictement limité à son propre user_id

UNAUTHENTICATED
  → POST /api/garmin/backfill?scope=all (sans JWT)
  → HTTP 401/403
  → aucune opération
```

---

## Données potentiellement affectées

Le backfill global (`backfill_connected_users_run_index_history`) itère sur **tous**
les utilisateurs Garmin connectés et pour chacun :

- Recalcule et réécrit les snapshots `run_index_history` (granularité hebdomadaire
  et mensuelle) dans la collection MongoDB `run_index_history`
- Appelle `garmin_backfill.backfill_user` qui reconstruit la collection `workouts`
  depuis `garmin_activities` et rewarme le cache feed Redis
- Invalide le cache `dashboard_insight_cache` de chaque utilisateur

Un utilisateur non-admin pouvait donc provoquer une réécriture de masse sur
l'ensemble de la base `run_index_history` + `workouts`.

---

## Patch

**Fichier modifié :** `backend/api/garmin.py`

Ajout de l'import `HTTPException` et `status` depuis FastAPI, et ajout d'une
vérification admin avant l'exécution du backfill global :

```python
# Avant
if scope == "all":
    asyncio.create_task(backfill_connected_users_run_index_history(db))
    return {"status": "started", "scope": "all"}

# Après
if scope == "all":
    if not user.get("is_admin"):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Admin access required for global backfill",
        )
    asyncio.create_task(backfill_connected_users_run_index_history(db))
    return {"status": "started", "scope": "all"}
```

Le mécanisme admin canonique est `user.get("is_admin")`, qui est résolu par
`auth.dependencies.get_current_user` via `auth.roles.is_admin_user(user)`.
Aucune nouvelle logique RBAC n'a été ajoutée.

---

## Tests

**Fichier :** `backend/tests/test_garmin_backfill_admin_pr218.py`  
**7 tests ajoutés et exécutés réellement.**

### Commande exacte

```
cd backend/
python -m pytest tests/test_garmin_backfill_admin_pr218.py -v
```

### Résultats exacts

```
platform linux -- Python 3.12.3, pytest-9.1.1, pluggy-1.6.0
plugins: anyio-4.14.2, asyncio-1.4.0, xdist-3.8.0

tests/test_garmin_backfill_admin_pr218.py::test_unauthenticated_scope_all_rejected     PASSED
tests/test_garmin_backfill_admin_pr218.py::test_normal_user_scope_all_forbidden         PASSED
tests/test_garmin_backfill_admin_pr218.py::test_normal_user_scope_all_no_userb_mutation PASSED
tests/test_garmin_backfill_admin_pr218.py::test_normal_user_own_scope_allowed           PASSED
tests/test_garmin_backfill_admin_pr218.py::test_admin_scope_all_allowed                 PASSED
tests/test_garmin_backfill_admin_pr218.py::test_forged_admin_role_in_body_rejected      PASSED
tests/test_garmin_backfill_admin_pr218.py::test_user_a_cannot_backfill_user_b           PASSED

7 passed in 1.39s
```

### Couverture

| Test | Cas | Résultat |
|---|---|---|
| TEST 1 | Unauthenticated + scope=all | 401 — global job: `not_called` ✅ |
| TEST 2 | USER_A normal + scope=all | 403 — global job: `not_called` ✅ |
| TEST 2b | USER_A normal + scope=all + isolation USER_B | 403 — backfill_user(USER_B): `not_called` ✅ |
| TEST 3 | USER_A normal + scope=user (défaut) | 200 — backfill_user appelé uniquement pour USER_A ✅ |
| TEST 4 | ADMIN + scope=all | 200 — tâche globale créée ✅ |
| TEST 5 | Forged role=admin / is_admin=true (query param) | 403 — global job: `not_called` ✅ |
| TEST 6 | USER_A ne peut jamais backfill USER_B | backfill_user uniquement USER_A ✅ |

### Isolation USER_A / USER_B / ADMIN

Trois utilisateurs distincts dans chaque test :
- `USER_A` (non-admin) — `usera@test.com`
- `USER_B` (non-admin) — `userb@test.com`
- `ADMIN` — `admin@test.com` (dans `ADMIN_EMAILS`)

USER_A avec scope=all → 403, `backfill_connected_users_run_index_history` non appelé,
`backfill_user` non appelé avec `USER_B_ID`.

ADMIN avec scope=all → 200, tâche créée.

---

## Scope

**A36 corrigé :** oui.  
**A55 (attribution rôle admin via ADMIN_EMAILS avant vérification d'identité) :** non corrigé, réservé pour PR219 comme demandé.

La vérification utilise le mécanisme canonique existant (`is_admin_user` via
`resolve_user_role` dans `auth/roles.py`). Aucun nouveau système RBAC introduit.

---

## Runtime

| Couche | Statut |
|---|---|
| **Code statique** | Patch appliqué et vérifié dans `backend/api/garmin.py` |
| **Tests automatisés** | 7/7 PASSED — exécutés réellement dans ce contexte sandbox |
| **Runtime production** | Non vérifié — backend nécessite MongoDB + Redis actifs |

Les tests utilisent un `httpx.AsyncClient` avec `ASGITransport` sur une app FastAPI
minimale avec une fausse base de données en mémoire. Ils ne constituent **pas** une
validation runtime production.

---

## Callers de garmin/backfill

Recherche de `garmin/backfill` dans le projet :

- `backend/api/garmin.py` — route principale (patchée)
- `backend/garmin/service.py` — appels internes depuis le worker (scope user individuel uniquement, non affecté)
- Aucun caller frontend trouvé
- Aucun script externe trouvé

---

## Verdict

**READY FOR AUDIT**

Étape suivante : C218 — audit indépendant de #218 avant merge.
