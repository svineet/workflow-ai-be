from __future__ import annotations

from typing import Any, Dict, Optional

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext


class CodeInterpreterToolSettings(BaseModel):
    name: Optional[str] = Field(default=None, description="Optional tool name override")


class CIOutput(BaseModel):
    ok: bool


@register("tool.code_interpreter")
class CodeInterpreterToolBlock(Block):
    type_name = "tool.code_interpreter"
    summary = "Code interpreter tool (Agents SDK hosted tool)"
    settings_model = CodeInterpreterToolSettings
    output_model = CIOutput
    tool_compatible = True

    @classmethod
    def extras(cls) -> Dict[str, Any]:
        return {"toolCompatible": True}

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        return CIOutput(ok=True).model_dump()


