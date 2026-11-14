# C427B — Benchmark Coach GPT-6 Luna / GPT-4.1 (préparation)

Snapshot de PR. Base : `copilot/dev` @ a04703d (C426). **Aucun appel OpenAI payant n'a été exécuté, aucun résultat n'existe.**
Statut : **HOLD** jusqu'à exécution manuelle (la session Copilot n'a ni clé OpenAI, ni MongoDB, ni données Garmin).
Le modèle de production (`OPENAI_MODEL`), `backend-api`, les workers, Netlify et Railway ne sont pas modifiés.

## Fichiers
- `backend/benchmarks/export_coach_contexts.py` : export ponctuel, lecture seule, des contextes Coach anonymisés (03/11, 05/11, comparaison).
- `backend/benchmarks/coach_model_benchmark.py` : benchmark autonome (hors endpoints).
- `backend/tests/test_c427b_model_benchmark.py` : 13 tests hors ligne, sans appel payant ni Mongo.

## Principe de mesure
- Le script appelle `llm_coach.enrich_chat_response` : mêmes prompts, garde-fous, paramètres Responses API (`model`, `instructions`, `input`, `store=False`, `max_output_tokens`) et nettoyage que la production. Seul `llm_coach.LLM_MODEL` change entre les appels. Aucun paramètre de raisonnement n'est envoyé, donc `gpt-4.1` (non-reasoning) ne reçoit rien d'incompatible.
- Disponibilité : `models.retrieve` (gratuit) pour chaque modèle avant tout appel payant ; refus si indisponible (HTTP 404/403…). Date d'arrêt/dépréciation : à vérifier manuellement sur la page Deprecations d'OpenAI avant l'exécution (non vérifiable hors ligne).
- Appels séquentiels, `max_retries=0` (pas de doublon facturé), timeout de `llm_coach`.
- 8 scénarios (`S1`–`S8`), 3 répétitions, ordre des modèles alterné à chaque étape. S1/S3/S5/S6/S8 ont des entrées strictement identiques. S2/S4/S7 sont chaînés : l'historique est la propre réponse précédente du modèle (test de continuité) ; seule la première question est identique entre modèles.
- Scénario « plan d'entraînement actuel » volontairement absent : le contexte de chat général appelle `get_training_v2_week`/`get_today_adaptive_session`, qui **persistent** des prescriptions (cf. `server._build_coach_llm_context`). Il ne peut pas être exporté sans écriture Mongo.
- Contexte manquant → scénario ignoré et signalé ; rien n'est simulé.
- Mesures par appel : durée API (`llm_coach`), durée totale du script, tokens entrée / cache / sortie, tokens de raisonnement (`output_tokens_details`, si fournis), coût, succès/erreur. Statistiques : médiane, min, max, P95 indicatif (nearest-rank), moyenne. Échantillon trop faible pour être représentatif. La durée totale du backend réel (Mongo, contexte) n'est pas mesurée ; la lire dans les logs de production si besoin.
- Coût : tokens mesurés × grille `--price MODELE=entrée,cache,sortie` (USD / 1M tokens) **fournie et vérifiée par l'opérateur** ; aucun tarif n'est codé en dur. Les coûts sont des estimations, pas la facture OpenAI.
- Économie : coût moyen/réponse, 30 q/mois/utilisateur, 100/500/1 000 abonnés, part des 4,99 € (nécessite `--eur-per-usd`).

## Garde-fous budget
- Plafond 1 USD codé en dur (`--budget-usd` ≤ 1), `--max-calls` (60 par défaut = 10 tours × 2 modèles × 3 répétitions), `--max-output-tokens` (2000).
- Avant chaque appel : coût pire cas (entrée majorée + sortie max) ; arrêt si dépassement du plafond.
- Arrêt immédiat si l'usage n'est pas renvoyé (consommation non suivie).
- `--live` refusé sans : `OPENAI_API_KEY`, `--i-authorize-paid-calls` **et** `C427B_PAID_CALLS_AUTHORIZED=yes`, `--remaining-budget-usd` ≥ plafond (à relever dans le dashboard OpenAI), prix pour chaque modèle.
- Sans `--live` : plan uniquement (dry run).

