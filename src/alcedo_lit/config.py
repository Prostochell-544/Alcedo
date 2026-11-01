"""Saved settings: the user's API keys and their choice about direct Google Scholar search."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def config_path() -> Path:
    base = os.environ.get("ALCEDO_CONFIG_DIR")
    if not base:
        if sys.platform == "win32":
            base = os.environ.get("APPDATA") or str(Path.home())
        else:
            base = os.environ.get("XDG_CONFIG_HOME") or str(Path.home() / ".config")
    return Path(base) / "alcedo" / "config.json"


def load_config() -> dict:
    try:
        data = json.loads(config_path().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    return data if isinstance(data, dict) else {}


def save_config(values: dict) -> Path:
    path = config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(values, indent=1), encoding="utf-8")
    try:
        path.chmod(0o600)  # keys are stored as plain text, so only the owner should read them
    except OSError:
        pass
    return path
