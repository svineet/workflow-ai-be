from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel


class RunCreate(BaseModel):
    start_input: Optional[Dict[str, Any]] = None


class RunResponse(BaseModel):
    id: int
    workflow_id: int
    status: str
    started_at: Optional[str] = None
    finished_at: Optional[str] = None
    trigger_type: Optional[str] = None
    outputs_json: Optional[Dict[str, Any]] = None
