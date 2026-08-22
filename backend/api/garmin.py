"""Garmin API router (HTTP layer).

Prefix /api is added when included by server.py (api_router has prefix /api).
Final routes: /api/garmin/*

All routes require a valid JWT. The authenticated user's identity (from the
JWT) is always used as user_id — never a client-supplied query parameter.
"""

from __future__ import annotations

from typing import Optional

from fastapi import APIRouter, Depends, Request
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field

from auth.dependencies import get_current_user
from garmin import service as garmin_service
from garmin import backfill as garmin_backfill
from services.run_index_history import backfill_connected_users_run_index_history, backfill_run_index_history
import dashboard_insight_cache as _dic
from jobs.queue import enqueue_sync
from jobs.health import queue_health
from jobs.redis_client import get_redis
from feed import realtime_cache
from feed.sse import event_stream
from feed.sync_progress_sse import sync_progress_event_stream

import logging
import time
logger = logging.getLogger(__name__)

ACTIVE_SIGNAL_PREFIX = "runindex:active_signal:"
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
    # Garmin Connect credentials for this user's own account.
    # Used once for the headless gccli login; never stored by the backend.
    garmin_username: str = Field(..., description="Garmin Connect email address")
    garmin_password: str = Field(..., description="Garmin Connect password")
    # Optional, testing-only hook to exercise the MFA (Mode 2) code path.
    simulate_mfa: bool = False

    class Config:
        # Prevent the password from leaking into repr/logs.
        json_encoders = {}

    def __repr__(self) -> str:
        return f"GarminConnectRequest(garmin_username={self.garmin_username!r}, simulate_mfa={self.simulate_mfa})"


@garmin_router.post("/connect")
async def connect_garmin(
    request: Request,
    body: GarminConnectRequest,
    user: dict = Depends(get_current_user),
):
    """Establish the Garmin session (fast auth check) and queue the initial sync.

    Auth is a lightweight token/status check (non-blocking); the heavy activity
    + metrics fetch is offloaded to the worker so the request returns instantly.
    """
    user_id = user["id"]
    db = request.app.state.db
    result = await garmin_service.connect(
        db,
        user_id,
        garmin_username=body.garmin_username,
        garmin_password=body.garmin_password,
        simulate_mfa=body.simulate_mfa,
    )
    if result.get("status") == "connected":
        # Kick off the first data sync in the background (never blocks the API).
        # Redis outage must not fail the connect itself.
        await _safe_enqueue(user_id)
    return result


@garmin_router.post("/sync")
async def sync_garmin(request: Request, user: dict = Depends(get_current_user)):
    """Non-blocking: enqueue a Garmin sync job and return immediately."""
    user_id = user["id"]
    res, err = await _safe_enqueue(user_id)
    if err is not None:
        return JSONResponse(
            status_code=503,
            content={"status": "unavailable", "detail": "sync service temporarily unavailable, retry shortly"},
        )
    return res


@garmin_router.get("/activities")
async def garmin_activities(
    request: Request,
    user: dict = Depends(get_current_user),
    limit: int = 20,
    since: Optional[str] = None,
):
    """Ultra-fast feed: Redis cache first, MongoDB fallback (+cache warm).

    Backward compatible: response is still {activities, count}. `since` (ISO
    start_time) enables incremental UI updates ("give me what's newer than X").
    """
    user_id = user["id"]
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
async def garmin_backfill_endpoint(
    request: Request,
    user: dict = Depends(get_current_user),
    scope: str = "user",
):
    """On-demand rebuild of derived Garmin data from `garmin_activities`.

    Rebuilds `workouts` + feed cache and also recalculates historical RunIndex
    snapshots with weekly/monthly granularity. Never calls gccli, never modifies
    `garmin_activities`. Idempotent.

    - scope=user (default): backfill one user synchronously, returns counts.
    - scope=all: backfill every connected Garmin user in a background task.
    """
    import asyncio
    user_id = user["id"]
    db = request.app.state.db
    if scope == "all":
        asyncio.create_task(backfill_connected_users_run_index_history(db))
        return {"status": "started", "scope": "all"}
    result = await garmin_backfill.backfill_user(db, user_id)
    history = await backfill_run_index_history(db, user_id)
    # Invalidate dashboard insight cache so the next request reflects the
    # refreshed RunIndex (PR181: cache must not serve stale run_index post-sync).
    _dic.invalidate_user(user_id)
    return {"status": "ok", **result, "run_index_history": history}


@garmin_router.get("/sync/stream")
async def garmin_sync_progress_stream(
    request: Request,
    user: dict = Depends(get_current_user),
    last_id: Optional[str] = None,
):
    """Server-Sent Events stream of SYNC_PROGRESS for the authenticated user.

    Emits an immediate snapshot of the current sync state, then streams future
    progress events from the dedicated Redis Stream in real time.

    - Reconnect-safe: resumes from the `Last-Event-ID` header or `last_id` query param.
    - User-isolated: only events for the authenticated user are forwarded.
    - No sync trigger, no gccli, no DB writes — pure delivery layer.
    - Heartbeat: `: ping` comment frames every ~20 s.
    """
    user_id = user["id"]
    start_id = last_id or request.headers.get("Last-Event-ID") or "$"
    return StreamingResponse(
        sync_progress_event_stream(user_id, request, start_id),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@garmin_router.get("/feed/stream")
async def garmin_feed_stream(
    request: Request,
    user: dict = Depends(get_current_user),
    last_id: Optional[str] = None,
):
    """Server-Sent Events stream of ACTIVITY_CREATED for a user (READ-ONLY).

    Pure delivery layer over the Redis Stream: no sync, no gccli, no DB writes.
    Reconnect-safe — resumes from the `Last-Event-ID` header (or `last_id` query
    param); defaults to only-new events. Non-destructive XREAD -> horizontally
    scalable. Emits `event: activity_created` frames + `: ping` heartbeats.
    """
    user_id = user["id"]
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
async def garmin_activity_signal(user: dict = Depends(get_current_user)):
    """Mark a user as ACTIVE from app interaction (used ONLY by the scheduler).

    Does NOT trigger a sync, call gccli, or touch activities/workouts. It simply
    stores a fresh app-interaction timestamp in Redis (TTL-based), which the
    scheduler worker reads to bump the user into the ACTIVE sync tier.
    """
    user_id = user["id"]
    try:
        r = get_redis()
        await r.set(f"{ACTIVE_SIGNAL_PREFIX}{user_id}", str(time.time()), ex=ACTIVE_SIGNAL_TTL)
        return {"status": "ok", "tier_hint": "active", "ttl_seconds": ACTIVE_SIGNAL_TTL}
    except Exception as exc:
        logger.error("[garmin] activity-signal failed user=%s: %s", user_id, exc)
        return JSONResponse(status_code=503, content={"status": "unavailable"})


@garmin_router.get("/status")
async def garmin_status(request: Request, user: dict = Depends(get_current_user)):
    user_id = user["id"]
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
async def disconnect_garmin(request: Request, user: dict = Depends(get_current_user)):
    user_id = user["id"]
    db = request.app.state.db
    return await garmin_service.disconnect(db, user_id)


@garmin_router.get("/daily-metrics")
async def garmin_daily_metrics(
    request: Request,
    user: dict = Depends(get_current_user),
    days: int = 7,
):
    user_id = user["id"]
    db = request.app.state.db
    return await garmin_service.get_daily_metrics(db, user_id, days=days)
