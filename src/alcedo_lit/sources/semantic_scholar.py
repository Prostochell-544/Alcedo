"""Semantic Scholar: an open catalogue of papers with boolean search, used among the free sources."""

from __future__ import annotations

import argparse
import re
import time

import requests

from ..doi import exact_doi
from ..net import SESSION, api_headers
from . import RESULTS_PER_PAGE

SEMANTIC_SCHOLAR_URL = "https://api.semanticscholar.org/graph/v1/paper/search/bulk"


def to_semantic_scholar_query(query: str) -> str:
    """Translate Scholar-style syntax. Quotes, a leading minus and parentheses are shared, and a space means AND.

    OR becomes `|`, except inside a quoted phrase. There are no intitle:, author: or source: operators.
    """
    query = re.sub(r"\b(?:allintitle|intitle|author|source):", "", query, flags=re.I)
    parts = re.split(r'("[^"]*")', query)
    return "".join(part if part.startswith('"') else re.sub(r"\bOR\b", "|", part) for part in parts)


def search_semantic_scholar(query: str, args: argparse.Namespace, on_page=None) -> tuple[list[dict], str | None, bool]:
    """Return up to pages x 10 of the most cited matching papers, because this search has no relevance order.

    Without a key, all users share one limit, so a refusal is common and worth retrying.
    Returns (results, error, whether to stop using this source).
    """
    params = {"query": to_semantic_scholar_query(query), "fields": "title,externalIds", "sort": "citationCount:desc"}
    headers = api_headers(args.mailto)
    if args.semantic_scholar_key:
        headers["x-api-key"] = args.semantic_scholar_key
    error = None
    for attempt in range(3):
        time.sleep(1.1 + 3 * attempt)  # a key allows one request per second
        try:
            resp = SESSION.get(SEMANTIC_SCHOLAR_URL, params=params, headers=headers, timeout=args.http_timeout)
        except requests.RequestException as exc:
            error = f"{type(exc).__name__}: {exc}"
            continue
        if resp.status_code == 200:
            papers = (resp.json().get("data") or [])[:args.pages * RESULTS_PER_PAGE]
            return [{"title": p.get("title") or "", "doi": exact_doi((p.get("externalIds") or {}).get("DOI"))}
                    for p in papers], None, False
        error = f"HTTP {resp.status_code}"
        if resp.status_code == 429:
            error += " - shared limit reached; a free API key gives you your own limit"
        elif resp.status_code < 500:
            return [], error, resp.status_code in {401, 403}
    return [], error, False
