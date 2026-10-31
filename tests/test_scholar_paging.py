"""Page handling of direct Scholar access, through a real worker process and a real pipe."""

import argparse

import pytest

from alcedo_lit.sources import scholar
from scholar_fakes import fake_worker


def run_query(monkeypatch, query, pages=5, page_timeout=3):
    monkeypatch.setattr(scholar, "_search_worker", fake_worker)
    monkeypatch.setattr(scholar, "PAGE_DELAY", 0.01)
    seen_pages = []
    args = argparse.Namespace(pages=pages, proxy=None, page_timeout=page_timeout)
    records, error = scholar.search_scholar(query, args, on_page=seen_pages.append)
    return records, error, seen_pages


@pytest.mark.parametrize("query, count, pages_seen", [
    ("few23", 23, [1, 2]),
    ("many200", 50, [1, 2, 3, 4]),
    ("exact10", 10, [1]),
    ("zero", 0, []),
])
def test_takes_up_to_five_pages_or_all_there_are(monkeypatch, query, count, pages_seen):
    records, error, seen = run_query(monkeypatch, query)
    assert error is None
    assert len(records) == count
    assert seen == pages_seen


def test_pages_option_limits_results(monkeypatch):
    records, error, _ = run_query(monkeypatch, "many200", pages=1)
    assert error is None
    assert len(records) == 10


def test_refusal_on_page_three_keeps_earlier_results(monkeypatch):
    records, error, _ = run_query(monkeypatch, "ban_on_page3")
    assert len(records) == 25
    assert "Cannot Fetch" in error


def test_hang_is_cut_off_by_the_timeout(monkeypatch):
    records, error, _ = run_query(monkeypatch, "hang_on_page2", page_timeout=1)
    assert len(records) == 10
    assert "did not answer" in error
