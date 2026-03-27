"""add_catalog_sku_and_message_products

Revision ID: 011
Revises: 010
Create Date: 2026-03-27 12:00:00.000000

"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

# revision identifiers, used by Alembic.
revision: str = "011"
down_revision: str | Sequence[str] | None = "010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "catalog_items",
        sa.Column("sku", sa.String(length=64), nullable=True),
    )
    op.execute("UPDATE catalog_items SET sku = 'LEGACY-' || id::text WHERE sku IS NULL")
    op.alter_column("catalog_items", "sku", existing_type=sa.String(length=64), nullable=False)
    op.create_index("ix_catalog_items_sku", "catalog_items", ["sku"])
    op.create_unique_constraint(
        "uq_catalog_items_agent_id_sku",
        "catalog_items",
        ["agent_id", "sku"],
    )

    op.add_column(
        "messages",
        sa.Column("products", sa.dialects.postgresql.JSONB(astext_type=sa.Text()), nullable=True),
    )

    op.drop_constraint("sources_catalog_item_id_fkey", "sources", type_="foreignkey")
    op.create_foreign_key(
        "fk_sources_catalog_item_id_catalog_items",
        "sources",
        "catalog_items",
        ["catalog_item_id"],
        ["id"],
        ondelete="SET NULL",
    )


def downgrade() -> None:
    op.drop_constraint("fk_sources_catalog_item_id_catalog_items", "sources", type_="foreignkey")
    op.create_foreign_key(
        "sources_catalog_item_id_fkey",
        "sources",
        "catalog_items",
        ["catalog_item_id"],
        ["id"],
    )

    op.drop_column("messages", "products")

    op.drop_constraint("uq_catalog_items_agent_id_sku", "catalog_items", type_="unique")
    op.drop_index("ix_catalog_items_sku", table_name="catalog_items")
    op.drop_column("catalog_items", "sku")
