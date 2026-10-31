import argparse

import pytest

from alcedo_lit.net import SESSION
from alcedo_lit.sources import serpapi
from helpers import FakeResponse


def scholar_api(totals, calls, quota_after=None):
    """A fake SerpApi with `totals[query]` results. It answers 429 after `quota_after` searches."""

    def fake_get(url, params=None, **_):
        assert url == serpapi.SERPAPI_URL
        assert params["engine"] == "google_scholar"
        assert 1 <= params["num"] <= 20
        query, start, num = params["q"], params["start"], params["num"]
        calls.append((start, num))
        if quota_after is not None and len(calls) > quota_after:
            return FakeResponse(status_code=429, data={"error": "Your account has run out of searches."})
        total = totals[query]
        if start >= total:
            return FakeResponse(data={"error": "Google hasn't returned any results for this query."})
        results = [{"title": f"{query} {i}", "link": f"https://doi.org/10.5555/{query}.{i}",
                    "resources": [{"file_format": "PDF", "link": f"https://x.org/{i}.pdf"}]}
                   for i in range(start, min(start + num, total))]
        pagination = {"current": start // 10 + 1}
        if start + num < total:
            pagination["next"] = "https://serpapi.com/search.json?start=..."
        return FakeResponse(data={"organic_results": results, "serpapi_pagination": pagination})

    return fake_get


def make_args(pages=5):
    return argparse.Namespace(pages=pages, serpapi_key="KEY", page_timeout=60)


@pytest.mark.parametrize("total, count, expected_calls", [
    (47, 47, [(0, 20), (20, 20), (40, 10)]),
    (200, 50, [(0, 20), (20, 20), (40, 10)]),
    (0, 0, [(0, 20)]),
    (20, 20, [(0, 20)]),  # no link to a next page, so no search is wasted
])
def test_paging_and_quota_use(monkeypatch, total, count, expected_calls):
    calls = []
    monkeypatch.setattr(SESSION, "get", scholar_api({"q": total}, calls))
    records, error, limit_hit = serpapi.search_serpapi("q", make_args())
    assert (len(records), error, limit_hit) == (count, None, False)
    assert calls == expected_calls


def test_two_pages_fit_in_one_search(monkeypatch):
    calls = []
    monkeypatch.setattr(SESSION, "get", scholar_api({"q": 200}, calls))
    records, _, _ = serpapi.search_serpapi("q", make_args(pages=2))
    assert len(records) == 20
    assert calls == [(0, 20)]


def test_pdf_link_comes_from_resources(monkeypatch):
    monkeypatch.setattr(SESSION, "get", scholar_api({"q": 1}, []))
    records, _, _ = serpapi.search_serpapi("q", make_args())
    assert records[0]["eprint_url"] == "https://x.org/0.pdf"


def test_quota_running_out_keeps_earlier_pages(monkeypatch):
    monkeypatch.setattr(SESSION, "get", scholar_api({"q": 200}, [], quota_after=1))
    records, error, limit_hit = serpapi.search_serpapi("q", make_args())
    assert len(records) == 20
    assert "run out of searches" in error
    assert limit_hit is True


def test_other_errors_are_not_treated_as_the_limit(monkeypatch):
    monkeypatch.setattr(SESSION, "get", lambda *a, **k: FakeResponse(status_code=500, data={"error": "boom"}))
    assert serpapi.search_serpapi("q", make_args()) == ([], "boom", False)


def test_account_check_raises_on_invalid_key(monkeypatch):
    response = FakeResponse(status_code=401, data={"error": "Invalid API key."})
    monkeypatch.setattr(SESSION, "get", lambda *a, **k: response)
    with pytest.raises(RuntimeError, match="Invalid API key"):
        serpapi.serpapi_account("WRONG", 5)
