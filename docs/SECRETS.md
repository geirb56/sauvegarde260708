# RunIndex — Gestion des secrets

> Ce document liste toutes les variables sensibles de RunIndex, leur rôle,
> les exigences de sécurité et les bonnes pratiques de rotation.

---

## Règles absolues

1. **Jamais** de secret dans Git — même dans un commit annulé ou une branche
   de test.
2. Les secrets sont injectés **exclusivement** via des variables d'environnement
   (Doppler, HashiCorp Vault, 1Password Secrets Automation, ou Docker Secrets).
3. Le module `backend/config/secrets.py` lit uniquement `os.environ` — pas de
   code spécifique à un fournisseur.
4. Tout secret compromis doit être **révoqué immédiatement** côté fournisseur,
   puis remplacé dans le gestionnaire de secrets.

---

## Tableau des variables sensibles

| Variable | Rôle | Longueur minimale | Rotation | Criticité |
|----------|------|:-----------------:|----------|:---------:|
| `JWT_SECRET_KEY` | Signature des tokens JWT | 64 hex (32 octets) | En cas de compromission — invalide **tous** les tokens actifs | 🔴 Critique |
| `MONGO_INITDB_ROOT_PASSWORD` | Mot de passe root MongoDB (Docker Compose) | 24 caractères aléatoires | En cas de compromission | 🔴 Critique |
| `MONGO_URL` | URI de connexion MongoDB (inclut credentials en prod) | — | En cas de compromission de l'URI ou des credentials inclus | 🔴 Critique |
| `PADDLE_API_KEY` | Clé API Paddle (server-side uniquement) | — | Depuis le dashboard Paddle → API Keys | 🔴 Critique |
| `PADDLE_WEBHOOK_SECRET` | Signature HMAC des webhooks Paddle | — | Depuis le dashboard Paddle → Webhooks | 🔴 Critique |
| `GARMIN_PASSWORD` | Mot de passe du compte Garmin Connect (gccli) | — | Dès changement de mot de passe Garmin | 🟠 Élevé |
| `EMERGENT_LLM_KEY` | Clé API LLM (accès OpenAI via Emergent) | — | Mensuelle (bonne pratique) | 🟠 Élevé |
| `GARMIN_USERNAME` | Email du compte Garmin Connect | — | Avec `GARMIN_PASSWORD` | 🟡 Modéré |

---

## Détail par variable

### `JWT_SECRET_KEY`

- **Rôle** : clé HMAC utilisée pour signer et vérifier tous les tokens JWT
  (connexion, OAuth, sessions).
- **Génération** : `openssl rand -hex 32` (produit 64 caractères hexadécimaux).
- **Impact d'une compromission** : un attaquant peut forger des tokens valides
  pour n'importe quel utilisateur. Rotation immédiate + invalidation de toutes
  les sessions actives.
- **Ne jamais** réutiliser la même clé entre staging et production.

### `MONGO_INITDB_ROOT_PASSWORD`

- **Rôle** : mot de passe du compte root MongoDB dans le container Docker
  Compose (développement/staging).
- **En production** : préférer MongoDB Atlas (auth gérée par le service) ou un
  mot de passe long aléatoire stocké dans le gestionnaire de secrets.
- **Génération** : `openssl rand -base64 24`.
- **Jamais** utiliser un mot de passe par défaut ou vide.

### `MONGO_URL`

- **Rôle** : URI de connexion MongoDB incluant les credentials en production
  (`******host/db`).
- **Restriction** : accessible uniquement depuis le backend (jamais exposé au
  frontend ou aux logs).

### `PADDLE_API_KEY`

- **Rôle** : authentification server-side auprès de l'API Paddle (création
  d'abonnements, gestion des clients).
- **Ne jamais** inclure dans le code frontend ou les réponses API.
- **Restriction d'IP** : activer le filtrage IP dans le dashboard Paddle si
  possible.

### `PADDLE_WEBHOOK_SECRET`

- **Rôle** : vérification HMAC-SHA256 des webhooks Paddle entrants.
- **Impact d'une compromission** : un attaquant peut forger des webhooks
  (activation frauduleuse d'abonnements).
- **Vérification** : le backend vérifie systématiquement la signature avant
  tout traitement.

### `GARMIN_USERNAME` / `GARMIN_PASSWORD`

- **Rôle** : credentials du compte Garmin Connect utilisé par gccli pour les
  synchronisations (phase mono-compte actuelle).
- **Stockage** : injectés uniquement en environnement ; gccli les stocke dans
  un vault chiffré local après le premier bootstrap.
- **Ne jamais** écrire ces credentials dans les logs Docker.
- **Phase multi-compte (future)** : chaque utilisateur possédera son propre
  vault chiffré — voir `app/credential_vault.py`.

### `EMERGENT_LLM_KEY`

- **Rôle** : accès à l'API LLM (GPT-4o-mini via Emergent) pour le coach IA.
- **Rotation mensuelle** recommandée même sans compromission.

---

## Stockage recommandé

### Développement local
```bash
# Copier .env.example → .env et remplir les valeurs
cp .env.example .env
# .env est ignoré par .gitignore — ne jamais le committer
```

### Staging / Production

| Outil | Commande de démarrage |
|-------|-----------------------|
| **Doppler** | `doppler run -- docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d` |
| **HashiCorp Vault** | Utiliser le plugin `vault-agent` ou `envconsul` |
| **1Password Secrets** | `op run --env-file=.env.1password -- docker compose up -d` |
| **Docker Secrets** | Monter les secrets via `secrets:` dans docker-compose.yml |

### Génération des secrets critiques
```bash
# JWT_SECRET_KEY (64 hex = 32 octets)
openssl rand -hex 32

# MONGO_INITDB_ROOT_PASSWORD (base64 24 octets)
openssl rand -base64 24

# Vérifier qu'aucun secret ne traîne dans Git
git log --all -p | grep -iE "(password|secret|api_key|token)" \
  | grep -v "example\|placeholder\|VARIABLE\|#"
```

---

## Checklist avant déploiement

- [ ] `JWT_SECRET_KEY` est défini, ≥ 64 caractères hexadécimaux, unique par
  environnement
- [ ] `MONGO_INITDB_ROOT_PASSWORD` est défini et n'est pas vide
- [ ] `PADDLE_API_KEY` et `PADDLE_WEBHOOK_SECRET` sont définis
- [ ] `GARMIN_USERNAME` et `GARMIN_PASSWORD` sont définis
- [ ] `EMERGENT_LLM_KEY` est défini
- [ ] `ENVIRONMENT=production` (bloque DEMO_MODE, CORS strict)
- [ ] `DEMO_MODE` est absent ou `false`
- [ ] Aucun secret dans `git log --all -p`
- [ ] Les ports Redis et MongoDB ne sont pas exposés sur l'hôte (voir
  `docker-compose.prod.yml`)

Voir aussi : [`scripts/check-prod-ready.sh`](../scripts/check-prod-ready.sh)
pour la vérification automatisée.
