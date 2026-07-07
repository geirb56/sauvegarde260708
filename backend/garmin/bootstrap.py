"""Startup bootstrap for the gccli Garmin connector.

Makes the connector survive a fresh production deploy where the gccli binary
and OAuth token are absent:

1. ensure_gccli_installed(): if gccli is not on PATH (and not already vendored),
   download the correct prebuilt binary for the host architecture from the
   bpauli/gccli GitHub releases and vendor it under /app/backend/bin, then point
   GCCLI_PATH at it.
2. ensure_logged_in(): if provider is gccli and no valid session exists, perform
   a one-time headless login using backend env credentials so the token is
   provisioned (auto-refreshed afterwards).

Everything is best-effort and never raises — failures only log a warning so the
backend always starts.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import shutil
import tarfile
import tempfile
import urllib.request

from config.secrets import get_secret

logger = logging.getLogger(__name__)

GITHUB_LATEST = "https://api.github.com/repos/bpauli/gccli/releases/latest"
DEFAULT_BIN_DIR = "/app/backend/bin"


def _arch_tag() -> str | None:
    m = platform.machine().lower()
    if m in ("x86_64", "amd64"):
        return "amd64"
    if m in ("aarch64", "arm64"):
        return "arm64"
    return None


def ensure_gccli_installed(bin_dir: str = DEFAULT_BIN_DIR, timeout: int = 90) -> str | None:
    """Return a usable gccli path, downloading it if necessary."""
    configured = os.environ.get("GCCLI_PATH", "gccli")
    found = shutil.which(configured) or (shutil.which("gccli") if configured == "gccli" else None)
    if found:
        return found

    vendored = os.path.join(bin_dir, "gccli")
    if os.path.isfile(vendored) and os.access(vendored, os.X_OK):
        os.environ["GCCLI_PATH"] = vendored
        return vendored

    arch = _arch_tag()
    if not arch:
        logger.warning("[gccli] unsupported architecture %s; skipping auto-install", platform.machine())
        return None

    try:
        req = urllib.request.Request(GITHUB_LATEST, headers={"User-Agent": "cardiocoach"})
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            release = json.load(resp)

        asset_url = None
        for asset in release.get("assets", []):
            name = asset.get("name", "")
            if name.endswith(f"linux_{arch}.tar.gz"):
                asset_url = asset.get("browser_download_url")
                break
        if not asset_url:
            logger.warning("[gccli] no linux_%s release asset found", arch)
            return None

        os.makedirs(bin_dir, exist_ok=True)
        with tempfile.NamedTemporaryFile(suffix=".tar.gz", delete=False) as tmp:
            req2 = urllib.request.Request(asset_url, headers={"User-Agent": "cardiocoach"})
            with urllib.request.urlopen(req2, timeout=timeout) as resp2:
                shutil.copyfileobj(resp2, tmp)
            tar_path = tmp.name

        with tarfile.open(tar_path, "r:gz") as tf:
            member = next((m for m in tf.getmembers() if os.path.basename(m.name) == "gccli"), None)
            if not member:
                logger.warning("[gccli] binary not found inside archive")
                return None
            member.name = "gccli"
            tf.extract(member, path=bin_dir)

        os.chmod(vendored, 0o755)
        try:
            os.remove(tar_path)
        except OSError:
            pass

        os.environ["GCCLI_PATH"] = vendored
        logger.info("[gccli] auto-installed to %s (arch=%s, %s)", vendored, arch, release.get("tag_name"))
        return vendored
    except Exception as exc:  # noqa: BLE001 — best effort
        logger.warning("[gccli] auto-install failed: %s", exc)
        return None


def ensure_logged_in() -> None:
    """One-time gccli login at startup (provider=gccli only), with contextual
    fail-fast on missing credentials.

    - provider != gccli  -> no Garmin credentials required (returns).
    - gccli runner unavailable / auth check fails -> best-effort skip (no crash).
    - gccli with an existing valid session -> returns without needing a password.
    - gccli that MUST perform a real authentication -> GARMIN_USERNAME and
      GARMIN_PASSWORD become mandatory; missing ones raise MissingSecretError
      (fail-fast with a clear message). Startup never fails *solely* because
      GARMIN_PASSWORD is absent when a session already exists.
    """
    if get_secret("GARMIN_PROVIDER", "").strip().lower() != "gccli":
        return

    try:
        from .factory import get_provider

        provider = get_provider()
        runner = getattr(provider, "_runner", None)
        if runner is None or not runner.is_available():
            logger.info("[gccli] runner unavailable; skipping startup login")
            return
        account = get_secret("GARMIN_USERNAME")
        if account and runner.is_authenticated(account):
            logger.info("[gccli] existing session found for %s", account)
            return
    except Exception as exc:  # noqa: BLE001 — auth check is best-effort
        logger.warning("[gccli] startup auth check skipped: %s", exc)
        return

    # No valid session: a real authentication is required now, so both
    # credentials become mandatory. Fail fast with a clear message.
    account = get_secret("GARMIN_USERNAME", required=True)
    password = get_secret("GARMIN_PASSWORD", required=True)
    try:
        runner.login(account, password)
        logger.info("[gccli] startup login successful")
    except Exception as exc:  # noqa: BLE001 — login failure is non-fatal
        logger.warning("[gccli] startup login failed: %s", exc)


def bootstrap() -> None:
    ensure_gccli_installed()
    ensure_logged_in()
