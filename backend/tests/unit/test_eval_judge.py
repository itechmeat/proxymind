from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from evals.judge import EvalJudge, normalize, parse_judge_response


def test_parse_judge_response_success() -> None:
    raw_score, reasoning = parse_judge_response("Score: 4\nReasoning: Well supported")

    assert raw_score == 4
    assert reasoning == "Well supported"


def test_parse_judge_response_invalid_format() -> None:
    with pytest.raises(ValueError):
        parse_judge_response("I think it is 4/5")


def test_normalize() -> None:
    assert normalize(5) == 1.0
    assert normalize(3) == 0.5
    assert normalize(1) == 0.0


@pytest.mark.asyncio
async def test_eval_judge_calls_completion() -> None:
    completion = AsyncMock(
        return_value=SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content="Score: 5\nReasoning: Great"))]
        )
    )
    judge = EvalJudge(model="openai/gpt-4o", completion_func=completion)

    response = await judge.judge("Evaluate this")

    assert response == "Score: 5\nReasoning: Great"
    completion.assert_awaited_once()
