import asyncio
import json
import os
from typing import Any, Dict

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db.models import Base, Workflow, Run, NodeRun, Log
from app.db.session import engine, SessionFactory


WEATHER_GRAPH: Dict[str, Any] = {
    "nodes": [
        {
            "id": "n1",
            "type": "http.request",
            "settings": {
                "method": "GET",
                "url": "https://api.github.com/repos/python/cpython",
                "headers": {"Accept": "application/vnd.github+json"},
                "follow_redirects": True,
                "timeout_seconds": 15.0,
            },
        },
        {
            "id": "n2",
            "type": "llm.simple",
            "settings": {
                "prompt": "Summarize this repository data: {{ n1.data }}",
                "model": "gpt-4o-mini",
            },
        },
        {
            "id": "n3",
            "type": "show",
            "settings": {"title": "LLM Summary"},
        },
    ],
    "edges": [
        {"id": "e1", "from": "n1", "to": "n2"},
        {"id": "e2", "from": "n2", "to": "n3"},
    ],
}


MINIMAL_GRAPH: Dict[str, Any] = {
    "nodes": [
        {"id": "s", "type": "start", "settings": {"payload": {"hello": "world"}}},
        {"id": "show", "type": "show", "settings": {"title": "Hello"}},
    ],
    "edges": [
        {"id": "e1", "from": "s", "to": "show"},
    ],
}


async def clear_db(session: AsyncSession) -> None:
    # order due to FKs with CASCADE
    await session.execute(delete(Log))
    await session.execute(delete(NodeRun))
    await session.execute(delete(Run))
    await session.execute(delete(Workflow))


async def seed_db(session: AsyncSession) -> None:
    await session.execute(
        Workflow.__table__.insert(),
        [
            {
                "name": "Repo Summary (HTTP -> LLM -> Show)",
                "description": "Fetch public repo JSON and summarize with LLM, then display",
                "webhook_slug": None,
                "graph_json": WEATHER_GRAPH,
            },
            {
                "name": "Hello Show",
                "description": "Start -> Show",
                "webhook_slug": None,
                "graph_json": MINIMAL_GRAPH,
            },
        ],
    )


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
    print("Seeded 2 workflows.")


if __name__ == "__main__":
    asyncio.run(main()) 