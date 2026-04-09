from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Iterator

import httpx

from ingestion.fetchers.base import BaseFetcher, FetchError
from ingestion.models.content_item import RawFetchedItem
from ingestion.models.source import Source

logger = logging.getLogger(__name__)

HF_API_BASE = "https://huggingface.co/api"
HF_PAPER_URL = "https://huggingface.co/papers/{id}"
HF_MODEL_URL = "https://huggingface.co/{model_id}"


class HuggingFaceFetcher(BaseFetcher):
    """
    Wave 2 — HuggingFace public API fetcher.

    fetch_config keys:
      - feed: "daily_papers" | "trending_models" (default: "daily_papers")
      - limit: number of items (default: 20)
    """

    fetch_method = "huggingface_api"

    def fetch(self, source: Source) -> Iterator[RawFetchedItem]:
        feed: str = source.fetch_config.get("feed", "daily_papers")
        limit: int = source.fetch_config.get("limit", 20)

        logger.info("HuggingFace fetch: %s → feed=%s", source.canonical_key, feed)

        with httpx.Client(timeout=20) as client:
            if feed == "daily_papers":
                yield from self._fetch_daily_papers(client, source, limit)
            elif feed == "trending_models":
                yield from self._fetch_trending_models(client, source, limit)
            else:
                raise FetchError(f"Unknown HuggingFace feed: {feed!r}")

    def _fetch_daily_papers(
        self, client: httpx.Client, source: Source, limit: int
    ) -> Iterator[RawFetchedItem]:
        resp = client.get(f"{HF_API_BASE}/daily_papers")
        resp.raise_for_status()
        items = resp.json()[:limit]

        for entry in items:
            try:
                paper = entry.get("paper", {})
                paper_id = paper.get("id", "")
                published_at = None
                if ts := paper.get("publishedAt"):
                    try:
                        published_at = datetime.fromisoformat(ts.rstrip("Z")).replace(
                            tzinfo=timezone.utc
                        )
                    except ValueError:
                        pass

                authors = paper.get("authors", [])
                author_name = authors[0].get("name") if authors else None

                yield RawFetchedItem(
                    source_id=source.id,
                    external_content_id=paper_id,
                    source_content_type="hf_paper",
                    title=paper.get("title"),
                    raw_text=paper.get("summary") or "",
                    url=HF_PAPER_URL.format(id=paper_id),
                    author_name=author_name,
                    published_at=published_at,
                    engagement_comment_count=entry.get("numComments"),
                    raw_payload={
                        "upvotes": entry.get("upvotes"),
                        "num_comments": entry.get("numComments"),
                        "paper_id": paper_id,
                    },
                )
            except Exception as exc:
                logger.warning("Skipping HF paper entry: %s", exc)

    def _fetch_trending_models(
        self, client: httpx.Client, source: Source, limit: int
    ) -> Iterator[RawFetchedItem]:
        sort = source.fetch_config.get("sort", "likes")
        resp = client.get(
            f"{HF_API_BASE}/models",
            params={"sort": sort, "limit": limit},
        )
        resp.raise_for_status()
        items = resp.json()

        for model in items:
            try:
                model_id = model.get("id", "")
                created_at = None
                if ts := model.get("createdAt"):
                    try:
                        created_at = datetime.fromisoformat(ts.rstrip("Z")).replace(
                            tzinfo=timezone.utc
                        )
                    except ValueError:
                        pass

                tags = model.get("tags", [])
                description = f"Tags: {', '.join(tags)}" if tags else ""

                yield RawFetchedItem(
                    source_id=source.id,
                    external_content_id=model_id,
                    source_content_type="hf_model",
                    title=model_id,
                    raw_text=description,
                    url=HF_MODEL_URL.format(model_id=model_id),
                    author_name=model.get("author"),
                    published_at=created_at,
                    raw_payload={
                        "likes": model.get("likes"),
                        "downloads": model.get("downloads"),
                        "pipeline_tag": model.get("pipeline_tag"),
                        "tags": tags[:10],
                    },
                )
            except Exception as exc:
                logger.warning("Skipping HF model entry: %s", exc)