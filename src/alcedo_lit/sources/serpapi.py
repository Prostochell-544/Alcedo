"""Google Scholar results through SerpApi, using the user's own API key."""

from __future__ import annotations

import argparse

import requests

from ..net import SESSION
from . import RESULTS_PER_PAGE

SERPAPI_URL = "https://serpapi.com/search.json"
SERPAPI_ACCOUNT_URL = "https://serpapi.com/account.json"
SERPAPI_PAGE_SIZE = 20  # the most Scholar results SerpApi returns for one search


def serpapi_account(key: str, timeout: float) -> dict:
    """Return the remaining quota. The Account API is free and uses no searches."""
    resp = SESSION.get(SERPAPI_ACCOUNT_URL, params={"api_key": key}, timeout=timeout)
    data = resp.json()
    if resp.status_code != 200 or data.get("error"):
        raise RuntimeError(data.get("error") or f"HTTP {resp.status_code}")
    return data


def search_serpapi(query: str, args: argparse.Namespace, on_page=None) -> tuple[list[dict], str | None, bool]:
    """Fetch Scholar results in pages of 20, up to pages x 10 in total.

    Each page costs one search from the quota, so 50 results cost 3 searches.
    Returns (results, error, whether the SerpApi limit was reached).
    """
    limit = args.pages * RESULTS_PER_PAGE
    pubs, start = [], 0
    while start < limit:
        num = min(SERPAPI_PAGE_SIZE, limit - start)
        params = {"engine": "google_scholar", "q": query, "hl": "en", "start": start, "num": num,
                  "api_key": args.serpapi_key}
        try:
            resp = SESSION.get(SERPAPI_URL, params=params, timeout=args.page_timeout)
            data = resp.json()
        except (requests.RequestException, ValueError) as exc:
            return pubs, f"{type(exc).__name__}: {exc}", False
        error = data.get("error") or ""
        if resp.status_code == 200 and "hasn't returned any results" in error:
            break  # the results are empty or have run out
        # 429 means the hourly limit was exceeded or the monthly searches ran out.
        if resp.status_code == 429 or "run out of searches" in error:
            return pubs, error or "HTTP 429", True
        if resp.status_code != 200 or error:
            return pubs, error or f"HTTP {resp.status_code}", False

        page = data.get("organic_results") or []
        pubs += [{"title": r.get("title") or "",
                  "pub_url": r.get("link"),
                  "eprint_url": next((x["link"] for x in r.get("resources") or [] if x.get("link")), None)}
                 for r in page]
        start += num
        # Without a link to the next page, stop: another search would waste quota.
        if not page or not (data.get("serpapi_pagination") or {}).get("next"):
            break
        if on_page and start < limit:
            on_page(start // SERPAPI_PAGE_SIZE)
    return pubs[:limit], None, False
