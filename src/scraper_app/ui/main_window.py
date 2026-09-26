"""Main desktop window for the Association Scraper."""

from __future__ import annotations

import json
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from threading import Thread

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QSpinBox,
    QDoubleSpinBox,
    QSplitter,
    QTabWidget,
    QTableWidget,
    QTableWidgetItem,
    QTextEdit,
    QVBoxLayout,
    QWidget,
    QAbstractItemView,
    QHeaderView,
)

from scraper_app.config import FIXTURES_DIR, supabase_configured
from scraper_app.db.models import Association, ScrapingStep, AppSettings, new_id
from scraper_app.db.repository import Repository
from scraper_app.demo import seed_demo_associations
from scraper_app.ui.workers import ScrapeWorker
from scraper_app.workflow.validation import validate_steps


ACTIONS = [
    "navigate",
    "find_records",
    "click",
    "wait",
    "extract_label_value",
    "extract_table",
    "follow_link",
    "next_page",
    "save",
    "fill",
    "select",
]

LOCATORS = ["", "css", "id", "class", "link_text", "button_text", "xpath"]


class FixtureServer:
    """Tiny static file server for practice HTML."""

    def __init__(self, directory: Path, port: int) -> None:
        self.directory = directory
        self.port = port
        self._httpd: ThreadingHTTPServer | None = None
        self._thread: Thread | None = None

    def start(self) -> str:
        directory = self.directory

        class Handler(SimpleHTTPRequestHandler):
            def __init__(self, *args, **kwargs):
                super().__init__(*args, directory=str(directory), **kwargs)

            def log_message(self, format, *args):  # noqa: A003
                return

        self._httpd = ThreadingHTTPServer(("127.0.0.1", self.port), Handler)
        self._thread = Thread(target=self._httpd.serve_forever, daemon=True)
        self._thread.start()
        return f"http://127.0.0.1:{self.port}"

    def stop(self) -> None:
        if self._httpd:
            self._httpd.shutdown()
            self._httpd = None


