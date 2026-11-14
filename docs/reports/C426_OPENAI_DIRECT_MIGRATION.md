# C426 — Migration du Coach vers l'API OpenAI directe

Snapshot de PR. Base : `copilot/dev` @ 5824882.

## Changement
`backend/llm_coach.py::_call_gpt` (point d'appel unique : chat, commentaire de séance, hybrid C359, localisation)
utilise désormais `openai.AsyncOpenAI().responses.create` au lieu d'`emergentintegrations`.
Signatures, prompts, nettoyage de réponse, limites (700 / transport chat) et contrat `(texte, ok, meta)` inchangés :
les appelants remboursent donc les quotas comme avant sur `ok == False`.

- `store=False`, aucun outil, aucun `user`/identifiant envoyé, `max_retries=0` (pas de doublon facturé).
- Timeout explicite (`OPENAI_TIMEOUT_SECONDS`, 30 s par défaut) + garde `asyncio.wait_for`.
- Erreurs (429, timeout, 5xx, réponse vide/incomplète) : `(None, False, meta)` avec `meta["error"]`; aucun texte inventé.
  Seul le type/statut est journalisé, jamais le message d'exception, les prompts ou la clé.
- Sans `OPENAI_API_KEY` : échec propre immédiat (backend opérationnel).
- Métadonnées/journal par appel : modèle réel, tokens entrée / entrée en cache / sortie, durée, succès,
  `estimated_cost_usd` (grille `OPENAI_PRICE_*_PER_MTOK`; `None` si non configurée — aucun tarif n'est supposé).
- `LLM_MODEL` = `OPENAI_MODEL` (défaut `gpt-6-luna`). Le modèle fait partie de la clé de cache des commentaires : un changement invalide ce cache (attendu).

## Railway (service `backend-api` uniquement)
```
OPENAI_API_KEY=<clé OpenAI>
OPENAI_MODEL=gpt-6-luna
```
Optionnel : `OPENAI_TIMEOUT_SECONDS`, `OPENAI_MAX_OUTPUT_TOKENS`, `OPENAI_PRICE_INPUT_PER_MTOK`,
`OPENAI_PRICE_CACHED_INPUT_PER_MTOK`, `OPENAI_PRICE_OUTPUT_PER_MTOK`.
Jamais dans Netlify, le frontend ou GitHub. Après validation E2E, `EMERGENT_LLM_KEY` n'est plus utile au Coach
(vérifier les autres usages Emergent avant suppression ; `emergentintegrations` reste dans `requirements.txt`).

## Coût théorique (non garanti)
Hypothèse du brief : 30 questions/mois × (8 000 tokens entrée + 1 000 sortie) ≈ 0,04 USD/utilisateur/mois,
soit ≈ 0,0013 USD/réponse. Tarifs gpt-6-luna **non vérifiés ici** : renseigner la grille `OPENAI_PRICE_*` et
lire `estimated_cost_usd` dans les logs pour confirmer. Les tokens de raisonnement comptent dans la sortie.

## Validation qualitative (À FAIRE — aucune clé disponible dans cet environnement)
Aucun appel réel n'a été fait ; la qualité et l'accessibilité de `gpt-6-luna` ne sont PAS validées.
Rejouer sur Railway/staging, avec les contextes des tests existants (`test_coach_c408_scenarios.py`, C392b, C400) :
1. footing ; 2. fractionné ; 3. répétitions Garmin ; 4. fréquence cardiaque ; 5. comparaison de deux séances ;
6. suivi conversationnel ; 7. allures ; 8. données manquantes ; 9. refus d'interprétation physiologique injustifiée ;
10. FREE/TRIAL/PREMIUM (analyse de séance refusée en FREE). Noter par scénario écarts vs attentes, latence, tokens.

## Procédure E2E runindex.app
1. Poser les variables sur `backend-api`, redéployer manuellement.
2. Vérifier l'accès modèle (un appel minimal borné) et qu'aucun log ne contient la clé.
3. Compte PREMIUM : commentaire de séance puis question chat (FR/EN/ES) ; lire les logs `[LLM] call ...`.
4. Compte FREE : analyse de séance refusée, quota décrémenté puis remboursé sur erreur simulée (clé invalide en staging).
5. Retirer temporairement la clé en staging : le Coach doit retomber sur son fallback sans erreur 5xx.

## Tests
Voir description de la PR.

## Verdict : HOLD
Code et tests mockés prêts ; HOLD tant que l'accès à `gpt-6-luna` et le test qualitatif réel ne sont pas faits.
