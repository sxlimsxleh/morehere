"""OSM places layer: places.last_seen_at and the districts table.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-12
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geometry

revision = "0002"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("places", sa.Column("last_seen_at", sa.DateTime(timezone=True)))

    op.create_table(
        "districts",
        sa.Column("number", sa.Integer(), autoincrement=False, nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("osm_id", sa.Text(), nullable=False),
        sa.Column(
            "geom",
            Geometry(geometry_type="MULTIPOLYGON", srid=4326, spatial_index=False),
            nullable=False,
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.PrimaryKeyConstraint("number", name="pk_districts"),
        sa.UniqueConstraint("name", name="uq_districts_name"),
    )
    op.create_index("ix_districts_geom", "districts", ["geom"], postgresql_using="gist")


def downgrade() -> None:
    op.drop_table("districts")
    op.drop_column("places", "last_seen_at")
