"""OpenAlex: an open catalogue of scholarly works, used as the default source."""

from __future__ import annotations

import argparse
import re
import time

import requests

from ..doi import exact_doi
from ..net import SESSION, api_headers
from . import RESULTS_PER_PAGE

OPENALEX_URL = "https://api.openalex.org/works"
OPENALEX_TYPES = {"article", "preprint", "review", "book-chapter", "book", "dissertation", "report", "standard"}


def to_openalex_query(query: str) -> str:
    """Translate Scholar-style syntax. Quotes, OR and parentheses are shared.

    OpenAlex ignores a leading minus, so `-word` becomes `NOT word`. It has no
    intitle:, author: or source: operators, so those prefixes are dropped.
    """
    query = re.sub(r'(^|\s)-(?=["\w(])', r"\1NOT ", query)
    return re.sub(r"\b(?:allintitle|intitle|author|source):", "", query, flags=re.I)


def search_openalex(query: str, args: argparse.Namespace) -> tuple[list[dict], str | None]:
    """Return up to pages x 10 of the most relevant works that have a DOI, and an error if any."""
    params = {
        "search": to_openalex_query(query),
        "filter": "has_doi:true,type:" + "|".join(sorted(OPENALEX_TYPES)),
        "per-page": min(args.pages * RESULTS_PER_PAGE, 200),
        "select": "doi,title",
    }
    if args.openalex_key:
        params["api_key"] = args.openalex_key
    error = None
    for attempt in range(3):
        time.sleep(3 * attempt)
        try:
            resp = SESSION.get(OPENALEX_URL, params=params, headers=api_headers(args.mailto),
                               timeout=args.http_timeout)
        except requests.RequestException as exc:
            error = f"{type(exc).__name__}: {exc}"
            continue
        if resp.status_code == 200:
            works = resp.json().get("results", [])
            return [{"title": w.get("title") or "", "doi": exact_doi(w.get("doi"))} for w in works], None
        error = f"HTTP {resp.status_code}"
        if resp.status_code == 429:
            error += " - OpenAlex budget used up; get a free API key and pass it with --openalex-key"
        elif resp.status_code < 500:
            break  # retrying will not fix any other 4xx
    return [], error
