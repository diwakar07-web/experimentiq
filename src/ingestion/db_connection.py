"""
ExperimentIQ — Database Connection Factory

Purpose:
    Provides SQLAlchemy engine creation and connection management for the
    entire pipeline. This is the single point of truth for database access.
    All other modules obtain database connections through this module.

Design:
    - Engine factory with connection pool configuration.
    - Session factory for ORM-style access (analytics queries).
    - Raw psycopg2 connection for COPY-based bulk loading.
    - Connection health check with retry logic.

Dependencies:
    - SQLAlchemy >= 2.0
    - psycopg2-binary
    - config.settings

Inputs:
    DatabaseSettings from config.settings.

Outputs:
    SQLAlchemy Engine, Session, or psycopg2 connection objects.
"""

from __future__ import annotations

import logging
import time
from contextlib import contextmanager
from functools import lru_cache
from typing import Generator, Optional

import psycopg2
import psycopg2.extensions
from sqlalchemy import Engine, create_engine, event, text
from sqlalchemy.exc import OperationalError, SQLAlchemyError
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import QueuePool

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Engine Configuration
# ---------------------------------------------------------------------------

# Pool configuration for an analytics workload (large, long-running queries)
_POOL_SIZE = 5
_MAX_OVERFLOW = 10
_POOL_TIMEOUT = 30  # seconds to wait for a connection from the pool
_POOL_RECYCLE = 3600  # recycle connections every hour
_CONNECT_TIMEOUT = 30  # TCP connection timeout in seconds


# ---------------------------------------------------------------------------
# Engine Factory
# ---------------------------------------------------------------------------


@lru_cache(maxsize=1)
def get_engine(
    dsn: Optional[str] = None,
    pool_size: int = _POOL_SIZE,
    max_overflow: int = _MAX_OVERFLOW,
    echo: bool = False,
) -> Engine:
    """
    Create and return a cached SQLAlchemy Engine instance.

    Uses lru_cache for singleton behaviour — the engine is created once and
    reused across the pipeline. Call get_engine.cache_clear() in tests.

    Args:
        dsn: SQLAlchemy DSN string. If None, reads from settings.
        pool_size: Number of connections to maintain in the pool.
        max_overflow: Maximum extra connections beyond pool_size.
        echo: If True, log all SQL statements (use only for debugging).

    Returns:
        SQLAlchemy Engine with connection pool.

    Raises:
        SQLAlchemyError: If the engine cannot be created.
    """
    if dsn is None:
        from config.settings import get_settings
        dsn = get_settings().database.dsn

    logger.info("Creating SQLAlchemy engine | pool_size=%d | max_overflow=%d", pool_size, max_overflow)

    engine = create_engine(
        dsn,
        poolclass=QueuePool,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_timeout=_POOL_TIMEOUT,
        pool_recycle=_POOL_RECYCLE,
        pool_pre_ping=True,  # Validate connections before use
        echo=echo,
        connect_args={
            "connect_timeout": _CONNECT_TIMEOUT,
            "application_name": "experimentiq",
        },
    )

    # Register a connect event listener to configure each connection
    @event.listens_for(engine, "connect")
    def set_search_path(dbapi_conn: Any, connection_record: Any) -> None:  # type: ignore[name-defined]
        cursor = dbapi_conn.cursor()
        cursor.execute("SET search_path TO public;")
        cursor.close()

    logger.info("SQLAlchemy engine created successfully")
    return engine


def get_session_factory(engine: Optional[Engine] = None) -> sessionmaker:
    """
    Return a sessionmaker bound to the application engine.

    Args:
        engine: Optional Engine instance. Defaults to the singleton engine.

    Returns:
        sessionmaker for creating database sessions.
    """
    if engine is None:
        engine = get_engine()
    return sessionmaker(bind=engine, autocommit=False, autoflush=False)


