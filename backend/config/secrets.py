"""Centralised secret access — environment-only, secret-manager ready.

All secrets are read exclusively from process environment variables. External
secret managers (Doppler, Vault, 1Password, Docker secrets) work by INJECTING
values into the environment at runtime, so no provider-specific code lives in
the app — swapping managers requires zero code changes.

Rules:
  - Never hardcode secrets. `.env` / `.env.example` hold variable NAMES only.
  - Use `get_secret(...)` (or `os.getenv` for non-sensitive config) everywhere.
  - `required=True` fails fast with a clear, provider-agnostic message.
"""

from __future__ import annotations

import os


class MissingSecretError(RuntimeError):
    """Raised when a secret marked as required is absent or empty."""


def get_secret(name: str, default=None, required: bool = False):
    """Return the value of secret ``name`` from the environment.

    - Reads from ``os.environ`` only (secret managers inject there at runtime).
    - Empty string is treated as "not set".
    - When ``required=True`` and the secret is missing, raises MissingSecretError
      with a clear message; otherwise returns ``default``.
    """
    value = os.environ.get(name)
    if value is None or value == "":
        if required:
            raise MissingSecretError(
                f"Required secret '{name}' is not set. Inject it at runtime via the "
                f"environment or a secret manager (Doppler / Vault / 1Password / "
                f"Docker secrets). Secrets must never be committed to the repository."
            )
        return default
    return value
