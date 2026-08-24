"""GeoFM-relevant request normalization tests."""

from pipeline.dispatch import _build_request


def test_given_frontend_map_bounds_when_building_request_then_bbox_is_normalized() -> None:
    # Act
    request = _build_request(
        {
            "query": "Use PlanAura",
            "session_id": "session-1",
            "map_bounds": {
                "west": -111.35,
                "south": 56.70,
                "east": -111.34,
                "north": 56.71,
                "center_lat": 56.705,
                "center_lng": -111.345,
            },
        }
    )

    # Assert
    assert request.bbox == (-111.35, 56.70, -111.34, 56.71)