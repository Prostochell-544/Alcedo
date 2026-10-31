import argparse

import pytest
import requests

from alcedo_lit import resolve
from alcedo_lit.net import SESSION, api_headers
from helpers import FakeResponse


def make_args(**overrides):
    defaults = {"mailto": None, "openalex_key": None, "http_timeout": 5, "page_meta": True, "title_search": True}
    return argparse.Namespace(**{**defaults, **overrides})


@pytest.fixture
def calls(monkeypatch):
    """Record requests. A request that a test did not set up fails like a network error."""
    log = {"urls": [], "responses": {}}

    def fake_get(url, **kwargs):
        log["urls"].append((url, kwargs))
        for prefix, response in log["responses"].items():
            if url.startswith(prefix):
                return response
        raise requests.ConnectionError(f"unexpected request: {url}")

    monkeypatch.setattr(SESSION, "get", fake_get)
    resolve.failed_lookups.clear()
    return log


def test_doi_given_by_the_source_is_used_as_is(calls):
    assert resolve.find_doi({"doi": "10.1234/report.full", "title": "t"}, make_args()) == "10.1234/report.full"
    assert calls["urls"] == []


def test_doi_in_url_needs_no_network(calls):
    pub = {"pub_url": "https://doi.org/10.1234/abc", "title": "t"}
    assert resolve.find_doi(pub, make_args()) == "10.1234/abc"
    assert calls["urls"] == []


def test_pubmed_link_goes_to_europepmc(calls):
    calls["responses"][resolve.EUROPEPMC_URL] = FakeResponse(data={"resultList": {"result": [{"doi": "10.1038/x"}]}})
    assert resolve.find_doi({"pub_url": "https://pubmed.ncbi.nlm.nih.gov/32015507/"}, make_args()) == "10.1038/x"


def test_meta_tags_come_before_title_search(calls):
    page = FakeResponse(url="https://publisher.org/a", headers={"Content-Type": "text/html"},
                        body=b'<meta name="citation_doi" content="10.5555/meta">')
    calls["responses"]["https://publisher.org"] = page
    pub = {"pub_url": "https://publisher.org/a", "title": "Some title"}
    assert resolve.find_doi(pub, make_args()) == "10.5555/meta"
    assert len(calls["urls"]) == 1


def test_publisher_requests_identify_alcedo_honestly(calls):
    calls["responses"]["https://publisher.org"] = FakeResponse(status_code=403, url="https://publisher.org/a",
                                                               headers={"Content-Type": "text/html"})
    resolve.find_doi({"pub_url": "https://publisher.org/a"}, make_args(title_search=False, mailto="me@example.org"))
    user_agent = calls["urls"][0][1]["headers"]["User-Agent"]
    assert user_agent.startswith("alcedo/")
    assert "Mozilla" not in user_agent
    assert "me@example.org" not in user_agent


def test_no_fetch_hosts_and_pdfs_are_skipped(calls):
    pub = {"pub_url": "https://www.researchgate.net/publication/1", "eprint_url": "https://x.org/paper.pdf"}
    assert resolve.find_doi(pub, make_args(title_search=False)) is None
    assert calls["urls"] == []


def test_title_search_falls_back_from_crossref_to_openalex(calls):
    title = "Array programming with NumPy"
    calls["responses"][resolve.CROSSREF_URL] = FakeResponse(data={"message": {"items": [
        {"DOI": "10.1/numpy-chapter", "title": ["NumPy"]}]}})
    calls["responses"][resolve.OPENALEX_URL] = FakeResponse(data={"results": [
        {"doi": "https://doi.org/10.1/review", "title": f'Review of "{title}"', "type": "peer-review"},
        {"doi": "https://doi.org/10.1038/numpy", "title": title, "type": "article"}]})
    assert resolve.find_doi({"title": title}, make_args(page_meta=False)) == "10.1038/numpy"
    crossref_params = calls["urls"][0][1]["params"]
    assert "type:journal-article" in crossref_params["filter"]
    assert "peer-review" not in crossref_params["filter"]


def test_failing_source_does_not_stop_the_chain(calls):
    calls["responses"][resolve.OPENALEX_URL] = FakeResponse(data={"results": [
        {"doi": "https://doi.org/10.1234/found", "title": "Exact title", "type": "article"}]})
    # Crossref has no response set up, so it fails like a network error.
    assert resolve.find_doi({"title": "Exact title"}, make_args(page_meta=False)) == "10.1234/found"
    assert resolve.failed_lookups == {"Crossref": 1}


def test_a_lookup_that_finds_nothing_is_not_counted_as_failed(calls):
    calls["responses"][resolve.CROSSREF_URL] = FakeResponse(data={"message": {"items": []}})
    calls["responses"][resolve.OPENALEX_URL] = FakeResponse(data={"results": []})
    assert resolve.find_doi({"title": "Unknown"}, make_args(page_meta=False)) is None
    assert not resolve.failed_lookups


def test_programming_errors_are_reported_and_do_not_stop_the_run(monkeypatch, capsys):
    def broken(*_):
        raise TypeError("a bug")

    monkeypatch.setattr(resolve, "find_doi", broken)
    lines = resolve.resolve_dois([{"title": "Odd record"}], make_args())
    assert lines == ["DOI not found: Odd record"]
    assert "TypeError: a bug" in capsys.readouterr().out


def test_resolve_dois_reports_missing_and_removes_duplicates(calls):
    records = [{"pub_url": "https://doi.org/10.1234/A", "title": "a"},
               {"pub_url": "https://doi.org/10.1234/a", "title": "same DOI in another case"},
               {"title": "no doi anywhere"}]
    lines = resolve.resolve_dois(records, make_args(page_meta=False, title_search=False))
    assert lines == ["https://doi.org/10.1234/A", "DOI not found: no doi anywhere"]


def test_result_line_is_a_valid_link_for_a_sici_doi():
    lines = resolve.resolve_dois([{"doi": "10.1002/(sici)1(1)45:1<118::aid-pi908>3.0.co;2-t"}], make_args())
    assert lines == ["https://doi.org/10.1002/(sici)1(1)45:1%3C118::aid-pi908%3E3.0.co;2-t"]


def test_resolve_dois_empty_names_the_source():
    assert resolve.resolve_dois([], make_args(), source="OpenAlex") == ["DOI not found (OpenAlex returned nothing)"]


def test_mailto_reaches_the_user_agent():
    assert "mailto:me@example.org" in api_headers("me@example.org")["User-Agent"]
