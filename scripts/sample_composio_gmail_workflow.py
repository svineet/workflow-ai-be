import asyncio
from typing import Any, Dict

from app.db.models import Base, Workflow
from app.db.session import engine, SessionFactory


GRAPH: Dict[str, Any] = {
    "nodes": [
        {
            "id": "agent",
            "type": "agent.react",
            "settings": {
                "system": "You are a witty assistant. Come up with a short, funny one-liner (family-friendly).",
                "prompt": "Write a short funny one-liner about coding in Python.",
                "model": "gpt-5",
                "temperature": 1.0,
                "max_steps": 3,
                # Expose gmail send as a tool
                "tools": [
                    {
                        "name": "send_email",
                        "type": "tool.composio",
                        "settings": {
                            "toolkit": "GMAIL",
                            "tool_slug": "GMAIL_SEND_EMAIL",
                            "args": {
                                "to": ["saivineet89+agent@gmail.com"],
                                "subject": "A joke for you",
                                "body": "{{ upstream.agent.final }}"
                            }
                        }
                    }
                ],
            },
        },
    ],
    "edges": [],
}


async def main() -> None:
    async with engine.begin() as conn:  # type: ignore[attr-defined]
        await conn.run_sync(Base.metadata.create_all)

    async with SessionFactory() as session:
        async with session.begin():
            await session.execute(
                Workflow.__table__.insert(),
                [
                    {
                        "name": "Composio Gmail Joke",
                        "description": "Agent generates a one-liner and emails it via Gmail",
                        "webhook_slug": None,
                        "graph_json": GRAPH,
                    }
                ],
            )
        await session.commit()
    print("Created workflow: Composio Gmail Joke")


if __name__ == "__main__":
    asyncio.run(main()) 