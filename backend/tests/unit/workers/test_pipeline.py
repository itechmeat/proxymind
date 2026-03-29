from __future__ import annotations

import uuid
from types import SimpleNamespace

import pytest

from app.workers.tasks.pipeline import _require_parent_row


def _chunk(*, parent_id: uuid.UUID | None) -> SimpleNamespace:
    return SimpleNamespace(
        id=uuid.uuid7(),
        parent_id=parent_id,
        document_version_id=uuid.uuid7(),
    )


def test_require_parent_row_returns_none_for_flat_chunk() -> None:
    chunk = _chunk(parent_id=None)

    parent_row = _require_parent_row(chunk=chunk, parent_rows_by_id=None)

    assert parent_row is None


def test_require_parent_row_raises_clear_error_when_parent_rows_missing() -> None:
    parent_id = uuid.uuid7()
    chunk = _chunk(parent_id=parent_id)

    with pytest.raises(ValueError, match="no parent rows were provided"):
        _require_parent_row(chunk=chunk, parent_rows_by_id=None)


def test_require_parent_row_raises_clear_error_when_mapping_is_incomplete() -> None:
    parent_id = uuid.uuid7()
    chunk = _chunk(parent_id=parent_id)

    with pytest.raises(ValueError, match="Parent chunk metadata is missing"):
        _require_parent_row(chunk=chunk, parent_rows_by_id={})
