"""GccliProvider — real Garmin connector backed by the isolated GccliRunner.

Multi-user: each provider instance is bound to one Garmin account (one RunIndex
user). The account email is set at construction time and never falls back to a
global credential after the per-user value is established.
"""

from __future__ import annotations

import logging
import os
from typing import Dict, List, Optional

from config.secrets import get_secret

from ..data_layer import GarminActivity
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

    def __init__(self, runner: GccliRunner, account: Optional[str] = None,
                 allow_global_account: bool = False):
        self._runner = runner
        # Per-user Garmin account email, bound at construction time.
        self._garmin_account = account
        # The global .env credentials (GARMIN_USERNAME/GARMIN_PASSWORD) may be
        # used ONLY by the legacy startup bootstrap provider. A per-user provider
        # MUST NEVER fall back to them — doing so would connect a RunIndex user
        # to the shared global Garmin account (data leak / broken multi-user).
        self._allow_global_account = allow_global_account

    def _account(self) -> Optional[str]:
        if self._garmin_account:
            return self._garmin_account
        if self._allow_global_account:
            return get_secret("GARMIN_USERNAME")
        return None

    def connect(self, user_id: str, garmin_username: Optional[str] = None,
                garmin_password: Optional[str] = None,
                simulate_mfa: bool = False) -> ConnectResult:
        if not self._runner.is_available():
            return ConnectResult(status=STATUS_ERROR, detail="Garmin connector unavailable.")

        # Per-user identity ONLY: the account comes from the credentials the
        # authenticated user supplied (or the account bound to this per-user
        # provider on reconnect). The global .env account is never used for a
        # user connection.
        account = garmin_username or self._garmin_account
        if self._allow_global_account and not account:
            account = get_secret("GARMIN_USERNAME")
        if not account:
            return ConnectResult(
                status=STATUS_ERROR,
                detail="Garmin credentials required. Please provide your Garmin username and password.",
            )

        # Already authenticated (per-user token persisted) -> connected immediately.
        if self._runner.is_authenticated(account):
            return ConnectResult(status=STATUS_CONNECTED, detail="Garmin connected")

        # A one-time login is required. The password MUST be supplied by the
        # user for this request — no global .env password fallback for users.
        password = garmin_password
        if self._allow_global_account and not password:
            password = get_secret("GARMIN_PASSWORD")
        if not password:
            return ConnectResult(
                status=STATUS_ERROR,
                detail="Garmin credentials required. Please provide your Garmin username and password.",
            )
        try:
            self._runner.login(account, password)
            return ConnectResult(status=STATUS_CONNECTED, detail="Garmin connected")
        except GccliMfaRequired:
            return ConnectResult(
                status=STATUS_MFA_REQUIRED,
                detail="Garmin requires additional verification. Please retry.",
            )
        except (GccliUnavailable, GccliError):
            logger.error("[gccli] connect failed")
            return ConnectResult(status=STATUS_ERROR, detail="Garmin connection failed.")

    def sync_activities(self, user_id: str, since: Optional[str] = None) -> List[Dict]:
        account = self._account()
        # Incremental (since given): fetch a small batch and keep only newer ones,
        # keeping Garmin API usage flat. Full sync: one page at the configured size.
        if since:
            limit = int(os.environ.get("GARMIN_INCREMENTAL_LIMIT", "10"))
        else:
            limit = int(os.environ.get("GARMIN_PAGE_SIZE", "50"))
        raw = self._runner.fetch_activities(limit=limit, account=account)
        acts = [self._normalize(a) for a in raw if a]
        if since:
            acts = [a for a in acts if (a.get("start_time") or "") > since]
        return acts

    def fetch_all_activities(self, page_size: int = 50) -> List[Dict]:
        """Fetch ALL available activities using paginated gccli calls.

        Loops with --start offset until gccli returns an empty page or fewer
        activities than page_size. Deduplicates by external_id so re-running is
        safe (idempotent). Intermediate errors are logged and stop the loop
        (partial results are returned rather than raising).
        """
        account = self._account()
        all_activities: List[Dict] = []
        seen_ids: set = set()
        start = 0

        while True:
            logger.info(
                "[gccli] deep sync page start=%d page_size=%d total_so_far=%d",
                start, page_size, len(all_activities),
            )
            try:
                page = self._runner.fetch_activities(
                    limit=page_size, start=start, account=account
                )
            except GccliError as exc:
                logger.error(
                    "[gccli] deep sync page error start=%d: %s; stopping pagination", start, exc
                )
                break

            if not page:
                logger.info("[gccli] deep sync empty page at start=%d; done", start)
                break

            added = 0
            for raw in page:
                if not raw:
                    continue
                normalized = self._normalize(raw)
                ext_id = normalized.get("external_id")
                if ext_id is None:
                    logger.debug("[gccli] skipping activity with no external_id: %s", raw)
                    continue
                if ext_id in seen_ids:
                    continue
                seen_ids.add(ext_id)
                all_activities.append(normalized)
                added += 1

            logger.info(
                "[gccli] deep sync page start=%d returned=%d added=%d total=%d",
                start, len(page), added, len(all_activities),
            )

            if len(page) < page_size:
                # Last page (partial): no more data available.
                break

            start += page_size

        logger.info("[gccli] deep sync complete total=%d", len(all_activities))
        return all_activities

    def get_daily_metrics(self, user_id: str, days: int = 7) -> List[Dict]:
        account = self._account()
        return self._runner.fetch_daily_metrics(days=days, account=account)

    def get_profile(self, user_id: str) -> Dict:
        return self._runner.get_profile(account=self._account())

    @staticmethod
    def _normalize(raw: Dict) -> Dict:
        # Delegate all field extraction to GarminActivity (PR01 model).
        normalized = GarminActivity.from_summary(raw)

        distance_m = normalized.distance_m
        duration_s = normalized.duration_s
        pace_spk = None
        if distance_m and duration_s and distance_m > 0:
            pace_spk = round(duration_s / (distance_m / 1000.0), 1)
        pace_str = None
        if pace_spk:
            m = int(pace_spk // 60)
            s = int(round(pace_spk % 60))
            if s == 60:
                m += 1
                s = 0
            pace_str = f"{m}:{s:02d}"

        ext_id = normalized.activity_id
        avg_hr = int(normalized.average_hr) if normalized.average_hr is not None else None
        activity_type = normalized.activity_type or "running"

        # Preserve the historical raw_payload shape (keyed from the original raw dict).
        raw_payload = {
            "activityId": raw.get("activityId") or raw.get("id"),
            "distance": distance_m,
            "duration": duration_s,
            "averageHR": raw.get("averageHR"),
            "averageSpeed": raw.get("averageSpeed"),
            "calories": raw.get("calories"),
            "elevationGain": raw.get("elevationGain"),
        }

        return {
            "external_id": ext_id,
            "source": "garmin",
            "name": raw.get("activityName"),
            "activity_type": activity_type,
            "start_time": normalized.start_time,
            "distance": distance_m,
            "duration": duration_s,
            "avg_hr": avg_hr,
            "pace": pace_str,
            "pace_seconds_per_km": pace_spk,
            "raw_payload": raw_payload,
            # New field added in PR02: full normalized model
            "garmin_activity": normalized.model_dump(),
        }
