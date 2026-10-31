"""Command line interface of Alcedo."""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

from . import __version__
from .pipeline import run


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        prog="alcedo",
        description="Collect DOIs from a list of literature search queries, grouped by query.",
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
                   help="auto: Google Scholar if a SerpApi key or --direct-scholar is given, falling back to "
                        "OpenAlex; otherwise OpenAlex. scholar: Scholar only. openalex: OpenAlex only (default: auto)")
    p.add_argument("--serpapi-key", default=os.environ.get("SERPAPI_KEY"),
                   help="SerpApi key for Google Scholar results (default: SERPAPI_KEY variable)")
    p.add_argument("--openalex-key", default=os.environ.get("OPENALEX_API_KEY"),
                   help="free OpenAlex API key; without one the daily budget is much smaller and shared per IP "
                        "(default: OPENALEX_API_KEY variable)")
    p.add_argument("--mailto", help="your e-mail, sent to Crossref, OpenAlex and Europe PMC to identify your requests")
    p.add_argument("--no-page-meta", dest="page_meta", action="store_false",
                   help="do not open publisher pages when looking for a DOI")
    p.add_argument("--no-title-search", dest="title_search", action="store_false",
                   help="do not look for a DOI by title in Crossref and OpenAlex")
    p.add_argument("--resume", action="store_true",
                   help="skip queries already collected in the results file")
    p.add_argument("--redo-openalex", action="store_true",
                   help="like --resume, but also collect OpenAlex blocks again, for example after "
                        "the SerpApi quota renews")
    p.add_argument("--overwrite", action="store_true",
                   help="replace an existing results file and collect everything again")
    p.add_argument("--max-failures", type=int, default=2,
                   help="stop asking Google Scholar after this many failures in a row (default: 2)")
    p.add_argument("--page-timeout", type=float, default=120,
                   help="hard timeout for one page of Google Scholar results, in seconds (default: 120)")
    p.add_argument("--http-timeout", type=float, default=15,
                   help="timeout for publisher and API requests, in seconds (default: 15)")

    direct = p.add_argument_group("experimental direct Google Scholar access",
                                  'needs: pip install "alcedo-lit[scholar]"; at your own risk')
    direct.add_argument("--direct-scholar", action="store_true",
                        help="query Google Scholar directly through scholarly when there is no SerpApi key")
    direct.add_argument("--delay", type=float, default=25,
                        help="pause between direct Scholar queries, in seconds (default: 25)")
    direct.add_argument("--proxy", help="HTTP(S) proxy of your network for direct Scholar access")

    args = p.parse_args(argv)
    if args.pages < 1:
        p.error("--pages must be at least 1")
    return args


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):  # a legacy console encoding must not crash the output
        try:
            stream.reconfigure(errors="replace")
        except Exception:
            pass
    return run(parse_args(argv))
