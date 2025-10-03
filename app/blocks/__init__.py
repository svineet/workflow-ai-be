from __future__ import annotations

# Import std blocks to populate registry on module load
from .std import start, http_request, gcs_write, llm_simple, show, web_get, agent_react, file_save, show_image  # noqa: F401

# Import class-based executors (stubs for now)
from . import executors  # noqa: F401
