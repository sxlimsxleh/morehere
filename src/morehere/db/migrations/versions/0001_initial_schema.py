"""Initial schema: extensions, source registry, raw records, places, listings, evidence.

Revision ID: 0001
Revises:
Create Date: 2026-11-12

Written by hand to mirror db/tables.py. tests/test_db.py checks that the two match
(Alembic autogenerate finds no difference), so they cannot drift apart silently.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from geoalchemy2 import Geography
from sqlalchemy.dialects import postgresql

revision = "0001"
down_revision = None
branch_labels = None
depends_on = None


def _timestamps(*, updated: bool = True) -> list[sa.Column]:
    cols = [
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        )
    ]
    if updated:
        cols.append(
            sa.Column(
                "updated_at",
                sa.DateTime(timezone=True),
                server_default=sa.func.now(),
                nullable=False,
            )
        )
    return cols


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS postgis")
    # Not used by any column yet; enabled now so the search milestone needs no superuser step.
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    op.create_table(
        "sources",
        sa.Column("source_id", sa.Text(), primary_key=True),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("legal_status", sa.Text(), nullable=False),
        sa.Column("licence", sa.Text()),
        sa.Column("attribution", sa.Text()),
        sa.Column("refresh_cron", sa.Text()),
        sa.Column("reliability", sa.Float(), nullable=False),
        *_timestamps(),
        sa.CheckConstraint(
            "reliability >= 0 AND reliability <= 1", name="ck_sources_reliability_range"
        ),
        sa.PrimaryKeyConstraint("source_id", name="pk_sources"),
    )

    op.create_table(
        "raw_records",
        sa.Column("raw_record_id", sa.Text(), primary_key=True),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("fetched_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("content_type", sa.Text(), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("payload", sa.Text(), nullable=False),
        *_timestamps(updated=False),
        sa.PrimaryKeyConstraint("raw_record_id", name="pk_raw_records"),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.source_id"], name="fk_raw_records_source_id_sources"
        ),
        sa.UniqueConstraint("source_id", "sha256", name="uq_raw_records_source_sha256"),
    )

    op.create_table(
        "places",
        sa.Column("place_id", sa.Text(), primary_key=True),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("address", sa.Text()),
        sa.Column("district", sa.Text()),
        sa.Column("geo", Geography(geometry_type="POINT", srid=4326, spatial_index=False)),
        sa.Column("osm_id", sa.Text()),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("osm_tags", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'")),
        *_timestamps(),
        sa.PrimaryKeyConstraint("place_id", name="pk_places"),
        sa.UniqueConstraint("osm_id", name="uq_places_osm_id"),
    )
    # GIST index: makes "within N metres of me" queries fast.
    op.create_index("ix_places_geo", "places", ["geo"], postgresql_using="gist")

    op.create_table(
        "evidence",
        sa.Column("evidence_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("raw_record_id", sa.Text(), nullable=False),
        sa.Column("source_text", sa.Text(), nullable=False),
        sa.Column("url", sa.Text()),
        sa.Column("captured_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("evidence_id", name="pk_evidence"),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.source_id"], name="fk_evidence_source_id_sources"
        ),
        sa.ForeignKeyConstraint(
            ["raw_record_id"],
            ["raw_records.raw_record_id"],
            name="fk_evidence_raw_record_id_raw_records",
        ),
        sa.CheckConstraint("length(source_text) > 0", name="ck_evidence_source_text_not_empty"),
    )

    op.create_table(
        "listings",
        sa.Column("listing_id", sa.Text(), primary_key=True),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("place_id", sa.Text(), nullable=False),
        sa.Column("category", sa.Text(), nullable=False),
        sa.Column("schedule", postgresql.JSONB()),
        sa.Column("language", sa.Text()),
        sa.Column("price_eur", sa.Numeric(8, 2)),
        sa.Column("price_period", sa.Text()),
        sa.Column("come_alone", sa.Boolean()),
        sa.Column("beginner_friendly", sa.Boolean()),
        sa.Column("group_size", sa.Text()),
        sa.Column("first_timer_info", sa.Text()),
        sa.Column("organiser_contact", sa.Text()),
        sa.Column("status", sa.Text(), nullable=False, server_default="draft"),
        sa.Column("last_verified_at", sa.DateTime(timezone=True)),
        *_timestamps(),
        sa.PrimaryKeyConstraint("listing_id", name="pk_listings"),
        sa.ForeignKeyConstraint(
            ["place_id"], ["places.place_id"], name="fk_listings_place_id_places"
        ),
        sa.CheckConstraint(
            "status IN ('draft', 'needs_review', 'published', 'hidden')",
            name="ck_listings_status_valid",
        ),
        sa.CheckConstraint(
            "price_eur IS NULL OR price_eur >= 0", name="ck_listings_price_not_negative"
        ),
        sa.CheckConstraint(
            "status <> 'published' OR (schedule IS NOT NULL AND last_verified_at IS NOT NULL)",
            name="ck_listings_published_needs_schedule_and_verification",
        ),
    )
    op.create_index("ix_listings_status", "listings", ["status"])
    op.create_index("ix_listings_place_id", "listings", ["place_id"])

    op.create_table(
        "listing_field_evidence",
        sa.Column("listing_id", sa.Text(), nullable=False),
        sa.Column("field", sa.Text(), nullable=False),
        sa.Column("evidence_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("listing_id", "field", name="pk_listing_field_evidence"),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.listing_id"],
            ondelete="CASCADE",
            name="fk_listing_field_evidence_listing_id_listings",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"],
            ["evidence.evidence_id"],
            name="fk_listing_field_evidence_evidence_id_evidence",
        ),
    )

    op.create_table(
        "tags",
        sa.Column("tag_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("listing_id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        # NOT NULL: no evidence, no tag (rule 3), enforced by the database too.
        sa.Column("evidence_id", sa.BigInteger(), nullable=False),
        sa.PrimaryKeyConstraint("tag_id", name="pk_tags"),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.listing_id"],
            ondelete="CASCADE",
            name="fk_tags_listing_id_listings",
        ),
        sa.ForeignKeyConstraint(
            ["evidence_id"], ["evidence.evidence_id"], name="fk_tags_evidence_id_evidence"
        ),
        sa.UniqueConstraint("listing_id", "name", name="uq_tags_listing_name"),
    )

    op.create_table(
        "listing_sources",
        sa.Column("listing_id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("listing_id", "source_id", name="pk_listing_sources"),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.listing_id"],
            ondelete="CASCADE",
            name="fk_listing_sources_listing_id_listings",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.source_id"], name="fk_listing_sources_source_id_sources"
        ),
    )

    op.create_table(
        "listing_drafts",
        sa.Column("draft_id", sa.BigInteger(), sa.Identity(), primary_key=True),
        sa.Column("raw_record_id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("extracted_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("draft", postgresql.JSONB(), nullable=False),
        sa.Column(
            "flags",
            postgresql.ARRAY(sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("review_status", sa.Text(), nullable=False, server_default="pending"),
        sa.Column("listing_id", sa.Text()),
        *_timestamps(updated=False),
        sa.PrimaryKeyConstraint("draft_id", name="pk_listing_drafts"),
        sa.ForeignKeyConstraint(
            ["raw_record_id"],
            ["raw_records.raw_record_id"],
            name="fk_listing_drafts_raw_record_id_raw_records",
        ),
        sa.ForeignKeyConstraint(
            ["source_id"], ["sources.source_id"], name="fk_listing_drafts_source_id_sources"
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.listing_id"],
            ondelete="SET NULL",
            name="fk_listing_drafts_listing_id_listings",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected')",
            name="ck_listing_drafts_review_status_valid",
        ),
    )
    op.create_index("ix_listing_drafts_review_status", "listing_drafts", ["review_status"])


def downgrade() -> None:
    for table in (
        "listing_drafts",
        "listing_sources",
        "tags",
        "listing_field_evidence",
        "listings",
        "evidence",
        "places",
        "raw_records",
        "sources",
    ):
        op.drop_table(table)
    # Extensions stay: other databases objects may use them, and dropping postgis
    # would need superuser rights in hosted Postgres.
