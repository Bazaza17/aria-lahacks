"""Database for the CREAO layer: TigerData (TimescaleDB) or any Postgres in the cloud, SQLite locally.

Tables are created on startup. On TimescaleDB the two event logs become hypertables with a
real-time continuous aggregate for exit flow (see timescale.py).
"""

import logging
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from functools import lru_cache

from sqlalchemy import DateTime, TypeDecorator
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy.orm import DeclarativeBase

from app.creao.config import get_settings

log = logging.getLogger(__name__)
status: dict = {}


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    """timestamptz; SQLite drops the zone, so values read back are marked UTC again."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value, dialect):
        return value.replace(tzinfo=UTC) if value is not None and value.tzinfo is None else value


def utcnow() -> datetime:
    return datetime.now(UTC)


@lru_cache
def engine() -> AsyncEngine:
    return create_async_engine(get_settings().database_url)


@lru_cache
def sessions() -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine(), expire_on_commit=False)


async def init_db() -> dict:
    from app.creao import models, timescale  # noqa: F401  (registers the tables)

    async with engine().begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        status["dialect"] = conn.dialect.name
        if conn.dialect.name == "postgresql":
            status.update(await timescale.setup(conn))
    log.info("CREAO layer database ready: %s", status)
    return status


async def get_session() -> AsyncIterator[AsyncSession]:
    async with sessions()() as session:
        yield session
