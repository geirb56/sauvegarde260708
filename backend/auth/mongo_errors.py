from __future__ import annotations

try:
    from pymongo.errors import DuplicateKeyError  # type: ignore
except Exception:  # pragma: no cover - fallback for constrained test environments
    class DuplicateKeyError(Exception):  # type: ignore[no-redef]
        pass
