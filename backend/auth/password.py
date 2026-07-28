"""Secure password hashing and verification using bcrypt via passlib."""

from __future__ import annotations

import logging

from passlib.context import CryptContext

logger = logging.getLogger(__name__)

# bcrypt is the recommended scheme; deprecated="auto" migrates old hashes on login
_pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(password: str) -> str:
    """Return a bcrypt hash of *password*.

    The plain-text password is never logged or stored.
    """
    return _pwd_context.hash(password)


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Return True if *plain_password* matches *hashed_password*.

    Uses constant-time comparison internally to prevent timing attacks.
    Never logs either argument.
    """
    try:
        return _pwd_context.verify(plain_password, hashed_password)
    except Exception:
        # Malformed hash — treat as mismatch
        logger.warning("Password verification failed due to malformed hash")
        return False
