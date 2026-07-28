# Test Credentials — RunIndex

## Auth JWT (PR22 — multi-user)
- Endpoint base: `/api/auth`
- Compte de test créé le 2026-07-28 (register via API) :
  - email: `testrunner@runindex.app`
  - password: `Test1234!`
  - user id (UUID): `08cafe9d-5c16-4fbb-86ae-591672a386ee`
- JWT_SECRET_KEY : configuré dans backend/.env (secret aléatoire généré, ne pas exposer).

## Données legacy
- Toutes les données historiques (141 activités Garmin, RunIndex, plan, abonnement trial) sont sous `user_id = "default"`.
- Accessibles côté backend via header `X-User-Id: default` ou `?user_id=default` (fallback legacy encore présent).
- ⚠️ Un compte JWT nouvellement créé ne voit PAS ces données (migration non faite).
