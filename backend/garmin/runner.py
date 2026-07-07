"""GccliRunner — isolated wrapper around the real `gccli` binary.

This is the ONLY place that knows how to talk to Garmin Connect through the
gccli command-line tool. It is intentionally isolated so the rest of the app
never depends on gccli details.

Auth model:
- gccli persists an OAuth token (file keyring) under a stable HOME directory.
- We perform a ONE-TIME headless login (email/password, optional MFA) via a
  pseudo-TTY; afterwards gccli auto-refreshes the token, so data commands do
  not need the password again.
- The Garmin password is sourced ONLY from backend env (never from the UI).

If gccli is missing or login needs interactive MFA we can't satisfy, methods
raise GccliUnavailable / GccliMfaRequired so callers can react gracefully.
"""

from __future__ import annotations

import json
import logging
import os
import pty
import select
import shutil
import subprocess
import time
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional

logger = logging.getLogger(__name__)


class GccliError(Exception):
    """Generic gccli failure."""


class GccliUnavailable(GccliError):
    """Raised when the gccli binary is missing."""


class GccliMfaRequired(GccliError):
    """Raised when login requires an MFA code we don't have."""


class GccliRunner:
    def __init__(
        self,
        gccli_path: str = "gccli",
        home: Optional[str] = None,
        keyring_backend: str = "file",
        timeout_seconds: int = 45,
        max_retries: int = 3,
    ):
        self.gccli_path = gccli_path
        self.home = home or os.environ.get("GCCLI_HOME", "/app/backend/.gccli_home")
        self.keyring_backend = keyring_backend
        # Clamp per-command timeout to a safe 15-60s window.
        self.timeout = max(15, min(60, timeout_seconds))
        self.max_retries = max(1, max_retries)
        os.makedirs(self.home, exist_ok=True)

    # ------------------------------------------------------------------ utils
    def is_available(self) -> bool:
        return shutil.which(self.gccli_path) is not None

    def _ensure_available(self) -> None:
        if not self.is_available():
            raise GccliUnavailable(f"gccli binary '{self.gccli_path}' not found in PATH")

    def _env(self, account: Optional[str] = None) -> dict:
        env = os.environ.copy()
        env["HOME"] = self.home
        env["GCCLI_KEYRING_BACKEND"] = self.keyring_backend
        if account:
            env["GCCLI_ACCOUNT"] = account
        return env

    def _run_json(self, args: List[str], account: Optional[str] = None):
        """Run a gccli data command with per-call timeout + bounded retries.

        Each invocation is a fresh subprocess with its own env (isolated per
        account, no shared state). Transient failures/timeouts are retried up
        to max_retries with exponential backoff; parse errors are not retried.
        """
        self._ensure_available()
        cmd = [self.gccli_path] + args + ["-j"]
        last_err: Optional[Exception] = None

        for attempt in range(1, self.max_retries + 1):
            try:
                cp = subprocess.run(
                    cmd,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=self.timeout,
                    env=self._env(account),
                )
                out = cp.stdout.decode("utf-8", errors="replace").strip()
                err = cp.stderr.decode("utf-8", errors="replace").strip()
                if cp.returncode != 0:
                    raise GccliError(f"gccli {' '.join(args)} failed: {err or out}")
                if not out:
                    return {}
                try:
                    return json.loads(out)
                except json.JSONDecodeError as exc:
                    # Non-transient: bad output won't fix itself, don't retry.
                    raise GccliError(
                        f"gccli {' '.join(args)} returned non-JSON: {out[:200]}"
                    ) from exc
            except json.JSONDecodeError:
                raise
            except subprocess.TimeoutExpired:
                last_err = GccliError(
                    f"gccli {' '.join(args)} timed out after {self.timeout}s"
                )
            except GccliError as exc:
                last_err = exc

            if attempt < self.max_retries:
                backoff = min(2 ** attempt, 8)
                logger.warning(
                    "[gccli] transient failure (attempt %s/%s) for '%s'; retrying in %ss",
                    attempt, self.max_retries, " ".join(args), backoff,
                )
                time.sleep(backoff)

        raise last_err or GccliError(f"gccli {' '.join(args)} failed")

    # ------------------------------------------------------------------- auth
    def auth_status(self, account: Optional[str] = None) -> dict:
        """Return {email, expired, expires_at} or {} if not authenticated."""
        self._ensure_available()
        cp = subprocess.run(
            [self.gccli_path, "auth", "status", "-j"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            timeout=self.timeout,
            env=self._env(account),
        )
        out = cp.stdout.decode("utf-8", errors="replace").strip()
        if cp.returncode != 0 or not out:
            return {}
        try:
            data = json.loads(out)
            return data if isinstance(data, dict) else {}
        except json.JSONDecodeError:
            return {}

    def is_authenticated(self, account: Optional[str] = None) -> bool:
        status = self.auth_status(account)
        # A stored session is usable even if the access token is 'expired'
        # because gccli auto-refreshes via the refresh token on next call.
        return bool(status.get("email"))

    def login(self, email: str, password: str, mfa_code: Optional[str] = None) -> None:
        """One-time headless login via a pseudo-TTY (gccli reads password from TTY)."""
        self._ensure_available()
        cmd = [self.gccli_path, "auth", "login", email, "--headless"]
        if mfa_code:
            cmd += ["--mfa-code", mfa_code]

        env = self._env(email)
        output_parts: List[str] = []
        pid, fd = pty.fork()
        if pid == 0:
            # Child
            try:
                os.execvpe(cmd[0], cmd, env)
            except Exception:  # noqa: BLE001
                os._exit(127)

        # Parent
        sent_pw = False
        deadline = time.time() + self.timeout
        exit_code = -1
        while time.time() < deadline:
            r, _, _ = select.select([fd], [], [], 0.5)
            if fd in r:
                try:
                    chunk = os.read(fd, 1024)
                except OSError:
                    break
                if not chunk:
                    break
                text = chunk.decode("utf-8", errors="replace")
                output_parts.append(text)
                if (not sent_pw) and ("assword" in text):
                    os.write(fd, (password + "\n").encode())
                    sent_pw = True
            try:
                wpid, status = os.waitpid(pid, os.WNOHANG)
                if wpid == pid:
                    exit_code = os.WEXITSTATUS(status) if os.WIFEXITED(status) else -1
                    break
            except ChildProcessError:
                break
            time.sleep(0.15)

        try:
            os.close(fd)
        except OSError:
            pass

        full_output = "".join(output_parts)
        low = full_output.lower()
        if exit_code == 0 or "logged in as" in low:
            logger.info("[gccli] login successful for %s", email)
            return
        if "mfa" in low or "two-factor" in low or "verification code" in low:
            raise GccliMfaRequired("Garmin login requires an MFA code")
        raise GccliError(f"gccli login failed: {full_output[:300]}")

    # -------------------------------------------------------------- data fetch
    def fetch_activities(self, limit: int = 20, account: Optional[str] = None) -> List[Dict]:
        data = self._run_json(["activities", "list", "--limit", str(limit)], account=account)
        if isinstance(data, list):
            return data
        return data.get("activities", []) if isinstance(data, dict) else []

    def fetch_daily_metrics(self, days: int = 7, account: Optional[str] = None) -> List[Dict]:
        """Combine resting HR (health hr), sleep, and HRV per day."""
        metrics: List[Dict] = []
        now = datetime.now(timezone.utc)
        for i in range(1, days + 1):  # start from yesterday (today often incomplete)
            day = (now - timedelta(days=i)).date().isoformat()
            entry: Dict = {"date": day, "source": "garmin"}

            # Resting HR (from health hr — health rhr endpoint 404s on some accounts)
            try:
                hr = self._run_json(["health", "hr", day], account=account)
                if isinstance(hr, dict):
                    entry["resting_hr"] = hr.get("restingHeartRate")
            except GccliError:
                entry["resting_hr"] = None

            # Sleep
            try:
                sleep = self._run_json(["health", "sleep", day], account=account)
                dto = sleep.get("dailySleepDTO", {}) if isinstance(sleep, dict) else {}
                secs = dto.get("sleepTimeSeconds")
                entry["sleep_hours"] = round(secs / 3600, 1) if secs else None
                scores = dto.get("sleepScores") or {}
                overall = scores.get("overall") or {}
                entry["sleep_score"] = overall.get("value")
            except GccliError:
                entry["sleep_hours"] = None
                entry["sleep_score"] = None

            # HRV (may be empty for accounts/devices without HRV)
            try:
                hrv = self._run_json(["health", "hrv", day], account=account)
                summary = hrv.get("hrvSummary", {}) if isinstance(hrv, dict) else {}
                entry["hrv"] = summary.get("lastNightAvg") or summary.get("weeklyAvg")
            except GccliError:
                entry["hrv"] = None

            # Only keep days that have at least one real metric
            if any(entry.get(k) is not None for k in ("resting_hr", "sleep_hours", "hrv")):
                metrics.append(entry)
        return metrics

    def get_profile(self, account: Optional[str] = None) -> Dict:
        try:
            return self._run_json(["auth", "status"], account=account)
        except GccliError:
            return {}
