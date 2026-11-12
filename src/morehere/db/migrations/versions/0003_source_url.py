"""sources.url: one registry entry per feed we pull from.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0003"
down_revision = "0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("sources", sa.Column("url", sa.Text()))


def downgrade() -> None:
    op.drop_column("sources", "url")
