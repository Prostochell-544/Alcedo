import argparse

import pytest
import requests

from alcedo_lit.net import SESSION
from alcedo_lit.sources import searchapi
from helpers import FakeResponse


def scholar_api(total, calls, status_after=None):
    """A fake SearchApi with `total` results. After `status_after` requests it answers with an error."""

    def fake_get(url, params=None, headers=None, **_):
        assert url == searchapi.SEARCHAPI_URL
        assert params["engine"] == "google_scholar"
        assert params["num"] == 20
        assert "api_key" not in params
        assert headers["Authorization"] == "Bearer KEY"
        page = params["page"]
        calls.append(page)
        if status_after and len(calls) > status_after[0]:
            return FakeResponse(status_code=status_after[1], data={"error": "Out of credits"})
        start = (page - 1) * 20
        results = [{"title": f"T{i}", "link": f"https://doi.org/10.5555/x.{i}",
                    "resource": {"format": "PDF", "link": f"https://x.org/{i}.pdf"}}
                   for i in range(start, min(start + 20, total))]
        pagination = {"current": page, "next": "https://..."} if start + 20 < total else {"current": page}
        return FakeResponse(data={"organic_results": results, "pagination": pagination})

    return fake_get


def make_args(pages=5):
    return argparse.Namespace(pages=pages, searchapi_key="KEY", page_timeout=60)


@pytest.mark.parametrize("total, count, requests_made", [
    (47, 47, [1, 2, 3]),
    (200, 50, [1, 2, 3]),
    (0, 0, [1]),
    (20, 20, [1]),  # no link to a next page, so no request is wasted
])
def test_paging_and_quota_use(monkeypatch, total, count, requests_made):
    calls = []
    monkeypatch.setattr(SESSION, "get", scholar_api(total, calls))
    pubs, error, stop = searchapi.search_searchapi("q", make_args())
    assert (len(pubs), error, stop) == (count, None, False)
    assert calls == requests_made


def test_pdf_link_comes_from_resource(monkeypatch):
    monkeypatch.setattr(SESSION, "get", scholar_api(1, []))
    pubs, _, _ = searchapi.search_searchapi("q", make_args())
    assert pubs[0] == {"title": "T0", "pub_url": "https://doi.org/10.5555/x.0", "eprint_url": "https://x.org/0.pdf"}


@pytest.mark.parametrize("status, stop", [(429, True), (401, True), (402, True), (500, False)])
def test_key_and_quota_errors_stop_the_api_but_keep_results(monkeypatch, status, stop):
    monkeypatch.setattr(SESSION, "get", scholar_api(200, [], status_after=(1, status)))
    pubs, error, stop_using = searchapi.search_searchapi("q", make_args())
    assert len(pubs) == 20
    assert error == "Out of credits"
    assert stop_using is stop


def test_network_error_is_not_treated_as_the_limit(monkeypatch):
    def fail(*_, **__):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(SESSION, "get", fail)
    pubs, error, stop_using = searchapi.search_searchapi("q", make_args())
    assert (pubs, stop_using) == ([], False)
    assert "ConnectionError" in error
