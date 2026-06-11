from __future__ import annotations

import sys

from .ui import MainWindow


def run() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
