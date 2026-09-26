"""Local SQLite storage — used when Supabase is not configured."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any

from scraper_app.db.models import (
    Association,
    Record,
    ScrapedRecord,
    ScrapingStep,
    new_id,
    utc_now_iso,
)


class SQLiteStore:
    def __init__(self, path: Path) -> None:
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._conn = sqlite3.connect(str(path), check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        cur.executescript(
            """
            create table if not exists associations (
                id text primary key,
                name text not null,
                website_url text not null default '',
                enabled integer not null default 1,
                max_per_hour integer not null default 10,
                delay_min_seconds real not null default 5,
                delay_max_seconds real not null default 40,
                created_at text,
                updated_at text
            );

            create table if not exists scraping_steps (
                id text primary key,
                association_id text not null,
                position integer not null,
                action text not null,
                locator_type text,
                locator_value text,
                params_json text not null default '{}',
                enabled integer not null default 1,
                phase text not null default 'discovery',
                foreign key(association_id) references associations(id) on delete cascade
            );

            create table if not exists records (
                id text primary key,
                association_id text not null,
                external_id text,
                source_url text not null,
                status text not null default 'pending',
                discovered_at text,
                error text,
                unique(association_id, source_url),
                foreign key(association_id) references associations(id) on delete cascade
            );

            create table if not exists scraped_records (
                record_id text primary key,
                association_id text not null,
                source_url text not null,
                scraped_data text not null default '{}',
                scraped_at text not null,
                foreign key(association_id) references associations(id) on delete cascade
            );

            create table if not exists scrape_progress (
                association_id text primary key,
                hour_bucket_start text,
                hour_count integer not null default 0,
                last_run_at text,
                notes text,
                foreign key(association_id) references associations(id) on delete cascade
            );
            """
        )
        self._conn.commit()

    def close(self) -> None:
        self._conn.close()

    # --- Associations ---

    def list_associations(self) -> list[Association]:
        rows = self._conn.execute(
            "select * from associations order by name collate nocase"
        ).fetchall()
        return [self._row_to_association(r) for r in rows]

    def get_association(self, association_id: str) -> Association | None:
        row = self._conn.execute(
            "select * from associations where id = ?", (association_id,)
        ).fetchone()
        return self._row_to_association(row) if row else None

    def upsert_association(self, assoc: Association) -> Association:
        now = utc_now_iso()
        if not assoc.id:
            assoc.id = new_id()
        existing = self.get_association(assoc.id)
        if existing is None:
            self._conn.execute(
                """
                insert into associations (
                    id, name, website_url, enabled, max_per_hour,
                    delay_min_seconds, delay_max_seconds, created_at, updated_at
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    assoc.id,
                    assoc.name,
                    assoc.website_url,
                    int(assoc.enabled),
                    assoc.max_per_hour,
                    assoc.delay_min_seconds,
                    assoc.delay_max_seconds,
                    now,
                    now,
                ),
            )
            assoc.created_at = now
            assoc.updated_at = now
        else:
            self._conn.execute(
                """
                update associations set
                    name = ?, website_url = ?, enabled = ?, max_per_hour = ?,
                    delay_min_seconds = ?, delay_max_seconds = ?, updated_at = ?
                where id = ?
                """,
                (
                    assoc.name,
                    assoc.website_url,
                    int(assoc.enabled),
                    assoc.max_per_hour,
                    assoc.delay_min_seconds,
                    assoc.delay_max_seconds,
                    now,
                    assoc.id,
                ),
            )
            assoc.updated_at = now
        self._conn.commit()
        return assoc

    def delete_association(self, association_id: str) -> None:
        self._conn.execute("delete from scraped_records where association_id = ?", (association_id,))
        self._conn.execute("delete from records where association_id = ?", (association_id,))
        self._conn.execute("delete from scraping_steps where association_id = ?", (association_id,))
        self._conn.execute("delete from scrape_progress where association_id = ?", (association_id,))
        self._conn.execute("delete from associations where id = ?", (association_id,))
        self._conn.commit()

    # --- Steps ---

    def list_steps(self, association_id: str, phase: str | None = None) -> list[ScrapingStep]:
        if phase:
            rows = self._conn.execute(
                """
                select * from scraping_steps
                where association_id = ? and phase = ?
                order by position
                """,
                (association_id, phase),
            ).fetchall()
        else:
            rows = self._conn.execute(
                """
                select * from scraping_steps
                where association_id = ?
                order by phase, position
                """,
                (association_id,),
            ).fetchall()
        return [self._row_to_step(r) for r in rows]

    def replace_steps(self, association_id: str, steps: list[ScrapingStep]) -> list[ScrapingStep]:
        self._conn.execute(
            "delete from scraping_steps where association_id = ?", (association_id,)
        )
        saved: list[ScrapingStep] = []
        for i, step in enumerate(steps):
            step.id = step.id or new_id()
            step.association_id = association_id
            step.position = i
            self._conn.execute(
                """
                insert into scraping_steps (
                    id, association_id, position, action, locator_type,
                    locator_value, params_json, enabled, phase
                ) values (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    step.id,
                    association_id,
                    step.position,
                    step.action,
                    step.locator_type,
                    step.locator_value,
                    json.dumps(step.params or {}),
                    int(step.enabled),
                    step.phase,
                ),
            )
            saved.append(step)
        self._conn.commit()
        return saved

    # --- Records queue ---

    def upsert_discovered_records(
        self, association_id: str, items: list[dict[str, str]]
    ) -> int:
        """items: [{source_url, external_id?}] — returns number newly inserted."""
        inserted = 0
        now = utc_now_iso()
        for item in items:
            url = item["source_url"]
            external_id = item.get("external_id")
            try:
                self._conn.execute(
                    """
                    insert into records (id, association_id, external_id, source_url, status, discovered_at)
                    values (?, ?, ?, ?, 'pending', ?)
                    """,
                    (new_id(), association_id, external_id, url, now),
                )
                inserted += 1
            except sqlite3.IntegrityError:
                pass
        self._conn.commit()
        return inserted

    def list_records(
        self, association_id: str, status: str | None = None
    ) -> list[Record]:
        if status:
            rows = self._conn.execute(
                "select * from records where association_id = ? and status = ?",
                (association_id, status),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "select * from records where association_id = ?",
                (association_id,),
            ).fetchall()
        return [self._row_to_record(r) for r in rows]

    def pick_random_pending(self, association_id: str) -> Record | None:
        row = self._conn.execute(
            """
            select * from records
            where association_id = ? and status = 'pending'
            order by random()
            limit 1
            """,
            (association_id,),
        ).fetchone()
        return self._row_to_record(row) if row else None

    def update_record_status(
        self, record_id: str, status: str, error: str | None = None
    ) -> None:
        self._conn.execute(
            "update records set status = ?, error = ? where id = ?",
            (status, error, record_id),
        )
        self._conn.commit()

    # --- Scraped records ---

    def save_scraped_record(
        self,
        association_id: str,
        source_url: str,
        scraped_data: dict[str, Any],
        record_id: str | None = None,
    ) -> ScrapedRecord:
        rid = record_id or new_id()
        scraped_at = utc_now_iso()
        existing = self._conn.execute(
            "select record_id from scraped_records where record_id = ?", (rid,)
        ).fetchone()
        payload = json.dumps(scraped_data)
        if existing:
            self._conn.execute(
                """
                update scraped_records
                set association_id = ?, source_url = ?, scraped_data = ?, scraped_at = ?
                where record_id = ?
                """,
                (association_id, source_url, payload, scraped_at, rid),
            )
        else:
            # Also match by source_url for upsert convenience
            by_url = self._conn.execute(
                """
                select record_id from scraped_records
                where association_id = ? and source_url = ?
                """,
                (association_id, source_url),
            ).fetchone()
            if by_url:
                rid = by_url["record_id"]
                self._conn.execute(
                    """
                    update scraped_records
                    set scraped_data = ?, scraped_at = ?
                    where record_id = ?
                    """,
                    (payload, scraped_at, rid),
                )
            else:
                self._conn.execute(
                    """
                    insert into scraped_records
                        (record_id, association_id, source_url, scraped_data, scraped_at)
                    values (?, ?, ?, ?, ?)
                    """,
                    (rid, association_id, source_url, payload, scraped_at),
                )
        self._conn.commit()
        return ScrapedRecord(
            record_id=rid,
            association_id=association_id,
            source_url=source_url,
            scraped_data=scraped_data,
            scraped_at=scraped_at,
        )

    def list_scraped_records(
        self, association_id: str | None = None
    ) -> list[ScrapedRecord]:
        if association_id:
            rows = self._conn.execute(
                """
                select * from scraped_records
                where association_id = ?
                order by scraped_at desc
                """,
                (association_id,),
            ).fetchall()
        else:
            rows = self._conn.execute(
                "select * from scraped_records order by scraped_at desc"
            ).fetchall()
        return [self._row_to_scraped(r) for r in rows]

    # --- Progress / hourly cap ---

    def get_hour_count(self, association_id: str, hour_bucket_start: str) -> int:
        row = self._conn.execute(
            "select hour_bucket_start, hour_count from scrape_progress where association_id = ?",
            (association_id,),
        ).fetchone()
        if not row:
            return 0
        if row["hour_bucket_start"] != hour_bucket_start:
            return 0
        return int(row["hour_count"] or 0)

    def increment_hour_count(self, association_id: str, hour_bucket_start: str) -> int:
        row = self._conn.execute(
            "select hour_bucket_start, hour_count from scrape_progress where association_id = ?",
            (association_id,),
        ).fetchone()
        now = utc_now_iso()
        if not row:
            self._conn.execute(
                """
                insert into scrape_progress
                    (association_id, hour_bucket_start, hour_count, last_run_at)
                values (?, ?, 1, ?)
                """,
                (association_id, hour_bucket_start, now),
            )
            self._conn.commit()
            return 1
        if row["hour_bucket_start"] != hour_bucket_start:
            count = 1
            self._conn.execute(
                """
                update scrape_progress
                set hour_bucket_start = ?, hour_count = ?, last_run_at = ?
                where association_id = ?
                """,
                (hour_bucket_start, count, now, association_id),
            )
        else:
            count = int(row["hour_count"] or 0) + 1
            self._conn.execute(
                """
                update scrape_progress
                set hour_count = ?, last_run_at = ?
                where association_id = ?
                """,
                (count, now, association_id),
            )
        self._conn.commit()
        return count

    # --- row helpers ---

    @staticmethod
    def _row_to_association(row: sqlite3.Row) -> Association:
        return Association(
            id=row["id"],
            name=row["name"],
            website_url=row["website_url"] or "",
            enabled=bool(row["enabled"]),
            max_per_hour=int(row["max_per_hour"]),
            delay_min_seconds=float(row["delay_min_seconds"]),
            delay_max_seconds=float(row["delay_max_seconds"]),
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    @staticmethod
    def _row_to_step(row: sqlite3.Row) -> ScrapingStep:
        return ScrapingStep(
            id=row["id"],
            association_id=row["association_id"],
            position=int(row["position"]),
            action=row["action"],
            phase=row["phase"] or "discovery",
            locator_type=row["locator_type"],
            locator_value=row["locator_value"],
            params=json.loads(row["params_json"] or "{}"),
            enabled=bool(row["enabled"]),
        )

    @staticmethod
    def _row_to_record(row: sqlite3.Row) -> Record:
        return Record(
            id=row["id"],
            association_id=row["association_id"],
            source_url=row["source_url"],
            status=row["status"],
            external_id=row["external_id"],
            discovered_at=row["discovered_at"],
            error=row["error"],
        )

    @staticmethod
    def _row_to_scraped(row: sqlite3.Row) -> ScrapedRecord:
        return ScrapedRecord(
            record_id=row["record_id"],
            association_id=row["association_id"],
            source_url=row["source_url"],
            scraped_data=json.loads(row["scraped_data"] or "{}"),
            scraped_at=row["scraped_at"],
        )
