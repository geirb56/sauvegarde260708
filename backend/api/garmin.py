"""Garmin API router (HTTP layer).

Prefix /api is added when included by server.py (api_router has prefix /api).
Final routes: /api/garmin/*

NON-NEGOTIABLE: no Garmin password is ever accepted from the client.
The connect endpoint takes only a user_id (auth abstracted backend-side).
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel

from garmin import service as garmin_service
from garmin import backfill as garmin_backfill
from jobs.queue import enqueue_sync
from jobs.health import queue_health
from jobs.redis_client import get_redis
from feed import realtime_cache
from feed.sse import event_stream

import logging
import time
logger = logging.getLogger(__name__)

ACTIVE_SIGNAL_PREFIX = "cardiocoach:active_signal:"
ACTIVE_SIGNAL_TTL = 45 * 60  # 45 min — matches scheduler ACTIVE window

garmin_router = APIRouter(prefix="/garmin", tags=["garmin"])


async def _safe_enqueue(user_id: str):
    """Enqueue a sync, tolerating a transient Redis outage."""
    try:
        return await enqueue_sync(user_id), None
    except Exception as exc:  # Redis down / connection error
        logger.error("[garmin] enqueue failed for user=%s: %s", user_id, exc)
        return None, exc


class GarminConnectRequest(BaseModel):
    # Optional, testing-only hook to exercise the MFA (Mode 2) code path.
    simulate_mfa: bool = False


@garmin_router.post("/connect")
async def connect_garmin(request: Request, body: Optional[GarminConnectRequest] = None, user_id: str = "default"):
    """Establish the Garmin session (fast auth check) and queue the initial sync.

    Auth is a lightweight token/status check (non-blocking); the heavy activity
    + metrics fetch is offloaded to the worker so the request returns instantly.
    """
    db = request.app.state.db
    simulate_mfa = bool(body.simulate_mfa) if body else False
    result = await garmin_service.connect(db, user_id, simulate_mfa=simulate_mfa)
    if result.get("status") == "connected":
        # Kick off the first data sync in the background (never blocks the API).
        # Redis outage must not fail the connect itself.
        await _safe_enqueue(user_id)
    return result


@garmin_router.post("/sync")
async def sync_garmin(request: Request, user_id: str = "default"):
    """Non-blocking: enqueue a Garmin sync job and return immediately."""
    res, err = await _safe_enqueue(user_id)
    if err is not None:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "detail": "sync service temporarily unavailable, retry shortly"},
        )
    return res


@garmin_router.get("/activities")
async def garmin_activities(request: Request, user_id: str = "default",
                            limit: int = 20, since: Optional[str] = None):
    """Ultra-fast feed: Redis cache first, MongoDB fallback (+cache warm).

    Backward compatible: response is still {activities, count}. `since` (ISO
    start_time) enables incremental UI updates ("give me what's newer than X").
    """
    cached = await realtime_cache.get_feed(user_id, since=since, limit=limit)
    # Serve from cache when it satisfies the request: incremental (since) reads
    # are always cache-authoritative; full reads need at least `limit` items so a
    # cold/partial cache doesn't return fewer results than the DB actually has.
    if cached and (since or len(cached) >= limit):
        return {"activities": cached, "count": len(cached), "source": "cache"}
    db = request.app.state.db
    items = await garmin_service.list_activities(db, user_id, limit=limit, since=since)
    # Warm the cache from the source of truth (only on a full, unfiltered read).
    if items and not since:
        try:
            await realtime_cache.warm_feed(user_id, items)
        except Exception as exc:  # cache warming must never break the response
            logger.warning("[garmin] feed warm failed user=%s: %s", user_id, exc)
    return {"activities": items, "count": len(items), "source": "db"}


@garmin_router.post("/backfill")
async def garmin_backfill_endpoint(request: Request, user_id: str = "default",
                                  scope: str = "user"):
    """On-demand rebuild of the derived `workouts` layer + feed cache from
    `garmin_activities` (source of truth). Never calls gccli, never modifies
    garmin_activities. Idempotent.

    - scope=user (default): backfill one user synchronously, returns counts.
    - scope=all: backfill every user in a background task, returns immediately.
    """
    import asyncio
    db = request.app.state.db
    if scope == "all":
        asyncio.create_task(garmin_backfill.backfill_all(db))
        return {"status": "started", "scope": "all"}
    result = await garmin_backfill.backfill_user(db, user_id)
    return {"status": "ok", **result}


@garmin_router.get("/feed/stream")
async def garmin_feed_stream(request: Request, user_id: str = "default",
                             last_id: Optional[str] = None):
    """Server-Sent Events stream of ACTIVITY_CREATED for a user (READ-ONLY).

    Pure delivery layer over the Redis Stream: no sync, no gccli, no DB writes.
    Reconnect-safe — resumes from the `Last-Event-ID` header (or `last_id` query
    param); defaults to only-new events. Non-destructive XREAD -> horizontally
    scalable. Emits `event: activity_created` frames + `: ping` heartbeats.
    """
    start_id = last_id or request.headers.get("Last-Event-ID") or "$"
    return StreamingResponse(
        event_stream(user_id, request, start_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",  # disable proxy buffering for SSE
        },
    )


@garmin_router.post("/activity-signal")
async def garmin_activity_signal(user_id: str = "default"):
    """Mark a user as ACTIVE from app interaction (used ONLY by the scheduler).

    Does NOT trigger a sync, call gccli, or touch activities/workouts. It simply
    stores a fresh app-interaction timestamp in Redis (TTL-based), which the
    scheduler worker reads to bump the user into the ACTIVE sync tier.
    """
    try:
        r = get_redis()
        await r.set(f"{ACTIVE_SIGNAL_PREFIX}{user_id}", str(time.time()), ex=ACTIVE_SIGNAL_TTL)
        return {"status": "ok", "tier_hint": "active", "ttl_seconds": ACTIVE_SIGNAL_TTL}
    except Exception as exc:
        logger.error("[garmin] activity-signal failed user=%s: %s", user_id, exc)
        return JSONResponse(status_code=503, content={"status": "unavailable"})


@garmin_router.get("/status")
async def garmin_status(request: Request, user_id: str = "default"):
    db = request.app.state.db
    return await garmin_service.get_status(db, user_id)


@garmin_router.get("/queue/health")
async def garmin_queue_health():
    """Lightweight, READ-ONLY Redis health snapshot of the sync queue.

    Response JSON:
      status                     "healthy" | "degraded" | "unhealthy"
      redis_connected            bool
      queue_length               int  — jobs waiting to be claimed
      processing_length          int  — jobs currently in-flight
      active_workers             int  — live worker heartbeats
      oldest_processing_seconds  int  — age of the oldest in-flight job (0 if none)
      orphans_recovered_total    int  — cumulative jobs requeued by the watchdog
      failed_jobs_total          int  — cumulative jobs that failed after max retries
      timestamp                  str  — ISO-8601 UTC

    Status rules: UNHEALTHY if redis down OR active_workers==0 OR
    oldest_processing>=120s OR queue_length>=2000; DEGRADED if queue_length>=500
    OR oldest_processing>=96s; otherwise HEALTHY.
    """
    return await queue_health()


@garmin_router.post("/disconnect")
async def disconnect_garmin(request: Request, user_id: str = "default"):
    db = request.app.state.db
    return await garmin_service.disconnect(db, user_id)


@garmin_router.get("/daily-metrics")
async def garmin_daily_metrics(request: Request, user_id: str = "default", days: int = 7):
    db = request.app.state.db
    return await garmin_service.get_daily_metrics(db, user_id, days=days)
