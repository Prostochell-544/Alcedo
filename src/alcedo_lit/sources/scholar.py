"""Experimental direct access to Google Scholar through the optional scholarly package.

Google Scholar's robots.txt disallows automated search, so this source is off by
default and needs --direct-scholar. Alcedo only paces the requests and stops asking
when Scholar refuses. scholarly itself sends a random browser User-Agent and may try to
open a browser when it meets a captcha; it has no setting to turn that off.
Prefer SerpApi or OpenAlex.
"""

from __future__ import annotations

import argparse
import itertools
import multiprocessing
import time

from . import RESULTS_PER_PAGE

SCHOLAR_HTTP_TIMEOUT = 20  # seconds, for one HTTP request inside scholarly
SCHOLAR_RETRIES = 2
PAGE_DELAY = 8  # seconds to wait before the next page of the same query
INSTALL_HINT = 'pip install "alcedo-lit[scholar]"'
WARNING = ("Direct Google Scholar access is experimental. Scholar's robots.txt disallows automated search, "
           "and you are responsible for following Google's terms. The scholarly library sends a random browser "
           "User-Agent and may try to open a browser for a captcha. Prefer --serpapi-key or OpenAlex.")


def load_scholarly(proxy: str | None):
    from scholarly import ProxyGenerator, scholarly

    scholarly.set_timeout(SCHOLAR_HTTP_TIMEOUT)
    scholarly.set_retries(SCHOLAR_RETRIES)
    if proxy:
        pg = ProxyGenerator()
        try:
            ok = pg.SingleProxy(http=proxy, https=proxy)
        except TypeError as exc:
            if "proxies" in str(exc):
                raise RuntimeError(f"scholarly cannot use a proxy with httpx>=0.28: {INSTALL_HINT}") from exc
            raise
        if not ok:
            raise RuntimeError("the proxy failed its check")
        scholarly.use_proxy(pg, pg)
    return scholarly


def _search_worker(query: str, max_pages: int, proxy: str | None, conn) -> None:
    """Run one query in a separate process and send the results page by page.

    Sending per page keeps what was already received if Scholar refuses a later
    page. scholarly loads the next page by itself when the current one runs out, and
    the iterator simply ends if there are fewer than `max_pages`.
    """
    page = []
    try:
        scholarly = load_scholarly(proxy)
        limit = max_pages * RESULTS_PER_PAGE
        for n, pub in enumerate(itertools.islice(scholarly.search_pubs(query), limit), 1):
            page.append({
                "title": (pub.get("bib") or {}).get("title") or "",
                "pub_url": pub.get("pub_url"),
                "eprint_url": pub.get("eprint_url"),
            })
            if n % RESULTS_PER_PAGE == 0 and n < limit:
                conn.send(("page", page))
                page = []
                time.sleep(PAGE_DELAY)
        conn.send(("done", page))
    except Exception as exc:
        if page:
            conn.send(("page", page))
        conn.send(("error", f"{type(exc).__name__}: {exc}"))
    finally:
        conn.close()


def search_scholar(query: str, args: argparse.Namespace, on_page=None) -> tuple[list[dict], str | None]:
    """Run a query in a separate process with a hard timeout for each page.

    A separate process can simply be killed. That is needed because scholarly retries
    a 403 response forever, waiting 1-2 minutes each time.

    Returns (results, error). Pages received before a failure are still returned.
    """
    ctx = multiprocessing.get_context("spawn")
    reader, writer = ctx.Pipe(duplex=False)
    proc = ctx.Process(target=_search_worker, daemon=True, args=(query, args.pages, args.proxy, writer))
    proc.start()
    writer.close()
    pubs, error = [], None
    try:
        while True:
            # The wait counts from the last page received, plus the pause between pages.
            if not reader.poll(args.page_timeout + PAGE_DELAY):
                error = f"Google Scholar did not answer within {args.page_timeout:.0f} s"
                break
            status, payload = reader.recv()
            if status == "error":
                error = payload
                break
            pubs.extend(payload)
            if status == "done":
                break
            if on_page:
                on_page(len(pubs) // RESULTS_PER_PAGE)
    except (EOFError, OSError):  # the process ended before sending its answer
        error = "the search process crashed"
    finally:
        if proc.is_alive():
            proc.terminate()
        proc.join(5)
        reader.close()
    return pubs, error
