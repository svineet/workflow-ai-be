from __future__ import annotations

import os, json
from typing import List, Dict

try:
    from dotenv import load_dotenv  # type: ignore
    # Load default .env and optional ENV_FILE override for local runs
    load_dotenv()
    env_file_override = os.getenv("ENV_FILE")
    if env_file_override:
        load_dotenv(env_file_override, override=False)
except Exception:
    # dotenv is optional; ignore if unavailable
    pass


class Settings:
    def __init__(self) -> None:
        # Core
        self.DATABASE_URL: str = os.getenv("DATABASE_URL", "postgresql+asyncpg://postgres:postgres@localhost:5432/workflow_ai")
        self.GCS_BUCKET: str = os.getenv("GCS_BUCKET", "")
        self.PORT: int = int(os.getenv("PORT", "8000"))

        # Optional
        self.OPENAI_API_KEY: str | None = os.getenv("OPENAI_API_KEY")
        self.COMPOSIO_API_KEY: str | None = os.getenv("COMPOSIO_API_KEY")
        composio_toolkits_csv = os.getenv("COMPOSIO_TOOLKITS", "GMAIL,GOOGLE_DRIVE,SLACK")
        self.COMPOSIO_TOOLKITS: List[str] = [t.strip() for t in composio_toolkits_csv.split(",") if t.strip()]
        try:
            self.COMPOSIO_AUTH_CONFIGS: Dict[str, str] = json.loads(os.getenv("COMPOSIO_AUTH_CONFIGS", "{}"))
        except Exception:
            self.COMPOSIO_AUTH_CONFIGS = {}

        # CORS
        cors_origins_csv = os.getenv("CORS_ORIGINS", "*")
        self.CORS_ORIGINS: List[str] = [origin.strip() for origin in cors_origins_csv.split(",") if origin.strip()]

        # Frontend base URL for redirects to SPA routes
        self.FRONTEND_BASE_URL: str | None = os.getenv("FRONTEND_BASE_URL")

        # Supabase (optional, used for File Save & media)
        self.SUPABASE_URL: str | None = os.getenv("SUPABASE_URL")
        self.SUPABASE_SERVICE_KEY: str | None = os.getenv("SUPABASE_SERVICE_KEY")
        self.SUPABASE_STORAGE_BUCKET: str | None = os.getenv("SUPABASE_STORAGE_BUCKET")
        try:
            self.SUPABASE_SIGNED_URL_EXPIRES_SECS: int = int(os.getenv("SUPABASE_SIGNED_URL_EXPIRES_SECS", "3600"))
        except Exception:
            self.SUPABASE_SIGNED_URL_EXPIRES_SECS = 3600


settings = Settings()
