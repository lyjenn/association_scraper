"""Application paths and environment settings."""

from __future__ import annotations

import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

ROOT_DIR = Path(__file__).resolve().parents[2]
DATA_DIR = Path(os.getenv("DATA_DIR", ROOT_DIR / "data")).expanduser()
DATA_DIR.mkdir(parents=True, exist_ok=True)

SQLITE_PATH = Path(os.getenv("SQLITE_PATH", DATA_DIR / "scraper.db")).expanduser()
SETTINGS_PATH = DATA_DIR / "settings.json"
PROXIES_PATH = DATA_DIR / "proxies.json"

SUPABASE_URL = os.getenv("SUPABASE_URL", "").strip()
SUPABASE_KEY = os.getenv("SUPABASE_KEY", "").strip()

SCHEMA_PATH = ROOT_DIR / "schemas" / "step.schema.json"
FIXTURES_DIR = ROOT_DIR / "fixtures"


def supabase_configured() -> bool:
    return bool(SUPABASE_URL and SUPABASE_KEY)
