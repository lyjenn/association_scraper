"""Scrape run loop: discovery, random pick, delays, hourly caps, proxy rotation."""

from __future__ import annotations

import logging
import random
import time
from datetime import datetime, timezone
from typing import Callable

from playwright.sync_api import sync_playwright

from scraper_app.db.models import AppSettings, Association
from scraper_app.db.repository import Repository
from scraper_app.proxy.manager import ProxyManager
from scraper_app.workflow.engine import WorkflowEngine

logger = logging.getLogger(__name__)

LogFn = Callable[[str], None]
StatusFn = Callable[[dict], None]


def current_hour_bucket() -> str:
    now = datetime.now(timezone.utc).replace(minute=0, second=0, microsecond=0)
    return now.isoformat().replace("+00:00", "Z")


class ScrapeRunner:
    def __init__(
        self,
        repo: Repository,
        association_ids: list[str],
        *,
        discover: bool = True,
        process: bool = True,
        log: LogFn | None = None,
        on_status: StatusFn | None = None,
    ) -> None:
        self.repo = repo
        self.association_ids = association_ids
        self.discover = discover
        self.process = process
        self.log = log or (lambda m: logger.info(m))
        self.on_status = on_status or (lambda d: None)
        self._stop = False
        self.settings = repo.load_settings()
        self.proxy_manager = ProxyManager.from_lines(
            repo.load_proxy_lines(),
            records_per_proxy=self.settings.records_per_proxy,
        )

    def stop(self) -> None:
        self._stop = True

    def run(self) -> None:
        associations = [
            a
            for aid in self.association_ids
            if (a := self.repo.get_association(aid)) and a.enabled
        ]
        if not associations:
            self.log("No enabled associations selected.")
            return

        with sync_playwright() as p:
            browser = p.chromium.launch(headless=self.settings.headless)
            context = self._new_context(browser)
            page = context.new_page()

            try:
                for assoc in associations:
                    if self._stop:
                        break
                    self.log(f"=== Association: {assoc.name} ===")
                    if self.discover:
                        engine = WorkflowEngine(
                            self.repo, page, assoc, log=self.log
                        )
                        result = engine.run_phase("discovery")
                        if not result.ok:
                            self.log(f"Discovery failed: {result.message}")

                    if not self.process:
                        continue

                    while not self._stop:
                        if not self._under_hourly_cap(assoc):
                            self.log(
                                f"Hourly cap reached for {assoc.name} "
                                f"({assoc.max_per_hour}/hour). Stopping this association."
                            )
                            break

                        record = self.repo.pick_random_pending(assoc.id)
                        if record is None:
                            self.log(f"No pending records for {assoc.name}.")
                            break

                        self.repo.update_record_status(record.id, "in_progress")
                        self._emit_status(assoc, record.source_url)

                        # Ensure we have a page/session
                        if page.is_closed():
                            context = self._new_context(browser)
                            page = context.new_page()

                        engine = WorkflowEngine(
                            self.repo, page, assoc, log=self.log
                        )
                        engine.set_current_record(record)
                        engine.buffer.clear()
                        result = engine.run_phase("record")

                        if result.ok:
                            self.repo.update_record_status(record.id, "done")
                            self.repo.increment_hour_count(assoc.id, current_hour_bucket())
                            self.log(f"Record done: {record.source_url}")
                        else:
                            self.repo.update_record_status(
                                record.id, "failed", error=result.message
                            )
                            self.log(f"Record failed: {result.message}")

                        # Proxy rotation after full record completes
                        self.proxy_manager.mark_record_complete()
                        if self.proxy_manager.should_rotate():
                            self.log(
                                "Records-per-proxy limit reached — rotating proxy session"
                            )
                            try:
                                context.close()
                            except Exception:
                                pass
                            self.proxy_manager.rotate()
                            context = self._new_context(browser)
                            page = context.new_page()
                            self.log(
                                f"New session with proxy: "
                                f"{self.proxy_manager.status_dict()['current_proxy']}"
                            )

                        self._emit_status(assoc, record.source_url)
                        self._variable_delay(assoc)
            finally:
                try:
                    context.close()
                except Exception:
                    pass
                browser.close()

        self.log("Scrape run finished.")

    def _new_context(self, browser):
        proxy = self.proxy_manager.playwright_proxy()
        if proxy:
            self.log(f"Opening browser session via {proxy.get('server')}")
            return browser.new_context(proxy=proxy)
        if self.proxy_manager.direct_mode:
            self.log("Opening browser session in DIRECT mode (no proxy)")
        return browser.new_context()

    def _under_hourly_cap(self, assoc: Association) -> bool:
        count = self.repo.get_hour_count(assoc.id, current_hour_bucket())
        return count < assoc.max_per_hour

    def _variable_delay(self, assoc: Association) -> None:
        lo = float(assoc.delay_min_seconds)
        hi = float(assoc.delay_max_seconds)
        if hi < lo:
            hi = lo
        # Mild long-tail: 80% uniform, 20% toward the high end
        if random.random() < 0.2 and hi > lo:
            delay = random.uniform((lo + hi) / 2, hi)
        else:
            delay = random.uniform(lo, hi)
        self.log(f"Waiting {delay:.1f}s before next record…")
        # Sleep in small chunks so stop() is responsive
        end = time.time() + delay
        while time.time() < end and not self._stop:
            time.sleep(min(0.25, end - time.time()))

    def _emit_status(self, assoc: Association, current_url: str) -> None:
        payload = {
            "association": assoc.name,
            "current_url": current_url,
            **self.proxy_manager.status_dict(),
        }
        self.on_status(payload)
