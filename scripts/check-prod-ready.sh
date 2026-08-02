#!/usr/bin/env bash
# =============================================================================
# scripts/check-prod-ready.sh — RunIndex pre-deployment readiness check
# =============================================================================
# Vérifie que toutes les conditions nécessaires au déploiement en production
# sont réunies avant de lancer `docker compose up`.
#
# Usage :
#   chmod +x scripts/check-prod-ready.sh
#   ./scripts/check-prod-ready.sh          # lit .env dans le répertoire courant
#   ENV_FILE=/path/to/.env ./scripts/check-prod-ready.sh
#
# Retourne 0 si tout est OK, 1 si au moins un problème est détecté.
# =============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Couleurs (désactivées si pas de TTY)
# ---------------------------------------------------------------------------
if [ -t 1 ]; then
  RED='\033[0;31m'; YELLOW='\033[1;33m'; GREEN='\033[0;32m'; RESET='\033[0m'
else
  RED=''; YELLOW=''; GREEN=''; RESET=''
fi

PASS="${GREEN}[OK]${RESET}"
WARN="${YELLOW}[WARN]${RESET}"
FAIL="${RED}[FAIL]${RESET}"

ERRORS=0
WARNINGS=0

fail()    { echo -e "${FAIL}  $1"; ERRORS=$((ERRORS + 1)); }
warn()    { echo -e "${WARN}  $1"; WARNINGS=$((WARNINGS + 1)); }
ok()      { echo -e "${PASS}  $1"; }
section() { echo; echo "=== $1 ==="; }

# ---------------------------------------------------------------------------
# Charger le fichier .env si présent
# ---------------------------------------------------------------------------
ENV_FILE="${ENV_FILE:-.env}"

