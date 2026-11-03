"""`alcedo filter`: narrow collected results by year, language, quartile and words, explaining every decision.

It works on an existing results file, so changing a condition uses no search quota. A record is excluded only when the
data shows it fails a condition. A record whose data is missing goes to a separate list, because nobody can tell.
"""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
from collections import Counter
from dataclasses import dataclass, field
from pathlib import Path

from .cache import Cache
from .config import load_config
from .doi import doi_url, normalize_title
from .metadata import fetch_metadata
from .results import ERROR_PREFIX, NOT_FOUND, NOT_REGISTERED, counted, doi_of_line, is_results_file, read_blocks

SJR_ISSN_COLUMN = "issn"
SJR_QUARTILE_COLUMN = "sjr best quartile"
SJR_DOWNLOAD_PAGE = "https://www.scimagojr.com/journalrank.php"
QUARTILES = ("Q1", "Q2", "Q3", "Q4")
COLUMNS = ["doi", "url", "title", "year", "journal", "issn", "language", "type", "quartile", "retracted", "authors",
           "found_by_queries", "queries", "reason"]


@dataclass
class Entry:
    """One record, however many queries found it."""

    doi: str | None
    title: str | None
    queries: list[str] = field(default_factory=list)
    registered: bool = True
    record: dict | None = None
    checked: bool = True
    quartile: str | None = None
    reasons: list[str] = field(default_factory=list)


def read_entries(path: Path) -> tuple[list[Entry], int]:
    """Return each record once, and the number of queries that failed and so have no complete block."""
    entries: dict[str, Entry] = {}
    failed = 0
    for query, lines in read_blocks(path).items():
        failed += any(line.startswith(ERROR_PREFIX) for line in lines)
        for line in lines:
            if doi := doi_of_line(line):
                key, entry = doi.lower(), Entry(doi, None)
            elif line.startswith(f"{NOT_REGISTERED}: "):
                doi = line.split(": ", 1)[1]
                key, entry = doi.lower(), Entry(doi, None, registered=False)
            elif line.startswith(f"{NOT_FOUND}: "):
                title = line.split(": ", 1)[1]
                key, entry = "title:" + normalize_title(title), Entry(None, title)
            else:
                continue
            found = entries.setdefault(key, entry)
            if query not in found.queries:
                found.queries.append(query)
    return list(entries.values()), failed


def merge_found_titles(entries: list[Entry]) -> list[Entry]:
    """Join a record without a DOI to a record with the same title that has one: another query found its DOI."""
    by_title = {normalize_title(e.title): e for e in entries if e.doi and e.title}
    merged = []
    for entry in entries:
        same = None if entry.doi else by_title.get(normalize_title(entry.title or ""))
        if same is None:
            merged.append(entry)
        else:
            same.queries.extend(q for q in entry.queries if q not in same.queries)
    return merged


def normalize_issn(issn: str) -> str:
    return re.sub(r"[^0-9Xx]", "", issn).upper()


def load_sjr(path: Path) -> dict[str, str]:
    """Read a Scimago journal rank file into {ISSN: best quartile}. Raises ValueError if it is not one."""
    with path.open(encoding="utf-8-sig", errors="replace", newline="") as file:
        header = file.readline()
        delimiter = ";" if header.count(";") >= header.count(",") else ","
        columns = [name.strip().strip('"').lower() for name in next(csv.reader([header], delimiter=delimiter), [])]
        if SJR_ISSN_COLUMN not in columns or SJR_QUARTILE_COLUMN not in columns:
            raise ValueError(f"{path} has no 'Issn' and 'SJR Best Quartile' columns. Download the file from "
                             f"{SJR_DOWNLOAD_PAGE} ('Download data').")
        issn_at, quartile_at = columns.index(SJR_ISSN_COLUMN), columns.index(SJR_QUARTILE_COLUMN)
        quartiles: dict[str, str] = {}
        for row in csv.reader(file, delimiter=delimiter):
            if len(row) <= max(issn_at, quartile_at):
                continue
            quartile = row[quartile_at].strip().upper()
            for issn in row[issn_at].split(","):
                if issn := normalize_issn(issn):
                    quartiles[issn] = quartile
    return quartiles


