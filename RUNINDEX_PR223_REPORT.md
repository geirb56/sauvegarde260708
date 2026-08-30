# RUNINDEX PR223 Report

- Base SHA réel: `5ef2b51587b9163003590ba51618bf05e83836bb`
- Head SHA final: `bc488029317a096276e4d00084ad27269724a313`

## Fichiers modifiés
- `RUNINDEX_PR223_REPORT.md`
- `backend/access_control.py`
- `backend/migrations/deduplicate_subscriptions.py`
- `backend/server.py`
- `backend/subscription_manager.py`
- `backend/tests/test_paddle_integrity_pr223.py`
- `backend/tests/test_paddle_subscription.py`
- `backend/tests/test_unique_subscription.py`

## Corrections C223
- **A38**: le checkout ignore toujours le prix client réel et n’utilise que `PADDLE_PRICE_ID`; un `price_id` client différent est rejeté.
- **A39**: le webhook passe d’un simple `find_one(event_id)` à un claim atomique avec états `processing` / `processed` / `failed`, et un index unique sur `paddle_events.event_id`.
- **A40**: le fail-closed Premium reste en place, mais la source canonique d’expiry est corrigée vers `data.current_billing_period.ends_at`.
- **Contrat annulation Paddle**: correction du naming canonique Paddle `canceled`, gestion correcte des annulations programmées et protection hors ordre via `occurred_at`.

## Naming Paddle canonique
- Contrat canonique Paddle traité par le backend: `subscription.canceled` et `status == "canceled"`.
- Alias historique toléré uniquement en normalisation d’entrée: `subscription.cancelled` / `cancelled` sont convertis vers la vérité canonique `canceled`.
- Plus aucune mutation métier Paddle ne dépend fonctionnellement de `subscription.cancelled` ou `status == "cancelled"`.

## Source canonique du price ID
- Source canonique: variable serveur `PADDLE_PRICE_ID` dans `backend/server.py`.
- Le checkout Paddle utilise toujours cette valeur pour la transaction et l’audit local `payment_transactions.price_id`.
- Si `PADDLE_PRICE_ID` est absent: fail closed `503`.

## Source canonique de `premium_expires_at`
- Source canonique utilisée pour accorder/renouveler Premium: `data.current_billing_period.ends_at` sur `subscription.activated` et `subscription.updated`.
- Helper introduit: `_extract_current_period_end(data)`.
- Contrat appliqué: aucune mutation qui maintient/accorde Premium n’est exécutée sans expiry valide.
- `next_billed_at` n’est plus la source canonique d’accès payé.

## Cas scheduled cancel
- Cas géré: `status=active`, `next_billed_at=null`, `scheduled_change=cancel`, `current_billing_period.ends_at=<future>`.
- Le backend garde Premium jusqu’à `current_billing_period.ends_at`.
- Le flux n’échoue pas parce que `next_billed_at` est nul.

## Webhook Paddle — ordre et machine d’état
### Avant C223
1. Vérification signature
2. Résolution `event_id`
3. `find_one(event_id)`
4. Mutation métier
5. `status=processed`

### Après C223
1. Vérification signature
2. Normalisation canonique `event_type` / `status`
3. Résolution `event_id` stable (rejet si absent)
4. Claim atomique de l’événement
   - nouvel event → `processing`
   - `processed` → duplicate success
   - `processing` → aucune deuxième mutation concurrente
   - `failed` → reclaim atomique en `processing`
5. Pour les mutations d’état abonnement: validation `occurred_at`
6. Protection hors ordre via `paddle_last_event_at`
7. Mutation métier
8. succès → `processed` + `processed_at`
9. échec → `failed` + `last_error` + `failed_at`

## Claim atomique / idempotence concurrente
- Le backend utilise `find_one_and_update(..., upsert=True, $setOnInsert=...)` pour claim un nouvel event atomiquement.
- Les retries d’un event `failed` sont re-claim atomiquement via `find_one_and_update` filtré sur `status=failed`.
- Un second delivery pendant `processing` ne rejoue pas la mutation.
- Les replays d’un event `processed` retournent une réponse idempotente sans mutation.

## Index unique
- Startup mis à jour avec: `await db.paddle_events.create_index("event_id", unique=True)`.
- Cet index rend l’unicité de `event_id` explicite et renforce la sécurité des claims atomiques.
- Le startup reste idempotent.

