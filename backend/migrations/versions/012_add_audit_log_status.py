"""add audit log status

Revision ID: 012
Revises: 011
Create Date: 2026-03-28 00:00:00.000000
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "012"
down_revision: str | None = "011"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "audit_logs",
        sa.Column(
            "status",
            sa.String(length=32),
            nullable=True,
            server_default="complete",
        ),
    )
    op.execute("UPDATE audit_logs SET status = 'complete' WHERE status IS NULL")
    op.alter_column("audit_logs", "status", nullable=False, server_default=None)


def downgrade() -> None:
    op.drop_column("audit_logs", "status")
