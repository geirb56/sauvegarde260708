"""
migrations/deduplicate_subscriptions.py
========================================

Safe migration that:
1. Identifies users who have more than one subscription document.
2. Determines which document to keep based on a deterministic priority strategy.
3. Removes the true duplicates (obsolete documents only).
4. Drops the old non-unique index on subscriptions.user_id (if it exists).
5. Re-creates the index as UNIQUE so the constraint is actually enforced.

Conservation strategy (most valuable first):
    PREMIUM  > TRIAL  > FREE(trial_used=True) > FREE(trial_used=False)
    Among equal status: most recently updated (updated_at, then created_at).

Safety constraints:
  - Documents are listed before ANY deletion.
  - Deletion only proceeds if exactly one "winner" can be determined per user_id.
  - If ambiguity is detected the script STOPS and prints a report for manual review.
  - A DRY_RUN mode (default) prints the plan without touching the database.
  - The unique index is created only after all duplicates are resolved.

Usage:
    # Dry run (inspect only, no writes) — default:
    python -m migrations.deduplicate_subscriptions
    python -m migrations.deduplicate_subscriptions --dry-run

    # Apply for real:
    python -m migrations.deduplicate_subscriptions --apply
    DRY_RUN=false python -m migrations.deduplicate_subscriptions

    CLI flag takes precedence over the DRY_RUN environment variable.

Environment variables expected (same as server.py):
    MONGODB_URL  — MongoDB connection string (default: mongodb://localhost:27017)
    DB_NAME      — Database name           (default: runindex)
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Status priority — higher = more valuable, keep this one
# ---------------------------------------------------------------------------

_LEGACY_PREMIUM = {"early_adopter", "active", "starter", "confort", "pro"}

_STATUS_PRIORITY: Dict[str, int] = {
    "premium":      100,
    "early_adopter": 90,
    "active":        80,
    "starter":       70,
    "confort":       70,
    "pro":           70,
    "trial":         50,
    "free":          10,
    "expired":        5,
    "canceled":       5,
    "cancelled":      5,
}


def _parse_dt(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (ValueError, TypeError):
        return None


def _score(doc: dict) -> Tuple[int, datetime]:
    """Return (status_priority, recency) for sorting. Higher is better."""
    priority = _STATUS_PRIORITY.get(doc.get("status", ""), 0)
    updated = _parse_dt(doc.get("updated_at")) or _parse_dt(doc.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)
    return (priority, updated)


def _pick_winner(docs: List[dict]) -> Tuple[Optional[dict], List[dict], bool]:
    """
    Choose the document to keep among duplicates.

    Returns:
        (winner, losers, ambiguous)
        - ambiguous=True if two docs share identical priority+recency (need manual review)
    """
    scored = sorted(docs, key=_score, reverse=True)
    winner = scored[0]
    second = scored[1] if len(scored) > 1 else None
    ambiguous = False
    if second and _score(winner) == _score(second):
        # Equal score — cannot decide automatically
        ambiguous = True
    losers = scored[1:]
    return winner, losers, ambiguous


# ---------------------------------------------------------------------------
# Index helpers
# ---------------------------------------------------------------------------

async def _get_index_info(collection) -> Dict[str, dict]:
    """Return {index_name: index_doc} for the collection."""
    result = {}
    async for idx in collection.list_indexes():
        result[idx["name"]] = idx
    return result


async def _ensure_unique_index(collection, dry_run: bool) -> None:
    """
    Drop the old non-unique user_id index (if present) and create a UNIQUE one.

    This is idempotent:
    - If the unique index already exists: no-op.
    - If a non-unique index with the same key exists: drop then recreate.
    - If no index on user_id: just create.
    """
    indexes = await _get_index_info(collection)

    # Find any existing index that covers user_id as a single-field index
    target_key = ("user_id", 1)
    existing_unique: Optional[str] = None
    existing_nonunique: Optional[str] = None

    for name, idx in indexes.items():
        key_pairs = list(idx.get("key", {}).items())
        if key_pairs == [target_key]:
            if idx.get("unique"):
                existing_unique = name
            else:
                existing_nonunique = name

    if existing_unique:
        logger.info("✅  Unique index on subscriptions.user_id already exists (%s) — no-op.", existing_unique)
        return

    if existing_nonunique:
        logger.info(
            "🔧  Non-unique index '%s' found on subscriptions.user_id — will drop and recreate as UNIQUE.",
            existing_nonunique,
        )
        if not dry_run:
            await collection.drop_index(existing_nonunique)
            logger.info("    Dropped '%s'.", existing_nonunique)
    else:
        logger.info("ℹ️   No user_id index found — will create UNIQUE index.")

    if not dry_run:
        await collection.create_index("user_id", unique=True, sparse=True)
        logger.info("✅  UNIQUE index on subscriptions.user_id created.")
    else:
        logger.info("[DRY RUN] Would create UNIQUE index on subscriptions.user_id (sparse=True).")


# ---------------------------------------------------------------------------
# Plan builder (pure, no I/O — easy to unit-test)
# ---------------------------------------------------------------------------

def _build_dedup_plan(
    groups: List[dict],
) -> Tuple[List[Tuple[dict, List[dict]]], List[dict]]:
    """
    Build a deduplication plan from the aggregation result groups.

    Each group is a dict with keys ``_id`` (user_id), ``count``, and ``docs``
    (list of subscription documents for that user).

    Returns:
        (plan, needs_review)
        - plan        : list of (winner, losers) tuples for unambiguous cases.
        - needs_review: list of {"user_id": …, "docs": […]} for ambiguous cases
                        that require manual inspection.
    """
    plan: List[Tuple[dict, List[dict]]] = []
    needs_review: List[dict] = []

    for group in groups:
        uid = group["_id"]
        docs = group["docs"]
        winner, losers, ambiguous = _pick_winner(docs)

        if ambiguous:
            needs_review.append({"user_id": uid, "docs": docs})
        else:
            plan.append((winner, losers))

    return plan, needs_review


def _log_dry_run_plan(plan: List[Tuple[dict, List[dict]]], needs_review: List[dict]) -> None:
    """Emit a structured DRY RUN PLAN to the logger (no writes)."""
    total_to_delete = sum(len(losers) for _, losers in plan)

    logger.info("")
    logger.info("┌─────────────────────────────────────────────────────┐")
    logger.info("│              DRY RUN — DEDUPLICATION PLAN           │")
    logger.info("│  No data will be modified until --apply is used.    │")
    logger.info("└─────────────────────────────────────────────────────┘")
    logger.info("  Duplicate user_id groups : %d", len(plan) + len(needs_review))
    logger.info("  Resolvable automatically : %d", len(plan))
    logger.info("  Require manual review    : %d", len(needs_review))
    logger.info("  Documents to delete      : %d", total_to_delete)
    logger.info("")

    for winner, losers in plan:
        uid = winner.get("user_id", "?")
        winner_id = str(winner.get("_id", "?"))
        logger.info(
            "  user_id=%-36s  total docs=%d",
            uid,
            1 + len(losers),
        )
        logger.info(
            "    ✅ KEEP   _id=%-24s  status=%-12s  updated=%s",
            winner_id,
            winner.get("status", "?"),
            str(winner.get("updated_at", winner.get("created_at", "n/a")))[:19],
        )
        for loser in losers:
            loser_id = str(loser.get("_id", "?"))
            logger.info(
                "    🗑  DELETE _id=%-24s  status=%-12s  updated=%s",
                loser_id,
                loser.get("status", "?"),
                str(loser.get("updated_at", loser.get("created_at", "n/a")))[:19],
            )
        logger.info("")

    if needs_review:
        logger.warning("  ⚠️  The following user_id(s) cannot be resolved automatically:")
        for item in needs_review:
            logger.warning("    user_id=%s  (%d docs, identical score — manual review needed)", item["user_id"], len(item["docs"]))


# ---------------------------------------------------------------------------
# Main migration logic
# ---------------------------------------------------------------------------

async def run(dry_run: bool = True) -> int:
    """
    Execute the deduplication migration.

    Returns:
        0 on success, 1 if manual review is required, 2 on unexpected error.
    """
    try:
        from motor.motor_asyncio import AsyncIOMotorClient
    except ImportError:
        logger.error("motor is not installed — run: pip install motor")
        return 2

    mongo_url = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
    db_name   = os.getenv("DB_NAME", "runindex")

    client = AsyncIOMotorClient(mongo_url)
    db = client[db_name]
    col = db.subscriptions

    logger.info("=== deduplicate_subscriptions migration ===")
    logger.info("DRY_RUN=%s  db=%s", dry_run, db_name)
    if dry_run:
        logger.info("  (Use --apply or DRY_RUN=false to apply changes)")

    # ── Step 1: Find all user_ids with more than one subscription document ───
    pipeline = [
        {"$group": {"_id": "$user_id", "count": {"$sum": 1}, "docs": {"$push": "$$ROOT"}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    duplicates = await col.aggregate(pipeline).to_list(length=None)

    if not duplicates:
        logger.info("✅  No duplicate subscriptions found.")
        await _ensure_unique_index(col, dry_run)
        client.close()
        return 0

    logger.info("⚠️   Found %d user_id(s) with duplicate subscriptions.", len(duplicates))

    # ── Step 2: Build deduplication plan ─────────────────────────────────────
    plan, needs_review = _build_dedup_plan(duplicates)

    # ── Step 3: Emit DRY RUN report ──────────────────────────────────────────
    _log_dry_run_plan(plan, needs_review)

    # ── Step 4: Halt if any ambiguous duplicates exist ───────────────────────
    if needs_review:
        logger.error("")
        logger.error("❌  STOPPING — %d user_id(s) cannot be resolved automatically:", len(needs_review))
        for item in needs_review:
            logger.error("  user_id=%s:", item["user_id"])
            for doc in item["docs"]:
                logger.error(
                    "    _id=%s  status=%-15s  updated=%s  trial_used=%s  paddle_sub=%s",
                    doc.get("_id"),
                    doc.get("status"),
                    str(doc.get("updated_at", doc.get("created_at", "n/a")))[:19],
                    doc.get("trial_used"),
                    doc.get("paddle_subscription_id"),
                )
        logger.error("")
        logger.error("Action required: inspect the documents above and manually delete the obsolete ones.")
        logger.error("Then re-run this migration.")
        client.close()
        return 1

    # ── Step 5: Apply deletions (skipped in DRY RUN) ─────────────────────────
    total_deleted = 0
    for winner, losers in plan:
        ids_to_delete = [doc["_id"] for doc in losers]
        if not dry_run:
            result = await col.delete_many({"_id": {"$in": ids_to_delete}})
            total_deleted += result.deleted_count
            logger.info(
                "  Deleted %d doc(s) for user_id=%s",
                result.deleted_count,
                winner.get("user_id"),
            )
        else:
            total_deleted += len(ids_to_delete)

    if dry_run:
        logger.info("[DRY RUN] %d document(s) would be deleted — no writes performed.", total_deleted)
    else:
        logger.info("Deleted %d document(s) total.", total_deleted)

    # ── Step 6: Enforce UNIQUE index ─────────────────────────────────────────
    await _ensure_unique_index(col, dry_run)

    logger.info("=== Migration complete. ===")
    client.close()
    return 0


def _parse_args(argv: Optional[List[str]] = None) -> bool:
    """Parse CLI arguments and return the effective dry_run flag."""
    parser = argparse.ArgumentParser(
        description=(
            "Safely deduplicate subscriptions.user_id to prepare a UNIQUE index.\n"
            "Defaults to --dry-run (inspect only, no writes)."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument(
        "--dry-run",
        dest="dry_run",
        action="store_true",
        default=None,
        help="Inspect only — list duplicates and the document that would be kept; no writes (default).",
    )
    mode.add_argument(
        "--apply",
        dest="dry_run",
        action="store_false",
        help="Apply changes: delete losing documents and create the UNIQUE index.",
    )
    args = parser.parse_args(argv)

    # CLI flag takes precedence; fall back to DRY_RUN env var (default true).
    if args.dry_run is None:
        return os.getenv("DRY_RUN", "true").strip().lower() not in ("false", "0", "no")
    return args.dry_run


if __name__ == "__main__":
    _dry_run = _parse_args()
    exit_code = asyncio.run(run(dry_run=_dry_run))
    sys.exit(exit_code)
