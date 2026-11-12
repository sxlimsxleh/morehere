"""Repository: the only place that converts between Pydantic models and table rows.

Everything outside `morehere.db` passes Pydantic objects in and gets Pydantic objects
back, so validation rules (grounded or flagged, no evidence no tag, publishable) always
run on the way in and on the way out.

Naive datetimes are treated as UTC before they are stored in timestamptz columns.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

from geoalchemy2 import Geometry
from sqlalchemy import cast, delete, func, select, update
from sqlalchemy.dialects.postgresql import array, insert
from sqlalchemy.orm import Session

from morehere.db.tables import (
    DistrictRow,
    EvidenceRow,
    ListingDraftRow,
    ListingFieldEvidenceRow,
    ListingRow,
    ListingSourceRow,
    PlaceRow,
    RawRecordRow,
    SourceRow,
    TagRow,
)
from morehere.models import (
    Evidence,
    GeoPoint,
    Listing,
    ListingDraft,
    Place,
    RawRecord,
    Schedule,
    Source,
    Tag,
)


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value


# ---------------------------------------------------------------------------
# Sources
# ---------------------------------------------------------------------------


def upsert_source(session: Session, source: Source) -> None:
    values = source.model_dump()
    stmt = insert(SourceRow).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[SourceRow.source_id],
        set_={k: stmt.excluded[k] for k in values if k != "source_id"} | {"updated_at": func.now()},
    )
    session.execute(stmt)


def get_source(session: Session, source_id: str) -> Source | None:
    row = session.get(SourceRow, source_id)
    if row is None:
        return None
    return Source.model_validate({name: getattr(row, name) for name in Source.model_fields})


# ---------------------------------------------------------------------------
# Raw records
# ---------------------------------------------------------------------------


def save_raw_record(session: Session, record: RawRecord) -> tuple[RawRecord, bool]:
    """Store a raw payload. Returns (stored record, created).

    If the same source already sent identical content (same sha256), nothing is stored
    and the existing record is returned with created=False.
    """
    values = record.model_dump()
    values["fetched_at"] = _utc(record.fetched_at)
    stmt = (
        insert(RawRecordRow)
        .values(**values)
        .on_conflict_do_nothing(constraint="uq_raw_records_source_sha256")
        .returning(RawRecordRow.raw_record_id)
    )
    created = session.execute(stmt).scalar_one_or_none() is not None
    row = session.execute(
        select(RawRecordRow).where(
            RawRecordRow.source_id == record.source_id, RawRecordRow.sha256 == record.sha256
        )
    ).scalar_one()
    return _raw_record_from_row(row), created


def latest_raw_record(session: Session, source_id: str, id_prefix: str = "") -> RawRecord | None:
    row = session.scalars(
        select(RawRecordRow)
        .where(
            RawRecordRow.source_id == source_id,
            RawRecordRow.raw_record_id.startswith(id_prefix),
        )
        .order_by(RawRecordRow.fetched_at.desc())
        .limit(1)
    ).first()
    return _raw_record_from_row(row) if row else None


def _raw_record_from_row(row: RawRecordRow) -> RawRecord:
    return RawRecord.model_validate({name: getattr(row, name) for name in RawRecord.model_fields})


# ---------------------------------------------------------------------------
# Places
# ---------------------------------------------------------------------------


def _point_ewkt(geo: GeoPoint) -> str:
    # WKT is (longitude latitude): x before y.
    return f"SRID=4326;POINT({geo.lon} {geo.lat})"


def save_place(session: Session, place: Place, seen_at: datetime | None = None) -> None:
    """Insert or update a place. `seen_at` records when an ingestion run saw it."""
    values: dict[str, Any] = place.model_dump(exclude={"geo"})
    values["geo"] = _point_ewkt(place.geo) if place.geo else None
    if seen_at is not None:
        values["last_seen_at"] = _utc(seen_at)
    stmt = insert(PlaceRow).values(**values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[PlaceRow.place_id],
        set_={k: stmt.excluded[k] for k in values if k != "place_id"} | {"updated_at": func.now()},
    )
    session.execute(stmt)


def _place_columns() -> list[Any]:
    as_geometry = cast(PlaceRow.geo, Geometry)
    return [
        PlaceRow.place_id,
        PlaceRow.name,
        PlaceRow.address,
        PlaceRow.district,
        PlaceRow.osm_id,
        PlaceRow.kind,
        PlaceRow.osm_tags,
        func.ST_Y(as_geometry).label("lat"),
        func.ST_X(as_geometry).label("lon"),
    ]


def _place_from_mapping(m: Any) -> Place:
    geo = GeoPoint(lat=m.lat, lon=m.lon) if m.lat is not None else None
    return Place(
        place_id=m.place_id,
        name=m.name,
        address=m.address,
        district=m.district,
        geo=geo,
        osm_id=m.osm_id,
        kind=m.kind,
        osm_tags=m.osm_tags,
    )


def get_place(session: Session, place_id: str) -> Place | None:
    m = session.execute(select(*_place_columns()).where(PlaceRow.place_id == place_id)).first()
    return _place_from_mapping(m) if m else None


def places_near(
    session: Session, point: GeoPoint, radius_m: float, kind: str | None = None
) -> list[tuple[Place, float]]:
    """Places within radius_m metres of point, nearest first, with their distance in metres."""
    here = func.ST_GeogFromText(_point_ewkt(point))
    distance = func.ST_Distance(PlaceRow.geo, here).label("distance_m")
    stmt = (
        select(*_place_columns(), distance)
        .where(func.ST_DWithin(PlaceRow.geo, here, radius_m))  # uses the GIST index
        .order_by(distance)
    )
    if kind is not None:
        stmt = stmt.where(PlaceRow.kind == kind)
    return [(_place_from_mapping(m), float(m.distance_m)) for m in session.execute(stmt)]


def count_places_not_seen_since(session: Session, seen_at: datetime) -> int:
    """OSM places the latest run did not see (closed, renamed, or retagged in OSM)."""
    return (
        session.scalar(
            select(func.count())
            .select_from(PlaceRow)
            .where(
                PlaceRow.osm_id.is_not(None),
                (PlaceRow.last_seen_at.is_(None)) | (PlaceRow.last_seen_at < _utc(seen_at)),
            )
        )
        or 0
    )


# ---------------------------------------------------------------------------
# Districts
# ---------------------------------------------------------------------------


def save_district(
    session: Session, number: int, name: str, osm_id: str, ways_wkt: list[str]
) -> None:
    """Store a district boundary, letting PostGIS assemble the polygon from its ways.

    ST_BuildArea turns a set of lines (outer and inner rings, in any order and split
    into any number of ways) into polygons with holes. If they don't close into an
    area, it returns NULL and we fail loudly instead of storing a broken boundary.
    """
    if not ways_wkt:
        raise ValueError(f"district {name}: no member ways")
    lines = [func.ST_GeomFromText(w, 4326) for w in ways_wkt]
    area = func.ST_Multi(func.ST_BuildArea(func.ST_Collect(array(lines))))
    geom = session.scalar(select(area))
    if geom is None:
        raise ValueError(f"district {name}: member ways do not close into an area")
    stmt = insert(DistrictRow).values(number=number, name=name, osm_id=osm_id, geom=geom)
    stmt = stmt.on_conflict_do_update(
        index_elements=[DistrictRow.number],
        set_={"name": name, "osm_id": osm_id, "geom": geom, "updated_at": func.now()},
    )
    session.execute(stmt)


def district_at(session: Session, point: GeoPoint) -> str | None:
    here = func.ST_GeomFromText(f"POINT({point.lon} {point.lat})", 4326)
    return session.scalar(
        select(DistrictRow.name).where(func.ST_Covers(DistrictRow.geom, here)).limit(1)
    )


def assign_districts(session: Session) -> int:
    """Set every located place's district from the boundaries. Returns how many got one.

    Location wins over any district name found in text. Does nothing if no boundaries
    are loaded yet, so a places run before a districts run does no harm.
    """
    if not session.scalar(select(func.count()).select_from(DistrictRow)):
        return 0
    containing = (
        select(DistrictRow.name)
        .where(func.ST_Covers(DistrictRow.geom, cast(PlaceRow.geo, Geometry)))
        .limit(1)
        .scalar_subquery()
    )
    session.execute(update(PlaceRow).where(PlaceRow.geo.is_not(None)).values(district=containing))
    return (
        session.scalar(
            select(func.count()).select_from(PlaceRow).where(PlaceRow.district.is_not(None))
        )
        or 0
    )


# ---------------------------------------------------------------------------
# Evidence (owned by the listing link or tag that uses it)
# ---------------------------------------------------------------------------


def _insert_evidence(session: Session, evidence: Evidence) -> int:
    values = evidence.model_dump()
    values["captured_at"] = _utc(evidence.captured_at)
    return session.execute(
        insert(EvidenceRow).values(**values).returning(EvidenceRow.evidence_id)
    ).scalar_one()


def _evidence_from_row(row: EvidenceRow) -> Evidence:
    return Evidence.model_validate({name: getattr(row, name) for name in Evidence.model_fields})


# ---------------------------------------------------------------------------
# Listings
# ---------------------------------------------------------------------------

_LISTING_COLUMNS = (
    "title",
    "place_id",
    "category",
    "language",
    "price_eur",
    "price_period",
    "come_alone",
    "beginner_friendly",
    "group_size",
    "first_timer_info",
    "organiser_contact",
    "status",
)


def save_listing(session: Session, listing: Listing) -> None:
    """Insert or replace a listing with its field evidence, tags and sources.

    Child rows are replaced, not merged: after saving, the database holds exactly what
    `listing` holds. Evidence rows that only the old version used are deleted.
    """
    values: dict[str, Any] = {name: getattr(listing, name) for name in _LISTING_COLUMNS}
    values["schedule"] = listing.schedule.model_dump(mode="json") if listing.schedule else None
    values["last_verified_at"] = (
        _utc(listing.last_verified_at) if listing.last_verified_at else None
    )
    stmt = insert(ListingRow).values(listing_id=listing.listing_id, **values)
    stmt = stmt.on_conflict_do_update(
        index_elements=[ListingRow.listing_id],
        set_={k: stmt.excluded[k] for k in values} | {"updated_at": func.now()},
    )
    session.execute(stmt)

    _delete_listing_children(session, listing.listing_id)

    for field, evidence in listing.field_evidence.items():
        session.add(
            ListingFieldEvidenceRow(
                listing_id=listing.listing_id,
                field=field,
                evidence_id=_insert_evidence(session, evidence),
            )
        )
    for tag in listing.tags:
        session.add(
            TagRow(
                listing_id=listing.listing_id,
                name=tag.name,
                evidence_id=_insert_evidence(session, tag.evidence),
            )
        )
    for source_id in listing.source_ids:
        session.add(ListingSourceRow(listing_id=listing.listing_id, source_id=source_id))
    session.flush()


def _delete_listing_children(session: Session, listing_id: str) -> None:
    old_evidence_ids = [
        *session.scalars(
            select(ListingFieldEvidenceRow.evidence_id).where(
                ListingFieldEvidenceRow.listing_id == listing_id
            )
        ),
        *session.scalars(select(TagRow.evidence_id).where(TagRow.listing_id == listing_id)),
    ]
    session.execute(
        delete(ListingFieldEvidenceRow).where(ListingFieldEvidenceRow.listing_id == listing_id)
    )
    session.execute(delete(TagRow).where(TagRow.listing_id == listing_id))
    session.execute(delete(ListingSourceRow).where(ListingSourceRow.listing_id == listing_id))
    if old_evidence_ids:
        session.execute(delete(EvidenceRow).where(EvidenceRow.evidence_id.in_(old_evidence_ids)))


def get_listing(session: Session, listing_id: str) -> Listing | None:
    row = session.get(ListingRow, listing_id)
    if row is None:
        return None

    field_evidence = {
        link_field: _evidence_from_row(ev)
        for link_field, ev in session.execute(
            select(ListingFieldEvidenceRow.field, EvidenceRow)
            .join(EvidenceRow, EvidenceRow.evidence_id == ListingFieldEvidenceRow.evidence_id)
            .where(ListingFieldEvidenceRow.listing_id == listing_id)
            .order_by(ListingFieldEvidenceRow.field)
        )
    }
    tags = [
        Tag(name=name, evidence=_evidence_from_row(ev))
        for name, ev in session.execute(
            select(TagRow.name, EvidenceRow)
            .join(EvidenceRow, EvidenceRow.evidence_id == TagRow.evidence_id)
            .where(TagRow.listing_id == listing_id)
            .order_by(TagRow.tag_id)
        )
    ]
    source_ids = list(
        session.scalars(
            select(ListingSourceRow.source_id)
            .where(ListingSourceRow.listing_id == listing_id)
            .order_by(ListingSourceRow.source_id)
        )
    )
    return Listing(
        listing_id=row.listing_id,
        **{name: getattr(row, name) for name in _LISTING_COLUMNS if name != "price_eur"},
        price_eur=float(row.price_eur) if row.price_eur is not None else None,
        schedule=Schedule.model_validate(row.schedule) if row.schedule else None,
        last_verified_at=row.last_verified_at,
        field_evidence=field_evidence,
        tags=tags,
        source_ids=source_ids,
    )


# ---------------------------------------------------------------------------
# Drafts
# ---------------------------------------------------------------------------


def save_draft(session: Session, draft: ListingDraft) -> int:
    """Queue an extraction result for curator review. Returns the draft_id."""
    return session.execute(
        insert(ListingDraftRow)
        .values(
            raw_record_id=draft.raw_record_id,
            source_id=draft.source_id,
            extracted_at=_utc(draft.extracted_at),
            draft=draft.model_dump(mode="json"),
            flags=list(draft.flags),
        )
        .returning(ListingDraftRow.draft_id)
    ).scalar_one()


def get_draft(session: Session, draft_id: int) -> ListingDraft | None:
    row = session.get(ListingDraftRow, draft_id)
    return ListingDraft.model_validate(row.draft) if row else None
