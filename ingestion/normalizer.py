from __future__ import annotations

import hashlib
import re
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from bs4 import BeautifulSoup
from dateutil import parser as dateutil_parser

from ingestion.models.content_item import ContentItem, RawFetchedItem


# ─────────────────────────────────────────────
# TEXT CLEANING
# ─────────────────────────────────────────────

# Collapse runs of whitespace (including \u00a0, \t, multiple spaces)
_WHITESPACE_RE = re.compile(r"[ \t\u00a0]+")
_BLANK_LINES_RE = re.compile(r"\n{3,}")

# Boilerplate line patterns — whole lines matching these are removed.
# Note: BS4 get_text() splits content at tag boundaries, so WordPress RSS like
# "<p>The post <a>Title</a> appeared first on <a>Blog</a>.</p>" becomes multiple lines.
# Patterns handle both the full-line and split-line cases.
_BOILERPLATE_LINE_PATTERNS = [
    # WordPress "appeared first on" — full line or split fragment
    re.compile(r"The post .+ appeared first on .+", re.I),
    re.compile(r"^The post$", re.I),
    re.compile(r"^appeared first on$", re.I),
    re.compile(r"^appeared first on\b", re.I),
    # WordPress "Continue reading" (various arrow symbols, incl. BS4-split arrow on next line)
    re.compile(r"Continue reading\s*[→›»↗\u2192\u203a\u00bb]?", re.I),
    re.compile(r"^[→›»↗\u2192\u203a\u00bb]+$"),  # standalone arrow left by BS4 split
    # Generic RSS truncation
    re.compile(r"Read (the )?(full |more |rest of the )?(article|post|story).*", re.I),
    re.compile(r"^[\[(\s]*\.{2,}[\])\s]*$"),  # lines that are just "..." or "[...]"
    # Email newsletter boilerplate
    re.compile(r"subscribe\s+to\s+our\s+newsletter", re.I),
    re.compile(r"sign\s+up\s+for\s+free", re.I),
    re.compile(r"unsubscribe\s+at\s+any\s+time", re.I),
    re.compile(r"view\s+this\s+(email|newsletter)\s+in\s+your\s+browser", re.I),
    re.compile(r"powered\s+by\s+\w+", re.I),
    re.compile(r"click\s+here\s+to\s+read\s+more", re.I),
]


def strip_html(text: str) -> str:
    """
    Parse and strip HTML using BeautifulSoup.
    Handles tags, entities, and encoding correctly.
    Falls back to input if BS4 fails.
    """
    if not text or "<" not in text:
        return text
    try:
        soup = BeautifulSoup(text, "lxml")
        return soup.get_text(separator="\n")
    except Exception:
        # Fallback: naive regex strip
        text = re.sub(r"<[^>]+>", " ", text)
        text = re.sub(r"&[a-z#0-9]+;", " ", text)
        return text


def clean_text(text: str) -> str:
    """
    Normalize raw content text:
    1. Strip HTML (via BS4)
    2. Remove boilerplate lines
    3. Collapse whitespace / blank lines
    """
    if not text:
        return ""

    text = strip_html(text)

    # Remove boilerplate on a per-line basis
    lines = text.splitlines()
    cleaned_lines = []
    for line in lines:
        stripped = line.strip()
        if any(p.search(stripped) for p in _BOILERPLATE_LINE_PATTERNS):
            continue
        cleaned_lines.append(_WHITESPACE_RE.sub(" ", line).strip())

    text = "\n".join(cleaned_lines)

    # Collapse excessive blank lines
    text = _BLANK_LINES_RE.sub("\n\n", text)

    return text.strip()


# ─────────────────────────────────────────────
# DATETIME PARSING
# ─────────────────────────────────────────────

def parse_datetime(value: str | datetime | None) -> Optional[datetime]:
    """
    Parse a datetime from string or pass through a datetime object.
    Always returns UTC-aware datetime or None.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=timezone.utc)
        return value
    try:
        dt = dateutil_parser.parse(str(value))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except Exception:
        return None


# ─────────────────────────────────────────────
# CONTENT HASH
# ─────────────────────────────────────────────

def compute_content_hash(
    source_id: UUID,
    url: Optional[str],
    title: Optional[str],
    content_text: Optional[str],
) -> str:
    """
    Generate a stable SHA-256 fingerprint for deduplication.

    Priority:
    1. URL (most stable identifier)
    2. source_id + title (for sources without URLs, e.g. Telegram)
    3. source_id + first 300 chars of text
    """
    if url:
        key = url.strip().lower()
    elif title:
        key = f"{source_id}::{title.strip().lower()}"
    else:
        snippet = (content_text or "")[:300]
        key = f"{source_id}::{snippet}"

    return hashlib.sha256(key.encode("utf-8")).hexdigest()


# ─────────────────────────────────────────────
# LANGUAGE DETECTION
# ─────────────────────────────────────────────

def detect_language(text: str) -> Optional[str]:
    """
    Lightweight language detection. Returns ISO 639-1 code or None.
    Falls back gracefully if langdetect is unavailable or text is too short.
    """
    if not text or len(text) < 20:
        return None
    try:
        from langdetect import detect, LangDetectException
        return detect(text)
    except Exception:
        return None


# ─────────────────────────────────────────────
# MAIN NORMALIZATION
# ─────────────────────────────────────────────

def normalize(raw: RawFetchedItem, source_language: Optional[str] = None) -> ContentItem:
    """
    Convert a RawFetchedItem → ContentItem with cleaned text, parsed datetime,
    content hash, and language detection.
    """
    normalized_text = clean_text(raw.raw_text or "")
    published_at = parse_datetime(raw.published_at)

    content_hash = compute_content_hash(
        source_id=raw.source_id,
        url=raw.url,
        title=raw.title,
        content_text=normalized_text,
    )

    language = source_language
    if not language and normalized_text:
        language = detect_language(normalized_text)

    # Map source_content_type → generic content_type
    content_type = _infer_content_type(raw.source_content_type)

    return ContentItem(
        source_id=raw.source_id,
        external_content_id=raw.external_content_id,
        content_type=content_type,
        source_content_type=raw.source_content_type,
        title=raw.title,
        content_text=raw.raw_text,
        normalized_text=normalized_text or None,
        url=raw.url,
        author_name=raw.author_name,
        published_at=published_at,
        engagement_like_count=raw.engagement_like_count,
        engagement_comment_count=raw.engagement_comment_count,
        engagement_repost_count=raw.engagement_repost_count,
        engagement_view_count=raw.engagement_view_count,
        raw_payload=raw.raw_payload,
        content_hash=content_hash,
        language=language,
        status="normalized",
    )


def _infer_content_type(source_content_type: str) -> str:
    mapping = {
        "rss_item": "article",
        "tg_message": "post",
        "yt_video": "video",
        "hn_item": "post",
        "web_page": "article",
        "manual": "article",
    }
    return mapping.get(source_content_type, "unknown")
