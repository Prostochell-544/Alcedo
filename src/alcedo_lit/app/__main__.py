"""Start the desktop application: `alcedo app`, `alcedo-app`, `python -m alcedo_lit.app`, or Alcedo.exe."""

from __future__ import annotations

import os
import sys
import traceback

INSTALL_HINT = 'pip install "alcedo-lit[app]"'


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    for name in ("stdout", "stderr"):  # a windowed program has no console, and printing must not fail
        if getattr(sys, name) is None:
            setattr(sys, name, open(os.devnull, "w", encoding="utf-8"))
    self_check = "--self-check" in argv  # used by the build: the program starts and makes its window, then quits
    if self_check:
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError:
        print(f"The desktop application needs one more package. Install it with: {INSTALL_HINT}", file=sys.stderr)
        return 1
    from .window import STYLE, MainWindow

    app = QApplication.instance() or QApplication(sys.argv[:1])
    app.setApplicationName("Alcedo")
    app.setStyleSheet(STYLE)
    if self_check:  # an error must end the check with a code, not wait in a dialog
        try:
            MainWindow().close()
        except Exception:
            traceback.print_exc()
            return 1
        return 0
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())
