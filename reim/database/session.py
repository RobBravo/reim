"""Engine and session management.

REIM uses synchronous SQLAlchemy with psycopg 3. See decision D2 in
``docs/implementation-plan.md`` for why the MVP does not use the async stack.
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from functools import lru_cache

from sqlalchemy import Engine, create_engine, text
from sqlalchemy.orm import Session, sessionmaker

from reim.core.config import Settings, get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    """Return the process-wide SQLAlchemy engine."""
    return build_engine(get_settings())


def build_engine(settings: Settings) -> Engine:
    """Create a new engine from explicit settings (used by tests and Alembic)."""
    return create_engine(
        settings.database_url,
        echo=settings.database_echo,
        pool_size=settings.database_pool_size,
        max_overflow=settings.database_max_overflow,
        pool_pre_ping=True,
        future=True,
    )


@lru_cache(maxsize=1)
def get_session_factory() -> sessionmaker[Session]:
    """Return the process-wide session factory."""
    return sessionmaker(bind=get_engine(), autoflush=False, expire_on_commit=False)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Yield a session wrapped in a transaction, committing on success.

    Any exception rolls the transaction back and propagates, so a critical
    failure mid-load never leaves partial data behind.
    """
    session = get_session_factory()()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def check_database_connection(engine: Engine | None = None) -> bool:
    """Return True when a trivial query succeeds against the database."""
    target = engine or get_engine()
    try:
        with target.connect() as connection:
            connection.execute(text("SELECT 1"))
    except Exception:
        return False
    return True


def reset_engine_cache() -> None:
    """Dispose and clear the cached engine/session factory (used by tests)."""
    if get_engine.cache_info().currsize:
        get_engine().dispose()
    get_engine.cache_clear()
    get_session_factory.cache_clear()
