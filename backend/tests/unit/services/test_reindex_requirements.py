from __future__ import annotations

from app.services.sparse_providers import (
    SparseProviderMetadata,
    sparse_backend_change_requires_reindex,
)


def test_sparse_backend_change_requires_reindex() -> None:
    current = SparseProviderMetadata(
        backend="bm25",
        model_name="Qdrant/bm25",
        contract_version="v1",
    )
    target = SparseProviderMetadata(
        backend="bge_m3",
        model_name="bge-m3",
        contract_version="v1",
    )

    assert sparse_backend_change_requires_reindex(current, target) is True


def test_same_sparse_backend_contract_does_not_require_reindex() -> None:
    current = SparseProviderMetadata(
        backend="bm25",
        model_name="Qdrant/bm25",
        contract_version="v1",
    )
    target = SparseProviderMetadata(
        backend="bm25",
        model_name="Qdrant/bm25",
        contract_version="v1",
    )

    assert sparse_backend_change_requires_reindex(current, target) is False
