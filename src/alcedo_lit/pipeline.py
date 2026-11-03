"""Run a list of queries: search API, otherwise the free sources together, saving after every query."""

from __future__ import annotations

import argparse
import math
import sys
import time
from collections.abc import Callable
from dataclasses import dataclass

from tqdm import tqdm

from .cache import Cache
from .check import queries_with_problems
from .doi import normalize_title
from .resolve import failed_lookups, resolve_dois
from .results import (
    DIRECT_LABEL,
    ERROR_PREFIX,
    NOT_FOUND,
    NOT_REGISTERED,
    SOURCE_PREFIX,
    combine_results,
    combined_path,
    counted,
    is_results_file,
    load_results,
    read_queries,
    save_results,
)
from .sources import RESULTS_PER_PAGE, openalex, scholar, searchapi, semantic_scholar, serpapi, serper
from .verify import verify_results

FEW_RESULTS = 10
SEMANTIC_SCHOLAR_LABEL = "Semantic Scholar"
NO_SCHOLAR_NOTICE = ("No search API key, and direct Google Scholar search is off, so results come from the free "
                     "catalogues. They are stable, but in our small tests their results were less complete than "
                     "Google Scholar's through an API. Direct search can add to them for free, but it needs a network "
                     "Scholar does not refuse and can return incomplete lists. To see the options, run: alcedo setup")


@dataclass
class Backend:
    """One way of getting Google Scholar results."""

    name: str
    search: Callable  # (query, args, on_page) -> (results, error, whether to stop using it)
    failures: int = 0
    off_reason: str | None = None
    asked: bool = False


def _search_scholar_directly(query, args, on_page):
    pubs, error = scholar.search_scholar(query, args, on_page=on_page)
    return pubs, error, False


def shorten(text: str, width: int = 50) -> str:
    return text if len(text) <= width else text[:width - 3] + "..."


def redact(text: str, args: argparse.Namespace) -> str:
    """Remove API keys and proxy credentials from error text, which reaches the console and the file.

    The SerpApi key travels in the URL, and requests includes the URL in its error messages.
    """
    for secret in (args.searchapi_key, args.serper_key, args.serpapi_key, args.openalex_key,
                   args.semantic_scholar_key, args.proxy):
        if secret:
            text = text.replace(secret, "***")
    return text


def source_label(args: argparse.Namespace, apis: list[Backend], semantic: Backend | None,
                 direct: Backend | None) -> str:
    if args.source == "openalex":
        return "OpenAlex only"
    names = [f"Google Scholar via {b.name}" for b in apis]
    if args.source == "scholar":
        return " then ".join(names + ([DIRECT_LABEL] if direct else [])) + " only"
    free = [*([SEMANTIC_SCHOLAR_LABEL] if semantic else []), "OpenAlex", *([DIRECT_LABEL] if direct else [])]
    return " then ".join([*names, " + ".join(free)])


def pause_before_scholar(args: argparse.Namespace, bar: tqdm) -> None:
    end = time.monotonic() + args.delay
    while (left := end - time.monotonic()) > 0:
        bar.set_postfix_str(f"waiting {left:.0f} s")
        time.sleep(min(1.0, left))


def _page_reporter(bar: tqdm, query: str):
    def show_page(done: int) -> None:
        bar.set_postfix_str(f"{shorten(query, 40)} | page {done + 1}")

    return show_page


def _note_few_results(query: str, source: str, count: int) -> None:
    if count < FEW_RESULTS:
        tqdm.write(f"[i] {source} found only {counted(count, 'result')} for '{shorten(query)}'. "
                   "The query may be narrow, or the list may be incomplete.")


def scholar_failure_lines(pubs: list[dict], error: str, args: argparse.Namespace) -> list[str]:
    """Build the block for a failed query when no fallback source is allowed."""
    if not pubs:
        return [f"{ERROR_PREFIX}: {error} - {NOT_FOUND}"]
    return resolve_dois(pubs, args) + [
        f"{ERROR_PREFIX} after {len(pubs)} results: {error} - remaining pages not collected"]


def _add_new(lines: list[str], new: list[str], limit: int | None = None) -> int:
    """Add lines that are not in the block yet, up to `limit` lines in the block. Returns how many were added."""
    seen = {line.lower() for line in lines}
    added = 0
    for line in new:
        if limit is not None and len(lines) >= limit:
            break
        if line.lower() not in seen:
            seen.add(line.lower())
            lines.append(line)
            added += 1
    return added


def _title_keys(pubs: list[dict]) -> set[str]:
    return {key for pub in pubs if (key := normalize_title(pub.get("title") or ""))}


