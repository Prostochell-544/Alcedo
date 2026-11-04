"""`alcedo export`: write results as RIS and BibTeX, for Zotero, Mendeley, EndNote and ASReview."""

from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import unicodedata
from pathlib import Path

from .cache import Cache
from .config import load_config
from .doi import doi_url
from .filters import merge_found_titles, read_entries
from .metadata import fetch_metadata
from .results import counted, is_results_file

RIS_TYPES = {"article": "JOUR", "journal-article": "JOUR", "review": "JOUR", "letter": "JOUR", "editorial": "JOUR",
             "conference-paper": "CPAPER", "proceedings-article": "CPAPER", "book-chapter": "CHAP", "book": "BOOK",
             "monograph": "BOOK", "edited-book": "BOOK", "dissertation": "THES", "report": "RPRT",
             "preprint": "UNPB", "posted-content": "UNPB"}
BIBTEX_TYPES = {"JOUR": "article", "CPAPER": "inproceedings", "CHAP": "incollection", "BOOK": "book",
                "THES": "phdthesis", "RPRT": "techreport", "UNPB": "misc", "GEN": "misc"}
CONTAINER_FIELD = {"article": "journal", "inproceedings": "booktitle", "incollection": "booktitle"}
NAME_PARTICLES = {"van", "von", "der", "den", "de", "del", "della", "di", "da", "dos", "das", "du", "la", "le", "ten",
                  "ter", "bin", "al", "el"}
NAME_SUFFIXES = {"JR", "SR", "II", "III", "IV"}
ORGANIZATION_RE = re.compile(r"\b(?:Organi[sz]ation|Consortium|Collaboration|Group|Society|Committee|Association|"
                             r"Institute|University|Network|Council|Agency|Team|Working)\b", re.I)


def read_records(path: Path) -> list[dict]:
    """Read a filter list (.csv) or a results file into [{"doi", "title", "queries"}], most often found first."""
    if path.suffix.lower() == ".csv":
        with path.open(encoding="utf-8-sig", newline="") as file:
            reader = csv.DictReader(file, delimiter=";")
            if not reader.fieldnames or "doi" not in reader.fieldnames:
                raise ValueError(f"{path} has no 'doi' column. Use a file from alcedo filter, or a results file.")
            return [{"doi": row["doi"] or None, "title": row.get("title") or None,
                     "queries": [q for q in (row.get("queries") or "").split(" | ") if q]} for row in reader]
    if not is_results_file(path):
        raise ValueError(f"{path} has no Alcedo results.")
    entries, _ = read_entries(path)
    entries = sorted(merge_found_titles(entries), key=lambda e: -len(e.queries))
    return [{"doi": e.doi, "title": e.title, "queries": e.queries} for e in entries if e.registered]


def _page_range(pages: str | None) -> tuple[str | None, str | None]:
    if not pages:
        return None, None
    parts = re.split(r"\s*[-–—]+\s*", str(pages))
    return parts[0] or None, parts[1] if len(parts) > 1 and parts[1] else None


def last_first(name: str) -> str:
    """Turn "Jie Li" into "Li, Jie", the form reference managers split into family and given name.

    Without the comma, Zotero keeps the whole name as one field and sorts by the given name. Particles such as "van"
    stay with the family name. A name that already has a comma, and an organization, is kept as it is.
    """
    name = " ".join(name.split())
    words = name.split(" ")
    if "," in name or len(words) < 2 or ORGANIZATION_RE.search(name):
        return name
    suffix = words.pop() if words[-1].rstrip(".").upper() in NAME_SUFFIXES and len(words) > 2 else None
    # Some records put an initial after the family name, as in "Tobias Stalder A"; it belongs with the given name.
    trailing = []
    while len(words) > 2 and re.fullmatch(r"[A-Z]\.?", words[-1]):
        trailing.insert(0, words.pop())
    words = words[:-1] + trailing + words[-1:] if trailing else words
    start = len(words) - 1
    while start > 1 and words[start - 1].lower() in NAME_PARTICLES:
        start -= 1
    family, given = " ".join(words[start:]), " ".join(words[:start])
    return f"{family}, {given}" + (f", {suffix}" if suffix else "")


