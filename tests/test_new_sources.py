import argparse

import pytest
import requests

from alcedo_lit.net import SESSION
from alcedo_lit.sources.semantic_scholar import SEMANTIC_SCHOLAR_URL, search_semantic_scholar, to_semantic_scholar_query
from alcedo_lit.sources.serper import SERPER_URL, search_serper
from helpers import FakeResponse

# ------------------------------- Serper -------------------------------


def serper_args(pages=5):
    return argparse.Namespace(pages=pages, serper_key="KEY", page_timeout=60)


def fake_serper(total, calls, fail_after=None):
    """A fake Serper with `total` results in pages of 10. After `fail_after` requests it answers with an error."""

    def fake_post(url, json=None, headers=None, **_):
        assert url == SERPER_URL
        assert headers["X-API-KEY"] == "KEY"
        assert "KEY" not in str(json)
        page = json.get("page", 1)
        calls.append(page)
        if fail_after and len(calls) > fail_after[0]:
            return FakeResponse(status_code=fail_after[1], data={"message": fail_after[2], "statusCode": fail_after[1]})
        start = (page - 1) * 10
        organic = [{"title": f"T{i}", "link": f"https://doi.org/10.5555/x.{i}", "pdfUrl": f"https://x.org/{i}.pdf",
                    "publicationInfo": "A", "year": 2020, "citedBy": 1} for i in range(start, min(start + 10, total))]
        return FakeResponse(data={"organic": organic})

    return fake_post


@pytest.mark.parametrize("total, count, pages", [
    (200, 50, [1, 2, 3, 4, 5]),
    (23, 23, [1, 2, 3, 4]),  # a request past the end costs one query, but a short page does not always mean the end
    (0, 0, [1]),
])
def test_serper_paging(monkeypatch, total, count, pages):
    calls = []
    monkeypatch.setattr(SESSION, "post", fake_serper(total, calls))
    pubs, error, stop = search_serper("q", serper_args())
    assert (len(pubs), error, stop) == (count, None, False)
    assert calls == pages


def test_serper_stops_when_a_page_only_repeats(monkeypatch):
    calls = []

    def same_page(url, json=None, **_):
        calls.append(json["page"])
        return FakeResponse(data={"organic": [{"title": "T", "link": "https://x.org/1"}]})

    monkeypatch.setattr(SESSION, "post", same_page)
    pubs, error, _ = search_serper("q", serper_args())
    assert (len(pubs), error, calls) == (1, None, [1, 2])


def test_serper_gives_an_empty_page_after_a_full_one_a_second_try(monkeypatch):
    calls = []
    answers = {1: [10], 2: [10], 3: [0, 10], 4: [10], 5: [10]}

    def flaky(url, json=None, **_):
        page = json["page"]
        calls.append(page)
        count = answers[page].pop(0)
        organic = [{"title": f"T{page}.{i}", "link": "https://x.org/1"} for i in range(count)]
        return FakeResponse(data={"organic": organic})

    monkeypatch.setattr(SESSION, "post", flaky)
    pubs, error, _ = search_serper("q", serper_args())
    assert (len(pubs), error) == (50, None)
    assert calls == [1, 2, 3, 3, 4, 5]


def test_serper_stops_when_the_page_stays_empty(monkeypatch):
    calls = []
    monkeypatch.setattr(SESSION, "post", fake_serper(20, calls))
    pubs, error, _ = search_serper("q", serper_args())
    assert (len(pubs), error) == (20, None)
    assert calls == [1, 2, 3, 3]  # one extra query, only when a full page is followed by an empty one


def test_serper_record_fields(monkeypatch):
    monkeypatch.setattr(SESSION, "post", fake_serper(1, []))
    pubs, _, _ = search_serper("q", serper_args())
    assert pubs[0] == {"title": "T0", "pub_url": "https://doi.org/10.5555/x.0", "eprint_url": "https://x.org/0.pdf"}


@pytest.mark.parametrize("status, message, stop", [
    (403, "Unauthorized.", True),  # what the real service answers to an invalid key
    (400, "Not enough credits", True),
    (500, "Server error", False),
])
def test_serper_errors_keep_results(monkeypatch, status, message, stop):
    monkeypatch.setattr(SESSION, "post", fake_serper(200, [], fail_after=(1, status, message)))
    pubs, error, stop_using = search_serper("q", serper_args())
    assert (len(pubs), error, stop_using) == (10, message, stop)


