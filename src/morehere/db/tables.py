"""SQLAlchemy table definitions.

These are storage shapes only. The rest of the app works with the Pydantic models in
`morehere.models`; `db/repo.py` converts between the two.

Choices worth knowing:
- Vocabularies (source kind, category, ...) are plain text, validated by Pydantic. Adding
  a category then needs no migration. Status columns, which code branches on, get CHECKs.
- `tags.evidence_id` is NOT NULL: "no evidence, no tag" holds even for raw SQL.
- `listings.schedule` is JSONB holding a `Schedule`; recurrence is expanded in Python.
- All timestamps are timestamptz, stored in UTC.
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from typing import Any

from geoalchemy2 import Geography
from sqlalchemy import (
    BigInteger,
    Boolean,
    CheckConstraint,
    DateTime,
    Float,
    ForeignKey,
    Identity,
    Index,
    MetaData,
    Numeric,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column

# Predictable constraint names, so migrations can refer to (and drop) them by name.
NAMING_CONVENTION = {
    "ix": "ix_%(column_0_label)s",
    "uq": "uq_%(table_name)s_%(column_0_name)s",
    "ck": "ck_%(table_name)s_%(constraint_name)s",
    "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
    "pk": "pk_%(table_name)s",
}


class Base(DeclarativeBase):
    metadata = MetaData(naming_convention=NAMING_CONVENTION)


def _created_at() -> Mapped[datetime]:
    return mapped_column(DateTime(timezone=True), server_default=func.now(), nullable=False)


def _updated_at() -> Mapped[datetime]:
    return mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class SourceRow(Base):
    __tablename__ = "sources"

    source_id: Mapped[str] = mapped_column(Text, primary_key=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    legal_status: Mapped[str] = mapped_column(Text, nullable=False)
    licence: Mapped[str | None] = mapped_column(Text)
    attribution: Mapped[str | None] = mapped_column(Text)
    refresh_cron: Mapped[str | None] = mapped_column(Text)
    reliability: Mapped[float] = mapped_column(Float, nullable=False)
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    __table_args__ = (
        CheckConstraint("reliability >= 0 AND reliability <= 1", name="reliability_range"),
    )


class RawRecordRow(Base):
    __tablename__ = "raw_records"

    raw_record_id: Mapped[str] = mapped_column(Text, primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.source_id"), nullable=False)
    fetched_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    sha256: Mapped[str] = mapped_column(String(64), nullable=False)
    content_type: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[datetime] = _created_at()

    # Fetching identical content from the same source again stores nothing new.
    __table_args__ = (UniqueConstraint("source_id", "sha256", name="uq_raw_records_source_sha256"),)


class PlaceRow(Base):
    __tablename__ = "places"

    place_id: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    address: Mapped[str | None] = mapped_column(Text)
    district: Mapped[str | None] = mapped_column(Text)
    # geography (not geometry): distances come back in metres without projecting.
    # The GIST index is declared explicitly below, so geoalchemy2 must not add its own.
    # Nullable: a tip can name a place before we know its coordinates.
    geo: Mapped[Any] = mapped_column(
        Geography(geometry_type="POINT", srid=4326, spatial_index=False), nullable=True
    )
    osm_id: Mapped[str | None] = mapped_column(Text, unique=True)
    kind: Mapped[str] = mapped_column(Text, nullable=False)
    osm_tags: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False, server_default="{}")
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    __table_args__ = (Index("ix_places_geo", "geo", postgresql_using="gist"),)


class EvidenceRow(Base):
    __tablename__ = "evidence"

    evidence_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.source_id"), nullable=False)
    raw_record_id: Mapped[str] = mapped_column(
        ForeignKey("raw_records.raw_record_id"), nullable=False
    )
    source_text: Mapped[str] = mapped_column(Text, nullable=False)
    url: Mapped[str | None] = mapped_column(Text)
    captured_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    __table_args__ = (CheckConstraint("length(source_text) > 0", name="source_text_not_empty"),)


class ListingRow(Base):
    __tablename__ = "listings"

    listing_id: Mapped[str] = mapped_column(Text, primary_key=True)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    place_id: Mapped[str] = mapped_column(ForeignKey("places.place_id"), nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    # none_as_null: store Python None as SQL NULL, not JSON 'null'. Without it,
    # "schedule IS NOT NULL" is true for a missing schedule and the CHECK below is useless.
    schedule: Mapped[dict[str, Any] | None] = mapped_column(JSONB(none_as_null=True))
    language: Mapped[str | None] = mapped_column(Text)
    price_eur: Mapped[Decimal | None] = mapped_column(Numeric(8, 2))
    price_period: Mapped[str | None] = mapped_column(Text)
    come_alone: Mapped[bool | None] = mapped_column(Boolean)
    beginner_friendly: Mapped[bool | None] = mapped_column(Boolean)
    group_size: Mapped[str | None] = mapped_column(Text)
    first_timer_info: Mapped[str | None] = mapped_column(Text)
    organiser_contact: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    last_verified_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = _created_at()
    updated_at: Mapped[datetime] = _updated_at()

    __table_args__ = (
        CheckConstraint(
            "status IN ('draft', 'needs_review', 'published', 'hidden')", name="status_valid"
        ),
        CheckConstraint("price_eur IS NULL OR price_eur >= 0", name="price_not_negative"),
        # Second line of defence behind the Pydantic validator.
        CheckConstraint(
            "status <> 'published' OR (schedule IS NOT NULL AND last_verified_at IS NOT NULL)",
            name="published_needs_schedule_and_verification",
        ),
        Index("ix_listings_status", "status"),
        Index("ix_listings_place_id", "place_id"),
    )


class ListingFieldEvidenceRow(Base):
    """Which evidence a listing field was accepted on, e.g. ('come_alone', evidence 42)."""

    __tablename__ = "listing_field_evidence"

    listing_id: Mapped[str] = mapped_column(
        ForeignKey("listings.listing_id", ondelete="CASCADE"), primary_key=True
    )
    field: Mapped[str] = mapped_column(Text, primary_key=True)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.evidence_id"), nullable=False)


class TagRow(Base):
    __tablename__ = "tags"

    tag_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    listing_id: Mapped[str] = mapped_column(
        ForeignKey("listings.listing_id", ondelete="CASCADE"), nullable=False
    )
    name: Mapped[str] = mapped_column(Text, nullable=False)
    evidence_id: Mapped[int] = mapped_column(ForeignKey("evidence.evidence_id"), nullable=False)

    __table_args__ = (UniqueConstraint("listing_id", "name", name="uq_tags_listing_name"),)


class ListingSourceRow(Base):
    __tablename__ = "listing_sources"

    listing_id: Mapped[str] = mapped_column(
        ForeignKey("listings.listing_id", ondelete="CASCADE"), primary_key=True
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.source_id"), primary_key=True)


class ListingDraftRow(Base):
    """Extraction output waiting for (or past) curator review."""

    __tablename__ = "listing_drafts"

    draft_id: Mapped[int] = mapped_column(BigInteger, Identity(), primary_key=True)
    raw_record_id: Mapped[str] = mapped_column(
        ForeignKey("raw_records.raw_record_id"), nullable=False
    )
    source_id: Mapped[str] = mapped_column(ForeignKey("sources.source_id"), nullable=False)
    extracted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    draft: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)  # a ListingDraft
    flags: Mapped[list[str]] = mapped_column(ARRAY(Text), nullable=False, server_default="{}")
    review_status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    # The listing this draft was accepted into or merged with, once reviewed.
    listing_id: Mapped[str | None] = mapped_column(
        ForeignKey("listings.listing_id", ondelete="SET NULL")
    )
    created_at: Mapped[datetime] = _created_at()

    __table_args__ = (
        CheckConstraint(
            "review_status IN ('pending', 'accepted', 'rejected')", name="review_status_valid"
        ),
        Index("ix_listing_drafts_review_status", "review_status"),
    )