def ris_entry(item: dict, record: dict | None) -> str:
    record = record or {}
    kind = RIS_TYPES.get(record.get("type") or "", "GEN") if record else ("JOUR" if item["doi"] else "GEN")
    lines = [("TY", kind), ("TI", record.get("title") or item["title"])]
    lines += [("AU", last_first(author)) for author in record.get("authors") or [] if author]
    first, last = _page_range(record.get("pages"))
    lines += [("PY", record.get("year")), ("T2", record.get("journal")), ("VL", record.get("volume")),
              ("IS", record.get("issue")), ("SP", first), ("EP", last),
              ("SN", (record.get("issn") or [None])[0]), ("LA", record.get("language")),
              ("DO", item["doi"]), ("UR", doi_url(item["doi"]) if item["doi"] else None),
              ("AB", record.get("abstract"))]
    if record.get("retracted"):
        lines.append(("N1", "Retracted, according to OpenAlex"))
    if item["queries"]:
        lines.append(("N1", "Found by Alcedo queries: " + " | ".join(item["queries"])))
    lines.append(("ER", ""))
    # A line break inside a value would end the field, so values are kept on one line.
    return "\n".join(f"{tag}  - {' '.join(str(value).split())}".rstrip() for tag, value in lines
                     if value not in (None, "") or tag == "ER") + "\n"


def _ascii_word(text: str) -> str:
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()
    return re.sub(r"[^A-Za-z0-9]", "", text)


def bibtex_key(item: dict, record: dict, used: set[str]) -> str:
    authors = [a for a in record.get("authors") or [] if a]
    surname = _ascii_word(last_first(authors[0]).split(",")[0]) if authors else ""
    words = [w for w in re.findall(r"\w+", record.get("title") or item["title"] or "") if len(w) > 3]
    first_word = _ascii_word(words[0]).lower() if words else ""
    base = (surname.lower() or "anon") + str(record.get("year") or "") + first_word
    key, suffix = base, ord("a")
    while key in used:
        key, suffix = base + chr(suffix), suffix + 1
    used.add(key)
    return key


def _bibtex_value(value) -> str:
    """Keep a value on one line and escape what would break the entry or LaTeX."""
    text = " ".join(str(value).split()).replace("{", "").replace("}", "")
    return re.sub(r"(?<!\\)([&%$#_])", r"\\\1", text)


def _bibtex_authors(authors: list[str | None]) -> str:
    """Join names with "and". An organization goes in braces, so BibTeX keeps it whole even if it contains "and"."""
    names = []
    for author in filter(None, authors):
        name = _bibtex_value(last_first(author))
        names.append(f"{{{name}}}" if ORGANIZATION_RE.search(author) else name)
    return " and ".join(names)


def bibtex_entry(item: dict, record: dict | None, used: set[str]) -> str:
    record = record or {}
    kind = BIBTEX_TYPES[RIS_TYPES.get(record.get("type") or "", "GEN") if record else "GEN"]
    first, last = _page_range(record.get("pages"))
    notes = (["Retracted, according to OpenAlex"] if record.get("retracted") else []) + (
        ["Found by Alcedo queries: " + " | ".join(item["queries"])] if item["queries"] else [])
    fields = [
        ("title", record.get("title") or item["title"]),
        ("author", _bibtex_authors(record.get("authors") or [])),
        ("year", record.get("year")),
        (CONTAINER_FIELD.get(kind, "howpublished"), record.get("journal")),
        ("volume", record.get("volume")),
        ("number", record.get("issue")),
        ("pages", f"{first}--{last}" if first and last else first),
        ("issn", (record.get("issn") or [None])[0]),
        ("language", record.get("language")),
        ("doi", item["doi"]),
        ("url", doi_url(item["doi"]) if item["doi"] else None),
        ("abstract", record.get("abstract")),
        ("note", "; ".join(notes)),
    ]
    body = ",\n".join(f"  {name} = {{{value if name == 'author' else _bibtex_value(value)}}}"
                      for name, value in fields if value not in (None, ""))
    return f"@{kind}{{{bibtex_key(item, record, used)},\n{body}\n}}\n"


