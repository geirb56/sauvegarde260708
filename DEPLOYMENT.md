# RunIndex — Roadmap de déploiement

> Document opérationnel : phases, checklists go/no-go, points d'attention.  
> Dernière mise à jour : 2026-08-02

---

## Vue d'ensemble des phases

| Phase | Objectif | Statut |
|-------|----------|--------|
| **Phase 0** | Préparation infra & documentation | ✅ En cours |
| **Phase 1** | Staging fonctionnel (mono-compte Garmin) | 🔲 À démarrer |
| **Phase 2** | Production (multi-utilisateurs, Garmin multi-compte) | 🔲 Bloqué Phase 1 |
| **Phase 3** | Scale & observabilité | 🔲 Futur |

---

## Phase 0 — Préparation infra & documentation

### Objectifs
- Créer la branche `release/v1.0` à partir de `main`
- README opérationnel (stack, setup, variables)
- `.env.example` complet et commenté
- `docker-compose.yml` staging-ready (MongoDB, healthchecks, secrets propres)
- Ce fichier `DEPLOYMENT.md`

### Commandes

```bash
# Créer la branche release depuis main
git fetch origin main
git checkout -b release/v1.0 origin/main

# Vérifier l'état de l'environnement
cp .env.example .env
# Éditer .env — remplir les valeurs obligatoires
docker compose up --build
curl http://localhost:8000/health
```

### Checklist go/no-go Phase 0

- [ ] `README.md` décrit le projet, la stack et les instructions de démarrage
- [ ] `.env.example` contient toutes les variables (JWT, Mongo, Redis, Paddle, Garmin, LLM)
- [ ] `docker-compose.yml` : MongoDB (pas Postgres), healthchecks, volumes nommés, pas de mots de passe en dur
- [ ] `GET /health` répond `{"status": "ok"}` après `docker compose up`
- [ ] Aucun secret réel dans Git (`git log --all -p | grep -i "secret\|password\|key"`)

---

## Phase 1 — Staging fonctionnel

### Objectifs
- Déployer sur un environnement staging (VM, Railway, Render, ou VPS)
- Valider le flux complet : inscription → connexion Garmin → sync → RunIndex
- Activer Paddle en mode sandbox (webhooks signés)
- Valider les tests d'authentification multi-utilisateurs

