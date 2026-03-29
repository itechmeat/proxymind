from __future__ import annotations

import uuid
from typing import TYPE_CHECKING

from evals.models import GenerationResult, RetrievalResult, ReturnedChunk

if TYPE_CHECKING:
    import httpx

    from evals.config import EvalConfig


class EvalClientError(RuntimeError):
    pass


class EvalClient:
    def __init__(self, *, config: EvalConfig, http_client: httpx.AsyncClient) -> None:
        self._config = config
        self._http = http_client

    async def retrieve(
        self,
        query: str,
        *,
        snapshot_id: uuid.UUID,
        top_n: int,
    ) -> RetrievalResult:
        url = f"{self._config.base_url}/api/admin/eval/retrieve"
        headers = {"Authorization": f"Bearer {self._config.admin_key}"}
        payload = {
            "query": query,
            "snapshot_id": str(snapshot_id),
            "top_n": top_n,
        }

        try:
            response = await self._http.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return RetrievalResult(
                chunks=[ReturnedChunk(**chunk) for chunk in data["chunks"]],
                timing_ms=data["timing_ms"],
            )
        except Exception as error:
            raise EvalClientError(f"Eval API request failed: {error}") from error

    async def generate(
        self,
        query: str,
        *,
        snapshot_id: uuid.UUID,
    ) -> GenerationResult:
        url = f"{self._config.base_url}/api/admin/eval/generate"
        headers = {"Authorization": f"Bearer {self._config.admin_key}"}
        payload = {
            "query": query,
            "snapshot_id": str(snapshot_id),
        }

        try:
            response = await self._http.post(url, json=payload, headers=headers)
            response.raise_for_status()
            data = response.json()
            return GenerationResult(
                answer=data["answer"],
                citations=data.get("citations", []),
                retrieved_chunks=[
                    ReturnedChunk(**chunk) for chunk in data.get("retrieved_chunks", [])
                ],
                rewritten_query=data.get("rewritten_query", query),
                timing_ms=data.get("timing_ms", 0.0),
                model=data.get("model", "unknown"),
            )
        except Exception as error:
            raise EvalClientError(f"Eval generate request failed: {error}") from error
