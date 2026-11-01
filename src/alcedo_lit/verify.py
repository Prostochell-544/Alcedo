"""Check collected DOIs against the doi.org registry. Search sources sometimes hold mistyped DOIs."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor

import requests
from tqdm import tqdm

from .doi import encode_doi
from .net import SESSION, api_headers
from .results import NOT_REGISTERED, doi_of_line

HANDLE_API = "https://doi.org/api/handles/"
WORKERS = 8
HANDLE_NOT_FOUND = 100
HANDLE_EXISTS = {1, 200}  # 200 means the handle exists but the requested values do not


def doi_exists(doi: str, timeout: float) -> bool | None:
    """Ask the registry about a DOI. None means no clear answer, which is not evidence against it."""
    try:
        resp = SESSION.get(HANDLE_API + encode_doi(doi), headers=api_headers(), timeout=timeout)
        code = resp.json().get("responseCode")
    except (requests.RequestException, ValueError, AttributeError):
        return None
    if code == HANDLE_NOT_FOUND:
        return False
    return True if code in HANDLE_EXISTS else None


def verify_results(results: dict[str, list[str]], timeout: float) -> tuple[int, int]:
    """Mark DOIs the registry does not know. Each unique DOI is checked once.

    DOIs that could not be checked stay as they are. Returns (not registered, unchecked).
    """
    dois: dict[str, str] = {}
    for lines in results.values():
        for line in lines:
            if doi := doi_of_line(line):
                dois.setdefault(doi.lower(), doi)

    with ThreadPoolExecutor(WORKERS) as pool:
        answers = pool.map(lambda doi: doi_exists(doi, timeout), dois.values())
        progress = tqdm(answers, total=len(dois), desc="  checking DOIs", unit="doi", leave=False)
        status = dict(zip(dois, progress, strict=True))

    for query, lines in results.items():
        results[query] = [
            f"{NOT_REGISTERED}: {doi}" if (doi := doi_of_line(line)) and status[doi.lower()] is False else line
            for line in lines
        ]
    answered = list(status.values())
    return answered.count(False), answered.count(None)
