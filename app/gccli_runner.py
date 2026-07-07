import subprocess
import tempfile
import os
import shutil
import logging
from typing import List, Dict
from time import sleep

logger = logging.getLogger(__name__)

class GccliError(Exception):
    pass

class GccliRunner:
    def __init__(self, gccli_path: str = "gccli", timeout_seconds: int = 30, max_retries: int = 3):
        self.gccli_path = gccli_path
        self.timeout = timeout_seconds
        self.max_retries = max_retries

    def _run_cmd(self, args: List[str], input_bytes: bytes | None = None, env=None) -> subprocess.CompletedProcess:
        last_exc = None
        for attempt in range(1, self.max_retries + 1):
            try:
                cp = subprocess.run(
                    args,
                    input=input_bytes,
                    stdout=subprocess.PIPE,
                    stderr=subprocess.PIPE,
                    timeout=self.timeout,
                    check=True,
                    env=env,
                )
                return cp
            except subprocess.CalledProcessError as e:
                last_exc = e
                logger.warning("gccli command failed (attempt %d/%d): %s", attempt, self.max_retries, e)
                if attempt < self.max_retries:
                    sleep(1 * attempt)
                    continue
                raise GccliError("gccli call failed") from e
            except subprocess.TimeoutExpired as e:
                last_exc = e
                logger.warning("gccli command timed out (attempt %d/%d)", attempt, self.max_retries)
                if attempt < self.max_retries:
                    continue
                raise GccliError("gccli timed out") from e
        raise last_exc or GccliError("gccli unknown error")

    def login(self, username: str, password: str, workdir: str) -> None:
        assert os.path.isdir(workdir)
        cmd = [self.gccli_path, "login", "--username", username]
        pfile = None
        try:
            pfile = tempfile.NamedTemporaryFile(mode="w+", delete=False, dir=workdir)
            pfile.write(password)
            pfile.flush()
            os.fchmod(pfile.fileno(), 0o600)
            pfile.close()
            cmd += ["--password-file", pfile.name]
            self._run_cmd(cmd, env=os.environ.copy())
        finally:
            if pfile:
                try:
                    os.remove(pfile.name)
                except Exception:
                    logger.exception("failed to remove temp password file")

    def fetch_activities(self, username: str, password: str, since: str | None = None) -> List[Dict]:
        tmpdir = tempfile.mkdtemp(prefix="gccli-")
        try:
            self.login(username, password, workdir=tmpdir)
            cmd = [self.gccli_path, "activities", "list", "--output", "json"]
            if since:
                cmd += ["--since", since]
            cp = self._run_cmd(cmd, env=os.environ.copy())
            import json
            activities = json.loads(cp.stdout.decode("utf-8"))
            return activities
        finally:
            try:
                shutil.rmtree(tmpdir)
            except Exception:
                logger.exception("cleanup tmpdir failed")

    def export_fit(self, activity_id: str, username: str, password: str) -> bytes:
        tmpdir = tempfile.mkdtemp(prefix="gccli-")
        try:
            self.login(username, password, workdir=tmpdir)
            cmd = [self.gccli_path, "activity", "export", activity_id, "--format", "fit", "--stdout"]
            cp = self._run_cmd(cmd, env=os.environ.copy())
            return cp.stdout
        finally:
            try:
                shutil.rmtree(tmpdir)
            except Exception:
                logger.exception("cleanup tmpdir failed")

    def get_profile(self, username: str, password: str) -> Dict:
        tmpdir = tempfile.mkdtemp(prefix="gccli-")
        try:
            self.login(username, password, workdir=tmpdir)
            cmd = [self.gccli_path, "profile", "get", "--output", "json"]
            cp = self._run_cmd(cmd, env=os.environ.copy())
            import json
            return json.loads(cp.stdout.decode("utf-8"))
        finally:
            shutil.rmtree(tmpdir, ignore_errors=True)
