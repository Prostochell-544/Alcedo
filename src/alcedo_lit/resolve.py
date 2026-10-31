"""Find the DOI of a search result, trying the cheapest and most exact sources first."""

from __future__ import annotations

import argparse
import time
from collections import Counter
from urllib.parse import urlparse

import requests
from tqdm import tqdm

from .doi import (
    best_title_match,
    doi_from_meta,
    doi_from_url_pattern,
    doi_url,
    europepmc_query,
    exact_doi,
    extract_doi,
    normalize_title,
)
from .net import SESSION, api_headers
from .results import NOT_FOUND
from .sources.openalex import OPENALEX_TYPES, OPENALEX_URL

CROSSREF_URL = "https://api.crossref.org/works"
EUROPEPMC_URL = "https://www.ebi.ac.uk/europepmc/webservices/rest/search"
# Real publications only: without this filter Crossref also returns peer reviews and
# Faculty Opinions records (typed as datasets) that repeat the title of the paper.
CROSSREF_TYPES_FILTER = ",".join(
    f"type:{t}" for t in ("journal-article", "proceedings-article", "posted-content", "book-chapter",
                          "book", "monograph", "edited-book", "reference-entry", "report", "dissertation"))
MAX_PAGE_BYTES = 1_500_000
LOOKUP_PAUSE = 0.5  # seconds before each network lookup, to be polite to shared services
# Sites that do not serve pages to tools, or serve them without DOI meta tags.
NO_FETCH_HOSTS = ("researchgate.net", "academia.edu", "semanticscholar.org",
                  "scholar.google.", "books.google.")

# Lookups that failed, by service. A record may have a DOI that a failed lookup could not return.
failed_lookups: Counter[str] = Counter()


def doi_from_europepmc(query: str, mailto: str | None, timeout: float) -> str | None:
    params = {"query": query, "format": "json", "resultType": "lite"}
    resp = SESSION.get(EUROPEPMC_URL, params=params, headers=api_headers(mailto), timeout=timeout)
    resp.raise_for_status()
    found = resp.json().get("resultList", {}).get("result", [])
    return exact_doi(found[0].get("doi")) if found else None


def doi_from_page(url: str, timeout: float) -> str | None:
    """Read the DOI from the final URL after redirects or from the page's meta tags.

    Publisher sites never receive the user's e-mail address.
    """
    headers = {**api_headers(), "Accept": "text/html,application/xhtml+xml"}
    with SESSION.get(url, headers=headers, timeout=(5, timeout), stream=True) as resp:
        if doi := extract_doi(resp.url):
            return doi
        if resp.status_code != 200 or "html" not in resp.headers.get("Content-Type", ""):
            return None
        body = bytearray()
        for chunk in resp.iter_content(64 * 1024):
            body += chunk
            if len(body) > MAX_PAGE_BYTES:
                break
        encoding = resp.encoding or "utf-8"
    return doi_from_meta(body.decode(encoding, errors="replace"))


def doi_from_crossref(title: str, mailto: str | None, timeout: float) -> str | None:
    params = {"query.bibliographic": title, "rows": 10, "select": "DOI,title",
              "filter": CROSSREF_TYPES_FILTER}
    if mailto:
        params["mailto"] = mailto
    resp = SESSION.get(CROSSREF_URL, params=params, headers=api_headers(mailto), timeout=timeout)
    resp.raise_for_status()
    items = resp.json()["message"]["items"]
    return best_title_match(title, ((item.get("DOI"), t) for item in items for t in item.get("title") or []))


def doi_from_openalex(title: str, api_key: str | None, mailto: str | None, timeout: float) -> str | None:
    # Finds short titles that Crossref misses, such as "Array programming with NumPy".
    params = {"filter": f"title.search:{normalize_title(title)}", "per-page": 10, "select": "doi,title,type"}
    if api_key:
        params["api_key"] = api_key
    resp = SESSION.get(OPENALEX_URL, params=params, headers=api_headers(mailto), timeout=timeout)
    resp.raise_for_status()
    works = [w for w in resp.json()["results"] if w.get("type") in OPENALEX_TYPES]
    return best_title_match(title, ((exact_doi(w.get("doi")), w.get("title")) for w in works))


def _attempt(service: str, func, *func_args) -> str | None:
    """Call a network source. A failed request or an unexpected answer is counted, not fatal."""
    time.sleep(LOOKUP_PAUSE)
    try:
        return func(*func_args)
    except (requests.RequestException, ValueError, KeyError):
        failed_lookups[service] += 1
        return None


def find_doi(pub: dict, args: argparse.Namespace) -> str | None:
    if pub.get("doi"):  # the search source already gave it
        return pub["doi"]

    urls = [u for u in (pub.get("pub_url"), pub.get("eprint_url")) if u]

    # 1. No network needed: the DOI is in the URL or follows from an identifier in it.
    for url in urls:
        if doi := extract_doi(url) or doi_from_url_pattern(url):
            return doi

    # 2. PubMed and PMC links resolve through Europe PMC.
    for url in urls:
        if (query := europepmc_query(url)) and (
                doi := _attempt("Europe PMC", doi_from_europepmc, query, args.mailto, args.http_timeout)):
            return doi

    # 3. Meta tags of the publisher's page.
    if args.page_meta:
        for url in urls:
            parsed = urlparse(url)
            if any(h in parsed.netloc.lower() for h in NO_FETCH_HOSTS) or parsed.path.lower().endswith(".pdf"):
                continue
            if doi := _attempt("publisher pages", doi_from_page, url, args.http_timeout):
                return doi

    # 4. Title search: Crossref, then OpenAlex.
    if args.title_search and pub.get("title"):
        return (_attempt("Crossref", doi_from_crossref, pub["title"], args.mailto, args.http_timeout)
                or _attempt("OpenAlex", doi_from_openalex, pub["title"], args.openalex_key, args.mailto,
                            args.http_timeout))
    return None


def resolve_dois(pubs: list[dict], args: argparse.Namespace, source: str = "Google Scholar") -> list[str]:
    """Build the result lines of one query."""
    if not pubs:
        return [f"{NOT_FOUND} ({source} returned nothing)"]
    lines, seen = [], set()
    for pub in tqdm(pubs, desc="  resolving DOIs", unit="paper", leave=False):
        title = pub.get("title") or "untitled"
        try:
            doi = find_doi(pub, args)
        except Exception as exc:  # one odd record must not take down the whole run, but it must show
            tqdm.write(f"[!] Could not process '{title[:60]}': {type(exc).__name__}: {exc}")
            doi = None
        if not doi:
            lines.append(f"{NOT_FOUND}: {title}")
        elif doi.lower() not in seen:
            seen.add(doi.lower())
            lines.append(doi_url(doi))
    return lines
