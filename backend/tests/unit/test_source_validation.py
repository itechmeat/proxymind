from __future__ import annotations

import pytest
from minio.error import S3Error
from pydantic import ValidationError

from app.api.schemas import SourceUploadMetadata
from app.db.models.enums import SourceType
from app.services.storage import StorageService, determine_source_type, validate_file_extension


def test_generate_object_key_sanitizes_and_formats_values() -> None:
    object_key = StorageService.generate_object_key(
        agent_id="00000000-0000-0000-0000-000000000001",  # type: ignore[arg-type]
        source_id="00000000-0000-0000-0000-000000000099",  # type: ignore[arg-type]
        filename="../../unsafe name!!.md",
    )

    assert object_key == (
        "00000000-0000-0000-0000-000000000001/00000000-0000-0000-0000-000000000099/unsafe_name_.md"
    )


def test_generate_object_key_truncates_long_filenames() -> None:
    object_key = StorageService.generate_object_key(
        agent_id="00000000-0000-0000-0000-000000000001",  # type: ignore[arg-type]
        source_id="00000000-0000-0000-0000-000000000099",  # type: ignore[arg-type]
        filename=f"{'a' * 300}.md",
    )

    filename = object_key.rsplit("/", maxsplit=1)[-1]
    assert len(filename) <= 255
    assert filename.endswith(".md")


@pytest.mark.parametrize("filename", ["notes.md", "DOCUMENT.MD", "note.Txt"])
def test_validate_file_extension_accepts_supported_types_case_insensitively(
    filename: str,
) -> None:
    assert validate_file_extension(filename) in {".md", ".txt"}


def test_validate_file_extension_rejects_unsupported_types() -> None:
    with pytest.raises(ValueError, match="Unsupported file format"):
        validate_file_extension("notes.pdf")


@pytest.mark.parametrize(
    ("filename", "expected"),
    [("notes.md", SourceType.MARKDOWN), ("notes.TXT", SourceType.TXT)],
)
def test_determine_source_type_maps_extension(filename: str, expected: SourceType) -> None:
    assert determine_source_type(filename) is expected


def test_source_upload_metadata_requires_title() -> None:
    with pytest.raises(ValidationError):
        SourceUploadMetadata.model_validate_json('{"description":"missing title"}')


def test_source_upload_metadata_rejects_title_too_long() -> None:
    with pytest.raises(ValidationError):
        SourceUploadMetadata.model_validate_json('{"title":"' + ("a" * 256) + '"}')


def test_source_upload_metadata_rejects_invalid_json() -> None:
    with pytest.raises(ValidationError):
        SourceUploadMetadata.model_validate_json("not json")


def test_source_upload_metadata_rejects_invalid_public_url() -> None:
    with pytest.raises(ValidationError):
        SourceUploadMetadata.model_validate_json('{"title":"Doc","public_url":"ftp://example.com"}')


@pytest.mark.asyncio
async def test_ensure_bucket_ignores_already_existing_bucket_error() -> None:
    class FakeClient:
        def make_bucket(self, bucket_name: str) -> None:
            raise S3Error(
                response=object(),  # type: ignore[arg-type]
                code="BucketAlreadyOwnedByYou",
                message="bucket exists",
                resource=f"/{bucket_name}",
                request_id="req",
                host_id="host",
                bucket_name=bucket_name,
            )

    service = StorageService(FakeClient(), "sources")  # type: ignore[arg-type]
    await service.ensure_bucket()
