"""The main window: Sources, Queries, Search and Results, the same steps as on the command line."""

from __future__ import annotations

import csv
import html
import importlib.util
import sys
from pathlib import Path

from PySide6.QtCore import QPoint, QProcess, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QFont, QIcon, QPixmap, QStandardItem, QStandardItemModel
from PySide6.QtWidgets import (
    QAbstractItemView,
    QApplication,
    QCheckBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QSizePolicy,
    QSpinBox,
    QStackedWidget,
    QTableView,
    QTabWidget,
    QToolButton,
    QToolTip,
    QVBoxLayout,
    QWidget,
)

from .. import __version__
from ..check import ERROR, check_text
from ..cli import parse_args
from ..config import config_path, load_config, save_config
from ..events import FINISHED, NOTE, NOTICE, PROBLEM, STARTED, STATUS, STEP, Event
from ..export import run_export
from ..filters import run_filter
from ..pipeline import run as run_search
from ..results import counted
from ..setup_wizard import looks_like_key
from .jobs import Job

ASSETS = Path(__file__).parent / "assets"
QUERIES_FILE, RESULTS_FILE = "queries.txt", "alcedo_results.txt"
API_KEYS = (("searchapi_key", "SearchApi", "100 free requests, then from $40 a month"),
            ("serper_key", "Serper", "2,500 free queries, about 500 searches of 50 results"),
            ("serpapi_key", "SerpApi", "250 free searches a month; asks for a phone number"))
FREE_KEYS = (("semantic_scholar_key", "Semantic Scholar", "Optional. Without a key, all users share one limit."),
             ("openalex_key", "OpenAlex", "Optional. A free key raises the daily budget."))
COMMON_TYPES = ("article", "review", "preprint", "book-chapter", "dissertation", "conference-paper")
LISTS = (("filtered", "Kept"), ("excluded", "Excluded"), ("unknown", "Check by hand"), ("duplicates", "Repeats"),
         ("no_access", "No open copy"))
SHOWN_COLUMNS = (("title", "Title"), ("year", "Year"), ("journal", "Journal"), ("quartile", "Quartile"),
                 ("open_access", "Open copy"), ("found_by_queries", "Queries"), ("reason", "Reason"))
COLUMN_WIDTHS = (56, 190, 70, 90, 66, 260)  # every column after the title
NUMERIC_COLUMNS = {"year", "found_by_queries"}


class HelpMark(QToolButton):
    """A small question mark that shows its explanation on hover or click, so that hints do not crowd the window."""

    def __init__(self, text: str) -> None:
        super().__init__()
        self.setObjectName("help")
        self.setText("?")
        self.setCursor(Qt.CursorShape.PointingHandCursor)
        self.setFocusPolicy(Qt.FocusPolicy.NoFocus)
        self.setToolTip(f"<p>{html.escape(text)}</p>")  # rich text, so that a long explanation wraps
        self.clicked.connect(self.show_help)

    def show_help(self) -> None:
        QToolTip.showText(self.mapToGlobal(QPoint(0, self.height())), self.toolTip(), self)


def with_help(widget: QWidget, text: str) -> QHBoxLayout:
    """The widget followed by its question mark."""
    row = QHBoxLayout()
    row.setSpacing(6)
    row.addWidget(widget)
    row.addWidget(HelpMark(text))
    row.addStretch(1)
    return row


def heading(text: str, help_text: str = "") -> QWidget:
    box = QWidget()
    layout = QVBoxLayout(box)
    layout.setContentsMargins(0, 0, 0, 8)
    title = QLabel(text)
    font = title.font()
    font.setPointSizeF(font.pointSizeF() * 1.5)
    font.setBold(True)
    title.setFont(font)
    if help_text:
        layout.addLayout(with_help(title, help_text))
    else:
        layout.addWidget(title)
    return box


