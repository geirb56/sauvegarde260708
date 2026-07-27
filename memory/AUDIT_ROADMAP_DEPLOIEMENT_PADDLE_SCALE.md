# 🗺️ AUDIT & ROADMAP — RunIndex

> Généré le 2026-07-27

---

## 📋 ÉTAT ACTUEL — Audit du code

### Architecture
L'application est une **SPA React + backend FastAPI (Python)** avec :
- **BDD** : MongoDB (via Motor async) — pas Postgres (le docker-compose contient Postgres mais le code n'utilise QUE Mongo)
- **Cache/Queue** : Redis
- **Workers** : Workers async maison (sync_worker, scheduler_worker, event_worker) — Celery est présent dans `tasks/` mais la logique principale est dans `workers/`
- **LLM** : GPT-4.1-mini via `emergentintegrations` (clé `EMERGENT_LLM_KEY`)
- **Paiement** : Stripe via `emergentintegrations.payments.stripe` (lib wrapper maison)
- **Garmin** : Intégration via `gccli` (CLI externe) + Terra API en parallèle
- **Frontend** : React 19, Radix UI, Tailwind CSS, React Router v7

---

### 🔴 Dette technique / Problèmes identifiés

**Infrastructure :**
1. **docker-compose.yml incohérent** : déclare Postgres mais le code utilise MongoDB. L'API (`api/`) référence Postgres et Celery, le backend principal (`backend/`) utilise Mongo et des workers async. Deux architectures coexistent.
2. **DEMO_MODE en production** : le flag `DEMO_MODE=true` bypasse tous les checks de subscription. Risque de laisser ce flag actif par erreur.
3. **Pas de fichier `.env.example`** : aucun template des variables d'environnement requises → setup manuel risqué.
4. **USER_ID hardcodé** : `const USER_ID = "default"` dans `Subscription.jsx` (et probablement ailleurs). Pas d'authentification utilisateur réelle dans le frontend.
5. **`MONGO_URL` requis au démarrage** mais pas de gestion de reconnexion.

**Paiement (Stripe actuel) :**
6. **Deux systèmes Stripe parallèles** : `/api/premium/checkout` (server.py ~l.4647) ET `/api/subscription/early-adopter/checkout` (~l.5395) avec deux webhooks séparés. Duplication et risque de désynchronisation.
7. **Vérification webhook absente en production** : le code commente `# En production, cela serait vérifié via l'API Stripe` (~l.5535). Les webhooks ne sont pas validés cryptographiquement → **faille de sécurité critique**.
8. **`stripe_customer_id`/`stripe_subscription_id`** stockés en clair dans MongoDB — OK mais à documenter.

**Scalabilité :**
9. **`MAX_CONCURRENCY = 5`** par défaut dans le sync_worker — largement insuffisant pour 1000 users actifs.
10. **Pas de rate-limiting API** côté FastAPI (aucun middleware `slowapi` ou équivalent visible).
11. **Cache in-process** (`_workout_cache`, `_weekly_cache` dans `coach_service.py`) : dictionnaires Python en mémoire. Ne scale pas sur plusieurs instances.
12. **Indexation MongoDB incomplète** : indexes créés au démarrage (`server.py:5583`) mais leur exhaustivité n'est pas vérifiée.

**Sécurité :**
13. **`MASTER_KEY` pour le credential vault** : critique, doit être rotatable sans downtime.
14. **Pas de CORS strict visible** dans le code analysé.

---

## 🏗️ ROADMAP EN 3 PHASES

---

### PHASE 1 — Déploiement Prod (prerequisite à tout le reste)
*Objectif : avoir une version déployée, stable et sécurisée*

#### 1.1 Nettoyage de l'infrastructure
- Choisir une architecture : **soit** garder `api/` (Postgres + Celery), **soit** garder `backend/` (Mongo + workers async) → **recommandé : `backend/` qui est nettement plus abouti**
- Supprimer la référence Postgres du `docker-compose.yml` et aligner sur MongoDB Atlas (cloud managed)
- Créer un fichier `.env.example` documentant toutes les variables : `MONGO_URL`, `REDIS_URL`, `EMERGENT_LLM_KEY`, `STRIPE_API_KEY`, `MASTER_KEY`, `DEMO_MODE`, `ALERT_WEBHOOK_URL`, `DB_NAME`, `REACT_APP_BACKEND_URL`

#### 1.2 Authentification utilisateur réelle
- Remplacer le `USER_ID = "default"` hardcodé par une vraie auth (JWT ou OAuth)
- Recommandé : intégrer **Supabase Auth** ou **Auth0** — le backend a déjà PyJWT et `python-jose`
- Le `SubscriptionContext.jsx` et toutes les pages doivent passer le vrai `user_id`

#### 1.3 Sécurisation des webhooks Stripe
- **Avant tout déploiement** : implémenter la validation de signature webhook (`stripe.Webhook.construct_event`) dans les deux endpoints `/webhook/stripe` et `/webhook/stripe/early-adopter`
- Sans ça, n'importe qui peut envoyer un faux webhook et activer un abonnement gratuit

#### 1.4 Désactiver DEMO_MODE
- Forcer `DEMO_MODE=false` en production via la config CI/CD
- Ajouter un check au démarrage qui refuse de démarrer si `DEMO_MODE=true` et `ENV=production`

#### 1.5 Choix d'hébergement
- **Backend** : Railway, Render, ou Fly.io (conteneurs Docker, simple)
- **MongoDB** : MongoDB Atlas M10 (10GB, $57/mois) minimum
- **Redis** : Upstash Redis ou Redis Cloud (plan payant pour la persistence)
- **Frontend** : Vercel ou Netlify (build React statique)
- **Workers** : même conteneur que le backend ou service séparé sur Railway

---

### PHASE 2 — Migration Stripe → Paddle
*Objectif : remplacer le processeur de paiement sans interrompre les abonnés existants*

#### Contexte code actuel
Les points d'entrée Stripe sont clairement identifiés :
- `backend/server.py` : 4 endpoints (`/api/premium/checkout`, `/api/subscription/early-adopter/checkout`, `/webhook/stripe`, `/webhook/stripe/early-adopter`)
- `backend/subscription_manager.py` : champs `stripe_customer_id`, `stripe_subscription_id`
- `backend/requirements.txt` : `stripe==14.4.1` + `emergentintegrations` (wrapper)
- `frontend/src/pages/Subscription.jsx` : appels vers ces endpoints

#### Étapes de migration

**2.1 Préparer la base de données**
- Ajouter les champs `paddle_customer_id`, `paddle_subscription_id` dans le schéma subscription MongoDB (en parallèle des champs Stripe)
- Ne jamais supprimer les champs Stripe tant que des abonnés actifs existent

**2.2 Créer le compte Paddle et configurer les produits**
- Créer le produit "Early Adopter" à €4.99/mois dans Paddle Dashboard
- Récupérer les `price_id` Paddle équivalents
- Configurer les webhooks Paddle (`subscription.activated`, `subscription.cancelled`, `payment.succeeded`)

**2.3 Implémenter les nouveaux endpoints Paddle**
- Ajouter `paddle-billing` (Python SDK officiel Paddle) à `requirements.txt`
- Créer `/api/subscription/paddle/checkout` (Paddle Checkout)
- Créer `/webhook/paddle` avec validation de signature Paddle
- Créer `/api/subscription/paddle/status`
- Dupliquer `activate_early_adopter()` en `activate_early_adopter_paddle()` dans `subscription_manager.py`

**2.4 Mode double-run (coexistence)**
- Conserver les anciens endpoints Stripe **actifs** pour les abonnés existants
- Basculer le frontend sur les nouveaux endpoints Paddle pour les nouveaux utilisateurs
- Variable d'environnement `PAYMENT_PROVIDER=paddle|stripe` pour switcher

**2.5 Migration des abonnés existants**
- Exporter la liste des `stripe_customer_id` actifs
- Utiliser l'API Stripe pour annuler les abonnements proprement (en fin de période)
- Envoyer un email aux utilisateurs pour recréer leur abonnement via Paddle (ou migrer via Paddle Import)
- Mettre à jour les documents MongoDB avec les nouveaux identifiants Paddle

**2.6 Nettoyage**
- Une fois tous les abonnés migrés, retirer les endpoints Stripe et la dépendance `stripe`
- Retirer les champs `stripe_*` du schéma (ou les conserver en historique)

---

### PHASE 3 — Scalabilité 1000 utilisateurs
*Objectif : supporter 1000 utilisateurs actifs sans dégradation*

#### Estimation de charge
- 1000 users × 1 sync Garmin/jour = 1000 jobs/jour ≈ 42 jobs/heure
- Pics potentiels : 100-200 syncs simultanés après une course
- LLM calls : ~10% des users actifs × 3 appels/jour = 300 appels LLM/jour

#### 3.1 Workers Garmin
- Augmenter `SYNC_MAX_CONCURRENCY` de 5 à **20-30** (tester avec `load_audit.py` qui existe déjà !)
- Activer `SYNC_SCHEDULE_INTERVAL` avec `SYNC_SCHEDULE_STAGGER_MS=500` pour étaler les syncs
- Déployer **2-3 instances** du sync_worker en parallèle (Redis comme coordinateur central)

#### 3.2 Remplacer le cache in-process par Redis
- `_workout_cache` et `_weekly_cache` dans `coach_service.py` → migrer vers Redis avec TTL
- Cela permet de scaler horizontalement le backend FastAPI (plusieurs instances)

#### 3.3 Indexation MongoDB
- Vérifier et compléter les index sur : `subscriptions.user_id`, `workouts.user_id + date`, `daily_metrics.user_id + date`, `garmin_connections.user_id`
- Activer MongoDB Atlas Performance Advisor pour détecter les slow queries

#### 3.4 Rate limiting API
- Ajouter `slowapi` (middleware FastAPI) sur les endpoints coûteux : `/api/coach/analyze`, `/api/training/plan`, `/api/rag/`
- Limites suggérées : 10 req/min par user sur les endpoints LLM

#### 3.5 Autoscaling
- Configurer **horizontal pod autoscaling** (HPA) sur le backend FastAPI : scale up si CPU > 70%
- Les workers async sont stateless → peuvent être scalés indépendamment

#### 3.6 Monitoring production
- Le système d'alertes (`monitoring/alerts.py`) est déjà bien conçu → le brancher sur Slack/Discord via `ALERT_WEBHOOK_URL`
- Ajouter **Sentry** pour le tracking des erreurs Python + React
- Mettre en place des **dashboards** MongoDB Atlas + Redis (métriques de queue)

#### 3.7 CDN pour le frontend
- Activer le CDN Vercel/Cloudflare devant le frontend React
- Configurer les headers de cache appropriés

---

## 📊 RÉSUMÉ DES PRIORITÉS

| Priorité | Action | Bloquant ? |
|----------|--------|------------|
| 🔴 P0 | Corriger la validation des webhooks Stripe | Oui (sécurité) |
| 🔴 P0 | Désactiver DEMO_MODE en prod | Oui |
| 🔴 P0 | Authentification utilisateur réelle | Oui |
| 🟠 P1 | Aligner docker-compose sur MongoDB | Oui (déploiement) |
| 🟠 P1 | Fichier `.env.example` | Oui (opérations) |
| 🟡 P2 | Migration Paddle (phases 2.1→2.6) | Non (Stripe fonctionne) |
| 🟡 P2 | Cache Redis (coach_service) | Pour multi-instances |
| 🟢 P3 | Augmenter concurrency workers | Pour 1000 users |
| 🟢 P3 | Rate limiting API | Pour 1000 users |
| 🟢 P3 | Monitoring / alerting | Pour prod robuste |
