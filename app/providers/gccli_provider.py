from typing import List, Dict, Optional
from .base import Provider
from app.credential_vault import CredentialVault
from app.gccli_runner import GccliRunner
import logging

logger = logging.getLogger(__name__)

class GccliProvider(Provider):
    def __init__(self, credential_vault: CredentialVault, runner: GccliRunner):
        self.vault = credential_vault
        self.runner = runner

    def sync_activities(self, user_id: str, since: Optional[str] = None) -> List[Dict]:
        token = self.vault.get_token_for_user(user_id)
        if token is None:
            raise RuntimeError("No credentials available for user")

        try:
            username, password = self.vault.get_credentials(token)
            raw_activities = self.runner.fetch_activities(username=username, password=password, since=since)
            normalized = [self._normalize_activity(a) for a in raw_activities]
            return normalized
        finally:
            # suppression immédiate
            self.vault.delete_credentials(token)

    def get_profile(self, user_id: str) -> Dict:
        token = self.vault.get_token_for_user(user_id)
        if token is None:
            return {}
        username, password = self.vault.get_credentials(token)
        try:
            profile = self.runner.get_profile(username=username, password=password)
            return profile
        finally:
            self.vault.delete_credentials(token)

    def _normalize_activity(self, raw: Dict) -> Dict:
        return {
            "external_id": raw.get("id"),
            "source": "garmin",
            "distance": raw.get("distance_m"),
            "duration": raw.get("duration_s"),
            "avg_hr": raw.get("avg_hr"),
            "pace": raw.get("avg_pace"),
            "raw_payload": raw,
        }
