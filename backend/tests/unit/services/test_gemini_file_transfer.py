from __future__ import annotations

from types import SimpleNamespace

import pytest
from google.genai import types

from app.services import gemini_file_transfer as transfer


class FakeFiles:
    def __init__(self) -> None:
        self.upload_calls: list[dict[str, object]] = []
        self.get_calls: list[str] = []
        self.delete_calls: list[str] = []
        self.get_responses: list[object] = []

    def upload(self, *, file, config):
        self.upload_calls.append({"file": file, "config": config})
        return SimpleNamespace(name="files/123", uri="gs://files/123")

    def get(self, *, name: str, config=None):
        self.get_calls.append(name)
        return self.get_responses.pop(0)

    def delete(self, *, name: str, config=None):
        self.delete_calls.append(name)
        return None


@pytest.mark.asyncio
async def test_prepare_file_part_uses_inline_transfer_below_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = FakeFiles()
    client = SimpleNamespace(files=files)
    captured: dict[str, object] = {}

    def fake_from_bytes(*, data: bytes, mime_type: str, media_resolution=None):
        captured["data"] = data
        captured["mime_type"] = mime_type
        return "inline-part"

    monkeypatch.setattr(transfer.types.Part, "from_bytes", fake_from_bytes)

    prepared = await transfer.prepare_file_part(
        client,
        b"hello",
        "image/png",
        threshold_bytes=10,
    )

    assert prepared.part == "inline-part"
    assert prepared.uploaded_file_name is None
    assert captured == {"data": b"hello", "mime_type": "image/png"}
    assert files.upload_calls == []


@pytest.mark.asyncio
async def test_prepare_file_part_uses_files_api_at_threshold(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    files = FakeFiles()
    files.get_responses = [SimpleNamespace(state=types.FileState.ACTIVE)]
    client = SimpleNamespace(files=files)

    monkeypatch.setattr(
        transfer.types.Part,
        "from_uri",
        lambda *, file_uri, mime_type=None, media_resolution=None: {
            "uri": file_uri,
            "mime": mime_type,
        },
    )

    prepared = await transfer.prepare_file_part(
        client,
        b"x" * 10,
        "video/mp4",
        threshold_bytes=10,
    )

    assert prepared.part == {"uri": "gs://files/123", "mime": "video/mp4"}
    assert prepared.uploaded_file_name == "files/123"
    assert files.upload_calls[0]["config"].mime_type == "video/mp4"
    assert files.get_calls == ["files/123"]


@pytest.mark.asyncio
async def test_wait_until_active_polls_until_file_is_ready() -> None:
    files = FakeFiles()
    files.get_responses = [
        SimpleNamespace(state=types.FileState.PROCESSING),
        SimpleNamespace(state=types.FileState.ACTIVE),
    ]
    client = SimpleNamespace(files=files)

    await transfer._wait_until_active(client, "files/123", poll_interval=0.0, max_wait=1.0)

    assert files.get_calls == ["files/123", "files/123"]


@pytest.mark.asyncio
async def test_wait_until_active_times_out() -> None:
    files = FakeFiles()
    files.get_responses = [SimpleNamespace(state=types.FileState.PROCESSING)]
    client = SimpleNamespace(files=files)

    with pytest.raises(TimeoutError, match="files/123"):
        await transfer._wait_until_active(client, "files/123", poll_interval=0.0, max_wait=0.0)


@pytest.mark.asyncio
async def test_cleanup_uploaded_file_logs_and_suppresses_delete_errors(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    messages: list[dict[str, object]] = []

    class ExplodingFiles:
        def delete(self, *, name: str, config=None):
            raise RuntimeError("boom")

    monkeypatch.setattr(
        transfer,
        "logger",
        SimpleNamespace(
            warning=lambda event, **kwargs: messages.append({"event": event, **kwargs})
        ),
    )

    await transfer.cleanup_uploaded_file(SimpleNamespace(files=ExplodingFiles()), "files/123")

    assert messages == [
        {
            "event": "gemini_file_transfer.cleanup_failed",
            "file_name": "files/123",
            "error": "boom",
        }
    ]
