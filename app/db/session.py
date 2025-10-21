from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine

from ..server.settings import settings


def get_async_engine() -> AsyncEngine:
    return create_async_engine(settings.DATABASE_URL, echo=False, future=True)


import ssl

ssl_ctx = ssl.create_default_context()

engine: AsyncEngine = get_async_engine().execution_options(
    connect_args={"ssl": ssl_ctx}
)

SessionFactory: async_sessionmaker[AsyncSession] = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
    autoflush=False,
)