def test_serper_network_error(monkeypatch):
    def fail(*_, **__):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(SESSION, "post", fail)
    pubs, error, stop = search_serper("q", serper_args())
    assert (pubs, stop) == ([], False)
    assert "ConnectionError" in error


# ------------------------------- Semantic Scholar -------------------------------


def s2_args(key=None, pages=5):
    return argparse.Namespace(pages=pages, semantic_scholar_key=key, mailto=None, http_timeout=5)


@pytest.mark.parametrize("query, expected", [
    ('"Alcedo atthis" kingfisher (foraging OR diet)', '"Alcedo atthis" kingfisher (foraging | diet)'),
    ('"bread OR butter" a OR b', '"bread OR butter" a | b'),
    ("a -b", "a -b"),
    ("Ti-6Al-4V ORCID", "Ti-6Al-4V ORCID"),
    ("intitle:nacre author:smith toughness", "nacre smith toughness"),
])
def test_semantic_scholar_query_translation(query, expected):
    assert to_semantic_scholar_query(query) == expected


def test_semantic_scholar_records_and_request(monkeypatch):
    seen = {}

    def fake_get(url, params=None, headers=None, **_):
        seen.update(url=url, params=params, headers=headers)
        return FakeResponse(data={"total": 2, "data": [
            {"title": "A", "externalIds": {"DOI": "10.1234/a"}},
            {"title": "B", "externalIds": {"MAG": "5"}},
            {"title": None, "externalIds": None},
        ]})

    monkeypatch.setattr(SESSION, "get", fake_get)
    records, error, stop = search_semantic_scholar("x OR y", s2_args(key="KEY"))
    assert (error, stop) == (None, False)
    assert records == [{"title": "A", "doi": "10.1234/a"}, {"title": "B", "doi": None}, {"title": "", "doi": None}]
    assert seen["url"] == SEMANTIC_SCHOLAR_URL
    assert seen["params"]["query"] == "x | y"
    assert seen["params"]["sort"] == "citationCount:desc"
    assert seen["headers"]["x-api-key"] == "KEY"


def test_semantic_scholar_without_a_key_sends_none(monkeypatch):
    def fake_get(url, params=None, headers=None, **_):
        assert "x-api-key" not in headers
        return FakeResponse(data={"total": 0, "data": None})

    monkeypatch.setattr(SESSION, "get", fake_get)
    assert search_semantic_scholar("x", s2_args()) == ([], None, False)


def test_semantic_scholar_takes_only_the_limit(monkeypatch):
    papers = [{"title": str(i), "externalIds": {}} for i in range(1000)]
    monkeypatch.setattr(SESSION, "get", lambda *a, **k: FakeResponse(data={"data": papers}))
    records, _, _ = search_semantic_scholar("x", s2_args(pages=2))
    assert len(records) == 20


def test_semantic_scholar_retries_a_refusal_then_answers(monkeypatch):
    answers = iter([FakeResponse(status_code=429, data={}), FakeResponse(data={"data": [{"title": "A"}]})])
    monkeypatch.setattr(SESSION, "get", lambda *a, **k: next(answers))
    records, error, _ = search_semantic_scholar("x", s2_args())
    assert (len(records), error) == (1, None)


def test_semantic_scholar_keeps_refusing(monkeypatch):
    calls = []

    def refuse(*_, **__):
        calls.append(1)
        return FakeResponse(status_code=429, data={})

    monkeypatch.setattr(SESSION, "get", refuse)
    records, error, stop = search_semantic_scholar("x", s2_args())
    assert (records, stop, len(calls)) == ([], False, 3)
    assert "free API key" in error


def test_semantic_scholar_403_without_a_key_is_retried_and_does_not_turn_it_off(monkeypatch):
    calls = []

    def forbid(*_, **__):
        calls.append(1)
        return FakeResponse(status_code=403, data={"message": "Forbidden"})

    monkeypatch.setattr(SESSION, "get", forbid)
    records, error, stop = search_semantic_scholar("x", s2_args())
    assert (records, stop, len(calls)) == ([], False, 3)
    assert "free API key" in error


def test_semantic_scholar_bad_key_stops_it_without_retrying(monkeypatch):
    calls = []

    def forbid(*_, **__):
        calls.append(1)
        return FakeResponse(status_code=403, data={"message": "Forbidden"})

    monkeypatch.setattr(SESSION, "get", forbid)
    _, error, stop = search_semantic_scholar("x", s2_args(key="BAD"))
    assert (error, stop, len(calls)) == ("HTTP 403", True, 1)
