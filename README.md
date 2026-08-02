# RunIndex

**RunIndex** est un coach course à pied intelligent (AI-powered), multiutilisateur. Il synchronise automatiquement les activités Garmin, calcule un score RunIndex (charge, récupération, HRV), génère des plans d'entraînement personnalisés et propose un coach conversationnel LLM.

---

## Stack technique

| Couche | Technologie |
|--------|-------------|
| Backend API | FastAPI (Python 3.11), MongoDB (Motor async), Redis |
| Authentification | JWT (PyJWT), OAuth Google/Apple |
| Workers asynchrones | `workers/sync_worker.py`, `scheduler_worker.py`, `event_worker.py` (Redis queue, at-least-once) |
| Intégration Garmin | gccli (CLI Garmin Connect, mono-compte phase actuelle) |
| Paiements | Paddle (webhooks signés) |
| LLM / Coach IA | OpenAI GPT via Emergent LLM Key, RAG maison |
| Frontend | React (Create React App + Craco), Tailwind CSS |
| Infrastructure | Docker Compose (MongoDB, Redis, API, Workers) |

---

## Prérequis

- **Docker** ≥ 24 et **Docker Compose** ≥ 2
- **Node.js** ≥ 18 (développement frontend)
- **Python** ≥ 3.11 (développement backend)
- Compte **Garmin Connect** (pour la synchronisation des activités)
- Compte **Paddle** (sandbox ou production) pour les paiements

---

## Variables d'environnement

Copier `.env.example` vers `backend/.env` (et `.env` pour Docker Compose) et remplir chaque valeur.  
Voir `.env.example` pour la liste complète commentée.

**Variables obligatoires au démarrage :**

| Variable | Description |
|----------|-------------|
| `MONGO_URL` | URI MongoDB (`mongodb://...`) |
| `DB_NAME` | Nom de la base de données |
| `JWT_SECRET_KEY` | Clé secrète JWT (≥ 32 caractères aléatoires) |
| `REDIS_URL` | URI Redis (`redis://...`) |
| `FRONTEND_URL` | URL publique du frontend (CORS strict en production) |
| `ENVIRONMENT` | `development` ou `production` |

---

## Démarrage local (Docker Compose)

```bash
# 1. Cloner et configurer les variables d'environnement
cp .env.example .env
# Éditer .env et remplir les valeurs (voir section Variables ci-dessus)

# 2. Lancer tous les services
docker compose up --build

# L'API est disponible sur http://localhost:8000
# La doc Swagger est sur http://localhost:8000/docs
```

### Développement backend (sans Docker)

```bash
cd backend
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Prérequis : MongoDB et Redis locaux (ou via Docker)
docker compose up -d mongo redis

# Copier les variables d'environnement
cp ../.env.example .env
# Éditer backend/.env

# Lancer l'API
uvicorn server:app --reload --port 8000

# Dans un autre terminal : lancer le sync worker
python -m workers.sync_worker
```

### Développement frontend

```bash
cd frontend
npm install
npm start
# Frontend disponible sur http://localhost:3000
```

---

## Démarrage en production

Voir [DEPLOYMENT.md](./DEPLOYMENT.md) pour la roadmap complète, les checklists go/no-go et les points d'attention (Garmin, secrets, CORS).

En résumé :

1. Injecter tous les secrets via un gestionnaire (Doppler, Vault, Docker Secrets) — jamais dans Git.
2. Mettre `ENVIRONMENT=production` — active le CORS strict et désactive le mode démo.
3. Configurer `TRUSTED_PROXY_COUNT` selon le nombre de reverse proxies/load balancers devant l'API.
4. Lancer `docker compose -f docker-compose.yml up -d`.
5. Vérifier le healthcheck : `GET /health`.

---

## Tests backend

```bash
cd backend
python -m pytest tests/ -v
```

---

## Architecture des services

```
frontend/ (React)
    │  HTTPS + JWT ******
backend/server.py  (FastAPI)
    ├── /api/auth/*          → JWT multi-user (Google/Apple OAuth)
    ├── /api/garmin/*        → sync Garmin, queue, healthcheck
    ├── /api/run-index       → score RunIndex (charge, récupération)
    ├── /api/coach/*         → coach LLM + RAG
    └── /api/webhook/paddle  → Paddle webhook (signé)
         │
    MongoDB (Motor async)    → activités, métriques, users, abonnements
    Redis                    → queue jobs, rate limiter, feed cache, SSE
         │
    workers/
    ├── sync_worker.py       → consomme la queue Redis, appelle gccli
    ├── scheduler_worker.py  → déclenche les syncs périodiques
    └── event_worker.py      → fan-out ACTIVITY_CREATED → workouts + feed
```

---

## Configuration OAuth (sans secrets dans Git)

Toutes les valeurs sensibles sont injectées **uniquement** via les variables d'environnement au runtime.

- Ne jamais committer `GOOGLE_CLIENT_SECRET`, clés privées Apple, tokens OAuth ou credentials Garmin.
- Les endpoints `/api/auth/google` et `/api/auth/apple` vérifient l'identité côté backend puis émettent le JWT RunIndex.
- En production, seul `FRONTEND_URL` est autorisé en CORS (`ENVIRONMENT=production`).
