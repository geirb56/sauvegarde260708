"""Shared dashboard-insight in-memory cache.

A single module-level dict is used so both the server (writer) and the
Garmin API (invalidator) operate on the same object without circular imports.
"""
from __future__ import annotations

# { f"{user_id}_{language}": (result, timestamp) }
_cache: dict = {}

# 5 minutes TTL
TTL_SECONDS = 300


def get(user_id: str, language: str):
    """Return cached (result, timestamp) or None."""
    return _cache.get(f"{user_id}_{language}")


def set(user_id: str, language: str, result, timestamp: float) -> None:
    _cache[f"{user_id}_{language}"] = (result, timestamp)


def invalidate_user(user_id: str) -> None:
    """Remove all cached entries for a given user (all languages)."""
    keys_to_delete = [k for k in _cache if k.startswith(f"{user_id}_")]
    for k in keys_to_delete:
        del _cache[k]