def hint(text: str) -> QLabel:
    label = QLabel(text)
    label.setWordWrap(True)
    label.setObjectName("hint")
    return label


def direct_search_available() -> bool:
    """Direct Google Scholar search needs scholarly, which the Windows program does not include."""
    return importlib.util.find_spec("scholarly") is not None


def show_in_folder(path: Path) -> None:
    """Open the folder of a file, with the file selected where the system allows it."""
    if sys.platform == "win32" and path.is_file():
        QProcess.startDetached("explorer.exe", ["/select,", str(path)])
        return
    folder = path if path.is_dir() else path.parent
    folder.mkdir(parents=True, exist_ok=True)
    QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))


class SourcesPage(QWidget):
    """Keys for the search APIs and the free sources, saved in the same settings file as `alcedo setup` uses."""

    saved = Signal(str)

    def __init__(self) -> None:
        super().__init__()
        self.fields: dict[str, QLineEdit] = {}
        self.states: dict[str, QLabel] = {}
        layout = QVBoxLayout(self)
        layout.addWidget(heading("Where Alcedo searches",
                                 "With a key for a search API, every query goes to Google Scholar through it. Without "
                                 "one, Alcedo uses Semantic Scholar and OpenAlex, which are free. Keys stay in a file "
                                 "on this computer."))
        for title, rows in (("Search APIs for Google Scholar", API_KEYS), ("Free sources", FREE_KEYS)):
            group = QGroupBox(title)
            form = QGridLayout(group)
            form.setColumnMinimumWidth(0, 130)  # the key fields of both groups start on one line
            for row, (field, label, cost) in enumerate(rows):
                edit = QLineEdit()
                edit.setEchoMode(QLineEdit.EchoMode.Password)
                edit.setMinimumWidth(320)
                state = QLabel()
                state.setObjectName("hint")
                form.addLayout(with_help(QLabel(label), cost), row, 0)
                form.addWidget(edit, row, 1)
                form.addWidget(state, row, 2)
                form.setColumnStretch(2, 1)
                self.fields[field], self.states[field] = edit, state
            if rows is FREE_KEYS:
                self.direct = QCheckBox("Also search Google Scholar directly when no API answers")
                if direct_search_available():
                    about = ("Free, but Google Scholar can refuse automated searches, and its lists can then be "
                             "incomplete. Alcedo says when that happens.")
                elif getattr(sys, "frozen", False):
                    about = ("The Windows program does not include direct search. It needs the Python version: "
                             'pip install "alcedo-lit[scholar]"')
                else:
                    about = 'Direct search needs one more package: pip install "alcedo-lit[scholar]"'
                self.direct.setEnabled(direct_search_available())
                form.addLayout(with_help(self.direct, about), len(rows), 0, 1, 3)
            layout.addWidget(group)
        self.save_button = QPushButton("Save")
        self.save_button.setDefault(True)
        self.save_button.clicked.connect(self.save)
        self.saved_in = QLabel()
        self.saved_in.setObjectName("hint")
        self.saved_in.setToolTip(f"Show the file in its folder: {config_path()}")
        # A long path is cut at the window edge instead of widening the window.
        self.saved_in.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
        self.saved_in.linkActivated.connect(lambda _link: show_in_folder(config_path()))
        save_row = QHBoxLayout()
        save_row.setSpacing(10)
        save_row.addWidget(self.save_button)
        save_row.addWidget(HelpMark("Leave a field empty to keep its key; type a dash (-) to remove it."))
        save_row.addWidget(self.saved_in, 1)
        layout.addLayout(save_row)
        layout.addStretch(1)
        self.load()

    def load(self) -> None:
        config = load_config()
        for field, edit in self.fields.items():
            key = config.get(field)
            edit.clear()
            edit.setPlaceholderText("saved; type to replace, or leave it" if key else "paste a key")
            self.states[field].setText(f"ends in {key[-4:]}" if key else "not set")
        self.direct.setChecked(direct_search_available() and bool(config.get("direct_scholar")))
        path = config_path()
        where = "Saved in" if path.exists() else "Will be saved in"
        self.saved_in.setText(f'{where} <a href="folder">{html.escape(str(path))}</a>')

    def save(self) -> None:
        config = load_config()
        for field, edit in self.fields.items():
            value = edit.text().strip()
            if not value:
                continue
            if not value.strip("-"):
                config.pop(field, None)
            elif looks_like_key(value):
                config[field] = value
            else:
                QMessageBox.warning(self, "Alcedo", "That does not look like a key, so it was not saved.")
                return
        if self.direct.isEnabled():  # without scholarly, keep the choice made in the Python version
            config["direct_scholar"] = self.direct.isChecked()
        save_config(config)
        self.load()
        self.saved.emit("Settings saved.")


