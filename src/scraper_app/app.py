"""QApplication bootstrap."""

from __future__ import annotations

import logging
import os
import sys

from scraper_app.db.repository import get_repository


def run_app(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv)
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )

    # Allow headless CI / cloud environments without a display
    if not os.environ.get("DISPLAY") and not os.environ.get("WAYLAND_DISPLAY"):
        os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

    from PySide6.QtWidgets import QApplication

    from scraper_app.ui.main_window import MainWindow

    app = QApplication(argv)
    app.setApplicationName("Association Scraper")
    repo = get_repository()
    window = MainWindow(repo)
    window.show()
    return app.exec()
