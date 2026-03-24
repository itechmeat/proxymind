from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.llm import LLMService
from app.services.llm_types import LLMError, LLMResponse


class FakeCompletion:
    def __init__(self, responses: list[object]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def __call__(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _response(
    *,
    content: str | None,
    model: str = "openai/gpt-4o",
    prompt_tokens: int = 11,
    completion_tokens: int = 7,
) -> object:
    return SimpleNamespace(
        model=model,
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))],
        usage=SimpleNamespace(
            prompt_tokens=prompt_tokens,
            completion_tokens=completion_tokens,
        ),
    )


@pytest.mark.asyncio
async def test_complete_returns_content_and_usage() -> None:
    completion = FakeCompletion([_response(content="Answer")])
    service = LLMService(
        model="openai/gpt-4o",
        api_key="sk-test",
        api_base="https://api.example.com",
        temperature=0.7,
        completion_func=completion,
    )

    response = await service.complete([{"role": "user", "content": "Hi"}])

    assert response == LLMResponse(
        content="Answer",
        model_name="openai/gpt-4o",
        token_count_prompt=11,
        token_count_completion=7,
    )


@pytest.mark.asyncio
async def test_complete_passes_configured_parameters() -> None:
    completion = FakeCompletion([_response(content="Configured")])
    service = LLMService(
        model="openai/gpt-4o",
        api_key="sk-test",
        api_base="https://api.example.com",
        temperature=0.7,
        completion_func=completion,
    )

    await service.complete([{"role": "user", "content": "Hi"}], temperature=0.2)

    assert completion.calls == [
        {
            "model": "openai/gpt-4o",
            "messages": [{"role": "user", "content": "Hi"}],
            "temperature": 0.2,
            "api_key": "sk-test",
            "base_url": "https://api.example.com",
        }
    ]


@pytest.mark.asyncio
async def test_complete_raises_llm_error_on_provider_failure() -> None:
    completion = FakeCompletion([RuntimeError("boom")])
    service = LLMService(
        model="openai/gpt-4o",
        api_key=None,
        api_base=None,
        temperature=0.7,
        completion_func=completion,
    )

    with pytest.raises(LLMError, match="LLM completion failed"):
        await service.complete([{"role": "user", "content": "Hi"}])


@pytest.mark.asyncio
async def test_complete_raises_on_empty_content() -> None:
    completion = FakeCompletion([_response(content="  ")])
    service = LLMService(
        model="openai/gpt-4o",
        api_key=None,
        api_base=None,
        temperature=0.7,
        completion_func=completion,
    )

    with pytest.raises(LLMError, match="LLM returned empty content"):
        await service.complete([{"role": "user", "content": "Hi"}])


@pytest.mark.asyncio
async def test_complete_raises_llm_error_on_malformed_response() -> None:
    completion = FakeCompletion([SimpleNamespace(model="openai/gpt-4o", choices=[])])
    service = LLMService(
        model="openai/gpt-4o",
        api_key=None,
        api_base=None,
        temperature=0.7,
        completion_func=completion,
    )

    with pytest.raises(LLMError, match="LLM completion failed"):
        await service.complete([{"role": "user", "content": "Hi"}])
