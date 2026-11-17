"""Run Alcedo's work in a background thread, so the window stays responsive, and pass its events to the window."""

from __future__ import annotations

import contextlib
import io
from collections.abc import Callable

from PySide6.QtCore import QThread, Signal

from .. import events
from ..events import NOTICE, PROBLEM, Event


class Stopped(KeyboardInterrupt):
    """Raised inside the work when the person presses Stop. The search treats it like Ctrl+C: it saves and stops."""


class _Lines(io.TextIOBase):
    """Turn what a command prints into events, one per line, so messages of filter and export reach the window."""

    def __init__(self, kind: str) -> None:
        self.kind = kind
        self.pending = ""

    def write(self, text: str) -> int:
        self.pending += text
        while "\n" in self.pending:
            line, self.pending = self.pending.split("\n", 1)
            if line.strip():
                events.emit(self.kind, line)
        return len(text)


class Job(QThread):
    """One piece of work, such as a search or a filter run. Signals arrive in the window's own thread."""

    event = Signal(object)
    finished_with = Signal(int)

    def __init__(self, work: Callable[[], int], parent=None) -> None:
        super().__init__(parent)
        self.work = work
        self.stop_requested = self.stop_raised = False

    def stop(self) -> None:
        self.stop_requested = True

    def _listen(self, event: Event) -> None:
        self.event.emit(event)
        if self.stop_requested and not self.stop_raised:
            # Once is enough: the search then saves, reports that it stopped, and returns.
            self.stop_raised = True
            raise Stopped

    def run(self) -> None:
        code = 1
        with events.listening(self._listen), contextlib.redirect_stdout(_Lines(NOTICE)), \
                contextlib.redirect_stderr(_Lines(PROBLEM)):
            try:
                code = self.work()
            except Stopped:
                code = 130
            except SystemExit as exc:  # a command refused its options
                code = exc.code if isinstance(exc.code, int) else 2
            except Exception as exc:  # the window must survive anything the work runs into, and say what it was
                self.event.emit(Event(PROBLEM, f"Something went wrong: {type(exc).__name__}: {exc}"))
        self.finished_with.emit(code)
