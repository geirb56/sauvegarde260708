"""Provider abstraction — the only interface the rest of the app may use.

Important: implementations must contain NO logic that leaks the underlying
transport (gccli / mock / future OAuth) to callers. Callers interact only via:

    provider.connect(user_id)
    provider.sync_activities(user_id)
    provider.fetch_all_activities()
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

    def fetch_all_activities(self, page_size: int = 50) -> List[Dict]:
        """Fetch ALL available activities using pagination.

        Subclasses should override to implement paginated fetching.
        The default implementation raises NotImplementedError since full-history
        pagination requires provider-specific support.
        """
        raise NotImplementedError(
            f"Provider '{self.name}' does not implement fetch_all_activities(). "
            "Override this method to support full history pagination."
        )

    @abstractmethod
    def get_daily_metrics(
        self,
        user_id: str,
        days: int = 7,
        start_days_ago: int = 1,
    ) -> List[Dict]:
        """Return recent daily health metrics (HRV, resting HR, sleep).

        Each item: {date, hrv, resting_hr, sleep_hours, sleep_score, source}.
        """
        raise NotImplementedError

    def get_max_metrics(self, user_id: str, date: Optional[str] = None) -> List[Dict]:
        """Return the raw gccli health max-metrics payload.

        Callers normalize via ``GarminVO2Max.from_max_metrics()``.
        Returns ``[]`` when the provider does not support this endpoint.
        """
        return []

    @abstractmethod
    def get_profile(self, user_id: str) -> Dict:
        raise NotImplementedError
