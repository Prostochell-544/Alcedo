import argparse
import time

import pytest
import requests

from alcedo_lit import cli, resolve
from alcedo_lit.cache import DAY, MISS, Cache, cache_path
from alcedo_lit.net import SESSION
from alcedo_lit.sources import openalex
from helpers import FakeResponse


def test_values_survive_reopening(tmp_path):
    path = tmp_path / "c.sqlite3"
    Cache(path).set("kind", "key", {"a": ["б", None]})
    assert Cache(path).get("kind", "key", 1) == {"a": ["б", None]}


def test_a_stored_none_is_different_from_nothing(tmp_path):
    cache = Cache(tmp_path / "c.sqlite3")
    assert cache.get("kind", "key", 1) is MISS
    cache.set("kind", "key", None)
    assert cache.get("kind", "key", 1) is None


def test_old_values_are_ignored_and_kinds_are_separate(tmp_path, monkeypatch):
    cache = Cache(tmp_path / "c.sqlite3")
    cache.set("kind", "key", 1)
    assert cache.get("other", "key", 1) is MISS
    now = time.time()
    monkeypatch.setattr(time, "time", lambda: now + 2 * DAY)
    assert cache.get("kind", "key", 1) is MISS
    assert cache.get("kind", "key", 3) == 1


@pytest.mark.parametrize("make_bad", ["folder", "not a database"])
def test_a_broken_cache_does_not_stop_anything(tmp_path, capsys, make_bad):
    path = tmp_path / "c.sqlite3"
    if make_bad == "folder":
        path.mkdir()
    else:
        path.write_bytes(b"this is not sqlite" * 100)
    cache = Cache(path)
    cache.set("kind", "key", 1)
    assert cache.get("kind", "key", 1) is MISS
    assert "Working without a cache" in capsys.readouterr().err


def test_the_cache_folder_can_be_chosen(monkeypatch, tmp_path):
    monkeypatch.setenv("ALCEDO_CACHE_DIR", str(tmp_path))
    assert cache_path() == tmp_path / "alcedo" / "cache.sqlite3"


# ------------------------------- DOI lookups -------------------------------

PUB = {"title": "A long enough title for the comparison", "pub_url": "https://publisher.org/a", "eprint_url": None}


def lookup_args(tmp_path, **overrides):
    defaults = {"mailto": None, "openalex_key": None, "http_timeout": 5, "page_meta": True, "title_search": True,
                "cache": Cache(tmp_path / "c.sqlite3")}
    return argparse.Namespace(**{**defaults, **overrides})


@pytest.fixture
def requests_made(monkeypatch):
    log = []
    resolve.failed_lookups.clear()
    log_responses = {}

    def fake_get(url, **_):
        log.append(url)
        for prefix, response in log_responses.items():
            if url.startswith(prefix):
                if isinstance(response, Exception):
                    raise response
                return response
        return FakeResponse(data={"message": {"items": []}, "results": []},
                            headers={"Content-Type": "text/html"}, url="https://publisher.org/a")

    monkeypatch.setattr(SESSION, "get", fake_get)
    log_responses["https://publisher.org/a"] = FakeResponse(
        url="https://publisher.org/a", headers={"Content-Type": "text/html"},
        body=b'<meta name="citation_doi" content="10.1234/found">')
    return log, log_responses


def test_a_found_doi_is_not_looked_up_again(tmp_path, requests_made):
    log, _ = requests_made
    args = lookup_args(tmp_path)
    assert resolve.resolve_dois([PUB], args) == ["https://doi.org/10.1234/found"]
    made = len(log)
    assert made > 0
    assert resolve.resolve_dois([PUB], args) == ["https://doi.org/10.1234/found"]
    assert len(log) == made


def test_no_doi_is_remembered_after_every_lookup_answered(tmp_path, requests_made):
    log, responses = requests_made
    responses["https://publisher.org/a"] = FakeResponse(url="https://publisher.org/a",
                                                        headers={"Content-Type": "text/html"}, body=b"<html></html>")
    args = lookup_args(tmp_path)
    assert resolve.resolve_dois([PUB], args)[0].startswith("DOI not found")
    made = len(log)
    assert resolve.resolve_dois([PUB], args)[0].startswith("DOI not found")
    assert len(log) == made


def test_no_doi_is_not_remembered_after_a_failed_lookup(tmp_path, requests_made):
    log, responses = requests_made
    responses["https://publisher.org/a"] = requests.ConnectionError("down")
    args = lookup_args(tmp_path)
    assert resolve.resolve_dois([PUB], args)[0].startswith("DOI not found")
    made = len(log)
    assert resolve.resolve_dois([PUB], args)[0].startswith("DOI not found")
    assert len(log) > made


def test_no_doi_is_not_remembered_when_lookups_were_turned_off(tmp_path, requests_made):
    log, responses = requests_made
    args = lookup_args(tmp_path, page_meta=False, title_search=False)
    assert resolve.resolve_dois([PUB], args)[0].startswith("DOI not found")
    assert log == []
    assert resolve.resolve_dois([PUB], lookup_args(tmp_path)) == ["https://doi.org/10.1234/found"]


def test_a_new_version_does_not_reuse_old_answers(tmp_path, requests_made, monkeypatch):
    log, _ = requests_made
    args = lookup_args(tmp_path)
    resolve.resolve_dois([PUB], args)
    made = len(log)
    monkeypatch.setattr(resolve, "DOI_CACHE_KIND", "doi-next-version")
    resolve.resolve_dois([PUB], args)
    assert len(log) > made


def test_a_record_that_came_with_a_doi_is_not_stored(tmp_path, requests_made):
    args = lookup_args(tmp_path)
    assert resolve.resolve_dois([{"title": "T", "doi": "10.1234/given"}], args) == ["https://doi.org/10.1234/given"]
    assert args.cache.db.execute("SELECT COUNT(*) FROM entries").fetchone()[0] == 0


# ------------------------------- Through the command line -------------------------------

def run_cli(tmp_path, monkeypatch, *flags):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "queries.txt").write_text("nacre toughness;", encoding="utf-8")
    monkeypatch.setattr(openalex, "search_openalex", lambda q, a: ([dict(PUB)], None))
    return cli.main(["--no-semantic-scholar", "--no-direct-scholar", "--overwrite", *flags])


def test_a_second_run_reuses_lookups_and_no_cache_does_not(tmp_path, monkeypatch, requests_made):
    log, _ = requests_made
    assert run_cli(tmp_path, monkeypatch) == 0
    made = len(log)
    assert made > 0
    assert run_cli(tmp_path, monkeypatch) == 0
    assert len(log) == made
    assert run_cli(tmp_path, monkeypatch, "--no-cache") == 0
    assert len(log) > made
