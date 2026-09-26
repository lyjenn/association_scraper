"""Config-driven Playwright workflow engine."""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass, field
from typing import Any, Callable
from urllib.parse import urljoin

from scraper_app.db.models import Association, Record, ScrapingStep
from scraper_app.db.repository import Repository
from scraper_app.workflow.extractors import ExtractBuffer, parse_table
from scraper_app.workflow.locators import resolve_locator

logger = logging.getLogger(__name__)

LogFn = Callable[[str], None]


@dataclass
class WorkflowResult:
    ok: bool
    message: str = ""
    discovered: list[dict[str, str]] = field(default_factory=list)
    scraped_data: dict[str, Any] = field(default_factory=dict)


class WorkflowEngine:
    """
    Loads an association's steps and executes them in order.
    Does not hard-code any association-specific page layout.
    """

    def __init__(
        self,
        repo: Repository,
        page: Any,
        association: Association,
        *,
        log: LogFn | None = None,
    ) -> None:
        self.repo = repo
        self.page = page
        self.association = association
        self.log = log or (lambda msg: logger.info(msg))
        self.buffer = ExtractBuffer()
        self._current_record: Record | None = None
        self._base_url = association.website_url or ""

    def set_current_record(self, record: Record | None) -> None:
        self._current_record = record

    def run_phase(self, phase: str) -> WorkflowResult:
        steps = [
            s
            for s in self.repo.list_steps(self.association.id, phase=phase)
            if s.enabled
        ]
        steps.sort(key=lambda s: s.position)
        discovered: list[dict[str, str]] = []
        try:
            for step in steps:
                self.log(f"Step [{phase}] {step.position}: {step.action}")
                result = self._run_step(step)
                if step.action == "find_records" and result.get("discovered"):
                    discovered.extend(result["discovered"])
                if step.action == "next_page" and result.get("discovered"):
                    discovered.extend(result["discovered"])
            if phase == "discovery" and discovered:
                n = self.repo.upsert_discovered_records(self.association.id, discovered)
                self.log(f"Discovered {len(discovered)} links ({n} new)")
            return WorkflowResult(
                ok=True,
                discovered=discovered,
                scraped_data=self.buffer.to_dict(),
            )
        except Exception as exc:
            self.log(f"Workflow error: {exc}")
            return WorkflowResult(ok=False, message=str(exc), discovered=discovered)

    def run_single_step(self, step: ScrapingStep) -> WorkflowResult:
        try:
            self._run_step(step)
            return WorkflowResult(ok=True, scraped_data=self.buffer.to_dict())
        except Exception as exc:
            return WorkflowResult(ok=False, message=str(exc))

    def _run_step(self, step: ScrapingStep) -> dict[str, Any]:
        action = step.action
        params = step.params or {}
        optional = bool(params.get("optional", False))

        handlers = {
            "navigate": self._action_navigate,
            "find_records": self._action_find_records,
            "click": self._action_click,
            "wait": self._action_wait,
            "extract_label_value": self._action_extract_label_value,
            "extract_table": self._action_extract_table,
            "follow_link": self._action_follow_link,
            "next_page": self._action_next_page,
            "save": self._action_save,
            "fill": self._action_fill,
            "select": self._action_select,
        }
        handler = handlers.get(action)
        if handler is None:
            raise ValueError(f"Unknown action: {action}")
        try:
            return handler(step) or {}
        except Exception:
            if optional:
                self.log(f"Optional step skipped: {action}")
                return {}
            raise

    def _template(self, text: str) -> str:
        if not text:
            return text
        out = text.replace("{{start.url}}", self.association.website_url or "")
        if self._current_record:
            out = out.replace("{{record.detail_url}}", self._current_record.source_url)
            out = out.replace("{{record.source_url}}", self._current_record.source_url)
        return out

    def _action_navigate(self, step: ScrapingStep) -> dict[str, Any]:
        params = step.params or {}
        url = params.get("url") or step.locator_value or self.association.website_url
        url = self._template(str(url))
        if not url:
            raise ValueError("navigate requires a url")
        self.log(f"Navigate → {url}")
        self.page.goto(url, wait_until=params.get("wait_until", "domcontentloaded"))
        self._base_url = url
        return {}

    def _action_click(self, step: ScrapingStep) -> dict[str, Any]:
        loc = resolve_locator(self.page, step.locator_type, step.locator_value)
        self.log(f"Click → {step.locator_type}={step.locator_value}")
        loc.first.click(timeout=(step.params or {}).get("timeout_ms", 15000))
        return {}

    def _action_wait(self, step: ScrapingStep) -> dict[str, Any]:
        params = step.params or {}
        if step.locator_type and step.locator_value:
            loc = resolve_locator(self.page, step.locator_type, step.locator_value)
            loc.first.wait_for(
                state=params.get("state", "visible"),
                timeout=params.get("timeout_ms", 15000),
            )
        else:
            ms = int(params.get("timeout_ms", params.get("ms", 1000)))
            self.page.wait_for_timeout(ms)
        return {}

    def _action_fill(self, step: ScrapingStep) -> dict[str, Any]:
        params = step.params or {}
        value = self._template(str(params.get("value", "")))
        loc = resolve_locator(self.page, step.locator_type, step.locator_value)
        loc.first.fill(value)
        return {}

    def _action_select(self, step: ScrapingStep) -> dict[str, Any]:
        params = step.params or {}
        value = str(params.get("value", ""))
        loc = resolve_locator(self.page, step.locator_type, step.locator_value)
        loc.first.select_option(value)
        return {}

    def _action_follow_link(self, step: ScrapingStep) -> dict[str, Any]:
        loc = resolve_locator(self.page, step.locator_type, step.locator_value)
        href = loc.first.get_attribute("href")
        if href:
            url = urljoin(self.page.url, href)
            self.page.goto(url, wait_until="domcontentloaded")
        else:
            loc.first.click()
        return {}

    def _action_find_records(self, step: ScrapingStep) -> dict[str, Any]:
        params = step.params or {}
        loc = resolve_locator(self.page, step.locator_type, step.locator_value)
        count = loc.count()
        discovered: list[dict[str, str]] = []
        attr = params.get("url_attr", "href")
        for i in range(count):
            el = loc.nth(i)
            href = el.get_attribute(attr) if attr != "text" else None
            if attr == "text" or not href:
                # Use current page + text as fallback identity
                text = (el.inner_text() or "").strip()
                href = el.get_attribute("href")
                if not href:
                    continue
            url = urljoin(self.page.url, href)
            external_id = None
            id_attr = params.get("id_attr")
            if id_attr:
                external_id = el.get_attribute(id_attr)
            if not external_id:
                external_id = url.rstrip("/").split("/")[-1]
            discovered.append({"source_url": url, "external_id": external_id or url})
        # de-dupe by url
        seen: set[str] = set()
        unique: list[dict[str, str]] = []
        for item in discovered:
            if item["source_url"] not in seen:
                seen.add(item["source_url"])
                unique.append(item)
        self.log(f"Found {len(unique)} records on page")
        return {"discovered": unique}

    def _action_next_page(self, step: ScrapingStep) -> dict[str, Any]:
        """Click next until gone or max_pages; re-run find_records selector from params."""
        params = step.params or {}
        max_pages = int(params.get("max_pages", 5))
        find_type = params.get("find_locator_type") or step.locator_type
        find_value = params.get("find_locator_value") or step.locator_value
        next_type = params.get("next_locator_type", "css")
        next_value = params.get("next_locator_value")
        if not next_value:
            raise ValueError("next_page requires params.next_locator_value")

        all_discovered: list[dict[str, str]] = []
        # Collect current page first if find locators provided
        if find_type and find_value:
            fake = ScrapingStep(
                id="tmp",
                association_id=self.association.id,
                position=0,
                action="find_records",
                locator_type=find_type,
                locator_value=find_value,
                params=params,
            )
            all_discovered.extend(self._action_find_records(fake).get("discovered", []))

        for _ in range(max_pages - 1):
            try:
                nxt = resolve_locator(self.page, next_type, next_value)
                if nxt.count() == 0:
                    break
                # disabled?
                cls = nxt.first.get_attribute("class") or ""
                if "disabled" in cls.lower():
                    break
                nxt.first.click()
                self.page.wait_for_timeout(int(params.get("pause_ms", 500)))
                if find_type and find_value:
                    fake = ScrapingStep(
                        id="tmp",
                        association_id=self.association.id,
                        position=0,
                        action="find_records",
                        locator_type=find_type,
                        locator_value=find_value,
                        params=params,
                    )
                    all_discovered.extend(
                        self._action_find_records(fake).get("discovered", [])
                    )
            except Exception as exc:
                self.log(f"Pagination stopped: {exc}")
                break

        seen: set[str] = set()
        unique = []
        for item in all_discovered:
            if item["source_url"] not in seen:
                seen.add(item["source_url"])
                unique.append(item)
        return {"discovered": unique}

    def _action_extract_label_value(self, step: ScrapingStep) -> dict[str, Any]:
        params = step.params or {}
        section = params.get("section", "General")
        # Mode 1: structured item rows
        item_selector = params.get("item_selector")
        label_selector = params.get("label_selector", ".label")
        value_selector = params.get("value_selector", ".value")
        pairs: dict[str, str] = {}

        if item_selector:
            root = self.page.locator(item_selector)
            for i in range(root.count()):
                item = root.nth(i)
                label = item.locator(label_selector).first
                value = item.locator(value_selector).first
                if label.count() == 0:
                    continue
                lt = (label.inner_text() or "").strip().rstrip(":")
                vt = (value.inner_text() or "").strip() if value.count() else ""
                if lt:
                    pairs[lt] = vt
        elif step.locator_type and step.locator_value:
            # Mode 2: container holds dl/dt/dd or .label/.value
            container = resolve_locator(self.page, step.locator_type, step.locator_value)
            # Try dt/dd
            dts = container.locator("dt")
            if dts.count() > 0:
                for i in range(dts.count()):
                    lt = (dts.nth(i).inner_text() or "").strip().rstrip(":")
                    dd = dts.nth(i).locator("xpath=following-sibling::dd[1]")
                    vt = (dd.inner_text() or "").strip() if dd.count() else ""
                    if lt:
                        pairs[lt] = vt
            else:
                items = container.locator(params.get("row_selector", ".field, .row, li"))
                for i in range(items.count()):
                    item = items.nth(i)
                    lab = item.locator(label_selector)
                    val = item.locator(value_selector)
                    if lab.count() == 0:
                        # "Label: value" plain text
                        text = (item.inner_text() or "").strip()
                        if ":" in text:
                            left, right = text.split(":", 1)
                            pairs[left.strip()] = right.strip()
                        continue
                    lt = (lab.first.inner_text() or "").strip().rstrip(":")
                    vt = (val.first.inner_text() or "").strip() if val.count() else ""
                    if lt:
                        pairs[lt] = vt
        else:
            raise ValueError("extract_label_value needs a container locator or item_selector")

        # Optional static pairs from params (for testing)
        if params.get("pairs"):
            pairs.update({str(k): str(v) for k, v in params["pairs"].items()})

        self.buffer.merge_label_values(section, pairs)
        self.log(f"Extracted {len(pairs)} fields into section {section!r}")
        return {"pairs": pairs}

    def _action_extract_table(self, step: ScrapingStep) -> dict[str, Any]:
        params = step.params or {}
        section = params.get("section", "Table")
        loc = resolve_locator(self.page, step.locator_type, step.locator_value)
        rows = parse_table(self.page, loc.first)
        self.buffer.set_table(section, rows)
        self.log(f"Extracted table {section!r} with {len(rows)} rows")
        return {"rows": rows}

    def _action_save(self, step: ScrapingStep) -> dict[str, Any]:
        source_url = (
            self._current_record.source_url
            if self._current_record
            else self.page.url
        )
        record_id = self._current_record.id if self._current_record else None
        data = self.buffer.to_dict()
        saved = self.repo.save_scraped_record(
            self.association.id,
            source_url,
            data,
            record_id=record_id,
        )
        self.log(f"Saved scraped_record {saved.record_id}")
        return {"record_id": saved.record_id}
