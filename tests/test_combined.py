"""The list without repeats that is written next to the results file."""

import csv

import pytest

from alcedo_lit import cli
from alcedo_lit.results import combine_results, combined_path, save_results
from alcedo_lit.sources import openalex
from helpers import pubs

A = "https://doi.org/10.1234/a"
B = "https://doi.org/10.1234/b"


def read_csv(path):
    with path.open(encoding="utf-8-sig", newline="") as file:
        return list(csv.DictReader(file, delimiter=";"))


def test_each_doi_appears_once_with_its_queries_most_found_first():
    combined = combine_results({"q1": [A], "q2": [B, A], "q3": [A, "DOI not found: x", "Source: OpenAlex"]})
    assert combined == [("10.1234/a", ["q1", "q2", "q3"]), ("10.1234/b", ["q2"])]


def test_doi_case_does_not_create_a_repeat():
    assert combine_results({"q1": ["https://doi.org/10.1234/ABC"], "q2": ["https://doi.org/10.1234/abc"]}) == [
        ("10.1234/ABC", ["q1", "q2"])]


def test_unregistered_doi_is_left_out():
    assert combine_results({"q": ["DOI not registered: 10.1234/a"]}) == []


def test_csv_opens_in_excel_and_keeps_sici_dois_whole(tmp_path):
    results = tmp_path / "r.txt"
    sici = "10.1002/(sici)1(1)45:1<118::aid-pi908>3.0.co;2-t"
    save_results(results, ["q1"], {"q1": ["https://doi.org/10.1002/(sici)1(1)45:1%3C118::aid-pi908%3E3.0.co;2-t"]})
    path = combined_path(results)
    assert path.name == "r_unique.csv"
    assert path.read_bytes().startswith(b"\xef\xbb\xbf")
    assert read_csv(path) == [{
        "doi": sici,
        "url": "https://doi.org/10.1002/(sici)1(1)45:1%3C118::aid-pi908%3E3.0.co;2-t",
        "found_by_queries": "1",
        "queries": "q1",
    }]


@pytest.fixture
def project(tmp_path, monkeypatch):
    (tmp_path / "queries.txt").write_text("q1 one; q2 two;", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(openalex, "search_openalex", lambda query, args: (pubs("same", range(1, 4)), None))
    return tmp_path


def test_a_run_writes_the_list_and_reports_unique_count(project, capsys):
    assert cli.main(["--no-semantic-scholar"]) == 0
    rows = read_csv(project / "alcedo_results_unique.csv")
    assert len(rows) == 3
    assert rows[0]["found_by_queries"] == "2"
    assert rows[0]["queries"] == "q1 one | q2 two"
    output = capsys.readouterr().out
    assert "DOIs: 6, unique: 3" in output
    assert "alcedo_results_unique.csv" in output


def test_resume_with_nothing_to_collect_still_writes_the_list(project, monkeypatch):
    assert cli.main(["--no-semantic-scholar"]) == 0
    (project / "alcedo_results_unique.csv").unlink()
    monkeypatch.setattr(openalex, "search_openalex", lambda *_: pytest.fail("nothing should be searched"))
    assert cli.main(["--no-semantic-scholar", "--resume"]) == 0
    assert len(read_csv(project / "alcedo_results_unique.csv")) == 3
