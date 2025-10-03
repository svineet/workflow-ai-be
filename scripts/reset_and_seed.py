import asyncio
import json
import os
import sys
from typing import Any, Dict

# Ensure 'app' is importable when running as a script
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Base, Workflow, Run, NodeRun, Log
from app.db.session import engine, SessionFactory


async def clear_db(session: AsyncSession) -> None:
    # order due to FKs with CASCADE
    await session.execute(delete(Log))
    await session.execute(delete(NodeRun))
    await session.execute(delete(Run))
    await session.execute(delete(Workflow))
async def seed_db(session: AsyncSession) -> None:
    # Intentionally left empty: example workflows removed
    return None


async def main() -> None:
    confirm = os.getenv("CONFIRM_RESET")
    if confirm is None:
        try:
            ans = input("This will CLEAR workflows, runs, logs. Proceed? [y/N]: ").strip().lower()
        except EOFError:
            ans = "n"
    else:
        ans = confirm.strip().lower()

    if ans not in ("y", "yes"):
        print("Aborting. Set CONFIRM_RESET=y to bypass prompt.")
        return

    # Ensure tables exist before seeding
    async with engine.begin() as conn:  # type: ignore[attr-defined]
        await conn.run_sync(Base.metadata.create_all)

    async with SessionFactory() as session:
        async with session.begin():
            await clear_db(session)
        async with session.begin():
            await seed_db(session)
        await session.commit()
    print("Database cleared. No example workflows seeded.")


if __name__ == "__main__":
    asyncio.run(main()) 