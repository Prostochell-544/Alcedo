"""Google Scholar results through SearchApi, using the user's own API key."""

from __future__ import annotations

import argparse

import requests

from ..net import SESSION
from . import RESULTS_PER_PAGE

SEARCHAPI_URL = "https://www.searchapi.io/api/v1/search"
SEARCHAPI_PAGE_SIZE = 20  # the page size stays fixed because the page number sets the offset
KEY_OR_QUOTA_STATUSES = {401, 402, 403, 429}


def search_searchapi(query: str, args: argparse.Namespace, on_page=None) -> tuple[list[dict], str | None, bool]:
    """Fetch Scholar results in pages of 20, up to pages x 10 in total.

    Each page costs one request from the quota, so 50 results cost 3 requests. The key
    travels in a header, not in the URL. Returns (results, error, whether to stop using this API).
    """
    limit = args.pages * RESULTS_PER_PAGE
    pubs: list[dict] = []
    page = 1
    while len(pubs) < limit:
        params = {"engine": "google_scholar", "q": query, "hl": "en", "page": page, "num": SEARCHAPI_PAGE_SIZE}
        try:
            resp = SESSION.get(SEARCHAPI_URL, params=params, headers={"Authorization": f"Bearer {args.searchapi_key}"},
                               timeout=args.page_timeout)
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            return pubs[:limit], f"{type(exc).__name__}: {exc}", False
        if resp.status_code != 200:
            error = str(data.get("error") or f"HTTP {resp.status_code}")
            return pubs[:limit], error, resp.status_code in KEY_OR_QUOTA_STATUSES

        results = data.get("organic_results") or []
        pubs += [{"title": r.get("title") or "", "pub_url": r.get("link"),
                  "eprint_url": (r.get("resource") or {}).get("link")} for r in results]
        # Without a link to the next page, stop: another request would waste quota.
        if not results or not (data.get("pagination") or {}).get("next"):
            break
        page += 1
        if on_page and len(pubs) < limit:
            on_page(page - 1)
    return pubs[:limit], None, False
