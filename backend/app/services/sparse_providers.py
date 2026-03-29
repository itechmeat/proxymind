from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol

import httpx
from qdrant_client import models

if TYPE_CHECKING:
    from app.core.config import Settings


@dataclass(frozen=True, slots=True)
class SparseProviderMetadata:
    backend: str
    model_name: str
    contract_version: str


SparseRepresentation = models.Document | models.SparseVector


class SparseProvider(Protocol):
    metadata: SparseProviderMetadata

    async def build_document_representation(self, text: str) -> SparseRepresentation: ...

    async def build_query_representation(self, text: str) -> SparseRepresentation: ...

    async def aclose(self) -> None: ...


class Bm25SparseProvider:
    def __init__(self, *, language: str) -> None:
        self.metadata = SparseProviderMetadata(
            backend="bm25",
            model_name="Qdrant/bm25",
            contract_version="v1",
        )
        self._language = language

    async def build_document_representation(self, text: str) -> models.Document:
        return models.Document(
            text=text,
            model=self.metadata.model_name,
            options=models.Bm25Config(language=self._language),
        )

    async def build_query_representation(self, text: str) -> models.Document:
        return await self.build_document_representation(text)

    async def aclose(self) -> None:
        return None


class ExternalBgeM3SparseProvider:
    def __init__(
        self,
        *,
        base_url: str,
        model_name: str = "bge-m3",
        timeout_seconds: float = 10.0,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        resolved_base_url = base_url.rstrip("/")
        if not resolved_base_url:
            raise ValueError("ExternalBgeM3SparseProvider base_url must not be empty")

        self.metadata = SparseProviderMetadata(
            backend="bge_m3",
            model_name=model_name,
            contract_version="v1",
        )
        self._base_url = resolved_base_url
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            base_url=self._base_url,
            timeout=timeout_seconds,
        )

    async def build_document_representation(self, text: str) -> models.SparseVector:
        return await self._build_sparse_vector("/sparse/documents", text)

    async def build_query_representation(self, text: str) -> models.SparseVector:
        return await self._build_sparse_vector("/sparse/queries", text)

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _build_sparse_vector(self, path: str, text: str) -> models.SparseVector:
        request_url = path if self._owns_client else f"{self._base_url}{path}"
        response = await self._client.post(request_url, json={"text": text})
        response.raise_for_status()
        payload = response.json()
        indices = payload.get("indices")
        values = payload.get("values")
        if not isinstance(indices, list) or not isinstance(values, list):
            raise ValueError("Sparse provider response must contain list fields 'indices' and 'values'")
        if len(indices) != len(values):
            raise ValueError("Sparse provider response indices and values must have the same length")
        try:
            normalized_indices = [int(index) for index in indices]
            normalized_values = [float(value) for value in values]
        except (TypeError, ValueError) as error:
            raise ValueError(
                "Sparse provider response 'indices' and 'values' must contain numeric items"
            ) from error
        return models.SparseVector(indices=normalized_indices, values=normalized_values)


def sparse_backend_change_requires_reindex(
    current: SparseProviderMetadata,
    target: SparseProviderMetadata,
) -> bool:
    return (
        current.backend != target.backend
        or current.model_name != target.model_name
        or current.contract_version != target.contract_version
    )


def build_sparse_provider(settings: Settings) -> SparseProvider:
    if settings.sparse_backend == "bm25":
        return Bm25SparseProvider(language=settings.bm25_language)
    if settings.bge_m3_provider_url is None:
        raise ValueError("BGE_M3_PROVIDER_URL is required when SPARSE_BACKEND=bge_m3")
    return ExternalBgeM3SparseProvider(
        base_url=settings.bge_m3_provider_url,
        model_name=settings.bge_m3_model_name,
        timeout_seconds=settings.bge_m3_timeout_seconds,
    )
