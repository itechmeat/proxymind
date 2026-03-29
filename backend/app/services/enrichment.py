from __future__ import annotations

import asyncio
import json
import threading
from collections.abc import Sequence
from dataclasses import dataclass
from typing import Any

import structlog
from pydantic import BaseModel, Field
from tenacity import retry, retry_if_exception, stop_after_attempt, wait_exponential

from app.services.gemini_client import create_genai_client
from app.services.token_counter import CHARS_PER_TOKEN

PIPELINE_VERSION = "s9-01-enrichment-v1"
logger = structlog.get_logger(__name__)

ENRICHMENT_PROMPT = """You are a search optimization assistant. Given a text chunk from a document, generate metadata to improve search retrieval.

<chunk>
{text_content}
</chunk>

Return JSON with:
- summary: 1-2 sentence description of what this chunk contains
- keywords: 5-8 search terms including synonyms and related concepts
- questions: 2-3 natural questions this chunk can answer"""


class EnrichmentSchema(BaseModel):
    summary: str = Field(min_length=1)
    keywords: list[str] = Field(min_length=1)
    questions: list[str] = Field(min_length=1)


@dataclass(slots=True, frozen=True)
class EnrichmentResult:
    summary: str
    keywords: list[str]
    questions: list[str]


def _normalize_enrichment_result(payload: EnrichmentSchema) -> EnrichmentResult:
    summary = payload.summary.strip()
    keywords = [keyword.strip() for keyword in payload.keywords if keyword.strip()]
    questions = [question.strip() for question in payload.questions if question.strip()]
    if not summary or not keywords or not questions:
        raise ValueError("Gemini enrichment returned incomplete structured output")
    return EnrichmentResult(summary=summary, keywords=keywords, questions=questions)


def _is_retryable_enrichment_error(error: BaseException) -> bool:
    from google.genai import errors as genai_errors

    return isinstance(error, genai_errors.ServerError) or (
        isinstance(error, genai_errors.ClientError) and getattr(error, "code", None) == 429
    )


class EnrichmentService:
    def __init__(
        self,
        *,
        model: str,
        temperature: float,
        max_output_tokens: int,
        min_chunk_tokens: int,
        max_concurrency: int,
        request_timeout_seconds: float = 30.0,
        api_key: str | None = None,
        use_vertexai: bool = False,
        project: str | None = None,
        location: str = "global",
        client: Any | None = None,
    ) -> None:
        self._model = model
        self._temperature = temperature
        self._max_output_tokens = max_output_tokens
        self._min_chunk_tokens = min_chunk_tokens
        self._request_timeout_seconds = request_timeout_seconds
        self._api_key = api_key
        self._use_vertexai = use_vertexai
        self._project = project
        self._location = location
        self._client = client
        self._client_lock = threading.Lock()
        self._semaphore = asyncio.Semaphore(max_concurrency)

    @property
    def model(self) -> str:
        return self._model

    async def enrich(self, chunks: Sequence[Any]) -> list[EnrichmentResult | None]:
        tasks = [self._enrich_chunk(chunk) for chunk in chunks]
        return await asyncio.gather(*tasks)

    async def _enrich_chunk(self, chunk: Any) -> EnrichmentResult | None:
        token_count = getattr(chunk, "token_count", None)
        text_content = getattr(chunk, "text_content", None)
        if not isinstance(text_content, str) or not text_content.strip():
            logger.warning(
                "enrichment.chunk_missing_text_content",
                chunk_index=getattr(chunk, "chunk_index", None),
            )
            return None
        if token_count is None:
            token_count = _estimate_tokens(text_content)
        if token_count < self._min_chunk_tokens:
            return None

        async with self._semaphore:
            try:
                response = await asyncio.wait_for(
                    asyncio.to_thread(
                        self._generate_content,
                        text_content,
                    ),
                    timeout=self._request_timeout_seconds,
                )
                payload = self._parse_response(response)
                return _normalize_enrichment_result(payload)
            except asyncio.TimeoutError:
                logger.warning(
                    "enrichment.chunk_timeout",
                    chunk_index=getattr(chunk, "chunk_index", None),
                    exc_info=True,
                )
                return None
            except Exception:
                logger.warning(
                    "enrichment.chunk_failed",
                    chunk_index=getattr(chunk, "chunk_index", None),
                    exc_info=True,
                )
                return None

    @retry(
        retry=retry_if_exception(_is_retryable_enrichment_error),
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=8),
        reraise=True,
    )
    def _generate_content(self, text_content: str) -> Any:
        from google.genai import types

        return self._get_client().models.generate_content(
            model=self._model,
            contents=ENRICHMENT_PROMPT.format(text_content=text_content),
            config=types.GenerateContentConfig(
                temperature=self._temperature,
                max_output_tokens=self._max_output_tokens,
                response_mime_type="application/json",
                response_schema=EnrichmentSchema,
            ),
        )

    def _parse_response(self, response: Any) -> EnrichmentSchema:
        parsed = getattr(response, "parsed", None)
        if isinstance(parsed, EnrichmentSchema):
            return parsed
        if isinstance(parsed, dict):
            return EnrichmentSchema.model_validate(parsed)

        text = (getattr(response, "text", "") or "").strip()
        if not text:
            raise ValueError("Gemini enrichment returned empty response")
        return EnrichmentSchema.model_validate(json.loads(text))

    def _get_client(self) -> Any:
        if self._client is None:
            with self._client_lock:
                if self._client is None:
                    self._client = create_genai_client(
                        api_key=self._api_key,
                        use_vertexai=self._use_vertexai,
                        project=self._project,
                        location=self._location,
                    )
        return self._client


def build_enriched_text(
    *,
    text_content: str,
    summary: str,
    keywords: Sequence[str],
    questions: Sequence[str],
    max_tokens: int = 8192,
) -> str:
    if _estimate_tokens(text_content) >= max_tokens:
        return text_content

    summary_section = f"\n\nSummary: {summary.strip()}" if summary.strip() else ""
    keywords_text = ", ".join(keyword.strip() for keyword in keywords if keyword.strip())
    keywords_section = f"\nKeywords: {keywords_text}" if keywords_text else ""
    question_lines = [question.strip() for question in questions if question.strip()]
    questions_section = (
        "\nQuestions:\n" + "\n".join(f"- {question}" for question in question_lines)
        if question_lines
        else ""
    )

    full_text = text_content + summary_section + keywords_section + questions_section
    if _estimate_tokens(full_text) <= max_tokens:
        return full_text

    without_questions = text_content + summary_section + keywords_section
    if _estimate_tokens(without_questions) <= max_tokens:
        return without_questions

    without_keywords = text_content + summary_section
    if _estimate_tokens(without_keywords) <= max_tokens:
        return without_keywords

    if not summary_section:
        return text_content

    summary_prefix = text_content + "\n\nSummary: "
    if _estimate_tokens(summary_prefix) >= max_tokens:
        return text_content

    summary_body = summary.strip()
    low = 0
    high = len(summary_body)
    best_fit = ""
    while low <= high:
        mid = (low + high) // 2
        candidate = summary_body[:mid].rstrip()
        candidate_text = summary_prefix + candidate if candidate else text_content
        if _estimate_tokens(candidate_text) <= max_tokens:
            best_fit = candidate
            low = mid + 1
        else:
            high = mid - 1

    truncated_summary = best_fit
    if not truncated_summary:
        return text_content
    return text_content + f"\n\nSummary: {truncated_summary}"


def _estimate_tokens(text: str) -> int:
    if not text:
        return 0
    return max(1, -(-len(text) // CHARS_PER_TOKEN))
