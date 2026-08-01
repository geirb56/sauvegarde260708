# Repository Inspection Summary

## Vue d’ensemble

Ce dépôt regroupe une application orientée sport/santé avec plusieurs couches techniques :
- un backend Python/FastAPI centré sur l’analyse, le coaching, l’authentification et les intégrations,
- un frontend React basé sur Create React App,
- une API et un worker Celery dédiés à une intégration Garmin/gccli,
- une infrastructure locale basée sur Docker Compose avec Redis et Postgres.

## Structure principale

- `/home/runner/work/sauvegarde260708/sauvegarde260708/api` : application FastAPI légère exposée via `api/main.py`.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/app` : bibliothèque applicative pour le vault de credentials, le runner gccli et les providers.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/backend` : backend principal avec services métier, auth, monitoring, sync, feed, jobs, engine et tests.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/frontend` : interface web React avec CRACO, Tailwind et composants UI.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/tasks` et `/home/runner/work/sauvegarde260708/sauvegarde260708/worker` : orchestration des tâches asynchrones Celery.
- `/home/runner/work/sauvegarde260708/sauvegarde260708/memory` : documentation interne et rapports techniques.

## Stack technique observée

### Backend Python
- FastAPI / Starlette / Uvicorn
- Celery, Redis
- Pydantic
- Pytest, Flake8, Black, Isort, Mypy
- Intégrations IA et data présentes dans les dépendances (`openai`, `google-genai`, `huggingface_hub`, `pandas`, `numpy`)

### Frontend
- React 19
- React Router 7
- CRACO
- Tailwind CSS
- Radix UI
- Axios, React Hook Form, Zod, Recharts

### Infrastructure locale
- `docker-compose.yml` démarre :
  - `api`
  - `worker`
  - `redis`
  - `postgres`

## Documentation existante notable

Le dépôt contient déjà plusieurs rapports et documents d’audit, notamment :
- `/home/runner/work/sauvegarde260708/sauvegarde260708/README.md`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/TROUBLESHOOTING.md`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/PRODUCTION_READINESS_REPORT.md`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/AUDIT_SECURITE.md`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/AUDIT_STRIPE_TO_PADDLE.md`
- `/home/runner/work/sauvegarde260708/sauvegarde260708/MULTI_USER_AUTH_MIGRATION_REPORT.md`

## Observations rapides

- Le dépôt mélange un socle d’intégration Garmin/gccli et une application plus large de coaching/analytics dans `backend`.
- Le `README.md` racine décrit surtout le squelette Garmin et ne couvre pas toute l’étendue du backend principal ni du frontend.
- Le frontend conserve un `README.md` standard Create React App, donc peu spécifique au produit.
- La présence de nombreux rapports Markdown suggère une base de travail déjà auditée sur les sujets sécurité, production, paiement et migration auth.

## Commandes et points d’entrée repérés

- Backend/API Docker : `uvicorn api.main:app --host 0.0.0.0 --port 8000 --proxy-headers`
- Worker : `celery -A tasks.sync_tasks worker --loglevel=info -Q SYNC_USER,FETCH_NEW_ACTIVITIES,PROCESS_ACTIVITY,COMPUTE_METRICS`
- Frontend :
  - `npm start`
  - `npm run build`
  - `npm test`

## Fichier créé

Ce résumé d’inspection a été ajouté dans :
- `/home/runner/work/sauvegarde260708/sauvegarde260708/REPOSITORY_INSPECTION_SUMMARY.md`
