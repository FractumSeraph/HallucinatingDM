import uuid
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import JSON, DateTime, String, event
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

from app.config import get_settings


class Base(DeclarativeBase):
    type_annotation_map = {dict[str, Any]: JSON, list[Any]: JSON}


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(UTC)


class TimestampedBase(Base):
    """Shared columns: UUID-hex string PK + created/updated timestamps."""

    __abstract__ = True

    id: Mapped[str] = mapped_column(String(32), primary_key=True, default=new_id)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


_engine = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


vec_available = False


def _load_sqlite_vec(dbapi_conn) -> None:
    """Load the sqlite-vec extension onto the raw sqlite3 connection.

    SQLAlchemy hands us an AsyncAdapt wrapper; unwrap to the stdlib connection.
    If loading fails (platform without loadable-extension support), vector
    search silently degrades to FTS-only.
    """
    global vec_available
    raw = dbapi_conn
    for attr in ("_connection", "_conn"):
        raw = getattr(raw, attr, raw)
    try:
        import sqlite_vec

        raw.enable_load_extension(True)
        sqlite_vec.load(raw)
        raw.enable_load_extension(False)
        vec_available = True
    except Exception:
        vec_available = False


def _configure_sqlite(dbapi_conn, _record) -> None:
    _load_sqlite_vec(dbapi_conn)
    cursor = dbapi_conn.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA synchronous=NORMAL")
    cursor.close()


def get_engine():
    global _engine
    if _engine is None:
        settings = get_settings()
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        _engine = create_async_engine(settings.resolved_database_url)
        event.listen(_engine.sync_engine, "connect", _configure_sqlite)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def get_db() -> AsyncIterator[AsyncSession]:
    async with get_sessionmaker()() as session:
        yield session


def reset_engine() -> None:
    """Test hook: drop cached engine/sessionmaker so a fresh DATABASE_URL applies."""
    global _engine, _sessionmaker
    _engine = None
    _sessionmaker = None
