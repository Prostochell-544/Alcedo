"""The search reports through events: the command line prints them as before, and a listener gets them instead."""

import pytest

from alcedo_lit import cli, events, pipeline
from alcedo_lit.events import FINISHED, NOTE, NOTICE, PROBLEM, STARTED, STATUS, STEP, STOPPED, Console, Event
from alcedo_lit.sources import openalex
from helpers import pubs


@pytest.fixture
def project(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "queries.txt").write_text("q1 one; q2 two;", encoding="utf-8")

    def fake_openalex(query, args):
        if query == "q2 two":
            return [], "HTTP 429"
        return pubs("oa", range(1, 4)), None

    monkeypatch.setattr(openalex, "search_openalex", fake_openalex)
    monkeypatch.setattr(pipeline, "pause_before_scholar", lambda args, bar: None)
    return tmp_path


def alcedo(*args):
    return cli.main(["--no-page-meta", "--no-title-search", "--no-semantic-scholar", "--no-direct-scholar", *args])


def test_a_listener_gets_the_events_and_nothing_is_printed(project, capsys):
    seen: list[Event] = []
    with events.listening(seen.append):
        assert alcedo() == 0
    out, err = capsys.readouterr()
    assert (out, err) == ("", "")  # not even the progress bars of single steps

    kinds = [e.kind for e in seen]
    assert kinds.count(STARTED) == 1 and kinds.count(STOPPED) == 1
    assert [e.data["query"] for e in seen if e.kind == STEP] == ["q1 one", "q2 two"]
    assert any(e.kind == STATUS and "OpenAlex" in e.text for e in seen)
    assert next(e for e in seen if e.kind == STARTED).data == {"total": 2, "done": 0}

    failure = next(e for e in seen if e.kind == NOTE and e.data.get("source") == "OpenAlex")
    assert failure.data == {"source": "OpenAlex", "query": "q2 two", "error": "HTTP 429"}

    summary = next(e for e in seen if e.kind == FINISHED).data
    assert (summary["queries"], summary["dois"], summary["errors"]) == (2, 3, 1)
    assert summary["output"] == "alcedo_results.txt"


def test_problems_before_a_run_are_events_too(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    seen: list[Event] = []
    with events.listening(seen.append):
        assert alcedo() == 1
    assert [(e.kind, e.text) for e in seen] == [(PROBLEM, "Query file not found: queries.txt")]


def test_without_a_listener_the_command_line_prints_as_before(project, capsys):
    assert alcedo() == 0
    out, err = capsys.readouterr()
    assert "Queries: 2, to collect: 2. Source: OpenAlex. Results: alcedo_results.txt" in out
    assert "[!] OpenAlex, 'q2 two': HTTP 429" in out
    assert "Done. DOIs: 3" in out
    assert "No search API key" in err


def test_the_listener_is_removed_after_the_block(project, capsys):
    with events.listening(lambda event: None):
        pass
    events.emit(NOTICE, "printed again")
    assert "printed again" in capsys.readouterr().out


def test_the_listener_is_removed_even_after_an_error(capsys):
    with pytest.raises(RuntimeError), events.listening(lambda event: None):
        raise RuntimeError
    events.emit(PROBLEM, "back on the terminal")
    assert "back on the terminal" in capsys.readouterr().err


def test_console_sends_each_kind_to_its_stream(capsys):
    console = Console()
    console(Event(NOTICE, "to stdout"))
    console(Event(PROBLEM, "to stderr"))
    console(Event(NOTE, "a note"))
    console(Event(STATUS, "ignored without a bar"))
    out, err = capsys.readouterr()
    assert out == "to stdout\na note\n"
    assert err == "to stderr\n"
