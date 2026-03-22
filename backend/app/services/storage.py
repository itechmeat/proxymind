from __future__ import annotations

import re
import uuid
from os.path import basename, splitext

import httpx

from app.db.models.enums import SourceType

ALLOWED_SOURCE_EXTENSIONS = (".md", ".txt")
SOURCE_TYPE_BY_EXTENSION = {
    ".md": SourceType.MARKDOWN,
    ".txt": SourceType.TXT,
}
_UNSAFE_FILENAME_CHARS = re.compile(r"[^A-Za-z0-9._-]+")
_MAX_FILENAME_LENGTH = 255


def sanitize_filename(filename: str) -> str:
    normalized = filename.replace("\\", "/").split("/")[-1]
    cleaned = _UNSAFE_FILENAME_CHARS.sub("_", normalized).strip("._")
    if not cleaned:
        cleaned = "upload"

    if len(cleaned) <= _MAX_FILENAME_LENGTH:
        return cleaned

    stem, suffix = splitext(cleaned)
    available = _MAX_FILENAME_LENGTH - len(suffix)
    if available <= 0:
        return cleaned[:_MAX_FILENAME_LENGTH]
    return f"{stem[:available]}{suffix}"


def validate_file_extension(filename: str) -> str:
    extension = splitext(filename or "")[1].lower()
    if extension not in ALLOWED_SOURCE_EXTENSIONS:
        allowed = ", ".join(ALLOWED_SOURCE_EXTENSIONS)
        raise ValueError(f"Unsupported file format. Allowed extensions: {allowed}")
    return extension


def determine_source_type(filename: str) -> SourceType:
    extension = validate_file_extension(filename)
    return SOURCE_TYPE_BY_EXTENSION[extension]


class StorageService:
    def __init__(self, http_client: httpx.AsyncClient, base_path: str) -> None:
        normalized_base_path = f"/{base_path.strip('/')}" if base_path.strip("/") else "/"
        self._http_client = http_client
        self.base_path = normalized_base_path

    def _build_url(self, object_key: str) -> str:
        normalized_object_key = object_key.lstrip("/")
        if self.base_path == "/":
            return "/" if not normalized_object_key else f"/{normalized_object_key}"
        if not normalized_object_key:
            return f"{self.base_path}/"
        return f"{self.base_path}/{normalized_object_key}"

    @staticmethod
    def generate_object_key(agent_id: uuid.UUID, source_id: uuid.UUID, filename: str) -> str:
        safe_filename = sanitize_filename(filename)
        return f"{agent_id}/{source_id}/{safe_filename}"

    async def ensure_storage_root(self) -> None:
        response = await self._http_client.post(self._build_url(""))
        response.raise_for_status()

    async def upload(
        self,
        object_key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> None:
        response = await self._http_client.post(
            self._build_url(object_key),
            files={
                "file": (
                    basename(object_key) or "upload",
                    content,
                    content_type or "application/octet-stream",
                )
            },
        )
        response.raise_for_status()

    async def download(self, object_key: str) -> bytes:
        response = await self._http_client.get(self._build_url(object_key))
        response.raise_for_status()
        return response.content

    async def delete(self, object_key: str) -> None:
        response = await self._http_client.delete(self._build_url(object_key))
        response.raise_for_status()
