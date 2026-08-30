# RUNINDEX PR223 Report

- Base SHA réel: `5ef2b51587b9163003590ba51618bf05e83836bb`
- Head SHA: `5ce1ff546d710a0bccba5544e4b0a69d5f61d47a`

## Fichiers modifiés
- `backend/server.py`
- `backend/access_control.py`
- `backend/subscription_manager.py`
- `backend/tests/test_paddle_subscription.py`
- `backend/tests/test_paddle_integrity_pr223.py`
- `RUNINDEX_PR223_REPORT.md`

## Root causes
- **A38**: `/api/subscription/paddle/checkout` acceptait `request.price_id` et pouvait créer une transaction Paddle avec un prix choisi côté client au lieu du `PADDLE_PRICE_ID` serveur.
- **A39**: `paddle_webhook` insérait l'`event_id` comme déjà traité avant la mutation métier; si `activate_premium`/`renew_premium` échouait ensuite, un retry Paddle trouvait un doublon et n'essayait plus la mutation.
- **A40**: l'accès Premium restait accordé quand `status=premium` sans `premium_expires_at` valide, car l'accès contrôlait l'expiration seulement si une date parseable existait.

## Source canonique du price ID
- Source canonique: variable serveur `PADDLE_PRICE_ID` dans `backend/server.py`.
- Comportement appliqué: le checkout rejette maintenant un `price_id` client différent et utilise toujours `PADDLE_PRICE_ID` pour la transaction et pour l'audit local.
- Fail closed: si `PADDLE_PRICE_ID` est absent, le checkout renvoie `503` et n'appelle pas Paddle.

## Webhook Paddle — ordre exact
### Avant
1. Vérification signature
2. Résolution `event_id`
3. Vérification doublon
4. Insertion immédiate dans `db.paddle_events` avec `processed_at`
5. Mutation métier (`activate_premium` / `renew_premium` / `cancel_subscription`)

### Après
1. Vérification signature
2. Résolution `event_id` stable (rejet si absent)
3. Si `db.paddle_events.status == processed` → réponse idempotente
4. Exécution de la mutation métier
5. Marquage `processed` seulement après succès
6. En cas d'échec, enregistrement `status=failed` + `last_error`, sans `processed_at`, pour garder le webhook retryable

## Mécanisme d’idempotence
- La déduplication ignore uniquement les événements déjà marqués `status=processed`.
- Un événement précédemment en échec (`status=failed`) est rejouable et repasse dans la mutation métier au retry.
- `transaction.completed` met seulement à jour `payment_transactions`; il n'accorde plus Premium sans date d'expiration canonique.

## Source réelle de `premium_expires_at`
- Source réellement utilisée pour accorder/renouveler Premium: `data.next_billed_at` des webhooks `subscription.activated` et `subscription.updated` dans `backend/server.py`.
- Si `next_billed_at` est absent ou invalide sur ces événements, la mutation Premium est refusée pour ne pas inventer d'expiration.

## Premium expiry — fail closed
- `status=premium` + `premium_expires_at` future valide → accès Premium.
- `status=premium` + `premium_expires_at` passée → accès FREE.
- `status=premium` + expiry absente → accès FREE.
- `status=premium` + expiry invalide → accès FREE.
- `check_premium_expiration()` persiste aussi le retour à FREE pour les états Premium sans expiry valide.

## Tests exécutés + résultats
Commande exécutée:

```bash
cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && python -m pytest \
  tests/test_paddle_integrity_pr223.py \
  tests/test_paddle_subscription.py::TestAccessControlResolve::test_premium_no_expiry_is_free \
  tests/test_paddle_subscription.py::TestAccessControlResolve::test_premium_not_yet_expired \
  tests/test_paddle_subscription.py::TestAccessControlResolve::test_premium_expired_returns_free \
  tests/test_paddle_subscription.py::TestAccessControlResolve::test_premium_invalid_expiry_is_free \
  tests/test_paddle_subscription.py::TestAccessControlResolve::test_premium_can_all_features \
  tests/test_paddle_subscription.py::TestAccessControlResolve::test_premium_unlimited_chat \
  tests/test_paddle_subscription.py::TestSubscriptionManager::test_premium_expiration_sets_free \
  tests/test_paddle_subscription.py::TestSubscriptionManager::test_premium_without_expiry_sets_free \
  tests/test_paddle_subscription.py::TestSubscriptionManager::test_premium_with_invalid_expiry_sets_free
```

Résultat: **18 tests passés**.

Couverture minimale validée:
- override de `price_id` client impossible
- absence de `PADDLE_PRICE_ID` serveur → fail closed
- signature webhook invalide → aucune mutation
- webhook déjà `processed` → idempotent
- mutation échoue → événement non marqué `processed`
- retry après échec → mutation rejouable
- succès mutation → événement ensuite `processed`
- Premium future/past/absente/invalide → résolution d'accès fail-closed
- aucune régression sur un Premium valide

## Runtime Paddle
- Runtime Paddle sandbox testé: **NON**
- Checkout réel / webhook signé réel / activation Premium réelle: **NON testés dans cette PR**

## Blocker
- Aucun blocker code: la source fiable effectivement utilisée pour `premium_expires_at` est `next_billed_at` sur `subscription.activated` et `subscription.updated`.
- Aucun traitement de A56 dans cette PR.
