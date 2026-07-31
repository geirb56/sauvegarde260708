# RunIndex - Garmin gccli integration skeleton

Ce dépôt contient un squelette pour l'intégration backend de Garmin via gccli.
Le design respecte le Provider Pattern, un vault de credentials chiffré, Celery workers et une couche d'exécution gccli isolée.

Structure clé:
- app/: librairie applicative (providers, credential vault, gccli runner)
- api/: FastAPI app
- worker/: Celery worker (tasks import)
- tasks/: Celery task definitions
- docker-compose.yml: services api, worker, redis, postgres

Important: configurez MASTER_KEY (base64) dans vos secrets, REDIS_URL et DATABASE_URL.

Voir README pour instructions de démarrage.

## Configuration OAuth (sans secrets dans Git)

Configurer uniquement via variables d’environnement au runtime.

Backend:

- `GOOGLE_CLIENT_ID=`
- `APPLE_CLIENT_ID=`
- `JWT_SECRET_KEY=`

Frontend:

- `REACT_APP_BACKEND_URL=`
- `REACT_APP_GOOGLE_CLIENT_ID=`
- `REACT_APP_APPLE_CLIENT_ID=`
- `REACT_APP_APPLE_REDIRECT_URI=`

Notes:

- This OAuth implementation validates Google and Apple ID tokens server-side and only requires the client IDs above at runtime.
- Do not commit `GOOGLE_CLIENT_SECRET`, Apple private keys, or any real OAuth secret to Git.
- Ne pas committer de client secret, private key, token OAuth ou credentials réels.
- Les endpoints `/api/auth/google` et `/api/auth/apple` vérifient l’identité côté backend puis émettent le JWT RunIndex.
