"""Repository facade: SQLite by default; optional Supabase sync for scraped_records."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from scraper_app.config import (
    PROXIES_PATH,
    SETTINGS_PATH,
    SQLITE_PATH,
    SUPABASE_KEY,
    SUPABASE_URL,
    supabase_configured,
)
from scraper_app.db.models import (
    AppSettings,
    Association,
    Record,
    ScrapedRecord,
    ScrapingStep,
)
from scraper_app.db.sqlite_store import SQLiteStore

logger = logging.getLogger(__name__)

_repo: Repository | None = None


class Repository:
    def __init__(self, sqlite_path: Path | None = None) -> None:
        self.store = SQLiteStore(sqlite_path or SQLITE_PATH)
        self._supabase = None
        if supabase_configured():
            try:
                from supabase import create_client

                self._supabase = create_client(SUPABASE_URL, SUPABASE_KEY)
                logger.info("Supabase client configured")
            except Exception as exc:  # pragma: no cover
                logger.warning("Supabase init failed, using SQLite only: %s", exc)

    @property
    def backend_name(self) -> str:
        return "supabase+sqlite" if self._supabase else "sqlite"

    # Associations / steps / queue — always local SQLite for responsive UI;
    # scraped_records also mirrored to Supabase when configured.

    def list_associations(self) -> list[Association]:
        return self.store.list_associations()

    def get_association(self, association_id: str) -> Association | None:
        return self.store.get_association(association_id)

    def upsert_association(self, assoc: Association) -> Association:
        return self.store.upsert_association(assoc)

    def delete_association(self, association_id: str) -> None:
        self.store.delete_association(association_id)

    def list_steps(self, association_id: str, phase: str | None = None) -> list[ScrapingStep]:
        return self.store.list_steps(association_id, phase)

    def replace_steps(self, association_id: str, steps: list[ScrapingStep]) -> list[ScrapingStep]:
        return self.store.replace_steps(association_id, steps)

    def upsert_discovered_records(
        self, association_id: str, items: list[dict[str, str]]
    ) -> int:
        return self.store.upsert_discovered_records(association_id, items)

    def list_records(self, association_id: str, status: str | None = None) -> list[Record]:
        return self.store.list_records(association_id, status)

    def pick_random_pending(self, association_id: str) -> Record | None:
        return self.store.pick_random_pending(association_id)

    def update_record_status(
        self, record_id: str, status: str, error: str | None = None
    ) -> None:
        self.store.update_record_status(record_id, status, error)

    def save_scraped_record(
        self,
        association_id: str,
        source_url: str,
        scraped_data: dict[str, Any],
        record_id: str | None = None,
    ) -> ScrapedRecord:
        result = self.store.save_scraped_record(
            association_id, source_url, scraped_data, record_id=record_id
        )
        if self._supabase is not None:
            try:
                self._supabase.table("scraped_records").upsert(
                    {
                        "record_id": result.record_id,
                        "association_id": result.association_id,
                        "source_url": result.source_url,
                        "scraped_data": result.scraped_data,
                        "scraped_at": result.scraped_at,
                    }
                ).execute()
            except Exception as exc:  # pragma: no cover
                logger.warning("Supabase upsert failed: %s", exc)
        return result

    def list_scraped_records(
        self, association_id: str | None = None
    ) -> list[ScrapedRecord]:
        return self.store.list_scraped_records(association_id)

    def get_hour_count(self, association_id: str, hour_bucket_start: str) -> int:
        return self.store.get_hour_count(association_id, hour_bucket_start)

    def increment_hour_count(self, association_id: str, hour_bucket_start: str) -> int:
        return self.store.increment_hour_count(association_id, hour_bucket_start)

    # --- Settings / proxies on disk ---

    def load_settings(self) -> AppSettings:
        if SETTINGS_PATH.exists():
            data = json.loads(SETTINGS_PATH.read_text(encoding="utf-8"))
            return AppSettings.from_dict(data)
        return AppSettings()

    def save_settings(self, settings: AppSettings) -> None:
        SETTINGS_PATH.parent.mkdir(parents=True, exist_ok=True)
        SETTINGS_PATH.write_text(
            json.dumps(settings.to_dict(), indent=2), encoding="utf-8"
        )

    def load_proxy_lines(self) -> list[str]:
        if not PROXIES_PATH.exists():
            return []
        data = json.loads(PROXIES_PATH.read_text(encoding="utf-8"))
        return list(data.get("proxies", []))

    def save_proxy_lines(self, lines: list[str]) -> None:
        PROXIES_PATH.parent.mkdir(parents=True, exist_ok=True)
        PROXIES_PATH.write_text(
            json.dumps({"proxies": lines}, indent=2), encoding="utf-8"
        )

    def close(self) -> None:
        self.store.close()


def get_repository() -> Repository:
    global _repo
    if _repo is None:
        _repo = Repository()
    return _repo
