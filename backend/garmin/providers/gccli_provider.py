"""GccliProvider — real Garmin connector backed by the isolated GccliRunner.

NON-NEGOTIABLE constraint: the frontend never supplies a Garmin password.
Credentials for the one-time login are sourced ONLY from backend env vars
(GARMIN_USERNAME / GARMIN_PASSWORD), used once, then gccli persists an OAuth
token that auto-refreshes. The password is never stored by us.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from config.secrets import get_secret

from ..runner import GccliRunner, GccliUnavailable, GccliMfaRequired, GccliError
from .base import (
    ConnectResult,
    Provider,
    STATUS_CONNECTED,
    STATUS_ERROR,
    STATUS_MFA_REQUIRED,
)

logger = logging.getLogger(__name__)


class GccliProvider(Provider):
    name = "gccli"

    def __init__(self, runner: GccliRunner):
        self._runner = runner

    def _account(self) -> Optional[str]:
        return get_secret("GARMIN_USERNAME")

    def connect(self, user_id: str, simulate_mfa: bool = False) -> ConnectResult:
        if not self._runner.is_available():
            return ConnectResult(status=STATUS_ERROR, detail="Garmin connector unavailable.")

        account = self._account()
        # Already authenticated (token persisted) -> connected immediately.
        if self._runner.is_authenticated(account):
            return ConnectResult(status=STATUS_CONNECTED, detail="Garmin connected")

        # Need a one-time login using backend-controlled credentials.
        password = get_secret("GARMIN_PASSWORD")
        if not account or not password:
            return ConnectResult(status=STATUS_ERROR, detail="Garmin connector not configured.")
        try:
            self._runner.login(account, password)
            return ConnectResult(status=STATUS_CONNECTED, detail="Garmin connected")
        except GccliMfaRequired:
            return ConnectResult(
                status=STATUS_MFA_REQUIRED,
                detail="Garmin requires additional verification. Please retry.",
            )
        except (GccliUnavailable, GccliError) as exc:
            logger.error("[gccli] connect failed: %s", exc)
            return ConnectResult(status=STATUS_ERROR, detail="Garmin connection failed.")

    def sync_activities(self, user_id: str, since: Optional[str] = None) -> List[Dict]:
        account = self._account()
        # Incremental (since given): fetch a small batch and keep only newer ones,
        # keeping Garmin API usage flat. Full sync: a larger recent window.
        if since:
            limit = int(os.environ.get("GARMIN_INCREMENTAL_LIMIT", "10"))
        else:
            limit = int(os.environ.get("GARMIN_FULL_LIMIT", "30"))
        raw = self._runner.fetch_activities(limit=limit, account=account)
        acts = [self._normalize(a) for a in raw if a]
        if since:
            acts = [a for a in acts if (a.get("start_time") or "") > since]
        return acts

    def get_daily_metrics(self, user_id: str, days: int = 7) -> List[Dict]:
        account = self._account()
        return self._runner.fetch_daily_metrics(days=days, account=account)

    def get_profile(self, user_id: str) -> Dict:
        return self._runner.get_profile(account=self._account())

    @staticmethod
    def _normalize(raw: Dict) -> Dict:
        atype = raw.get("activityType")
        if isinstance(atype, dict):
            atype = atype.get("typeKey")
        distance_m = raw.get("distance")
        duration_s = raw.get("duration")
        pace_spk = None
        if distance_m and duration_s and distance_m > 0:
            pace_spk = round(duration_s / (distance_m / 1000.0), 1)
        ext_id = raw.get("activityId") or raw.get("id")
        pace_str = None
        if pace_spk:
            m = int(pace_spk // 60)
            s = int(round(pace_spk % 60))
            if s == 60:
                m += 1
                s = 0
            pace_str = f"{m}:{s:02d}"
        return {
            "external_id": str(ext_id) if ext_id is not None else None,
            "source": "garmin",
            "name": raw.get("activityName"),
            "activity_type": atype or "running",
            "start_time": raw.get("startTimeLocal") or raw.get("startTimeGMT"),
            "distance": distance_m,
            "duration": duration_s,
            "avg_hr": int(raw["averageHR"]) if raw.get("averageHR") else None,
            "pace": pace_str,
            "pace_seconds_per_km": pace_spk,
            "raw_payload": {
                "activityId": ext_id,
                "distance": distance_m,
                "duration": duration_s,
                "averageHR": raw.get("averageHR"),
                "averageSpeed": raw.get("averageSpeed"),
                "calories": raw.get("calories"),
                "elevationGain": raw.get("elevationGain"),
            },
        }
