from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..server.settings import settings


def get_async_engine() -> AsyncEngine:
    return create_async_engine(settings.DATABASE_URL, echo=False, future=True)


engine: AsyncEngine = get_async_engine()
SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)
