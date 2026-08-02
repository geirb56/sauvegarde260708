"""Share gccli sessions across processes/containers via MongoDB.

The Garmin login (`/api/garmin/connect`) runs on the API backend and writes the
per-user gccli OAuth token to the local disk at `GCCLI_HOME/{user_id}/`. The
sync workers may run on a DIFFERENT machine/container (e.g. Railway) whose local
disk does not contain that token. This module bridges the gap:

  - after a successful connect, the backend calls `save_session()` to persist the
    user's gccli session files into Mongo (`garmin_sessions`);
  - before a sync, the worker calls `ensure_session()` which restores the files
    into its own `GCCLI_HOME/{user_id}/` when they are missing;
  - after a successful sync, the worker re-saves the (possibly refreshed) token.

Strict per-user isolation: every document is keyed by `user_id`; a restore only
ever writes the files of that single user.

Security: the session blob is ENCRYPTED at rest with Fernet (AES-128-CBC +
HMAC). The key is `GCCLI_SESSION_KEY` if set, otherwise it is derived
deterministically from `JWT_SECRET_KEY` (shared by backend and workers). Tokens
are therefore never stored in clear text.
"""
from __future__ import annotations

import base64
import hashlib
import json
import logging
import os
from datetime import datetime, timezone
from typing import Optional

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)

SESSIONS_COLLECTION = "garmin_sessions"


def _base_home() -> str:
    return os.environ.get("GCCLI_HOME", "/app/backend/.gccli_home")


def user_home(user_id: str) -> str:
    """Absolute path of a user's isolated gccli HOME directory."""
    return os.path.join(_base_home(), user_id)


def _fernet() -> Fernet:
    explicit = os.environ.get("GCCLI_SESSION_KEY")
    if explicit:
        key = explicit.encode()
    else:
        secret = os.environ.get("JWT_SECRET_KEY", "")
        digest = hashlib.sha256(secret.encode()).digest()
        key = base64.urlsafe_b64encode(digest)
    return Fernet(key)


def is_populated(home: str) -> bool:
    """True if the user's gccli credentials directory holds at least one file."""
    creds_dir = os.path.join(home, ".config", "gccli", "credentials")
    if not os.path.isdir(creds_dir):
        return False
    for _root, _dirs, files in os.walk(creds_dir):
        if files:
            return True
    return False


def _collect_files(home: str) -> dict:
    """Read every file under `home` into {relative_path: base64(bytes)}."""
    files: dict[str, str] = {}
    if not os.path.isdir(home):
        return files
    for root, _dirs, names in os.walk(home):
        for name in names:
            abspath = os.path.join(root, name)
            relpath = os.path.relpath(abspath, home)
            try:
                with open(abspath, "rb") as fh:
                    files[relpath] = base64.b64encode(fh.read()).decode("ascii")
            except OSError as exc:
                logger.warning("[session_store] skip file=%s: %s", relpath, exc)
    return files


def _write_files(home: str, files: dict) -> int:
    """Write {relpath: base64(bytes)} back under `home`. Returns file count."""
    written = 0
    for relpath, b64 in files.items():
        # Defense-in-depth: never escape the user's home directory.
        dest = os.path.normpath(os.path.join(home, relpath))
        if not dest.startswith(os.path.normpath(home) + os.sep):
            logger.warning("[session_store] skip unsafe path=%s", relpath)
            continue
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        with open(dest, "wb") as fh:
            fh.write(base64.b64decode(b64))
        written += 1
    return written


async def save_session(db, user_id: str) -> bool:
    """Persist the user's on-disk gccli session into Mongo (encrypted).

    Best-effort: returns False (and logs) instead of raising, so it can never
    break the connect/sync flow. Scoped strictly to `user_id`.
    """
    try:
        home = user_home(user_id)
        files = _collect_files(home)
        if not files:
            return False
        blob = _fernet().encrypt(json.dumps(files).encode("utf-8"))
        await db[SESSIONS_COLLECTION].update_one(
            {"user_id": user_id},
            {"$set": {
                "user_id": user_id,
                "blob": blob.decode("ascii"),
                "enc": "fernet",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            }},
            upsert=True,
        )
        logger.info("[session_store] saved session user=%s files=%d", user_id, len(files))
        return True
    except Exception as exc:  # never break the caller
        logger.warning("[session_store] save failed user=%s: %s", user_id, exc)
        return False


async def restore_session(db, user_id: str) -> bool:
    """Restore a user's gccli session from Mongo onto local disk.

    Returns True if a session was found and written, False if none exists or on
    decode/decrypt failure (treated as "session unavailable" by the caller).
    """
    try:
        doc = await db[SESSIONS_COLLECTION].find_one({"user_id": user_id}, {"_id": 0})
        if not doc or not doc.get("blob"):
            return False
        try:
            raw = _fernet().decrypt(doc["blob"].encode("ascii"))
        except InvalidToken:
            logger.error("[session_store] decrypt failed user=%s (key mismatch?)", user_id)
            return False
        files = json.loads(raw.decode("utf-8"))
        home = user_home(user_id)
        os.makedirs(home, exist_ok=True)
        written = _write_files(home, files)
        logger.info("[session_store] restored session user=%s files=%d", user_id, written)
        return written > 0
    except Exception as exc:
        logger.warning("[session_store] restore failed user=%s: %s", user_id, exc)
        return False


async def ensure_session(db, user_id: str) -> bool:
    """Guarantee the user's gccli session is present on local disk before a sync.

    - If already populated locally (same container as connect) -> True.
    - Otherwise try to restore it from Mongo (cross-container case).
    Returns False when no usable session exists (missing/expired) so the caller
    can degrade gracefully and ask the user to reconnect.
    """
    home = user_home(user_id)
    if is_populated(home):
        return True
    return await restore_session(db, user_id)


async def delete_session(db, user_id: str) -> None:
    """Remove a user's stored session (called on disconnect)."""
    try:
        await db[SESSIONS_COLLECTION].delete_one({"user_id": user_id})
    except Exception as exc:
        logger.warning("[session_store] delete failed user=%s: %s", user_id, exc)