class QueriesPage(QWidget):
    """The query file of a review, checked as you type, and the button that starts the search."""

    start = Signal(Path, int)

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(heading("Your queries",
                                 "One query per line, each ending with a semicolon. Alcedo checks them as you type, "
                                 "without using any quota. Each review keeps its files in a folder of its own."))
        folder_row = QHBoxLayout()
        self.folder_label = QLabel()
        self.folder_label.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        choose = QPushButton("Choose folder…")
        choose.clicked.connect(self.choose_folder)
        folder_row.addWidget(QLabel("Folder:"))
        folder_row.addWidget(self.folder_label, 1)
        folder_row.addWidget(choose)
        layout.addLayout(folder_row)

        body = QHBoxLayout()
        self.editor = QPlainTextEdit()
        self.editor.setFont(QFont("Consolas, Menlo, monospace"))
        self.editor.setPlaceholderText('"Alcedo atthis" kingfisher (foraging OR diet);')
        self.editor.textChanged.connect(lambda: self.timer.start())
        body.addWidget(self.editor, 3)
        side = QVBoxLayout()
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        self.problems = QListWidget()
        self.problems.setWordWrap(True)
        side.addWidget(QLabel("<b>Check</b>"))
        side.addWidget(self.summary)
        side.addWidget(self.problems, 1)
        body.addLayout(side, 2)
        layout.addLayout(body, 1)

        run_row = QHBoxLayout()
        self.pages = QSpinBox()
        self.pages.setRange(1, 10)
        self.pages.setValue(5)
        run_row.addWidget(QLabel("Result pages per query"))
        run_row.addLayout(with_help(self.pages, "Each page has 10 results. When a query has fewer, Alcedo takes all "
                                                "there are."), 1)
        self.start_button = QPushButton("Start search")
        self.start_button.setDefault(True)
        self.start_button.clicked.connect(self.request_start)
        run_row.addWidget(self.start_button)
        layout.addLayout(run_row)

        self.timer = QTimer(self, singleShot=True, interval=300)
        self.timer.timeout.connect(self.check)
        folder = load_config().get("app_folder")
        self.set_folder(Path(folder) if folder else Path.home() / "Alcedo")

    @property
    def folder(self) -> Path:
        return Path(self.folder_label.text())

    def set_folder(self, folder: Path) -> None:
        self.folder_label.setText(str(folder))
        queries = folder / QUERIES_FILE
        self.editor.setPlainText(queries.read_text(encoding="utf-8-sig") if queries.exists() else "")
        self.check()

    def choose_folder(self) -> None:
        chosen = QFileDialog.getExistingDirectory(self, "Folder for this review", str(self.folder))
        if chosen:
            config = load_config()
            config["app_folder"] = chosen
            save_config(config)
            self.set_folder(Path(chosen))

    def check(self) -> None:
        """Show the problems in the queries. Errors stop the search, warnings do not."""
        checked = check_text(self.editor.toPlainText())
        self.problems.clear()
        errors = warnings = 0
        for number, (query, problems) in enumerate(checked, 1):
            for level, message in problems:
                errors += level == ERROR
                warnings += level != ERROR
                item = QListWidgetItem(f"Query {number}, {level}: {message}")
                item.setToolTip(query)
                item.setData(Qt.ItemDataRole.UserRole, level)
                self.problems.addItem(item)
        if not checked:
            self.summary.setText("No queries yet.")
        else:
            self.summary.setText(f"{counted(len(checked), 'query', 'queries')}, {counted(errors, 'error')}, "
                                 f"{counted(warnings, 'warning')}." + (" Fix the errors to start." if errors else ""))
        self.start_button.setEnabled(bool(checked) and not errors)

    def request_start(self) -> None:
        self.folder.mkdir(parents=True, exist_ok=True)
        (self.folder / QUERIES_FILE).write_text(self.editor.toPlainText(), encoding="utf-8")
        self.start.emit(self.folder, self.pages.value())