def _not_in(pubs: list[dict], known: set[str]) -> list[dict]:
    return [pub for pub in pubs if normalize_title(pub.get("title") or "") not in known]


def _ask(backend: Backend, query: str, args: argparse.Namespace, bar: tqdm) -> tuple[list[dict], str | None]:
    """Ask one source. Returns (results, why it failed), and turns the source off when it should not be asked again."""
    bar.set_postfix_str(shorten(query))
    pubs, error, stop_using = backend.search(query, args, _page_reporter(bar, query))
    if not error:
        backend.failures = 0
        return pubs, None

    backend.failures += 1
    error = redact(" ".join(error.split()), args)
    tqdm.write(f"[!] {backend.name}, '{shorten(query)}': {error}")
    if stop_using or backend.failures >= args.max_failures:
        why = error if stop_using else f"failures in a row: {backend.failures}"
        backend.off_reason = f"{backend.name} off ({why})"
        tqdm.write(f"[!] {backend.off_reason}. Moving on without it.")
    return pubs, f"{backend.name} unavailable: {error}"


def _ask_direct(direct: Backend, query: str, args: argparse.Namespace, bar: tqdm) -> tuple[list[dict], str | None]:
    if direct.off_reason:
        return [], direct.off_reason
    if direct.asked:
        pause_before_scholar(args, bar)
    direct.asked = True
    return _ask(direct, query, args, bar)


def _ask_semantic(semantic: Backend, query: str, args: argparse.Namespace, bar: tqdm) -> tuple[list[dict], str | None]:
    return ([], semantic.off_reason) if semantic.off_reason else _ask(semantic, query, args, bar)


def _ask_apis(query: str, apis: list[Backend], args: argparse.Namespace,
              bar: tqdm) -> tuple[list[dict], Backend | None, str | None]:
    """Try each search API. Returns (results, the API that answered, why none did).

    Results from an API that failed partway are kept, because they already cost quota.
    """
    limit = args.pages * RESULTS_PER_PAGE
    partial: list[dict] = []
    reason = None
    for backend in apis:
        if backend.off_reason:
            reason = backend.off_reason
            continue
        pubs, error = _ask(backend, query, args, bar)
        partial = (partial + _not_in(pubs, _title_keys(partial)))[:limit]
        if not error:
            return partial, backend, None
        reason = error
    return partial, None, reason


def collect_free(query: str, api_pubs: list[dict], reason: str | None, semantic: Backend | None,
                 direct: Backend | None, args: argparse.Namespace, bar: tqdm) -> list[str]:
    """Build a block when no API answered: Semantic Scholar, OpenAlex, then whatever direct search adds.

    Semantic Scholar matches strictly, so it goes first, and direct search goes last because its lists can be
    incomplete. Each source gives up to the limit, so none pushes out another's records. Only results from an API
    that failed partway keep the block to the limit, because the free sources just complete them. A source that
    fails is left out, records already in the block are not looked up again, and only when no source answers is
    the block an error.
    """
    limit = args.pages * RESULTS_PER_PAGE
    lines = resolve_dois(api_pubs, args) if api_pubs else []
    counts = [f"Google Scholar ({len(lines)})"] if lines else []
    notes = [reason] if reason else []
    known = _title_keys(api_pubs)
    answered = False

    if semantic:
        pubs, error = _ask_semantic(semantic, query, args, bar)
        if error:
            notes.append(error)
        else:
            answered = True
            new = _not_in(pubs, known)
            known |= _title_keys(pubs)
            added = _add_new(lines, resolve_dois(new, args, source=SEMANTIC_SCHOLAR_LABEL) if new else [],
                             limit if api_pubs else len(lines) + limit)
            counts.append(f"{SEMANTIC_SCHOLAR_LABEL} ({added})")

    bar.set_postfix_str(f"{shorten(query, 40)} | OpenAlex")
    oa_pubs, oa_error = openalex.search_openalex(query, args)
    if oa_error:
        oa_error = redact(oa_error, args)
        tqdm.write(f"[!] OpenAlex, '{shorten(query)}': {oa_error}")
        notes.append(f"OpenAlex unavailable: {oa_error}")
    else:
        answered = True
        _note_few_results(query, "OpenAlex", len(oa_pubs))
        known |= _title_keys(oa_pubs)
        added = _add_new(lines, resolve_dois(oa_pubs, args, source="OpenAlex") if oa_pubs else [],
                         limit if api_pubs else len(lines) + limit)
        counts.append(f"OpenAlex ({added})" if counts or semantic or direct else "OpenAlex")

    if direct:
        pubs, error = _ask_direct(direct, query, args, bar)
        if error:
            notes.append(error)
        if pubs:
            answered = True
            if len(pubs) < limit:
                tqdm.write(f"[!] {DIRECT_LABEL} returned only {len(pubs)} of up to {limit}; "
                           f"the list may be incomplete: '{shorten(query)}'")
            new = _not_in(pubs, known)
            added = _add_new(lines, resolve_dois(new, args) if new else [])
            counts.append(f"{DIRECT_LABEL} ({added} new of {len(pubs)})")
            notes.append("the direct list may be incomplete")
        elif not error:
            notes.append(f"{DIRECT_LABEL} found nothing")

    if not answered:
        return lines + [f"{ERROR_PREFIX}: {'; '.join(notes)} - {NOT_FOUND}"]
    if not lines:
        lines = [f"{NOT_FOUND} (no source returned anything)"]
    source = f"{SOURCE_PREFIX} {' + '.join(counts)}"
    return [source + (f" - {'; '.join(notes)}" if notes else ""), *lines]