## Protection hors ordre avec `occurred_at`
- Les événements modifiant l’état abonnement exigent un `occurred_at` parseable.
- Le backend persiste `paddle_last_event_at` sur la subscription pour:
  - `subscription.activated`
  - `subscription.updated`
  - `subscription.canceled`
- Si un event reçu plus tard a `occurred_at < paddle_last_event_at`, il est traité comme obsolète et n’écrase pas l’état plus récent.

## Contrat `subscription.canceled`
- L’annulation n’accorde jamais d’extension artificielle.
- Si la vraie fin de période est future, Premium reste actif jusqu’à cette date.
- Sinon la subscription devient FREE.
- Un `subscription.updated active` plus ancien reçu après un `subscription.canceled` récent ne peut plus réactiver Premium.

## `transaction.completed`
- Décision conservée: `transaction.completed` ne donne pas Premium.
- Il met seulement à jour `payment_transactions` et peut être marqué `processed`.
- L’activation Premium attend un event subscription avec expiry canonique.

## Consumers audités
Recherche effectuée sur:
- `premium_expires_at`
- `paddle_last_event_at`
- `status=premium`
- `canceled` / `cancelled`
- `activate_premium`
- `renew_premium`
- `cancel_subscription`
- `paddle_events`
- `payment_transactions`
- `get_user_access`

Constat:
- Les décisions d’accès Premium restent centralisées par `access_control.get_user_access()`.
- Aucun consumer backend audité n’accorde Premium en contournant `access_control.get_user_access()`.
- `get_user_subscription()` reste un helper CRUD/display et non une source d’autorité d’accès.

## Premium expiry — fail closed
- `status=premium` + expiry future valide → PREMIUM.
- `status=premium` + expiry passée → FREE.
- `status=premium` + expiry absente → FREE.
- `status=premium` + expiry invalide → FREE.
- `check_premium_expiration()` persiste aussi le retour à FREE pour les états Premium incomplets ou invalides.

## Tests réellement exécutés
Commande exécutée:

```bash
cd /home/runner/work/sauvegarde260708/sauvegarde260708/backend && python -m pytest tests/test_paddle_integrity_pr223.py tests/test_paddle_subscription.py::TestPaddleWebhookSecurity::test_tampered_body_raises tests/test_paddle_subscription.py::TestPaddleWebhookSecurity::test_all_paddle_event_types_parse tests/test_paddle_subscription.py::TestAccessControlResolve::test_premium_no_expiry_is_free tests/test_paddle_subscription.py::TestAccessControlResolve::test_premium_not_yet_expired tests/test_paddle_subscription.py::TestAccessControlResolve::test_premium_expired_returns_free tests/test_paddle_subscription.py::TestAccessControlResolve::test_premium_invalid_expiry_is_free tests/test_paddle_subscription.py::TestAccessControlResolve::test_premium_can_all_features tests/test_paddle_subscription.py::TestAccessControlResolve::test_premium_unlimited_chat tests/test_paddle_subscription.py::TestSubscriptionManager::test_premium_expiration_sets_free tests/test_paddle_subscription.py::TestSubscriptionManager::test_premium_without_expiry_sets_free tests/test_paddle_subscription.py::TestSubscriptionManager::test_premium_with_invalid_expiry_sets_free tests/test_unique_subscription.py::TestDeduplicationStrategy::test_canceled_loses_to_free
```

Résultat exact: **31 tests passés**.

Couverture validée:
- `subscription.canceled` traité
- `subscription.updated status=canceled` traité
- `current_billing_period.ends_at` utilisé pour activated/updated
- scheduled cancel avec `next_billed_at=null` garde Premium jusqu’à fin de période
- absence / invalidité de `current_billing_period.ends_at` → fail closed
- deux deliveries simultanées même `event_id` → une seule mutation
- second delivery pendant `processing` → pas de double mutation
- `failed` → retry possible
- retry succès → `processed`
- replay `processed` → aucune mutation
- événements hors ordre ignorés via `occurred_at`
- signature invalide → aucune mutation
- `transaction.completed` → pas de Premium
- pricing canonique checkout toujours protégé
- Premium expiry future/past/missing/invalid couverte

## Runtime Paddle sandbox
- Runtime Paddle sandbox testé: **NON**
- Checkout réel / webhook signé réel / activation Premium réelle / replay runtime réel: **NON testés dans cette PR**
