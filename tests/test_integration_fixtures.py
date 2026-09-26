"""End-to-end scrape against the two practice fixture sites."""

from __future__ import annotations

import socket
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

import pytest
from playwright.sync_api import sync_playwright


def _free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return int(sock.getsockname()[1])

from scraper_app.config import FIXTURES_DIR
from scraper_app.db.models import AppSettings
from scraper_app.db.repository import Repository
from scraper_app.demo import seed_demo_associations
from scraper_app.proxy.manager import ProxyManager
from scraper_app.scheduler.runner import ScrapeRunner


class _Server:
    def __init__(self, directory: Path, port: int) -> None:
        self.directory = directory
        self.port = port
        self._httpd = None

    def start(self) -> str:
        directory = self.directory

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(directory), **kwargs)

            def log_message(self, format, *args):  # noqa: A003
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self.port = self._httpd.server_address[1]
        Thread(target=self._httpd.serve_forever, daemon=True).start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()


@pytest.fixture()
def fixture_env(tmp_path: Path):
    srv_a = _Server(FIXTURES_DIR / "association_a", _free_port())
    srv_b = _Server(FIXTURES_DIR / "association_b", _free_port())
    url_a = srv_a.start()
    url_b = srv_b.start()
    assert ":0/" not in url_a and ":0/" not in url_b
    repo = Repository(sqlite_path=tmp_path / "int.db")
    # Redirect settings/proxies to tmp via monkeypatch of module paths would be nicer;
    # for runner we pass repo and set settings on repo paths — override by writing
    # through repo after patching is hard. Instead set on the repo's load methods
    # by writing to the real settings would pollute. We'll configure via repo methods
    # but Settings use global paths. Patch them for this test.
    from scraper_app import config as cfg
    import scraper_app.db.repository as repomod

    settings_path = tmp_path / "settings.json"
    proxies_path = tmp_path / "proxies.json"
    old_settings = cfg.SETTINGS_PATH
    old_proxies = cfg.PROXIES_PATH
    cfg.SETTINGS_PATH = settings_path
    cfg.PROXIES_PATH = proxies_path
    repomod.SETTINGS_PATH = settings_path
    repomod.PROXIES_PATH = proxies_path

    repo.save_settings(AppSettings(records_per_proxy=2, headless=True))
    repo.save_proxy_lines([])  # direct mode for CI
    ids = seed_demo_associations(repo, url_a, url_b)
    # Speed up delays already set in seed
    yield repo, ids
    srv_a.stop()
    srv_b.stop()
    cfg.SETTINGS_PATH = old_settings
    cfg.PROXIES_PATH = old_proxies
    repomod.SETTINGS_PATH = old_settings
    repomod.PROXIES_PATH = old_proxies


def test_two_associations_different_scraped_shapes(fixture_env):
    repo, ids = fixture_env
    runner = ScrapeRunner(repo, ids, discover=True, process=True)
    runner.run()

    all_rows = repo.list_scraped_records()
    assert len(all_rows) >= 4  # 3+3 but hourly/process all with high max

    by_assoc = {}
    for row in all_rows:
        by_assoc.setdefault(row.association_id, []).append(row)

    assert set(by_assoc.keys()) == set(ids)

    a_data = by_assoc[ids[0]][0].scraped_data
    b_data = by_assoc[ids[1]][0].scraped_data

    assert "General Profile Information" in a_data
    assert "Contacts" in a_data
    assert isinstance(a_data["Contacts"], list)

    assert "Breeder Information" in b_data
    assert "Animals" in b_data
    assert "General Profile Information" not in b_data
    assert "Herd Prefix" not in str(b_data)


def test_proxy_manager_sticky_then_rotate_unit():
    """Document sticky rule: rotate only after mark_record_complete N times."""
    mgr = ProxyManager.from_lines(
        ["http://127.0.0.1:1", "http://127.0.0.1:2"], records_per_proxy=2
    )
    first = mgr.current
    # mid-record: no rotate API called
    assert first.port == 1
    mgr.mark_record_complete()
    assert mgr.current.port == 1
    mgr.mark_record_complete()
    assert mgr.should_rotate()
    mgr.rotate()
    assert mgr.current.port == 2


def test_discovery_only_playwright(fixture_env):
    repo, ids = fixture_env
    assoc = repo.get_association(ids[0])
    assert assoc
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        page = browser.new_page()
        from scraper_app.workflow.engine import WorkflowEngine

        engine = WorkflowEngine(repo, page, assoc)
        result = engine.run_phase("discovery")
        browser.close()
    assert result.ok
    pending = repo.list_records(assoc.id, status="pending")
    assert len(pending) == 3
