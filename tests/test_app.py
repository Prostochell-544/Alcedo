"""The desktop application, without a display. Skipped when Qt for Python is not installed."""

import gc
import html
import os
import time

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
QtWidgets = pytest.importorskip("PySide6.QtWidgets")

from PySide6.QtCore import QEvent, QEventLoop, QTimer  # noqa: E402

from alcedo_lit import config, events  # noqa: E402
from alcedo_lit.app import __main__ as app_main  # noqa: E402
from alcedo_lit.app import jobs, window  # noqa: E402
from alcedo_lit.app.window import (  # noqa: E402
    HelpMark,
    MainWindow,
    QueriesPage,
    ResultsPage,
    SearchPage,
    SourcesPage,
)
from alcedo_lit.events import NOTE, NOTICE, PROBLEM, STARTED, STATUS, STEP, Event  # noqa: E402

# One application for the whole run, never deleted by a fixture: if Qt went away before the windows the tests left
# behind, Python would crash while freeing them at exit, after every test had passed.
APP = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])


@pytest.fixture
def app():
    yield APP
    for widget in APP.topLevelWidgets():
        widget.close()
        widget.deleteLater()
    gc.collect()
    APP.sendPostedEvents(None, QEvent.Type.DeferredDelete)


def wait_for(job, timeout=5000):
    loop = QEventLoop()
    job.finished_with.connect(lambda code: loop.quit())
    QTimer.singleShot(timeout, loop.quit)
    job.start()
    loop.exec()
    job.wait(timeout)  # the signal comes just before the thread ends


def test_queries_are_checked_and_errors_block_the_start(app, tmp_path):
    page = QueriesPage()
    page.set_folder(tmp_path)
    page.editor.setPlainText("nacre toughness;")
    page.check()
    assert page.start_button.isEnabled()
    assert "1 query, 0 errors, 0 warnings." in page.summary.text()

    page.editor.setPlainText("nacre toughness; gecko or adhesive;")
    page.check()
    assert page.start_button.isEnabled()  # a warning does not stop the search
    assert page.problems.item(0).text().startswith("Query 2, warning:")

    page.editor.setPlainText("nacre*;")
    page.check()
    assert not page.start_button.isEnabled()
    assert "Fix the errors to start." in page.summary.text()


def test_starting_saves_the_queries_in_the_folder(app, tmp_path):
    page = QueriesPage()
    page.set_folder(tmp_path / "review")
    page.editor.setPlainText("nacre toughness;")
    started = []
    page.start.connect(lambda folder, pages: started.append((folder, pages)))
    page.request_start()
    assert (tmp_path / "review" / "queries.txt").read_text(encoding="utf-8") == "nacre toughness;"
    assert started == [(tmp_path / "review", 5)]


def test_sources_save_keys_and_the_choice_about_direct_search(app, monkeypatch):
    monkeypatch.setattr(window, "direct_search_available", lambda: True)
    page = SourcesPage()
    page.fields["serper_key"].setText("SERPER-KEY-123456")
    page.direct.setChecked(True)
    page.save()
    saved = config.load_config()
    assert saved["serper_key"] == "SERPER-KEY-123456"
    assert saved["direct_scholar"] is True
    assert page.states["serper_key"].text() == "ends in 3456"
    assert page.fields["serper_key"].text() == ""  # the key is not shown again

    page.fields["serper_key"].setText("-")
    page.save()
    assert "serper_key" not in config.load_config()


def test_without_scholarly_the_direct_choice_is_off_and_kept(app, monkeypatch):
    config.save_config({"direct_scholar": True})
    monkeypatch.setattr(window, "direct_search_available", lambda: False)
    page = SourcesPage()
    assert not page.direct.isEnabled() and not page.direct.isChecked()
    page.save()
    assert config.load_config()["direct_scholar"] is True  # the Python version with scholarly still uses it


def test_the_settings_file_is_always_shown_as_a_link(app):
    page = SourcesPage()
    path = html.escape(str(config.config_path()))
    assert page.saved_in.text() == f'Will be saved in <a href="folder">{path}</a>'
    page.save()
    assert page.saved_in.text() == f'Saved in <a href="folder">{path}</a>'


def test_the_built_program_can_check_itself(app):
    assert app_main.main(["--self-check"]) == 0


def test_hints_wait_behind_question_marks(app):
    page = SourcesPage()  # kept, so that Qt does not delete the marks while they are read
    tips = [mark.toolTip() for mark in page.findChildren(HelpMark)]
    assert any("2,500 free queries" in tip for tip in tips)
    assert any("type a dash (-) to remove it" in tip for tip in tips)
    assert all(tip.startswith("<p>") for tip in tips)  # rich text, so that long hints wrap


