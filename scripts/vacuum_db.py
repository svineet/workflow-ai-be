import asyncio

from sqlalchemy.ext.asyncio import create_async_engine

from app.server.settings import settings


async def main() -> None:
    # Use AUTOCOMMIT isolation for VACUUM which cannot run inside a transaction
    engine = create_async_engine(settings.DATABASE_URL, isolation_level="AUTOCOMMIT")
    async with engine.connect() as conn:
        # VACUUM FULL ANALYZE entire database
        await conn.exec_driver_sql("VACUUM (FULL, ANALYZE);")
    await engine.dispose()
    print("VACUUM FULL ANALYZE completed.")


if __name__ == "__main__":
    asyncio.run(main()) 