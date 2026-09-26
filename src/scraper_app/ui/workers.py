"""Background QThread workers for scraping."""

from __future__ import annotations

from PySide6.QtCore import QThread, Signal

from scraper_app.db.repository import Repository
from scraper_app.scheduler.runner import ScrapeRunner


class ScrapeWorker(QThread):
    log_line = Signal(str)
    status = Signal(dict)
    finished_ok = Signal()
    failed = Signal(str)

    def __init__(
        self,
        association_ids: list[str],
        *,
        discover: bool = True,
        process: bool = True,
        parent=None,
    ) -> None:
        super().__init__(parent)
        self.association_ids = association_ids
        self.discover = discover
        self.process = process
        self._runner: ScrapeRunner | None = None

    def run(self) -> None:
        try:
            repo = Repository()
            self._runner = ScrapeRunner(
                repo,
                self.association_ids,
                discover=self.discover,
                process=self.process,
                log=lambda m: self.log_line.emit(m),
                on_status=lambda d: self.status.emit(d),
            )
            self._runner.run()
            self.finished_ok.emit()
        except Exception as exc:
            self.failed.emit(str(exc))

    def request_stop(self) -> None:
        if self._runner:
            self._runner.stop()
