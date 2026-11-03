"""`alcedo check`: find mistakes in a query file before a run uses up any quota. Nothing here touches the network."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from .results import counted

ERROR, WARNING = "error", "warning"
QUOTED_RE = re.compile(r'"[^"]*"')
CURLY_QUOTES = "«»“”„‟‘’"
MINUS_WITH_SPACE_RE = re.compile(r"(?:^|\s)-\s+\S")
SCHOLAR_ONLY_RE = re.compile(r"\b(?:allintitle|intitle|author|source):", re.I)
NOT_FILTERS_RE = re.compile(r"\b(?:site|filetype):", re.I)
YEAR_RANGE_RE = re.compile(r"\b(?:19|20)\d\d\s*[-–—]\s*(?:19|20)\d\d\b")
CYRILLIC_RE = re.compile(r"[Ѐ-ӿ]")
OR_GROUP_RE = re.compile(r"\(([^()]*)\)")
MAX_OR_TERMS = 5
MAX_WORDS = 12


def _or_outside_parentheses(bare: str) -> bool:
    depth = 0
    for token in re.findall(r"[()]|\bOR\b", bare):
        if token == "(":
            depth += 1
        elif token == ")":
            depth -= 1
        elif depth <= 0:
            return True
    return False


def _parentheses_balance(bare: str) -> bool:
    depth = 0
    for char in bare:
        depth += {"(": 1, ")": -1}.get(char, 0)
        if depth < 0:
            return False
    return depth == 0


def find_problems(query: str) -> list[tuple[str, str]]:
    """Return (level, message) pairs for one query. An error means the query will not work as written."""
    problems = []
    if query.count('"') % 2:
        problems.append((ERROR, 'A quote mark " has no pair, so the phrase does not end where you meant.'))
    # Everything else looks outside quoted phrases, where these characters and words are only text.
    bare = QUOTED_RE.sub(" ", query)

    if not _parentheses_balance(bare):
        problems.append((ERROR, "Parentheses do not match."))
    if "*" in bare:
        problems.append((ERROR, "`*` is not supported: OpenAlex answers with an error. List the word forms with OR."))
    if any(char in query for char in CURLY_QUOTES):
        problems.append((ERROR, 'Curly quotes or guillemets do not mark a phrase. Use straight quotes: "...".'))
    if _or_outside_parentheses(bare):
        problems.append((ERROR, "OR needs parentheses: write nacre (toughness OR fracture)."))

    if re.search(r"\b(?:or|Or|oR)\b", bare):
        problems.append((WARNING, 'A lowercase "or" is not an operator and silently means AND. Write OR in capitals.'))
    if MINUS_WITH_SPACE_RE.search(bare):
        problems.append((WARNING, "A minus excludes a word only when attached to it: write -dental."))
    if SCHOLAR_ONLY_RE.search(bare):
        problems.append((WARNING, "intitle:, author: and source: work only in Google Scholar. Other sources "
                                  "drop the prefix and search the word everywhere."))
    if NOT_FILTERS_RE.search(bare):
        problems.append((WARNING, "site: and filetype: are not filters here."))
    if YEAR_RANGE_RE.search(bare):
        problems.append((WARNING, "Years are not a filter here: they just become extra search words."))
    if CYRILLIC_RE.search(query):
        problems.append((WARNING, "The indexes are mostly English, so a query in another language finds far less."))
    if "#" in query:
        problems.append((WARNING, "There are no comments: # and the text after it are part of the query."))

    words = [w for w in re.split(r"[\s()]+", query) if w and w != "OR"]
    if len(words) == 1:
        problems.append((WARNING, "One word gives close to random results. Add what you want to know about it."))
    elif len(words) > MAX_WORDS:
        problems.append((WARNING, f"This is a long query, with {len(words)} terms. As a rule of thumb, "
                                  f"keep to {MAX_WORDS} or split it in two."))
    if any(len(re.findall(r"\bOR\b", group)) >= MAX_OR_TERMS for group in OR_GROUP_RE.findall(bare)):
        problems.append((WARNING, f"A long OR list blurs the results. As a rule of thumb, keep to "
                                  f"{MAX_OR_TERMS} terms."))
    return problems


def check_text(text: str) -> list[tuple[str, list[tuple[str, str]]]]:
    """Return (query, problems) for each query in a file's text, in order."""
    checked, seen = [], set()
    for part in text.split(";"):
        part = part.strip()
        query = " ".join(part.split())
        if not query:
            continue
        problems = find_problems(query)
        if query in seen:
            problems.append((WARNING, "This repeats an earlier query, so it will be skipped."))
        if "\n" in part:
            problems.append((WARNING, "This query spans several lines. If these are separate queries, "
                                      "end each one with ;"))
        seen.add(query)
        checked.append((query, problems))
    return checked


def queries_with_problems(path: Path) -> int:
    """Count queries that may have a mistake, for a short note before a run."""
    return sum(bool(problems) for _, problems in check_text(path.read_text(encoding="utf-8-sig")))


def run_check(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(prog="alcedo check", description="Find mistakes in a query file before a run. "
                                                                      "Uses no network and no quota.")
    parser.add_argument("-i", "--input", type=Path, default=Path("queries.txt"),
                        help="file with queries separated by ';' (default: queries.txt)")
    args = parser.parse_args(argv)
    try:
        text = args.input.read_text(encoding="utf-8-sig")
    except OSError as exc:
        print(f"Cannot read {args.input}: {exc.strerror}", file=sys.stderr)
        return 1
    except UnicodeDecodeError:
        print(f"{args.input} is not saved as UTF-8. Save it as UTF-8 and try again.", file=sys.stderr)
        return 1

    checked = check_text(text)
    if not checked:
        print(f"No queries in {args.input} (separate them with ';')", file=sys.stderr)
        return 1
    errors = warnings = 0
    for number, (query, problems) in enumerate(checked, 1):
        if problems:
            print(f"Query {number}: {query}")
        for level, message in problems:
            print(f"  {level}: {message}")
            errors += level == ERROR
            warnings += level == WARNING
    print(f"Checked {counted(len(checked), 'query', 'queries')}: {counted(errors, 'error')}, "
          f"{counted(warnings, 'warning')}.")
    return 1 if errors else 0
