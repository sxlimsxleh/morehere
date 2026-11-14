"""Audit log of curator decisions.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-14
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005"
down_revision = "0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "curator_actions",
        sa.Column("action_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("curator", sa.Text(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("listing_id", sa.Text()),
        sa.Column("details", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        sa.PrimaryKeyConstraint("action_id", name="pk_curator_actions"),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.listing_id"],
            ondelete="SET NULL",
            name="fk_curator_actions_listing_id_listings",
        ),
    )
    op.create_index("ix_curator_actions_listing_id", "curator_actions", ["listing_id"])


def downgrade() -> None:
    op.drop_table("curator_actions")
