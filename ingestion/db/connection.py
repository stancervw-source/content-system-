from __future__ import annotations

import os
from contextlib import contextmanager
from typing import Generator

import psycopg
from psycopg.rows import dict_row


def get_dsn() -> str:
    dsn = os.getenv("DATABASE_URL")
    if not dsn:
        raise EnvironmentError("DATABASE_URL is not set. Copy .env.example to .env and fill it in.")
    return dsn


def get_connection() -> psycopg.Connection:
    """Open a new synchronous connection. Caller is responsible for closing."""
    return psycopg.connect(get_dsn(), row_factory=dict_row)


@contextmanager
def managed_connection() -> Generator[psycopg.Connection, None, None]:
    """Context manager: opens connection, commits on success, rolls back on error."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()
