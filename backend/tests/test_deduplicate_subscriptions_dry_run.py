"""
tests/test_deduplicate_subscriptions_dry_run.py
=================================================

Focused tests for the DRY_RUN mode of
``migrations/deduplicate_subscriptions.py``.

Verifies that --dry-run (the default):
  - never modifies any data (no delete_many / drop_index / create_index called);
  - lists every user_id that has duplicate subscriptions;
  - identifies the document to keep (winner) and those that would be deleted;
  - correctly reports ambiguous cases that need manual review;
  - returns exit-code 0 for clean databases and resolvable duplicates,
    and exit-code 1 for ambiguous duplicates.

All tests run without a real MongoDB connection by using the same Motor stub
pattern as the existing test_unique_subscription.py suite.
"""

from __future__ import annotations

import asyncio
import logging
import sys
from datetime import datetime, timezone, timedelta
from typing import List
from unittest.mock import AsyncMock, MagicMock

import pytest

# ---------------------------------------------------------------------------
# Motor stub (same pattern as test_unique_subscription.py)
# ---------------------------------------------------------------------------

_motor_stub = MagicMock()
_motor_stub.motor_asyncio = MagicMock()
_motor_stub.motor_asyncio.AsyncIOMotorDatabase = object
sys.modules.setdefault("motor", _motor_stub)
sys.modules.setdefault("motor.motor_asyncio", _motor_stub.motor_asyncio)

