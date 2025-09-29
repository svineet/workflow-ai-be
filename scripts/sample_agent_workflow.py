import asyncio
import os
import sys
from typing import Any, Dict

# Ensure 'app' is importable when running as a script
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__FILE__ if '__FILE__' in globals() else __file__), "..")))

from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import insert

from app.db.models import Base, Workflow
from app.db.session import engine, SessionFactory


AGENT_GRAPH: Dict[str, Any] = {
    "nodes": [
        {
            "id": "agent",
            "type": "agent.react",
            "settings": {
                "system": "You are a math assistant. Use the calculator tool to compute when needed.",
                "prompt": "What is (12 + 7) * 3?",
                "model": "gpt-4o-mini",
                "temperature": 0.0,
                "max_steps": 5
            },
        },
        {"id": "calc", "type": "tool.calculator", "settings": {}},
        {
            "id": "show",
            "type": "show",
            "settings": {"template": "Final: {{ upstream.agent.final }}"},
        },
    ],
    "edges": [
        {"id": "e1", "from": "agent", "to": "show"},
        {"id": "t1", "from": "agent", "to": "calc", "kind": "tool"},
    ],
}


async def main() -> None:
    # Ensure tables exist before inserting
    async with engine.begin() as conn:  # type: ignore[attr-defined]
        await conn.run_sync(Base.metadata.create_all)

    async with SessionFactory() as session:
        async with session.begin():
            await session.execute(
                Workflow.__table__.insert(),
                [
                    {
                        "name": "Agent Calculator Demo",
                        "description": "Agent.react uses calculator tool via tool edge to answer a math question",
                        "webhook_slug": None,
                        "graph_json": AGENT_GRAPH,
                    }
                ],
            )
        await session.commit()
    print("Created workflow: Agent Calculator Demo")


if __name__ == "__main__":
    asyncio.run(main()) 