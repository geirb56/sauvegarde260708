from typing import List, Dict, Optional
from .base import Provider

class TerraProvider(Provider):
    def sync_activities(self, user_id: str, since: Optional[str] = None) -> List[Dict]:
        # stub implementation for future Terra API
        return []

    def get_profile(self, user_id: str) -> Dict:
        return {}
