from __future__ import annotations

from sqlalchemy.dialects import postgresql

from app.core.constants import DEFAULT_AGENT_ID, DEFAULT_KNOWLEDGE_BASE_ID
from app.services.snapshot import SnapshotService


def test_build_create_draft_statement_uses_literal_partial_index_predicate() -> None:
    service = SnapshotService()

    statement = service._build_create_draft_statement(
        agent_id=DEFAULT_AGENT_ID,
        knowledge_base_id=DEFAULT_KNOWLEDGE_BASE_ID,
    )
    compiled = str(statement.compile(dialect=postgresql.dialect()))

    assert "ON CONFLICT (agent_id, knowledge_base_id) WHERE status = 'draft' DO NOTHING" in compiled
    assert "WHERE status = %(status_" not in compiled
