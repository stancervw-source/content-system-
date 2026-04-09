"""
scripts/run_ingestion.py

CLI runner for the ingestion pipeline.

Usage:
    # Run all active Wave 1 sources:
    python -m scripts.run_ingestion --wave 1

    # Run all active sources with RSS fetch method:
    python -m scripts.run_ingestion --method rss

    # Run a single source by canonical key:
    python -m scripts.run_ingestion --source casey-winters

    # Run all active sources (all waves):
    python -m scripts.run_ingestion --all

    # Dry run (fetch + normalize, skip DB save):
    python -m scripts.run_ingestion --wave 1 --dry-run
"""
from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

sys.path.insert(0, str(Path(__file__).parent.parent))

from ingestion.db.connection import managed_connection
from ingestion.pipeline import run_all_active, run_by_canonical_key

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    datefmt="%H:%M:%S",
)
logger = logging.getLogger(__name__)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run content ingestion pipeline")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--all", action="store_true", help="Run all active sources")
    group.add_argument("--wave", type=int, choices=[1, 2, 3], help="Run sources from this wave")
    group.add_argument("--method", help="Run sources with this fetch_method")
    group.add_argument("--source", help="Run a single source by canonical_key")

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Fetch and normalize but do not save to DB (prints summary only)",
    )
    args = parser.parse_args()

    if args.dry_run:
        logger.warning("DRY RUN mode — no data will be written to DB")

    try:
        with managed_connection() as conn:
            if args.source:
                result = run_by_canonical_key(conn, args.source)
                _print_result(result)
                if args.dry_run:
                    conn.rollback()
            else:
                wave = args.wave if args.wave else None
                method = args.method if args.method else None
                results = run_all_active(conn, fetch_method=method, wave=wave)
                for r in results:
                    _print_result(r)
                if args.dry_run:
                    conn.rollback()
    except KeyboardInterrupt:
        logger.info("Interrupted.")
        sys.exit(0)
    except Exception as exc:
        logger.error("Fatal error: %s", exc)
        sys.exit(1)


def _print_result(result) -> None:
    status = "OK" if result.success else "FAIL"
    print(
        f"[{status}] {result.source_key}: "
        f"fetched={result.fetched} saved={result.saved} "
        f"dupes={result.duplicates} errors={result.errors}"
    )
    for msg in result.error_messages:
        print(f"       ↳ {msg}")


if __name__ == "__main__":
    main()
