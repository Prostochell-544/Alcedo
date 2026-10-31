"""Shared HTTP session. Requests made here identify themselves as Alcedo."""

from __future__ import annotations

import requests

from . import __version__

SESSION = requests.Session()


def api_headers(mailto: str | None = None) -> dict[str, str]:
    contact = f" (mailto:{mailto})" if mailto else ""
    return {"User-Agent": f"alcedo/{__version__}{contact}"}
