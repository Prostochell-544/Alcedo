"""Read the query file and read and write the grouped results file."""

from __future__ import annotations

import re
from pathlib import Path

NOT_FOUND = "DOI not found"
ERROR_PREFIX = "Query error"
SOURCE_PREFIX = "Source:"
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


def load_results(path: Path, redo_openalex: bool = False) -> dict[str, list[str]]:
    """Load finished blocks for --resume.

    Blocks with an error line are dropped so they get collected again. With
    `redo_openalex`, so are blocks taken wholly or partly from OpenAlex.
    """
    results: dict[str, list[str]] = {}
    current = None
    if path.exists():
        for line in path.read_text(encoding="utf-8").splitlines():
            if m := HEADER_RE.match(line):
                current = m.group(1)
                results[current] = []
            elif current is not None and line.strip():
                results[current].append(line)

    def redo(line: str) -> bool:
        return line.startswith(ERROR_PREFIX) or (
            redo_openalex and line.startswith(SOURCE_PREFIX) and "OpenAlex" in line)

    return {q: lines for q, lines in results.items() if not any(redo(line) for line in lines)}


def save_results(path: Path, queries: list[str], results: dict[str, list[str]]) -> None:
    order = queries + [q for q in results if q not in queries]
    path.write_text(
        "".join(HEADER_FMT.format(q) + "\n" + "\n".join(results[q]) + "\n\n" for q in order if q in results),
        encoding="utf-8",
    )