@contextmanager
def get_session(engine: Optional[Engine] = None) -> Generator[Session, None, None]:
    """
    Context manager that provides a database session with automatic cleanup.

    Commits on clean exit; rolls back on any exception.

    Args:
        engine: Optional Engine. Defaults to the singleton engine.

    Yields:
        SQLAlchemy Session.

    Raises:
        SQLAlchemyError: On database errors (after rollback).

    Usage:
        with get_session() as session:
            result = session.execute(text("SELECT 1"))
    """
    factory = get_session_factory(engine)
    session = factory()
    try:
        yield session
        session.commit()
    except SQLAlchemyError as exc:
        session.rollback()
        logger.error("Session error, rolling back: %s", exc)
        raise
    finally:
        session.close()


@contextmanager
def get_connection(engine: Optional[Engine] = None) -> Generator:
    """
    Context manager that provides a raw SQLAlchemy connection.

    For use when executing raw SQL strings directly.

    Args:
        engine: Optional Engine. Defaults to the singleton engine.

    Yields:
        SQLAlchemy Connection.

    Usage:
        with get_connection() as conn:
            result = conn.execute(text("SELECT COUNT(*) FROM users"))
    """
    if engine is None:
        engine = get_engine()
    with engine.connect() as conn:
        try:
            yield conn
            conn.commit()
        except SQLAlchemyError as exc:
            conn.rollback()
            logger.error("Connection error, rolling back: %s", exc)
            raise


def get_raw_psycopg2_connection(
    dsn: Optional[str] = None,
) -> psycopg2.extensions.connection:
    """
    Return a raw psycopg2 connection for COPY-based bulk loading.

    Unlike the SQLAlchemy connection, this bypasses the ORM layer entirely.
    Used exclusively by the BulkLoader for maximum throughput.

    Args:
        dsn: Psycopg2 DSN string. If None, reads from settings.

    Returns:
        Open psycopg2 connection with autocommit=False.

    Raises:
        psycopg2.OperationalError: If the connection cannot be established.
    """
    if dsn is None:
        from config.settings import get_settings
        settings = get_settings()
        dsn = settings.database.psycopg2_dsn

    conn = psycopg2.connect(dsn, connect_timeout=_CONNECT_TIMEOUT)
    conn.autocommit = False
    logger.debug("Raw psycopg2 connection established")
    return conn


# ---------------------------------------------------------------------------
# Health Check
# ---------------------------------------------------------------------------


def check_database_connectivity(
    max_retries: int = 3,
    retry_delay_seconds: float = 2.0,
) -> bool:
    """
    Verify that the database is reachable with retry logic.

    Args:
        max_retries: Maximum number of connection attempts.
        retry_delay_seconds: Seconds to wait between retries.

    Returns:
        True if the database is reachable; False otherwise.
    """
    engine = get_engine()

    for attempt in range(1, max_retries + 1):
        try:
            with engine.connect() as conn:
                conn.execute(text("SELECT 1"))
            logger.info("Database connectivity check PASSED | attempt=%d", attempt)
            return True
        except OperationalError as exc:
            logger.warning(
                "Database connectivity check failed | attempt=%d/%d | error=%s",
                attempt,
                max_retries,
                exc,
            )
            if attempt < max_retries:
                time.sleep(retry_delay_seconds)

    logger.error("Database is unreachable after %d attempts", max_retries)
    return False


def dispose_engine() -> None:
    """
    Dispose of the engine connection pool and clear the lru_cache.

    Call this at the end of the pipeline or in test teardown to ensure
    all connections are returned to the OS.
    """
    try:
        engine = get_engine()
        engine.dispose()
        logger.info("SQLAlchemy engine disposed")
    except Exception:
        pass
    finally:
        get_engine.cache_clear()
        logger.debug("Engine cache cleared")


# ---------------------------------------------------------------------------
# Type alias (avoids circular import from event listener)
# ---------------------------------------------------------------------------
from typing import Any  # noqa: E402 (placed here intentionally)
