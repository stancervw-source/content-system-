from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import UUID

from pydantic import BaseModel, Field


class ContentItem(BaseModel):
    id: Optional[UUID] = None

    # Source
    source_id: UUID
    external_content_id: Optional[str] = None

    # Classification
    content_type: Optional[str] = None         # article | post | thread | video | episode
    source_content_type: Optional[str] = None  # raw type from fetcher: rss_item | tg_message | yt_video

    # Body
    title: Optional[str] = None
    content_text: Optional[str] = None         # raw fetched text
    normalized_text: Optional[str] = None      # cleaned, ready for AI layer
    summary_raw: Optional[str] = None
    url: Optional[str] = None
    author_name: Optional[str] = None

    # Timing
    published_at: Optional[datetime] = None
    fetched_at: Optional[datetime] = None

    # Engagement
    engagement_like_count: Optional[int] = None
    engagement_comment_count: Optional[int] = None
    engagement_repost_count: Optional[int] = None
    engagement_view_count: Optional[int] = None

    # Raw
    raw_payload: Optional[dict[str, Any]] = None

    # Dedup
    content_hash: str

    # Classification
    language: Optional[str] = None

    # Pipeline state
    status: str = "new"
    is_duplicate: bool = False
    topic_cluster_id: Optional[UUID] = None

    # Timestamps
    created_at: Optional[datetime] = None

    class Config:
        from_attributes = True


class RawFetchedItem(BaseModel):
    """
    Intermediate structure returned by fetchers before normalization.
    Fetchers fill what they can; normalizer converts to ContentItem.
    """
    source_id: UUID
    external_content_id: Optional[str] = None
    source_content_type: str  # rss_item | tg_message | yt_video | hn_item | web_page | manual

    title: Optional[str] = None
    raw_text: Optional[str] = None
    url: Optional[str] = None
    author_name: Optional[str] = None
    published_at: Optional[datetime] = None

    engagement_like_count: Optional[int] = None
    engagement_comment_count: Optional[int] = None
    engagement_repost_count: Optional[int] = None
    engagement_view_count: Optional[int] = None

    raw_payload: dict[str, Any] = Field(default_factory=dict)
