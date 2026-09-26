"""Entry point: python -m scraper_app"""

from __future__ import annotations

import sys


def main() -> None:
    from scraper_app.app import run_app

    raise SystemExit(run_app(sys.argv))


if __name__ == "__main__":
    main()
