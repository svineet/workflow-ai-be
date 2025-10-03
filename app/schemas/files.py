from __future__ import annotations

from typing import Optional, Literal
from pydantic import BaseModel, Field


class FileRef(BaseModel):
    """Reference to a file stored in object storage.

    This is designed to be frontend-friendly and portable across nodes.
    """

    id: Optional[str] = Field(default=None, description="Database id if persisted")
    storage: Literal["supabase"] = Field(default="supabase", description="Storage provider")
    bucket: str = Field(..., description="Storage bucket name")
    path: str = Field(..., description="Object path inside the bucket")
    content_type: Optional[str] = Field(default=None, description="MIME type, if known")
    size: Optional[int] = Field(default=None, description="Size in bytes, if known")
    # URLs are signed/ephemeral; backend will re-sign when needed
    signed_url: Optional[str] = Field(default=None, description="Signed URL with limited TTL")
    public_url: Optional[str] = Field(default=None, description="Public URL if bucket/object is public")


class FilesOutput(BaseModel):
    """Canonical output envelope for nodes that produce files."""

    files: list[FileRef] = Field(default_factory=list)
