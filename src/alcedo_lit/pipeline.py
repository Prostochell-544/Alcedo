"""Run a list of queries: pick the source, fall back when needed, save after every query."""

from __future__ import annotations

import argparse
import math
import sys
import time

from tqdm import tqdm

from .resolve import failed_lookups, resolve_dois
from .results import ERROR_PREFIX, NOT_FOUND, SOURCE_PREFIX, is_results_file, load_results, read_queries, save_results
from .sources import RESULTS_PER_PAGE, openalex, scholar, serpapi


def shorten(text: str, width: int = 50) -> str:
    return text if len(text) <= width else text[:width - 3] + "..."


def redact(text: str, args: argparse.Namespace) -> str:
    """Remove API keys and proxy credentials from error text, which reaches the console and the file.

    The SerpApi key travels in the URL, and requests includes the URL in its error messages.
    """
    for secret in (args.serpapi_key, args.openalex_key, args.proxy):
        if secret:
            text = text.replace(secret, "***")
    return text


def source_label(args: argparse.Namespace) -> str:
    if args.source == "openalex":
        return "OpenAlex only"
    scholar_name = "Google Scholar via SerpApi" if args.serpapi_key else "Google Scholar (direct)"
    if args.source == "scholar":
        return f"{scholar_name} only"
    if args.serpapi_key or args.direct_scholar:
        return f"{scholar_name}, falling back to OpenAlex"
    return "OpenAlex (add --serpapi-key for Google Scholar results)"


def pause_before_scholar(args: argparse.Namespace, bar: tqdm) -> None:
    end = time.monotonic() + args.delay
    while (left := end - time.monotonic()) > 0:
        bar.set_postfix_str(f"waiting {left:.0f} s")
        time.sleep(min(1.0, left))


def _page_reporter(bar: tqdm, query: str):
    def show_page(done: int) -> None:
        bar.set_postfix_str(f"{shorten(query, 40)} | page {done + 1}")

    return show_page


def scholar_failure_lines(pubs: list[dict], error: str, name: str, args: argparse.Namespace) -> list[str]:
    """Build the block for a failed query when no fallback source is allowed."""
    if not pubs:
        return [f"{ERROR_PREFIX} ({name}): {error} - {NOT_FOUND}"]
    return resolve_dois(pubs, args) + [
        f"{ERROR_PREFIX} ({name}) after {len(pubs)} results: {error} - remaining pages not collected"]


def collect_with_openalex(query: str, scholar_pubs: list[dict], reason: str | None,
                          args: argparse.Namespace) -> list[str]:
    """Build a block through OpenAlex. Any partial Scholar results come first, and
    OpenAlex tops them up to the limit without repeating a DOI."""
    lines = resolve_dois(scholar_pubs, args) if scholar_pubs else []
    from_scholar = len(lines)
    oa_pubs, oa_error = openalex.search_openalex(query, args)
    if oa_error:
        failed_before = f"{reason}; " if reason else ""
        return lines + [f"{ERROR_PREFIX}: {failed_before}OpenAlex - {redact(oa_error, args)} - {NOT_FOUND}"]

    limit = args.pages * RESULTS_PER_PAGE
    seen = {line.lower() for line in lines}
    for line in resolve_dois(oa_pubs, args, source="OpenAlex"):
        if len(lines) >= limit:
            break
        if line.lower() not in seen:
            seen.add(line.lower())
            lines.append(line)
    source = (f"Google Scholar ({from_scholar}) + OpenAlex ({len(lines) - from_scholar})"
              if from_scholar else "OpenAlex")
    return [f"{SOURCE_PREFIX} {source}" + (f" - {reason}" if reason else "")] + lines


def _check_serpapi(args: argparse.Namespace, todo: list[str]) -> tuple[int | None, str | None]:
    """Validate the key and report the quota. Returns (exit code to stop with, reason to skip SerpApi)."""
    try:
        account = serpapi.serpapi_account(args.serpapi_key, args.http_timeout)
    except Exception as exc:
        print(f"SerpApi rejected the key: {redact(str(exc), args)}", file=sys.stderr)
        return 1, None
    month_left = account.get("total_searches_left")
    rate = account.get("account_rate_limit_per_hour")
    hour_left = rate - (account.get("this_hour_searches") or 0) if rate else None
    per_query = math.ceil(args.pages * RESULTS_PER_PAGE / serpapi.SERPAPI_PAGE_SIZE)
    print(f"SerpApi: {month_left} searches left this month, {hour_left} this hour; "
          f"one query uses up to {per_query}.")
    known = [x for x in (month_left, hour_left) if x is not None]
    if known and min(known) <= 0:
        if args.source == "scholar":
            print("SerpApi quota is used up. Wait for it to renew.", file=sys.stderr)
            return 1, None
        print("SerpApi quota is used up. All queries go to OpenAlex.")
        return None, "SerpApi off (limit reached)"
    if known and min(known) < per_query * len(todo):
        print(f"The quota covers about {min(known) // per_query} of {len(todo)} queries. The rest go to "
              "OpenAlex; collect them again later with --redo-openalex.")
    return None, None


