from __future__ import annotations

import pytest
from pydantic import ValidationError

from morehere.config import CityConfig, load_city_config


def test_munich_config_loads() -> None:
    config = load_city_config()
    assert config.city == "Munich"
    assert config.freshness_days == 60
    assert len(config.districts) == 25
    assert sorted(d.number for d in config.districts) == list(range(1, 26))


def test_alias_lookup_is_unambiguous_where_it_should_be() -> None:
    config = load_city_config()
    assert [d.name for d in config.districts_for("Westend")] == ["Schwanthalerhöhe"]
    assert [d.name for d in config.districts_for("haidhausen")] == ["Au-Haidhausen"]
    assert [d.name for d in config.districts_for("Maxvorstadt")] == ["Maxvorstadt"]


def test_ambiguous_aliases_return_every_candidate() -> None:
    config = load_city_config()
    assert len(config.districts_for("Giesing")) == 2
    assert len(config.districts_for("Schwabing")) == 2


def test_score_weights_must_sum_to_one() -> None:
    data = load_city_config().model_dump()
    data["score_weights"]["recurrence"] = 0.9
    with pytest.raises(ValidationError, match="sum to 1"):
        CityConfig.model_validate(data)
