"""HTTP/SOCKS proxy list with records_per_proxy rotation during scraping."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any
from urllib.parse import urlparse


@dataclass
class ProxyInfo:
    scheme: str
    host: str
    port: int
    username: str | None = None
    password: str | None = None
    status: str = "ready"  # ready | in_use | failed | disabled
    failure_count: int = 0
    raw: str = ""

    @property
    def server(self) -> str:
        return f"{self.scheme}://{self.host}:{self.port}"

    def to_playwright(self) -> dict[str, str]:
        cfg: dict[str, str] = {"server": self.server}
        if self.username:
            cfg["username"] = self.username
        if self.password:
            cfg["password"] = self.password
        return cfg

    def display(self) -> str:
        if self.username:
            return f"{self.scheme}://{self.username}@{self.host}:{self.port}"
        return self.server


def parse_proxy_line(line: str) -> ProxyInfo | None:
    line = line.strip()
    if not line or line.startswith("#"):
        return None
    if "://" not in line:
        # host:port → assume http
        line = "http://" + line
    parsed = urlparse(line)
    if not parsed.hostname or not parsed.port:
        return None
    scheme = (parsed.scheme or "http").lower()
    if scheme.startswith("socks5"):
        scheme = "socks5"
    elif scheme.startswith("socks4"):
        scheme = "socks4"
    elif scheme not in ("http", "https"):
        scheme = "http"
    return ProxyInfo(
        scheme=scheme,
        host=parsed.hostname,
        port=int(parsed.port),
        username=parsed.username,
        password=parsed.password,
        raw=line,
    )


@dataclass
class ProxyManager:
    """
    Rotates proxies during scraping after every `records_per_proxy` completed records.
    Never rotates mid-record — caller finishes the record, then calls
    `should_rotate()` / `rotate()`.
    """

    records_per_proxy: int = 5
    proxies: list[ProxyInfo] = field(default_factory=list)
    current_index: int = 0
    records_on_current: int = 0
    last_rotation: str | None = None
    direct_mode: bool = False

    @classmethod
    def from_lines(
        cls, lines: list[str], records_per_proxy: int = 5
    ) -> ProxyManager:
        proxies: list[ProxyInfo] = []
        for line in lines:
            info = parse_proxy_line(line)
            if info:
                proxies.append(info)
        mgr = cls(records_per_proxy=max(1, records_per_proxy), proxies=proxies)
        if not proxies:
            mgr.direct_mode = True
        return mgr

    @property
    def current(self) -> ProxyInfo | None:
        if self.direct_mode or not self.proxies:
            return None
        # skip disabled/failed when reading
        n = len(self.proxies)
        for _ in range(n):
            p = self.proxies[self.current_index % n]
            if p.status not in ("disabled", "failed"):
                return p
            self.current_index = (self.current_index + 1) % n
        return None

    def playwright_proxy(self) -> dict[str, str] | None:
        cur = self.current
        if cur is None:
            return None
        cur.status = "in_use"
        return cur.to_playwright()

    def mark_record_complete(self) -> None:
        """Call after a full record workflow finishes."""
        self.records_on_current += 1

    def should_rotate(self) -> bool:
        if self.direct_mode or not self.proxies:
            return False
        return self.records_on_current >= self.records_per_proxy

    def rotate(self) -> ProxyInfo | None:
        """Advance to the next healthy proxy and reset the counter."""
        if self.direct_mode or not self.proxies:
            self.records_on_current = 0
            return None
        if self.current is not None and self.current.status == "in_use":
            self.current.status = "ready"
        n = len(self.proxies)
        start = self.current_index
        for offset in range(1, n + 1):
            idx = (start + offset) % n
            candidate = self.proxies[idx]
            if candidate.status not in ("disabled", "failed"):
                self.current_index = idx
                self.records_on_current = 0
                self.last_rotation = (
                    datetime.now(timezone.utc).replace(microsecond=0).isoformat()
                )
                return candidate
        # all failed — reset failures and stay
        for p in self.proxies:
            if p.status == "failed":
                p.status = "ready"
                p.failure_count = 0
        self.current_index = (start + 1) % n
        self.records_on_current = 0
        self.last_rotation = (
            datetime.now(timezone.utc).replace(microsecond=0).isoformat()
        )
        return self.current

    def mark_failed(self) -> None:
        cur = self.current
        if cur is None:
            return
        cur.failure_count += 1
        cur.status = "failed"

    def status_dict(self) -> dict[str, Any]:
        cur = self.current
        return {
            "current_proxy": cur.display() if cur else ("(direct)" if self.direct_mode else None),
            "current_proxy_index": self.current_index if cur else None,
            "records_on_current": self.records_on_current,
            "records_per_proxy": self.records_per_proxy,
            "proxy_status": cur.status if cur else ("direct" if self.direct_mode else None),
            "last_rotation": self.last_rotation,
            "proxy_count": len(self.proxies),
            "direct_mode": self.direct_mode,
        }
