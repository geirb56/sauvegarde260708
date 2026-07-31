"""
test_unique_subscription.py
============================

Tests that enforce the "one subscription per user" invariant and cover
all scenarios described in the RUNINDEX problem statement:

  - User with a single subscription
  - Legacy user with duplicate subscriptions (deduplication migration logic)
  - New user creation (starts FREE, no duplicate)
  - Trial lifecycle (activate → active → expired → FREE)
  - Premium lifecycle (activate → cancel → FREE with grace period)
  - Paddle webhook: subscription.activated / subscription.updated /
                    subscription.cancelled / idempotence
  - Backend restart: index idempotence (_ensure_subscriptions_unique_index)
  - Index creation on clean DB
  - Index creation on historical DB (non-unique index pre-exists)
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Minimal motor stub so we can import backend modules without a real MongoDB
# ---------------------------------------------------------------------------

_motor_stub = MagicMock()
_motor_stub.motor_asyncio = MagicMock()
_motor_stub.motor_asyncio.AsyncIOMotorDatabase = object
sys.modules.setdefault("motor", _motor_stub)
sys.modules.setdefault("motor.motor_asyncio", _motor_stub.motor_asyncio)

from subscription_manager import (  # noqa: E402
    SubscriptionStatus,
    TRIAL_DURATION_DAYS,
    create_free_subscription,
    create_trial_subscription,
    activate_premium,
    renew_premium,
    cancel_subscription,
    check_trial_expiration,
    check_premium_expiration,
    activate_garmin_trial,
    get_trial_days_remaining,
)
from migrations.deduplicate_subscriptions import (  # noqa: E402
    _pick_winner,
    _score,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def _future(days=30) -> str:
    return (datetime.now(timezone.utc) + timedelta(days=days)).isoformat()


def _past(hours=1) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


# ---------------------------------------------------------------------------
# In-memory MongoDB collection that enforces a unique index on user_id
# ---------------------------------------------------------------------------

class _UniqueKeyError(Exception):
    pass


class _UniqueCol:
    """
    Minimal Motor collection mock that raises on duplicate user_id inserts.
    Models the behaviour of a collection with a UNIQUE index on user_id.
    """

    def __init__(self):
        self._docs: Dict[str, dict] = {}  # user_id → doc

    async def find_one(self, q: dict, proj: Optional[dict] = None):
        uid = q.get("user_id")
        if uid is None:
            # Search by _id or other field — not needed in these tests
            return None
        doc = self._docs.get(uid)
        if doc and proj:
            return {k: v for k, v in doc.items() if proj.get(k, 1)}
        return dict(doc) if doc else None

    async def insert_one(self, doc: dict):
        uid = doc.get("user_id")
        if uid in self._docs:
            # Simulate DuplicateKeyError
            from auth.mongo_errors import DuplicateKeyError
            raise DuplicateKeyError(f"E11000 duplicate key user_id={uid}")
        self._docs[uid] = {k: v for k, v in doc.items() if k != "_id"}

    async def update_one(self, q: dict, upd: dict, upsert: bool = False):
        uid = q.get("user_id")
        existing = self._docs.get(uid)
        if existing is None:
            if upsert:
                existing = {"user_id": uid}
            else:
                return
        if "$set" in upd:
            existing.update(upd["$set"])
        self._docs[uid] = existing

    async def count_documents(self, q: dict) -> int:
        uid = q.get("user_id")
        return 1 if uid and uid in self._docs else 0

    def _all_docs(self) -> List[dict]:
        return list(self._docs.values())


class _DB:
    def __init__(self):
        self.subscriptions = _UniqueCol()
        self.garmin_trial_registry = _UniqueCol()


# ═══════════════════════════════════════════════════════════════════════════
# 1. Single subscription per user
# ═══════════════════════════════════════════════════════════════════════════

class TestSingleSubscription:
    def test_new_user_starts_free(self):
        async def go():
            db = _DB()
            sub = await create_free_subscription(db, "u_new")
            assert sub["status"] == SubscriptionStatus.FREE
            assert sub["user_id"] == "u_new"
            assert sub.get("trial_used") is False
            # Only one document exists
            assert await db.subscriptions.count_documents({"user_id": "u_new"}) == 1
        _run(go())

    def test_create_free_is_idempotent(self):
        """Calling create_free_subscription twice must not raise and must not create two docs."""
        async def go():
            db = _DB()
            sub1 = await create_free_subscription(db, "u_idem")
            sub2 = await create_free_subscription(db, "u_idem")
            assert sub1["status"] == sub2["status"] == SubscriptionStatus.FREE
            assert await db.subscriptions.count_documents({"user_id": "u_idem"}) == 1
        _run(go())

    def test_trial_creates_one_doc(self):
        async def go():
            db = _DB()
            sub = await create_trial_subscription(db, "u_trial")
            assert sub["status"] == SubscriptionStatus.TRIAL
            assert await db.subscriptions.count_documents({"user_id": "u_trial"}) == 1
        _run(go())

    def test_premium_upgrade_stays_one_doc(self):
        async def go():
            db = _DB()
            await create_free_subscription(db, "u_prem")
            exp = datetime.now(timezone.utc) + timedelta(days=30)
            sub = await activate_premium(db, "u_prem", "sub_1", "cus_1", exp)
            assert sub["status"] == SubscriptionStatus.PREMIUM
            assert await db.subscriptions.count_documents({"user_id": "u_prem"}) == 1
        _run(go())

    def test_cancel_stays_one_doc(self):
        async def go():
            db = _DB()
            await create_free_subscription(db, "u_cancel")
            exp = datetime.now(timezone.utc) + timedelta(days=15)
            await activate_premium(db, "u_cancel", "sub_x", "cus_x", exp)
            sub = await cancel_subscription(db, "u_cancel")
            assert sub is not None
            assert await db.subscriptions.count_documents({"user_id": "u_cancel"}) == 1
        _run(go())


# ═══════════════════════════════════════════════════════════════════════════
# 2. Trial lifecycle
# ═══════════════════════════════════════════════════════════════════════════

class TestTrialLifecycle:
    def test_trial_lasts_30_days(self):
        async def go():
            db = _DB()
            sub = await create_trial_subscription(db, "u_t_days")
            days = get_trial_days_remaining(sub)
            assert days is not None
            assert 28 <= days <= TRIAL_DURATION_DAYS
        _run(go())

    def test_trial_expires_to_free(self):
        async def go():
            db = _DB()
            sub = await create_trial_subscription(db, "u_t_exp")
            # Manually backdate trial_end
            sub["trial_end"] = _past(hours=1)
            db.subscriptions._docs["u_t_exp"]["trial_end"] = sub["trial_end"]
            result = await check_trial_expiration(db, sub)
            assert result["status"] == SubscriptionStatus.FREE
        _run(go())

    def test_active_trial_not_expired(self):
        async def go():
            db = _DB()
            sub = await create_trial_subscription(db, "u_t_active")
            result = await check_trial_expiration(db, sub)
            assert result["status"] == SubscriptionStatus.TRIAL
        _run(go())

    def test_trial_days_remaining_is_none_for_free(self):
        async def go():
            db = _DB()
            sub = await create_free_subscription(db, "u_free_days")
            assert get_trial_days_remaining(sub) is None
        _run(go())


# ═══════════════════════════════════════════════════════════════════════════
# 3. Premium lifecycle
# ═══════════════════════════════════════════════════════════════════════════

class TestPremiumLifecycle:
    def test_activate_premium(self):
        async def go():
            db = _DB()
            await create_free_subscription(db, "u_p_act")
            exp = datetime.now(timezone.utc) + timedelta(days=30)
            sub = await activate_premium(db, "u_p_act", "paddle_sub_123", "paddle_cus_456", exp)
            assert sub["status"] == SubscriptionStatus.PREMIUM
            assert sub["paddle_subscription_id"] == "paddle_sub_123"
        _run(go())

    def test_premium_expiry_reverts_to_free(self):
        async def go():
            db = _DB()
            await create_free_subscription(db, "u_p_exp")
            past = datetime.now(timezone.utc) - timedelta(hours=1)
            await activate_premium(db, "u_p_exp", "s", "c", past)
            sub = await db.subscriptions.find_one({"user_id": "u_p_exp"})
            result = await check_premium_expiration(db, sub)
            assert result["status"] == SubscriptionStatus.FREE
        _run(go())

    def test_cancel_no_expiry_immediate_free(self):
        async def go():
            db = _DB()
            await create_free_subscription(db, "u_p_cancel_no_exp")
            await activate_premium(db, "u_p_cancel_no_exp", "s", "c", None)
            sub = await cancel_subscription(db, "u_p_cancel_no_exp")
            assert sub["status"] == SubscriptionStatus.FREE
        _run(go())

    def test_cancel_with_future_expiry_keeps_premium_until_end(self):
        async def go():
            db = _DB()
            await create_free_subscription(db, "u_p_cancel_grace")
            future = datetime.now(timezone.utc) + timedelta(days=15)
            await activate_premium(db, "u_p_cancel_grace", "s", "c", future)
            sub = await cancel_subscription(db, "u_p_cancel_grace")
            # Status remains PREMIUM until end of paid period
            assert sub["status"] == SubscriptionStatus.PREMIUM
            assert sub.get("cancelled_at") is not None
        _run(go())

    def test_renew_extends_expiry(self):
        async def go():
            db = _DB()
            await create_free_subscription(db, "u_p_renew")
            exp1 = datetime.now(timezone.utc) + timedelta(days=30)
            await activate_premium(db, "u_p_renew", "sub_1", "cus_1", exp1)
            exp2 = datetime.now(timezone.utc) + timedelta(days=60)
            sub = await renew_premium(db, "u_p_renew", "sub_1", exp2)
            assert sub["status"] == SubscriptionStatus.PREMIUM
            exp_dt = datetime.fromisoformat(sub["premium_expires_at"].replace("Z", "+00:00"))
            assert exp_dt > datetime.now(timezone.utc) + timedelta(days=50)
        _run(go())


# ═══════════════════════════════════════════════════════════════════════════
# 4. Paddle webhook idempotence (subscription_manager + in-memory DB)
# ═══════════════════════════════════════════════════════════════════════════

class TestPaddleWebhookIdempotence:
    """
    Simulate the Paddle webhook path (activate_premium / renew_premium /
    cancel_subscription) and verify that re-delivering the same event does
    not create a second subscription document.
    """

    def test_activate_premium_idempotent(self):
        """Calling activate_premium twice for the same user must yield one doc."""
        async def go():
            db = _DB()
            await create_free_subscription(db, "u_wh_act")
            exp = datetime.now(timezone.utc) + timedelta(days=30)
            # First webhook delivery
            await activate_premium(db, "u_wh_act", "sub_paddle_1", "cus_1", exp)
            # Duplicate webhook delivery (same event re-delivered)
            await activate_premium(db, "u_wh_act", "sub_paddle_1", "cus_1", exp)
            assert await db.subscriptions.count_documents({"user_id": "u_wh_act"}) == 1
            sub = await db.subscriptions.find_one({"user_id": "u_wh_act"})
            assert sub["status"] == SubscriptionStatus.PREMIUM
        _run(go())

    def test_cancel_idempotent(self):
        """Calling cancel_subscription twice must not raise and must keep one doc."""
        async def go():
            db = _DB()
            await create_free_subscription(db, "u_wh_can")
            future = datetime.now(timezone.utc) + timedelta(days=15)
            await activate_premium(db, "u_wh_can", "sub_2", "cus_2", future)
            await cancel_subscription(db, "u_wh_can")
            await cancel_subscription(db, "u_wh_can")
            assert await db.subscriptions.count_documents({"user_id": "u_wh_can"}) == 1
        _run(go())

    def test_renew_idempotent(self):
        """Re-delivering subscription.updated (renewal) stays at one document."""
        async def go():
            db = _DB()
            await create_free_subscription(db, "u_wh_renew")
            exp1 = datetime.now(timezone.utc) + timedelta(days=30)
            await activate_premium(db, "u_wh_renew", "sub_r", "cus_r", exp1)
            exp2 = datetime.now(timezone.utc) + timedelta(days=60)
            await renew_premium(db, "u_wh_renew", "sub_r", exp2)
            await renew_premium(db, "u_wh_renew", "sub_r", exp2)  # duplicate
            assert await db.subscriptions.count_documents({"user_id": "u_wh_renew"}) == 1
        _run(go())

    def test_activate_without_prior_subscription_creates_one(self):
        """Paddle webhook may arrive before create_free_subscription runs (upsert path)."""
        async def go():
            db = _DB()
            # No subscription pre-created — activate_premium does an upsert
            exp = datetime.now(timezone.utc) + timedelta(days=30)
            await activate_premium(db, "u_wh_new", "sub_new", "cus_new", exp)
            assert await db.subscriptions.count_documents({"user_id": "u_wh_new"}) == 1
            sub = await db.subscriptions.find_one({"user_id": "u_wh_new"})
            assert sub["status"] == SubscriptionStatus.PREMIUM
        _run(go())


# ═══════════════════════════════════════════════════════════════════════════
# 5. Deduplication migration logic (_pick_winner)
# ═══════════════════════════════════════════════════════════════════════════

class TestDeduplicationStrategy:
    """Unit tests for the migration's winner-selection logic."""

    def _doc(self, status="free", updated_at=None, trial_used=False, paddle_sub=None):
        return {
            "user_id": "u_dup",
            "status": status,
            "updated_at": updated_at or datetime.now(timezone.utc).isoformat(),
            "trial_used": trial_used,
            "paddle_subscription_id": paddle_sub,
        }

    def test_premium_wins_over_free(self):
        docs = [self._doc("free"), self._doc("premium")]
        winner, losers, ambiguous = _pick_winner(docs)
        assert not ambiguous
        assert winner["status"] == "premium"
        assert len(losers) == 1
        assert losers[0]["status"] == "free"

    def test_premium_wins_over_trial(self):
        docs = [self._doc("trial"), self._doc("premium")]
        winner, losers, ambiguous = _pick_winner(docs)
        assert not ambiguous
        assert winner["status"] == "premium"

    def test_trial_wins_over_free(self):
        docs = [self._doc("free"), self._doc("trial")]
        winner, losers, ambiguous = _pick_winner(docs)
        assert not ambiguous
        assert winner["status"] == "trial"

    def test_most_recently_updated_wins_among_same_status(self):
        old = self._doc("free", updated_at=_past(hours=48))
        new = self._doc("free", updated_at=datetime.now(timezone.utc).isoformat())
        winner, losers, ambiguous = _pick_winner([old, new])
        assert not ambiguous
        assert winner["updated_at"] == new["updated_at"]

    def test_early_adopter_treated_as_premium(self):
        docs = [self._doc("early_adopter"), self._doc("free")]
        winner, losers, ambiguous = _pick_winner(docs)
        assert winner["status"] == "early_adopter"

    def test_legacy_active_wins_over_trial(self):
        docs = [self._doc("trial"), self._doc("active")]
        winner, losers, ambiguous = _pick_winner(docs)
        assert winner["status"] == "active"

    def test_cancelled_loses_to_free(self):
        docs = [self._doc("cancelled"), self._doc("free")]
        winner, losers, ambiguous = _pick_winner(docs)
        assert winner["status"] == "free"

    def test_single_doc_no_ambiguity(self):
        winner, losers, ambiguous = _pick_winner([self._doc("free")])
        assert not ambiguous
        assert winner["status"] == "free"
        assert losers == []

    def test_ambiguous_detected_for_identical_docs(self):
        now = datetime.now(timezone.utc).isoformat()
        doc1 = self._doc("free", updated_at=now)
        doc2 = self._doc("free", updated_at=now)
        _, _, ambiguous = _pick_winner([doc1, doc2])
        assert ambiguous


