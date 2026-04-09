from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Optional
from uuid import UUID

import psycopg

from ingestion.db import repository as repo
from ingestion.deduplicator import check_and_mark_duplicate
from ingestion.fetchers.base import FetchError
from ingestion.fetchers.router import get_fetcher
from ingestion.models.source import Source
from ingestion.normalizer import normalize

logger = logging.getLogger(__name__)


@dataclass
class RunResult:
    source_key: str
    fetched: int = 0
    saved: int = 0
    duplicates: int = 0
    errors: int = 0
    skipped: int = 0
    error_messages: list[str] = field(default_factory=list)

    @property
    def success(self) -> bool:
        return self.errors == 0


def run_source(conn: psycopg.Connection, source: Source) -> RunResult:
    """
    Full ingestion pipeline for a single source:
    fetch → normalize → dedup → save

    Commits nothing — caller decides when to commit.
    """
    result = RunResult(source_key=source.canonical_key)

    try:
        fetcher = get_fetcher(source.fetch_method)
    except FetchError as exc:
        logger.error("No fetcher for %s: %s", source.canonical_key, exc)
        result.errors += 1
        result.error_messages.append(str(exc))
        return result

    try:
        raw_items = list(fetcher.fetch(source))
    except FetchError as exc:
        logger.error("Fetch failed for %s: %s", source.canonical_key, exc)
        repo.record_source_error(conn, source.id, str(exc))
        result.errors += 1
        result.error_messages.append(str(exc))
        return result

    result.fetched = len(raw_items)

    for raw in raw_items:
        try:
            # 1. Normalize
            item = normalize(raw, source_language=source.language)

            # 2. Deduplicate
            item = check_and_mark_duplicate(conn, item)

            if item.is_duplicate:
                result.duplicates += 1
                # Still insert with is_duplicate=True so we have a record
                # Skip if you prefer not to store duplicates at all
                repo.insert_content_item(conn, item)
                continue

            # 3. Persist
            inserted_id = repo.insert_content_item(conn, item)
            if inserted_id is None:
                # ON CONFLICT DO NOTHING hit (same source_id + external_content_id)
                result.skipped += 1
            else:
                result.saved += 1

        except Exception as exc:
            logger.warning(
                "Error processing item from %s (ext_id=%s): %s",
                source.canonical_key,
                raw.external_content_id,
                exc,
            )
            result.errors += 1

    repo.touch_source_checked(conn, source.id)

    logger.info(
        "Source %s: fetched=%d saved=%d dupes=%d skipped=%d errors=%d",
        source.canonical_key,
        result.fetched,
        result.saved,
        result.duplicates,
        result.skipped,
        result.errors,
    )
    return result


def run_all_active(
    conn: psycopg.Connection,
    fetch_method: Optional[str] = None,
    wave: Optional[int] = None,
) -> list[RunResult]:
    """
    Run ingestion for all active sources, optionally filtered by fetch_method or wave.
    Commits after each source to avoid losing progress on error.
    """
    sources = repo.get_active_sources(conn, fetch_method=fetch_method, wave=wave)

    if not sources:
        logger.warning("No active sources found (fetch_method=%s, wave=%s)", fetch_method, wave)
        return []

    logger.info("Starting ingestion: %d sources", len(sources))
    results: list[RunResult] = []

    for source in sources:
        result = run_source(conn, source)
        results.append(result)
        conn.commit()  # Commit per-source to preserve partial progress

    _log_summary(results)
    return results


def run_by_canonical_key(conn: psycopg.Connection, canonical_key: str) -> RunResult:
    """Run ingestion for a single source identified by canonical_key."""
    source = repo.get_source_by_key(conn, canonical_key)
    if not source:
        raise ValueError(f"Source not found: {canonical_key!r}")
    if not source.is_active:
        raise ValueError(f"Source {canonical_key!r} is not active")

    result = run_source(conn, source)
    conn.commit()
    return result


def _log_summary(results: list[RunResult]) -> None:
    total_fetched = sum(r.fetched for r in results)
    total_saved = sum(r.saved for r in results)
    total_dupes = sum(r.duplicates for r in results)
    total_errors = sum(r.errors for r in results)
    failed_sources = [r.source_key for r in results if not r.success]

    logger.info(
        "Ingestion complete: sources=%d fetched=%d saved=%d dupes=%d errors=%d",
        len(results), total_fetched, total_saved, total_dupes, total_errors,
    )
    if failed_sources:
        logger.warning("Failed sources: %s", ", ".join(failed_sources))
