"""AnalystAgent GeoFM tool tests."""

import pytest

from agents.analyst_agent.analyst_agent import AnalystAgent
from agents.analyst_agent.session_context import AnalystSession, clear_session, set_session
from agents.analyst_agent.tools import compare_with_geofm, get_geofm_run
from mcp_runtime.traced_client import TracedMcpClient
from pipeline.contracts import AnalysisRequest


class FakeGeoFmClient:
    """Capture traced calls and return a configured envelope."""

    def __init__(self, result):
        self.result = result
        self.calls = []

    async def call(self, tool, args):
        self.calls.append((tool, args))
        return self.result


@pytest.fixture(autouse=True)
def reset_session():
    clear_session()
    yield
    clear_session()


def _session() -> AnalystSession:
    return AnalystSession(
        session_id="turn-1",
        authenticated_user_id="tenant:user-1",
        bbox=(-111.35, 56.70, -111.34, 56.71),
        loaded_collections=["hls2-s30"],
        stac_items=[
            {
                "id": "epoch-b",
                "collection": "hls2-s30",
                "properties": {"datetime": "2024-07-15T00:00:00Z"},
            },
            {
                "id": "epoch-a",
                "collection": "hls2-s30",
                "properties": {"datetime": "2023-07-15T00:00:00Z"},
            },
        ],
    )


@pytest.mark.asyncio
async def test_given_loaded_hls_pair_when_submitting_then_earliest_and_latest_are_used(
    monkeypatch,
) -> None:
    # Arrange
    fake = FakeGeoFmClient(
        {
            "summary": "GeoFM run run-1 is queued.",
            "payload": {"run_id": "run-1", "status": "queued"},
            "evidence": [{"kind": "calculation", "identifier": "run-1"}],
        }
    )
    monkeypatch.setattr(
        TracedMcpClient,
        "from_geofm",
        classmethod(lambda cls, **kwargs: fake),
    )
    set_session(_session())

    # Act
    result = await compare_with_geofm()

    # Assert
    request = fake.calls[0][1]["request"]
    assert fake.calls[0][0] == "geofm_compare_epochs"
    assert request["item_id_epoch_a"] == "epoch-a"
    assert request["item_id_epoch_b"] == "epoch-b"
    assert request["requested_by"] == "tenant:user-1"
    assert result["structured"]["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_given_completed_run_when_polling_then_vector_visualization_is_returned(
    monkeypatch,
) -> None:
    # Arrange
    feature = {
        "type": "Feature",
        "geometry": {
            "type": "Polygon",
            "coordinates": [[[-111.35, 56.70], [-111.34, 56.70], [-111.35, 56.70]]],
        },
        "properties": {"area_km2": 1.2, "mean_distance": 0.7},
    }
    fake = FakeGeoFmClient(
        {
            "summary": "GeoFM run complete.",
            "payload": {
                "run_id": "run-1",
                "status": "complete",
                "statistics": {"threshold": 0.35},
                "features": [feature],
            },
            "evidence": [],
        }
    )
    monkeypatch.setattr(
        TracedMcpClient,
        "from_geofm",
        classmethod(lambda cls, **kwargs: fake),
    )
    set_session(_session())

    # Act
    result = await get_geofm_run("run-1")

    # Assert
    visualization = result["visualizations"][0]
    assert visualization["kind"] == "vector_layer"
    assert visualization["spec"]["data"]["features"] == [feature]
    assert fake.calls[0][1]["requested_by"] == "tenant:user-1"


@pytest.mark.asyncio
async def test_given_foundation_change_module_when_analyzing_then_registry_is_always_pinged(
    monkeypatch,
) -> None:
    # Arrange
    import agents.analyst_agent.tools as analyst_tools

    agent = AnalystAgent()
    calls = 0
    captured_request = None

    async def fake_list_geofm_models():
        nonlocal calls
        calls += 1
        return {"success": True, "models": [{"id": "planaura_hls"}]}

    async def fake_invoke(request, _invocation):
        nonlocal captured_request
        captured_request = request
        return "Foundation analysis ready.", [], []

    monkeypatch.setattr(analyst_tools, "list_geofm_models", fake_list_geofm_models)
    monkeypatch.setattr(agent, "_invoke_agent_service", fake_invoke)
    request = AnalysisRequest(
        question="Find contextual change in the loaded scenes",
        session_id="foundation-change-test",
        geoint_module="foundation_change",
    )

    # Act
    await agent.run(request)

    # Assert
    assert calls == 1
    assert captured_request.geofm_context == {
        "success": True,
        "models": [{"id": "planaura_hls"}],
    }