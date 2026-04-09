from __future__ import annotations

import logging
import re
from typing import Iterator
from urllib.parse import parse_qs, urlparse

from ingestion.fetchers.base import BaseFetcher, FetchError
from ingestion.models.content_item import RawFetchedItem
from ingestion.models.source import Source

logger = logging.getLogger(__name__)

_VIDEO_ID_RE = re.compile(r"(?:v=|youtu\.be/)([A-Za-z0-9_-]{11})")


class YouTubeFetcher(BaseFetcher):
    """
    Wave 1 — YouTube transcript fetcher.

    Pulls transcripts from YouTube videos via youtube-transcript-api.
    No API key required for transcripts.

    fetch_config keys:
      - video_ids: list of explicit video IDs to fetch (for one-off imports)
      - channel_id: YouTube channel ID (requires YOUTUBE_API_KEY for listing videos)
      - languages: preferred transcript language codes (default: ["ru", "en"])
      - max_videos: max videos to process per run (default: 10)

    For MVP: video_ids mode is fully supported.
    Channel listing mode requires YouTube Data API (see fetch_config: channel_id).
    """

    fetch_method = "youtube_transcript"

    def fetch(self, source: Source) -> Iterator[RawFetchedItem]:
        try:
            from youtube_transcript_api import YouTubeTranscriptApi, NoTranscriptFound, TranscriptsDisabled
        except ImportError:
            raise FetchError("youtube-transcript-api not installed. Run: pip install youtube-transcript-api")

        video_ids: list[str] = source.fetch_config.get("video_ids", [])
        languages: list[str] = source.fetch_config.get("languages", ["ru", "en"])
        max_videos: int = source.fetch_config.get("max_videos", 10)

        if not video_ids:
            # Try to extract video ID from source URL
            if source.url:
                vid = _extract_video_id(source.url)
                if vid:
                    video_ids = [vid]

        if not video_ids:
            raise FetchError(
                f"Source {source.canonical_key!r} has no video_ids in fetch_config and no parseable URL"
            )

        logger.info(
            "YouTube fetch: %s → %d video(s)", source.canonical_key, len(video_ids[:max_videos])
        )

        for video_id in video_ids[:max_videos]:
            try:
                transcript_list = YouTubeTranscriptApi.list_transcripts(video_id)
                transcript = _pick_transcript(transcript_list, languages)
                segments = transcript.fetch()
                full_text = " ".join(s["text"] for s in segments)

                yield RawFetchedItem(
                    source_id=source.id,
                    external_content_id=video_id,
                    source_content_type="yt_video",
                    title=None,  # Requires YouTube API to get title
                    raw_text=full_text,
                    url=f"https://www.youtube.com/watch?v={video_id}",
                    author_name=source.canonical_name,
                    published_at=None,  # Requires YouTube API
                    raw_payload={
                        "video_id": video_id,
                        "transcript_language": transcript.language_code,
                        "is_generated": transcript.is_generated,
                        "segment_count": len(segments),
                    },
                )
            except Exception as exc:
                logger.warning(
                    "Skipping YouTube video %s from %s: %s", video_id, source.canonical_key, exc
                )


def _extract_video_id(url: str) -> str | None:
    match = _VIDEO_ID_RE.search(url)
    return match.group(1) if match else None


def _pick_transcript(transcript_list, preferred_languages: list[str]):
    """Pick the best available transcript in preferred language order."""
    try:
        return transcript_list.find_transcript(preferred_languages)
    except Exception:
        # Fall back to any available transcript
        return transcript_list.find_manually_created_transcript(
            [t.language_code for t in transcript_list]
        )