def collect_scholar_only(query: str, api_pubs: list[dict], reason: str | None, direct: Backend | None,
                         args: argparse.Namespace, bar: tqdm) -> list[str]:
    """Build a block for --source scholar, when no API answered: direct search if it is on, and nothing else."""
    if direct is None:
        return scholar_failure_lines(api_pubs, reason or "no source available", args)
    pubs, error = _ask_direct(direct, query, args, bar)
    pubs = api_pubs + _not_in(pubs, _title_keys(api_pubs))
    if error:
        return scholar_failure_lines(pubs, error, args)
    limit = args.pages * RESULTS_PER_PAGE
    note = f"{DIRECT_LABEL} returned {len(pubs)} of up to {limit}; the list may be incomplete"
    return [f"{SOURCE_PREFIX} {note}", *resolve_dois(pubs, args)]


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
        print("SerpApi quota is used up.")
        return None, "SerpApi off (limit reached)"
    if known and min(known) < per_query * len(todo):
        print(f"The quota covers about {min(known) // per_query} of {len(todo)} queries. The rest use the next "
              "source; collect them again later with --redo-free.")
    return None, None


def _check_direct_scholar(args: argparse.Namespace, have_api: bool) -> int | None:
    """Warn and check scholarly and the proxy. Returns an exit code to stop with."""
    print(scholar.REMINDER if args.direct_warning_shown else scholar.WARNING, file=sys.stderr)
    try:
        scholar.load_scholarly(args.proxy)
    except ImportError as exc:
        if args.source == "scholar" and not have_api:
            print(f"scholarly cannot be imported: {exc}\nInstall it with: {scholar.INSTALL_HINT}", file=sys.stderr)
            return 1
        print(f"scholarly cannot be imported ({exc}), so direct search is skipped.\n"
              f"To use it, run: {scholar.INSTALL_HINT}", file=sys.stderr)
        args.direct_scholar = False
    except Exception as exc:
        print(f"Could not set up scholarly: {type(exc).__name__}: {redact(str(exc), args)}", file=sys.stderr)
        return 1
    return None


def build_backends(args: argparse.Namespace,
                   todo: list[str]) -> tuple[list[Backend], Backend | None, int | None, str | None]:
    """Line up the Scholar sources. Returns (APIs in order, direct search, exit code to stop with, why an API is off).
    """
    apis: list[Backend] = []
    skipped = None
    if args.source == "openalex":
        return apis, None, None, None
    if args.searchapi_key:
        print("SearchApi: a query with 50 results uses 3 requests from your quota.")
        apis.append(Backend("SearchApi", lambda q, a, on_page: searchapi.search_searchapi(q, a, on_page=on_page)))
    if args.serper_key:
        print("Serper: a query with 50 results uses 5 queries from your quota.")
        apis.append(Backend("Serper", lambda q, a, on_page: serper.search_serper(q, a, on_page=on_page)))
    if args.serpapi_key:
        stop, skipped = _check_serpapi(args, todo)
        if stop is not None:
            return apis, None, stop, None
        if skipped is None:
            apis.append(Backend("SerpApi", lambda q, a, on_page: serpapi.search_serpapi(q, a, on_page=on_page)))
    direct = None
    if args.direct_scholar:
        stop = _check_direct_scholar(args, have_api=bool(apis))
        if stop is not None:
            return apis, None, stop, None
        if args.direct_scholar:
            direct = Backend("Google Scholar", _search_scholar_directly)
    return apis, direct, None, skipped