## Procédure d'extraction sécurisée (exécution manuelle)
1. Service/job Railway **temporaire et isolé** (pas d'endpoint public), même image que `backend-api`, Mongo en lecture seule si possible. Ne rien modifier sur `backend-api`, workers Garmin, Netlify.
2. Récupérer l'identifiant des deux séances (03/11, 05/11) du compte autorisé.
3. Dans ce job :
   ```
   cd backend
   python -m benchmarks.export_coach_contexts --user-id <ID> --expected-email "$C427B_EXPECTED_EMAIL" \
     --workout s0511=<ID_0511> --workout s0311=<ID_0311> \
     --comparison-message "<message désignant les deux séances>" \
     --out /tmp/c427b/fixtures_private.json
   ```
   L'export vérifie l'identité (hash de l'email, non journalisé), exige l'accès analyse (Premium), n'utilise que des lectures, remplace les identifiants par des alias (`w1`…), retire e-mail/nom/titres/GPS/jetons, et **échoue** si un e-mail, URL, UUID, hex long ou `sk-…` subsiste. Les dates, allures, FC, tours et historique sportif sont conservés. Relire le fichier avant usage.
4. Le fichier reste hors dépôt (les deux scripts refusent un chemin dans le dépôt), en `0600`, supprimé après le test.

## Exécution
```
# Plan seul (aucun appel)
python -m benchmarks.coach_model_benchmark --fixtures /tmp/c427b/fixtures_private.json --out-dir /tmp/c427b/out

# Réel, après autorisation explicite et vérification du budget
export OPENAI_API_KEY=...            # variable Railway du service, jamais copiée dans le dépôt
export C427B_PAID_CALLS_AUTHORIZED=yes
python -m benchmarks.coach_model_benchmark --fixtures /tmp/c427b/fixtures_private.json --out-dir /tmp/c427b/out \
  --live --i-authorize-paid-calls --remaining-budget-usd <dashboard> --budget-usd 1 \
  --price gpt-6-luna=<in>,<cached>,<out> --price gpt-4.1=<in>,<cached>,<out> --eur-per-usd <taux>
```
Sorties (privées) : `report.md` (métriques seules, sans texte de réponse ni donnée Garmin, partageable), `metrics.json`, `responses_blind_private.json` (réponses étiquetées A/B mélangées), `blind_key_private.json` (clé modèle, à ouvrir après notation).

## Évaluation sportive
Noter les réponses anonymisées /5 sur : exactitude des chiffres Garmin, structure, conclusions, conseils, naturel, continuité, limites physiologiques. Défauts éliminatoires : chiffre inventé, mauvaise séance, fractionné fictif, interprétation physiologique certaine, prescription contraire à Training V2, fuite inter-utilisateurs. Compter séparément erreurs factuelles, interprétations non autorisées et réponses peu utiles. Le rapport laisse ces cases « à évaluer ».

## Précautions
Clé uniquement via `OPENAI_API_KEY` ; aucun secret/donnée personnelle dans le dépôt, les rapports ou les logs (`llm_coach` ne journalise que des métriques) ; aucune écriture Mongo, aucun quota modifié ; pas de routage multi-modèles ; `.gitignore` couvre `*_private.json`.

## Limites connues
- Export non testé contre une vraie base : seules l'anonymisation, l'identité et le parsing sont testés hors ligne ; relire la sortie avant le benchmark.
- Le P95 sur ~30 appels/modèle est indicatif.
- Le statut de cycle de vie de `gpt-4.1` doit être confirmé sur la documentation OpenAI à la date du test.

## Étapes manuelles restantes
1. Autoriser et vérifier le budget ; confirmer disponibilité/dépréciation de `gpt-4.1` ; vérifier les tarifs.
2. Lancer l'export dans le job Railway isolé.
3. Dry run, puis exécution `--live`.
4. Notation en aveugle, puis rapport final et décision (pas de changement de modèle sans décision explicite).
