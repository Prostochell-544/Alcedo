"""Checking DOIs in the doi.org registry with --verify-dois."""

import pytest
import requests

from alcedo_lit import cli, verify
from alcedo_lit.net import SESSION
from alcedo_lit.sources import openalex
from helpers import FakeResponse, blocks_of, pubs


@pytest.fixture
def registry(monkeypatch):
    """A fake registry. Keys are DOIs in lower case; missing ones answer 'not found'."""
    state = {"answers": {}, "requests": []}

    def fake_get(url, headers=None, **_):
        assert url.startswith(verify.HANDLE_API)
        doi = url.removeprefix(verify.HANDLE_API)
        state["requests"].append((doi, headers))
        answer = state["answers"].get(doi.lower(), 100)
        if isinstance(answer, Exception):
            raise answer
        return FakeResponse(status_code=404 if answer == 100 else 200, data={"responseCode": answer})

    monkeypatch.setattr(SESSION, "get", fake_get)
    return state


@pytest.mark.parametrize("answer, expected", [(1, True), (200, True), (100, False), (2, None), (None, None)])
def test_registry_answers(registry, answer, expected):
    registry["answers"]["10.1234/a"] = answer
    assert verify.doi_exists("10.1234/a", 5) is expected


def test_network_error_is_not_evidence_against_a_doi(registry):
    registry["answers"]["10.1234/a"] = requests.ConnectionError("down")
    assert verify.doi_exists("10.1234/a", 5) is None


def test_non_json_answer_is_not_evidence_against_a_doi(monkeypatch):
    def not_json():
        raise ValueError("not json")

    response = FakeResponse()
    response.json = not_json
    monkeypatch.setattr(SESSION, "get", lambda *a, **k: response)
    assert verify.doi_exists("10.1234/a", 5) is None


def test_sici_doi_is_encoded_and_email_is_not_sent(registry):
    registry["answers"]["10.1002/(sici)1(1)45:1%3c118::aid%3e3.0.co;2-t"] = 1
    assert verify.doi_exists("10.1002/(sici)1(1)45:1<118::aid>3.0.co;2-t", 5) is True
    assert "mailto" not in registry["requests"][0][1]["User-Agent"]


def test_results_mark_only_what_the_registry_denies(registry):
    registry["answers"].update({"10.1234/good": 1, "10.1234/down": requests.ConnectionError("down")})
    results = {"q1": ["Source: OpenAlex", "https://doi.org/10.1234/good", "https://doi.org/10.1234/bad"],
               "q2": ["https://doi.org/10.1234/bad", "https://doi.org/10.1234/down", "DOI not found: x"]}
    assert verify.verify_results(results, 5) == (1, 1)
    assert results == {
        "q1": ["Source: OpenAlex", "https://doi.org/10.1234/good", "DOI not registered: 10.1234/bad"],
        "q2": ["DOI not registered: 10.1234/bad", "https://doi.org/10.1234/down", "DOI not found: x"],
    }
    assert sorted(doi for doi, _ in registry["requests"]) == ["10.1234/bad", "10.1234/down", "10.1234/good"]


@pytest.fixture
def project(tmp_path, monkeypatch, registry):
    (tmp_path / "queries.txt").write_text("q1 one; q2 two;", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(openalex, "search_openalex", lambda query, args: (pubs("x", range(1, 3)), None))
    registry["answers"]["10.1234/x.1"] = 1
    return tmp_path


def test_checking_is_off_by_default(project, registry):
    assert cli.main(["--no-semantic-scholar"]) == 0
    assert registry["requests"] == []


def test_run_marks_dois_removes_them_from_the_list_and_reports(project, registry, capsys):
    assert cli.main(["--no-semantic-scholar", "--verify-dois"]) == 0
    blocks = blocks_of(project / "alcedo_results.txt")
    assert blocks["q1 one"] == ["Source: OpenAlex", "https://doi.org/10.1234/x.1", "DOI not registered: 10.1234/x.2"]
    assert "10.1234/x.2" not in (project / "alcedo_results_unique.csv").read_text(encoding="utf-8-sig")
    output = capsys.readouterr().out
    assert "unique: 1" in output
    assert "'DOI not registered': 2 result lines" in output


def test_existing_results_can_be_checked_with_resume(project, registry, monkeypatch):
    assert cli.main(["--no-semantic-scholar"]) == 0
    monkeypatch.setattr(openalex, "search_openalex", lambda *_: pytest.fail("nothing should be searched"))
    assert cli.main(["--no-semantic-scholar", "--resume", "--verify-dois"]) == 0
    assert "DOI not registered: 10.1234/x.2" in (project / "alcedo_results.txt").read_text(encoding="utf-8")


def test_unchecked_dois_stay_and_are_reported(project, registry, capsys):
    registry["answers"]["10.1234/x.2"] = requests.ConnectionError("down")
    assert cli.main(["--no-semantic-scholar", "--verify-dois"]) == 0
    assert "https://doi.org/10.1234/x.2" in (project / "alcedo_results.txt").read_text(encoding="utf-8")
    assert "Could not check 1 DOI" in capsys.readouterr().out
