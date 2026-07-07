"""Provider factory — the Garmin connector now uses the REAL gccli provider.

The mock provider has been removed. gccli is the single, real Garmin backend.
"""

from __future__ import annotations

import os
from functools import lru_cache

from .providers.base import Provider
from .providers.gccli_provider import GccliProvider
from .runner import GccliRunner


@lru_cache(maxsize=1)
def _gccli_provider() -> GccliProvider:
    runner = GccliRunner(
        gccli_path=os.environ.get("GCCLI_PATH", "gccli"),
        home=os.environ.get("GCCLI_HOME", "/app/backend/.gccli_home"),
        keyring_backend=os.environ.get("GCCLI_KEYRING_BACKEND", "file"),
        timeout_seconds=int(os.environ.get("GCCLI_TIMEOUT", "45")),
        max_retries=int(os.environ.get("GCCLI_MAX_RETRIES", "3")),
    )
    return GccliProvider(runner=runner)


def get_provider() -> Provider:
    return _gccli_provider()


def active_provider_name() -> str:
    return "gccli"
