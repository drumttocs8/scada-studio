"""
Async database engine and session factory.

Engine is created lazily on first use so the app can start even
without a database (e.g. Railway sidecar-only deployment).
"""

import logging
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from config import get_settings

logger = logging.getLogger(__name__)

_engine = None
_async_session = None


def _get_engine():
    global _engine, _async_session
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(
            settings.database_url, echo=False, pool_size=5, max_overflow=10
        )
        _async_session = async_sessionmaker(
            _engine, class_=AsyncSession, expire_on_commit=False
        )
        logger.info("Database engine created")
    return _engine, _async_session


async def get_db() -> AsyncSession:
    """FastAPI dependency — yields an async DB session."""
    _, session_factory = _get_engine()
    async with session_factory() as session:
        yield session
