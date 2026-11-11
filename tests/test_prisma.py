import argparse
from pathlib import Path

import pytest

from alcedo_lit import cli, filters
from alcedo_lit.prisma import API_LABEL, _conditions, count_found

BLOCKS = """=== Query: from an api ===
https://doi.org/10.1234/a
https://doi.org/10.1234/b
DOI not found: A paper without a DOI at all here

=== Query: free sources ===
Source: Semantic Scholar (1) + OpenAlex (2) + Google Scholar (direct) (1 new of 4) - the direct list may be incomplete
https://doi.org/10.1234/a
https://doi.org/10.1234/c
https://doi.org/10.1234/d
https://doi.org/10.1234/e

=== Query: openalex only ===
Source: OpenAlex - SearchApi unavailable: Out of credits
https://doi.org/10.1234/f
DOI not registered: 10.1234/fake

=== Query: scholar only ===
Source: Google Scholar (direct) returned 1 of up to 50; the list may be incomplete
https://doi.org/10.1234/g

=== Query: api ran out ===
Source: Google Scholar (1) + OpenAlex (1) - SearchApi unavailable: Out of credits
https://doi.org/10.1234/h
https://doi.org/10.1234/i

=== Query: failed ===
Query error: OpenAlex unavailable: HTTP 429 - DOI not found

"""


@pytest.fixture
def results(tmp_path):
    path = tmp_path / "alcedo_results.txt"
    path.write_text(BLOCKS, encoding="utf-8")
    return path


def test_records_are_counted_by_source(results):
    found = count_found(results)
    assert (found.queries, found.failed, found.records) == (6, 1, 12)
    assert dict(found.by_source) == {API_LABEL: 4, "Semantic Scholar": 1, "OpenAlex": 5,
                                     "Google Scholar, direct search": 2}
    assert sum(found.by_source.values()) == found.records


def test_the_log_adds_up(results, monkeypatch):
    monkeypatch.chdir(results.parent)
    papers = {f"10.1234/{x}": {"title": f"Paper {x}", "year": 2020, "type": "article", "open_access": "closed"}
              for x in "abcdefghi"}
    papers["10.1234/c"] = {**papers["10.1234/c"], "year": 2001, "open_access": "gold",
                           "open_access_url": "https://x.org/c.pdf"}
    monkeypatch.setattr(filters, "fetch_metadata", lambda dois, args, cache=None: (papers, []))
    assert cli.main(["filter", "--year-from", "2015"]) == 0
    log = (results.parent / "alcedo_selection_log.md").read_text(encoding="utf-8")
    assert "- Queries: 6, of which 1 failed during collection" in log
    assert "- Records found, counting a paper once for every query that found it: 12" in log
    assert "- Found by more than one query: 1" in log  # 10.1234/a, found by two queries
    assert "- Unique records: 11" in log
    assert "Conditions: years 2015 to …; retracted papers excluded." in log
    assert "- Excluded: 2 (`alcedo_excluded.csv`)" in log
    assert "  - year is before 2015: 1" in log
    assert "  - DOI not registered in doi.org: 1" in log
    assert "- Data missing, to check by hand: 1 (`alcedo_unknown.csv`)" in log  # the record without a DOI
    assert "- Kept: 8 (`alcedo_filtered.csv`)" in log
    assert "- Without one: 8 (`alcedo_no_access.csv`)" in log
    assert ("records marked as ineligible by automation tools (Alcedo) n = 1; records removed for other reasons, "
            "such as retraction or a DOI that does not exist, n = 1.") in log
    assert "- Records screened: n = 9, of which 1 lack data" in log


def test_conditions_are_listed_in_full():
    args =argparse.Namespace(year_from=None, year_to=2020, language={"en", "de"}, type={"review", "article"},
                              quartile={"Q2", "Q1"}, sjr=Path("dir/scimagojr 2025.csv"), exclude_word=["dental"],
                              keep_retracted=True)
    assert _conditions(args) == ["years … to 2020", "language de, en", "type article, review",
                                 "quartile Q1, Q2, from the SJR file scimagojr 2025.csv", 'excluded words "dental"',
                                 "retracted papers kept"]
