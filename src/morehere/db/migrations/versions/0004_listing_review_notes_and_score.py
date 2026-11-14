"""Listings: review notes for curators, and the Regular Score.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-13
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004"
down_revision = "0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "listings",
        sa.Column(
            "review_notes",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
    )
    op.add_column("listings", sa.Column("regular_score", postgresql.JSONB()))
    op.add_column("listings", sa.Column("score_total", sa.Float()))
    op.create_index("ix_listings_score_total", "listings", ["score_total"])


def downgrade() -> None:
    op.drop_index("ix_listings_score_total", table_name="listings")
    op.drop_column("listings", "score_total")
    op.drop_column("listings", "regular_score")
    op.drop_column("listings", "review_notes")
