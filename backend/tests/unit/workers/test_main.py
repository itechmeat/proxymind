from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.workers import main


@pytest.mark.asyncio
async def test_on_shutdown_disposes_engine_even_if_qdrant_close_fails() -> None:
    engine = SimpleNamespace(dispose=AsyncMock())
    qdrant_service = SimpleNamespace(close=AsyncMock(side_effect=RuntimeError("boom")))

    await main.on_shutdown({"db_engine": engine, "qdrant_service": qdrant_service})

    qdrant_service.close.assert_awaited_once()
    engine.dispose.assert_awaited_once()