class MainWindow(QMainWindow):
    def __init__(self, repo: Repository | None = None) -> None:
        super().__init__()
        self.repo = repo or Repository()
        self.setWindowTitle("Association Scraper")
        self.resize(1100, 720)

        self._worker: ScrapeWorker | None = None
        self._servers: list[FixtureServer] = []

        tabs = QTabWidget()
        tabs.addTab(self._build_associations_tab(), "Associations")
        tabs.addTab(self._build_steps_tab(), "Scraping Method")
        tabs.addTab(self._build_proxies_tab(), "Proxies")
        tabs.addTab(self._build_run_tab(), "Run / Results")
        self.setCentralWidget(tabs)

        backend = self.repo.backend_name
        supabase = "Supabase configured" if supabase_configured() else "Local SQLite only"
        self.statusBar().showMessage(f"Storage: {backend} — {supabase}")

        self.refresh_associations()
        self.refresh_results()

    # ---------- Associations ----------

    def _build_associations_tab(self) -> QWidget:
        w = QWidget()
        layout = QHBoxLayout(w)

        left = QVBoxLayout()
        self.assoc_list = QListWidget()
        self.assoc_list.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.assoc_list.currentItemChanged.connect(self._on_assoc_selected)
        left.addWidget(QLabel("Associations (select one or more for a run)"))
        left.addWidget(self.assoc_list)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("Add")
        add_btn.clicked.connect(self._add_association)
        del_btn = QPushButton("Delete")
        del_btn.clicked.connect(self._delete_association)
        demo_btn = QPushButton("Load practice associations")
        demo_btn.clicked.connect(self._load_demo)
        btn_row.addWidget(add_btn)
        btn_row.addWidget(del_btn)
        btn_row.addWidget(demo_btn)
        left.addLayout(btn_row)

        form_box = QGroupBox("Edit association")
        form = QFormLayout(form_box)
        self.name_edit = QLineEdit()
        self.url_edit = QLineEdit()
        self.enabled_check = QCheckBox("Enabled")
        self.enabled_check.setChecked(True)
        self.max_hour_spin = QSpinBox()
        self.max_hour_spin.setRange(1, 1000)
        self.max_hour_spin.setValue(10)
        self.delay_min = QDoubleSpinBox()
        self.delay_min.setRange(0, 3600)
        self.delay_min.setValue(5)
        self.delay_max = QDoubleSpinBox()
        self.delay_max.setRange(0, 3600)
        self.delay_max.setValue(40)
        form.addRow("Name", self.name_edit)
        form.addRow("Website URL", self.url_edit)
        form.addRow(self.enabled_check)
        form.addRow("Max records / hour", self.max_hour_spin)
        form.addRow("Delay min (seconds)", self.delay_min)
        form.addRow("Delay max (seconds)", self.delay_max)
        save_btn = QPushButton("Save association")
        save_btn.clicked.connect(self._save_association)
        form.addRow(save_btn)

        layout.addLayout(left, 2)
        layout.addWidget(form_box, 3)
        self._current_assoc_id: str | None = None
        return w

    def refresh_associations(self) -> None:
        self.assoc_list.clear()
        self.steps_assoc_combo.blockSignals(True)
        self.steps_assoc_combo.clear()
        self.run_assoc_list.clear()
        for a in self.repo.list_associations():
            label = f"{'[on] ' if a.enabled else '[off] '}{a.name}"
            item = QListWidgetItem(label)
            item.setData(Qt.UserRole, a.id)
            self.assoc_list.addItem(item)
            self.steps_assoc_combo.addItem(a.name, a.id)
            run_item = QListWidgetItem(a.name)
            run_item.setData(Qt.UserRole, a.id)
            run_item.setFlags(run_item.flags() | Qt.ItemIsUserCheckable)
            run_item.setCheckState(Qt.Checked if a.enabled else Qt.Unchecked)
            self.run_assoc_list.addItem(run_item)
        self.steps_assoc_combo.blockSignals(False)

    def _on_assoc_selected(self, current: QListWidgetItem | None, _prev) -> None:
        if not current:
            return
        assoc = self.repo.get_association(current.data(Qt.UserRole))
        if not assoc:
            return
        self._current_assoc_id = assoc.id
        self.name_edit.setText(assoc.name)
        self.url_edit.setText(assoc.website_url)
        self.enabled_check.setChecked(assoc.enabled)
        self.max_hour_spin.setValue(assoc.max_per_hour)
        self.delay_min.setValue(assoc.delay_min_seconds)
        self.delay_max.setValue(assoc.delay_max_seconds)

    def _add_association(self) -> None:
        assoc = Association(id=new_id(), name="New Association", website_url="")
        self.repo.upsert_association(assoc)
        self.refresh_associations()
        # select it
        for i in range(self.assoc_list.count()):
            if self.assoc_list.item(i).data(Qt.UserRole) == assoc.id:
                self.assoc_list.setCurrentRow(i)
                break

    def _save_association(self) -> None:
        if not self._current_assoc_id:
            QMessageBox.information(self, "Save", "Select an association first.")
            return
        assoc = Association(
            id=self._current_assoc_id,
            name=self.name_edit.text().strip() or "Untitled",
            website_url=self.url_edit.text().strip(),
            enabled=self.enabled_check.isChecked(),
            max_per_hour=self.max_hour_spin.value(),
            delay_min_seconds=self.delay_min.value(),
            delay_max_seconds=self.delay_max.value(),
        )
        self.repo.upsert_association(assoc)
        self.refresh_associations()
        self.statusBar().showMessage(f"Saved {assoc.name}", 3000)

    def _delete_association(self) -> None:
        item = self.assoc_list.currentItem()
        if not item:
            return
        aid = item.data(Qt.UserRole)
        if QMessageBox.question(self, "Delete", "Delete this association and its steps?") != QMessageBox.Yes:
            return
        self.repo.delete_association(aid)
        self._current_assoc_id = None
        self.refresh_associations()

    def _load_demo(self) -> None:
        # Start fixture servers on uncommon ports
        for s in self._servers:
            s.stop()
        self._servers = []
        srv_a = FixtureServer(FIXTURES_DIR / "association_a", 43127)
        srv_b = FixtureServer(FIXTURES_DIR / "association_b", 43128)
        url_a = srv_a.start()
        url_b = srv_b.start()
        self._servers = [srv_a, srv_b]
        ids = seed_demo_associations(self.repo, url_a, url_b)
        self.refresh_associations()
        self.refresh_steps()
        QMessageBox.information(
            self,
            "Practice associations",
            "Loaded two practice associations with different page layouts.\n"
            f"Site A: {url_a}/index.html\n"
            f"Site B: {url_b}/search.html\n"
            f"IDs: {', '.join(ids)}",
        )

    # ---------- Steps editor ----------

    def _build_steps_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        top = QHBoxLayout()
        self.steps_assoc_combo = QComboBox()
        self.steps_assoc_combo.currentIndexChanged.connect(self.refresh_steps)
        self.phase_combo = QComboBox()
        self.phase_combo.addItems(["discovery", "record"])
        self.phase_combo.currentIndexChanged.connect(self.refresh_steps)
        top.addWidget(QLabel("Association"))
        top.addWidget(self.steps_assoc_combo, 2)
        top.addWidget(QLabel("Phase"))
        top.addWidget(self.phase_combo)
        layout.addLayout(top)

        self.steps_table = QTableWidget(0, 5)
        self.steps_table.setHorizontalHeaderLabels(
            ["Action", "Locator type", "Locator value", "Params (JSON)", "Enabled"]
        )
        self.steps_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        layout.addWidget(self.steps_table)

        btns = QHBoxLayout()
        for label, slot in [
            ("Add step", self._add_step_row),
            ("Delete step", self._delete_step_row),
            ("Move up", lambda: self._move_step(-1)),
            ("Move down", lambda: self._move_step(1)),
            ("Save steps", self._save_steps),
            ("Validate", self._validate_steps),
        ]:
            b = QPushButton(label)
            b.clicked.connect(slot)
            btns.addWidget(b)
        layout.addLayout(btns)
        hint = QLabel(
            "Each association has its own ordered recipe. "
            "Params JSON can include section, url, item_selector, optional, etc."
        )
        hint.setWordWrap(True)
        layout.addWidget(hint)
        return w

    def refresh_steps(self) -> None:
        self.steps_table.setRowCount(0)
        aid = self.steps_assoc_combo.currentData()
        if not aid:
            return
        phase = self.phase_combo.currentText()
        steps = self.repo.list_steps(aid, phase=phase)
        for step in steps:
            self._append_step_row(step)

    def _append_step_row(self, step: ScrapingStep | None = None) -> None:
        r = self.steps_table.rowCount()
        self.steps_table.insertRow(r)
        action = QComboBox()
        action.addItems(ACTIONS)
        if step:
            action.setCurrentText(step.action)
        loc = QComboBox()
        loc.addItems(LOCATORS)
        if step and step.locator_type:
            loc.setCurrentText(step.locator_type)
        val = QLineEdit(step.locator_value or "" if step else "")
        params = QTextEdit()
        params.setMaximumHeight(60)
        params.setPlainText(json.dumps(step.params if step else {}, indent=2))
        enabled = QCheckBox()
        enabled.setChecked(step.enabled if step else True)
        self.steps_table.setCellWidget(r, 0, action)
        self.steps_table.setCellWidget(r, 1, loc)
        self.steps_table.setCellWidget(r, 2, val)
        self.steps_table.setCellWidget(r, 3, params)
        self.steps_table.setCellWidget(r, 4, enabled)

    def _add_step_row(self) -> None:
        self._append_step_row(
            ScrapingStep(
                id=new_id(),
                association_id=self.steps_assoc_combo.currentData() or "",
                position=0,
                action="navigate",
                phase=self.phase_combo.currentText(),
            )
        )

    def _delete_step_row(self) -> None:
        r = self.steps_table.currentRow()
        if r >= 0:
            self.steps_table.removeRow(r)

    def _move_step(self, delta: int) -> None:
        r = self.steps_table.currentRow()
        if r < 0:
            return
        nr = r + delta
        if nr < 0 or nr >= self.steps_table.rowCount():
            return
        # Swap by reading and rewriting — simple approach: collect all, swap, reload
        steps = self._read_steps_from_table()
        steps[r], steps[nr] = steps[nr], steps[r]
        self.steps_table.setRowCount(0)
        for s in steps:
            self._append_step_row(s)
        self.steps_table.setCurrentCell(nr, 0)

    def _read_steps_from_table(self) -> list[ScrapingStep]:
        aid = self.steps_assoc_combo.currentData() or ""
        phase = self.phase_combo.currentText()
        steps: list[ScrapingStep] = []
        for r in range(self.steps_table.rowCount()):
            action = self.steps_table.cellWidget(r, 0).currentText()
            loc = self.steps_table.cellWidget(r, 1).currentText() or None
            val = self.steps_table.cellWidget(r, 2).text().strip() or None
            raw = self.steps_table.cellWidget(r, 3).toPlainText().strip() or "{}"
            try:
                params = json.loads(raw)
            except json.JSONDecodeError:
                params = {}
            enabled = self.steps_table.cellWidget(r, 4).isChecked()
            steps.append(
                ScrapingStep(
                    id=new_id(),
                    association_id=aid,
                    position=r,
                    action=action,
                    phase=phase,
                    locator_type=loc,
                    locator_value=val,
                    params=params,
                    enabled=enabled,
                )
            )
        return steps

    def _save_steps(self) -> None:
        aid = self.steps_assoc_combo.currentData()
        if not aid:
            return
        phase = self.phase_combo.currentText()
        new_steps = self._read_steps_from_table()
        # Keep the other phase intact
        other = [s for s in self.repo.list_steps(aid) if s.phase != phase]
        combined = other + new_steps
        # Re-number globally
        for i, s in enumerate(sorted(combined, key=lambda x: (0 if x.phase == "discovery" else 1, x.position))):
            s.position = i
        errors = validate_steps(combined)
        if errors:
            QMessageBox.warning(self, "Validation", "\n".join(errors[:12]))
            return
        # Sort discovery then record
        ordered = [s for s in combined if s.phase == "discovery"] + [
            s for s in combined if s.phase == "record"
        ]
        self.repo.replace_steps(aid, ordered)
        self.refresh_steps()
        self.statusBar().showMessage("Steps saved", 3000)

    def _validate_steps(self) -> None:
        steps = self._read_steps_from_table()
        errors = validate_steps(steps)
        if errors:
            QMessageBox.warning(self, "Validation", "\n".join(errors[:20]))
        else:
            QMessageBox.information(self, "Validation", "All steps look valid.")

    # ---------- Proxies ----------

    def _build_proxies_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        layout.addWidget(QLabel(
            "Paste one HTTP/SOCKS proxy per line, for example:\n"
            "http://user:pass@host:8080\nsocks5://host:1080"
        ))
        self.proxy_edit = QTextEdit()
        self.proxy_edit.setPlainText("\n".join(self.repo.load_proxy_lines()))
        layout.addWidget(self.proxy_edit)

        form = QFormLayout()
        settings = self.repo.load_settings()
        self.records_per_proxy = QSpinBox()
        self.records_per_proxy.setRange(1, 1000)
        self.records_per_proxy.setValue(settings.records_per_proxy)
        self.headless_check = QCheckBox("Run browser headless")
        self.headless_check.setChecked(settings.headless)
        form.addRow("Records per proxy", self.records_per_proxy)
        form.addRow(self.headless_check)
        layout.addLayout(form)

        save = QPushButton("Save proxy settings")
        save.clicked.connect(self._save_proxies)
        layout.addWidget(save)

        self.proxy_status = QLabel("Proxy status: (idle)")
        self.proxy_status.setWordWrap(True)
        layout.addWidget(self.proxy_status)
        return w

    def _save_proxies(self) -> None:
        lines = [ln.strip() for ln in self.proxy_edit.toPlainText().splitlines() if ln.strip()]
        self.repo.save_proxy_lines(lines)
        settings = AppSettings(
            records_per_proxy=self.records_per_proxy.value(),
            headless=self.headless_check.isChecked(),
        )
        self.repo.save_settings(settings)
        if not lines:
            self.proxy_status.setText(
                "Saved. No proxies configured — runs will use DIRECT mode (warning)."
            )
        else:
            self.proxy_status.setText(
                f"Saved {len(lines)} proxies. Records per proxy = {settings.records_per_proxy}."
            )

    # ---------- Run / Results ----------

    def _build_run_tab(self) -> QWidget:
        w = QWidget()
        layout = QVBoxLayout(w)
        splitter = QSplitter(Qt.Horizontal)

        left = QWidget()
        left_l = QVBoxLayout(left)
        left_l.addWidget(QLabel("Select associations to scrape"))
        self.run_assoc_list = QListWidget()
        left_l.addWidget(self.run_assoc_list)
        btns = QHBoxLayout()
        self.start_btn = QPushButton("Start (discover + process)")
        self.start_btn.clicked.connect(lambda: self._start_run(True, True))
        self.discover_btn = QPushButton("Discover only")
        self.discover_btn.clicked.connect(lambda: self._start_run(True, False))
        self.stop_btn = QPushButton("Stop")
        self.stop_btn.clicked.connect(self._stop_run)
        self.stop_btn.setEnabled(False)
        btns.addWidget(self.start_btn)
        btns.addWidget(self.discover_btn)
        btns.addWidget(self.stop_btn)
        left_l.addLayout(btns)
        self.run_status = QLabel("Ready.")
        self.run_status.setWordWrap(True)
        left_l.addWidget(self.run_status)
        left_l.addWidget(QLabel("Log"))
        self.log_view = QTextEdit()
        self.log_view.setReadOnly(True)
        left_l.addWidget(self.log_view)

        right = QWidget()
        right_l = QVBoxLayout(right)
        refresh = QPushButton("Refresh results")
        refresh.clicked.connect(self.refresh_results)
        export = QPushButton("Export selected JSON")
        export.clicked.connect(self._export_result)
        row = QHBoxLayout()
        row.addWidget(refresh)
        row.addWidget(export)
        right_l.addLayout(row)
        self.results_table = QTableWidget(0, 4)
        self.results_table.setHorizontalHeaderLabels(
            ["Association", "Source URL", "Scraped at", "scraped_data"]
        )
        self.results_table.horizontalHeader().setSectionResizeMode(3, QHeaderView.Stretch)
        self.results_table.itemSelectionChanged.connect(self._show_result_detail)
        right_l.addWidget(self.results_table)
        self.result_detail = QTextEdit()
        self.result_detail.setReadOnly(True)
        right_l.addWidget(self.result_detail)

        splitter.addWidget(left)
        splitter.addWidget(right)
        splitter.setSizes([450, 650])
        layout.addWidget(splitter)
        return w

    def _selected_run_ids(self) -> list[str]:
        ids = []
        for i in range(self.run_assoc_list.count()):
            item = self.run_assoc_list.item(i)
            if item.checkState() == Qt.Checked:
                ids.append(item.data(Qt.UserRole))
        return ids

    def _start_run(self, discover: bool, process: bool) -> None:
        ids = self._selected_run_ids()
        if not ids:
            QMessageBox.information(self, "Run", "Check at least one association.")
            return
        # Persist proxy settings from UI first
        self._save_proxies()
        self.log_view.clear()
        self.start_btn.setEnabled(False)
        self.discover_btn.setEnabled(False)
        self.stop_btn.setEnabled(True)
        self._worker = ScrapeWorker(ids, discover=discover, process=process)
        self._worker.log_line.connect(self._append_log)
        self._worker.status.connect(self._on_run_status)
        self._worker.finished_ok.connect(self._run_finished)
        self._worker.failed.connect(self._run_failed)
        self._worker.start()

    def _stop_run(self) -> None:
        if self._worker:
            self._worker.request_stop()
            self._append_log("Stop requested…")

    def _append_log(self, line: str) -> None:
        self.log_view.append(line)

    def _on_run_status(self, data: dict) -> None:
        self.run_status.setText(
            f"Association: {data.get('association')} | "
            f"Proxy: {data.get('current_proxy')} | "
            f"Records on proxy: {data.get('records_on_current')}/"
            f"{data.get('records_per_proxy')} | "
            f"Last rotation: {data.get('last_rotation')}"
        )
        self.proxy_status.setText(
            f"Current proxy: {data.get('current_proxy')} | "
            f"Index: {data.get('current_proxy_index')} | "
            f"Count: {data.get('records_on_current')} | "
            f"Status: {data.get('proxy_status')} | "
            f"Last rotation: {data.get('last_rotation')}"
        )

    def _run_finished(self) -> None:
        self.start_btn.setEnabled(True)
        self.discover_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        self.refresh_results()
        self.statusBar().showMessage("Run finished", 5000)

    def _run_failed(self, err: str) -> None:
        self.start_btn.setEnabled(True)
        self.discover_btn.setEnabled(True)
        self.stop_btn.setEnabled(False)
        QMessageBox.critical(self, "Run failed", err)

    def refresh_results(self) -> None:
        self.results_table.setRowCount(0)
        assoc_names = {a.id: a.name for a in self.repo.list_associations()}
        for row in self.repo.list_scraped_records():
            r = self.results_table.rowCount()
            self.results_table.insertRow(r)
            self.results_table.setItem(
                r, 0, QTableWidgetItem(assoc_names.get(row.association_id, row.association_id))
            )
            self.results_table.setItem(r, 1, QTableWidgetItem(row.source_url))
            self.results_table.setItem(r, 2, QTableWidgetItem(row.scraped_at))
            preview = json.dumps(row.scraped_data)[:120]
            item = QTableWidgetItem(preview)
            item.setData(Qt.UserRole, row)
            self.results_table.setItem(r, 3, item)

    def _show_result_detail(self) -> None:
        items = self.results_table.selectedItems()
        if not items:
            return
        row = items[0].row()
        item = self.results_table.item(row, 3)
        scraped = item.data(Qt.UserRole)
        if scraped:
            self.result_detail.setPlainText(json.dumps(scraped.scraped_data, indent=2))

    def _export_result(self) -> None:
        items = self.results_table.selectedItems()
        if not items:
            QMessageBox.information(self, "Export", "Select a result row first.")
            return
        row = items[0].row()
        scraped = self.results_table.item(row, 3).data(Qt.UserRole)
        if not scraped:
            return
        path = Path("data") / f"export_{scraped.record_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps({
            "record_id": scraped.record_id,
            "association_id": scraped.association_id,
            "source_url": scraped.source_url,
            "scraped_at": scraped.scraped_at,
            "scraped_data": scraped.scraped_data,
        }, indent=2), encoding="utf-8")
        QMessageBox.information(self, "Export", f"Wrote {path}")

    def closeEvent(self, event) -> None:  # noqa: N802
        for s in self._servers:
            s.stop()
        if self._worker and self._worker.isRunning():
            self._worker.request_stop()
            self._worker.wait(3000)
        event.accept()
