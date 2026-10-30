"""Async SQLAlchemy engine + session (asyncpg) — lazy: der Engine entsteht erst beim ersten Zugriff.

Mit memory:// gibt es keinen Engine (Speicher-Adapter, siehe storage.py).
"""
from functools import cache

from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from .settings import DATABASE_URL


def get_engine(url: str | None = None) -> AsyncEngine:
    # Schlüssel normalisieren: @cache unterscheidet get_engine() von get_engine(url) → sonst zwei Engines/Pools.
    return _engine(url or DATABASE_URL)


@cache
def _engine(url: str) -> AsyncEngine:
    if url.startswith("memory://"):
        raise RuntimeError("memory:// hat keinen SQL-Engine — Speicher-Port (storage.py) nutzen")
    return create_async_engine(url, pool_pre_ping=True)


def get_sessionmaker(url: str | None = None) -> async_sessionmaker:
    return _sessionmaker(url or DATABASE_URL)


@cache
def _sessionmaker(url: str) -> async_sessionmaker:
    return async_sessionmaker(_engine(url), expire_on_commit=False)


def __getattr__(name: str):
    # `from fldos.db import engine, SessionLocal` bleibt gültig, baut aber erst beim Import-Zugriff.
    if name == "engine":
        return get_engine()
    if name == "SessionLocal":
        return get_sessionmaker()
    raise AttributeError(name)