def _parse_args(argv: list[str]) -> argparse.Namespace:
    config = load_config()
    p = argparse.ArgumentParser(
        prog="alcedo export",
        description="Write records as RIS and BibTeX, with authors, journal and abstracts, for Zotero, Mendeley, "
                    "EndNote and ASReview.")
    p.add_argument("-i", "--input", type=Path,
                   help="list from alcedo filter, or a results file (default: alcedo_filtered.csv if it exists, "
                        "otherwise alcedo_results.txt)")
    p.add_argument("-o", "--output", help="start of the output file names (default: the input file name)")
    p.add_argument("--format", choices=("both", "ris", "bibtex"), default="both", help="(default: both)")
    p.add_argument("--openalex-key", default=os.environ.get("OPENALEX_API_KEY") or config.get("openalex_key"),
                   help="free OpenAlex API key (default: OPENALEX_API_KEY variable or alcedo setup)")
    p.add_argument("--mailto", help="your e-mail, sent to Crossref and OpenAlex to identify your requests")
    p.add_argument("--http-timeout", type=float, default=30, help="timeout for each request, in seconds (default: 30)")
    p.add_argument("--no-cache", dest="use_cache", action="store_false", help="do not reuse or save paper data")
    return p.parse_args(argv)


def run_export(argv: list[str]) -> int:
    args = _parse_args(argv)
    if args.input is None:
        args.input = Path("alcedo_filtered.csv")
        if not args.input.exists():
            args.input = Path("alcedo_results.txt")
    if not args.input.exists():
        print(f"File not found: {args.input}. Run alcedo in this folder first, or name the file with -i.",
              file=sys.stderr)
        return 1
    try:
        items = read_records(args.input)
    except (OSError, ValueError, UnicodeDecodeError) as exc:
        print(f"Cannot read {args.input}: {exc}", file=sys.stderr)
        return 1
    if not items:
        print(f"No records in {args.input}.", file=sys.stderr)
        return 1

    dois = [item["doi"] for item in items if item["doi"]]
    records, unchecked = fetch_metadata(dois, args, Cache() if args.use_cache else None) if dois else ({}, [])
    stem = args.output or str(args.input.with_suffix(""))
    written = []
    try:
        if args.format in ("both", "ris"):
            path = Path(f"{stem}.ris")
            path.write_text("\n".join(ris_entry(i, records.get((i["doi"] or "").lower())) for i in items),
                            encoding="utf-8")
            written.append(path)
        if args.format in ("both", "bibtex"):
            path, used = Path(f"{stem}.bib"), set()
            path.write_text("\n".join(bibtex_entry(i, records.get((i["doi"] or "").lower()), used) for i in items),
                            encoding="utf-8")
            written.append(path)
    except OSError as exc:
        print(f"Cannot write {exc.filename}: {exc.strerror}. If it is open elsewhere, close it and run again.",
              file=sys.stderr)
        return 1

    without_doi = sum(not item["doi"] for item in items)
    with_abstract = sum(bool((records.get((i["doi"] or "").lower()) or {}).get("abstract")) for i in items)
    print(f"Exported {counted(len(items), 'record')} from {args.input}: {', '.join(map(str, written))}. "
          f"With an abstract: {with_abstract}.")
    if without_doi:
        print(f"Records without a DOI, which keep only their title: {without_doi}.")
    if unchecked:
        print(f"Could not fetch the data of {counted(len(unchecked), 'DOI')}, so those records are incomplete. "
              "Run again later to fill them in.")
    return 0