class SearchPage(QWidget):
    """Progress of the search and everything it reports, with a button to stop it."""

    stop = Signal()
    show_results = Signal()

    def __init__(self) -> None:
        super().__init__()
        layout = QVBoxLayout(self)
        layout.addWidget(heading("Search", "Results are saved after every query, so you can stop and continue later."))
        self.source = QLabel()
        self.source.setWordWrap(True)
        self.progress = QProgressBar()
        self.progress.setFormat("%v of %m queries")
        self.status = QLabel("Not started.")
        self.status.setObjectName("hint")
        layout.addWidget(self.source)
        layout.addWidget(self.progress)
        layout.addWidget(self.status)
        layout.addWidget(QLabel("<b>What happened</b>"))
        self.log = QPlainTextEdit(readOnly=True)
        self.log.setFont(QFont("Consolas, Menlo, monospace"))
        layout.addWidget(self.log, 1)
        buttons = QHBoxLayout()
        self.stop_button = QPushButton("Stop")
        self.stop_button.setEnabled(False)
        self.stop_button.clicked.connect(self.stop.emit)
        self.results_button = QPushButton("Show results")
        self.results_button.setEnabled(False)
        self.results_button.clicked.connect(self.show_results.emit)
        buttons.addWidget(self.stop_button)
        buttons.addStretch(1)
        buttons.addWidget(self.results_button)
        layout.addLayout(buttons)

    def begin(self) -> None:
        self.log.clear()
        self.source.clear()
        self.progress.setValue(0)
        self.status.setText("Starting…")
        self.stop_button.setEnabled(True)
        self.results_button.setEnabled(False)

    def on_event(self, event: Event) -> None:
        if event.kind == STARTED:
            self.progress.setRange(0, max(event.data["total"], 1))
            self.progress.setValue(event.data["done"])
        elif event.kind == STATUS:
            self.status.setText(event.text)
        elif event.kind == STEP:
            self.progress.setValue(self.progress.value() + 1)
        elif event.kind == NOTICE and event.text.startswith("Queries:"):
            self.source.setText(event.text)
        elif event.kind in (NOTE, NOTICE, PROBLEM):
            self.log.appendPlainText(event.text)
        elif event.kind == FINISHED:
            self.status.setText(f"Done: {event.data['dois']} DOIs, {event.data['unique']} unique, "
                                f"{counted(event.data['errors'], 'query', 'queries')} with errors.")

    def end(self, code: int) -> None:
        self.stop_button.setEnabled(False)
        self.results_button.setEnabled(code in (0, 130))
        if code == 130:
            self.status.setText("Stopped. What was collected is saved; start again to continue.")
        elif code != 0:
            self.status.setText("The search could not run. See the messages above.")