def _best_quartile(issns: list[str], sjr: dict[str, str]) -> str | None:
    """Return the best quartile among a journal's ISSNs, "" if it is listed with none, and None if it is not listed."""
    listed = [sjr[n] for n in map(normalize_issn, issns) if n in sjr]
    if not listed:
        return None
    return min((q for q in listed if q in QUARTILES), default="")


def judge(entry: Entry, args: argparse.Namespace, words: list[tuple[str, re.Pattern]],
          sjr: dict[str, str] | None) -> str:
    """Decide a record and fill in its reasons. A failed condition outweighs any missing data."""
    record = entry.record or {}
    excluded, unknown = [], []

    if not entry.registered:
        excluded.append("DOI not registered in doi.org")
    if record.get("retracted") and not args.keep_retracted:
        excluded.append("retracted")

    text = " ".join(filter(None, (entry.title, record.get("title"), record.get("abstract"))))
    for word, pattern in words:
        if pattern.search(text):
            excluded.append(f'contains "{word}"')

    if entry.record:
        year = record.get("year")
        if args.year_from or args.year_to:
            if not year:
                unknown.append("no year")
            elif args.year_from and year < args.year_from:
                excluded.append(f"year {year} is before {args.year_from}")
            elif args.year_to and year > args.year_to:
                excluded.append(f"year {year} is after {args.year_to}")
        if args.language:
            language = (record.get("language") or "").lower()
            if not language:
                unknown.append("no language")
            elif language not in args.language:
                excluded.append(f"language {language}")
        if sjr is not None:
            entry.quartile = _best_quartile(record.get("issn") or [], sjr)
            if not record.get("issn"):
                unknown.append("no ISSN")
            elif entry.quartile is None:
                unknown.append("journal not in the SJR file")
            elif not entry.quartile:
                unknown.append("no quartile in the SJR file")
            elif entry.quartile not in args.quartile:
                excluded.append(f"quartile {entry.quartile}")
    elif not entry.doi:
        unknown.append("no DOI")
    elif not entry.checked:
        unknown.append("could not be checked, run again later")
    elif entry.registered:
        unknown.append("no data for this DOI")

    entry.reasons = excluded or unknown
    return "excluded" if excluded else "unknown" if unknown else "kept"


def _write(path: Path, entries: list[Entry]) -> None:
    entries = sorted(entries, key=lambda e: -len(e.queries))
    # Excel with a Russian or other European locale needs the semicolon and the byte order mark.
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(COLUMNS)
        for e in entries:
            r = e.record or {}
            writer.writerow([e.doi or "", doi_url(e.doi) if e.doi else "", r.get("title") or e.title or "",
                             r.get("year") or "", r.get("journal") or "", ", ".join(r.get("issn") or []),
                             r.get("language") or "", r.get("type") or "", e.quartile or "",
                             "" if r.get("retracted") is None else r["retracted"],
                             ", ".join(filter(None, r.get("authors") or [])), len(e.queries), " | ".join(e.queries),
                             "; ".join(e.reasons)])


def _parse_args(argv: list[str]) -> argparse.Namespace:
    config = load_config()
    p = argparse.ArgumentParser(
        prog="alcedo filter",
        description="Narrow collected results by year, language, quartile and words. Uses no search quota. "
                    "Records with missing data go to a separate list instead of being dropped.")
    p.add_argument("-i", "--input", type=Path, default=Path("alcedo_results.txt"),
                   help="results file to filter (default: alcedo_results.txt)")
    p.add_argument("-o", "--output", help="start of the output file names (default: the input file name without "
                                          "_results, next to it)")
    p.add_argument("--year-from", type=int, help="keep papers from this year on")
    p.add_argument("--year-to", type=int, help="keep papers up to this year")
    p.add_argument("--language", help="keep these languages, as two-letter codes separated by commas, such as en,ru")
    p.add_argument("--quartile", help="keep these quartiles, such as Q1,Q2; needs --sjr")
    p.add_argument("--sjr", type=Path, help=f"journal rank file you downloaded from {SJR_DOWNLOAD_PAGE}")
    p.add_argument("--exclude-word", action="append", default=[], metavar="WORD",
                   help="exclude records with this word or phrase in the title or abstract; can be repeated")
    p.add_argument("--keep-retracted", action="store_true", help="do not exclude papers marked as retracted")
    p.add_argument("--openalex-key", default=os.environ.get("OPENALEX_API_KEY") or config.get("openalex_key"),
                   help="free OpenAlex API key (default: OPENALEX_API_KEY variable or alcedo setup)")
    p.add_argument("--mailto", help="your e-mail, sent to Crossref and OpenAlex to identify your requests")
    p.add_argument("--http-timeout", type=float, default=30, help="timeout for each request, in seconds (default: 30)")
    p.add_argument("--no-cache", dest="use_cache", action="store_false", help="do not reuse or save paper data")
    args = p.parse_args(argv)

    if args.year_from and args.year_to and args.year_from > args.year_to:
        p.error("--year-from is later than --year-to")
    if bool(args.quartile) != bool(args.sjr):
        p.error(f"--quartile and --sjr go together. Download the file from {SJR_DOWNLOAD_PAGE} ('Download data').")
    if args.quartile:
        args.quartile = {q.strip().upper() for q in args.quartile.split(",") if q.strip()}
        if not args.quartile <= set(QUARTILES):
            p.error("--quartile takes Q1, Q2, Q3 or Q4, separated by commas")
    if args.language:
        args.language = {code.strip().lower() for code in args.language.split(",") if code.strip()}
    return args


