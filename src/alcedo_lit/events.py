"""Events from a search: what it is doing and what went wrong, kept apart from how they are shown.

The command line shows them through `Console`, exactly as it printed them before. An interface can listen instead:

    with events.listening(my_listener):
        pipeline.run(args)

While a listener is set, nothing is printed.
"""

from __future__ import annotations

import sys
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from dataclasses import dataclass, field

from tqdm import tqdm

NOTICE = "notice"  # information for the person running Alcedo
PROBLEM = "problem"  # something is wrong or needs their attention
NOTE = "note"  # a remark during the search, such as a source that failed for one query
STARTED = "started"  # the search began; data: total, done
STATUS = "status"  # what the search is doing now, such as the query and page
STEP = "step"  # one more query is finished; data: query
STOPPED = "stopped"  # the search ended, finished or not
FINISHED = "finished"  # the counts of the run; data: the summary


@dataclass(frozen=True)
class Event:
    kind: str
    text: str = ""
    data: dict = field(default_factory=dict)


Listener = Callable[[Event], None]
_listeners: list[Listener] = []


class Console:
    """Show events in the terminal, with a progress bar for the queries."""

    def __init__(self) -> None:
        self.bar: tqdm | None = None

    def __call__(self, event: Event) -> None:
        if event.kind == STARTED:
            self.bar = tqdm(total=event.data["total"], initial=event.data["done"], desc="Queries", unit="query")
        elif event.kind == STATUS and self.bar is not None:
            self.bar.set_postfix_str(event.text)
        elif event.kind == STEP and self.bar is not None:
            self.bar.update()
        elif event.kind == STOPPED and self.bar is not None:
            self.bar.close()
            self.bar = None
        elif event.kind == NOTE:
            tqdm.write(event.text)
        elif event.kind == NOTICE:
            print(event.text)
        elif event.kind == PROBLEM:
            print(event.text, file=sys.stderr)


_console = Console()


def on_terminal() -> bool:
    """Tell whether events go to the terminal. Progress bars of single steps are drawn only then."""
    return not _listeners


def emit(kind: str, text: str = "", **data) -> None:
    event = Event(kind, text, data)
    for listener in list(_listeners) or [_console]:
        listener(event)


@contextmanager
def listening(listener: Listener) -> Iterator[None]:
    """Send events to `listener` instead of the terminal while the block runs."""
    _listeners.append(listener)
    try:
        yield
    finally:
        _listeners.remove(listener)


class Progress:
    """Report the progress of the queries as events, with the calls a tqdm bar takes."""

    def __init__(self, total: int, done: int) -> None:
        emit(STARTED, total=total, done=done)

    def set_postfix_str(self, text: str) -> None:
        emit(STATUS, text)

    def update(self, query: str | None = None) -> None:
        emit(STEP, query=query)

    def close(self) -> None:
        emit(STOPPED)
