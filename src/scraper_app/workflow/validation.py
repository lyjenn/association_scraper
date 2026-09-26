"""Validate scraping steps against the JSON schema."""

from __future__ import annotations

import json
from typing import Any

from jsonschema import Draft202012Validator

from scraper_app.config import SCHEMA_PATH
from scraper_app.db.models import ScrapingStep

ALLOWED_ACTIONS = {
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
}

ALLOWED_LOCATORS = {
    None,
    "css",
    "id",
    "class",
    "link_text",
    "button_text",
    "xpath",
}


def _load_schema() -> dict[str, Any]:
    return json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))


def step_to_dict(step: ScrapingStep) -> dict[str, Any]:
    return {
        "id": step.id,
        "position": step.position,
        "action": step.action,
        "phase": step.phase,
        "locator_type": step.locator_type,
        "locator_value": step.locator_value,
        "enabled": step.enabled,
        "params": step.params or {},
    }


def validate_step(step: ScrapingStep | dict[str, Any]) -> list[str]:
    data = step_to_dict(step) if isinstance(step, ScrapingStep) else step
    errors: list[str] = []
    action = data.get("action")
    if action not in ALLOWED_ACTIONS:
        errors.append(f"Unknown action: {action!r}")
    phase = data.get("phase")
    if phase not in ("discovery", "record"):
        errors.append(f"Phase must be 'discovery' or 'record', got {phase!r}")
    loc = data.get("locator_type")
    if loc not in ALLOWED_LOCATORS:
        errors.append(f"Unknown locator_type: {loc!r}")
    try:
        Draft202012Validator(_load_schema()).validate(data)
    except Exception as exc:
        errors.append(str(exc))
    return errors


def validate_steps(steps: list[ScrapingStep]) -> list[str]:
    all_errors: list[str] = []
    for i, step in enumerate(steps):
        for err in validate_step(step):
            all_errors.append(f"Step {i} ({step.action}): {err}")
    return all_errors
