from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterator

import httpx

from ingestion.fetchers.base import BaseFetcher, FetchError
from ingestion.models.content_item import RawFetchedItem
from ingestion.models.source import Source

logger = logging.getLogger(__name__)

HN_API_BASE = "https://hacker-news.firebaseio.com/v0"
HN_ITEM_URL = "https://news.ycombinator.com/item?id={id}"


class HackerNewsFetcher(BaseFetcher):
    """
    Wave 1 — Hacker News public API fetcher.

    Supports fetching from:
    - topstories / newstories / beststories
    - Show HN (filtered from newstories)
    - Ask HN (filtered from newstories)

    fetch_config keys:
      - feed: "topstories" | "newstories" | "beststories" | "showstories" | "askstories" |
              "jobstories" | "showhn" | "askhn" (default: "topstories")
              showstories/askstories use the dedicated HN endpoints (better than filtering newstories)
      - limit: number of items to fetch (default: 30)
      - min_score: skip items below this score (default: 0)
    """

    fetch_method = "hn_api"

    def fetch(self, source: Source) -> Iterator[RawFetchedItem]:
        feed: str = source.fetch_config.get("feed", "topstories")
        limit: int = source.fetch_config.get("limit", 30)
        min_score: int = source.fetch_config.get("min_score", 0)

        logger.info("HN fetch: %s → feed=%s", source.canonical_key, feed)

        with httpx.Client(timeout=15) as client:
            item_ids = self._get_item_ids(client, feed, limit)

            for item_id in item_ids:
                try:
                    item = self._get_item(client, item_id)
                    if not item or item.get("deleted") or item.get("dead"):
                        continue
                    if item.get("score", 0) < min_score:
                        continue
                    if feed == "showhn" and not item.get("title", "").startswith("Show HN"):
                        continue
                    if feed == "askhn" and not item.get("title", "").startswith("Ask HN"):
                        continue

                    yield self._item_to_raw(item, source)
                except Exception as exc:
                    logger.warning("Skipping HN item %s: %s", item_id, exc)

    def _get_item_ids(self, client: httpx.Client, feed: str, limit: int) -> list[int]:
        _feed_map = {
            "showhn": "newstories",
            "askhn": "newstories",
            "showstories": "showstories",
            "askstories": "askstories",
            "jobstories": "jobstories",
        }
        api_feed = _feed_map.get(feed, feed)
        resp = client.get(f"{HN_API_BASE}/{api_feed}.json")
        resp.raise_for_status()
        return resp.json()[:limit]

    def _get_item(self, client: httpx.Client, item_id: int) -> dict | None:
        resp = client.get(f"{HN_API_BASE}/item/{item_id}.json")
        resp.raise_for_status()
        return resp.json()

    @staticmethod
    def _item_to_raw(item: dict, source: Source) -> RawFetchedItem:
        published_at = None
        if ts := item.get("time"):
            published_at = datetime.fromtimestamp(ts, tz=timezone.utc)

        # Combine title + text (Ask HN / Show HN posts have text body)
        raw_text = item.get("text") or ""

        return RawFetchedItem(
            source_id=source.id,
            external_content_id=str(item["id"]),
            source_content_type="hn_item",
            title=item.get("title"),
            raw_text=raw_text,
            url=item.get("url") or HN_ITEM_URL.format(id=item["id"]),
            author_name=item.get("by"),
            published_at=published_at,
            engagement_comment_count=item.get("descendants"),
            raw_payload={
                "hn_id": item["id"],
                "score": item.get("score"),
                "item_type": item.get("type"),
                "kids_count": len(item.get("kids", [])),
            },
        )
