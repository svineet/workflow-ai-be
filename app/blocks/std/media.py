from __future__ import annotations

from pydantic import BaseModel, Field
from typing import Literal, Optional


class Media(BaseModel):
    kind: Literal["audio", "image", "file"]
    mime: str
    bytes_b64: str
    filename: Optional[str] = Field(default=None)
    size: Optional[int] = Field(default=None)
    uri: Optional[str] = Field(default=None) 