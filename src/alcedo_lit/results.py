"""Read the query file and read and write the grouped results file."""

from __future__ import annotations

import csv
import re
from pathlib import Path

from .doi import doi_url, extract_doi

NOT_FOUND = "DOI not found"
NOT_REGISTERED = "DOI not registered"
ERROR_PREFIX = "Query error"
SOURCE_PREFIX = "Source:"
DIRECT_LABEL = "Google Scholar (direct)"
HEADER_FMT = "=== Query: {} ==="
HEADER_RE = re.compile(r"^=== Query: (.*) ===$")


def read_queries(path: Path) -> list[str]:
    queries = []
    for part in path.read_text(encoding="utf-8-sig").split(";"):
        query = " ".join(part.split())  # line breaks and repeated spaces become one space
        if query and query not in queries:
            queries.append(query)
    return queries


def is_results_file(path: Path) -> bool:
    """Tell whether a file holds Alcedo blocks. An empty file counts, as there is nothing to lose."""
    text = path.read_text(encoding="utf-8", errors="replace")
    return not text.strip() or any(HEADER_RE.match(line) for line in text.splitlines())


def counted(number: int, noun: str, plural: str | None = None) -> str:
    return f"{number} {noun if number == 1 else plural or noun + 's'}"


def read_blocks(path: Path) -> dict[str, list[str]]:
    """Read a results file into {query: lines}."""
    results: dict[str, list[str]] = {}
    current = None
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if m := HEADER_RE.match(line):
                current = m.group(1)
                results[current] = []
            elif current is not None and line.strip():
                results[current].append(line)
    return results


def load_results(path: Path, redo_free: bool = False) -> dict[str, list[str]]:
    """Load finished blocks for --resume.

    Blocks with an error line are dropped so they get collected again. With `redo_free`,
    so are blocks with a source line, which means they did not come wholly from a search API.
    """
    results = read_blocks(path)

    def redo(line: str) -> bool:
        return line.startswith(ERROR_PREFIX) or (
            redo_free and line.startswith(SOURCE_PREFIX))

    return {q: lines for q, lines in results.items() if not any(redo(line) for line in lines)}


def doi_of_line(line: str) -> str | None:
    """Return the DOI if a result line is a DOI link."""
    return extract_doi(line) if line.startswith("https://doi.org/") else None


def combine_results(blocks: dict[str, list[str]]) -> list[tuple[str, list[str]]]:
    """List each DOI once with the queries that found it, most often found first."""
    found: dict[str, tuple[str, list[str]]] = {}
    for query, lines in blocks.items():
        for line in lines:
            if doi := doi_of_line(line):
                _, found_by = found.setdefault(doi.lower(), (doi, []))
                if query not in found_by:
                    found_by.append(query)
    return sorted(found.values(), key=lambda entry: -len(entry[1]))


def combined_path(results_path: Path) -> Path:
    return results_path.with_name(f"{results_path.stem}_unique.csv")


def save_results(path: Path, queries: list[str], results: dict[str, list[str]]) -> None:
    """Write the results file and, next to it, the combined list without repeats."""
    order = queries + [q for q in results if q not in queries]
    blocks = {q: results[q] for q in order if q in results}
    path.write_text(
        "".join(HEADER_FMT.format(q) + "\n" + "\n".join(lines) + "\n\n" for q, lines in blocks.items()),
        encoding="utf-8",
    )
    # Excel with a Russian or other European locale needs the semicolon and the byte order mark.
    with combined_path(path).open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.writer(file, delimiter=";")
        writer.writerow(["doi", "url", "found_by_queries", "queries"])
        for doi, found_by in combine_results(blocks):
            writer.writerow([doi, doi_url(doi), len(found_by), " | ".join(found_by)])
