from __future__ import annotations

import sys

if __name__ == "__main__":
    # When run directly, add the parent directory to sys.path so absolute
    # imports resolve correctly.
    from pathlib import Path

    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from infrared_player.ui import MainWindow
else:
    from .ui import MainWindow


def run() -> int:
    from PySide6.QtWidgets import QApplication

    app = QApplication(sys.argv)
    window = MainWindow()
    window.show()
    return app.exec()
