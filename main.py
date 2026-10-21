"""Application entry point."""

from __future__ import annotations

import sys

from PySide6.QtWidgets import QApplication

from translator import close_translator
from ui import MainWindow


def main() -> int:
    app = QApplication(sys.argv)
    app.aboutToQuit.connect(close_translator)
    window = MainWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
