"""Google Scholar results through Serper, using the user's own API key.

The request and the fields come from Serper's site and from its answer to an invalid key.
This source has not yet been run with a real key.
"""

from __future__ import annotations

import argparse

import requests

from ..net import SESSION
from . import RESULTS_PER_PAGE

SERPER_URL = "https://google.serper.dev/scholar"
KEY_OR_QUOTA_STATUSES = {401, 402, 403, 429}


def search_serper(query: str, args: argparse.Namespace, on_page=None) -> tuple[list[dict], str | None, bool]:
    """Fetch Scholar results page by page, up to pages x 10 in total.

    The key travels in a header, not in the URL. Returns (results, error, whether to stop using this API).
    """
    limit = args.pages * RESULTS_PER_PAGE
    pubs: list[dict] = []
    seen: set[str] = set()
    page = 1
    while len(pubs) < limit:
        try:
            resp = SESSION.post(SERPER_URL, json={"q": query, "page": page}, headers={"X-API-KEY": args.serper_key},
                                timeout=args.page_timeout)
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            return pubs[:limit], f"{type(exc).__name__}: {exc}", False
        if resp.status_code != 200:
            error = str(data.get("message") or f"HTTP {resp.status_code}")
            return pubs[:limit], error, resp.status_code in KEY_OR_QUOTA_STATUSES or "credit" in error.lower()

        # Serper gives no link to the next page, so an empty or repeated page ends the list.
        new = [r for r in data.get("organic") or [] if (r.get("title") or "") not in seen]
        if not new:
            break
        seen.update(r.get("title") or "" for r in new)
        pubs += [{"title": r.get("title") or "", "pub_url": r.get("link"), "eprint_url": r.get("pdfUrl")} for r in new]
        page += 1
        if on_page and len(pubs) < limit:
            on_page(page - 1)
    return pubs[:limit], None, False
