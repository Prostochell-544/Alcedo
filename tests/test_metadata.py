import argparse

import pytest
import requests

from alcedo_lit.cache import Cache
from alcedo_lit.metadata import BATCH_SIZE, fetch_metadata, record_from_crossref, record_from_openalex
from alcedo_lit.net import SESSION
from alcedo_lit.resolve import CROSSREF_URL
from alcedo_lit.sources.openalex import OPENALEX_URL
from helpers import FakeResponse

WORK = {
    "doi": "https://doi.org/10.1234/A",
    "title": "Paper A",
    "publication_year": 2020,
    "language": "en",
    "type": "article",
    "is_retracted": False,
    "primary_location": {"source": {"display_name": "Journal", "issn_l": "1111-1111",
                                    "issn": ["1111-1111", "2222-2222"]}},
    "authorships": [{"author": {"display_name": "A Author"}}, {"author": {"display_name": "B Author"}}],
    "biblio": {"volume": "5", "issue": "2", "first_page": "10", "last_page": "20"},
    "abstract_inverted_index": {"Hello": [0], "again": [2], "world": [1]},
}
CROSSREF = {
    "title": ["Paper B"],
    "issued": {"date-parts": [[2019, 3]]},
    "container-title": ["Other Journal"],
    "ISSN": ["3333-3333"],
    "language": "en",
    "type": "journal-article",
    "author": [{"given": "C", "family": "Author"}, {"name": "A Group"}],
    "volume": "7",
    "page": "1-9",
    "abstract": "<jats:p>Some &amp; text</jats:p>",
}


def make_args():
    return argparse.Namespace(openalex_key=None, mailto=None, http_timeout=5)


def test_openalex_record():
    assert record_from_openalex(WORK) == {
        "title": "Paper A", "year": 2020, "journal": "Journal", "issn": ["1111-1111", "2222-2222"], "language": "en",
        "type": "article", "retracted": False, "authors": ["A Author", "B Author"], "volume": "5", "issue": "2",
        "pages": "10-20", "abstract": "Hello world again", "source": "OpenAlex"}


def test_openalex_record_with_little_data():
    record = record_from_openalex({"doi": "https://doi.org/10.1/x", "primary_location": None, "biblio": None})
    assert record["journal"] is None
    assert record["issn"] == []
    assert record["authors"] == []
    assert record["pages"] is None
    assert record["abstract"] is None


def test_crossref_record_does_not_claim_a_paper_is_not_retracted():
    record = record_from_crossref(CROSSREF)
    assert record["retracted"] is None
    assert record["year"] == 2019
    assert record["authors"] == ["C Author", "A Group"]
    assert record["abstract"] == "Some & text"
    assert record["source"] == "Crossref"


@pytest.fixture
def services(monkeypatch):
    """A fake OpenAlex that knows `openalex`, and a fake Crossref that knows `crossref`."""
    state = {"openalex": {"10.1234/a": WORK}, "crossref": {"10.1234/b": CROSSREF}, "calls": [], "batches": [],
             "openalex_down": False, "crossref_down": False}

    def fake_get(url, params=None, **_):
        state["calls"].append(url)
        if url == OPENALEX_URL:
            if state["openalex_down"]:
                raise requests.ConnectionError("down")
            asked = params["filter"].removeprefix("doi:").split("|")
            state["batches"].append(asked)
            return FakeResponse(data={"results": [state["openalex"][d] for d in asked if d in state["openalex"]]})
        assert url.startswith(CROSSREF_URL)
        if state["crossref_down"]:
            raise requests.ConnectionError("down")
        doi = requests.utils.unquote(url.rsplit("/", 1)[1])
        if doi in state["crossref"]:
            return FakeResponse(data={"message": state["crossref"][doi]})
        return FakeResponse(status_code=404)

    monkeypatch.setattr(SESSION, "get", fake_get)
    return state


def test_openalex_first_then_crossref_then_nothing(services):
    records, unchecked = fetch_metadata(["10.1234/A", "10.1234/b", "10.1234/none"], make_args())
    assert records["10.1234/a"]["source"] == "OpenAlex"
    assert records["10.1234/b"]["source"] == "Crossref"
    assert records["10.1234/none"] is None
    assert unchecked == []


def test_dois_go_in_batches(services):
    fetch_metadata([f"10.1234/{i}" for i in range(BATCH_SIZE + 3)], make_args())
    assert [len(batch) for batch in services["batches"]] == [BATCH_SIZE, 3]


def test_a_doi_with_a_comma_goes_straight_to_crossref(services):
    services["crossref"]["10.1234/a,b"] = CROSSREF
    records, _ = fetch_metadata(["10.1234/a,b"], make_args())
    assert records["10.1234/a,b"]["source"] == "Crossref"
    assert services["batches"] == []


def test_when_both_services_fail_the_doi_is_unchecked_not_unknown(services):
    services["openalex_down"] = services["crossref_down"] = True
    records, unchecked = fetch_metadata(["10.1234/a"], make_args())
    assert records == {}
    assert unchecked == ["10.1234/a"]


def test_when_openalex_fails_crossref_can_still_answer(services):
    services["openalex_down"] = True
    records, unchecked = fetch_metadata(["10.1234/b"], make_args())
    assert records["10.1234/b"]["source"] == "Crossref"
    assert unchecked == []


def test_crossref_not_knowing_a_doi_is_no_answer_when_openalex_failed(services):
    services["openalex_down"] = True
    records, unchecked = fetch_metadata(["10.1234/none"], make_args())
    assert records == {}
    assert unchecked == ["10.1234/none"]


def test_answers_are_cached_and_failures_are_not(tmp_path, services):
    cache = Cache(tmp_path / "c.sqlite3")
    fetch_metadata(["10.1234/a", "10.1234/none"], make_args(), cache)
    services["calls"].clear()
    records, _ = fetch_metadata(["10.1234/a", "10.1234/none"], make_args(), cache)
    assert services["calls"] == []
    assert records["10.1234/a"]["title"] == "Paper A"
    assert records["10.1234/none"] is None

    services["openalex_down"] = services["crossref_down"] = True
    fetch_metadata(["10.1234/later"], make_args(), cache)
    services["openalex_down"] = services["crossref_down"] = False
    services["openalex"]["10.1234/later"] = {**WORK, "doi": "https://doi.org/10.1234/later"}
    services["calls"].clear()
    records, unchecked = fetch_metadata(["10.1234/later"], make_args(), cache)
    assert services["calls"]
    assert records["10.1234/later"]["title"] == "Paper A"
    assert unchecked == []
