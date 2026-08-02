"""Tests for the gccli session store (backend <-> worker sharing via Mongo).

Covered:
  - save/restore round-trip (files identical);
  - strict isolation between two distinct users;
  - restore when no session exists -> False (graceful);
  - the stored blob is ENCRYPTED (plaintext token never present);
  - ensure_session: populated locally -> True; missing -> restored from Mongo.
"""
from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault("JWT_SECRET_KEY", "session-store-test-secret-32chars!!")
os.environ.pop("GCCLI_SESSION_KEY", None)  # exercise the derived-key path

from garmin import session_store  # noqa: E402


def _run(coro):
    return asyncio.run(coro)


class _Collection:
    def __init__(self):
        self._docs = []

    async def find_one(self, query, projection=None):
        for d in self._docs:
            if all(d.get(k) == v for k, v in query.items()):
                return dict(d)
        return None

    async def update_one(self, query, update, upsert=False):
        for d in self._docs:
            if all(d.get(k) == v for k, v in query.items()):
                d.update(update.get("$set", {}))
                return
        if upsert:
            doc = dict(query)
            doc.update(update.get("$set", {}))
            self._docs.append(doc)

    async def delete_one(self, query):
        self._docs = [d for d in self._docs if not all(d.get(k) == v for k, v in query.items())]


class _FakeDB:
    def __init__(self):
        self._cols = {}

    def __getitem__(self, name):
        return self._cols.setdefault(name, _Collection())


TOKEN_A = b"gccli:token:alice-SECRET-AAA"
TOKEN_B = b"gccli:token:bob-SECRET-BBB"


def _seed_home(base, user_id, token_bytes):
    creds = os.path.join(base, user_id, ".config", "gccli", "credentials")
    os.makedirs(creds, exist_ok=True)
    with open(os.path.join(creds, f"gccli:token:{user_id}"), "wb") as f:
        f.write(token_bytes)
    with open(os.path.join(base, user_id, ".config", "gccli", "config.json"), "wb") as f:
        f.write(b'{"account":"' + user_id.encode() + b'"}')


def test_save_restore_roundtrip(tmp_path):
    os.environ["GCCLI_HOME"] = str(tmp_path)
    db = _FakeDB()
    _seed_home(str(tmp_path), "userA", TOKEN_A)

    assert _run(session_store.save_session(db, "userA")) is True

    # Wipe local disk, then restore from Mongo.
    import shutil
    shutil.rmtree(os.path.join(str(tmp_path), "userA"))
    assert session_store.is_populated(session_store.user_home("userA")) is False

    assert _run(session_store.restore_session(db, "userA")) is True
    restored = os.path.join(str(tmp_path), "userA", ".config", "gccli", "credentials", "gccli:token:userA")
    assert open(restored, "rb").read() == TOKEN_A


def test_two_users_are_isolated(tmp_path):
    os.environ["GCCLI_HOME"] = str(tmp_path)
    db = _FakeDB()
    _seed_home(str(tmp_path), "userA", TOKEN_A)
    _seed_home(str(tmp_path), "userB", TOKEN_B)

    assert _run(session_store.save_session(db, "userA")) is True
    assert _run(session_store.save_session(db, "userB")) is True

    # Fresh disk: restore each user separately.
    import shutil
    shutil.rmtree(str(tmp_path))
    os.makedirs(str(tmp_path), exist_ok=True)

    assert _run(session_store.restore_session(db, "userA")) is True
    assert _run(session_store.restore_session(db, "userB")) is True

    a_token = os.path.join(str(tmp_path), "userA", ".config", "gccli", "credentials", "gccli:token:userA")
    b_token = os.path.join(str(tmp_path), "userB", ".config", "gccli", "credentials", "gccli:token:userB")
    assert open(a_token, "rb").read() == TOKEN_A
    assert open(b_token, "rb").read() == TOKEN_B
    # No cross-contamination: userA home must NOT contain userB's token file.
    assert not os.path.exists(
        os.path.join(str(tmp_path), "userA", ".config", "gccli", "credentials", "gccli:token:userB")
    )


def test_restore_missing_session_returns_false(tmp_path):
    os.environ["GCCLI_HOME"] = str(tmp_path)
    db = _FakeDB()
    assert _run(session_store.restore_session(db, "ghost")) is False
    assert _run(session_store.ensure_session(db, "ghost")) is False


def test_stored_blob_is_encrypted(tmp_path):
    os.environ["GCCLI_HOME"] = str(tmp_path)
    db = _FakeDB()
    _seed_home(str(tmp_path), "userA", TOKEN_A)
    _run(session_store.save_session(db, "userA"))

    doc = _run(db[session_store.SESSIONS_COLLECTION].find_one({"user_id": "userA"}))
    blob = doc["blob"]
    assert doc["enc"] == "fernet"
    # Plaintext secret must NOT appear in the stored (encrypted) blob.
    assert "alice-SECRET-AAA" not in blob
    assert "gccli:token" not in blob


def test_ensure_session_prefers_local_then_restores(tmp_path):
    os.environ["GCCLI_HOME"] = str(tmp_path)
    db = _FakeDB()
    _seed_home(str(tmp_path), "userA", TOKEN_A)
    # Populated locally -> True even with empty DB.
    assert _run(session_store.ensure_session(db, "userA")) is True

    # Save, wipe, then ensure must restore from Mongo.
    _run(session_store.save_session(db, "userA"))
    import shutil
    shutil.rmtree(os.path.join(str(tmp_path), "userA"))
    assert _run(session_store.ensure_session(db, "userA")) is True
    assert session_store.is_populated(session_store.user_home("userA")) is True
