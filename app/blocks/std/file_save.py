from __future__ import annotations

from typing import Any, Dict, Optional
from datetime import datetime, timedelta

from pydantic import BaseModel, Field

from ..registry import register
from ..base import Block, RunContext
from ...schemas.files import FileRef, FilesOutput
from ...server.settings import settings
from ...db.session import SessionFactory
from ...db.models import FileAsset


class FileSaveSettings(BaseModel):
    # Either take explicit bytes/base64 and metadata, or accept upstream file refs
    # For first version, we assume inputs are provided as a dictionary:
    # - content: bytes | base64 string | text
    # - filename/path: where to store inside bucket
    # - content_type: optional MIME
    path: str = Field(..., description="Object path within bucket e.g. generated/123.png")
    content: Optional[Any] = Field(default=None, description="Content: bytes, base64 string (prefix optional), or text")
    content_type: Optional[str] = Field(default=None)
    use_public_url: bool = Field(default=False, description="Also compute a public URL if bucket is public")
    bucket: Optional[str] = Field(default=None, description="Override storage bucket")


class FileSaveOutput(FilesOutput):
    pass


@register("file.save")
class FileSaveBlock(Block):
    type_name = "file.save"
    summary = "Save file bytes to Supabase Storage and persist a FileAsset record"
    settings_model = FileSaveSettings
    output_model = FileSaveOutput

    async def run(self, input: Dict[str, Any], ctx: RunContext) -> Dict[str, Any]:
        if ctx.supabase is None:
            raise RuntimeError("Supabase is not configured. Set SUPABASE_URL, SUPABASE_SERVICE_KEY and SUPABASE_STORAGE_BUCKET")

        s = self.settings
        raw_content = s.get("content")
        content_type = s.get("content_type")
        bucket = s.get("bucket") or ctx.supabase.bucket
        path_raw = s.get("path")
        if not path_raw:
            raise ValueError("file.save requires 'path'")

        # Render path and any string content
        path = self.render_expression(str(path_raw), upstream=input.get("upstream") or {}, extra={"settings": s, "trigger": input.get("trigger") or {}})

        # Resolve content into bytes. If not explicitly provided, fall back to first upstream FileRef.
        data_bytes: bytes
        if raw_content is None:
            # Try aggregated files passed in input
            first_fr: Optional[FileRef] = None
            try:
                files_list = input.get("files") or []
                if isinstance(files_list, list) and files_list:
                    candidate = files_list[0]
                    if isinstance(candidate, FileRef):
                        first_fr = candidate
                    elif isinstance(candidate, dict):
                        first_fr = FileRef.model_validate(candidate)
            except Exception:
                first_fr = None

            if first_fr is not None:
                # Prefer content type from source
                if first_fr.content_type and not content_type:
                    content_type = first_fr.content_type
                # Ensure we have a signed URL
                signed = first_fr.signed_url
                if not signed and ctx.supabase and first_fr.storage == "supabase":
                    try:
                        signed = ctx.supabase.create_signed_url(first_fr.path)
                    except Exception:
                        signed = None
                if not signed:
                    raise ValueError("file.save could not resolve content: upstream FileRef missing signed_url and cannot re-sign")
                # Download bytes
                resp = await ctx.http.get(signed)
                data_bytes = await resp.aread()
            else:
                raise ValueError("file.save requires 'content' or upstream 'files'")
        elif isinstance(raw_content, (bytes, bytearray)):
            data_bytes = bytes(raw_content)
        elif isinstance(raw_content, str):
            # Detect data URL or base64 prefix
            txt = self.render_expression(raw_content, upstream=input.get("upstream") or {}, extra={"settings": s, "trigger": input.get("trigger") or {}})
            if txt.startswith("data:") and ";base64," in txt:
                try:
                    meta, b64 = txt.split(",", 1)
                    if not content_type and meta.startswith("data:"):
                        content_type = meta[5:].split(";")[0] or content_type
                    import base64
                    data_bytes = base64.b64decode(b64)
                except Exception:
                    data_bytes = txt.encode("utf-8")
                    if not content_type:
                        content_type = "text/plain; charset=utf-8"
            else:
                # Maybe plain base64 without data URL
                try:
                    import base64
                    data_bytes = base64.b64decode(txt)
                    if not content_type:
                        content_type = "application/octet-stream"
                except Exception:
                    data_bytes = txt.encode("utf-8")
                    if not content_type:
                        content_type = "text/plain; charset=utf-8"
        else:
            # JSON-like content
            import json
            data_bytes = json.dumps(raw_content).encode("utf-8")
            content_type = content_type or "application/json"

        # Upload to Supabase
        uri = ctx.supabase.upload_bytes(path, data_bytes, content_type=content_type or "application/octet-stream", upsert=True)

        # Generate signed URL and optionally public URL
        signed_url_ttl = settings.SUPABASE_SIGNED_URL_EXPIRES_SECS or 3600
        signed_url = ctx.supabase.create_signed_url(path, expires_in=signed_url_ttl)
        public_url = ctx.supabase.public_url(path) if bool(s.get("use_public_url")) else None

        # Persist FileAsset in DB
        async with SessionFactory() as session:
            expires_at = datetime.utcnow() + timedelta(seconds=int(signed_url_ttl))
            fa = FileAsset(
                run_id=ctx.run_id,
                node_id=input.get("node_id") or "",
                storage="supabase",
                bucket=bucket,
                path=path,
                content_type=content_type,
                size=len(data_bytes),
                signed_url=signed_url,
                signed_url_expires_at=expires_at,
                public_url=public_url,
            )
            session.add(fa)
            await session.commit()
            await session.refresh(fa)

        # Build FileRef for output
        fileref = FileRef(
            id=str(fa.id),
            storage="supabase",
            bucket=bucket,
            path=path,
            content_type=content_type,
            size=len(data_bytes),
            signed_url=signed_url,
            public_url=public_url,
        )

        # Log concise data
        await ctx.logger("file.save: uploaded", {"path": path, "bucket": bucket, "size": len(data_bytes), "content_type": content_type}, node_id=input.get("node_id"))

        return FileSaveOutput(files=[fileref]).model_dump()
