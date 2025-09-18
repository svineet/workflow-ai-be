from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class GcsWriteInput(BaseModel):
    path: str = Field(..., description="GCS object path within bucket")
    content: Optional[Any] = Field(default=None, description="Content to write; if object/list, will be JSON-encoded")
    as_json: bool = Field(default=False, description="Force JSON encoding")


class GcsWriteOutput(BaseModel):
    gcs_uri: str
    size: int


@register("gcs.write")
class GcsWriteBlock(Block):
    type_name = "gcs.write"
    summary = "Write content to a GCS object and return URI and size"
    input_model = GcsWriteInput
    output_model = GcsWriteOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        path = self.params.get("path")
        if not path:
            raise ValueError("gcs.write requires 'path'")
        content = self.params.get("content")
        as_json = bool(self.params.get("as_json"))

        if as_json:
            import json
            data_bytes = json.dumps(content).encode("utf-8")
            content_type = "application/json"
        else:
            if isinstance(content, (dict, list)):
                import json
                data_bytes = json.dumps(content).encode("utf-8")
                content_type = "application/json"
            elif isinstance(content, (bytes, bytearray)):
                data_bytes = bytes(content)
                content_type = "application/octet-stream"
            else:
                data_bytes = (str(content) if content is not None else "").encode("utf-8")
                content_type = "text/plain; charset=utf-8"

        uri = ctx.gcs.write_bytes(path, data_bytes, content_type=content_type)
        return GcsWriteOutput(gcs_uri=uri, size=len(data_bytes)).model_dump()