def run(args: argparse.Namespace) -> int:
    if not args.input.exists():
        print(f"Query file not found: {args.input}", file=sys.stderr)
        return 1
    try:
        queries = read_queries(args.input)
        doubtful = queries_with_problems(args.input)
    except UnicodeDecodeError:
        print(f"{args.input} is not saved as UTF-8. Save it as UTF-8 and try again.", file=sys.stderr)
        return 1
    if not queries:
        print(f"No queries in {args.input} (separate them with ';')", file=sys.stderr)
        return 1
    if doubtful:
        print(f"{doubtful} of {counted(len(queries), 'query', 'queries')} may have mistakes. To see them, run: "
              f"alcedo check -i {args.input}",
              file=sys.stderr)
    if args.source == "scholar" and not (args.searchapi_key or args.serper_key or args.serpapi_key
                                         or args.direct_scholar):
        print("--source scholar needs a search API key (run: alcedo setup) or --direct-scholar.", file=sys.stderr)
        return 2

    continuing = args.resume or args.redo_free
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
    args.cache = Cache() if args.use_cache else None
    results = load_results(args.output, args.redo_free) if continuing and not args.overwrite else {}
    todo = [q for q in queries if q not in results]

    apis, direct, stop, skipped = build_backends(args, todo)
    if stop is not None:
        return stop
    if not apis and not direct and args.source == "auto" and not skipped:
        print(NO_SCHOLAR_NOTICE, file=sys.stderr)
    semantic = None
    if args.source == "auto" and args.semantic_scholar:
        semantic = Backend(SEMANTIC_SCHOLAR_LABEL, semantic_scholar.search_semantic_scholar)

    print(f"Queries: {len(queries)}, to collect: {len(todo)}. Source: {source_label(args, apis, semantic, direct)}. "
          f"Results: {args.output}")
    bar = tqdm(total=len(queries), initial=len(queries) - len(todo), desc="Queries", unit="query")
    try:
        for query in todo:
            pubs, answered, reason = _ask_apis(query, apis, args, bar)
            if answered:
                _note_few_results(query, answered.name, len(pubs))
                lines = resolve_dois(pubs, args)
            elif args.source == "scholar":
                lines = collect_scholar_only(query, pubs, reason, direct, args, bar)
            else:
                lines = collect_free(query, pubs, reason or skipped, semantic, direct, args, bar)

            # --resume collects a block with an error line again from scratch.
            results[query] = lines
            save_results(args.output, queries, results)
            bar.update()

            if args.source == "scholar" and all(b.off_reason for b in [*apis, *([direct] if direct else [])]):
                tqdm.write("[!] No Google Scholar source is left. Use a search API key or try later, "
                           "then run with --resume.")
                break

        unchecked = 0
        if args.verify_dois:
            bar.set_postfix_str("checking DOIs")
            _, unchecked = verify_results(results, args.http_timeout)
    except KeyboardInterrupt:
        tqdm.write("Interrupted. Collected results are saved; continue with --resume.")
        return 130
    finally:
        bar.close()

    save_results(args.output, queries, results)

    lines = [line for q in queries if q in results for line in results[q]]
    found = sum(line.startswith("https://doi.org/") for line in lines)
    unique = len(combine_results({q: results[q] for q in queries if q in results}))
    missing = sum(line.startswith(NOT_FOUND) for line in lines)
    not_registered = sum(line.startswith(NOT_REGISTERED) for line in lines)
    sources = [line.split(" - ")[0] for line in lines if line.startswith(SOURCE_PREFIX)]
    via_free = sum("OpenAlex" in source or SEMANTIC_SCHOLAR_LABEL in source for source in sources)
    via_direct = sum(DIRECT_LABEL in source for source in sources)
    errors = sum(line.startswith(ERROR_PREFIX) for line in lines)
    print(f"Done. DOIs: {found}, unique: {unique}, without a DOI: {missing}, queries via free catalogues: {via_free}, "
          f"queries with errors: {errors}. File: {args.output}")
    print(f"List without repeats: {combined_path(args.output)}")
    if direct and direct.failures:
        print(scholar.REFUSED)
    if via_direct:
        print(f"{counted(via_direct, 'query', 'queries')} used direct Google Scholar search, so the lists may be "
              "incomplete. "
              "With a search API key, collect them again using --redo-free.")
    if not_registered:
        print(f"Marked '{NOT_REGISTERED}': {counted(not_registered, 'result line')}. doi.org does not know them.")
    if unchecked:
        print(f"Could not check {counted(unchecked, 'DOI')} in doi.org. They stay in the results; "
              "run again to check them.")
    if failed_lookups:
        details = ", ".join(f"{service}: {count}" for service, count in failed_lookups.most_common())
        print(f"Failed DOI lookups ({details}). Some records marked '{NOT_FOUND}' may have a DOI; "
              "run again later to retry them.")
    return 0
