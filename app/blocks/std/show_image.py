from __future__ import annotations

from typing import Any, Dict, Optional, List
from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext
from ...schemas.files import FileRef


class ShowImageSettings(BaseModel):
    title: Optional[str] = Field(default=None, description="Optional caption/title")
    # Accept either an explicit array of FileRefs or a pointer key into upstream
    files_key: Optional[str] = Field(default=None, description="When set, picks files from upstream[this_key].files")


class ShowImageOutput(BaseModel):
    images: List[FileRef]
    title: Optional[str] = None


@register("show.image")
class ShowImageBlock(Block):
    type_name = "show.image"
    summary = "Display one or more images using FileRefs with signed/public URLs"
    settings_model = ShowImageSettings
    output_model = ShowImageOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        s = self.settings
        upstream = input.get("upstream") or {}
        files_key = s.get("files_key")

        images: List[FileRef] = []

        def coerce_ref(obj: Any) -> Optional[FileRef]:
            try:
                if isinstance(obj, FileRef):
                    return obj
                if isinstance(obj, dict):
                    # Defensive copy and normalize
                    return FileRef.model_validate(obj)
            except Exception:
                return None
            return None

        # First, try files_key from upstream
        if files_key and isinstance(upstream, dict):
            payload = upstream.get(files_key)
            if isinstance(payload, dict) and isinstance(payload.get("files"), list):
                for it in payload.get("files"):
                    fr = coerce_ref(it)
                    if fr:
                        images.append(fr)

        # If none found, try flattening all upstream values searching for files arrays
        if not images:
            for val in upstream.values():
                if isinstance(val, dict) and isinstance(val.get("files"), list):
                    for it in val.get("files"):
                        fr = coerce_ref(it)
                        if fr:
                            images.append(fr)

        # If still none, look for common fields
        if not images and isinstance(upstream, dict):
            for v in upstream.values():
                fr = coerce_ref(v)
                if fr:
                    images.append(fr)

        # If supabase is configured and signed_url missing/expired, re-sign
        refreshed: List[FileRef] = []
        for fr in images:
            if ctx.supabase and fr.storage == "supabase" and (not fr.signed_url):
                try:
                    url = ctx.supabase.create_signed_url(fr.path)
                    fr.signed_url = url
                except Exception:
                    pass
            refreshed.append(fr)

        out = ShowImageOutput(images=refreshed, title=s.get("title"))
        await ctx.logger(
            "show.image: prepared images",
            {"count": len(refreshed), "have_signed": sum(1 for x in refreshed if x.signed_url)},
            node_id=input.get("node_id"),
        )
        return out.model_dump()
