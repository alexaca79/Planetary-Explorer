"""AnalystAgent GeoFM tool tests."""

import pytest

from agents.analyst_agent.analyst_agent import AnalystAgent
from agents.analyst_agent.session_context import AnalystSession, clear_session, set_session
from agents.analyst_agent.tools import (
    _canonical_geofm_resource,
    compare_with_geofm,
    get_geofm_run,
)
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
def reset_session(monkeypatch):
    monkeypatch.setenv(
        "GEOFM_OWNER_SIGNING_KEY",
        "test-owner-signing-key-at-least-32-characters",
    )
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


def test_given_equivalent_geofm_values_when_canonicalized_then_proofs_are_stable() -> None:
    # Arrange
    raw = {
        "run_id": "00000000-0000-0000-0000-00000000000A",
        "threshold": 1,
        "geometry": {"coordinates": [[1, 2.5]]},
    }
    normalized = {
        "run_id": "00000000-0000-0000-0000-00000000000a",
        "threshold": 1.0,
        "geometry": {"coordinates": [[1.0, 2.5]]},
    }

    # Act & Assert
    assert _canonical_geofm_resource(raw) == _canonical_geofm_resource(normalized)


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
    assert len(fake.calls[0][1]["owner_signature"]) == 64
    assert len(fake.calls[0][1]["owner_signature_nonce"]) == 32
    assert fake.calls[0][1]["owner_signature_expires_at"] > 0
    assert result["structured"]["run_id"] == "run-1"


@pytest.mark.asyncio
async def test_given_reversed_explicit_hls_pair_when_submitting_then_order_is_normalized(
    monkeypatch,
) -> None:
    # Arrange
    fake = FakeGeoFmClient(
        {
            "summary": "GeoFM run run-1 is queued.",
            "payload": {"run_id": "run-1", "status": "queued"},
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
    result = await compare_with_geofm("epoch-b", "epoch-a")

    # Assert
    request = fake.calls[0][1]["request"]
    assert result["success"] is True
    assert request["item_id_epoch_a"] == "epoch-a"
    assert request["item_id_epoch_b"] == "epoch-b"


@pytest.mark.asyncio
async def test_given_untrusted_explicit_ids_when_submitting_then_loaded_pair_is_used(
    monkeypatch,
) -> None:
    # Arrange
    fake = FakeGeoFmClient(
        {
            "summary": "GeoFM run run-1 is queued.",
            "payload": {"run_id": "run-1", "status": "queued"},
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
    result = await compare_with_geofm("before", "after")

    # Assert
    request = fake.calls[0][1]["request"]
    assert result["success"] is True
    assert request["item_id_epoch_a"] == "epoch-a"
    assert request["item_id_epoch_b"] == "epoch-b"


@pytest.mark.asyncio
async def test_given_string_numeric_options_when_submitting_then_request_is_normalized(
    monkeypatch,
) -> None:
    # Arrange
    fake = FakeGeoFmClient(
        {
            "summary": "GeoFM run run-1 is queued.",
            "payload": {"run_id": "run-1", "status": "queued"},
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
    result = await compare_with_geofm(threshold="0.7", max_features="100")

    # Assert
    request = fake.calls[0][1]["request"]
    assert result["success"] is True
    assert request["threshold"] == 0.7
    assert request["max_features"] == 100


@pytest.mark.asyncio
async def test_given_fractional_feature_limit_when_submitting_then_request_is_rejected(
    monkeypatch,
) -> None:
    # Arrange
    fake = FakeGeoFmClient({})
    monkeypatch.setattr(
        TracedMcpClient,
        "from_geofm",
        classmethod(lambda cls, **kwargs: fake),
    )
    set_session(_session())

    # Act
    result = await compare_with_geofm(max_features="10.5")

    # Assert
    assert result["success"] is False
    assert "integer" in result["error"]
    assert fake.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize("datetime_value", [None, "2024-07-15T00:00:00Z"])
async def test_given_ambiguous_explicit_hls_pair_when_submitting_then_request_is_rejected(
    monkeypatch,
    datetime_value,
) -> None:
    # Arrange
    fake = FakeGeoFmClient({})
    monkeypatch.setattr(
        TracedMcpClient,
        "from_geofm",
        classmethod(lambda cls, **kwargs: fake),
    )
    session = _session()
    session.stac_items[0]["properties"]["datetime"] = datetime_value
    if datetime_value is not None:
        session.stac_items[1]["properties"]["datetime"] = datetime_value
    set_session(session)

    # Act
    result = await compare_with_geofm("epoch-a", "epoch-b")

    # Assert
    assert result["success"] is False
    assert "acquisition" in result["error"]
    assert fake.calls == []


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
    result = await get_geofm_run("00000000-0000-0000-0000-000000000001")

    # Assert
    visualization = result["visualizations"][0]
    assert visualization["kind"] == "vector_layer"
    assert visualization["spec"]["data"]["features"] == [feature]
    assert fake.calls[0][1]["requested_by"] == "tenant:user-1"
    assert len(fake.calls[0][1]["owner_signature"]) == 64
    assert len(fake.calls[0][1]["owner_signature_nonce"]) == 32


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