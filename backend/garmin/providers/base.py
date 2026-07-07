"""Provider abstraction — the only interface the rest of the app may use.

Important: implementations must contain NO logic that leaks the underlying
transport (gccli / mock / future OAuth) to callers. Callers interact only via:

    provider.connect(user_id)
    provider.sync_activities(user_id)
    provider.get_profile(user_id)
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Dict, List, Optional

# Connection statuses returned by connect()
STATUS_CONNECTED = "connected"
STATUS_MFA_REQUIRED = "mfa_required"
STATUS_ERROR = "error"


@dataclass
class ConnectResult:
    status: str  # one of STATUS_*
    detail: str = ""


class Provider(ABC):
    """Business interface used by the service layer."""

    name: str = "base"

    @abstractmethod
    def connect(self, user_id: str, simulate_mfa: bool = False) -> ConnectResult:
        """Establish an authenticated Garmin session (auth abstracted backend-side).

        Must never require the frontend to provide a Garmin password.
        """
        raise NotImplementedError

    @abstractmethod
    def sync_activities(self, user_id: str, since: Optional[str] = None) -> List[Dict]:
        raise NotImplementedError

    @abstractmethod
    def get_daily_metrics(self, user_id: str, days: int = 7) -> List[Dict]:
        """Return recent daily health metrics (HRV, resting HR, sleep).

        Each item: {date, hrv, resting_hr, sleep_hours, sleep_score, source}.
        """
        raise NotImplementedError

    @abstractmethod
    def get_profile(self, user_id: str) -> Dict:
        raise NotImplementedError