# ═══════════════════════════════════════════════════════════════════════════
# 6. Index idempotence (_ensure_subscriptions_unique_index)
# ═══════════════════════════════════════════════════════════════════════════

class TestIndexIdempotence:
    """
    Test _ensure_subscriptions_unique_index without a real MongoDB by mocking
    the collection's list_indexes / drop_index / create_index.
    """

    def _make_col(self, indexes: list):
        """
        Return a mock Motor collection whose list_indexes() yields `indexes`.
        Each item in `indexes` is a dict with at least 'name' and 'key'.
        """
        col = MagicMock()

        async def _list_indexes():
            for idx in indexes:
                yield idx

        col.list_indexes = _list_indexes
        col.drop_index = AsyncMock()
        col.create_index = AsyncMock()
        return col

    def _make_db(self, indexes: list):
        db = MagicMock()
        db.subscriptions = self._make_col(indexes)
        return db

    def test_unique_index_already_exists_no_op(self):
        """If the UNIQUE index is already there, no drop or create should happen."""
        async def go():
            from services.subscription_index import ensure_subscriptions_unique_index
            db = self._make_db([
                {"name": "user_id_1", "key": {"user_id": 1}, "unique": True, "sparse": True},
            ])
            await ensure_subscriptions_unique_index(db)
            db.subscriptions.drop_index.assert_not_called()
            db.subscriptions.create_index.assert_not_called()
        _run(go())

    def test_non_unique_index_is_dropped_and_recreated(self):
        """Legacy non-unique index must be dropped and a UNIQUE one created."""
        async def go():
            from services.subscription_index import ensure_subscriptions_unique_index
            db = self._make_db([
                {"name": "user_id_1", "key": {"user_id": 1}},  # no "unique" key → non-unique
            ])
            await ensure_subscriptions_unique_index(db)
            db.subscriptions.drop_index.assert_called_once_with("user_id_1")
            db.subscriptions.create_index.assert_called_once()
            call_args = db.subscriptions.create_index.call_args
            assert call_args[1].get("unique") is True
        _run(go())

    def test_no_index_creates_unique(self):
        """On a clean DB (no user_id index at all), the UNIQUE one is created."""
        async def go():
            from services.subscription_index import ensure_subscriptions_unique_index
            db = self._make_db([
                {"name": "_id_", "key": {"_id": 1}},  # only the default _id index
            ])
            await ensure_subscriptions_unique_index(db)
            db.subscriptions.drop_index.assert_not_called()
            db.subscriptions.create_index.assert_called_once()
            call_args = db.subscriptions.create_index.call_args
            assert call_args[1].get("unique") is True
        _run(go())

    def test_backend_restart_idempotent(self):
        """Calling ensure_subscriptions_unique_index twice on a DB that already
        has the UNIQUE index must be a no-op on the second call."""
        async def go():
            from services.subscription_index import ensure_subscriptions_unique_index
            db = self._make_db([
                {"name": "user_id_1", "key": {"user_id": 1}, "unique": True, "sparse": True},
            ])
            await ensure_subscriptions_unique_index(db)
            await ensure_subscriptions_unique_index(db)
            db.subscriptions.drop_index.assert_not_called()
            db.subscriptions.create_index.assert_not_called()
        _run(go())

    def test_duplicates_prevent_index_no_data_deleted(self):
        """
        Scenario 4: if MongoDB refuses to create the unique index because duplicate
        user_id values exist (OperationFailure), ensure_subscriptions_unique_index
        must re-raise the error WITHOUT deleting or modifying any document.
        """
        async def go():
            import pymongo.errors
            from services.subscription_index import ensure_subscriptions_unique_index
            col = self._make_col([{"name": "_id_", "key": {"_id": 1}}])
            # Simulate MongoDB refusing the unique index due to duplicate keys.
            col.create_index = AsyncMock(
                side_effect=pymongo.errors.OperationFailure(
                    "E11000 duplicate key error: cannot build unique index over duplicate values"
                )
            )
            col.delete_one = AsyncMock()
            col.delete_many = AsyncMock()
            db = MagicMock()
            db.subscriptions = col
            with pytest.raises(pymongo.errors.OperationFailure):
                await ensure_subscriptions_unique_index(db)
            # No data must have been deleted.
            col.delete_one.assert_not_called()
            col.delete_many.assert_not_called()
        _run(go())


