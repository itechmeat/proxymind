from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai.errors import ServerError

from app.db.models.enums import SourceType
from app.services.gemini_content import EXTRACTION_PROMPTS, GeminiContentService
from app.services.gemini_file_transfer import PreparedFilePart


class FakeModels:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    def generate_content(self, *, model: str, contents: list[object], config: object) -> object:
        self.calls.append({"model": model, "contents": list(contents), "config": config})
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def test_extraction_prompts_are_language_neutral() -> None:
    assert all(
        "preserve the original language" in prompt.lower()
        for prompt in EXTRACTION_PROMPTS.values()
    )


@pytest.mark.asyncio
async def test_extract_text_content_uses_prompt_for_source_type(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = FakeModels([SimpleNamespace(text="image description")])

    async def fake_prepare_file_part(*args, **kwargs) -> PreparedFilePart:
        return PreparedFilePart(part="prepared-part", uploaded_file_name=None)  # type: ignore[arg-type]

    monkeypatch.setattr("app.services.gemini_content.prepare_file_part", fake_prepare_file_part)
    service = GeminiContentService(
        model="gemini-2.5-flash",
        upload_threshold_bytes=10,
        client=SimpleNamespace(models=models),  # type: ignore[arg-type]
    )

    text = await service.extract_text_content(b"image", "image/png", SourceType.IMAGE)

    assert text == "image description"
    assert models.calls[0]["contents"] == [EXTRACTION_PROMPTS[SourceType.IMAGE], "prepared-part"]
    assert models.calls[0]["config"].response_mime_type == "text/plain"


@pytest.mark.asyncio
async def test_extract_text_content_retries_transient_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    models = FakeModels(
        [
            ServerError(503, {"error": {"message": "temporary", "status": "UNAVAILABLE"}}, None),
            SimpleNamespace(text="ok"),
        ]
    )

    async def fake_prepare_file_part(*args, **kwargs) -> PreparedFilePart:
        return PreparedFilePart(part="prepared-part", uploaded_file_name=None)  # type: ignore[arg-type]

    monkeypatch.setattr("app.services.gemini_content.prepare_file_part", fake_prepare_file_part)
    service = GeminiContentService(
        model="gemini-2.5-flash",
        upload_threshold_bytes=10,
        client=SimpleNamespace(models=models),  # type: ignore[arg-type]
    )

    text = await service.extract_text_content(b"audio", "audio/mpeg", SourceType.AUDIO)

    assert text == "ok"
    assert len(models.calls) == 2


@pytest.mark.asyncio
async def test_extract_text_content_cleans_up_uploaded_files(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    cleanup_calls: list[str | None] = []
    models = FakeModels([SimpleNamespace(text="pdf text")])

    async def fake_prepare_file_part(*args, **kwargs) -> PreparedFilePart:
        return PreparedFilePart(part="prepared-part", uploaded_file_name="files/123")  # type: ignore[arg-type]

    async def fake_cleanup_uploaded_file(_client, file_name: str | None) -> None:
        cleanup_calls.append(file_name)

    monkeypatch.setattr("app.services.gemini_content.prepare_file_part", fake_prepare_file_part)
    monkeypatch.setattr(
        "app.services.gemini_content.cleanup_uploaded_file",
        fake_cleanup_uploaded_file,
    )
    service = GeminiContentService(
        model="gemini-2.5-flash",
        upload_threshold_bytes=10,
        client=SimpleNamespace(models=models),  # type: ignore[arg-type]
    )

    await service.extract_text_content(b"pdf", "application/pdf", SourceType.PDF)

    assert cleanup_calls == ["files/123"]
