"""Map locator_type + value to a Playwright locator."""

from __future__ import annotations

from typing import Any


def resolve_locator(page: Any, locator_type: str | None, locator_value: str | None):
    if not locator_type or locator_value is None or locator_value == "":
        raise ValueError("locator_type and locator_value are required for this step")

    lt = locator_type.lower().strip()
    value = locator_value

    if lt == "css":
        return page.locator(value)
    if lt == "id":
        vid = value[1:] if value.startswith("#") else value
        return page.locator(f"#{vid}")
    if lt == "class":
        cls = value[1:] if value.startswith(".") else value
        # Support space-separated classes
        parts = [p for p in cls.split() if p]
        selector = "".join(f".{p}" for p in parts) if parts else f".{cls}"
        return page.locator(selector)
    if lt == "link_text":
        return page.get_by_role("link", name=value, exact=True)
    if lt == "button_text":
        # Tabs are often buttons or links; try button first, then role=tab, then text
        btn = page.get_by_role("button", name=value, exact=True)
        if btn.count() > 0:
            return btn
        tab = page.get_by_role("tab", name=value, exact=True)
        if tab.count() > 0:
            return tab
        return page.get_by_text(value, exact=True)
    if lt == "xpath":
        xp = value if value.startswith("xpath=") else f"xpath={value}"
        return page.locator(xp)

    raise ValueError(f"Unsupported locator_type: {locator_type!r}")