def _check_direct_scholar(args: argparse.Namespace) -> int | None:
    """Check scholarly and the proxy before collecting. Returns an exit code to stop with."""
    print(scholar.WARNING, file=sys.stderr)
    try:
        scholar.load_scholarly(args.proxy)
    except ImportError as exc:
        if args.source == "scholar":
            print(f"scholarly cannot be imported: {exc}\nInstall it with: {scholar.INSTALL_HINT}", file=sys.stderr)
            return 1
        print(f"scholarly cannot be imported ({exc}). All queries go to OpenAlex.\n"
              f"To use it, run: {scholar.INSTALL_HINT}", file=sys.stderr)
        args.direct_scholar = False
    except Exception as exc:
        print(f"Could not set up scholarly: {type(exc).__name__}: {redact(str(exc), args)}", file=sys.stderr)
        return 1
    return None


def run(args: argparse.Namespace) -> int:
    if not args.input.exists():
        print(f"Query file not found: {args.input}", file=sys.stderr)
        return 1
    queries = read_queries(args.input)
    if not queries:
        print(f"No queries in {args.input} (separate them with ';')", file=sys.stderr)
        return 1
    if args.source == "scholar" and not (args.serpapi_key or args.direct_scholar):
        print("--source scholar needs --serpapi-key (recommended) or --direct-scholar.", file=sys.stderr)
        return 2

    continuing = args.resume or args.redo_openalex
    if args.output.exists() and not args.overwrite:
        if not continuing:
            print(f"{args.output} already exists. Use --resume to continue it or --overwrite to replace it.",
                  file=sys.stderr)
            return 1
        if not is_results_file(args.output):
            print(f"{args.output} has no Alcedo results, so continuing would replace it. "
                  "Choose another file with -o, or use --overwrite.", file=sys.stderr)
            return 1

    failed_lookups.clear()
    results = load_results(args.output, args.redo_openalex) if continuing and not args.overwrite else {}
    todo = [q for q in queries if q not in results]

    scholar_name = "SerpApi" if args.serpapi_key else "Google Scholar"
    scholar_off_reason = None  # why Scholar is not being asked; noted in the block
    if args.source != "openalex":
        if args.serpapi_key:
            stop, scholar_off_reason = _check_serpapi(args, todo)
            if stop is not None:
                return stop
        elif args.direct_scholar:
            stop = _check_direct_scholar(args)
            if stop is not None:
                return stop

    print(f"Queries: {len(queries)}, to collect: {len(todo)}. Source: {source_label(args)}. "
          f"Results: {args.output}")
    use_scholar = (args.source != "openalex" and scholar_off_reason is None
                   and bool(args.serpapi_key or args.direct_scholar))
    scholar_asked = False
    failures_in_row = 0
    bar = tqdm(total=len(queries), initial=len(queries) - len(todo), desc="Queries", unit="query")
    try:
        for query in todo:
            lines, pubs, error, limit_hit = None, [], None, False
            if use_scholar:
                if scholar_asked and not args.serpapi_key:  # requests go to SerpApi, not to Scholar
                    pause_before_scholar(args, bar)
                scholar_asked = True
                bar.set_postfix_str(shorten(query))
                show_page = _page_reporter(bar, query)
                if args.serpapi_key:
                    pubs, error, limit_hit = serpapi.search_serpapi(query, args, on_page=show_page)
                else:
                    pubs, error = scholar.search_scholar(query, args, on_page=show_page)
                if error:
                    failures_in_row += 1
                    error = redact(" ".join(error.split()), args)
                    tqdm.write(f"[!] {scholar_name}, '{shorten(query)}': {error}")
                else:
                    failures_in_row = 0
                    lines = resolve_dois(pubs, args)

            if lines is None:  # no complete Scholar results: an error, or Scholar is not in use
                if args.source == "scholar":
                    lines = scholar_failure_lines(pubs, error, scholar_name, args)
                else:
                    bar.set_postfix_str(f"{shorten(query, 40)} | OpenAlex")
                    reason = f"{scholar_name} unavailable: {error}" if error else scholar_off_reason
                    lines = collect_with_openalex(query, pubs, reason, args)

            # --resume collects a block with an error line again from scratch.
            results[query] = lines
            save_results(args.output, queries, results)
            bar.update()

            if use_scholar and (limit_hit or failures_in_row >= args.max_failures):
                why = "limit reached" if limit_hit else f"failures in a row: {failures_in_row}"
                if args.source == "scholar":
                    advice = ("Continue after the SerpApi quota renews" if args.serpapi_key else
                              "Scholar is refusing requests; use --serpapi-key or try later")
                    tqdm.write(f"[!] {scholar_name}: {why}. {advice}, then run with --resume.")
                    break
                use_scholar = False
                scholar_off_reason = f"{scholar_name} off ({why})"
                tqdm.write(f"[!] {scholar_name}: {why}. The remaining queries go straight to OpenAlex.")
    except KeyboardInterrupt:
        tqdm.write("Interrupted. Collected results are saved; continue with --resume.")
        return 130
    finally:
        bar.close()

    lines = [line for q in queries if q in results for line in results[q]]
    found = sum(line.startswith("https://doi.org/") for line in lines)
    missing = sum(line.startswith(NOT_FOUND) for line in lines)
    via_openalex = sum(line.startswith(SOURCE_PREFIX) and "OpenAlex" in line for line in lines)
    errors = sum(line.startswith(ERROR_PREFIX) for line in lines)
    print(f"Done. DOIs: {found}, without a DOI: {missing}, queries via OpenAlex: {via_openalex}, "
          f"queries with errors: {errors}. File: {args.output}")
    if failed_lookups:
        details = ", ".join(f"{service}: {count}" for service, count in failed_lookups.most_common())
        print(f"Failed DOI lookups ({details}). Some records marked '{NOT_FOUND}' may have a DOI; "
              "run again later to retry them.")
    return 0
