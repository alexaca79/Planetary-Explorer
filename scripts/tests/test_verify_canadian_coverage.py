"""Contracts for the read-only Canadian catalog coverage verifier."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

import pytest


SCRIPT = Path(__file__).resolve().parents[1] / "verify_canadian_coverage.py"
SPEC = importlib.util.spec_from_file_location("verify_canadian_coverage", SCRIPT)
assert SPEC and SPEC.loader
verifier = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = verifier
SPEC.loader.exec_module(verifier)


def test_given_empty_catalog_when_validating_then_no_data_is_distinct_from_failure() -> None:
    result = verifier.validate_response(
        {"type": "FeatureCollection", "features": []},
        "hls2-s30",
        (82.5018, -62.3481),
    )

    assert result == {"outcome": "no_data", "scene_id": None}
    assert verifier.validate_response({}, "hls2-s30", (82.5018, -62.3481))["outcome"] == "error"


@pytest.fixture
def scene() -> dict:
    return {
        "type": "FeatureCollection",
        "features": [{
            "type": "Feature",
            "id": "canadian-scene",
            "collection": "hls2-s30",
            "geometry": {
                "type": "Polygon",
                "coordinates": [[
                    [-123.2, 49.2], [-123.0, 49.2], [-123.0, 49.4],
                    [-123.2, 49.4], [-123.2, 49.2],
                ]],
            },
            "properties": {"datetime": "2026-07-15T10:00:00Z"},
            "assets": {"B04": {"href": "https://example.invalid/red.tif?secret=test"}},
        }],
    }


def test_given_matching_scene_when_validating_then_only_safe_provenance_is_retained(scene: dict) -> None:
    result = verifier.validate_response(
        scene, "hls2-s30", (49.2827, -123.1207), ("2026-06-01", "2026-08-26"),
    )

    assert result == {
        "outcome": "covered",
        "scene_id": "canadian-scene",
        "scene_start": "2026-07-15T10:00:00Z",
        "scene_end": "2026-07-15T10:00:00Z",
    }


def test_given_self_intersecting_footprint_when_validating_then_repair_is_disclosed(scene: dict) -> None:
    scene["features"][0]["geometry"]["coordinates"] = [
        [[0, 0], [2, 2], [0, 2], [2, 0], [0, 0]],
    ]

    result = verifier.validate_response(scene, "hls2-s30", (1.7, 1.0))

    assert result["outcome"] == "covered"
    assert result["warnings"] == ["Catalog footprint required geometry repair; source pixels remain unverified."]


@pytest.mark.parametrize(
    ("collection", "point", "dates"),
    [
        ("sentinel-1-rtc", (49.2827, -123.1207), None),
        ("hls2-s30", (63.7467, -68.5170), None),
        ("hls2-s30", (49.2827, -123.1207), ("2025-02-01", "2025-02-28")),
    ],
)
def test_given_mismatched_scene_when_validating_then_it_is_not_coverage(
    scene: dict, collection: str, point: tuple, dates: tuple | None,
) -> None:
    result = verifier.validate_response(scene, collection, point, dates)

    assert result["outcome"] == "error"


def test_given_no_live_flag_when_running_then_network_is_not_opened(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(sys, "argv", [str(SCRIPT)])

    def unexpected_client(*args, **kwargs):
        raise AssertionError("Live catalog checks must be opt-in.")

    monkeypatch.setattr(verifier.httpx, "AsyncClient", unexpected_client)

    assert verifier.main() == 0