# ═══════════════════════════════════════════════════════════════════════════
# 7. Two subscriptions for same user must be rejected
# ═══════════════════════════════════════════════════════════════════════════

class TestUniqueConstraintEnforced:
    """
    The _UniqueCol enforces the uniqueness invariant. These tests verify
    that the subscription_manager handles DuplicateKeyError correctly.
    """

    def test_create_free_twice_raises_and_returns_existing(self):
        """create_free_subscription must be idempotent, not create a duplicate."""
        async def go():
            db = _DB()
            s1 = await create_free_subscription(db, "u_dup_free")
            s2 = await create_free_subscription(db, "u_dup_free")
            # Must return the existing doc, not raise
            assert s1["user_id"] == s2["user_id"]
            assert await db.subscriptions.count_documents({"user_id": "u_dup_free"}) == 1
        _run(go())

    def test_activate_premium_upsert_does_not_duplicate(self):
        """activate_premium uses update_one(upsert=True) — never insert_one."""
        async def go():
            db = _DB()
            await create_free_subscription(db, "u_dup_prem")
            exp = datetime.now(timezone.utc) + timedelta(days=30)
            await activate_premium(db, "u_dup_prem", "s1", "c1", exp)
            await activate_premium(db, "u_dup_prem", "s1", "c1", exp)
            assert await db.subscriptions.count_documents({"user_id": "u_dup_prem"}) == 1
        _run(go())