class ResultsPage(QWidget):
    """Conditions for `alcedo filter`, the five lists it writes, and the export buttons."""

    run_filter = Signal(list)
    run_export = Signal(list)

    def __init__(self) -> None:
        super().__init__()
        self.folder: Path | None = None
        layout = QVBoxLayout(self)
        layout.addWidget(heading("Results", "Change the conditions as often as you like: filtering uses no search "
                                            "quota. Records with missing data are listed apart, never dropped."))
        conditions = QGroupBox("Conditions")
        grid = QGridLayout(conditions)
        self.year_from, self.year_to = QSpinBox(), QSpinBox()
        for box in (self.year_from, self.year_to):
            box.setRange(1899, 2100)
            box.setSpecialValueText("any")
            box.setValue(1899)
        self.languages = QLineEdit("en")
        self.types = {kind: QCheckBox(kind) for kind in COMMON_TYPES}
        for kind in ("article", "review"):
            self.types[kind].setChecked(True)
        self.quartiles = {q: QCheckBox(q) for q in ("Q1", "Q2", "Q3", "Q4")}
        self.sjr = QLabel("No SJR file chosen")
        self.sjr.setObjectName("hint")
        choose_sjr = QPushButton("Choose SJR file…")
        choose_sjr.clicked.connect(self.choose_sjr)
        self.words = QLineEdit()
        self.words.setPlaceholderText("such as dental, rat; separated by commas")
        self.keep_retracted = QCheckBox("Keep retracted papers")

        grid.addWidget(QLabel("Years"), 0, 0)
        years = QHBoxLayout()
        years.addWidget(self.year_from)
        years.addWidget(QLabel("to"))
        years.addWidget(self.year_to)
        years.addStretch(1)
        grid.addLayout(years, 0, 1)
        grid.addWidget(QLabel("Languages"), 0, 2)
        grid.addWidget(self.languages, 0, 3)
        grid.addWidget(QLabel("Record types"), 1, 0)
        types = QHBoxLayout()
        for box in self.types.values():
            types.addWidget(box)
        types.addStretch(1)
        grid.addLayout(types, 1, 1, 1, 3)
        grid.addWidget(QLabel("Quartiles"), 2, 0)
        quartiles = QHBoxLayout()
        for box in self.quartiles.values():
            quartiles.addWidget(box)
        quartiles.addWidget(HelpMark("Quartiles come from the journal list of scimagojr.com: open it, press "
                                     "Download data and choose the file here. Alcedo remembers it."))
        quartiles.addWidget(choose_sjr)
        quartiles.addWidget(self.sjr, 1)
        grid.addLayout(quartiles, 2, 1, 1, 3)
        grid.addWidget(QLabel("Excluded words"), 3, 0)
        grid.addWidget(self.words, 3, 1)
        grid.addWidget(self.keep_retracted, 3, 2, 1, 2)
        apply_row = QHBoxLayout()
        self.apply_button = QPushButton("Apply")
        self.apply_button.setDefault(True)
        self.apply_button.clicked.connect(self.apply)
        self.summary = QLabel()
        self.summary.setWordWrap(True)
        apply_row.addWidget(self.apply_button)
        apply_row.addWidget(self.summary, 1)
        grid.addLayout(apply_row, 4, 0, 1, 4)
        layout.addWidget(conditions)

        self.tabs = QTabWidget()
        self.tables: dict[str, QTableView] = {}
        for name, label in LISTS:
            table = QTableView()
            table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
            table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
            table.setWordWrap(False)
            table.verticalHeader().hide()
            table.doubleClicked.connect(self.open_record)
            self.tables[name] = table
            self.tabs.addTab(table, label)
        layout.addWidget(self.tabs, 1)

        exports = QHBoxLayout()
        for label, fmt in (("Export for Zotero (RIS)", "ris"), ("Export BibTeX", "bibtex")):
            button = QPushButton(label)
            button.clicked.connect(lambda _=False, fmt=fmt: self.export(fmt))
            exports.addWidget(button)
        exports.addStretch(1)
        log_button = QPushButton("Selection log")
        log_button.clicked.connect(lambda: self.open_file("alcedo_selection_log.md"))
        folder_button = QPushButton("Open folder")
        folder_button.clicked.connect(self.open_folder)
        exports.addWidget(log_button)
        exports.addWidget(folder_button)
        layout.addLayout(exports)
        sjr = load_config().get("sjr_file")
        if sjr and Path(sjr).exists():
            self.sjr.setText(sjr)

    def choose_sjr(self) -> None:
        chosen, _ = QFileDialog.getOpenFileName(self, "SJR file from scimagojr.com", str(Path.home()),
                                                "CSV files (*.csv)")
        if chosen:
            self.sjr.setText(chosen)
            config = load_config()
            config["sjr_file"] = chosen
            save_config(config)

    def conditions(self) -> list[str]:
        """Turn the form into the options of `alcedo filter`."""
        argv = ["-i", str(self.folder / RESULTS_FILE)]
        if self.year_from.value() > self.year_from.minimum():
            argv += ["--year-from", str(self.year_from.value())]
        if self.year_to.value() > self.year_to.minimum():
            argv += ["--year-to", str(self.year_to.value())]
        if self.languages.text().strip():
            argv += ["--language", self.languages.text().strip()]
        types = [kind for kind, box in self.types.items() if box.isChecked()]
        if types:
            argv += ["--type", ",".join(types)]
        quartiles = [q for q, box in self.quartiles.items() if box.isChecked()]
        if quartiles:
            argv += ["--quartile", ",".join(quartiles), "--sjr", self.sjr.text()]
        for word in filter(None, (w.strip() for w in self.words.text().split(","))):
            argv += ["--exclude-word", word]
        if self.keep_retracted.isChecked():
            argv.append("--keep-retracted")
        return argv

    def apply(self) -> None:
        if not self.folder or not (self.folder / RESULTS_FILE).exists():
            QMessageBox.information(self, "Alcedo", "There are no results yet. Run a search first.")
            return
        if any(box.isChecked() for box in self.quartiles.values()) and not Path(self.sjr.text()).is_file():
            QMessageBox.information(self, "Alcedo", "Quartiles need the SJR file. Download it from scimagojr.com "
                                                    "(Download data) and choose it here.")
            return
        self.apply_button.setEnabled(False)
        self.summary.setText("Fetching paper data and applying the conditions…")
        self.run_filter.emit(self.conditions())

    def export(self, fmt: str) -> None:
        if self.folder and (self.folder / "alcedo_filtered.csv").exists():
            self.run_export.emit(["-i", str(self.folder / "alcedo_filtered.csv"), "--format", fmt])
        else:
            QMessageBox.information(self, "Alcedo", "Apply the conditions first: the export takes the kept list.")

    def load(self, folder: Path) -> None:
        """Show the lists that `alcedo filter` wrote into the folder."""
        self.folder = folder
        self.apply_button.setEnabled(True)
        for (name, label), index in zip(LISTS, range(self.tabs.count()), strict=True):
            path = folder / f"alcedo_{name}.csv"
            model = QStandardItemModel()
            model.setHorizontalHeaderLabels([title for _, title in SHOWN_COLUMNS])
            rows = []
            if path.exists():
                with path.open(encoding="utf-8-sig", newline="") as file:
                    rows = list(csv.DictReader(file, delimiter=";"))
            for row in rows:
                items = []
                for column, _ in SHOWN_COLUMNS:
                    value = row.get(column) or ""
                    item = QStandardItem()
                    # Numbers are stored as numbers, so that sorting puts 10 after 9.
                    item.setData(int(value) if column in NUMERIC_COLUMNS and value.isdigit() else value,
                                 Qt.ItemDataRole.DisplayRole)
                    item.setData(row.get("url") or row.get("open_access_url") or "", Qt.ItemDataRole.UserRole)
                    items.append(item)
                model.appendRow(items)
            table = self.tables[name]
            table.setSortingEnabled(False)
            table.setModel(model)
            header = table.horizontalHeader()
            header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
            header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)  # the title takes the free width
            header.setStretchLastSection(False)
            for column, width in enumerate(COLUMN_WIDTHS, 1):
                table.setColumnWidth(column, width)
            table.setColumnHidden(len(SHOWN_COLUMNS) - 1, name == "filtered")  # kept records have no reason
            # The lists come with the papers found by most queries first; keep that order until a column is clicked.
            header.setSortIndicator(-1, Qt.SortOrder.AscendingOrder)
            table.setSortingEnabled(True)
            self.tabs.setTabText(index, f"{label} {len(rows)}")

    def open_record(self, index) -> None:
        url = index.data(Qt.ItemDataRole.UserRole)
        if url:
            QDesktopServices.openUrl(QUrl(url))

    def open_folder(self) -> None:
        if self.folder:
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder)))

    def open_file(self, name: str) -> None:
        if self.folder and (self.folder / name).exists():
            QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.folder / name)))


class MainWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle("Alcedo")
        self.setWindowIcon(QIcon(str(ASSETS / "logo.png")))
        self.resize(1180, 760)
        self.job: Job | None = None

        self.sources, self.queries = SourcesPage(), QueriesPage()
        self.search, self.results = SearchPage(), ResultsPage()
        self.steps = QListWidget()
        self.steps.setObjectName("steps")
        self.steps.setFixedWidth(190)
        self.steps.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.pages = QStackedWidget()
        for label, page in (("Sources", self.sources), ("Queries", self.queries), ("Search", self.search),
                            ("Results", self.results)):
            self.steps.addItem(QListWidgetItem(label))
            wrapper = QWidget()
            inner = QVBoxLayout(wrapper)
            inner.setContentsMargins(28, 22, 28, 18)
            inner.addWidget(page)
            self.pages.addWidget(wrapper)
        self.steps.currentRowChanged.connect(self.pages.setCurrentIndex)

        top = QWidget()
        top.setObjectName("top")
        bar = QHBoxLayout(top)
        bar.setContentsMargins(16, 10, 16, 10)
        logo = QLabel()
        logo.setPixmap(QPixmap(str(ASSETS / "logo.png")).scaled(QSize(34, 34), Qt.AspectRatioMode.KeepAspectRatio,
                                                                  Qt.TransformationMode.SmoothTransformation))
        name = QLabel("<b>Alcedo</b>")
        name.setObjectName("name")
        bar.addWidget(logo)
        bar.addWidget(name)
        bar.addWidget(hint(__version__))
        bar.addStretch(1)
        local = QLabel("Runs on this computer only")
        local.setObjectName("hint")
        bar.addWidget(local)

        middle = QHBoxLayout()
        middle.setSpacing(0)
        middle.setContentsMargins(0, 0, 0, 0)
        middle.addWidget(self.steps)
        middle.addWidget(self.pages, 1)
        central = QWidget()
        outer = QVBoxLayout(central)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(0)
        outer.addWidget(top)
        outer.addLayout(middle, 1)
        self.setCentralWidget(central)
        self.steps.setCurrentRow(1 if self.has_any_key_or_choice() else 0)

        self.sources.saved.connect(lambda text: self.statusBar().showMessage(text, 4000))
        self.queries.start.connect(self.start_search)
        self.search.stop.connect(lambda: self.job and self.job.stop())
        self.search.show_results.connect(self.open_results)
        self.results.run_filter.connect(self.start_filter)
        self.results.run_export.connect(self.start_export)

    @staticmethod
    def has_any_key_or_choice() -> bool:
        config = load_config()
        return any(config.get(k) for k in ("searchapi_key", "serper_key", "serpapi_key")) or "direct_scholar" in config

    def closeEvent(self, event) -> None:  # the name Qt calls
        """Stop the work before the window goes: a thread still running when Alcedo quits would crash it."""
        if self.job and self.job.isRunning():
            answer = QMessageBox.question(self, "Alcedo", "Alcedo is still working. Stop and close? Results are "
                                                          "saved after every query, so you can continue later.")
            if answer != QMessageBox.StandardButton.Yes:
                event.ignore()
                return
            self.job.stop()  # takes effect at the next step of the work, after the current request
            self.statusBar().showMessage("Stopping…")
            while not self.job.wait(100):
                QApplication.processEvents()
        event.accept()

    def busy(self) -> bool:
        if self.job and self.job.isRunning():
            QMessageBox.information(self, "Alcedo", "Alcedo is still working. Wait for it, or stop the search.")
            return True
        return False

    def start_search(self, folder: Path, pages: int) -> None:
        if self.busy():
            return
        results = folder / RESULTS_FILE
        argv = ["-i", str(folder / QUERIES_FILE), "-o", str(results), "--pages", str(pages)]
        if results.exists():
            answer = QMessageBox.question(
                self, "Alcedo", "This folder already has results. Continue them, collecting only the queries that are "
                "missing? Choose No to start over and replace them.",
                QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No | QMessageBox.StandardButton.Cancel)
            if answer == QMessageBox.StandardButton.Cancel:
                return
            argv.append("--resume" if answer == QMessageBox.StandardButton.Yes else "--overwrite")

        def work() -> int:
            args = parse_args(argv)
            if args.direct_scholar is None or not direct_search_available():  # the Sources step decides
                args.direct_scholar = False
            return run_search(args)

        self.search.begin()
        self.steps.setCurrentRow(2)
        self.launch(work, self.search.on_event, self.search.end)

    def open_results(self) -> None:
        folder = self.queries.folder
        self.results.load(folder)
        self.steps.setCurrentRow(3)
        if not (folder / "alcedo_filtered.csv").exists():
            self.results.apply()

    def start_filter(self, argv: list[str]) -> None:
        if self.busy():
            return
        messages: list[str] = []

        def done(code: int) -> None:
            self.results.load(self.queries.folder)
            text = " ".join(m for m in messages if m.startswith(("Records:", "Of the kept")))
            problems = [m for m in messages if m.startswith(("Cannot", "No ", "--"))]
            self.results.summary.setText(problems[0] if code and problems else text)

        self.launch(lambda: run_filter(argv), lambda e: messages.append(e.text), done)

    def start_export(self, argv: list[str]) -> None:
        if self.busy():
            return
        messages: list[str] = []

        def done(code: int) -> None:
            text = next((m for m in messages if m.startswith("Exported")), "The export failed.")
            self.statusBar().showMessage(text, 8000)
            if code == 0:
                QDesktopServices.openUrl(QUrl.fromLocalFile(str(self.queries.folder)))

        self.launch(lambda: run_export(argv), lambda e: messages.append(e.text), done)

    def launch(self, work, on_event, on_done) -> None:
        self.job = Job(work, self)
        self.job.event.connect(on_event)
        self.job.finished_with.connect(on_done)
        self.job.start()


STYLE = """
QWidget#top { border-bottom: 1px solid palette(mid); }
QLabel#name { font-size: 17px; }
QLabel#hint { color: palette(placeholder-text); }
QToolButton#help { border: 1px solid palette(mid); border-radius: 8px; color: palette(placeholder-text);
                   font-size: 11px; font-weight: bold; padding: 0; min-width: 15px; max-width: 15px;
                   min-height: 15px; max-height: 15px; }
QToolButton#help:hover { color: palette(text); border-color: palette(text); }
QListWidget#steps { border: none; border-right: 1px solid palette(mid); padding: 12px 8px; font-size: 14px;
                     background: transparent; outline: none; }
QListWidget#steps::item { padding: 9px 10px; border-radius: 6px; }
QListWidget#steps::item:selected { background: palette(highlight); color: palette(highlighted-text); }
QGroupBox { font-weight: bold; }
"""
