from __future__ import annotations

import asyncio
import threading
from typing import TYPE_CHECKING, Any

from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.db.models.enums import SourceType
from app.services.gemini_file_transfer import cleanup_uploaded_file, prepare_file_part

if TYPE_CHECKING:
    pass

EXTRACTION_PROMPTS = {
    SourceType.PDF: (
        "Extract the readable text from this PDF for search indexing. "
        "Preserve the original language. Return plain text only."
    ),
    SourceType.IMAGE: (
        "Describe this image for retrieval and include any visible text. "
        "Preserve the original language of any text that appears in the image. "
        "Return plain text only."
    ),
    SourceType.AUDIO: (
        "Transcribe or summarize the spoken content in this audio for retrieval. "
        "Preserve the original language. Return plain text only."
    ),
    SourceType.VIDEO: (
        "Describe the important spoken and visible content in this video for retrieval. "
        "Preserve the original language. Return plain text only."
    ),
}


def _is_retryable_content_error(error: BaseException) -> bool:
    from google.genai import errors as genai_errors

    return isinstance(error, genai_errors.ServerError) or (
        isinstance(error, genai_errors.ClientError) and error.code == 429
    )


class GeminiContentService:
    def __init__(
        self,
        *,
        model: str,
        upload_threshold_bytes: int,
        api_key: str | None = None,
        client: Any | None = None,
    ) -> None:
        self._model = model
        self._upload_threshold_bytes = upload_threshold_bytes
        self._api_key = api_key
        self._client = client
        self._client_lock = threading.Lock()

    async def extract_text_content(
        self,
        file_bytes: bytes,
        mime_type: str,
        source_type: SourceType,
    ) -> str:
        prompt = EXTRACTION_PROMPTS[source_type]
        client = self._get_client()
        prepared_file = await prepare_file_part(
            client,
            file_bytes,
            mime_type,
            threshold_bytes=self._upload_threshold_bytes,
        )
        try:
            response = await asyncio.to_thread(
                self._generate_content,
                prompt,
                prepared_file.part,
            )
        finally:
            await cleanup_uploaded_file(client, prepared_file.uploaded_file_name)

        text_content = (response.text or "").strip()
        if not text_content:
            raise ValueError("Gemini content extraction returned empty text")
        return text_content

    @retry(
        retry=retry_if_exception(_is_retryable_content_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _generate_content(
        self,
        prompt: str,
        file_part: object,
    ) -> Any:
        from google.genai import types

        return self._get_client().models.generate_content(
            model=self._model,
            contents=[prompt, file_part],
            config=types.GenerateContentConfig(response_mime_type="text/plain"),
        )

    def _get_client(self) -> Any:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    if not self._api_key:
                        raise ValueError("GEMINI_API_KEY is required for Gemini content extraction")
                    from google import genai

                    self._client = genai.Client(api_key=self._api_key)
        return self._client
