"""Provider factory — the Garmin connector now uses the REAL gccli provider.

The mock provider has been removed. gccli is the single, real Garmin backend.

Multi-user isolation: each RunIndex user gets their own GCCLI HOME directory so
their OAuth token is stored separately from every other user's token.
"""

from __future__ import annotations

import os
from typing import Optional

from .providers.base import Provider
from .providers.gccli_provider import GccliProvider
from .runner import GccliRunner


def _make_runner(home: str) -> GccliRunner:
    return GccliRunner(
        gccli_path=os.environ.get("GCCLI_PATH", "gccli"),
        home=home,
        keyring_backend=os.environ.get("GCCLI_KEYRING_BACKEND", "file"),
        timeout_seconds=int(os.environ.get("GCCLI_TIMEOUT", "45")),
        max_retries=int(os.environ.get("GCCLI_MAX_RETRIES", "3")),
    )


def _base_home() -> str:
    return os.environ.get("GCCLI_HOME", "/app/backend/.gccli_home")


def get_provider_for_user(user_id: str, garmin_account: Optional[str] = None) -> GccliProvider:
    """Return an isolated GccliProvider for a specific RunIndex user.

    Each user gets their own HOME directory under the base GCCLI_HOME so their
    OAuth token is completely isolated from every other user's session.
    """
    # Sanitize user_id to prevent path traversal: keep only alphanumerics and
    # hyphens (UUID format).  If the value somehow contains path separators or
    # dots after JWT validation, we raise rather than silently using a bad path.
    safe_uid = "".join(c for c in user_id if c.isalnum() or c == "-")
    if not safe_uid or safe_uid != user_id:
        raise ValueError(f"Invalid user_id for GCCLI home path: {user_id!r}")
    user_home = os.path.join(_base_home(), safe_uid)
    runner = _make_runner(user_home)
    return GccliProvider(runner=runner, account=garmin_account)


def get_provider() -> Provider:
    """Global provider using the base GCCLI_HOME (used by bootstrap only)."""
    runner = _make_runner(_base_home())
    return GccliProvider(runner=runner)


def active_provider_name() -> str:
    return "gccli"
