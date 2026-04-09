from __future__ import annotations

import json
import logging
from typing import Optional
from uuid import UUID

import psycopg

from ingestion.models.content_item import ContentItem
from ingestion.models.source import Source, SourceCreate

logger = logging.getLogger(__name__)


# ─────────────────────────────────────────────
# SOURCES
# ─────────────────────────────────────────────

def upsert_source(conn: psycopg.Connection, source: SourceCreate) -> UUID:
    """
    Insert source or update on canonical_key conflict.
    Returns the source UUID.
    """
    sql = """
        INSERT INTO sources (
            source_name, canonical_name, canonical_key,
            source_type, region, language,
            primary_platform, platforms,
            url, handle,
            themes, signal_type,
            signal_quality, early_signal_potential, startup_signal_value,
            content_adaptation_value, brand_fit,
            tier, wave,
            monitoring_frequency, fetch_method, fetch_config,
            is_active, notes
        ) VALUES (
            %(source_name)s, %(canonical_name)s, %(canonical_key)s,
            %(source_type)s, %(region)s, %(language)s,
            %(primary_platform)s, %(platforms)s,
            %(url)s, %(handle)s,
            %(themes)s, %(signal_type)s,
            %(signal_quality)s, %(early_signal_potential)s, %(startup_signal_value)s,
            %(content_adaptation_value)s, %(brand_fit)s,
            %(tier)s, %(wave)s,
            %(monitoring_frequency)s, %(fetch_method)s, %(fetch_config)s,
            %(is_active)s, %(notes)s
        )
        ON CONFLICT (canonical_key) DO UPDATE SET
            source_name             = EXCLUDED.source_name,
            canonical_name          = EXCLUDED.canonical_name,
            source_type             = EXCLUDED.source_type,
            region                  = EXCLUDED.region,
            language                = EXCLUDED.language,
            primary_platform        = EXCLUDED.primary_platform,
            platforms               = EXCLUDED.platforms,
            url                     = EXCLUDED.url,
            handle                  = EXCLUDED.handle,
            themes                  = EXCLUDED.themes,
            signal_type             = EXCLUDED.signal_type,
            signal_quality          = EXCLUDED.signal_quality,
            early_signal_potential  = EXCLUDED.early_signal_potential,
            startup_signal_value    = EXCLUDED.startup_signal_value,
            content_adaptation_value = EXCLUDED.content_adaptation_value,
            brand_fit               = EXCLUDED.brand_fit,
            tier                    = EXCLUDED.tier,
            wave                    = EXCLUDED.wave,
            monitoring_frequency    = EXCLUDED.monitoring_frequency,
            fetch_method            = EXCLUDED.fetch_method,
            fetch_config            = EXCLUDED.fetch_config,
            is_active               = EXCLUDED.is_active,
            notes                   = EXCLUDED.notes,
            updated_at              = NOW()
        RETURNING id
    """
    params = source.model_dump()
    params["platforms"] = json.dumps(params["platforms"])
    params["fetch_config"] = json.dumps(params["fetch_config"])
    params["themes"] = params["themes"] or []

    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return row["id"]


def get_active_sources(
    conn: psycopg.Connection,
    fetch_method: Optional[str] = None,
    wave: Optional[int] = None,
) -> list[Source]:
    """Return active sources, optionally filtered by fetch_method or wave."""
    conditions = ["is_active = TRUE"]
    params: dict = {}

    if fetch_method:
        conditions.append("fetch_method = %(fetch_method)s")
        params["fetch_method"] = fetch_method

    if wave is not None:
        conditions.append("wave = %(wave)s")
        params["wave"] = wave

    where = " AND ".join(conditions)
    sql = f"""
        SELECT * FROM sources
        WHERE {where}
        ORDER BY tier ASC, wave ASC, source_name ASC
    """
    with conn.cursor() as cur:
        cur.execute(sql, params)
        rows = cur.fetchall()
    return [_row_to_source(r) for r in rows]


def get_source_by_key(conn: psycopg.Connection, canonical_key: str) -> Optional[Source]:
    with conn.cursor() as cur:
        cur.execute("SELECT * FROM sources WHERE canonical_key = %s", (canonical_key,))
        row = cur.fetchone()
    return _row_to_source(row) if row else None


def record_source_error(conn: psycopg.Connection, source_id: UUID, error_msg: str) -> None:
    sql = """
        UPDATE sources SET
            error_count   = error_count + 1,
            last_error_at  = NOW(),
            last_error_msg = %(msg)s,
            updated_at    = NOW()
        WHERE id = %(id)s
    """
    with conn.cursor() as cur:
        cur.execute(sql, {"id": str(source_id), "msg": error_msg})


def touch_source_checked(conn: psycopg.Connection, source_id: UUID) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE sources SET last_checked_at = NOW(), updated_at = NOW() WHERE id = %s",
            (str(source_id),),
        )


# ─────────────────────────────────────────────
# CONTENT ITEMS
# ─────────────────────────────────────────────

def insert_content_item(conn: psycopg.Connection, item: ContentItem) -> Optional[UUID]:
    """
    Insert a content item. Returns UUID on success, None if skipped (duplicate external_id).
    Caller must handle setting is_duplicate before calling.
    """
    sql = """
        INSERT INTO content_items (
            source_id, external_content_id,
            content_type, source_content_type,
            title, content_text, normalized_text, summary_raw,
            url, author_name,
            published_at, fetched_at,
            engagement_like_count, engagement_comment_count,
            engagement_repost_count, engagement_view_count,
            raw_payload, content_hash, language,
            status, is_duplicate
        ) VALUES (
            %(source_id)s, %(external_content_id)s,
            %(content_type)s, %(source_content_type)s,
            %(title)s, %(content_text)s, %(normalized_text)s, %(summary_raw)s,
            %(url)s, %(author_name)s,
            %(published_at)s, NOW(),
            %(engagement_like_count)s, %(engagement_comment_count)s,
            %(engagement_repost_count)s, %(engagement_view_count)s,
            %(raw_payload)s, %(content_hash)s, %(language)s,
            %(status)s, %(is_duplicate)s
        )
        ON CONFLICT (source_id, external_content_id) DO NOTHING
        RETURNING id
    """
    params = item.model_dump(exclude={"id", "created_at", "fetched_at", "topic_cluster_id"})
    params["source_id"] = str(item.source_id)
    params["raw_payload"] = json.dumps(params["raw_payload"]) if params.get("raw_payload") else None

    with conn.cursor() as cur:
        cur.execute(sql, params)
        row = cur.fetchone()
        return row["id"] if row else None


def find_by_hash(conn: psycopg.Connection, content_hash: str) -> Optional[UUID]:
    """Returns the id of an existing item with this hash, or None."""
    with conn.cursor() as cur:
        cur.execute(
            "SELECT id FROM content_items WHERE content_hash = %s LIMIT 1",
            (content_hash,),
        )
        row = cur.fetchone()
    return row["id"] if row else None


def update_item_status(conn: psycopg.Connection, item_id: UUID, status: str) -> None:
    with conn.cursor() as cur:
        cur.execute(
            "UPDATE content_items SET status = %s WHERE id = %s",
            (status, str(item_id)),
        )


# ─────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────

def _row_to_source(row: dict) -> Source:
    data = dict(row)
    if isinstance(data.get("platforms"), str):
        data["platforms"] = json.loads(data["platforms"])
    if isinstance(data.get("fetch_config"), str):
        data["fetch_config"] = json.loads(data["fetch_config"])
    # themes is a native PG array, psycopg returns it as a Python list already
    return Source(**data)
