from abc import ABC, abstractmethod
from typing import List, Dict, Optional

class Provider(ABC):
    """Interface métier que le reste de l'application utilise.

    Important: ne contient aucune logique gccli/terra.
    """

    @abstractmethod
    def sync_activities(self, user_id: str, since: Optional[str] = None) -> List[Dict]:
        raise NotImplementedError

    @abstractmethod
    def get_profile(self, user_id: str) -> Dict:
        raise NotImplementedError
