"""Command line interface of Alcedo."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__, setup_wizard
from .check import run_check
from .config import load_config
from .export import run_export
from .filters import run_filter
from .pipeline import run


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    config = load_config()
    p = argparse.ArgumentParser(
        prog="alcedo",
        description="Collect DOIs from a list of literature search queries, grouped by query. "
                    "To set up API keys and see the search options, run: alcedo setup. "
                    "To find mistakes in your queries first, run: alcedo check. "
                    "To narrow the results by year, language or quartile, run: alcedo filter. "
                    "To save them for Zotero or ASReview, run: alcedo export",
    )
    p.add_argument("--version", action="version", version=f"alcedo {__version__}")
    p.add_argument("-i", "--input", type=Path, default=Path("queries.txt"),
                   help="file with queries separated by ';' (default: queries.txt)")
    p.add_argument("-o", "--output", type=Path, default=Path("alcedo_results.txt"),
                   help="results file (default: alcedo_results.txt)")
    p.add_argument("--pages", type=int, default=5,
                   help="how many result pages of 10 to take per query; "
                        "takes them all if there are fewer (default: 5)")
    p.add_argument("--source", choices=("auto", "scholar", "openalex"), default="auto",
                   help="auto: a search API, otherwise Semantic Scholar, OpenAlex and direct Scholar if you turned "
                        "it on. scholar: Google Scholar only. openalex: OpenAlex only (default: auto)")
    p.add_argument("--searchapi-key", default=os.environ.get("SEARCHAPI_KEY") or config.get("searchapi_key"),
                   help="SearchApi key for Google Scholar results (default: SEARCHAPI_KEY variable or alcedo setup)")
    p.add_argument("--serper-key", default=os.environ.get("SERPER_API_KEY") or config.get("serper_key"),
                   help="Serper key for Google Scholar results (default: SERPER_API_KEY variable or alcedo setup)")
    p.add_argument("--serpapi-key", default=os.environ.get("SERPAPI_KEY") or config.get("serpapi_key"),
                   help="SerpApi key for Google Scholar results (default: SERPAPI_KEY variable or alcedo setup)")
    p.add_argument("--openalex-key", default=os.environ.get("OPENALEX_API_KEY") or config.get("openalex_key"),
                   help="free OpenAlex API key; without one the daily budget is much smaller and shared per IP "
                        "(default: OPENALEX_API_KEY variable or alcedo setup)")
    p.add_argument("--semantic-scholar-key",
                   default=os.environ.get("SEMANTIC_SCHOLAR_API_KEY") or config.get("semantic_scholar_key"),
                   help="free Semantic Scholar API key; without one all users share a limit "
                        "(default: SEMANTIC_SCHOLAR_API_KEY variable or alcedo setup)")
    p.add_argument("--semantic-scholar", action=argparse.BooleanOptionalAction, default=True,
                   help="use Semantic Scholar among the free sources (default: yes)")
    p.add_argument("--mailto", help="your e-mail, sent to Crossref, OpenAlex, Semantic Scholar and Europe PMC "
                                    "to identify your requests")
    p.add_argument("--no-page-meta", dest="page_meta", action="store_false",
                   help="do not open publisher pages when looking for a DOI")
    p.add_argument("--no-title-search", dest="title_search", action="store_false",
                   help="do not look for a DOI by title in Crossref and OpenAlex")
    p.add_argument("--resume", action="store_true",
                   help="skip queries already collected in the results file")
    p.add_argument("--redo-free", action="store_true",
                   help="like --resume, but also collect blocks from the free sources again, "
                        "for example after adding an API key")
    p.add_argument("--overwrite", action="store_true",
                   help="replace an existing results file and collect everything again")
    p.add_argument("--verify-dois", action="store_true",
                   help="check every DOI in the doi.org registry and mark the ones that do not exist")
    p.add_argument("--no-cache", dest="use_cache", action="store_false",
                   help="do not reuse or save DOI lookups from earlier runs")
    p.add_argument("--max-failures", type=int, default=2,
                   help="stop using a Google Scholar source after this many failures in a row (default: 2)")
    p.add_argument("--page-timeout", type=float, default=120,
                   help="hard timeout for one page of Google Scholar results, in seconds (default: 120)")
    p.add_argument("--http-timeout", type=float, default=15,
                   help="timeout for publisher and API requests, in seconds (default: 15)")

    direct = p.add_argument_group("direct Google Scholar search",
                                  'free but unreliable; needs: pip install "alcedo-lit[scholar]"')
    direct.add_argument("--direct-scholar", action=argparse.BooleanOptionalAction, default=config.get("direct_scholar"),
                        help="add direct search to the free sources when no API answers "
                             "(default: your choice in alcedo setup)")
    direct.add_argument("--delay", type=float, default=25,
                        help="pause between direct Scholar queries, in seconds (default: 25)")
    direct.add_argument("--proxy", help="HTTP(S) proxy of your network for direct Scholar access")

    p.set_defaults(direct_warning_shown=bool(config.get("direct_scholar")))  # whoever agreed has read it
    args = p.parse_args(argv)
    if args.pages < 1:
        p.error("--pages must be at least 1")
    return args


def decide_direct_search(args: argparse.Namespace) -> None:
    """Ask once whether to use direct search, the first time it would matter. Never ask without a terminal."""
    if args.direct_scholar is not None:
        return
    args.direct_scholar = False
    has_api = args.searchapi_key or args.serper_key or args.serpapi_key
    if args.source != "openalex" and not has_api and setup_wizard.is_terminal():
        args.direct_scholar = setup_wizard.ask_direct_choice(load_config())
        args.direct_warning_shown = True


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # a legacy console encoding must not crash the output
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    argv = sys.argv[1:] if argv is None else argv
    if argv[:1] == ["setup"]:
        return setup_wizard.run_setup()
    if argv[:1] == ["check"]:
        return run_check(argv[1:])
    if argv[:1] == ["filter"]:
        return run_filter(argv[1:])
    if argv[:1] == ["export"]:
        return run_export(argv[1:])
    args = parse_args(argv)
    decide_direct_search(args)
    return run(args)
