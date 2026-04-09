from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Iterator

from ingestion.fetchers.base import BaseFetcher, FetchError
from ingestion.models.content_item import RawFetchedItem
from ingestion.models.source import Source

logger = logging.getLogger(__name__)


class TelegramFetcher(BaseFetcher):
    """
    Wave 1 — Telegram public channel fetcher via Telethon (MTProto).

    Reads public channels without needing to be a member.
    Requires TELEGRAM_API_ID and TELEGRAM_API_HASH in environment.

    fetch_config keys (optional):
      - channel: channel username override (e.g. "@gornal")
      - limit: number of messages to fetch per run (default: 50)
      - min_id: fetch only messages newer than this message ID

    First run requires interactive phone auth — run scripts/setup_telegram.py once.
    Session is saved to telegram.session in the project root.
    """

    fetch_method = "telegram_api"

    def fetch(self, source: Source) -> Iterator[RawFetchedItem]:
        try:
            import asyncio
            from telethon import TelegramClient
            from telethon.tl.types import Message
        except ImportError:
            raise FetchError("telethon not installed. Run: pip install telethon")

        api_id = os.getenv("TELEGRAM_API_ID")
        api_hash = os.getenv("TELEGRAM_API_HASH")

        if not api_id or not api_hash:
            raise FetchError(
                "TELEGRAM_API_ID and TELEGRAM_API_HASH must be set for telegram_api fetcher"
            )

        channel = source.fetch_config.get("channel") or source.handle
        if not channel:
            raise FetchError(f"Source {source.canonical_key!r} has no Telegram channel/handle")

        limit: int = source.fetch_config.get("limit", 50)
        min_id: int = source.fetch_config.get("min_id", 0)

        logger.info("Telegram fetch: %s → channel=%s", source.canonical_key, channel)

        async def _fetch_async() -> list[RawFetchedItem]:
            results = []
            async with TelegramClient("telegram.session", int(api_id), api_hash) as client:
                try:
                    async for msg in client.iter_messages(channel, limit=limit, min_id=min_id):
                        if not isinstance(msg, Message) or not msg.text:
                            continue
                        try:
                            results.append(self._message_to_raw(msg, source))
                        except Exception as exc:
                            logger.warning(
                                "Skipping Telegram message %s from %s: %s",
                                msg.id, source.canonical_key, exc,
                            )
                except Exception as exc:
                    raise FetchError(f"Failed to fetch from Telegram channel {channel!r}: {exc}") from exc
            return results

        try:
            items = asyncio.run(_fetch_async())
        except FetchError:
            raise
        except Exception as exc:
            raise FetchError(f"Async error fetching {channel!r}: {exc}") from exc

        for item in items:
            yield item

    @staticmethod
    def _message_to_raw(msg, source: Source) -> RawFetchedItem:
        published_at = msg.date
        if published_at and published_at.tzinfo is None:
            published_at = published_at.replace(tzinfo=timezone.utc)

        channel = source.fetch_config.get("channel") or source.handle or ""
        url = f"https://t.me/{channel.lstrip('@')}/{msg.id}" if channel else None

        return RawFetchedItem(
            source_id=source.id,
            external_content_id=str(msg.id),
            source_content_type="tg_message",
            title=None,  # TG messages don't have titles
            raw_text=msg.text,
            url=url,
            author_name=None,
            published_at=published_at,
            engagement_view_count=getattr(msg, "views", None),
            engagement_comment_count=getattr(
                getattr(msg, "replies", None), "replies", None
            ),
            raw_payload={
                "message_id": msg.id,
                "has_media": msg.media is not None,
                "grouped_id": msg.grouped_id,
            },
        )
