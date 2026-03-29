from __future__ import annotations

import asyncio
import re
from collections.abc import Awaitable, Callable
from typing import Any

import litellm
from tenacity import retry, retry_if_exception_type, stop_after_attempt, wait_exponential

JudgeCompletionCallable = Callable[..., Awaitable[Any]]
_JUDGE_RESPONSE_PATTERN = re.compile(
    r"^Score:\s*([1-5])\s*\nReasoning:\s*(.+)$",
    flags=re.DOTALL,
)


class JudgeRetryableError(RuntimeError):
    pass


class EmptyJudgeContentError(RuntimeError):
    pass


def parse_judge_response(response_text: str) -> tuple[int, str]:
    match = _JUDGE_RESPONSE_PATTERN.match(response_text.strip())
    if match is None:
        raise ValueError("Judge response did not match expected format")
    raw_score = int(match.group(1))
    reasoning = match.group(2).strip()
    if not reasoning:
        raise ValueError("Judge reasoning must not be empty")
    return raw_score, reasoning


def normalize(raw_score: int) -> float:
    if raw_score < 1 or raw_score > 5:
        raise ValueError("raw_score must be between 1 and 5")
    return (raw_score - 1) / 4


class EvalJudge:
    def __init__(
        self,
        *,
        model: str,
        api_key: str | None = None,
        base_url: str | None = None,
        temperature: float = 0.0,
        timeout_seconds: float = 30.0,
        completion_func: JudgeCompletionCallable | None = None,
    ) -> None:
        self._model = model
        self._api_key = api_key
        self._base_url = base_url
        self._temperature = temperature
        self._timeout_seconds = timeout_seconds
        self._completion_func = completion_func or litellm.acompletion

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=4),
        retry=retry_if_exception_type(JudgeRetryableError),
        reraise=True,
    )
    async def judge(self, prompt: str) -> str:
        try:
            response = await asyncio.wait_for(
                self._completion_func(
                    model=self._model,
                    messages=[
                        {
                            "role": "system",
                            "content": (
                                "You are an evaluation judge. Return ONLY the exact format "
                                '"Score: <1-5>\\nReasoning: <brief explanation>".'
                            ),
                        },
                        {"role": "user", "content": prompt},
                    ],
                    temperature=self._temperature,
                    api_key=self._api_key,
                    base_url=self._base_url,
                ),
                timeout=self._timeout_seconds,
            )
            choices = getattr(response, "choices", None)
            if not choices:
                raise JudgeRetryableError("Judge response is missing choices")
            message = getattr(choices[0], "message", None)
            content = getattr(message, "content", None)
        except (JudgeRetryableError, EmptyJudgeContentError):
            raise
        except Exception as error:
            raise JudgeRetryableError(f"Judge completion failed: {error}") from error

        if not isinstance(content, str) or not content.strip():
            raise EmptyJudgeContentError("Judge returned empty content")
        return content.strip()
