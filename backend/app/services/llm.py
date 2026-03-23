from __future__ import annotations

from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Any

import litellm
import structlog

ChatMessage = dict[str, str]
CompletionCallable = Callable[..., Awaitable[Any]]


class LLMError(RuntimeError):
    pass


@dataclass(slots=True, frozen=True)
class LLMResponse:
    content: str
    model_name: str | None
    token_count_prompt: int | None
    token_count_completion: int | None


@dataclass(slots=True, frozen=True)
class LLMToken:
    content: str


@dataclass(slots=True, frozen=True)
class LLMStreamEnd:
    model_name: str | None
    token_count_prompt: int | None
    token_count_completion: int | None


LLMStreamEvent = LLMToken | LLMStreamEnd


class LLMService:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None,
        api_base: str | None,
        temperature: float,
        completion_func: CompletionCallable | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._api_base = api_base
        self._temperature = temperature
        self._completion_func = completion_func or litellm.acompletion
        self._logger = structlog.get_logger(__name__)

    async def complete(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
    ) -> LLMResponse:
        try:
            response = await self._completion_func(
                model=self._model,
                messages=messages,
                temperature=self._temperature if temperature is None else temperature,
                api_key=self._api_key,
                base_url=self._api_base,
            )
            choices = getattr(response, "choices", None)
            if not choices:
                raise ValueError("LLM response is missing choices")

            first_choice = choices[0]
            message = getattr(first_choice, "message", None)
            content = getattr(message, "content", None)
        except Exception as error:
            self._logger.error("llm.completion_failed", model=self._model, error=str(error))
            raise LLMError("LLM completion failed") from error

        if not isinstance(content, str) or not content.strip():
            self._logger.error("llm.empty_content", model=self._model)
            raise LLMError("LLM returned empty content")

        usage = getattr(response, "usage", None)
        return LLMResponse(
            content=content.strip(),
            model_name=getattr(response, "model", None),
            token_count_prompt=getattr(usage, "prompt_tokens", None),
            token_count_completion=getattr(usage, "completion_tokens", None),
        )

    async def stream(
        self,
        messages: list[ChatMessage],
        *,
        temperature: float | None = None,
    ) -> AsyncIterator[LLMStreamEvent]:
        try:
            response = await self._completion_func(
                model=self._model,
                messages=messages,
                temperature=self._temperature if temperature is None else temperature,
                api_key=self._api_key,
                base_url=self._api_base,
                stream=True,
                stream_options={"include_usage": True},
            )
        except Exception as error:
            self._logger.error("llm.stream_init_failed", model=self._model, error=str(error))
            raise LLMError("LLM streaming failed") from error

        model_name: str | None = None
        token_count_prompt: int | None = None
        token_count_completion: int | None = None
        emitted_token = False

        try:
            async for chunk in response:
                choices = getattr(chunk, "choices", None)
                delta = getattr(choices[0], "delta", None) if choices else None
                delta_content = getattr(delta, "content", None)
                if isinstance(delta_content, str) and delta_content:
                    emitted_token = True
                    yield LLMToken(content=delta_content)

                usage = getattr(chunk, "usage", None)
                if usage is not None:
                    token_count_prompt = getattr(usage, "prompt_tokens", None)
                    token_count_completion = getattr(usage, "completion_tokens", None)

                chunk_model = getattr(chunk, "model", None)
                if chunk_model is not None:
                    model_name = chunk_model
        except Exception as error:
            self._logger.error("llm.stream_read_failed", model=self._model, error=str(error))
            raise LLMError("LLM streaming failed") from error

        if not emitted_token:
            self._logger.error("llm.empty_content", model=self._model)
            raise LLMError("LLM returned empty content")

        yield LLMStreamEnd(
            model_name=model_name,
            token_count_prompt=token_count_prompt,
            token_count_completion=token_count_completion,
        )
