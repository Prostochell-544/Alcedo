"""A local cache of lookups, so a repeated run does not ask the same services again.

It holds titles and links of the records you searched for, and stays on your computer.
"""

from __future__ import annotations

import json
import os
import sqlite3
import sys
import time
from pathlib import Path

DAY = 86400
MISS = object()  # a stored None means "looked this up, and there is nothing"


def cache_path() -> Path:
    base = os.environ.get("ALCEDO_CACHE_DIR")
    if not base:
        if sys.platform == "win32":
            base = os.environ.get("LOCALAPPDATA") or str(Path.home())
        else:
            base = os.environ.get("XDG_CACHE_HOME") or str(Path.home() / ".cache")
    return Path(base) / "alcedo" / "cache.sqlite3"


class Cache:
    """Stores JSON values by kind and key. A cache that cannot work turns itself off instead of stopping a run."""

    def __init__(self, path: Path | None = None) -> None:
        self.path = path or cache_path()
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            self.db: sqlite3.Connection | None = sqlite3.connect(self.path)
            # Waiting for the disk on every write made runs slow, and losing a cache entry costs only one more lookup.
            self.db.execute("PRAGMA synchronous = OFF")
            self.db.execute("PRAGMA journal_mode = MEMORY")
            with self.db:
                self.db.execute("CREATE TABLE IF NOT EXISTS entries "
                                "(kind TEXT, key TEXT, value TEXT, saved_at REAL, PRIMARY KEY (kind, key))")
        except (OSError, sqlite3.Error) as exc:
            self._turn_off(exc)

    def _turn_off(self, exc: Exception) -> None:
        print(f"Working without a cache: {self.path}: {exc}", file=sys.stderr)
        self.db = None

    def get(self, kind: str, key: str, max_age_days: float):
        """Return the stored value, or MISS if there is none or it is too old."""
        if self.db is None:
            return MISS
        try:
            row = self.db.execute("SELECT value, saved_at FROM entries WHERE kind = ? AND key = ?",
                                  (kind, key)).fetchone()
        except sqlite3.Error as exc:
            self._turn_off(exc)
            return MISS
        if row is None or time.time() - row[1] > max_age_days * DAY:
            return MISS
        return json.loads(row[0])

    def set(self, kind: str, key: str, value) -> None:
        if self.db is None:
            return
        try:
            with self.db:
                self.db.execute("INSERT OR REPLACE INTO entries VALUES (?, ?, ?, ?)",
                                (kind, key, json.dumps(value, ensure_ascii=False), time.time()))
        except sqlite3.Error as exc:
            self._turn_off(exc)
