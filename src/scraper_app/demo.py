"""Load practice associations (fixtures) into the local database."""

from __future__ import annotations

import json
from pathlib import Path

from scraper_app.config import FIXTURES_DIR
from scraper_app.db.models import Association, ScrapingStep, new_id
from scraper_app.db.repository import Repository


def _steps_from_json(association_id: str, payload: dict) -> list[ScrapingStep]:
    steps: list[ScrapingStep] = []
    pos = 0
    for phase in ("discovery", "record"):
        for raw in payload.get(phase, []):
            steps.append(
                ScrapingStep(
                    id=new_id(),
                    association_id=association_id,
                    position=pos,
                    action=raw["action"],
                    phase=raw.get("phase", phase),
                    locator_type=raw.get("locator_type"),
                    locator_value=raw.get("locator_value"),
                    params=raw.get("params") or {},
                    enabled=True,
                )
            )
            pos += 1
    return steps


def seed_demo_associations(repo: Repository, base_url_a: str, base_url_b: str) -> list[str]:
    """
    Create/replace the two practice associations pointing at local fixture servers.
    Returns association IDs.
    """
    ids: list[str] = []
    specs = [
        ("association_a", base_url_a.rstrip("/") + "/index.html"),
        ("association_b", base_url_b.rstrip("/") + "/search.html"),
    ]
    # Remove previous demo associations with same names
    existing = {a.name: a for a in repo.list_associations()}
    for folder, url in specs:
        path = FIXTURES_DIR / folder / "steps.json"
        payload = json.loads(path.read_text(encoding="utf-8"))
        name = payload["name"]
        if name in existing:
            repo.delete_association(existing[name].id)
        assoc = Association(
            id=new_id(),
            name=name,
            website_url=url,
            enabled=True,
            max_per_hour=20,
            delay_min_seconds=0.2,
            delay_max_seconds=0.5,
        )
        repo.upsert_association(assoc)
        repo.replace_steps(assoc.id, _steps_from_json(assoc.id, payload))
        ids.append(assoc.id)
    return ids


def fixture_paths() -> dict[str, Path]:
    return {
        "a": FIXTURES_DIR / "association_a",
        "b": FIXTURES_DIR / "association_b",
    }
