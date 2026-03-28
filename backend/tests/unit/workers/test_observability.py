from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from app.workers.observability import update_queue_depth


@pytest.mark.asyncio
async def test_update_queue_depth_uses_sorted_set_cardinality(monkeypatch) -> None:
    redis_client = AsyncMock()
    redis_client.zcard.return_value = 7

    observed: list[int] = []
    monkeypatch.setattr(
        "app.workers.observability.ARQ_QUEUE_DEPTH.set",
        lambda value: observed.append(value),
    )

    await update_queue_depth(redis_client)

    redis_client.zcard.assert_awaited_once_with("arq:queue")
    redis_client.llen.assert_not_called()
    assert observed == [7]
