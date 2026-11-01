import argparse

import pytest
import requests

from alcedo_lit import resolve
from alcedo_lit.net import SESSION, api_headers
from alcedo_lit.verify import HANDLE_API
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


def handles(calls, known, unknown=()):
    """Answer the doi.org registry: DOIs in `known` exist, DOIs in `unknown` do not, others give no clear answer."""
    # The fake matches by prefix and in order, so the longer DOIs, which are the unknown ones here, come first.
    for doi in unknown:
        calls["responses"][HANDLE_API + doi] = FakeResponse(data={"responseCode": 100})
    for doi in known:
        calls["responses"][HANDLE_API + doi] = FakeResponse(data={"responseCode": 1})


def test_page_number_after_a_doi_is_dropped_when_the_registry_says_so(calls):
    handles(calls, known=["10.1093/reprod/xaag115"], unknown=["10.1093/reprod/xaag115/8787412"])
    pub = {"pub_url": "https://academic.oup.com/article-lookup/doi/10.1093/reprod/xaag115/8787412"}
    assert resolve.find_doi(pub, make_args()) == "10.1093/reprod/xaag115"


def test_a_doi_that_really_ends_in_a_number_is_kept(calls):
    doi = "10.1088/1742-6596/1234/1/012001"
    handles(calls, known=[doi])
    assert resolve.find_doi({"pub_url": f"https://iopscience.iop.org/article/{doi}"}, make_args()) == doi


def test_without_an_answer_from_the_registry_the_doi_stays_as_found(calls):
    doi = "10.1093/reprod/xaag115/8787412"
    assert resolve.find_doi({"pub_url": f"https://academic.oup.com/article-lookup/doi/{doi}"}, make_args()) == doi


def test_when_neither_form_is_registered_the_doi_stays_as_found(calls):
    doi = "10.1093/reprod/xaag115/8787412"
    handles(calls, known=[], unknown=[doi, "10.1093/reprod/xaag115"])
    assert resolve.find_doi({"pub_url": f"https://academic.oup.com/x/{doi}"}, make_args()) == doi


def test_a_doi_org_link_is_taken_whole_with_no_lookup(calls):
    doi = "10.1234/abc/123"
    assert resolve.find_doi({"pub_url": f"https://doi.org/{doi}"}, make_args()) == doi
    assert calls["urls"] == []


def test_ordinary_doi_in_a_url_needs_no_lookup(calls):
    assert resolve.find_doi({"pub_url": "https://publisher.org/doi/10.1234/abc"}, make_args()) == "10.1234/abc"
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
