from __future__ import annotations

from dataclasses import dataclass


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