def test_the_form_becomes_the_options_of_alcedo_filter(app, tmp_path):
    page = ResultsPage()
    page.folder = tmp_path
    page.year_from.setValue(2015)
    page.languages.setText("en, ru")
    page.quartiles["Q1"].setChecked(True)
    page.sjr.setText("sjr.csv")
    page.words.setText("dental, rat , ")
    page.keep_retracted.setChecked(True)
    assert page.conditions() == ["-i", str(tmp_path / "alcedo_results.txt"), "--year-from", "2015",
                                 "--language", "en, ru", "--type", "article,review", "--quartile", "Q1",
                                 "--sjr", "sjr.csv", "--exclude-word", "dental", "--exclude-word", "rat",
                                 "--keep-retracted"]


def test_the_lists_are_shown_with_their_counts(app, tmp_path):
    (tmp_path / "alcedo_filtered.csv").write_text(
        "﻿doi;url;title;year;journal;quartile;open_access;found_by_queries;reason\n"
        "10.1/a;https://doi.org/10.1/a;Paper A;2020;J;Q1;gold;2;\n"
        "10.1/b;https://doi.org/10.1/b;Paper B;2019;J;Q2;closed;10;\n", encoding="utf-8")
    page = ResultsPage()
    page.load(tmp_path)
    assert page.tabs.tabText(0) == "Kept 2"
    assert page.tabs.tabText(1) == "Excluded 0"
    model = page.tables["filtered"].model()
    assert model.index(0, 0).data() == "Paper A"  # the order of the file, until a column is clicked
    assert model.index(1, 5).data() == 10  # a number, so that it sorts as one


def test_the_search_page_follows_the_events(app):
    page = SearchPage()
    page.begin()
    for event in (Event(NOTICE, "Queries: 2, to collect: 2. Source: OpenAlex."),
                  Event(STARTED, data={"total": 2, "done": 0}), Event(STATUS, "q1 | page 2"),
                  Event(STEP, data={"query": "q1"}), Event(NOTE, "[!] OpenAlex failed")):
        page.on_event(event)
    assert page.source.text().startswith("Queries: 2")
    assert (page.progress.value(), page.progress.maximum()) == (1, 2)
    assert page.status.text() == "q1 | page 2"
    assert "[!] OpenAlex failed" in page.log.toPlainText()
    page.end(130)
    assert page.results_button.isEnabled()
    assert "Stopped" in page.status.text()


def test_a_job_passes_on_events_and_printed_lines(app):
    def work():
        events.emit(NOTE, "a note")
        print("a printed line")
        print("a problem", file=__import__("sys").stderr)
        return 0

    job = jobs.Job(work)
    seen, codes = [], []
    job.event.connect(seen.append)
    job.finished_with.connect(codes.append)
    wait_for(job)
    app.processEvents()
    assert [(e.kind, e.text) for e in seen] == [(NOTE, "a note"), (NOTICE, "a printed line"), (PROBLEM, "a problem")]
    assert codes == [0]


def test_stop_ends_the_work_at_the_next_event(app):
    def work():
        for _ in range(1000):
            events.emit(STATUS, "working")
        return 0

    job = jobs.Job(work)
    job.stop()
    codes = []
    job.finished_with.connect(codes.append)
    wait_for(job)
    app.processEvents()
    assert codes == [130]


def test_an_error_in_the_work_is_reported_not_raised(app):
    job = jobs.Job(lambda: 1 / 0)
    seen, codes = [], []
    job.event.connect(seen.append)
    job.finished_with.connect(codes.append)
    wait_for(job)
    app.processEvents()
    assert codes == [1]
    assert "ZeroDivisionError" in seen[0].text


def test_closing_during_work_stops_it_first(app, monkeypatch):
    def work():
        while True:
            events.emit(STATUS, "working")
            time.sleep(0.01)

    main_window = MainWindow()
    monkeypatch.setattr(QtWidgets.QMessageBox, "question", lambda *args: QtWidgets.QMessageBox.StandardButton.Yes)
    codes = []
    main_window.launch(work, lambda event: None, codes.append)
    assert main_window.close()
    assert not main_window.job.isRunning()
    app.processEvents()
    assert codes == [130]


def test_the_window_opens_on_sources_until_something_is_chosen(app):
    window = MainWindow()
    assert window.steps.currentRow() == 0
    assert [window.steps.item(row).text() for row in range(4)] == ["Sources", "Queries", "Search", "Results"]
    config.save_config({"direct_scholar": False})
    assert MainWindow().steps.currentRow() == 1
