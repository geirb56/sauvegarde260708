import os
import time
import base64
import secrets
import logging
from typing import Optional, Tuple

try:
    import redis
except Exception:
    redis = None

from cryptography.hazmat.primitives.ciphers.aead import AESGCM

logger = logging.getLogger(__name__)
DEFAULT_TTL = 24 * 3600

class CredentialVault:
    def __init__(self, redis_url: Optional[str] = None, master_key_b64: Optional[str] = None):
        if master_key_b64 is None:
            raise RuntimeError("MASTER_KEY must be provided for CredentialVault")
        self._key = base64.b64decode(master_key_b64)
        self._aesgcm = AESGCM(self._key)
        self._redis = None
        if redis_url and redis is not None:
            try:
                self._redis = redis.from_url(redis_url)
            except Exception:
                logger.exception("Redis init failed, falling back to in-memory vault")
                self._redis = None
        self._memory = {}

    def _encrypt(self, plaintext: bytes, aad: bytes = b"") -> bytes:
        nonce = AESGCM.generate_key(bit_length=96)[:12]
        ciphertext = self._aesgcm.encrypt(nonce, plaintext, aad)
        return nonce + ciphertext

    def _decrypt(self, blob: bytes, aad: bytes = b"") -> bytes:
        nonce = blob[:12]
        ct = blob[12:]
        return self._aesgcm.decrypt(nonce, ct, aad)

    def store_temp_credentials(self, user_id: str, username: str, password: str, ttl_seconds: int = DEFAULT_TTL) -> str:
        token = secrets.token_urlsafe(32)
        payload = f"{username}\n{password}".encode("utf-8")
        enc = self._encrypt(payload)
        expires_at = int(time.time()) + min(ttl_seconds, DEFAULT_TTL)
        blob_b64 = base64.b64encode(enc).decode("utf-8")
        if self._redis:
            key = f"cred:{token}"
            self._redis.hset(key, mapping={"blob": blob_b64, "user_id": user_id})
            self._redis.expire(key, expires_at - int(time.time()))
        else:
            self._memory[token] = {"blob": blob_b64, "expires_at": expires_at, "user_id": user_id}
        return token

    def get_credentials(self, token: str) -> Tuple[str, str]:
        if self._redis:
            key = f"cred:{token}"
            row = self._redis.hgetall(key)
            if not row:
                raise KeyError("credentials not found")
            blob_b64 = row[b"blob"].decode()
        else:
            rec = self._memory.get(token)
            if not rec or rec["expires_at"] < int(time.time()):
                raise KeyError("credentials not found or expired")
            blob_b64 = rec["blob"]
        enc = base64.b64decode(blob_b64)
        plaintext = self._decrypt(enc)
        username, password = plaintext.decode("utf-8").split("\n", 1)
        return username, password

    def delete_credentials(self, token: str) -> None:
        if self._redis:
            key = f"cred:{token}"
            try:
                self._redis.delete(key)
            except Exception:
                logger.exception("Redis delete failed")
        else:
            self._memory.pop(token, None)

    def get_token_for_user(self, user_id: str) -> Optional[str]:
        if self._redis:
            for k in self._redis.scan_iter(match="cred:*"):
                row = self._redis.hgetall(k)
                if row and row.get(b"user_id", b"").decode() == user_id:
                    return k.decode().split(":", 1)[1]
            return None
        else:
            for token, rec in self._memory.items():
                if rec["user_id"] == user_id and rec["expires_at"] >= int(time.time()):
                    return token
            return None
