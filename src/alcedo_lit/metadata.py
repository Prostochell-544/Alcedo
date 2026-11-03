"""Fetch what is known about each DOI: OpenAlex in batches, then Crossref for what OpenAlex lacks."""

from __future__ import annotations

import argparse
import html
import re
import time
from urllib.parse import quote

import requests
from tqdm import tqdm

from .cache import MISS, Cache
from .net import SESSION, api_headers
from .resolve import CROSSREF_URL
from .sources.openalex import OPENALEX_URL

BATCH_SIZE = 50
FOUND_MAX_AGE_DAYS = 30  # short, because a paper can be retracted later
NOT_FOUND_MAX_AGE_DAYS = 7
CACHE_KIND = "metadata-1"
OPENALEX_FIELDS = ("doi,title,publication_year,language,type,is_retracted,primary_location,authorships,biblio,"
                   "abstract_inverted_index")


def _abstract_text(inverted: dict | None) -> str | None:
    if not inverted:
        return None
    words = sorted((place, word) for word, places in inverted.items() for place in places)
    return " ".join(word for _, word in words)


def record_from_openalex(work: dict) -> dict:
    source = (work.get("primary_location") or {}).get("source") or {}
    biblio = work.get("biblio") or {}
    first, last = biblio.get("first_page"), biblio.get("last_page")
    return {
        "title": work.get("title"),
        "year": work.get("publication_year"),
        "journal": source.get("display_name"),
        "issn": source.get("issn") or ([source["issn_l"]] if source.get("issn_l") else []),
        "language": work.get("language"),
        "type": work.get("type"),
        "retracted": work.get("is_retracted"),
        "authors": [(a.get("author") or {}).get("display_name") for a in work.get("authorships") or []],
        "volume": biblio.get("volume"),
        "issue": biblio.get("issue"),
        "pages": f"{first}-{last}" if first and last and first != last else first,
        "abstract": _abstract_text(work.get("abstract_inverted_index")),
        "source": "OpenAlex",
    }


def record_from_crossref(message: dict) -> dict:
    date_parts = ((message.get("issued") or {}).get("date-parts") or [[None]])[0]
    abstract = message.get("abstract")
    authors = [" ".join(p for p in (a.get("given"), a.get("family")) if p) or a.get("name")
               for a in message.get("author") or []]
    return {
        "title": (message.get("title") or [None])[0],
        "year": date_parts[0] if date_parts else None,
        "journal": (message.get("container-title") or [None])[0],
        "issn": message.get("ISSN") or [],
        "language": message.get("language"),
        "type": message.get("type"),
        # Crossref has no general retraction flag, so None means "not known", not "not retracted".
        "retracted": None,
        "authors": authors,
        "volume": message.get("volume"),
        "issue": message.get("issue"),
        "pages": message.get("page"),
        "abstract": html.unescape(re.sub(r"<[^>]+>", "", abstract)).strip() if abstract else None,
        "source": "Crossref",
    }


def _openalex_batch(dois: list[str], args: argparse.Namespace) -> dict[str, dict] | None:
    """Return records by lowercase DOI, or None if OpenAlex did not answer."""
    params = {"filter": "doi:" + "|".join(dois), "per-page": BATCH_SIZE, "select": OPENALEX_FIELDS}
    if args.openalex_key:
        params["api_key"] = args.openalex_key
    for attempt in range(3):
        time.sleep(3 * attempt)
        try:
            resp = SESSION.get(OPENALEX_URL, params=params, headers=api_headers(args.mailto),
                               timeout=args.http_timeout)
        except requests.RequestException:
            continue
        if resp.status_code == 200:
            return {(work.get("doi") or "").removeprefix("https://doi.org/").lower(): record_from_openalex(work)
                    for work in resp.json().get("results", [])}
        if resp.status_code != 429 and resp.status_code < 500:
            break
    return None


def _crossref_one(doi: str, args: argparse.Namespace) -> tuple[dict | None, bool]:
    """Return (record or None, whether Crossref gave a clear answer)."""
    time.sleep(0.1)
    try:
        resp = SESSION.get(f"{CROSSREF_URL}/{quote(doi, safe='')}", headers=api_headers(args.mailto),
                           timeout=args.http_timeout)
    except requests.RequestException:
        return None, False
    if resp.status_code == 200:
        return record_from_crossref(resp.json()["message"]), True
    return None, resp.status_code == 404


def fetch_metadata(dois: list[str], args: argparse.Namespace, cache: Cache | None = None) -> tuple[dict, list[str]]:
    """Return (records by lowercase DOI, DOIs that could not be checked).

    A DOI that no service knows maps to None. A DOI with a failed lookup is left out and not cached, so a later run
    can try again. Only clear answers are cached.
    """
    records: dict[str, dict | None] = {}
    todo = []
    for doi in dict.fromkeys(d.lower() for d in dois):
        if cache is not None and (found := cache.get(CACHE_KIND, doi, FOUND_MAX_AGE_DAYS)) is not MISS and found:
            records[doi] = found
        elif cache is not None and cache.get(CACHE_KIND + "-none", doi, NOT_FOUND_MAX_AGE_DAYS) is not MISS:
            records[doi] = None
        else:
            todo.append(doi)

    # A comma would split the OpenAlex filter, so such a DOI goes straight to Crossref.
    batchable = [d for d in todo if "," not in d and "|" not in d]
    answered: dict[str, dict] = {}
    openalex_failed: set[str] = set()
    batches = [batchable[i:i + BATCH_SIZE] for i in range(0, len(batchable), BATCH_SIZE)]
    for batch in tqdm(batches, desc="  fetching metadata", unit="batch", leave=False):
        found = _openalex_batch(batch, args)
        if found is None:
            openalex_failed.update(batch)
        else:
            answered.update(found)

    unchecked = []
    for doi in todo:
        record = answered.get(doi)
        clear = record is not None
        if record is None:
            record, clear = _crossref_one(doi, args)
            # If OpenAlex failed and Crossref has no such DOI, the answer is still not known.
            clear = clear and (record is not None or doi not in openalex_failed)
        if not clear:
            unchecked.append(doi)
            continue
        records[doi] = record
        if cache is not None:
            if record:
                cache.set(CACHE_KIND, doi, record)
            else:
                cache.set(CACHE_KIND + "-none", doi, True)
    return records, unchecked
