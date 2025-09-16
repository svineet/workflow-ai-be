from __future__ import annotations

from typing import Optional

from google.cloud import storage

from ..server.settings import settings


class GCSWriter:
    def __init__(self, bucket_name: Optional[str] = None) -> None:
        self._client = storage.Client()
        self._bucket_name = bucket_name or settings.GCS_BUCKET
        if not self._bucket_name:
            raise RuntimeError("GCS_BUCKET not configured")
        self._bucket = self._client.bucket(self._bucket_name)

    def write_bytes(self, path: str, data: bytes, content_type: str = "application/octet-stream") -> str:
        blob = self._bucket.blob(path)
        blob.upload_from_string(data, content_type=content_type)
        return f"gs://{self._bucket_name}/{path}"
