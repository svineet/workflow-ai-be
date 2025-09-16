from __future__ import annotations

import os
from typing import List


class Settings:
    def __init__(self) -> None:
        # Core
        self.DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/workflow_ai")
        self.GCS_BUCKET: str = os.getenv("GCS_BUCKET", "")
        self.PORT: int = int(os.getenv("PORT", "8000"))

        # Optional
        self.OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")

        # CORS
        cors_origins_csv = os.getenv("CORS_ORIGINS", "*")
        self.CORS_ORIGINS: List[str] = [origin.strip() for origin in cors_origins_csv.split(",") if origin.strip()]


settings = Settings()
