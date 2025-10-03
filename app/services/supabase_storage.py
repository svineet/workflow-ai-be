from __future__ import annotations

from dataclasses import dataclass
from io import BytesIO
from typing import Optional

from .gcs import GCSWriter  # keep import for parity and potential fallbacks
from ..server.settings import settings


class SupabaseNotConfigured(RuntimeError):
    pass


@dataclass
class SupabaseConfig:
    url: Optional[str]
    service_key: Optional[str]
    bucket: Optional[str]
    signed_url_expires_secs: int


class SupabaseStorage:
    """Lightweight wrapper around supabase-py for storage uploads and signed URLs.

    Lazily initializes the Supabase client so the app can run without Supabase
    configured in environments where this feature is not used.
    """

    def __init__(self, *, url: Optional[str] = None, service_key: Optional[str] = None,
                 bucket: Optional[str] = None, signed_url_expires_secs: Optional[int] = None) -> None:
        cfg = SupabaseConfig(
            url=url or settings.SUPABASE_URL,
            service_key=service_key or settings.SUPABASE_SERVICE_KEY,
            bucket=bucket or settings.SUPABASE_STORAGE_BUCKET,
            signed_url_expires_secs=(
                settings.SUPABASE_SIGNED_URL_EXPIRES_SECS if signed_url_expires_secs is None else signed_url_expires_secs
            ),
        )
        self._cfg = cfg
        self._client = None

    def _ensure_client(self):
        if self._client is not None:
            return self._client
        if not self._cfg.url or not self._cfg.service_key or not self._cfg.bucket:
            raise SupabaseNotConfigured(
                "Supabase is not configured. Set SUPABASE_URL, SUPABASE_SERVICE_KEY and SUPABASE_STORAGE_BUCKET."
            )
        try:
            # Lazy import to avoid hard dependency when unused
            from supabase import create_client  # type: ignore
        except Exception as ex:
            raise RuntimeError(
                "Supabase client library not installed. Add 'supabase' to requirements.txt"
            ) from ex
        self._client = create_client(self._cfg.url, self._cfg.service_key)
        return self._client

    @property
    def bucket(self) -> str:
        if not self._cfg.bucket:
            raise SupabaseNotConfigured("SUPABASE_STORAGE_BUCKET not configured")
        return self._cfg.bucket

    def upload_bytes(self, path: str, data: bytes, *, content_type: str = "application/octet-stream", upsert: bool = True) -> str:
        """Upload bytes to Supabase Storage. Returns a storage URI like supabase://bucket/path."""
        client = self._ensure_client()
        storage = client.storage.from_(self.bucket)
        # supabase-py expects a file-like for binary buffers
        file_obj = BytesIO(data)
        # As of supabase-py v2, upload signature is (path, file, file_options)
        file_options = {"contentType": content_type, "upsert": upsert}
        res = storage.upload(path, file_obj, file_options=file_options)
        # res is usually dict with 'path' key or raises on error
        _ = res  # not used but kept for future checks
        return f"supabase://{self.bucket}/{path}"

    def create_signed_url(self, path: str, *, expires_in: Optional[int] = None) -> str:
        client = self._ensure_client()
        storage = client.storage.from_(self.bucket)
        ttl = int(expires_in or self._cfg.signed_url_expires_secs)
        result = storage.create_signed_url(path, ttl)
        # result may be dict like { 'signedURL': 'https://...' } or {'signed_url': ...} depending on version
        url = None
        for key in ("signedURL", "signed_url", "url"):
            try:
                val = result.get(key)  # type: ignore[assignment]
                if isinstance(val, str) and val:
                    url = val
                    break
            except Exception:
                pass
        if not url:
            # Some versions return a plain string
            if isinstance(result, str):
                url = result
        if not isinstance(url, str) or not url:
            raise RuntimeError("Failed to obtain a signed URL from Supabase response")
        return url

    def public_url(self, path: str) -> str:
        client = self._ensure_client()
        storage = client.storage.from_(self.bucket)
        result = storage.get_public_url(path)
        url = None
        try:
            url = result.get("publicURL")  # type: ignore[attr-defined]
        except Exception:
            pass
        if not url and isinstance(result, str):
            url = result
        if not isinstance(url, str) or not url:
            raise RuntimeError("Failed to obtain a public URL from Supabase response")
        return url
