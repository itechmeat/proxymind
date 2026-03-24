from __future__ import annotations

import asyncio
import io
from dataclasses import dataclass
from time import monotonic
from typing import Any

import structlog
from google.genai import types

logger = structlog.get_logger(__name__)


@dataclass(slots=True, frozen=True)
class PreparedFilePart:
    part: object
    uploaded_file_name: str | None


async def prepare_file_part(
    client: Any,
    file_bytes: bytes,
    mime_type: str,
    *,
    threshold_bytes: int,
) -> PreparedFilePart:
    if len(file_bytes) < threshold_bytes:
        return PreparedFilePart(
            part=types.Part.from_bytes(data=file_bytes, mime_type=mime_type),
            uploaded_file_name=None,
        )

    uploaded_file = await asyncio.to_thread(
        client.files.upload,
        file=io.BytesIO(file_bytes),
        config=types.UploadFileConfig(mime_type=mime_type),
    )
    await _wait_until_active(client, uploaded_file.name)
    return PreparedFilePart(
        part=types.Part.from_uri(file_uri=uploaded_file.uri, mime_type=mime_type),
        uploaded_file_name=uploaded_file.name,
    )


async def _wait_until_active(
    client: Any,
    file_name: str,
    *,
    poll_interval: float = 1.0,
    max_wait: float = 300.0,
) -> None:
    deadline = monotonic() + max_wait
    while True:
        current_file = await asyncio.to_thread(client.files.get, name=file_name)
        state_name = _normalize_file_state(getattr(current_file, "state", None))
        if state_name == "ACTIVE":
            return
        if state_name == "FAILED":
            raise RuntimeError(f"Gemini Files API processing failed for {file_name}")
        if monotonic() >= deadline:
            raise TimeoutError(f"Timed out waiting for Gemini file {file_name} to become ACTIVE")
        await asyncio.sleep(poll_interval)


async def cleanup_uploaded_file(client: Any, file_name: str | None) -> None:
    if file_name is None:
        return
    try:
        await asyncio.to_thread(client.files.delete, name=file_name)
    except Exception as error:
        logger.warning(
            "gemini_file_transfer.cleanup_failed",
            file_name=file_name,
            error=str(error),
        )


def _normalize_file_state(raw_state: object) -> str | None:
    if raw_state is None:
        return None
    state_name = getattr(raw_state, "name", None)
    if isinstance(state_name, str):
        return state_name
    if isinstance(raw_state, str):
        return raw_state
    return str(raw_state).split(".")[-1]
