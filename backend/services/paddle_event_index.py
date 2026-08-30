from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any

from services.datetime_utils import normalize_utc_datetime

logger = logging.getLogger(__name__)

_TARGET_PARTIAL_FILTER = {"event_id": {"$exists": True}}
_TARGET_INDEX_NAME = "event_id_unique_partial"

def _event_status_rank(status: Any) -> int:
    """Rank event states for dedup winner choice (lower is better)."""
    normalized = str(status or "").strip().lower()
    if normalized == "processed":
        return 0
    if normalized == "processing":
        return 1
    if normalized == "failed":
        return 2
    return 3


def _event_recency(doc: dict[str, Any]) -> datetime:
    """Return most relevant event timestamp for deterministic tie-breaking."""
    for field in ("processed_at", "failed_at", "claimed_at", "updated_at", "occurred_at"):
        parsed = normalize_utc_datetime(doc.get(field))
        if parsed is not None:
            return parsed
    return datetime(1970, 1, 1, tzinfo=timezone.utc)


def _pick_event_winner(docs: list[dict[str, Any]]) -> tuple[dict[str, Any], list[dict[str, Any]], str]:
    """Pick one deterministic winner for a duplicate event_id group."""
    ranked = sorted(
        docs,
        key=lambda doc: (
            _event_status_rank(doc.get("status")),
            -_event_recency(doc).timestamp(),
            str(doc.get("_id")),
        ),
    )
    winner = ranked[0]
    losers = ranked[1:]
    reason = (
        "winner chosen by status priority processed>processing>failed>legacy, "
        "then newest timestamp, then lowest _id"
    )
    return winner, losers, reason


async def _deduplicate_event_id_docs(col: Any, archive_col: Any) -> int:
    """Archive and remove duplicate event_id rows before unique index creation."""
    duplicate_groups = await col.aggregate(
        [
            {"$match": {"event_id": {"$exists": True, "$ne": None}}},
            {"$group": {"_id": "$event_id", "count": {"$sum": 1}, "docs": {"$push": "$$ROOT"}}},
            {"$match": {"count": {"$gt": 1}}},
        ]
    ).to_list(length=None)

    deduped = 0
    for group in duplicate_groups:
        event_id = group.get("_id")
        docs = list(group.get("docs") or [])
        if len(docs) < 2:
            continue

        winner, losers, reason = _pick_event_winner(docs)
        loser_ids = [doc.get("_id") for doc in losers if doc.get("_id") is not None]
        if not loser_ids:
            continue

        for loser in losers:
            loser_id = loser.get("_id")
            if loser_id is None:
                continue
            archive_id = f"{event_id}:{loser_id}"
            await archive_col.update_one(
                {"_id": archive_id},
                {
                    "$setOnInsert": {
                        "_id": archive_id,
                        "event_id": event_id,
                        "winner_id": winner.get("_id"),
                        "loser_id": loser_id,
                        "reason": reason,
                        "deduped_at": datetime.now(timezone.utc).isoformat(),
                        "loser_document": loser,
                    }
                },
                upsert=True,
            )

        await col.delete_many({"_id": {"$in": loser_ids}})
        deduped += len(loser_ids)
        logger.warning(
            "Deduplicated paddle_events for event_id=%r keeping _id=%r and archiving %d loser(s)",
            event_id,
            winner.get("_id"),
            len(loser_ids),
        )
    return deduped


def _is_event_id_index(idx: dict[str, Any]) -> bool:
    return list((idx.get("key") or {}).items()) == [("event_id", 1)]


def _is_target_unique_index(idx: dict[str, Any]) -> bool:
    return bool(idx.get("unique")) and (idx.get("partialFilterExpression") or {}) == _TARGET_PARTIAL_FILTER


async def ensure_paddle_events_unique_index(db: Any) -> None:
    """
    Idempotently migrate paddle_events to a unique partial index on event_id.

    The helper deduplicates duplicate event_id groups first, archives removed
    rows, then ensures a single compatible unique partial index.
    """
    col = db.paddle_events
    archive_col = db.paddle_events_dedup_archive

    deduped = await _deduplicate_event_id_docs(col, archive_col)
    if deduped:
        logger.info("Deduplicated %d paddle_events duplicate documents before index creation", deduped)

    event_id_indexes: list[tuple[str, dict[str, Any]]] = []
    async for idx in col.list_indexes():
        name = idx.get("name")
        if not name:
            continue
        if _is_event_id_index(idx):
            event_id_indexes.append((name, idx))

    has_target = any(_is_target_unique_index(idx) for _, idx in event_id_indexes)
    if has_target:
        logger.info("paddle_events.event_id unique partial index already present")
        return

    for name, idx in event_id_indexes:
        logger.warning("Dropping incompatible paddle_events.event_id index %s (spec=%s)", name, idx)
        await col.drop_index(name)

    await col.create_index(
        "event_id",
        name=_TARGET_INDEX_NAME,
        unique=True,
        partialFilterExpression=_TARGET_PARTIAL_FILTER,
    )
    logger.info("Created paddle_events.event_id unique partial index")
