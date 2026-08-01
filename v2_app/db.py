from __future__ import annotations

from contextlib import contextmanager
from typing import Any, Iterable

from sqlalchemy import create_engine, text

from .config import DATABASE_URL


engine = create_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_size=5,
    max_overflow=5,
    future=True,
)


@contextmanager
def connection():
    with engine.begin() as conn:
        yield conn


def fetch_all(sql: str, params: dict[str, Any] | None = None) -> list[dict[str, Any]]:
    with engine.connect() as conn:
        return [dict(row._mapping) for row in conn.execute(text(sql), params or {})]


def fetch_one(sql: str, params: dict[str, Any] | None = None) -> dict[str, Any] | None:
    with engine.connect() as conn:
        row = conn.execute(text(sql), params or {}).mappings().first()
        return dict(row) if row else None


def execute(sql: str, params: dict[str, Any] | None = None) -> None:
    with engine.begin() as conn:
        conn.execute(text(sql), params or {})


def execute_many(sql: str, rows: Iterable[dict[str, Any]]) -> None:
    payload = list(rows)
    if not payload:
        return
    with engine.begin() as conn:
        conn.execute(text(sql), payload)

