from __future__ import annotations

import logging
from typing import Iterator

import feedparser

from ingestion.fetchers.base import BaseFetcher, FetchError
from ingestion.models.content_item import RawFetchedItem
from ingestion.models.source import Source
from ingestion.normalizer import parse_datetime

logger = logging.getLogger(__name__)


class RSSFetcher(BaseFetcher):
    """
    Wave 1 — RSS / Atom feed fetcher.

    fetch_config keys (optional):
      - feed_url: override the RSS URL (if different from source.url)
      - max_items: max entries to return per run (default: 50)
    """

    fetch_method = "rss"

    def fetch(self, source: Source) -> Iterator[RawFetchedItem]:
        feed_url = source.fetch_config.get("feed_url") or source.url

        if not feed_url:
            raise FetchError(f"Source {source.canonical_key!r} has no URL for RSS fetching")

        logger.info("RSS fetch: %s → %s", source.canonical_key, feed_url)

        feed = feedparser.parse(feed_url)

        if feed.bozo and not feed.entries:
            raise FetchError(
                f"RSS parse error for {source.canonical_key!r}: {feed.bozo_exception}"
            )

        max_items: int = source.fetch_config.get("max_items", 50)

        for entry in feed.entries[:max_items]:
            try:
                yield self._entry_to_raw(entry, source)
            except Exception as exc:
                logger.warning("Skipping RSS entry from %s: %s", source.canonical_key, exc)

    @staticmethod
    def _entry_to_raw(entry: feedparser.FeedParserDict, source: Source) -> RawFetchedItem:
        # Prefer summary over content (content can be huge HTML blobs)
        raw_text = (
            entry.get("summary")
            or _get_content_value(entry)
            or ""
        )

        published = parse_datetime(
            entry.get("published") or entry.get("updated")
        )

        return RawFetchedItem(
            source_id=source.id,
            external_content_id=entry.get("id") or entry.get("link"),
            source_content_type="rss_item",
            title=entry.get("title"),
            raw_text=raw_text,
            url=entry.get("link"),
            author_name=entry.get("author"),
            published_at=published,
            raw_payload={
                "feed_id": entry.get("id"),
                "tags": [t.get("term") for t in entry.get("tags", [])],
            },
        )


def _get_content_value(entry: feedparser.FeedParserDict) -> str | None:
    """Extract the best content value from feedparser content list."""
    content_list = entry.get("content", [])
    if not content_list:
        return None
    # Prefer text/html, fallback to first available
    for c in content_list:
        if c.get("type") == "text/html":
            return c.get("value")
    return content_list[0].get("value")
