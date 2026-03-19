from __future__ import annotations

import asyncio
import re
import uuid
from io import BytesIO
from os.path import splitext

from minio import Minio
from minio.error import S3Error

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
    def __init__(self, client: Minio, bucket_name: str) -> None:
        self._client = client
        self.bucket_name = bucket_name

    @staticmethod
    def generate_object_key(agent_id: uuid.UUID, source_id: uuid.UUID, filename: str) -> str:
        safe_filename = sanitize_filename(filename)
        return f"{agent_id}/{source_id}/{safe_filename}"

    async def ensure_bucket(self) -> None:
        try:
            await asyncio.to_thread(self._client.make_bucket, self.bucket_name)
        except S3Error as error:
            if error.code not in {"BucketAlreadyOwnedByYou", "BucketAlreadyExists"}:
                raise

    async def upload(
        self,
        object_key: str,
        content: bytes,
        content_type: str | None = None,
    ) -> None:
        stream = BytesIO(content)
        await asyncio.to_thread(
            self._client.put_object,
            self.bucket_name,
            object_key,
            stream,
            len(content),
            content_type=content_type or "application/octet-stream",
        )

    async def download(self, object_key: str) -> bytes:
        def _download() -> bytes:
            response = self._client.get_object(self.bucket_name, object_key)
            try:
                return response.read()
            finally:
                response.close()
                response.release_conn()

        return await asyncio.to_thread(_download)

    async def delete(self, object_key: str) -> None:
        await asyncio.to_thread(self._client.remove_object, self.bucket_name, object_key)
