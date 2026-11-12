"""Load and validate a city config such as config/munich.yaml."""

from __future__ import annotations

import math
from pathlib import Path

import yaml
from pydantic import BaseModel, ConfigDict, Field, model_validator


class _Strict(BaseModel):
    model_config = ConfigDict(extra="forbid")


class BBox(_Strict):
    south: float
    west: float
    north: float
    east: float

    @model_validator(mode="after")
    def _ordered(self) -> BBox:
        if not (self.south < self.north and self.west < self.east):
            raise ValueError("bbox must have south < north and west < east")
        return self


class District(_Strict):
    number: int = Field(ge=1)
    name: str
    aliases: list[str] = Field(default_factory=list)


class OsmTag(_Strict):
    key: str
    value: str


class CityConfig(_Strict):
    city: str
    country_code: str = Field(min_length=2, max_length=2)
    timezone: str
    bbox: BBox
    freshness_days: int = Field(gt=0)
    districts: list[District] = Field(min_length=1)
    score_weights: dict[str, float]
    osm_place_tags: list[OsmTag]

    @model_validator(mode="after")
    def _weights_sum_to_one(self) -> CityConfig:
        if not math.isclose(sum(self.score_weights.values()), 1.0, abs_tol=1e-9):
            raise ValueError("score_weights must sum to 1")
        return self

    def districts_for(self, name: str) -> list[District]:
        """All districts a name could mean. More than one result means: don't guess."""
        needle = name.strip().casefold()
        return [
            d
            for d in self.districts
            if needle == d.name.casefold() or needle in (a.casefold() for a in d.aliases)
        ]


DEFAULT_CONFIG_PATH = Path(__file__).resolve().parents[2] / "config" / "munich.yaml"


def load_city_config(path: Path = DEFAULT_CONFIG_PATH) -> CityConfig:
    with path.open(encoding="utf-8") as f:
        return CityConfig.model_validate(yaml.safe_load(f))
