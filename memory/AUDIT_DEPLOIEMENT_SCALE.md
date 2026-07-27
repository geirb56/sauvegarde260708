# RunIndex — Audit technique & Roadmap (Déploiement · Stripe→Paddle · 1000 utilisateurs)
_Date : 2026-07-27 — basé sur le code de la PR #16 (commit 29fce67)_

---

## 1. Résumé exécutif
L'app est aujourd'hui un **produit mono-utilisateur** techniquement solide (Garmin, RunIndex, plans, IA, abonnement) mais **pas prête pour du multi-utilisateur ni du scale**. Trois chantiers structurants sont nécessaires avant 1000 utilisateurs :

1. **Auth réelle + isolation des données** (aujourd'hui tout tourne sur `user_id="default"`).
2. **Modèle Garmin par utilisateur** (aujourd'hui **un seul compte Garmin partagé** en dur dans `.env`) → **blocage n°1**.
3. **State partagé externalisé** (rate-limit et cache en mémoire process → cassent dès qu'on a plus d'une instance).

La migration Stripe→Paddle est, elle, relativement **contenue** (les points d'intégration paiement sont peu nombreux).

---

## 2. Audit technique de l'existant

### 2.1 Stack réelle
- **Backend** : FastAPI (`server.py`, ~5600 lignes), Motor/MongoDB, workers Garmin via Redis.
- **Frontend** : React (CRA), servi séparément.
- **Files/Workers** : Redis + 4 workers supervisor (sync / event / scheduler / monitor).
- **LLM** : `emergentintegrations` (`gpt-4.1-mini`, `llm_coach.py:29`) via `EMERGENT_LLM_KEY`.
- **Paiement** : Stripe via `emergentintegrations.payments.stripe.checkout` (`server.py:71`).
- ⚠️ `docker-compose.yml` à la racine est un **vestige** (référence Postgres/Celery/dossier `api/` qui ne correspondent pas au backend réel). À ignorer / nettoyer.

### 2.2 Points forts
- Données déjà **clefées par `user_id`** dans la majorité des collections (`workouts`, `garmin_activities`, `garmin_connections`, `subscriptions`, `run_index_scores`).
- Abonnement propre et centralisé (`subscription_manager.py`) : statuts trial/free/early_adopter/premium, expiration, features par statut.
- Pipeline Garmin déjà **event-driven** (queues Redis, scheduler avec cooldown, verrous par user `sync_worker.py:88`) → bonne base pour scaler la synchro.
- RunIndex history avec backfill, tests unitaires existants (cycle dates 35, history 4, garmin deep sync 21, subscription/chat 25).

### 2.3 Blocages critiques (bloquants pour multi-utilisateur / scale)

| # | Blocage | Preuve dans le code | Impact |
|---|---------|---------------------|--------|
| **B1** | **Compte Garmin unique partagé** | `gccli_provider.py` lit `GARMIN_USERNAME`/`GARMIN_PASSWORD` du `.env`, une seule session OAuth gccli persistée | **Tous les utilisateurs verraient les mêmes activités.** Impossible en l'état d'avoir 1000 comptes Garmin distincts. |
| **B2** | **Pas d'auth réelle** | `auth_user` retombe sur `"default"` (`server.py:273-309`), aucun mot de passe / JWT vérifié | Aucune séparation des comptes, aucune sécurité. |
| **B3** | **Fuite de données inter-utilisateurs** | Requêtes `{"$or":[{"user_id":uid},{"user_id":None},{"user_id":{"$exists":False}}]}` (`server.py:641,652,1467,1556,3615,4272…`) | Dès qu'il y a plusieurs users, chacun voit aussi les données "orphelines"/d'autrui. **Faille de confidentialité.** |
| **B4** | **Rate-limiter en mémoire** | `RateLimiter` = `defaultdict` en RAM du process (`server.py:179-244`) | Inefficace/incohérent dès qu'on a >1 instance backend (scale horizontal). |
| **B5** | **Cache temps réel en mémoire** | `realtime_cache` (feed dashboard) stocké en process | Idem : incohérent en multi-instance, perdu au restart. |
| **B6** | **Secrets en clair dans `.env`** | `GARMIN_PASSWORD`, `STRIPE_API_KEY`, credentials Garmin | À déplacer vers un secret manager avant prod publique. |
| **B7** | **Coût LLM non maîtrisé** | Appels `gpt-4.1-mini` par séance/chat sans quota par plan strict côté serveur pour tous les endpoints | À 1000 users, coût et latence peuvent exploser sans cache/quotas. |

---

## 3. Roadmap DÉPLOIEMENT (mise en ligne)

### Phase 0 — Déploiement "as-is" (mono/faible charge)
Objectif : mettre en ligne rapidement la version actuelle (démo / early access limité).
1. **Choisir la cible** : Emergent Deploy (le plus simple, intégré) ou Vercel (front) + hébergeur conteneur (back). → *décision utilisateur*.
2. **Externaliser les secrets** : sortir `GARMIN_PASSWORD`, `STRIPE_API_KEY` du `.env` vers les variables d'environnement de la plateforme de déploiement.
3. **MongoDB managé** : provisionner une base MongoDB Atlas (pas la Mongo locale du preview) + `MONGO_URL` de prod.
4. **Redis managé** : Redis Cloud/Upstash pour les queues Garmin.
5. **Health checks** : exposer `/api/health`, configurer readiness/liveness.
6. **CORS / URLs** : `CORS_ORIGINS`, `FRONTEND_URL` pointant vers le domaine prod.
7. **Nettoyer** le `docker-compose.yml` vestige pour éviter les confusions.
8. **Passer le déploiement au `deployment_agent`** (vérifie hardcoding, ports, CORS) avant mise en ligne.

> À ce stade : app en ligne mais toujours **mono-utilisateur** (un seul Garmin). OK pour une démo publique / liste d'attente, pas pour 1000 users.

---

## 4. Roadmap MIGRATION Stripe → Paddle

**Bonne nouvelle** : la surface Stripe est petite et centralisée.

### Points d'intégration Stripe actuels
- Init & checkout : `server.py:4645` (`/subscription/checkout`), `4717` (`/premium/checkout`).
- Vérification de paiement : `server.py:4729` (`/subscription/checkout/status/{id}`), `5512` (`/subscription/verify-checkout`).
- Webhook : `/api/webhook/stripe`.
- Activation abonnement : `subscription_manager.activate_early_adopter()` (champs `stripe_customer_id`, `stripe_subscription_id`).
- Prix : `EARLY_ADOPTER_PRICE_ID = "price_early_adopter_499"` (`subscription_manager.py:26`).

### Étapes de migration
1. **Compte & produit Paddle** : créer le produit/prix "Early Adopter 4,99 €/mois" dans Paddle (Billing v2), récupérer `price_id`, `vendor/seller id`, `API key`, `webhook secret`.
2. **Choisir l'approche** : Paddle **Checkout overlay/hosted** (recommandé — Paddle est *Merchant of Record*, gère TVA/UE, idéal pour du SaaS EU à 4,99 €).
3. **Backend** : remplacer les 2 endpoints checkout + les 2 endpoints status par des appels Paddle (création de transaction + redirection), et **réécrire le webhook** `/api/webhook/paddle` pour écouter `subscription.created/activated/canceled/past_due`.
4. **Modèle de données** : ajouter `paddle_customer_id`, `paddle_subscription_id` (garder les champs Stripe pour compat/historique), adapter `activate_early_adopter()`.
5. **Vérification de signature** webhook Paddle (obligatoire — sécurité).
6. **Frontend** (`Subscription.jsx`, `Settings.jsx`) : remplacer l'ouverture du checkout Stripe par Paddle.js (overlay) ou l'URL hosted.
7. **Cycle de vie** : gérer annulation, échec de paiement (`past_due` → `free`), remboursement.
8. **Tests** : environnement **Paddle Sandbox** de bout en bout, puis `testing_agent` sur le flux payant.

> ⚠️ `emergentintegrations` fournit Stripe "clé en main" ; **Paddle n'y est pas** → intégration directe via le SDK/API Paddle (à valider via `integration_expert`). Prévoir la config Paddle par vos soins (clés).
> Estimation : **migration ciblée, faisable en un chantier dédié** une fois les clés Paddle fournies.

---

## 5. Roadmap SCALING → 1000 utilisateurs

C'est le chantier le plus lourd. Ordre recommandé :

### Étape A — Authentification & comptes (prérequis absolu)
- Mettre une **vraie auth** (Supabase Auth **ou** JWT custom — décision utilisateur). Chaque compte = un `user_id` stable.
- Migrer les données actuelles `default` vers le 1er compte propriétaire.
- **Supprimer le fallback `"default"`** et l'accès aux données orphelines (corriger B2).

### Étape B — Isolation stricte des données (sécurité)
- Retirer partout le `$or … {user_id:None}/{$exists:false}` (B3) → filtrer **uniquement** par `user_id` du token.
- Backfill : attribuer un `user_id` à toutes les données legacy (aujourd'hui `None`/`default`).
- Ajouter des index MongoDB composés `{user_id, date}` / `{user_id, external_id}` pour la perf multi-user.

### Étape C — Garmin par utilisateur (blocage n°1, B1)
Le point le plus délicat. Options :
- **Option recommandée : Garmin OAuth officiel (Garmin Connect Developer / Health API)** → chaque utilisateur autorise SON compte via OAuth ; on stocke un token par user. Robuste et conforme, mais nécessite l'accès au programme développeur Garmin (démarche à faire).
- **Option intermédiaire : agrégateur tiers** (ex. Terra API — déjà des traces `/api/terra/status` dans le code) qui gère l'OAuth multi-appareils (Garmin/Strava/Coros…). Plus rapide à intégrer, coût par utilisateur.
- **À éviter à grande échelle** : demander login/mdp Garmin de chaque user (le modèle gccli actuel) → risque sécurité + fragile + non conforme.
- Adapter `garmin/service.py` & providers pour lire le **token du user courant** au lieu de `GARMIN_USERNAME`/`PASSWORD` global.

### Étape D — State partagé & scale horizontal
- **Rate-limiter → Redis** (B4) : remplacer le `defaultdict` par un compteur Redis (sliding window). Indispensable pour tourner en plusieurs instances.
- **Cache temps réel → Redis** (B5) au lieu de la RAM process.
- Rendre le backend **stateless** → pouvoir lancer N réplicas derrière un load balancer.
- Dimensionner les **workers Garmin** : file par user déjà en place (`sync_worker`), ajouter du parallélisme + backoff + respect des quotas de l'API Garmin/agrégateur.

### Étape E — Coûts & quotas LLM (B7)
- Mettre en **cache** les analyses IA par séance (déjà partiellement le cas) et **quotas serveur** par plan (free/trial/premium).
- Suivre le budget `EMERGENT_LLM_KEY` (auto top-up) ; envisager un modèle moins cher pour les analyses non premium.

### Étape F — Observabilité & prod-readiness
- Logs structurés + alerting (les rapports `INFRA_SECRETS_ALERTING_report.md`, `QUEUE_HEALTH_report.md` existent déjà en mémoire → capitaliser dessus).
- Monitoring MongoDB/Redis (connexions, latence), métriques queues.
- Sauvegardes MongoDB automatiques, plan de restauration.
- Rate-limit anti-abus + WAF/ingress.

### Dimensionnement indicatif 1000 users
- MongoDB Atlas M10+ (index en place), Redis managé, 2–3 réplicas backend stateless + autoscaling, pool de workers Garmin séparé du web.
- Le vrai facteur limitant sera **les quotas de l'API Garmin/agrégateur** (fréquence de sync) → prévoir sync espacée + webhooks entrants plutôt que polling.

---

## 6. Plan par phases (priorisé)

| Phase | Contenu | Prérequis externes | Priorité |
|-------|---------|--------------------|----------|
| **P0** | Déploiement as-is (secrets, Mongo/Redis managés, health, `deployment_agent`) | Choix hébergeur, Atlas/Redis | 🔴 Immédiat |
| **P1** | Auth réelle + isolation données (A+B) | Choix Supabase vs JWT | 🔴 Bloquant multi-user |
| **P2** | Garmin par utilisateur (C) | Accès Garmin OAuth **ou** Terra | 🔴 Bloquant n°1 |
| **P3** | Migration Stripe→Paddle | Clés Paddle (sandbox+prod) | 🟠 Selon besoin business |
| **P4** | Redis rate-limit + cache, stateless, scale (D) | Redis managé | 🟠 Avant montée en charge |
| **P5** | Quotas/cache LLM + observabilité (E+F) | — | 🟡 Continu |

---

## 7. Décisions à prendre (input utilisateur requis)
1. **Hébergement** : Emergent Deploy vs Vercel+conteneur ?
2. **Auth** : Supabase Auth (rapide, social login) vs JWT custom (contrôle total) ?
3. **Garmin multi-user** : Garmin OAuth officiel (démarche dev) vs agrégateur type Terra (coût/user, plus rapide) ?
4. **Paddle** : confirmer le passage (Merchant of Record, gère TVA UE) et fournir les clés sandbox.
5. **Budget** : Mongo Atlas + Redis managé + budget LLM mensuel cible.

> Aucune ligne de code n'a été modifiée pour cet audit (analyse en lecture seule).
