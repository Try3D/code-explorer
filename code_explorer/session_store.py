"""Persistent session ID storage for claude CLI sessions, keyed by repo+branch."""

import json
import os
import tempfile
from datetime import datetime, timezone
from pathlib import Path

from .config import CACHE_DIR

_SESSIONS_PATH = CACHE_DIR / "sessions.json"


class SessionStore:
    """Stores and retrieves claude session IDs, keyed by 'owner/repo@branch'."""

    def __init__(self, path: Path = _SESSIONS_PATH) -> None:
        self._path = path

    def get(self, key: str) -> str | None:
        """Return the stored session_id for key, or None if not found."""
        data = self._load()
        entry = data.get(key)
        return entry["session_id"] if entry else None

    def save(self, key: str, session_id: str) -> None:
        """Store session_id for key, updating last_used_at."""
        data = self._load()
        data[key] = {
            "session_id": session_id,
            "last_used_at": datetime.now(timezone.utc).isoformat(),
        }
        self._write(data)

    def clear(self, key: str) -> None:
        """Remove the stored session for key (e.g. after session expiry)."""
        data = self._load()
        if key in data:
            del data[key]
            self._write(data)

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            return json.loads(self._path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}

    def _write(self, data: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=self._path.parent, suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            os.replace(tmp, self._path)
        except Exception:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
