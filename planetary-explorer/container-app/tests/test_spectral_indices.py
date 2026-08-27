"""Tests for deterministic temporal spectral-index sampling."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest

from agents.analyst_agent.session_context import AnalystSession, clear_session, set_session
from agents.raster_sampling_agent import spectral_indices
from agents.raster_sampling_agent.spectral_indices import (
    RasterSamplingError,
    SpectralIndexSample,
    normalize_temporal_window,
    rank_stac_candidates,
)


@pytest.fixture(autouse=True)
def reset_analyst_session():
    """Keep the Analyst ContextVar isolated between tests."""
    clear_session()
    yield
    clear_session()


def _sample(*, epoch: str, acquisition: str, value: float, item_id: str) -> SpectralIndexSample:
    return SpectralIndexSample(
        metric="nbr",
        value=value,
        mean=value,
        median=value,
        minimum=value - 0.1,
        maximum=value + 0.1,
        standard_deviation=0.03,
        valid_pixel_count=100,
        total_pixel_count=125,
        valid_pixel_fraction=0.8,
        requested_epoch=epoch,
        search_window="2026-01-01/2026-12-31",
        acquisition_datetime=acquisition,
        item_id=item_id,
        collection="sentinel-2-l2a",
        cloud_cover=5.0,
        nir_asset="B08",
        swir_asset="B12",
        mask_asset="SCL",
        item_url=f"https://example.test/{item_id}",
    )


def test_given_current_day_when_normalizing_epoch_then_searches_back_and_not_future() -> None:
    # Act
    window = normalize_temporal_window("2026-08-26", today=date(2026, 8, 26))

    # Assert
    assert window.stac_datetime == "2026-08-12/2026-08-26"


def test_given_candidates_when_ranking_then_prefers_covering_nearest_scene() -> None:
    # Arrange
    target = datetime(2026, 4, 1, tzinfo=UTC)
    outside_exact = {
        "id": "outside",
        "bbox": [10.0, 10.0, 11.0, 11.0],
        "properties": {"datetime": "2026-04-01T00:00:00Z", "eo:cloud_cover": 0},
    }
    inside_near = {
        "id": "inside",
        "bbox": [-123.0, 47.0, -122.0, 48.0],
        "properties": {"datetime": "2026-04-02T00:00:00Z", "eo:cloud_cover": 10},
    }

    # Act
    ranked = rank_stac_candidates(
        [outside_exact, inside_near],
        target=target,
        latitude=47.6,
        longitude=-122.3,
    )

    # Assert
    assert ranked[0]["id"] == "inside"


def test_given_first_scene_has_no_pixels_when_sampling_then_tries_next_scene(monkeypatch) -> None:
    # Arrange
    items = [
        {
            "id": "masked",
            "bbox": [-123.0, 47.0, -122.0, 48.0],
            "properties": {"datetime": "2026-04-01T00:00:00Z"},
        },
        {
            "id": "clear",
            "bbox": [-123.0, 47.0, -122.0, 48.0],
            "properties": {"datetime": "2026-04-02T00:00:00Z"},
        },
    ]
    monkeypatch.setattr(spectral_indices, "_search_stac_items", lambda *_args: items)

    def fake_sample(item, *, bbox, window):
        if item["id"] == "masked":
            raise RasterSamplingError("masked")
        return _sample(
            epoch=window.requested,
            acquisition="2026-04-02T00:00:00+00:00",
            value=0.4,
            item_id="clear",
        )

    monkeypatch.setattr(spectral_indices, "_sample_sentinel_2_nbr", fake_sample)

    # Act
    result = spectral_indices.sample_temporal_nbr(
        "sentinel-2-l2a",
        "2026-04-01",
        bbox=(-122.4, 47.5, -122.2, 47.7),
        today=date(2026, 8, 26),
    )

    # Assert
    assert result.item_id == "clear"


@pytest.mark.asyncio
async def test_given_nbr_question_when_comparing_then_returns_numeric_scene_results(monkeypatch) -> None:
    # Arrange
    from agents.analyst_agent.tools import compare_temporal

    samples = {
        "2026-04-01": _sample(
            epoch="2026-04-01",
            acquisition="2026-03-30T19:10:01+00:00",
            value=0.2,
            item_id="before",
        ),
        "2026-08-26": _sample(
            epoch="2026-08-26",
            acquisition="2026-08-24T18:59:11+00:00",
            value=0.1,
            item_id="after",
        ),
    }
    monkeypatch.setattr(
        spectral_indices,
        "sample_temporal_nbr",
        lambda _collection, when, *, bbox: samples[when],
    )
    set_session(
        AnalystSession(
            question="Calculate extent-wide NBR change for both epochs",
            session_id="nbr-test",
            bbox=(-122.4, 47.5, -122.2, 47.7),
            loaded_collections=["sentinel-2-l2a"],
        )
    )

    # Act
    result = await compare_temporal(
        "sentinel-2-l2a",
        "2026-04-01",
        "2026-08-26",
    )

    # Assert
    assert result["success"] is True
    assert result["t1_value"] == pytest.approx(0.2)
    assert result["t2_value"] == pytest.approx(0.1)
    assert result["delta"] == pytest.approx(-0.1)
    assert result["dnbr"] == pytest.approx(0.1)