# ═══════════════════════════════════════════════════════════════════════════
# 8. Migration write-control: DRY_RUN vs. real run
# ═══════════════════════════════════════════════════════════════════════════

class TestMigrationWriteControl:
    """
    Scenarios 5 & 6:
      - DRY_RUN=True  → delete_many must NEVER be called even when duplicates exist.
      - DRY_RUN=False → delete_many IS called, but only for the losing document(s);
                        the winner is never deleted.
    """

    def _dup_groups(self):
        """One user_id with two docs: premium (winner) and free (loser)."""
        now = datetime.now(timezone.utc).isoformat()
        old = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
        return [
            {
                "_id": "u_mig_dup",
                "count": 2,
                "docs": [
                    {
                        "_id": "id_prem",
                        "user_id": "u_mig_dup",
                        "status": "premium",
                        "updated_at": now,
                        "paddle_subscription_id": "paddle_sub_abc",
                    },
                    {
                        "_id": "id_free",
                        "user_id": "u_mig_dup",
                        "status": "free",
                        "updated_at": old,
                        "paddle_subscription_id": None,
                    },
                ],
            }
        ]

    def _make_col_and_client(self, dup_groups):
        """
        Build a fully-async mock Motor collection and matching client stub
        that the migration's run() function can use without a real MongoDB.
        """
        col = MagicMock()
        col.delete_many = AsyncMock(return_value=MagicMock(deleted_count=1))
        col.create_index = AsyncMock()
        col.drop_index = AsyncMock()

        async def _list_indexes():
            yield {"name": "_id_", "key": {"_id": 1}}
        col.list_indexes = _list_indexes

        # aggregate(pipeline).to_list(length=None) must be awaitable.
        agg_cursor = MagicMock()
        agg_cursor.to_list = AsyncMock(return_value=dup_groups)
        col.aggregate = MagicMock(return_value=agg_cursor)

        db = MagicMock()
        db.subscriptions = col

        client = MagicMock()
        client.__getitem__ = MagicMock(return_value=db)
        client.close = MagicMock()
        return col, client

    def _patch_motor_client(self, client):
        """Point the already-stubbed motor module at our fake client."""
        import sys
        sys.modules["motor.motor_asyncio"].AsyncIOMotorClient = MagicMock(
            return_value=client
        )

    def test_dry_run_never_calls_delete_many(self):
        """
        Scenario 5: DRY_RUN=True — even when duplicates are present,
        delete_many must never be called on the collection.
        """
        async def go():
            from migrations.deduplicate_subscriptions import run
            col, client = self._make_col_and_client(self._dup_groups())
            self._patch_motor_client(client)
            result = await run(dry_run=True)
            assert result == 0
            col.delete_many.assert_not_called()
        _run(go())

    def test_real_run_deletes_only_losers(self):
        """
        Scenario 6: DRY_RUN=False — delete_many is called exactly once,
        for the loser (free) document only; the winner (premium) is never deleted.
        Paddle data is preserved because the winner carries paddle_subscription_id.
        """
        async def go():
            from migrations.deduplicate_subscriptions import run
            col, client = self._make_col_and_client(self._dup_groups())
            self._patch_motor_client(client)
            result = await run(dry_run=False)
            assert result == 0
            col.delete_many.assert_called_once()
            ids_deleted = col.delete_many.call_args[0][0]["_id"]["$in"]
            # Loser (free / no Paddle ID) must be deleted.
            assert "id_free" in ids_deleted
            # Winner (premium + Paddle subscription) must NOT be deleted.
            assert "id_prem" not in ids_deleted
        _run(go())
