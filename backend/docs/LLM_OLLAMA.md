# CardioCoach - Intégration LLM Ollama

## Architecture
Le chatbot utilise un LLM local (Ollama) exécuté **uniquement sur le serveur** backend.
**Aucune exécution côté client/mobile.**

## Configuration

### Variables d'environnement
```env
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=phi3:mini
```

### Modèles recommandés
| Modèle | RAM requise | Vitesse | Qualité |
|--------|-------------|---------|---------|
| phi3:mini | 2-3 GB | Rapide | Bon |
| llama3.2:3b-instruct | 3-4 GB | Moyen | Très bon |
| qwen2.5:7b-instruct | 6-8 GB | Lent | Excellent |

## Installation Ollama (serveur)

```bash
# Installation
curl -fsSL https://ollama.com/install.sh | sh

# Démarrer le service
ollama serve &

# Télécharger le modèle
ollama pull phi3:mini
```

## Fonctionnement

1. **Requête chat** → Le backend reçoit la question utilisateur
2. **Contexte RAG** → Construction du contexte avec données Strava (workouts, stats)
3. **Appel Ollama** → Si disponible, génère une réponse LLM naturelle
4. **Fallback** → Si Ollama échoue/timeout (15s), utilise les templates Python

## Logs

```
[LLM] Réponse générée par phi3:mini en 2.34s pour user abc123
[Chat] Fallback templates Python pour user abc123 (Ollama non disponible)
```

## Sécurité

- ✅ LLM exécuté 100% côté serveur
- ✅ Pas d'appels API cloud externes
- ✅ Pas de dépendance internet pour l'inférence
- ❌ Pas de WebLLM/on-device sur mobile
- ❌ Pas d'OpenAI/Claude/Gemini API

## Fichiers

- `/app/backend/llm_coach.py` - Module d'intégration Ollama
- `/app/backend/server.py` - Endpoint `/chat/send` avec fallback
- `/app/backend/.env` - Configuration OLLAMA_HOST/MODEL
