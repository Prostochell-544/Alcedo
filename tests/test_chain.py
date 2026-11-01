"""The order of sources, what is said to the user, and how the user's keys and choice are kept."""

import builtins
import getpass
import os
import sys

import pytest

from alcedo_lit import cli, config, pipeline, setup_wizard
from alcedo_lit.sources import openalex, scholar, searchapi, semantic_scholar, serpapi, serper
from helpers import blocks_of, dois_in, pubs

QUERIES = ("q1 one", "q2 two", "q3 three")


@pytest.fixture
def world(tmp_path, monkeypatch):
    """Fake sources. `direct_results` sets how many results direct Scholar returns."""
    (tmp_path / "queries.txt").write_text(";".join(QUERIES), encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    state = {"api": [], "direct": [], "openalex": [], "api_quota": None, "direct_results": 50, "direct_error": None,
             "results": tmp_path / "alcedo_results.txt"}

    def fake_api(query, args, on_page=None):
        state["api"].append(query)
        if state["api_quota"] is not None and len(state["api"]) > state["api_quota"]:
            return [], "Out of credits", True
        return pubs("api" + query[1], range(1, 51)), None, False

    def fake_direct(query, args, on_page=None):
        state["direct"].append(query)
        return pubs("dir" + query[1], range(1, state["direct_results"] + 1)), state["direct_error"]

    def fake_openalex(query, args):
        state["openalex"].append(query)
        return pubs("oa" + query[1], range(1, 61)), None

    monkeypatch.setattr(searchapi, "search_searchapi", fake_api)
    monkeypatch.setattr(scholar, "search_scholar", fake_direct)
    monkeypatch.setattr(scholar, "load_scholarly", lambda proxy: object())
    monkeypatch.setattr(openalex, "search_openalex", fake_openalex)
    monkeypatch.setattr(pipeline, "pause_before_scholar", lambda args, bar: None)
    return state


def alcedo(*args):
    return cli.main(["--no-page-meta", "--no-title-search", "--no-semantic-scholar", *args])


# ------------------------------- Semantic Scholar and Serper -------------------------------

@pytest.fixture
def semantic(world, monkeypatch):
    """A fake Semantic Scholar with 10 results of its own, and turning on the real position in the chain."""
    world.update(semantic=[], semantic_error=None, semantic_stop=False)

    def fake(query, args, on_page=None):
        world["semantic"].append(query)
        if world["semantic_error"]:
            return [], world["semantic_error"], world["semantic_stop"]
        return pubs("s2" + query[1], range(1, 11)), None, False

    monkeypatch.setattr(semantic_scholar, "search_semantic_scholar", fake)
    return world


def with_semantic(*args):
    return cli.main(["--no-page-meta", "--no-title-search", *args])


def test_semantic_scholar_comes_first_among_the_free_sources(semantic):
    assert with_semantic("--direct-scholar") == 0
    block = blocks_of(semantic["results"])["q1 one"]
    assert block[0].startswith("Source: Semantic Scholar (10) + OpenAlex (50) + Google Scholar (direct) (50 new of 50)")
    found = dois_in(block)
    assert len(found) == 110
    assert all("/s21." in doi for doi in found[:10])
    assert all("/oa1." in doi for doi in found[10:60])


def test_semantic_scholar_is_not_used_when_an_api_answers(semantic):
    assert with_semantic("--searchapi-key", "KEY") == 0
    assert semantic["semantic"] == []


def test_semantic_scholar_fails_and_the_block_stands_without_it(semantic):
    semantic["semantic_error"] = "HTTP 429 - shared limit reached"
    assert with_semantic() == 0
    assert semantic["semantic"] == ["q1 one", "q2 two"]  # off after 2 failures in a row
    blocks = blocks_of(semantic["results"])
    assert blocks["q1 one"][0].startswith("Source: OpenAlex (50) - Semantic Scholar unavailable: HTTP 429")
    assert "Semantic Scholar off (failures in a row: 2)" in blocks["q3 three"][0]
    assert len(dois_in(blocks["q1 one"])) == 50


def test_semantic_scholar_alone_is_enough_for_a_block(semantic, monkeypatch):
    monkeypatch.setattr(openalex, "search_openalex", lambda q, a: ([], "HTTP 429"))
    assert with_semantic() == 0
    block = blocks_of(semantic["results"])["q1 one"]
    assert block[0].startswith("Source: Semantic Scholar (10) - OpenAlex unavailable")
    assert len(dois_in(block)) == 10


def test_openalex_only_and_scholar_only_leave_semantic_scholar_out(semantic):
    assert with_semantic("--source", "openalex") == 0
    assert with_semantic("--source", "scholar", "--direct-scholar", "--overwrite") == 0
    assert semantic["semantic"] == []


def test_redo_collects_free_blocks_again_through_the_api(semantic):
    assert with_semantic() == 0
    assert with_semantic("--searchapi-key", "KEY", "--redo-openalex") == 0
    assert "Source:" not in semantic["results"].read_text(encoding="utf-8")


def test_serper_is_tried_after_searchapi_and_before_serpapi(world, monkeypatch):
    calls = []
    monkeypatch.setattr(searchapi, "search_searchapi", lambda *a, **k: (calls.append("searchapi") or [], "Out", True))
    monkeypatch.setattr(serper, "search_serper",
                        lambda *a, **k: (calls.append("serper") or pubs("x", [1, 2]), None, False))
    monkeypatch.setattr(serpapi, "serpapi_account", lambda key, timeout: {"total_searches_left": 100})
    monkeypatch.setattr(serpapi, "search_serpapi", lambda *a, **k: pytest.fail("SerpApi must wait its turn"))
    assert alcedo("--searchapi-key", "A", "--serper-key", "B", "--serpapi-key", "C") == 0
    assert calls == ["searchapi", "serper", "serper", "serper"]
    assert "Source:" not in world["results"].read_text(encoding="utf-8")


def test_a_serper_key_alone_is_enough_for_source_scholar(world, monkeypatch):
    monkeypatch.setattr(serper, "search_serper", lambda *a, **k: (pubs("x", [1, 2]), None, False))
    assert alcedo("--source", "scholar", "--serper-key", "KEY") == 0


def test_new_keys_are_hidden_in_errors(world, monkeypatch, capsys):
    monkeypatch.setattr(serper, "search_serper", lambda *a, **k: ([], "failed for SECRET-A", False))
    monkeypatch.setattr(semantic_scholar, "search_semantic_scholar", lambda *a, **k: ([], "failed for SECRET-B", False))
    assert with_semantic("--serper-key", "SECRET-A", "--semantic-scholar-key", "SECRET-B") == 0
    captured = capsys.readouterr()
    text = captured.out + captured.err + world["results"].read_text(encoding="utf-8")
    assert "SECRET-" not in text


# ------------------------------- Order -------------------------------

def test_api_comes_first_and_is_not_marked(world):
    assert alcedo("--searchapi-key", "KEY", "--direct-scholar") == 0
    assert world["api"] == list(QUERIES)
    assert world["direct"] == world["openalex"] == []
    assert "Source:" not in world["results"].read_text(encoding="utf-8")


def test_when_the_api_runs_out_both_free_sources_take_over(world):
    world["api_quota"] = 1
    assert alcedo("--searchapi-key", "KEY", "--direct-scholar") == 0
    assert world["api"] == ["q1 one", "q2 two"]  # the failed call turns the API off
    assert world["direct"] == world["openalex"] == ["q2 two", "q3 three"]
    blocks = blocks_of(world["results"])
    assert "Source:" not in "\n".join(blocks["q1 one"])
    assert blocks["q2 two"][0].startswith("Source: OpenAlex (50) + Google Scholar (direct) (50 new of 50)")
    assert "SearchApi unavailable: Out of credits" in blocks["q2 two"][0]
    assert "SearchApi off (Out of credits)" in blocks["q3 three"][0]


def test_results_from_an_api_that_ran_out_are_kept_and_come_first(world, monkeypatch):
    monkeypatch.setattr(searchapi, "search_searchapi",
                        lambda *a, **k: (pubs("api", range(1, 41)), "Out of credits", True))
    assert alcedo("--searchapi-key", "KEY", "--direct-scholar") == 0
    block = blocks_of(world["results"])["q1 one"]
    assert block[0].startswith("Source: Google Scholar (40) + OpenAlex (10) + Google Scholar (direct) (50 new of 50)")
    found = dois_in(block)
    assert len(found) == 100
    assert all("/api." in doi for doi in found[:40])
    assert all("/oa1." in doi for doi in found[40:50])
    assert all("/dir1." in doi for doi in found[50:])


def test_openalex_comes_first_and_direct_search_only_adds(world):
    world["direct_results"] = 6
    assert alcedo("--direct-scholar") == 0
    block = blocks_of(world["results"])["q1 one"]
    assert "OpenAlex (50) + Google Scholar (direct) (6 new of 6)" in block[0]
    assert "the direct list may be incomplete" in block[0]
    found = dois_in(block)
    assert len(found) == 56
    assert all("/oa1." in doi for doi in found[:50])
    assert all("/dir1." in doi for doi in found[50:])


def test_records_already_found_are_not_looked_up_or_repeated(world, monkeypatch):
    shared = pubs("oa1", range(1, 4))
    monkeypatch.setattr(scholar, "search_scholar", lambda q, a, on_page=None: (shared + pubs("dir", [9]), None))
    seen_by_resolver = []
    real_resolve = pipeline.resolve_dois

    def spy(records, args, source="Google Scholar"):
        seen_by_resolver.append((source, len(records)))
        return real_resolve(records, args, source=source)

    monkeypatch.setattr(pipeline, "resolve_dois", spy)
    assert alcedo("--direct-scholar") == 0
    assert ("Google Scholar", 1) in seen_by_resolver
    block = blocks_of(world["results"])["q1 one"]
    assert "(1 new of 4)" in block[0]
    assert len(dois_in(block)) == len(set(dois_in(block))) == 51


def test_when_direct_search_fails_only_openalex_is_used(world):
    world["direct_error"] = "Cannot Fetch"
    world["direct_results"] = 0
    assert alcedo("--direct-scholar") == 0
    block = blocks_of(world["results"])["q1 one"]
    assert block[0].startswith("Source: OpenAlex (50) - Google Scholar unavailable: Cannot Fetch")
    assert "(direct) (" not in block[0]
    assert all("/oa1." in doi for doi in dois_in(block))


def test_when_openalex_fails_only_direct_search_is_used(world, monkeypatch):
    monkeypatch.setattr(openalex, "search_openalex", lambda q, a: ([], "HTTP 429"))
    assert alcedo("--direct-scholar") == 0
    block = blocks_of(world["results"])["q1 one"]
    assert block[0].startswith("Source: Google Scholar (direct) (50 new of 50) - OpenAlex unavailable: HTTP 429")
    assert not any(line.startswith("Query error") for line in block)
    assert len(dois_in(block)) == 50


def test_when_both_free_sources_fail_the_block_is_an_error_and_resume_retries_it(world, monkeypatch):
    world["direct_error"] = "Cannot Fetch"
    world["direct_results"] = 0
    monkeypatch.setattr(openalex, "search_openalex", lambda q, a: ([], "HTTP 429"))
    assert alcedo("--direct-scholar") == 0
    block = blocks_of(world["results"])["q1 one"]
    assert block[0].startswith("Query error")
    assert "OpenAlex unavailable: HTTP 429" in block[0]
    assert "Google Scholar unavailable: Cannot Fetch" in block[0]

    monkeypatch.setattr(openalex, "search_openalex", lambda q, a: (pubs("oa", range(1, 4)), None))
    assert alcedo("--no-direct-scholar", "--resume") == 0
    assert len(dois_in(blocks_of(world["results"])["q1 one"])) == 3


def test_invalid_key_says_so_and_later_queries_skip_the_api(world, monkeypatch, capsys):
    calls = []

    def rejected(query, args, on_page=None):
        calls.append(query)
        return [], "Invalid API key.", True

    monkeypatch.setattr(searchapi, "search_searchapi", rejected)
    assert alcedo("--searchapi-key", "WRONG") == 0
    assert calls == ["q1 one"]
    assert "SearchApi off (Invalid API key.)" in capsys.readouterr().out
    assert "SearchApi off (Invalid API key.)" in blocks_of(world["results"])["q2 two"][0]


def test_when_every_scholar_source_fails_openalex_answers(world):
    world["direct_error"] = "Cannot Fetch"
    world["direct_results"] = 0
    assert alcedo("--direct-scholar") == 0
    assert world["direct"] == ["q1 one", "q2 two"]  # off after 2 failures in a row
    assert world["openalex"] == list(QUERIES)
    blocks = blocks_of(world["results"])
    assert "Google Scholar unavailable" in blocks["q1 one"][0]
    assert "Google Scholar off (failures in a row: 2)" in blocks["q3 three"][0]


def test_searchapi_is_tried_before_serpapi(world, monkeypatch):
    monkeypatch.setattr(serpapi, "serpapi_account", lambda key, timeout: {"total_searches_left": 100})
    monkeypatch.setattr(serpapi, "search_serpapi", lambda *a, **k: pytest.fail("SerpApi must wait its turn"))
    assert alcedo("--searchapi-key", "A", "--serpapi-key", "B") == 0
    assert len(world["api"]) == 3


# ------------------------------- Honest results -------------------------------

def test_full_direct_list_is_still_marked(world):
    assert alcedo("--direct-scholar") == 0
    block = blocks_of(world["results"])["q1 one"]
    assert block[0] == ("Source: OpenAlex (50) + Google Scholar (direct) (50 new of 50) - "
                        "the direct list may be incomplete")
    assert len(dois_in(block)) == 100


def test_short_direct_list_is_mentioned_in_the_console(world, capsys):
    world["direct_results"] = 6
    assert alcedo("--direct-scholar") == 0
    assert "returned only 6 of up to 50; the list may be incomplete" in capsys.readouterr().out


def test_direct_list_without_openalex_is_marked_and_stands_alone(world):
    world["direct_results"] = 6
    assert alcedo("--direct-scholar", "--source", "scholar") == 0
    block = blocks_of(world["results"])["q1 one"]
    assert block[0] == "Source: Google Scholar (direct) returned 6 of up to 50; the list may be incomplete"
    assert len(dois_in(block)) == 6
    assert world["openalex"] == []


def test_summary_says_how_many_queries_used_direct_search(world, capsys):
    assert alcedo("--direct-scholar") == 0
    assert "3 queries used direct Google Scholar search" in capsys.readouterr().out


def test_redo_collects_direct_blocks_again_through_the_api(world):
    alcedo("--direct-scholar")
    world["direct"].clear()
    assert alcedo("--searchapi-key", "KEY", "--redo-openalex") == 0
    assert world["api"] == list(QUERIES)
    assert "Source:" not in world["results"].read_text(encoding="utf-8")


def test_few_results_from_an_api_are_mentioned(world, monkeypatch, capsys):
    monkeypatch.setattr(searchapi, "search_searchapi", lambda *a, **k: (pubs("x", range(1, 4)), None, False))
    assert alcedo("--searchapi-key", "KEY") == 0
    assert "SearchApi found only 3 results" in capsys.readouterr().out


def test_few_results_from_openalex_are_mentioned(world, monkeypatch, capsys):
    monkeypatch.setattr(openalex, "search_openalex", lambda q, a: (pubs("x", range(1, 3)), None))
    assert alcedo() == 0
    assert "OpenAlex found only 2 results" in capsys.readouterr().out


# ------------------------------- What the user is told -------------------------------

def test_warning_explains_network_incompleteness_and_terms():
    text = scholar.WARNING.lower()
    for fact in ("vpn", "browser", "incomplete", "robots.txt", "user-agent"):
        assert fact in text


def test_direct_warning_is_shown_when_it_is_used(world, capsys):
    assert alcedo("--direct-scholar") == 0
    assert "robots.txt" in capsys.readouterr().err


def test_after_agreeing_the_full_warning_becomes_a_short_reminder(world, capsys):
    config.save_config({"direct_scholar": True})
    assert alcedo() == 0
    err = capsys.readouterr().err
    assert scholar.REMINDER in err
    assert "robots.txt" not in err


def test_refused_direct_search_says_what_to_do_at_the_end(world, capsys):
    world["direct_error"] = "MaxTriesExceededException: Cannot Fetch from Google Scholar."
    world["direct_results"] = 0
    assert alcedo("--direct-scholar") == 0
    out = capsys.readouterr().out
    assert out.rstrip().endswith(scholar.REFUSED)
    for fact in ("VPN", "browser", "alcedo setup"):
        assert fact in scholar.REFUSED


def test_working_direct_search_gives_no_refusal_advice(world, capsys):
    assert alcedo("--direct-scholar") == 0
    assert scholar.REFUSED not in capsys.readouterr().out


def test_without_key_or_choice_the_user_is_pointed_to_setup(world, capsys):
    assert alcedo() == 0
    assert "alcedo setup" in capsys.readouterr().err
    assert world["direct"] == []


def test_setup_overview_states_costs_and_who_is_responsible():
    text = setup_wizard.OVERVIEW
    for fact in ("your own key", "100 free", "2500 free", "not tested yet", "250 free", "phone", "3 requests",
                 "visible to the provider", "OpenAlex", "Semantic Scholar", "left out"):
        assert fact in text


# ------------------------------- The user's choice -------------------------------

def test_first_run_in_a_terminal_asks_once_and_remembers(world, monkeypatch, capsys):
    monkeypatch.setattr(setup_wizard, "is_terminal", lambda: True)
    answers = []

    def say_yes(prompt):
        answers.append(prompt)
        return "y"

    monkeypatch.setattr(builtins, "input", say_yes)
    assert alcedo() == 0
    assert len(answers) == 1
    captured = capsys.readouterr()
    assert "VPN" in captured.out  # the risks come before the question
    assert "robots.txt" not in captured.err  # and they are not printed twice
    assert world["direct"] == list(QUERIES)
    assert config.load_config()["direct_scholar"] is True

    world["direct"].clear()
    assert alcedo("--overwrite") == 0
    assert len(answers) == 1
    assert world["direct"] == list(QUERIES)


def test_answering_no_uses_openalex_and_is_remembered(world, monkeypatch):
    monkeypatch.setattr(setup_wizard, "is_terminal", lambda: True)
    monkeypatch.setattr(builtins, "input", lambda prompt: "")
    assert alcedo() == 0
    assert world["direct"] == []
    assert config.load_config()["direct_scholar"] is False


def test_never_asks_when_a_key_exists_or_without_a_terminal(world, monkeypatch):
    monkeypatch.setattr(builtins, "input", lambda prompt: pytest.fail("must not ask"))
    assert alcedo() == 0  # the test run has no terminal
    monkeypatch.setattr(setup_wizard, "is_terminal", lambda: True)
    assert alcedo("--searchapi-key", "KEY", "--overwrite") == 0
    assert alcedo("--source", "openalex", "--overwrite") == 0


def test_no_direct_flag_overrides_the_saved_choice(world):
    config.save_config({"direct_scholar": True})
    assert alcedo("--no-direct-scholar") == 0
    assert world["direct"] == []


# ------------------------------- Keys -------------------------------

def test_setup_saves_keys_without_printing_them(monkeypatch, capsys):
    monkeypatch.setattr(setup_wizard, "is_terminal", lambda: True)
    typed = iter(["SECRET-SEARCH", "", "", "SECRET-OPENALEX", ""])
    monkeypatch.setattr(getpass, "getpass", lambda prompt: next(typed))
    monkeypatch.setattr(builtins, "input", lambda prompt: "n")
    assert cli.main(["setup"]) == 0
    saved = config.load_config()
    assert saved["searchapi_key"] == "SECRET-SEARCH"
    assert "serpapi_key" not in saved
    assert saved["openalex_key"] == "SECRET-OPENALEX"
    assert saved["direct_scholar"] is False
    output = capsys.readouterr().out
    assert "SECRET" not in output
    assert "SearchApi key: set, ends in ARCH" in output
    assert "SerpApi key: not set" in output


def test_pressing_enter_in_setup_keeps_saved_keys(monkeypatch):
    config.save_config({"searchapi_key": "OLD", "direct_scholar": True})
    monkeypatch.setattr(setup_wizard, "is_terminal", lambda: True)
    monkeypatch.setattr(getpass, "getpass", lambda prompt: "")
    monkeypatch.setattr(builtins, "input", lambda prompt: "")
    assert cli.main(["setup"]) == 0
    assert config.load_config() == {"searchapi_key": "OLD", "direct_scholar": True}


@pytest.mark.parametrize("typed", ["-", "------"])
def test_dashes_in_setup_remove_a_saved_key(monkeypatch, typed):
    config.save_config({"searchapi_key": "OLD-KEY-SAVED-EARLIER", "direct_scholar": False})
    monkeypatch.setattr(setup_wizard, "is_terminal", lambda: True)
    answers = iter([typed, "", "", "", ""])
    monkeypatch.setattr(getpass, "getpass", lambda prompt: next(answers))
    monkeypatch.setattr(builtins, "input", lambda prompt: "")
    assert cli.main(["setup"]) == 0
    assert "searchapi_key" not in config.load_config()


@pytest.mark.parametrize("typed", ["xq7z", "two words in the key", "abcdefghijklmnop\x16"])
def test_setup_refuses_what_cannot_be_a_key_without_echoing_it(monkeypatch, capsys, typed):
    monkeypatch.setattr(setup_wizard, "is_terminal", lambda: True)
    answers = iter([typed, "", "", "", ""])
    monkeypatch.setattr(getpass, "getpass", lambda prompt: next(answers))
    monkeypatch.setattr(builtins, "input", lambda prompt: "")
    assert cli.main(["setup"]) == 0
    assert "searchapi_key" not in config.load_config()
    output = capsys.readouterr().out
    assert "does not look like a SearchApi key" in output
    assert typed not in output


def test_setup_needs_a_terminal(capsys):
    assert cli.main(["setup"]) == 1
    assert "SEARCHAPI_KEY" in capsys.readouterr().err


def test_null_device_is_not_a_terminal(monkeypatch):
    with open(os.devnull) as null:  # it reports isatty() on Windows, where getpass would then wait forever
        monkeypatch.setattr(sys, "stdin", null)
        assert setup_wizard.is_terminal() is False


def test_saved_key_is_used_and_the_environment_wins(world, monkeypatch):
    config.save_config({"searchapi_key": "FROM_FILE"})
    assert cli.parse_args([]).searchapi_key == "FROM_FILE"
    monkeypatch.setenv("SEARCHAPI_KEY", "FROM_ENV")
    assert cli.parse_args([]).searchapi_key == "FROM_ENV"
    assert cli.parse_args(["--searchapi-key", "FROM_FLAG"]).searchapi_key == "FROM_FLAG"


def test_broken_config_file_is_ignored():
    path = config.config_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("not json", encoding="utf-8")
    assert config.load_config() == {}


def test_searchapi_key_is_hidden_in_errors(world, monkeypatch, capsys):
    monkeypatch.setattr(searchapi, "search_searchapi", lambda *a, **k: ([], "failed for SECRET123", False))
    assert alcedo("--searchapi-key", "SECRET123") == 0
    captured = capsys.readouterr()
    assert "SECRET123" not in captured.out + captured.err
    assert "SECRET123" not in world["results"].read_text(encoding="utf-8")
