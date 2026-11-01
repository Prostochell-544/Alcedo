"""Source selection, fallback, resume and secret handling, from the command line entry point down."""

import pytest
import requests

from alcedo_lit import cli, pipeline
from alcedo_lit.net import SESSION
from alcedo_lit.sources import openalex, scholar, serpapi
from helpers import FakeResponse, blocks_of, dois_in, pubs

Q_FULL, Q_PARTIAL, Q_DEAD, Q_AFTER, Q_LAST = "q1 full", "q2 partial", "q3 dead", "q4 after", "q5 last"


@pytest.fixture
def project(tmp_path, monkeypatch):
    """A temporary project with fake sources that record their calls."""
    (tmp_path / "queries.txt").write_text(";".join((Q_FULL, Q_PARTIAL, Q_DEAD, Q_AFTER, Q_LAST)), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    state = {"scholar": [], "openalex": [], "pauses": 0, "openalex_broken": set()}

    def fake_scholar(query, args, on_page=None):
        state["scholar"].append(query)
        if query == Q_FULL:
            return pubs("sch", range(1, 13)), None
        if query == Q_PARTIAL:
            return pubs("q2", range(1, 21)), "MaxTriesExceededException: Cannot Fetch"
        return [], "Scholar timeout"

    def fake_openalex(query, args):
        state["openalex"].append(query)
        if query in state["openalex_broken"]:
            return [], "HTTP 429"
        # 60 works; for q2 the numbers 16-20 repeat DOIs already found through Scholar.
        return pubs(query.split()[0], range(16, 76)), None

    def fake_pause(args, bar):
        state["pauses"] += 1

    monkeypatch.setattr(scholar, "search_scholar", fake_scholar)
    monkeypatch.setattr(scholar, "load_scholarly", lambda proxy: object())
    monkeypatch.setattr(openalex, "search_openalex", fake_openalex)
    monkeypatch.setattr(pipeline, "pause_before_scholar", fake_pause)
    state["results"] = tmp_path / "alcedo_results.txt"
    return state


def alcedo(*args):
    return cli.main(["--no-page-meta", "--no-title-search", "--no-semantic-scholar", *args])


def test_default_without_keys_uses_openalex_and_never_touches_scholar(project):
    assert alcedo() == 0
    assert project["scholar"] == []
    blocks = blocks_of(project["results"])
    assert all(lines[0] == "Source: OpenAlex" and len(dois_in(lines)) == 50 for lines in blocks.values())


def test_source_scholar_without_a_backend_is_refused(project):
    assert alcedo("--source", "scholar") == 2
    assert project["scholar"] == []


def test_direct_scholar_warns_and_adds_to_openalex(project, capsys):
    assert alcedo("--direct-scholar") == 0
    assert "robots.txt" in capsys.readouterr().err
    assert project["scholar"] == [Q_FULL, Q_PARTIAL, Q_DEAD]  # off after 2 failures in a row
    assert project["openalex"] == [Q_FULL, Q_PARTIAL, Q_DEAD, Q_AFTER, Q_LAST]
    assert project["pauses"] == 2

    blocks = blocks_of(project["results"])
    assert "OpenAlex (50) + Google Scholar (direct) (12 new of 12)" in blocks[Q_FULL][0]
    assert "the direct list may be incomplete" in blocks[Q_FULL][0]
    assert len(dois_in(blocks[Q_FULL])) == 62
    assert "/q1." in blocks[Q_FULL][1]  # OpenAlex comes first

    # Direct search failed after 20 results. Those it found stay, and 16-20 are already in OpenAlex.
    partial = blocks[Q_PARTIAL]
    assert "OpenAlex (50) + Google Scholar (direct) (15 new of 20)" in partial[0]
    assert "Google Scholar unavailable" in partial[0]
    assert len(dois_in(partial)) == len(set(dois_in(partial))) == 65

    assert blocks[Q_DEAD][0].startswith("Source: OpenAlex (50) - ")
    assert "Google Scholar unavailable" in blocks[Q_DEAD][0]
    assert "Google Scholar off (failures in a row: 2)" in blocks[Q_AFTER][0]


def test_both_sources_failing_leaves_an_error_line_and_resume_retries_only_it(project):
    project["openalex_broken"].add(Q_LAST)
    assert alcedo("--direct-scholar") == 0
    assert any(line.startswith("Query error") for line in blocks_of(project["results"])[Q_LAST])

    project["openalex_broken"].clear()
    project["scholar"].clear()
    project["openalex"].clear()
    assert alcedo("--direct-scholar", "--resume") == 0
    assert project["scholar"] == [Q_LAST]
    assert project["openalex"] == [Q_LAST]
    assert len(dois_in(blocks_of(project["results"])[Q_LAST])) == 50


def test_source_scholar_stops_after_failures_and_never_uses_openalex(project):
    assert alcedo("--direct-scholar", "--source", "scholar") == 0
    assert project["openalex"] == []
    blocks = blocks_of(project["results"])
    assert list(blocks) == [Q_FULL, Q_PARTIAL, Q_DEAD]
    assert "may be incomplete" in blocks[Q_FULL][0]
    assert len(dois_in(blocks[Q_FULL])) == 12
    assert len(dois_in(blocks[Q_PARTIAL])) == 20
    assert any("remaining pages not collected" in line for line in blocks[Q_PARTIAL])


def test_source_openalex_ignores_a_serpapi_key(project, monkeypatch):
    monkeypatch.setattr(SESSION, "get", lambda *a, **k: pytest.fail("SerpApi must not be contacted"))
    assert alcedo("--source", "openalex", "--serpapi-key", "KEY") == 0
    assert project["scholar"] == []


# ------------------------------- SerpApi -------------------------------

ACCOUNT_OK = {"total_searches_left": 240, "account_rate_limit_per_hour": 50, "this_hour_searches": 3}


@pytest.fixture
def serp(project, monkeypatch):
    """Serve the account check and a fake search: 33 results each, out of quota after `quota_after` searches."""
    project.update(account=dict(ACCOUNT_OK), serp=[], quota_after=None)

    def fake_search(query, args, on_page=None):
        project["serp"].append(query)
        if project["quota_after"] is not None and len(project["serp"]) > project["quota_after"]:
            return pubs("serp" + query[1], range(1, 21)), "Your account has run out of searches.", True
        return pubs("serp" + query[1], range(1, 34)), None, False

    monkeypatch.setattr(serpapi, "search_serpapi", fake_search)
    monkeypatch.setattr(serpapi, "serpapi_account", lambda key, timeout: project["account"])
    return project


def test_serpapi_key_replaces_scholarly_and_needs_no_pauses(serp, monkeypatch):
    monkeypatch.setattr(scholar, "load_scholarly", lambda proxy: pytest.fail("scholarly must not be used"))
    assert alcedo("--serpapi-key", "KEY") == 0
    assert serp["scholar"] == []
    assert serp["pauses"] == 0
    assert all(len(dois_in(lines)) == 33 for lines in blocks_of(serp["results"]).values())


def test_quota_running_out_tops_up_from_openalex_and_stops_searching(serp):
    serp["quota_after"] = 1
    assert alcedo("--serpapi-key", "KEY") == 0
    assert serp["serp"] == [Q_FULL, Q_PARTIAL]
    blocks = blocks_of(serp["results"])
    assert "(20) + OpenAlex (30)" in blocks[Q_PARTIAL][0]
    assert "run out of searches" in blocks[Q_PARTIAL][0]
    assert "SerpApi off (Your account has run out of searches.)" in blocks[Q_DEAD][0]


def test_redo_openalex_collects_those_blocks_through_serpapi(serp):
    serp["quota_after"] = 1
    alcedo("--serpapi-key", "KEY")
    serp["quota_after"] = None
    serp["serp"].clear()
    assert alcedo("--serpapi-key", "KEY", "--redo-openalex") == 0
    assert serp["serp"] == [Q_PARTIAL, Q_DEAD, Q_AFTER, Q_LAST]
    assert "Source:" not in serp["results"].read_text(encoding="utf-8")


def test_empty_quota_at_start_spends_no_searches(serp):
    serp["account"]["total_searches_left"] = 0
    assert alcedo("--serpapi-key", "KEY") == 0
    assert serp["serp"] == []
    assert serp["results"].read_text(encoding="utf-8").count("SerpApi off (limit reached)") == 5


def test_empty_quota_with_source_scholar_stops(serp):
    serp["account"]["total_searches_left"] = 0
    assert alcedo("--serpapi-key", "KEY", "--source", "scholar") == 1


def test_invalid_key_stops_before_collecting(project, monkeypatch, capsys):
    response = FakeResponse(status_code=401, data={"error": "Invalid API key."})
    monkeypatch.setattr(SESSION, "get", lambda *a, **k: response)
    assert alcedo("--serpapi-key", "WRONG") == 1
    assert "Invalid API key" in capsys.readouterr().err
    assert not project["results"].exists()


def test_network_error_does_not_leak_the_key(project, monkeypatch, capsys):
    def fake_get(url, **_):
        if url == serpapi.SERPAPI_ACCOUNT_URL:
            return FakeResponse(data=ACCOUNT_OK)
        raise requests.ConnectionError("Max retries exceeded with url: /search.json?q=x&api_key=SECRET123")

    monkeypatch.setattr(SESSION, "get", fake_get)
    assert alcedo("--serpapi-key", "SECRET123") == 0
    captured = capsys.readouterr()
    assert "SECRET123" not in project["results"].read_text(encoding="utf-8")
    assert "SECRET123" not in captured.out + captured.err
    assert "***" in project["results"].read_text(encoding="utf-8")


def test_serpapi_key_is_read_from_the_environment(serp, monkeypatch):
    monkeypatch.setenv("SERPAPI_KEY", "FROM_ENV")
    assert alcedo() == 0
    assert len(serp["serp"]) == 5


# --------------------------- Protecting results ---------------------------

def test_existing_results_are_not_replaced_by_accident(project, capsys):
    project["results"].write_text("=== Query: old ===\nhttps://doi.org/10.1234/old\n\n", encoding="utf-8")
    assert alcedo() == 1
    assert "--overwrite" in capsys.readouterr().err
    assert project["openalex"] == []
    assert "10.1234/old" in project["results"].read_text(encoding="utf-8")


def test_overwrite_replaces_results_and_collects_again(project):
    project["results"].write_text(f"=== Query: {Q_FULL} ===\nhttps://doi.org/10.1234/old\n\n", encoding="utf-8")
    assert alcedo("--overwrite", "--resume") == 0
    assert len(project["openalex"]) == 5
    assert "10.1234/old" not in project["results"].read_text(encoding="utf-8")


def test_resume_refuses_a_file_without_alcedo_blocks(project, capsys):
    old = "=== Запрос: старый формат ===\nhttps://doi.org/10.1234/old\n\n"
    project["results"].write_text(old, encoding="utf-8")
    assert alcedo("--resume") == 1
    assert "no Alcedo results" in capsys.readouterr().err
    assert project["results"].read_text(encoding="utf-8") == old


def test_failed_lookups_are_reported_in_the_summary(project, monkeypatch, capsys):
    def no_network(*_, **__):
        raise requests.ConnectionError("down")

    monkeypatch.setattr(openalex, "search_openalex", lambda query, args: ([{"title": query}], None))
    monkeypatch.setattr(SESSION, "get", no_network)
    assert cli.main(["--no-page-meta", "--no-semantic-scholar"]) == 0
    assert "Failed DOI lookups (Crossref: 5, OpenAlex: 5)" in capsys.readouterr().out


# ------------------------------ Input checks ------------------------------

def test_missing_query_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    assert cli.main([]) == 1


def test_empty_query_file(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "queries.txt").write_text(" ; ;", encoding="utf-8")
    assert cli.main([]) == 1


def test_invalid_pages_is_a_usage_error():
    with pytest.raises(SystemExit):
        cli.parse_args(["--pages", "0"])
