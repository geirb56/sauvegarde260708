"""Shared async Redis connection (lazy singleton, per-process)."""

from __future__ import annotations

import os

import redis.asyncio as aioredis

_redis: "aioredis.Redis | None" = None


def get_redis() -> "aioredis.Redis":
    global _redis
    if _redis is None:
        url = os.environ["REDIS_URL"]
        # socket_timeout=None: blocking commands (BLMOVE) must not be cut short
        # by the client socket read timeout.
        _redis = aioredis.from_url(
            url,
            encoding="utf-8",
            decode_responses=True,
            socket_timeout=None,
            socket_connect_timeout=5,
            health_check_interval=30,
        )
    return _redis
