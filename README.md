# CardioCoach - Garmin gccli integration skeleton

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