# Import only after stubbing motor.
from migrations.deduplicate_subscriptions import (  # noqa: E402
    _build_dedup_plan,
    _log_dry_run_plan,
    _parse_args,
    _pick_winner,
    run,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _run(coro):
    return asyncio.run(coro)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _past(hours: int = 2) -> str:
    return (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()


def _doc(
    _id: str,
    user_id: str,
    status: str = "free",
    updated_at: str | None = None,
) -> dict:
    return {
        "_id": _id,
        "user_id": user_id,
        "status": status,
        "updated_at": updated_at or _now(),
    }


def _group(user_id: str, docs: list) -> dict:
    """Build an aggregation group dict as returned by MongoDB."""
    return {"_id": user_id, "count": len(docs), "docs": docs}


def _make_col_and_client(dup_groups: list):
    """
    Return a (col, client) pair where col is a fully-async mock Motor
    collection backed by ``dup_groups`` as the aggregation result.
    """
    col = MagicMock()
    col.delete_many = AsyncMock(return_value=MagicMock(deleted_count=1))
    col.create_index = AsyncMock()
    col.drop_index = AsyncMock()

    async def _list_indexes():
        yield {"name": "_id_", "key": {"_id": 1}}

    col.list_indexes = _list_indexes

    agg_cursor = MagicMock()
    agg_cursor.to_list = AsyncMock(return_value=dup_groups)
    col.aggregate = MagicMock(return_value=agg_cursor)

    db = MagicMock()
    db.subscriptions = col

    client = MagicMock()
    client.__getitem__ = MagicMock(return_value=db)
    client.close = MagicMock()
    return col, client


def _patch_motor(client):
    sys.modules["motor.motor_asyncio"].AsyncIOMotorClient = MagicMock(
        return_value=client
    )


# ═══════════════════════════════════════════════════════════════════════════
# 1. _build_dedup_plan — pure unit tests (no MongoDB needed)
# ═══════════════════════════════════════════════════════════════════════════

class TestBuildDedupPlan:
    """Tests for the pure _build_dedup_plan() helper."""

    def test_empty_groups_returns_empty_plan(self):
        plan, needs_review = _build_dedup_plan([])
        assert plan == []
        assert needs_review == []

    def test_single_user_with_two_unambiguous_docs(self):
        docs = [
            _doc("id_prem", "u1", "premium", _now()),
            _doc("id_free", "u1", "free",    _past(2)),
        ]
        plan, needs_review = _build_dedup_plan([_group("u1", docs)])

        assert needs_review == []
        assert len(plan) == 1
        winner, losers = plan[0]
        assert winner["status"] == "premium"
        assert winner["_id"] == "id_prem"
        assert len(losers) == 1
        assert losers[0]["_id"] == "id_free"

    def test_multiple_users_all_resolvable(self):
        groups = [
            _group("u1", [
                _doc("u1_a", "u1", "premium", _now()),
                _doc("u1_b", "u1", "free",    _past(4)),
            ]),
            _group("u2", [
                _doc("u2_a", "u2", "trial",   _now()),
                _doc("u2_b", "u2", "free",    _past(6)),
            ]),
        ]
        plan, needs_review = _build_dedup_plan(groups)

        assert needs_review == []
        assert len(plan) == 2

        # User u1: premium wins
        winner1, losers1 = next(
            (w, l) for w, l in plan if w["user_id"] == "u1"
        )
        assert winner1["status"] == "premium"
        assert len(losers1) == 1

        # User u2: trial wins
        winner2, losers2 = next(
            (w, l) for w, l in plan if w["user_id"] == "u2"
        )
        assert winner2["status"] == "trial"
        assert len(losers2) == 1

    def test_ambiguous_docs_go_to_needs_review(self):
        ts = _now()
        docs = [
            _doc("id_a", "u_amb", "free", ts),
            _doc("id_b", "u_amb", "free", ts),
        ]
        plan, needs_review = _build_dedup_plan([_group("u_amb", docs)])

        assert plan == []
        assert len(needs_review) == 1
        assert needs_review[0]["user_id"] == "u_amb"
        assert len(needs_review[0]["docs"]) == 2

    def test_mixed_resolvable_and_ambiguous(self):
        ts = _now()
        groups = [
            # Resolvable
            _group("u_ok", [
                _doc("ok_a", "u_ok", "premium", _now()),
                _doc("ok_b", "u_ok", "free",    _past(8)),
            ]),
            # Ambiguous
            _group("u_amb", [
                _doc("amb_a", "u_amb", "free", ts),
                _doc("amb_b", "u_amb", "free", ts),
            ]),
        ]
        plan, needs_review = _build_dedup_plan(groups)

        assert len(plan) == 1
        assert len(needs_review) == 1

    def test_three_docs_two_losers(self):
        docs = [
            _doc("id_prem",  "u3", "premium",    _now()),
            _doc("id_trial", "u3", "trial",      _past(1)),
            _doc("id_free",  "u3", "free",       _past(10)),
        ]
        plan, needs_review = _build_dedup_plan([_group("u3", docs)])

        assert needs_review == []
        winner, losers = plan[0]
        assert winner["status"] == "premium"
        assert len(losers) == 2
        loser_ids = {l["_id"] for l in losers}
        assert "id_trial" in loser_ids
        assert "id_free"  in loser_ids

    def test_winner_user_id_matches_group(self):
        docs = [
            _doc("a", "user_xyz", "premium", _now()),
            _doc("b", "user_xyz", "free",    _past(3)),
        ]
        plan, _ = _build_dedup_plan([_group("user_xyz", docs)])
        winner, _ = plan[0]
        assert winner["user_id"] == "user_xyz"

    def test_loser_never_equals_winner(self):
        docs = [
            _doc("keep_me",   "u_x", "premium", _now()),
            _doc("delete_me", "u_x", "free",    _past(5)),
        ]
        plan, _ = _build_dedup_plan([_group("u_x", docs)])
        winner, losers = plan[0]
        assert all(loser["_id"] != winner["_id"] for loser in losers)


# ═══════════════════════════════════════════════════════════════════════════
# 2. DRY_RUN output — log capture tests
# ═══════════════════════════════════════════════════════════════════════════

class TestDryRunOutput:
    """
    Verify that _log_dry_run_plan emits the expected content to the logger.
    Uses pytest caplog to capture log records.
    """

    def _make_plan(self) -> tuple:
        """One resolvable user + one ambiguous user."""
        docs_ok = [
            _doc("w1", "u_ok",  "premium", _now()),
            _doc("l1", "u_ok",  "free",    _past(3)),
        ]
        ts = _now()
        docs_amb = [
            _doc("a1", "u_amb", "free", ts),
            _doc("a2", "u_amb", "free", ts),
        ]
        groups = [_group("u_ok", docs_ok), _group("u_amb", docs_amb)]
        return _build_dedup_plan(groups)

    def test_plan_header_emitted(self, caplog):
        plan, needs_review = self._make_plan()
        with caplog.at_level(logging.INFO, logger="migrations.deduplicate_subscriptions"):
            _log_dry_run_plan(plan, needs_review)
        combined = "\n".join(caplog.messages)
        assert "DRY RUN" in combined

    def test_duplicate_user_id_listed(self, caplog):
        plan, needs_review = self._make_plan()
        with caplog.at_level(logging.INFO, logger="migrations.deduplicate_subscriptions"):
            _log_dry_run_plan(plan, needs_review)
        combined = "\n".join(caplog.messages)
        assert "u_ok" in combined

    def test_winner_marked_keep(self, caplog):
        plan, needs_review = self._make_plan()
        with caplog.at_level(logging.INFO, logger="migrations.deduplicate_subscriptions"):
            _log_dry_run_plan(plan, needs_review)
        # KEEP line must reference the winner's _id
        keep_lines = [m for m in caplog.messages if "KEEP" in m]
        assert keep_lines, "Expected at least one KEEP line in log output"
        assert any("w1" in line for line in keep_lines), (
            "Winner _id 'w1' should appear in a KEEP log line"
        )

    def test_loser_marked_delete(self, caplog):
        plan, needs_review = self._make_plan()
        with caplog.at_level(logging.INFO, logger="migrations.deduplicate_subscriptions"):
            _log_dry_run_plan(plan, needs_review)
        delete_lines = [m for m in caplog.messages if "DELETE" in m]
        assert delete_lines, "Expected at least one DELETE line in log output"
        assert any("l1" in line for line in delete_lines), (
            "Loser _id 'l1' should appear in a DELETE log line"
        )

    def test_winner_never_in_delete_lines(self, caplog):
        plan, needs_review = self._make_plan()
        with caplog.at_level(logging.INFO, logger="migrations.deduplicate_subscriptions"):
            _log_dry_run_plan(plan, needs_review)
        delete_lines = [m for m in caplog.messages if "DELETE" in m]
        assert not any("w1" in line for line in delete_lines), (
            "Winner _id 'w1' must not appear in any DELETE log line"
        )

    def test_loser_never_in_keep_lines(self, caplog):
        plan, needs_review = self._make_plan()
        with caplog.at_level(logging.INFO, logger="migrations.deduplicate_subscriptions"):
            _log_dry_run_plan(plan, needs_review)
        keep_lines = [m for m in caplog.messages if "KEEP" in m]
        assert not any("l1" in line for line in keep_lines), (
            "Loser _id 'l1' must not appear in any KEEP log line"
        )

    def test_ambiguous_user_listed_in_review(self, caplog):
        plan, needs_review = self._make_plan()
        with caplog.at_level(logging.WARNING, logger="migrations.deduplicate_subscriptions"):
            _log_dry_run_plan(plan, needs_review)
        combined = "\n".join(caplog.messages)
        assert "u_amb" in combined

    def test_totals_reflect_plan_size(self, caplog):
        plan, needs_review = self._make_plan()
        with caplog.at_level(logging.INFO, logger="migrations.deduplicate_subscriptions"):
            _log_dry_run_plan(plan, needs_review)
        combined = "\n".join(caplog.messages)
        # 1 resolvable + 1 ambiguous = 2 groups total
        assert "2" in combined

    def test_no_plan_no_output_except_header(self, caplog):
        """An empty plan (clean database) still emits the header."""
        with caplog.at_level(logging.INFO, logger="migrations.deduplicate_subscriptions"):
            _log_dry_run_plan([], [])
        assert any("DRY RUN" in m for m in caplog.messages)
        # No KEEP or DELETE lines expected
        assert not any("KEEP" in m for m in caplog.messages)
        assert not any("DELETE" in m for m in caplog.messages)

    def test_multiple_losers_all_appear_in_delete_lines(self, caplog):
        docs = [
            _doc("w_multi",  "u_multi", "premium", _now()),
            _doc("l_trial",  "u_multi", "trial",   _past(1)),
            _doc("l_free",   "u_multi", "free",    _past(5)),
        ]
        plan, needs_review = _build_dedup_plan([_group("u_multi", docs)])
        with caplog.at_level(logging.INFO, logger="migrations.deduplicate_subscriptions"):
            _log_dry_run_plan(plan, needs_review)
        delete_lines = [m for m in caplog.messages if "DELETE" in m]
        assert any("l_trial" in line for line in delete_lines)
        assert any("l_free"  in line for line in delete_lines)


# ═══════════════════════════════════════════════════════════════════════════
# 3. run() — DRY_RUN=True integration tests (mocked Motor)
# ═══════════════════════════════════════════════════════════════════════════

class TestRunDryRunMode:
    """
    Integration-level tests for run(dry_run=True).

    All use a mocked Motor client — no real MongoDB required.
    """

    def test_clean_db_returns_0_no_writes(self):
        """No duplicates → exit 0, no delete/index modifications."""
        async def go():
            col, client = _make_col_and_client([])
            _patch_motor(client)
            result = await run(dry_run=True)
            assert result == 0
            col.delete_many.assert_not_called()
        _run(go())

    def test_duplicates_present_returns_0_no_writes(self):
        """Resolvable duplicates present → exit 0, no delete_many called."""
        async def go():
            groups = [_group("u1", [
                _doc("id_prem", "u1", "premium", _now()),
                _doc("id_free", "u1", "free",    _past(3)),
            ])]
            col, client = _make_col_and_client(groups)
            _patch_motor(client)
            result = await run(dry_run=True)
            assert result == 0
            col.delete_many.assert_not_called()
        _run(go())

    def test_dry_run_does_not_create_index(self):
        """DRY_RUN must not create a new index on the collection."""
        async def go():
            groups = [_group("u2", [
                _doc("x", "u2", "premium", _now()),
                _doc("y", "u2", "free",    _past(2)),
            ])]
            col, client = _make_col_and_client(groups)
            _patch_motor(client)
            await run(dry_run=True)
            col.create_index.assert_not_called()
        _run(go())

    def test_dry_run_does_not_drop_index(self):
        """DRY_RUN must not drop any existing index."""
        async def go():
            col, client = _make_col_and_client([])
            _patch_motor(client)
            await run(dry_run=True)
            col.drop_index.assert_not_called()
        _run(go())

    def test_ambiguous_duplicates_returns_1_no_writes(self):
        """Ambiguous duplicates → exit 1, no write operations."""
        async def go():
            ts = _now()
            groups = [_group("u_amb", [
                _doc("a1", "u_amb", "free", ts),
                _doc("a2", "u_amb", "free", ts),
            ])]
            col, client = _make_col_and_client(groups)
            _patch_motor(client)
            result = await run(dry_run=True)
            assert result == 1
            col.delete_many.assert_not_called()
            col.create_index.assert_not_called()
            col.drop_index.assert_not_called()
        _run(go())

    def test_dry_run_multiple_users_no_writes(self):
        """Multiple users with duplicates — all resolvable — exit 0, no writes."""
        async def go():
            groups = [
                _group("u_a", [
                    _doc("a1", "u_a", "premium", _now()),
                    _doc("a2", "u_a", "free",    _past(2)),
                ]),
                _group("u_b", [
                    _doc("b1", "u_b", "trial",   _now()),
                    _doc("b2", "u_b", "free",    _past(5)),
                    _doc("b3", "u_b", "expired", _past(10)),
                ]),
            ]
            col, client = _make_col_and_client(groups)
            _patch_motor(client)
            result = await run(dry_run=True)
            assert result == 0
            col.delete_many.assert_not_called()
        _run(go())

    def test_dry_run_logs_duplicate_user_ids(self, caplog):
        """Verify the log output includes the user_id of each duplicate group."""
        async def go():
            groups = [_group("user_abc", [
                _doc("p1", "user_abc", "premium", _now()),
                _doc("f1", "user_abc", "free",    _past(3)),
            ])]
            col, client = _make_col_and_client(groups)
            _patch_motor(client)
            with caplog.at_level(logging.INFO, logger="migrations.deduplicate_subscriptions"):
                await run(dry_run=True)
        _run(go())
        combined = "\n".join(caplog.messages)
        assert "user_abc" in combined

    def test_dry_run_logs_winner_and_loser_ids(self, caplog):
        """Winner _id appears in a KEEP line; loser _id in a DELETE line."""
        async def go():
            groups = [_group("u_wl", [
                _doc("winner_id", "u_wl", "premium", _now()),
                _doc("loser_id",  "u_wl", "free",    _past(4)),
            ])]
            col, client = _make_col_and_client(groups)
            _patch_motor(client)
            with caplog.at_level(logging.INFO, logger="migrations.deduplicate_subscriptions"):
                await run(dry_run=True)
        _run(go())
        keep_lines   = [m for m in caplog.messages if "KEEP"   in m]
        delete_lines = [m for m in caplog.messages if "DELETE" in m]
        assert any("winner_id" in line for line in keep_lines)
        assert any("loser_id"  in line for line in delete_lines)


# ═══════════════════════════════════════════════════════════════════════════
# 4. _parse_args — CLI argument parsing
# ═══════════════════════════════════════════════════════════════════════════

class TestParseArgs:
    """Tests for the CLI argument parser."""

    def test_no_args_defaults_to_dry_run(self, monkeypatch):
        """With no CLI args and DRY_RUN env unset, dry_run must be True."""
        monkeypatch.delenv("DRY_RUN", raising=False)
        assert _parse_args([]) is True

    def test_explicit_dry_run_flag(self, monkeypatch):
        monkeypatch.delenv("DRY_RUN", raising=False)
        assert _parse_args(["--dry-run"]) is True

    def test_apply_flag_returns_false(self, monkeypatch):
        monkeypatch.delenv("DRY_RUN", raising=False)
        assert _parse_args(["--apply"]) is False

    def test_env_dry_run_false_without_flag(self, monkeypatch):
        """DRY_RUN=false env var → dry_run=False when no CLI flag given."""
        monkeypatch.setenv("DRY_RUN", "false")
        assert _parse_args([]) is False

    def test_env_dry_run_0_without_flag(self, monkeypatch):
        monkeypatch.setenv("DRY_RUN", "0")
        assert _parse_args([]) is False

    def test_cli_apply_overrides_env_dry_run_true(self, monkeypatch):
        """CLI --apply overrides DRY_RUN=true env var."""
        monkeypatch.setenv("DRY_RUN", "true")
        assert _parse_args(["--apply"]) is False

    def test_cli_dry_run_overrides_env_dry_run_false(self, monkeypatch):
        """CLI --dry-run overrides DRY_RUN=false env var."""
        monkeypatch.setenv("DRY_RUN", "false")
        assert _parse_args(["--dry-run"]) is True