def run_filter(argv: list[str]) -> int:
    args = _parse_args(argv)
    if not args.input.exists():
        print(f"Results file not found: {args.input}. Collect results first by running: alcedo", file=sys.stderr)
        return 1
    if not is_results_file(args.input):
        print(f"{args.input} has no Alcedo results.", file=sys.stderr)
        return 1
    entries, failed = read_entries(args.input)
    if not entries:
        print(f"No records in {args.input}.", file=sys.stderr)
        return 1

    sjr = None
    if args.sjr:
        try:
            sjr = load_sjr(args.sjr)
        except (OSError, ValueError) as exc:
            print(f"Cannot use the SJR file: {exc}", file=sys.stderr)
            return 1

    dois = [e.doi for e in entries if e.doi and e.registered]
    records, unchecked = fetch_metadata(dois, args, Cache() if args.use_cache else None) if dois else ({}, [])
    unchecked = set(unchecked)
    for entry in entries:
        if entry.doi:
            key = entry.doi.lower()
            entry.record = records.get(key)
            entry.checked = key not in unchecked
            if entry.record:
                entry.title = entry.record.get("title")
    entries = merge_found_titles(entries)

    words = [(word, re.compile(rf"(?<!\w){re.escape(word)}(?!\w)", re.I)) for word in args.exclude_word]
    groups: dict[str, list[Entry]] = {"kept": [], "excluded": [], "unknown": []}
    for entry in entries:
        groups[judge(entry, args, words, sjr)].append(entry)

    stem = args.output or str(args.input.with_name(args.input.stem.removesuffix("_results")))
    paths = {"kept": Path(f"{stem}_filtered.csv"), "excluded": Path(f"{stem}_excluded.csv"),
             "unknown": Path(f"{stem}_unknown.csv")}
    try:
        for name, path in paths.items():
            _write(path, groups[name])
    except OSError as exc:
        print(f"Cannot write {exc.filename}: {exc.strerror}. If it is open in Excel, close it and run again.",
              file=sys.stderr)
        return 1

    print(f"Records: {len(entries)}. Kept: {len(groups['kept'])}. Excluded: {len(groups['excluded'])}. "
          f"Unknown: {len(groups['unknown'])}.")
    for name, label in (("excluded", "Excluded"), ("unknown", "Unknown")):
        reasons = Counter(re.sub(r"\byear \d+", "year", reason) for e in groups[name] for reason in e.reasons)
        if reasons:
            print(f"{label}, by reason: " + ", ".join(f"{reason} ({count})" for reason, count in reasons.most_common()))
    print(f"Files: {paths['kept']}, {paths['excluded']}, {paths['unknown']}")
    if groups["unknown"]:
        print("Check the unknown list by hand: these records may well meet your conditions.")
    if failed:
        print(f"{counted(failed, 'query', 'queries')} failed during collection, so their results are incomplete. "
              "Collect them again with: alcedo --resume")
    if unchecked:
        print(f"Could not check {counted(len(unchecked), 'DOI')}. Run again later to fill them in.")
    return 0
