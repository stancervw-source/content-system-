from __future__ import annotations

import logging
from uuid import UUID

import psycopg

from ingestion.db.repository import find_by_hash
from ingestion.models.content_item import ContentItem

logger = logging.getLogger(__name__)


def check_and_mark_duplicate(conn: psycopg.Connection, item: ContentItem) -> ContentItem:
    """
    Check whether an item with the same content_hash already exists in the DB.
    If yes, mark the item as duplicate and update status.
    Does NOT persist — caller handles insertion.
    """
    existing_id = find_by_hash(conn, item.content_hash)

    if existing_id:
        logger.debug(
            "Duplicate detected: hash=%s matches existing id=%s",
            item.content_hash,
            existing_id,
        )
        return item.model_copy(update={"is_duplicate": True, "status": "deduplicated"})

    return item.model_copy(update={"status": "deduplicated"})
