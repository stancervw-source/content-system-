from __future__ import annotations

import csv
import json
import logging
from pathlib import Path
from typing import Iterator

from ingestion.fetchers.base import BaseFetcher, FetchError
from ingestion.models.content_item import RawFetchedItem
from ingestion.models.source import Source
from ingestion.normalizer import parse_datetime

logger = logging.getLogger(__name__)


class ManualImportFetcher(BaseFetcher):
    """
    Wave 1 — Manual import from JSON or CSV file.

    Useful for one-off imports, testing, and sources without automated ingestion.

    fetch_config keys:
      - file_path: path to import file (required)
      - file_format: "json" | "csv" (default: inferred from extension)

    JSON format: list of objects with any subset of standard fields.
    CSV format: header row + data rows with same fields.

    Standard field names (all optional):
      external_content_id, title, raw_text, url, author_name,
      published_at, engagement_like_count, engagement_comment_count,
      engagement_repost_count, engagement_view_count
    """

    fetch_method = "manual_import"

    def fetch(self, source: Source) -> Iterator[RawFetchedItem]:
        file_path = source.fetch_config.get("file_path")

        if not file_path:
            raise FetchError(
                f"Source {source.canonical_key!r}: manual_import requires fetch_config.file_path"
            )

        path = Path(file_path)
        if not path.exists():
            raise FetchError(f"Import file not found: {path}")

        fmt = source.fetch_config.get("file_format") or path.suffix.lstrip(".")
        fmt = fmt.lower()

        logger.info("Manual import: %s → %s", source.canonical_key, path)

        if fmt == "json":
            records = self._load_json(path)
        elif fmt == "csv":
            records = self._load_csv(path)
        else:
            raise FetchError(f"Unsupported import format: {fmt!r}. Use 'json' or 'csv'.")

        for record in records:
            try:
                yield self._record_to_raw(record, source)
            except Exception as exc:
                logger.warning("Skipping record from %s: %s", path, exc)

    @staticmethod
    def _load_json(path: Path) -> list[dict]:
        with path.open(encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, list):
            raise FetchError(f"JSON import file must contain a list, got {type(data).__name__}")
        return data

    @staticmethod
    def _load_csv(path: Path) -> list[dict]:
        with path.open(encoding="utf-8", newline="") as f:
            return list(csv.DictReader(f))

    @staticmethod
    def _record_to_raw(record: dict, source: Source) -> RawFetchedItem:
        return RawFetchedItem(
            source_id=source.id,
            external_content_id=record.get("external_content_id") or record.get("id"),
            source_content_type="manual",
            title=record.get("title"),
            raw_text=record.get("raw_text") or record.get("content") or record.get("text"),
            url=record.get("url"),
            author_name=record.get("author_name") or record.get("author"),
            published_at=parse_datetime(record.get("published_at") or record.get("date")),
            engagement_like_count=_int_or_none(record.get("engagement_like_count")),
            engagement_comment_count=_int_or_none(record.get("engagement_comment_count")),
            engagement_repost_count=_int_or_none(record.get("engagement_repost_count")),
            engagement_view_count=_int_or_none(record.get("engagement_view_count")),
            raw_payload={"source_record": record},
        )


def _int_or_none(value) -> int | None:
    if value is None or value == "":
        return None
    try:
        return int(value)
    except (ValueError, TypeError):
        return None
