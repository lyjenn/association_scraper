# Association Scraper

A desktop app that scrapes member/profile information from association websites. **Each association has its own scraping recipe** (ordered steps). The app follows that recipe with Playwright, rotates HTTP/SOCKS proxies after every N finished records, and saves flexible JSON results to Supabase (or a local SQLite file).

## What you need

- Python 3.12+
- [uv](https://github.com/astral-sh/uv) (recommended)
- Playwright browsers (`uv run playwright install chromium`)

## Install and run

```bash
uv sync --all-extras
uv run playwright install chromium
uv run association-scraper
```

Or:

```bash
uv run python -m scraper_app
```

Optional Supabase: copy `.env.example` to `.env` and set `SUPABASE_URL` and `SUPABASE_KEY`. If those are empty, the app uses a local SQLite database under `data/`.

Apply the SQL in `supabase/migrations/001_init.sql` in your Supabase project when you want the online tables.

## How to use it (short)

1. Open **Associations** → **Load practice associations** (starts two local demo websites with different layouts).
2. Open **Scraping Method** to view or edit each association’s step recipe.
3. Open **Proxies** to paste proxies and set **Records per proxy** (for demos you can leave proxies empty and use direct mode).
4. Open **Run / Results**, check the associations you want, click **Start**.
5. Inspect `scraped_data` JSON in the results panel.

## Ideas to remember

- The core engine does **not** hard-code one website’s tabs or field names.
- One browser session + one proxy stay together for an entire record (all clicks and extracts).
- After `records_per_proxy` completed records, the session closes and a new one opens with the next proxy.
- Final rows live in `scraped_records` with general columns plus `scraped_data` JSONB/JSON.

## Tests

```bash
uv sync --all-extras
uv run playwright install chromium
uv run pytest -q
```

## Project layout

- `src/scraper_app/workflow/` — config-driven Playwright engine
- `src/scraper_app/proxy/` — proxy list + rotation
- `src/scraper_app/scheduler/` — random pick, delays, hourly caps
- `src/scraper_app/ui/` — PySide6 desktop UI
- `fixtures/` — two practice sites with different structures
- `supabase/migrations/` — SQL schema for Supabase