if [ -f "$ENV_FILE" ]; then
  # shellcheck disable=SC1090
  set -a
  # Exclure les lignes commentées et les lignes vides
  while IFS= read -r line || [ -n "$line" ]; do
    [[ "$line" =~ ^[[:space:]]*# ]] && continue
    [[ -z "${line// }" ]] && continue
    export "$line" 2>/dev/null || true
  done < "$ENV_FILE"
  set +a
  echo "Fichier .env chargé : $ENV_FILE"
else
  echo -e "${WARN}  Aucun fichier .env trouvé à '$ENV_FILE' — variables lues depuis l'environnement uniquement."
  WARNINGS=$((WARNINGS + 1))
fi

# ---------------------------------------------------------------------------
# 1. ENVIRONMENT
# ---------------------------------------------------------------------------
section "Environnement"

env_val="${ENVIRONMENT:-}"
if [ "$env_val" = "production" ]; then
  ok "ENVIRONMENT=production"
elif [ -z "$env_val" ]; then
  fail "ENVIRONMENT n'est pas défini (doit être 'production')"
else
  fail "ENVIRONMENT='$env_val' — doit être 'production' pour un déploiement en production"
fi

# ---------------------------------------------------------------------------
# 2. DEMO_MODE doit être absent ou false
# ---------------------------------------------------------------------------
section "Demo mode"

demo_val="${DEMO_MODE:-false}"
demo_lower="$(echo "$demo_val" | tr '[:upper:]' '[:lower:]')"
if [ "$demo_lower" = "true" ] || [ "$demo_lower" = "1" ] || [ "$demo_lower" = "yes" ]; then
  fail "DEMO_MODE=$demo_val — interdit en production (bypasse les vérifications d'abonnement)"
else
  ok "DEMO_MODE est désactivé ($demo_val)"
fi

# ---------------------------------------------------------------------------
# 3. Secrets critiques
# ---------------------------------------------------------------------------
section "Secrets critiques"

check_secret() {
  local name="$1"
  local min_len="${2:-1}"
  local val="${!name:-}"

  if [ -z "$val" ]; then
    fail "$name est vide ou non défini"
  elif [ "${#val}" -lt "$min_len" ]; then
    fail "$name est trop court (${#val} car. < minimum $min_len)"
  else
    ok "$name est défini (${#val} car.)"
  fi
}

check_secret "JWT_SECRET_KEY" 32
check_secret "MONGO_URL" 10
check_secret "REDIS_URL" 10
check_secret "PADDLE_API_KEY" 10
check_secret "PADDLE_WEBHOOK_SECRET" 10
check_secret "GARMIN_USERNAME" 3
check_secret "GARMIN_PASSWORD" 6
check_secret "EMERGENT_LLM_KEY" 10

# ---------------------------------------------------------------------------
# 4. MONGO_INITDB_ROOT_PASSWORD (Docker Compose self-hosted uniquement)
# ---------------------------------------------------------------------------
section "MongoDB"

mongo_url="${MONGO_URL:-}"
if echo "$mongo_url" | grep -q "mongo:27017"; then
  # Probablement un déploiement Docker Compose self-hosted
  check_secret "MONGO_INITDB_ROOT_PASSWORD" 12
else
  ok "MONGO_URL pointe vers un service externe (Atlas ou managé) — MONGO_INITDB_ROOT_PASSWORD non requis"
fi

# ---------------------------------------------------------------------------
# 5. FRONTEND_URL (CORS strict en production)
# ---------------------------------------------------------------------------
section "CORS / Frontend"

frontend_url="${FRONTEND_URL:-}"
if [ -z "$frontend_url" ]; then
  fail "FRONTEND_URL n'est pas défini — CORS de production sera vide"
elif echo "$frontend_url" | grep -qE "^https://"; then
  ok "FRONTEND_URL=$frontend_url (HTTPS)"
elif echo "$frontend_url" | grep -qE "^http://localhost"; then
  warn "FRONTEND_URL pointe vers localhost — acceptable uniquement en staging local"
else
  warn "FRONTEND_URL=$frontend_url — vérifier qu'il s'agit bien d'une URL HTTPS de production"
fi

# ---------------------------------------------------------------------------
# 6. PADDLE_ENVIRONMENT
# ---------------------------------------------------------------------------
section "Paddle"

paddle_env="${PADDLE_ENVIRONMENT:-sandbox}"
if [ "$paddle_env" = "production" ]; then
  ok "PADDLE_ENVIRONMENT=production"
elif [ "$paddle_env" = "sandbox" ]; then
  warn "PADDLE_ENVIRONMENT=sandbox — paiements réels désactivés (OK pour staging)"
else
  fail "PADDLE_ENVIRONMENT='$paddle_env' — valeur invalide (doit être 'production' ou 'sandbox')"
fi

# ---------------------------------------------------------------------------
# 7. TRUSTED_PROXY_COUNT
# ---------------------------------------------------------------------------
section "Proxy"

proxy_count="${TRUSTED_PROXY_COUNT:-0}"
if [ "$proxy_count" -ge 1 ] 2>/dev/null; then
  ok "TRUSTED_PROXY_COUNT=$proxy_count (reverse proxy configuré)"
else
  warn "TRUSTED_PROXY_COUNT=0 — vérifier si un reverse proxy/load balancer est devant l'API"
fi

# ---------------------------------------------------------------------------
# 8. Vérification Git — pas de secrets dans l'historique
# ---------------------------------------------------------------------------
section "Sécurité Git"

if command -v git &>/dev/null && git rev-parse --git-dir &>/dev/null 2>&1; then
  # Vérifie uniquement dans les fichiers trackés (pas l'historique complet — trop lent)
  if git grep -l -iE "(password|secret|api_key)\s*=\s*['\"][^'\"]+['\"]" -- \
       ':!*.example' ':!*.md' ':!tests/' ':!test_*' 2>/dev/null | grep -q .; then
    fail "Des patterns suspects ont été trouvés dans les fichiers Git trackés — vérifier manuellement"
  else
    ok "Aucun secret apparent dans les fichiers trackés"
  fi
else
  warn "Pas dans un dépôt Git — vérification ignorée"
fi

# ---------------------------------------------------------------------------
# Résumé
# ---------------------------------------------------------------------------
echo
echo "========================================"
if [ "$ERRORS" -gt 0 ]; then
  echo -e "${FAIL}  $ERRORS erreur(s), $WARNINGS avertissement(s)"
  echo "  Corriger les erreurs avant de déployer."
  echo "========================================"
  exit 1
elif [ "$WARNINGS" -gt 0 ]; then
  echo -e "${WARN}  0 erreur, $WARNINGS avertissement(s)"
  echo "  Revérifier les avertissements selon le contexte."
  echo "========================================"
  exit 0
else
  echo -e "${PASS}  Tout est OK — prêt pour le déploiement en production."
  echo "========================================"
  exit 0
fi
