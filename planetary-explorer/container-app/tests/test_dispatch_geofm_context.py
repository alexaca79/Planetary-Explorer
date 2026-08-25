"""GeoFM-relevant request normalization tests."""

import pytest

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


@pytest.mark.asyncio
async def test_given_foundation_change_module_when_dispatching_then_analysis_is_forced(
    monkeypatch,
) -> None:
    # Arrange
    import pipeline.dispatch as dispatch_module
    import pipeline.layer1_agents as layer1_module

    class UnexpectedRouter:
        async def route(self, **_kwargs):
            raise AssertionError("Foundation Change must bypass ActionRouter")

    class CapturingSpecialist:
        def __init__(self) -> None:
            self.decision = None

        async def run(self, decision, _request, _body):
            self.decision = decision
            return {"action": decision.action, "elapsed_ms": 0}

    specialist = CapturingSpecialist()

    class FakeAgents:
        def for_action(self, action):
            assert action == "ANALYZE"
            return specialist

    monkeypatch.setattr(
        dispatch_module,
        "build_default_pipeline",
        lambda: (UnexpectedRouter(), None, None, None),
    )
    monkeypatch.setattr(
        layer1_module,
        "build_layer1_agents",
        lambda **_kwargs: FakeAgents(),
    )

    # Act
    result = await dispatch_module.run_pipeline_v2(
        {
            "query": "Load HLS imagery and find contextual change",
            "session_id": "foundation-change-dispatch",
            "geoint_module": "foundation_change",
        }
    )

    # Assert
    assert result["action"] == "ANALYZE"
    assert specialist.decision.reasoning == "foundation_change_module"