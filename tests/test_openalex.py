import argparse

import pytest
import requests

from alcedo_lit.net import SESSION
from alcedo_lit.sources.openalex import search_openalex, to_openalex_query
from helpers import FakeResponse


@pytest.mark.parametrize("query, expected", [
    ("-foo bar", "NOT foo bar"),
    ('a -"b c"', 'a NOT "b c"'),
    ("mussel-inspired x", "mussel-inspired x"),
    ("Ti-6Al-4V porosity", "Ti-6Al-4V porosity"),
    ("intitle:nacre toughness", "nacre toughness"),
])
def test_query_translation(query, expected):
    assert to_openalex_query(query) == expected


def make_args(**overrides):
    return argparse.Namespace(**{**{"pages": 5, "openalex_key": None, "mailto": None, "http_timeout": 5}, **overrides})


def test_search_asks_for_works_with_doi_and_returns_records(monkeypatch):
    seen = {}

    def fake_get(url, params, **_):
        seen.update(params)
        return FakeResponse(data={"results": [{"doi": "https://doi.org/10.1234/a", "title": "A"}]})

    monkeypatch.setattr(SESSION, "get", fake_get)
    records, error = search_openalex("nacre -dental", make_args(openalex_key="KEY"))
    assert error is None
    assert records == [{"title": "A", "doi": "10.1234/a"}]
    assert seen["search"] == "nacre NOT dental"
    assert seen["per-page"] == 50
    assert seen["filter"].startswith("has_doi:true,type:")
    assert seen["api_key"] == "KEY"


def test_sici_doi_from_openalex_stays_whole(monkeypatch):
    sici = "10.1002/(sici)1097-0126(199801)45:1<118::aid-pi908>3.0.co;2-t"
    response = FakeResponse(data={"results": [{"doi": f"https://doi.org/{sici}", "title": "Old paper"}]})
    monkeypatch.setattr(SESSION, "get", lambda *a, **k: response)
    records, _ = search_openalex("q", make_args())
    assert records[0]["doi"] == sici


def test_429_is_retried_then_points_to_the_api_key(monkeypatch):
    attempts = []
    monkeypatch.setattr(SESSION, "get", lambda *a, **k: attempts.append(1) or FakeResponse(status_code=429))
    records, error = search_openalex("q", make_args())
    assert len(attempts) == 3
    assert records == []
    assert "--openalex-key" in error


def test_other_client_errors_are_not_retried(monkeypatch):
    attempts = []
    monkeypatch.setattr(SESSION, "get", lambda *a, **k: attempts.append(1) or FakeResponse(status_code=400))
    assert search_openalex("nacre*", make_args()) == ([], "HTTP 400")
    assert len(attempts) == 1


def test_network_error_is_reported(monkeypatch):
    def fail(*_, **__):
        raise requests.ConnectionError("no route")

    monkeypatch.setattr(SESSION, "get", fail)
    records, error = search_openalex("q", make_args())
    assert records == []
    assert "ConnectionError" in error
