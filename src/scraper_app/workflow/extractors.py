"""Build scraped_data JSON from label/value pairs and tables."""

from __future__ import annotations

from typing import Any


class ExtractBuffer:
    """In-memory builder for association-specific scraped_data."""

    def __init__(self) -> None:
        self.data: dict[str, Any] = {}

    def clear(self) -> None:
        self.data = {}

    def merge_label_values(self, section: str, pairs: dict[str, str]) -> None:
        section = section or "General"
        existing = self.data.get(section)
        if existing is None:
            self.data[section] = dict(pairs)
        elif isinstance(existing, dict):
            existing.update(pairs)
        else:
            # Section was a table/list; keep both under a suffixed key
            self.data[f"{section} (fields)"] = dict(pairs)

    def set_table(self, section: str, rows: list[dict[str, str]]) -> None:
        section = section or "Table"
        self.data[section] = rows

    def to_dict(self) -> dict[str, Any]:
        return dict(self.data)


def parse_label_value_elements(
    page: Any,
    container_selector: str | None,
    label_selector: str,
    value_selector: str,
) -> dict[str, str]:
    """
    Read repeating label/value nodes.

    Expects each item to contain a label element and a value element.
    If container_selector is set, search inside it; otherwise page-wide items
    are found via the parent of label_selector matches.
    """
    pairs: dict[str, str] = {}
    root = page.locator(container_selector) if container_selector else page.locator("body")
    # Prefer structured rows: elements matching an item selector in params,
    # but if not provided, find all labels and sibling/nearby values.
    labels = root.locator(label_selector)
    count = labels.count()
    for i in range(count):
        label_el = labels.nth(i)
        label_text = (label_el.inner_text() or "").strip().rstrip(":")
        # Try value as sibling via parent
        parent = label_el.locator("xpath=..")
        value_el = parent.locator(value_selector).first
        if value_el.count() == 0:
            continue
        value_text = (value_el.inner_text() or "").strip()
        if label_text:
            pairs[label_text] = value_text
    return pairs


def parse_table(page: Any, table_locator) -> list[dict[str, str]]:
    """Read a table; first row or thead becomes column labels."""
    rows_out: list[dict[str, str]] = []
    # headers
    header_cells = table_locator.locator("thead tr th, thead tr td")
    headers: list[str] = []
    if header_cells.count() > 0:
        for i in range(header_cells.count()):
            headers.append((header_cells.nth(i).inner_text() or "").strip())
        body_rows = table_locator.locator("tbody tr")
    else:
        first = table_locator.locator("tr").first
        ths = first.locator("th, td")
        for i in range(ths.count()):
            headers.append((ths.nth(i).inner_text() or "").strip())
        body_rows = table_locator.locator("tr").nth(1)
        # all tr after first
        all_tr = table_locator.locator("tr")
        # rebuild as locator list via indexing
        body_count = all_tr.count()
        for r in range(1, body_count):
            cells = all_tr.nth(r).locator("td, th")
            row: dict[str, str] = {}
            for c in range(cells.count()):
                key = headers[c] if c < len(headers) and headers[c] else f"Column {c + 1}"
                row[key] = (cells.nth(c).inner_text() or "").strip()
            if any(row.values()):
                rows_out.append(row)
        return rows_out

    for r in range(body_rows.count()):
        cells = body_rows.nth(r).locator("td, th")
        row = {}
        for c in range(cells.count()):
            key = headers[c] if c < len(headers) and headers[c] else f"Column {c + 1}"
            row[key] = (cells.nth(c).inner_text() or "").strip()
        if any(row.values()):
            rows_out.append(row)
    return rows_out