### Prérequis
- MongoDB Atlas (M0 free tier suffisant) **ou** MongoDB auto-hébergé avec auth
- Redis (Upstash free tier **ou** Redis Cloud)
- Secrets injectés via Doppler / Vault (jamais en clair)
- Domaine + TLS (Let's Encrypt ou Cloudflare)

### Variables obligatoires pour le staging

```
ENVIRONMENT=production
MONGO_URL=mongodb+srv://...
DB_NAME=runindex_staging
JWT_SECRET_KEY=<openssl rand -hex 32>
REDIS_URL=redis://...
FRONTEND_URL=https://staging.runindex.app
TRUSTED_PROXY_COUNT=1
PADDLE_API_KEY=...
PADDLE_WEBHOOK_SECRET=...
PADDLE_ENVIRONMENT=sandbox
GARMIN_USERNAME=...
GARMIN_PASSWORD=...
EMERGENT_LLM_KEY=...
```

### Checklist go/no-go Phase 1

- [ ] `ENVIRONMENT=production` — CORS strict, demo mode bloqué
- [ ] Connexion MongoDB stable (ping < 100 ms)
- [ ] Redis accessible (PING → PONG)
- [ ] `GET /health` → 200
- [ ] Inscription utilisateur → JWT valide
- [ ] OAuth Google/Apple → session JWT
- [ ] Connexion compte Garmin → gccli bootstrap OK
- [ ] Sync manuel Garmin → activités en base MongoDB
- [ ] Calcul RunIndex → score non-null
- [ ] Webhook Paddle sandbox → signature vérifiée, abonnement créé
- [ ] Frontend accessible sur HTTPS avec TLS valide
- [ ] Logs sans credentials (grep "password\|secret" dans les logs Docker)

---

## Phase 2 — Production multi-utilisateurs

### Prérequis bloquants (voir `MULTI_USER_AUTH_MIGRATION_REPORT.md`)
- Migration Garmin multi-compte : chaque utilisateur dispose de son propre compte Garmin Connect (gccli multi-credential vault)
- Migration des `user_id="default"` restants en base MongoDB
- Tests de charge (≥ 100 utilisateurs simultanés)

### Points d'attention Garmin
- **gccli est actuellement mono-compte** : `GARMIN_USERNAME` et `GARMIN_PASSWORD` sont globaux.
- En production multi-utilisateurs, chaque utilisateur doit posséder son propre compte Garmin.
- Le credential vault (`app/credential_vault.py`) est conçu pour le multi-compte mais gccli ne supporte pas encore le changement de session à la volée.
- **Ne pas exposer** `GARMIN_USERNAME` / `GARMIN_PASSWORD` dans les logs ou les réponses API.
- La rotation des credentials Garmin doit se faire hors-bande (pas d'API dédiée pour l'instant).

### Checklist go/no-go Phase 2

- [ ] Zéro occurrence de `user_id="default"` dans les requêtes MongoDB actives
- [ ] gccli multi-compte validé (credential vault par utilisateur)
- [ ] Tests de charge : 100 syncs concurrents sans dégradation
- [ ] Backups MongoDB automatiques (Atlas ou mongodump CRON)
- [ ] Rate limiting Garmin : max 1 sync / 10 min / utilisateur (respect ToS Garmin)
- [ ] Alertes monitoring (uptime, latence p95, erreurs 5xx)

---

## Phase 3 — Scale & observabilité

- Kubernetes (ou Fly.io multi-region) pour API et workers
- Prometheus + Grafana pour les métriques (endpoint `/metrics` déjà prévu)
- Sentry pour le tracing d'erreurs backend et frontend
- CDN pour les assets statiques React
- Cache Redis L2 pour les calculs RunIndex (TTL 1 heure)

---

## Gestion des secrets

### Règles absolues
1. **Jamais** de secret dans Git (même dans un commit revert).
2. Utiliser un gestionnaire de secrets : Doppler, HashiCorp Vault, 1Password Secrets Automation, ou Docker Secrets.
3. Le module `backend/config/secrets.py` lit exclusivement `os.environ` — zéro code spécifique au gestionnaire.
4. Rotation : les secrets compromis doivent être révoqués **immédiatement** côté fournisseur, puis mis à jour dans le gestionnaire.

### Secrets critiques
| Variable | Rotation recommandée | Niveau de criticité |
|----------|----------------------|---------------------|
| `JWT_SECRET_KEY` | En cas de compromission (invalide tous les tokens) | 🔴 Critique |
| `PADDLE_WEBHOOK_SECRET` | Depuis le dashboard Paddle | 🔴 Critique |
| `PADDLE_API_KEY` | Depuis le dashboard Paddle | 🔴 Critique |
| `GARMIN_PASSWORD` | Dès changement de mot de passe Garmin | 🟠 Élevé |
| `EMERGENT_LLM_KEY` | Mensuelle (bonne pratique) | 🟠 Élevé |
| `MONGO_URL` | En cas de compromission | 🔴 Critique |

---

## Démarrage rapide staging (Docker Compose)

```bash
# Cloner le repo et créer la branche release
git clone https://github.com/geirb56/sauvegarde260708.git
cd sauvegarde260708
git checkout release/v1.0

# Configurer les secrets (jamais en clair — exemple avec Doppler)
doppler run -- docker compose up -d

# Vérifier les services
docker compose ps
curl http://localhost:8000/health

# Voir les logs
docker compose logs -f api
docker compose logs -f sync-worker
```

---

## Commandes utiles

```bash
# Vérifier qu'aucun secret ne traine dans Git
git log --all -p | grep -iE "(password|secret|api_key|token)" | grep -v "example\|placeholder\|VARIABLE"

# Générer un JWT_SECRET_KEY solide
openssl rand -hex 32

# Tester la connexion MongoDB depuis le container API
docker compose exec api python -c "import asyncio; from motor.motor_asyncio import AsyncIOMotorClient; ..."

# Vider la queue Redis en dev
docker compose exec redis redis-cli DEL runindex:garmin:queue
```
