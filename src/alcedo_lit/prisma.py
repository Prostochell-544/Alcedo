"""A selection log with the numbers a PRISMA 2020 flow diagram asks for, written by `alcedo filter`."""

from __future__ import annotations

import argparse
import re
from collections import Counter
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from . import __version__
from .results import DIRECT_LABEL, ERROR_PREFIX, NOT_FOUND, NOT_REGISTERED, SOURCE_PREFIX, read_blocks

API_LABEL = "Google Scholar through a search API"
SOURCE_NAMES = {"Google Scholar": API_LABEL, DIRECT_LABEL: "Google Scholar, direct search"}
# Reasons that are not about the conditions you chose: PRISMA counts these as "removed for other reasons".
OTHER_REASONS = ("retracted", "DOI not registered in doi.org")


@dataclass
class Found:
    """What the search collected, counting a paper once for every query that found it."""

    queries: int = 0
    failed: int = 0
    records: int = 0
    by_source: Counter = field(default_factory=Counter)


def _is_record(line: str) -> bool:
    return line.startswith(("https://doi.org/", f"{NOT_FOUND}: ", f"{NOT_REGISTERED}: "))


def count_found(path: Path) -> Found:
    """Count the records in a results file by source, from the source line of each block."""
    found = Found()
    for lines in read_blocks(path).values():
        found.queries += 1
        found.failed += any(line.startswith(ERROR_PREFIX) for line in lines)
        records = sum(map(_is_record, lines))
        found.records += records
        source = next((line for line in lines if line.startswith(SOURCE_PREFIX)), None)
        if source is None:
            found.by_source[API_LABEL] += records  # only blocks from a search API have no source line
            continue
        parts = source.removeprefix(SOURCE_PREFIX).split(" - ")[0].strip()
        counted = 0
        bare = None
        for part in parts.split(" + "):
            if part.startswith(DIRECT_LABEL) and "returned" in part:  # a block from --source scholar
                bare = DIRECT_LABEL
                continue
            if m := re.fullmatch(r"(.+?) \((\d+)(?: new of \d+)?\)", part):
                name, number = m.group(1), int(m.group(2))
                found.by_source[SOURCE_NAMES.get(name, name)] += number
                counted += number
            else:
                bare = part
        if bare:
            found.by_source[SOURCE_NAMES.get(bare, bare)] += records - counted
    return found


def _conditions(args: argparse.Namespace) -> list[str]:
    conditions = []
    if args.year_from or args.year_to:
        conditions.append(f"years {args.year_from or '…'} to {args.year_to or '…'}")
    if args.language:
        conditions.append("language " + ", ".join(sorted(args.language)))
    if args.type:
        conditions.append("type " + ", ".join(sorted(args.type)))
    if args.quartile:
        conditions.append(f"quartile {', '.join(sorted(args.quartile))}, from the SJR file {args.sjr.name}")
    if args.exclude_word:
        conditions.append("excluded words " + ", ".join(f'"{w}"' for w in args.exclude_word))
    conditions.append("retracted papers kept" if args.keep_retracted else "retracted papers excluded")
    return conditions


def write_log(path: Path, args: argparse.Namespace, found: Found, unique_before: int, joined_titles: int,
              groups: dict[str, list], files: dict[str, Path]) -> None:
    """Write the selection log. `unique_before` counts records once each, before titles were compared."""
    repeats = len(groups["duplicates"])
    across_queries = found.records - unique_before
    duplicates = across_queries + joined_titles + repeats
    screened = found.records - duplicates
    excluded = groups["excluded"]
    other = [e for e in excluded if all(r in OTHER_REASONS for r in e.reasons)]
    by_reason = Counter(re.sub(r"\byear \d+", "year", reason) for e in excluded for reason in e.reasons)
    open_copy = sum(bool((e.record or {}).get("open_access_url")) for e in groups["kept"])
    unknown_access = sum((e.record or {}).get("open_access") is None for e in groups["kept"])

    lines = [
        "# Selection log",
        "",
        f"Made by Alcedo {__version__} on {date.today().isoformat()} from `{args.input.name}`.",
        "",
        "## Search",
        "",
        f"- Queries: {found.queries}" + (f", of which {found.failed} failed during collection" if found.failed else ""),
        f"- Records found, counting a paper once for every query that found it: {found.records}",
        *(f"  - {source}: {number}" for source, number in found.by_source.most_common()),
        "",
        "## Duplicates",
        "",
        f"- Found by more than one query: {across_queries}",
        f"- Without a DOI, but with the title of a record that has one: {joined_titles}",
        f"- The same work under another DOI, such as a preprint of an article: {repeats} "
        f"(`{files['duplicates'].name}`)",
        f"- Unique records: {screened}",
        "",
        "## Screening by Alcedo",
        "",
        "Conditions: " + "; ".join(_conditions(args)) + ".",
        "",
        f"- Excluded: {len(excluded)} (`{files['excluded'].name}`)",
        *(f"  - {reason}: {number}" for reason, number in by_reason.most_common()),
        f"- Data missing, to check by hand: {len(groups['unknown'])} (`{files['unknown'].name}`)",
        f"- Kept: {len(groups['kept'])} (`{files['kept'].name}`)",
        "",
        "A record can fail more than one condition, so the reasons can add up to more than the excluded records.",
        "",
        "## Access to the kept papers",
        "",
        f"- With a legal open copy: {open_copy}",
        f"- Without one: {len(groups['no_access'])} (`{files['no_access'].name}`)",
        f"- Not known: {unknown_access}",
        "",
        "## For a PRISMA 2020 flow diagram",
        "",
        f"- Records identified from databases: n = {found.records}, by source as listed under Search.",
        f"- Records removed before screening: duplicate records n = {duplicates}; records marked as ineligible by "
        f"automation tools (Alcedo) n = {len(excluded) - len(other)}; records removed for other reasons, such as "
        f"retraction or a DOI that does not exist, n = {len(other)}.",
        f"- Records screened: n = {len(groups['kept']) + len(groups['unknown'])}, of which "
        f"{len(groups['unknown'])} lack data and need checking by hand.",
        "",
        "The next steps, screening titles and abstracts and assessing full texts, are done by people, so record those "
        "numbers yourself. Open copies help with the reports you seek for retrieval, and the papers without one may "
        "end up as reports not retrieved.",
        "",
    ]
    path.write_text("\n".join(lines), encoding="utf-8")
