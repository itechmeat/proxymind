from __future__ import annotations

from types import SimpleNamespace

import pytest

from app.services.llm import LLMService
from app.services.llm_types import LLMError, LLMStreamEnd, LLMToken


class FakeStreamChunk:
    def __init__(
        self,
        content: str | None = None,
        *,
        usage: object | None = None,
        model: str | None = None,
    ) -> None:
        self.choices = [SimpleNamespace(delta=SimpleNamespace(content=content))]
        self.usage = usage
        self.model = model


class FakeStreamResponse:
    def __init__(self, chunks: list[FakeStreamChunk]) -> None:
        self._chunks = list(chunks)

    def __aiter__(self):
        return self

    async def __anext__(self):
        if not self._chunks:
            raise StopAsyncIteration
        return self._chunks.pop(0)


class FakeStreamingCompletion:
    def __init__(self, responses: list[FakeStreamResponse | Exception]) -> None:
        self._responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def __call__(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = self._responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def _make_service(completion: FakeStreamingCompletion) -> LLMService:
    return LLMService(
        model="openai/gpt-4o",
        api_key="sk-test",
        api_base=None,
        temperature=0.7,
        completion_func=completion,
    )


@pytest.mark.asyncio
async def test_stream_yields_tokens_and_end() -> None:
    completion = FakeStreamingCompletion(
        [
            FakeStreamResponse(
                [
                    FakeStreamChunk(content="Hello"),
                    FakeStreamChunk(content=" world"),
                    FakeStreamChunk(
                        content=None,
                        usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5),
                        model="openai/gpt-4o",
                    ),
                ]
            )
        ]
    )
    service = _make_service(completion)

    events = [event async for event in service.stream([{"role": "user", "content": "Hi"}])]

    assert events == [
        LLMToken(content="Hello"),
        LLMToken(content=" world"),
        LLMStreamEnd(
            model_name="openai/gpt-4o",
            token_count_prompt=10,
            token_count_completion=5,
        ),
    ]


@pytest.mark.asyncio
async def test_stream_passes_stream_options() -> None:
    completion = FakeStreamingCompletion([FakeStreamResponse([FakeStreamChunk(content="ok")])])
    service = _make_service(completion)

    _ = [event async for event in service.stream([{"role": "user", "content": "Hi"}])]

    assert completion.calls[0]["stream"] is True
    assert completion.calls[0]["stream_options"] == {"include_usage": True}


@pytest.mark.asyncio
async def test_stream_skips_empty_chunks() -> None:
    completion = FakeStreamingCompletion(
        [
            FakeStreamResponse(
                [
                    FakeStreamChunk(content=None),
                    FakeStreamChunk(content=""),
                    FakeStreamChunk(content="token"),
                ]
            )
        ]
    )
    service = _make_service(completion)

    events = [event async for event in service.stream([{"role": "user", "content": "Hi"}])]

    assert [event for event in events if isinstance(event, LLMToken)] == [LLMToken(content="token")]


@pytest.mark.asyncio
async def test_stream_raises_llm_error_on_provider_failure() -> None:
    completion = FakeStreamingCompletion([RuntimeError("provider down")])
    service = _make_service(completion)

    with pytest.raises(LLMError, match="LLM streaming failed"):
        _ = [event async for event in service.stream([{"role": "user", "content": "Hi"}])]


@pytest.mark.asyncio
async def test_stream_yields_end_without_usage() -> None:
    completion = FakeStreamingCompletion([FakeStreamResponse([FakeStreamChunk(content="answer")])])
    service = _make_service(completion)

    events = [event async for event in service.stream([{"role": "user", "content": "Hi"}])]

    end_events = [event for event in events if isinstance(event, LLMStreamEnd)]
    assert len(end_events) == 1
    assert end_events[0].token_count_prompt is None
    assert end_events[0].token_count_completion is None


@pytest.mark.asyncio
async def test_stream_raises_on_empty_stream() -> None:
    completion = FakeStreamingCompletion(
        [
            FakeStreamResponse(
                [
                    FakeStreamChunk(
                        content=None,
                        usage=SimpleNamespace(prompt_tokens=1, completion_tokens=0),
                        model="openai/gpt-4o",
                    )
                ]
            )
        ]
    )
    service = _make_service(completion)

    with pytest.raises(LLMError, match="LLM returned empty content"):
        _ = [event async for event in service.stream([{"role": "user", "content": "Hi"}])]
