from __future__ import annotations

import sys
import logging
import logging.config

import uvicorn
from fastapi import FastAPI
from sqlalchemy.ext.asyncio import AsyncEngine

from ..db.models import Base
from ..db.session import engine
from .middleware import add_cors
from .settings import settings
from .api import router as api_router


# Configure application logging to stdout so it appears in Docker logs
LOGGING = {
    "version": 1,
    "disable_existing_loggers": False,
    "formatters": {
        "default": {"format": "%(asctime)s %(levelname)s [%(name)s] %(message)s"}
    },
    "handlers": {
        "default": {
            "class": "logging.StreamHandler",
            "formatter": "default",
            "stream": "ext://sys.stdout",
        }
    },
    "loggers": {
        "uvicorn": {"handlers": ["default"], "level": "INFO"},
        "uvicorn.error": {"handlers": ["default"], "level": "INFO"},
        "uvicorn.access": {"handlers": ["default"], "level": "INFO"},
        "assistant": {"handlers": ["default"], "level": "INFO", "propagate": False},
        "": {"handlers": ["default"], "level": "INFO"},  # root logger
    },
}

logging.config.dictConfig(LOGGING)


def create_app() -> FastAPI:
    app = FastAPI(title="Workflow AI Backend")
    app.include_router(api_router)

    @app.get("/healthz")
    async def healthz():
        return {"ok": True}

    add_cors(app)

    @app.on_event("startup")
    async def on_startup():
        async with engine.begin() as conn:  # type: ignore[attr-defined]
            await conn.run_sync(Base.metadata.create_all)

    return app


app = create_app()


if __name__ == "__main__":
    uvicorn.run("app.server.main:app", host="0.0.0.0", port=settings.PORT, reload=True)
