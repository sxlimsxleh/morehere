"""FastAPI app. Run with `make api` (http://localhost:8000, docs at /docs).

Read-only and unauthenticated: it serves published, public information only. Auth and
rate limits come with deployment (milestone 12).
"""

# No `from __future__ import annotations` here: FastAPI reads these annotations at runtime,
# and the aliases (Cat, Filt, ...) defined inside create_app must not become strings.

import os
from collections.abc import Callable
from datetime import UTC, datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import Engine, text

from morehere.api import service
from morehere.api.schemas import FeedPage, Health, ListingDetail, MapCollection
from morehere.config import CityConfig, load_city_config
from morehere.db.session import make_engine
from morehere.models import Category, GeoPoint


def create_app(
    engine: Engine | None = None,
    config: CityConfig | None = None,
    clock: Callable[[], datetime] = lambda: datetime.now(UTC),
) -> FastAPI:
    """Build the app. Tests pass their own engine and a fixed clock."""
    engine = engine or make_engine()
    config = config or load_city_config()
    app = FastAPI(
        title="morehere. API",
        version="0.1.0",
        description="Recurring places in Munich where newcomers can become regulars. "
        "Every fact comes with the words it was taken from. Place data © OpenStreetMap "
        "contributors (ODbL).",
    )
    origins = os.environ.get("API_CORS_ORIGINS", "*").split(",")
    app.add_middleware(
        CORSMiddleware, allow_origins=origins, allow_methods=["GET"], allow_headers=["*"]
    )

    def catalogue() -> service.Catalogue:
        return service.load_catalogue(engine)

    def filters(
        category: Category | None = None,
        english: Annotated[bool, Query(description="Held in English or English + German")] = False,
        free: bool = False,
        district: str | None = None,
        when: Annotated[
            Literal["tonight", "weekend", "week"] | None,
            Query(description="Happens in this window"),
        ] = None,
    ) -> service.Filters:
        return service.Filters(
            category=category, english=english, free=free, district=district, when=when
        )

    def here(
        lat: Annotated[float | None, Query(ge=-90, le=90)] = None,
        lon: Annotated[float | None, Query(ge=-180, le=180)] = None,
    ) -> GeoPoint | None:
        if (lat is None) != (lon is None):
            raise HTTPException(422, "give both lat and lon, or neither")
        return GeoPoint(lat=lat, lon=lon) if lat is not None and lon is not None else None

    Cat = Annotated[service.Catalogue, Depends(catalogue)]
    Filt = Annotated[service.Filters, Depends(filters)]
    Here = Annotated[GeoPoint | None, Depends(here)]
    Limit = Annotated[int, Query(ge=1, le=100)]
    Offset = Annotated[int, Query(ge=0)]

    def page(cards: list, offset: int, limit: int) -> FeedPage:  # type: ignore[type-arg]
        return FeedPage(
            items=cards[offset : offset + limit], total=len(cards), offset=offset, limit=limit
        )

    @app.get("/listings", response_model=FeedPage, summary="The feed, best first")
    def list_listings(
        cat: Cat, f: Filt, at: Here, limit: Limit = 20, offset: Offset = 0
    ) -> FeedPage:
        return page(service.feed(cat, config, clock(), f, at), offset, limit)

    @app.get("/search", response_model=FeedPage, summary="Keyword search with the same filters")
    def search(
        q: Annotated[str, Query(min_length=2, max_length=100)],
        cat: Cat,
        f: Filt,
        at: Here,
        limit: Limit = 20,
        offset: Offset = 0,
    ) -> FeedPage:
        return page(service.feed(cat, config, clock(), f, at, query=q), offset, limit)

    @app.get("/listings/{listing_id}", response_model=ListingDetail)
    def get_listing(listing_id: str, cat: Cat) -> ListingDetail:
        item = next((i for i in cat.items if i.listing.listing_id == listing_id), None)
        if item is None:  # unknown, or not published: same answer, nothing leaks
            raise HTTPException(404, "listing not found")
        return service.detail(item, cat, config, clock())

    @app.get("/map", response_model=MapCollection, summary="GeoJSON of listings with coordinates")
    def map_view(cat: Cat, f: Filt) -> MapCollection:
        return service.map_collection(cat, config, clock(), f)

    @app.get("/health", response_model=Health)
    def health(cat: Cat) -> Health:
        with engine.connect() as conn:
            conn.execute(text("SELECT 1"))
        return Health(status="ok", published_listings=len(cat.items))

    return app


def __getattr__(name: str):  # type: ignore[no-untyped-def]
    # `uvicorn morehere.api.app:app` builds the real app lazily, so importing this module
    # (e.g. in tests or the OpenAPI export) doesn't connect to a database.
    if name == "app":
        return create_app()
    raise AttributeError(name)
