"""Shared dataclasses for associations, steps, records, and results."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from uuid import uuid4


def new_id() -> str:
    return str(uuid4())


@dataclass
class Association:
    id: str
    name: str
    website_url: str = ""
    enabled: bool = True
    max_per_hour: int = 10
    delay_min_seconds: float = 5.0
    delay_max_seconds: float = 40.0
    created_at: str | None = None
    updated_at: str | None = None


@dataclass
class ScrapingStep:
    id: str
    association_id: str
    position: int
    action: str
    phase: str = "discovery"  # discovery | record
    locator_type: str | None = None
    locator_value: str | None = None
    params: dict[str, Any] = field(default_factory=dict)
    enabled: bool = True


@dataclass
class Record:
    id: str
    association_id: str
    source_url: str
    status: str = "pending"
    external_id: str | None = None
    discovered_at: str | None = None
    error: str | None = None


@dataclass
class ScrapedRecord:
    record_id: str
    association_id: str
    source_url: str
    scraped_data: dict[str, Any]
    scraped_at: str


@dataclass
class AppSettings:
    records_per_proxy: int = 5
    allow_direct_mode: bool = True
    headless: bool = True

    def to_dict(self) -> dict[str, Any]:
        return {
            "records_per_proxy": self.records_per_proxy,
            "allow_direct_mode": self.allow_direct_mode,
            "headless": self.headless,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any] | None) -> AppSettings:
        data = data or {}
        return cls(
            records_per_proxy=int(data.get("records_per_proxy", 5)),
            allow_direct_mode=bool(data.get("allow_direct_mode", True)),
            headless=bool(data.get("headless", True)),
        )


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")
