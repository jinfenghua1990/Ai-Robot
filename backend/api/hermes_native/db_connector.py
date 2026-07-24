"""
Database connector module for Hermes trading system.
Provides connection pooling and query execution utilities.
"""

import os
from contextlib import contextmanager
from typing import Any, Generator, Optional, Optional

import psycopg2
from psycopg2 import pool
from psycopg2.extras import RealDictCursor, Json

# Database configuration from environment or defaults
DB_CONFIG = {
    "host": os.getenv("DB_HOST", "localhost"),
    "port": int(os.getenv("DB_PORT", "5432")),
    "database": os.getenv("DB_NAME", "hermes"),
    "user": os.getenv("DB_USER", "gino"),
    "password": os.getenv("DB_PASSWORD", ""),
}

# Connection pool singleton
_connection_pool: Optional[pool.ThreadedConnectionPool] = None


def get_connection_pool(min_connections: int = 1, max_connections: int = 10) -> pool.ThreadedConnectionPool:
    """Get or create the database connection pool."""
    global _connection_pool
    if _connection_pool is None:
        _connection_pool = pool.ThreadedConnectionPool(
            min_connections,
            max_connections,
            **DB_CONFIG
        )
    return _connection_pool


def close_connection_pool():
    """Close all connections in the pool."""
    global _connection_pool
    if _connection_pool is not None:
        _connection_pool.closeall()
        _connection_pool = None


@contextmanager
def get_connection() -> Generator:
    """Context manager for database connections."""
    pool = get_connection_pool()
    conn = pool.getconn()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        pool.putconn(conn)


@contextmanager
def get_cursor(commit: bool = True) -> Generator:
    """Context manager for database cursors with auto-commit."""
    with get_connection() as conn:
        cursor = conn.cursor(cursor_factory=RealDictCursor)
        try:
            yield cursor
            if commit:
                conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            cursor.close()


def execute_query(query: str, params: Optional[tuple] = None) -> list[dict[str, Any]]:
    """Execute a SELECT query and return results as list of dicts."""
    with get_cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchall()


def execute_one(query: str, params: Optional[tuple] = None) -> Optional[dict[str, Any]]:
    """Execute a SELECT query and return a single result."""
    with get_cursor() as cursor:
        cursor.execute(query, params)
        return cursor.fetchone()


def execute_write(query: str, params: Optional[tuple] = None) -> int:
    """Execute an INSERT/UPDATE/DELETE query and return rowcount."""
    with get_cursor() as cursor:
        cursor.execute(query, params)
        return cursor.rowcount


def execute_many(query: str, params_list: list) -> int:
    """Execute a query with multiple parameter sets."""
    with get_connection() as conn:
        cursor = conn.cursor()
        cursor.executemany(query, params_list)
        conn.commit()
        return cursor.rowcount


def insert_returning(query: str, params: Optional[tuple] = None) -> Optional[Any]:
    """Execute INSERT with RETURNING clause and return the value."""
    with get_cursor() as cursor:
        cursor.execute(query, params)
        result = cursor.fetchone()
        return result[0] if result else None


def table_exists(table_name: str) -> bool:
    """Check if a table exists in the database."""
    query = """
        SELECT EXISTS (
            SELECT FROM information_schema.tables 
            WHERE table_name = %s
        )
    """
    result = execute_one(query, (table_name,))
    return result["exists"] if result else False


def get_table_columns(table_name: str) -> list[dict[str, Any]]:
    """Get column information for a table."""
    query = """
        SELECT column_name, data_type, is_nullable, column_default
        FROM information_schema.columns
        WHERE table_name = %s
        ORDER BY ordinal_position
    """
    return execute_query(query, (table_name,))


# ─── Market Resolution ────────────────────────────────────────────────────────

A_SHARE_MARKETS = ("SH", "SZ", "BJ")
"""All A-share market codes. CN_A is not a real market — it is an aggregate."""

MARKET_ALIASES = {
    "CN_A": A_SHARE_MARKETS,
    "CSI": A_SHARE_MARKETS,
}
"""Market aliases that map to multiple underlying markets."""


def resolve_market_codes(market: str) -> tuple[str, ...]:
    """
    Resolve a market code to one or more concrete market codes.

    - 'CN_A' / 'CSI' → ('SH', 'SZ', 'BJ')  — all A-share markets
    - Any other string → (market,)           — returned as a single-element tuple
    """
    if market in MARKET_ALIASES:
        return MARKET_ALIASES[market]
    return (market,)


def market_filter(market: str) -> tuple[str, list]:
    """
    Return a SQL market filter clause and its parameters.

    Returns:
        (sql_fragment, [params])

    Examples:
        market_filter('CN_A')  → ("market IN (%,%,%)", ['SH', 'SZ', 'BJ'])
        market_filter('SH')    → ("market = %s",       ['SH'])
    """
    codes = resolve_market_codes(market)
    if len(codes) == 1:
        return ("market = %s", list(codes))
    placeholders = ",".join("%s" for _ in codes)
    return (f"market IN ({placeholders})", list(codes))
