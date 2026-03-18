"""seed_default_agent

Revision ID: 002
Revises: 001
Create Date: 2026-03-18 11:10:06.746564

"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "002"
down_revision: str | Sequence[str] | None = "001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

DEFAULT_AGENT_ID = "00000000-0000-0000-0000-000000000001"
DEFAULT_KNOWLEDGE_BASE_ID = "00000000-0000-0000-0000-000000000002"


def upgrade() -> None:
    """Upgrade schema."""
    agent_table = sa.table(
        "agents",
        sa.column("id", sa.UUID()),
        sa.column("owner_id", sa.UUID()),
        sa.column("name", sa.String()),
        sa.column("description", sa.Text()),
        sa.column("avatar_url", sa.String()),
        sa.column("active_snapshot_id", sa.UUID()),
        sa.column("default_knowledge_base_id", sa.UUID()),
        sa.column("language", sa.String()),
        sa.column("timezone", sa.String()),
    )
    op.bulk_insert(
        agent_table,
        [
            {
                "id": uuid.UUID(DEFAULT_AGENT_ID),
                "owner_id": None,
                "name": "Default Agent",
                "description": "Bootstrap agent seeded by Alembic migration.",
                "avatar_url": None,
                "active_snapshot_id": None,
                "default_knowledge_base_id": uuid.UUID(DEFAULT_KNOWLEDGE_BASE_ID),
                "language": "en",
                "timezone": None,
            }
        ],
    )


def downgrade() -> None:
    """Downgrade schema."""
    op.get_bind().execute(
        sa.text("DELETE FROM agents WHERE id = :agent_id"),
        {"agent_id": uuid.UUID(DEFAULT_AGENT_ID)},
    )
